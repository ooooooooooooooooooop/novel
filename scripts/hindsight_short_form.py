#!/usr/bin/env python3
"""hindsight_short_form — Hindsight Reconciliation（作者性 §11-12 闭环回填）.

用法:
    python scripts/hindsight_short_form.py --output-dir <extend|compose> --chapters-dir <chapters>

两遍式（对齐 review/reader）：第一遍生成 output/hindsight/hindsight_prompt.txt 后
退出（[WAITING]）；operator/独立 Judge 填 output/hindsight/hindsight_response.txt
后重跑 → 解析并回填 ChoiceLedger 的 consequence/hindsight → 触发下次 Consolidation。

证据纪律：prompt 只含「当初选了什么 + 之后真实提交的章节正文」，judge 必须从
证据里读实际后果（禁止决策时刻即时自我解释）。空台账 / 无开放性选择时 no-op。
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow_action.hindsight import reconcile_hindsight


def main() -> int:
    parser = argparse.ArgumentParser(description="Hindsight Reconciliation")
    parser.add_argument("--output-dir", required=True, help="工作区 output/<mode> 目录")
    parser.add_argument("--chapters-dir", required=True, help="章节正文目录")
    parser.add_argument(
        "--lag",
        type=int,
        default=2,
        help="滞后几章才算有证据（默认 2，防即时自我解释）",
    )
    args = parser.parse_args()

    result = reconcile_hindsight(
        Path(args.output_dir),
        Path(args.chapters_dir),
        lag=args.lag,
    )
    status = result["status"]
    if status == "noop":
        print("Hindsight: no open choices (无滞后/无证据)，no-op")
        return 0
    if status == "prompt":
        print(f"[STEP: HINDSIGHT] Prompt saved: {result['prompt_path']}")
        print(f"[WAITING] Generate response to: "
              f"{result['prompt_path'].with_name('hindsight_response.txt')}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    if status == "done":
        print(f"Hindsight: 回填 {result['updated']} 条选择（consequence + hindsight）")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
