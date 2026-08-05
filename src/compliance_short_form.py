#!/usr/bin/env python3
"""compliance_short_form — 内容合规模块 CLI 入口.

纯代码单遍扫描（无需 LLM），对齐 style_short_form 骨架：
  1. hash check（输入变化时拒绝重跑）
  2. prose 模式：扫敏感词 + 平台政策检查
  3. 产出 compliance_report.json

用法:
    python src/compliance_short_form.py <input.txt> --output-dir <dir>
        [--platform 通用] [--sensitive on|off] [--nsfw on|off] [--lexicon FILE]
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.domain_layer.compliance_rules import get_platform_names
from src.workflow_action.compliance import ComplianceUnit


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def _load_custom_lexicon(path: Path) -> list:
    """加载自定义词库 JSON（--lexicon FILE）.

    格式: {"entries": [{"word": "...", "category": "...", "severity": "...", "note": "..."}]}
    或直接是列表。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "entries" in data:
        return data["entries"]
    raise ValueError(
        "自定义词库格式错误: 应为 {\"entries\": [...]} 或直接是列表"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="内容合规模块：扫敏感词 + 平台政策")
    parser.add_argument("input_file", nargs="?", default="input.txt", help="输入文本路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--platform",
        default="通用",
        help=f"目标平台（默认 通用；可用: {', '.join(get_platform_names())}）",
    )
    parser.add_argument(
        "--sensitive",
        default="on",
        choices=["on", "off"],
        help="敏感词扫描开关（默认 on；off 时跳过词库扫描，平台政策检查仍跑）",
    )
    parser.add_argument(
        "--nsfw",
        default="off",
        choices=["on", "off"],
        help="成人向（NSFW）开关（默认 off 正常向：扫描涉黄分类；on：跳过涉黄分类，其余分类仍扫）",
    )
    parser.add_argument(
        "--lexicon",
        default="",
        help="自定义词库 JSON 文件路径（与内置词库合并）",
    )
    args = parser.parse_args()

    text_path = Path(args.input_file)
    if not text_path.exists():
        print(f"Error: Input file not found: {text_path}")
        return 1
    text = _read_text(text_path)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 0: hash check
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

    # Step 1: load custom lexicon (optional)
    custom_entries: list | None = None
    if args.lexicon:
        custom_entries = _load_custom_lexicon(Path(args.lexicon))
        print(f"Loaded custom lexicon: {args.lexicon} ({len(custom_entries)} entries)")

    # Step 2: scan (pure code)
    sensitive_on = args.sensitive == "on"
    nsfw_on = args.nsfw == "on"
    unit = ComplianceUnit()
    report = unit.scan_prose(
        text,
        platform=args.platform,
        sensitive_on=sensitive_on,
        nsfw_on=nsfw_on,
        custom_entries=custom_entries,
        source_text_ref=str(text_path),
    )

    print(f"\n{'=' * 50}")
    print(
        f"Compliance Scan | platform={args.platform} | sensitive={args.sensitive} "
        f"| nsfw={args.nsfw}"
    )
    print(f"{'=' * 50}")
    print(f"风险等级: {report.risk_level()} | 命中: {len(report.hits)} | 政策 issue: {len(report.issues)}")
    if report.hits:
        for hit in report.hits:
            print(
                f"  [{hit.severity}] {hit.category}: '{hit.word}' "
                f"@line {hit.line_number} …{hit.snippet}…"
            )
    else:
        print("敏感词命中: 无")
    if report.issues:
        for issue in report.issues:
            print(f"  [policy:{issue.severity}] {issue.violated_rule}: {issue.description}")

    # Step 3: save report
    report_path = output_dir / "compliance_report.json"
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
