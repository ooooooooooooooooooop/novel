"""hindsight_short_form — Hindsight Reconciliation CLI 执行脚本 (R5 整改).

两遍式：
1. 收集开放性 ChoiceRecord，生成 output/hindsight/hindsight_prompt.txt
2. operator/Judge 填响应后，重跑本脚本回填 ChoiceRecord 的真实后果与回看判定
3. 自动更新并持久化 author_model_v3.json（支撑样本与反例证据）与 AuthorKernel
"""

import argparse
import sys
from pathlib import Path

from src.workflow_action.authormodel_v3 import (
    load_author_model_v3,
    save_author_model_v3,
    update_author_model_from_hindsight,
)
from src.object_state.authormodel_v3 import AuthorModelV3
from src.workflow_action.choiceledger import load_choice_ledger
from src.workflow_action.hindsight import reconcile_hindsight


def main() -> int:
    parser = argparse.ArgumentParser(description="Hindsight Reconciliation 执行器")
    parser.add_argument("--output-dir", required=True, type=Path, help="输出目录 (output/extend 或 output/compose)")
    parser.add_argument("--chapters-dir", required=True, type=Path, help="章节目录 (chapters/)")
    parser.add_argument("--lag", type=int, default=2, help="滞后几章才算证据（默认 2）")
    parser.add_argument("--response", type=Path, default=None, help="显式指定 hindsight_response.txt 路径")

    args = parser.parse_args()
    output_dir = args.output_dir
    chapters_dir = args.chapters_dir

    result = reconcile_hindsight(
        output_dir,
        chapters_dir,
        lag=args.lag,
        response_path=args.response,
    )

    status = result.get("status")
    if status == "noop":
        print("Hindsight: 无待回看的开放性选择（证据尚未累积达到 lag 要求或已全部回填）")
        return 0
    elif status == "prompt":
        print(f"Hindsight: 已生成回看提示词 -> {result.get('prompt_path')}")
        print(f"  待回看选择数: {result.get('n_open')} 条")
        print("  请将审阅结果写入 hindsight_response.txt 后重新运行 novel hindsight")
        return 0
    elif status == "done":
        updated = result.get("updated", 0)
        print(f"Hindsight: 成功回填 {updated} 条真实选择后果与回看判定")

        # R5: 将回填的 ChoiceRecord 同步更新至 AuthorModelV3 与持久化
        ledger = load_choice_ledger(output_dir)
        work_name = output_dir.parent.parent.name if output_dir.parent.name == "output" else "default_work"

        author_model = load_author_model_v3(output_dir) or load_author_model_v3(output_dir.parent) or AuthorModelV3(
            author_id=f"author_{work_name}",
            author_name=work_name,
        )

        n_p_updated = update_author_model_from_hindsight(author_model, ledger.choices, work_name)
        saved_path = save_author_model_v3(output_dir, author_model)
        # 同时保存至作品级目录供跨模式共享
        save_author_model_v3(output_dir.parent, author_model)
        print(f"AuthorModelV3: 已更新 {n_p_updated} 条原则支撑/反例证据 -> {saved_path}")
        return 0
    else:
        print(f"Hindsight: 未知执行状态 {status}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
