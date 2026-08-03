#!/usr/bin/env python3
"""time_short_form — 时间域模块 CLI 入口（横向域，跨 audit/extend/compose 消费）.

纯代码单遍（无需 LLM），对齐 compliance_short_form 骨架：
  --rebuild  从正文提取章节时间锚，校准既有 TimeBook（无 TimeBook 时零成本）
  --check    运行 FACTTRACK v2 时间审计，产出 timeline_report.json（一等产物）
  --status   打印 TimeBook 当前状态（不产生文件）

用法:
    python src/time_short_form.py --output-dir <dir> [--status]
    python src/time_short_form.py --input <text.txt> --output-dir <dir> --rebuild
    python src/time_short_form.py --output-dir <dir> --check
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state import TimeBook
from src.workflow_action.time_audit import build_timeline_report
from src.workflow_action.timebook import (
    extract_time_anchors,
    load_time_book,
    refresh_time_book_anchors,
    resolve_time_dir,
    save_time_book,
)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def _load_objects(output_dir: Path) -> list:
    """尝试从相邻模式工作区加载对象层（audit/extend rebuild package）.

    无 package 时返回空列表 → baseline-3 与先知检测自然跳过，
    仅 time_book 驱动的检测运行（零成本契约）。
    """
    parent = output_dir.parent
    candidates = [
        parent / "rebuild_package.json",
        parent / "extend_rebuild_package.json",
    ]
    serializer = SerializationBoundaryUnit()
    for path in candidates:
        if path.exists():
            try:
                package = serializer.load(path)
                return serializer.deserialize_package(package)
            except Exception:
                continue
    return []


def _print_status(tb, *, time_dir: Path) -> None:
    print(f"TimeBook: {time_dir / 'time_book.json'}")
    if tb is None:
        print("  状态: 不存在（零成本降级；所有时间注入/检测关闭）")
        return
    latest = tb.latest_anchor()
    print(f"  状态: 存在 (schema_version={tb.schema_version})")
    if tb.initial is not None and not tb.initial.is_empty():
        bits = " ".join(
            b for b in (tb.initial.date, tb.initial.lunar, tb.initial.loc) if b
        )
        print(f"  起点: {bits}")
    else:
        print("  起点: (未设定)")
    print(f"  锚点: {len(tb.anchors)} 个章节时间锚")
    if latest is not None:
        bits = " ".join(
            b for b in (latest.chapter, latest.date, latest.lunar, latest.tod, latest.loc) if b
        )
        print(f"  最新: {bits}")
    print(f"  时代背景: {len(tb.era)} 个年份条目")
    print(f"  时间线: {len(tb.timelines)} 条")
    print(f"  时间规则: {len(tb.rules)} 条")


def main() -> int:
    parser = argparse.ArgumentParser(description="时间域模块：TimeBook 管理 + 时间审计")
    parser.add_argument("--input", default="", help="输入文本路径（--rebuild 用）")
    parser.add_argument("--output-dir", default="output", help="输出目录（时间域 home = output/time）")
    parser.add_argument("--rebuild", action="store_true", help="从正文提取锚点并校准 TimeBook")
    parser.add_argument("--check", action="store_true", help="运行时间审计，产出 timeline_report.json")
    parser.add_argument("--status", action="store_true", help="打印 TimeBook 当前状态（默认动作）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    time_dir = resolve_time_dir(output_dir)
    time_dir.mkdir(parents=True, exist_ok=True)

    # 默认动作：status（不产生文件）
    do_status = args.status or not (args.rebuild or args.check)
    do_rebuild = args.rebuild
    do_check = args.check

    # Step 1: rebuild（可选）——提取锚点校准/建立 TimeBook
    if do_rebuild:
        if not args.input:
            print("Error: --rebuild requires --input <text.txt>")
            return 1
        text_path = Path(args.input)
        if not text_path.exists():
            print(f"Error: Input file not found: {text_path}")
            return 1
        from src.boundary_control.chunking import split_by_chapters

        text = _read_text(text_path)
        chunks = split_by_chapters(text)
        extracted = extract_time_anchors(chunks)
        print(f"提取章节时间锚: {len(extracted)} 个（共 {len(chunks)} 章）")
        tb = load_time_book(output_dir)
        if tb is None:
            # 显式管理命令：从既有文本建立 TimeBook（与 audit/extend 的零成本自动挂钩不同）
            if not extracted:
                print("  TimeBook 不存在且无可提取锚 → 未产生任何文件（零成本契约）")
            else:
                tb = TimeBook(anchors=[a for a in extracted])
                save_time_book(output_dir, tb)
                print(f"  TimeBook 已建立: {time_dir / 'time_book.json'} ({len(tb.anchors)} 锚)")
        else:
            refresh_time_book_anchors(output_dir, chunks)
            tb = load_time_book(output_dir)
            print(f"  TimeBook 已校准: {time_dir / 'time_book.json'}")

    # Step 2: check（可选）——时间审计产出 timeline_report.json
    if do_check:
        tb = load_time_book(output_dir)
        objects = _load_objects(output_dir)
        report = build_timeline_report(
            objects,
            tb,
            source_text_ref=str(Path(args.input)) if args.input else "",
            extracted_anchors=extract_time_anchors(
                split_by_chapters(_read_text(Path(args.input)))
            )
            if args.input and Path(args.input).exists()
            else None,
        )
        report_path = time_dir / "timeline_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n时间审计: {report['issue_count']} 项 issue "
              f"({report['blocking_count']} blocking) | route={report['route']}")
        for i in report["issues"]:
            print(f"  [{i['severity']}] {i['issue_id']}: {i['description']}")
        print(f"Saved: {report_path}")

    # Step 3: status（默认 / 显式）
    if do_status:
        tb = load_time_book(output_dir)
        _print_status(tb, time_dir=time_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
