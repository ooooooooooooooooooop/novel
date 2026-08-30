# Current Status

> **人类可读指针门面（2026-08-30 起）**：本文件不再承载任何资格、数字或哈希声明。
> 当前验证资格的唯一机器真源是仓库根 `current_state.json`（第四轮 attestation
> 协议：subject commit 的双 bundle 由独立聚合器从原始 artifact 重推导）。

<!-- state:current -->
**当前状态（唯一机器真源：`current_state.json`）**：默认标记 `CURRENT_HEAD_UNVERIFIED`——
carrier 提交不可自证；subject 资格以 json 的 `subject_overall_status` 为准。
本区块禁止数字声明与历史资格。
<!-- /state:current -->

## 有效性边界与交叉引用

- DirectAPI provider calling is not implemented（provider 调用仍未实现，`28_directapi_boundary_note.md`）；
  自动化就绪边界见 `29_automation_readiness_boundary.md`。
- Tier 0 canary 运行手册：`31_tier0_canary_runbook.md`；
  发布记录合同：`32_tier0_release_record_contract.md`（schema v2，
  `--expected-collected-tests`，结构化 full_pytest_result）。
- 一键回归门：`python scripts/tier0_canary_regression.py`（只读）。

## 历史记录的去向

- 历史 release 记录：`docs/00_project/releases/tier0-release.json`（2301，post-tag
  historical record）与 `q1-release.json`（2460，tag_self_record）——字节级白名单锁定，
  只经 `validate_legacy_tier0_release_record` 校验。
- 历史验收叙事（R0–R9、Tier 0 三流硬化、S1–S7 等）：见 git 历史、
  `30_production_readiness_checklist.md`、`40_session_handoff.md`、
  `54_master_goal_execution_plan.md` 的带日期小节。
- 第三轮起的状态收敛事实：见 `current_state.json` 的 `profiles` /
  `last_certified_checkpoint` / `state_artifacts/`（可重算原始 artifact）。
