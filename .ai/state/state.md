# novel-main — Project State

> **Pointer-only（2026-08-30 起）**：本文件不再承载任何资格、数字或哈希声明。
> 当前验证资格的唯一机器真源是仓库根 `current_state.json`
> （第四轮 attestation 协议：bundle runner + 独立聚合器 + 原始 artifact 重推导）。
> 接手协议：新 agent 只读本文件 + `current_state.json` + Context Package，
> 禁止读聊天历史。

## goal

Automatic Novel Narrative System：解析叙事结构、维护叙事状态、规划故事推进、
审查生成结果，支持 Rebuild/Continue/Rewrite。

## constraints

- 本地分阶段 CLI；操作员在环；无云端 CI
- 状态/资格声明只允许出现在 `current_state.json` 与带日期+commit/tag 绑定的
  历史记录中
- 隐私纪律：真实小说信息一律不入库

## pointers

- 历史 release 记录：`docs/00_project/releases/`（字节级白名单锁定）
- 历史验收叙事：`docs/00_project/30_production_readiness_checklist.md`、
  `40_session_handoff.md`、`54_master_goal_execution_plan.md`（带日期小节）
- 运营侧证据（gitignored）：`runtime/refs/cpa_active/`
