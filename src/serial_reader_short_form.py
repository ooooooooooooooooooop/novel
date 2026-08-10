#!/usr/bin/env python3
"""serial_reader_short_form — 连续章/窗口读者审查 CLI 入口.

从连续 N 章（含最后一章）评估相邻章 + 窗口读者质量，产出
serial_reader_report.json（route=none，不阻断，供 ReaderQualityGatePolicy 消费）：
  1. 确定性预分析（纯代码，复用 prose_evidence/prose_reconcile）
  2. LLM 质性分级标注（response-file [WAITING] 循环）——12 维，needs_work/weak 才入 findings
  3. 合并 → SerialReaderReport

用法:
    python src/serial_reader_short_form.py --last-chapter <最后章.txt> --window 3 \\
        --chapters-dir <chapters/> --output-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.workflow_action.serial_reader import SerialReaderUnit, load_serial_report
from src.workflow_action.style import load_style_context


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def _read_response_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _chapter_num(path: Path) -> int:
    try:
        return int(path.stem[len("chapter_"):])
    except (ValueError, IndexError):
        return 1 << 30


def _collect_window(
    chapters_dir: Path, last_path: Path, window: int
) -> tuple[list[str], list[str]]:
    """从 chapters_dir 取「以 last_path 结尾」的连续 window 章正文与标识.

    返回 (chapters, chapter_refs)（从旧到新）。不足 window 时取到开头；
    无前章（仅 1 章）时报错（window>1 需要至少相邻两章）。
    """
    last_num = _chapter_num(last_path)
    all_files = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    # 找到 last_path 在目录中的位置（按编号）
    positions = [i for i, p in enumerate(all_files) if _chapter_num(p) == last_num]
    if not positions:
        # last 章不在 chapters_dir：退回读目录最后一个连续段
        positions = [len(all_files) - 1]
    end = positions[-1]
    start = max(0, end - window + 1)
    picked = all_files[start:end + 1]
    chapters = [_read_text(p) for p in picked]
    refs = [p.stem for p in picked]
    if len(chapters) < 2:
        raise ValueError(
            f"window={window} 需要至少相邻两章，chapters_dir 仅提供 "
            f"{len(chapters)} 章（{chapters_dir}）"
        )
    return chapters, refs


def main() -> int:
    parser = argparse.ArgumentParser(description="连续章/窗口读者审查")
    parser.add_argument(
        "--last-chapter", required=True, help="最后（审查目标）章节正文路径"
    )
    parser.add_argument(
        "--window", type=int, default=3, choices=[3, 5],
        help="窗口大小（3 或 5，含最后一章）",
    )
    parser.add_argument(
        "--chapters-dir", default="", help="chapters 目录（含前章），缺省取 last-chapter 的父目录"
    )
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--style", default="", help="引用风格库档案 <name>（辅助判断）"
    )
    parser.add_argument(
        "--expectations-from", default="",
        help="ForeshadowGraph JSON 路径（可选）；派生读者预期台账注入",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    last_path = Path(args.last_chapter)
    if not last_path.exists():
        print(f"Error: last chapter not found: {last_path}")
        return 1
    chapters_dir = Path(args.chapters_dir) if args.chapters_dir else last_path.parent

    # hash check（对齐单章 reader）
    hash_path = output_dir / ".input_hash"
    current_hash = file_content_hash(last_path)
    hash_errors = validate_run_hash(
        hash_path=hash_path,
        current_hash=current_hash,
        output_dir=output_dir,
        label="last chapter input",
    )
    if hash_errors:
        for error in hash_errors:
            print(error)
        return 1

    try:
        chapters, refs = _collect_window(chapters_dir, last_path, args.window)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    unit = SerialReaderUnit()
    prompt_path = output_dir / "serial_reader_prompt.txt"
    response_path = output_dir / "serial_reader_response.txt"
    report_path = output_dir / "serial_reader_report.json"

    # 读者预期台账（可选，供窗口「ReaderExpectation 是否推进」判断）
    expectation_context = ""
    if args.expectations_from:
        from src.object_state.foreshadowgraph import ForeshadowGraph
        from src.object_state.readerexpectation import derive_reader_expectations

        fg_path = Path(args.expectations_from)
        if fg_path.exists():
            package = json.loads(fg_path.read_text(encoding="utf-8"))
            fg_data = (
                package.get("stable_memory", {}).get("ForeshadowGraph", [])
                if isinstance(package, dict)
                else package
            )
            if fg_data:
                fg = ForeshadowGraph.model_validate(fg_data[0])
                ledger = derive_reader_expectations(
                    fg, current_plotunit_count=2
                )
                expectation_context = ledger.to_prompt_context()

    if not response_path.exists():
        style_context = load_style_context(output_dir, style_name=args.style or None)
        prompt = unit.build_prompt(
            chapters,
            window=args.window,
            chapter_refs=refs,
            review_target=last_path.stem,
            reader_contract_context=_load_contract_context(output_dir),
            reader_expectation_context=expectation_context,
        )
        # style 上下文附在 prompt 末尾（辅助情绪/节奏判断）
        if style_context:
            prompt += "\n\n【写作风格画像】\n" + style_context
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\n[STEP: SERIAL READER] Prompt saved: {prompt_path}")
        print(f"[WAITING] Generate response to: {response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    response = _read_response_text(response_path)
    qualitative = unit.parse_response(response)
    report = unit.merge(
        qualitative,
        window=args.window,
        review_target=last_path.stem,
        chapter_refs=refs,
    )
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {report_path}")
    print(f"Window: {args.window} ({' → '.join(refs)})")
    print(f"Overall: {report.overall}")
    for f in report.findings:
        print(
            f"  [{f.grade}/{f.severity}] {f.dimension} {f.dimension}: "
            f"{f.diagnosis}"
        )
        if f.fix_direction:
            print(f"      改法: {f.fix_direction}")
    print("Route: none (报告供 ReaderQualityGatePolicy 消费，不自封阻断)")
    return 0


def _load_contract_context(output_dir: Path) -> str:
    """读取 ReaderContract 上下文（output/<mode>/reader_contract.json 或同级）."""
    for name in ("reader_contract.json",):
        for base in (output_dir, output_dir.parent):
            p = base / name
            if p.exists():
                try:
                    from src.object_state.readercontract import ReaderContract

                    return ReaderContract.model_validate_json(
                        p.read_text(encoding="utf-8")
                    ).to_prompt_context()
                except Exception:
                    return ""
    return ""


if __name__ == "__main__":
    sys.exit(main())
