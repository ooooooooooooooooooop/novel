#!/usr/bin/env python3
"""reader_short_form — 读者体验审查 CLI 入口.

从已有章节正文评估读者体验质量，产出 7 维分级标注报告：
  1. 量化代理分析（纯代码，无需 LLM）
  2. LLM 质性分级标注（response-file 循环）
  3. 合并 → reader_report.json（route=none，不阻断）

用法:
    python src/reader_short_form.py <input.txt> --output-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.workflow_action.reader_experience import ReaderExperienceUnit
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


def main() -> int:
    parser = argparse.ArgumentParser(description="从章节正文做读者体验分级标注")
    parser.add_argument("input_file", nargs="?", default="input.txt", help="章节正文路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--style",
        default="",
        help="引用风格库中的已有档案 <name>（辅助判断情绪落地/场景现场感）",
    )
    parser.add_argument(
        "--chapter-id",
        default="",
        help="章节标识（如 chapter_1），默认取输入文件名的 stem",
    )
    parser.add_argument(
        "--expectations-from",
        default="",
        help="ForeshadowGraph JSON 路径（可选）；提供则从活跃伏笔派生读者预期台账，"
        "写入 reader_expectations.json",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    text_path = Path(args.input_file)
    if not text_path.exists():
        print(f"Error: Input file not found: {text_path}")
        return 1
    text = _read_text(text_path)
    chapter_id = args.chapter_id or text_path.stem

    # hash check（对齐 style/compliance 的 input 校验）
    hash_path = output_dir / ".input_hash"
    current_hash = file_content_hash(text_path)
    hash_errors = validate_run_hash(
        hash_path=hash_path,
        current_hash=current_hash,
        output_dir=output_dir,
        label="input file",
    )
    if hash_errors:
        for error in hash_errors:
            print(error)
        return 1

    unit = ReaderExperienceUnit()
    prompt_path = output_dir / "reader_prompt.txt"
    response_path = output_dir / "reader_response.txt"
    report_path = output_dir / "reader_report.json"

    if not response_path.exists():
        # load_style_context 内部取 output_dir.parent / "style" → 传本单元 output_dir
        #（<book>/output/reader_experience → <book>/output/style/style_profile.json）
        style_context = load_style_context(output_dir, style_name=args.style or None)
        prompt = unit.build_prompt(
            prose_text=text,
            chapter_id=chapter_id,
            style_context=style_context,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\n[STEP: READER] Prompt saved: {prompt_path}")
        print(f"[WAITING] Generate response to: {response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    # parse + merge
    response = _read_response_text(response_path)
    qualitative = unit.parse_response(response)
    report = unit.merge(
        qualitative,
        review_target=str(text_path),
        chapter_id=chapter_id,
    )
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {report_path}")
    print(f"Overall: {report.overall}")
    for dim in report.dimensions:
        print(f"  [{dim.grade}] {dim.dimension} {dim.name}: {dim.diagnosis}")
        if dim.fix_direction:
            print(f"      改法: {dim.fix_direction}")
    print("Route: none (不阻断，供人工/精修参考)")

    # 读者预期台账：从 ForeshadowGraph 派生读者视角的等待清单（可选）
    if args.expectations_from:
        from src.object_state.foreshadowgraph import ForeshadowGraph
        from src.object_state.readerexpectation import derive_reader_expectations

        fg_path = Path(args.expectations_from)
        if not fg_path.exists():
            print(f"Warning: expectations-from not found: {fg_path}")
            return 0
        package = json.loads(fg_path.read_text(encoding="utf-8"))
        fg_data = (
            package.get("stable_memory", {}).get("ForeshadowGraph", [])
            if isinstance(package, dict)
            else package
        )
        if not fg_data:
            print("Warning: ForeshadowGraph empty in expectations-from source")
            return 0
        fg = ForeshadowGraph.model_validate(fg_data[0])
        # 当前 PlotUnit 总数：从该章的 compose/extend 产物估算（供逾期判定）
        ledger = derive_reader_expectations(fg, current_plotunit_count=2)
        exp_path = output_dir / "reader_expectations.json"
        exp_path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nSaved: {exp_path}")
        print(f"读者预期 {len(ledger.expectations)} 条")
        for exp in ledger.top_questions(limit=5):
            print(f"  [{exp.importance}/{exp.status}] {exp.reader_question}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
