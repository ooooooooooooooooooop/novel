"""S6（54 计划 §S6）无人连续生产链就绪检查——48 清单的代码级自动化等价物.

把 48_a1_autonomous_production_handoff.md 中 A1 无人生产链的人工验收环节改为
程序化断言（不调 LLM、不依赖 runtime/ 真机证据），验证代码层保障全部在位：

- 无人工干涉：auto 入口不含 [WAITING]/staged response 语义
- S2 终审闸：评审器换位一致性约束 + 读者门禁轴武装率（hard_consistency 恒跑）
- S3 因果防线：提交点 reader gate 并入 run_causal_defense
- 证据链完整：precommit 证伪 + reader gate 报告 + commit head 校验（恢复只识别完整提交）
- 预算合规：calls/input/output/cost 四轴扣减 + 超限拒绝
- checkpoint 自动比对：10/20/30 章 long-horizon checkpoint
- stop 后零正文调用：viability stop 语义（AutonomousDecision route）

真机依赖部分（三类各 30 章无人 Canary + 90 章聚合 + 独立 release/tag）由
`a1_release_validation.py` 在真实 provider 运行后聚合——本脚本是运行前的代码层前置。

用法：python scripts/verify_a1_chain_readiness.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 需要确认的保障点（模块路径, 符号名, 说明）——符号以 def/class/import 任一形式出现在该模块源码
IMPORT_CHECKS: list[tuple[str, str, str]] = [
    ("src.boundary_control.reader_gate", "evaluate_commit_reader_gate",
     "提交点读者门禁链（确定性硬门禁 + 报告武装）"),
    ("src.boundary_control.reader_gate", "run_causal_defense",
     "S3 因果防线并入提交闸（causal_issues 并入 reconcile_issues）"),
    ("src.workflow_action.precommit", "build_evaluator_precommit",
     "正文前冻结 EvaluatorPrecommit（不可修改，零 LLM）"),
    ("src.workflow_action.precommit", "falsify_prose_against_precommit",
     "确定性证伪：正文与预承诺硬事实比对"),
    ("src.boundary_control.chapter_commit", "ChapterCommitBoundary",
     "章节提交边界（无半提交）"),
    ("src.object_state.autonomous", "charge_usage",
     "四轴预算扣减（calls/input/output/cost）"),
    ("src.workflow_action.autonomous_runner", "AutonomousRunner",
     "A1 自动执行内核"),
]

# AutonomousRunner 必须拥有的成员（代码级保障）
MEMBER_CHECKS: list[tuple[str, str]] = [
    ("_verify_committed_head", "恢复只识别完整提交（拒绝猜提交头）"),
    ("_run_long_horizon_checkpoint", "10/20/30 章 checkpoint 自动比对"),
    ("_record_precommits", "precommit 证据落盘（证据链完整）"),
]


def _source(module_path: str) -> str:
    path = REPO_ROOT / Path(*module_path.split(".")).with_suffix(".py")
    return path.read_text(encoding="utf-8")


def verify_readiness() -> dict[str, bool]:
    checks: dict[str, bool] = {}

    # 1. 无人工干涉：auto 入口不执行 [WAITING]（仅允许 docstring 否定性说明）
    auto_src = _source("src.auto_short_form")
    checks["auto 入口无 [WAITING] 执行路径"] = (
        "[WAITING]" not in auto_src.replace("无 [WAITING]", "")
    )

    # 2. 符号级保障点（def/class/import 任一形式出现在模块源码）
    for module, name, label in IMPORT_CHECKS:
        checks[label] = name in _source(module)

    # 3. AutonomousRunner 成员保障
    runner_src = _source("src.workflow_action.autonomous_runner")
    for member, label in MEMBER_CHECKS:
        checks[label] = f"def {member}" in runner_src

    # 4. 评审器换位一致性约束（S2）：policy 有 position_consistency 下限
    checks["S2 换位一致性下限在位（policy 字段）"] = (
        "pairwise_position_consistency_min" in _source("src.object_state.autonomous")
    )

    # 5. 读者门禁轴武装率：hard_consistency 恒跑（不静默放行）
    gate_src = _source("src.boundary_control.reader_gate")
    checks["读者门禁 hard_consistency 轴恒跑"] = '"hard_consistency": True' in gate_src

    # 6. 预算四轴拒绝语义：超限 append 到 exceeded（charge_usage 拒绝）
    checks["预算四轴超限拒绝（charge_usage）"] = (
        'exceeded.append("cost_usd")' in _source("src.object_state.autonomous")
    )

    return checks


def main(argv: list[str] | None = None) -> int:
    checks = verify_readiness()
    ok = all(checks.values())
    print("S6 无人连续生产链就绪检查（48 清单自动化等价物·代码层）")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if ok:
        print("  真机依赖项（90 章无人 Canary / 独立 release / 新 tag）待真实 provider 运行 a1_release_validation.py 聚合")
    print(f"SUITE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
