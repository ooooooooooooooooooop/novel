#!/usr/bin/env python3
"""rubric_short_form — WebNovelBench 8 维本地评测 rubric 导出 CLI 入口.

纯代码单遍导出（无需 LLM，无输入文件），对齐 compliance_short_form 骨架：
  - rubric 是静态领域知识导出（无 input 文件、无 .input_hash 版本校验）
  - 输出 novels/<小说>/output/rubric/rubric.json
  - 离线：不触碰网络/provider，纯 stdlib

用法:
    python src/rubric_short_form.py --output-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain_layer.review_rubric import render_rubric_json
from src.workflow_action.timebook import resolve_time_dir


def _load_timeline_report(output_dir: Path):
    """加载时间域 timeline_report.json（若有）→ rubric 挂载时间一致性维."""
    time_dir = resolve_time_dir(output_dir)
    path = time_dir / "timeline_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 WebNovelBench 8 维本地评测 rubric")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timeline_report = _load_timeline_report(output_dir)
    report_path = output_dir / "rubric.json"
    report_path.write_text(
        render_rubric_json(timeline_report),
        encoding="utf-8",
    )

    n_dims = 9 if timeline_report is not None else 8
    print(f"Saved: {report_path}")
    print(f"Rubric: WebNovelBench {n_dims} 维本地评测 (离线, arXiv:2505.14818)")
    if timeline_report is not None:
        print(f"  时间一致性维 (wnb_09) 已挂载：依据 {resolve_time_dir(output_dir) / 'timeline_report.json'}")
    print("Signal strength: strong=2 (角色一致性/跨场景衔接), moderate=2 (意境/语境), weak=1 (修辞负向代理), none=3 (LLM-judge)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
