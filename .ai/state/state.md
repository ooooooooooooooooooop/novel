# novel-main — Project State（canonical · 随代码版本演进 · decisions 只增不改）

> 接手协议：新 agent 只读本文件 + Context Package，**禁止读聊天历史**。
> 更新：里程碑时由主 agent 更新；初始化 2026-08-28（来源：README、docs/00_project/releases/、broker topic s6-s7-cpa）。

## goal

Automatic Novel Narrative System：解析叙事结构、维护叙事状态、规划故事推进、审查生成结果，支持 Rebuild/Continue/Rewrite。长期目标含后续落地实现工作。

## current_state

- **Tier 0 production-ready**（2026-07-28 判定）：local staged CLI v0，operator-in-the-loop
- 测试基线：**3079 passed + 1 skipped（3080 collected）**，本地测试声明，GitHub 无 CI
- checkpoint tag：`v0.1.2-tier0`；release record：`docs/00_project/releases/tier0-release.json`
- 三条流水线代码完成并端到端验证：`audit_short_form` / `extend_short_form` / `compose_short_form`
- 一键回归门：`python scripts/tier0_canary_regression.py`
- **当前停机**：`paused_external_auth`（2026-08-26 起）——外部模型服务授权失效（HTTP 503），非代码故障；细节属运营侧私有信息，见个人状态库

## architecture

- 设计层 `docs/`（00_project … 07_decisions）+ 实现层 `src/`；流水线=分阶段 CLI
- 决策记录：`docs/07_decisions/`（12 份决策文档）
- 叙事数据/模板：`style_library/`、`author_models/`、`author_templates/`、`reference_texts/`

## decisions（摘要，全文见 docs/07_decisions/）

- 2026-07-28：Tier 0 判定标准与达成（tag v0.1.2-tier0）
- 模型边界 / 工作流顺序 / schema 粒度 / 示例策略 / 审查策略 / 实验策略 / context packaging / ownership matrix：见 02–11 各决策文档
- 2026-08-26：ch9 temperature=0 下无效 state ref 确定性死锁已修复；S6 offdom 推进至 16/30

## constraints

- 本地分阶段 CLI；操作员在环；无云端 CI
- 外部模型网关的可用授权是 production 跑批的前置条件
- 机器睡眠会冻结在途请求 → 醒后 HTTPError（已知运行风险）

## completed_work

- 三个实现切片全部端到端验证；extend/compose canary 通过 `novel gate` 四同标准
- ch9–ch16 已提交；生产 ch9 plan survivors=2

## unresolved

- **外部模型服务授权失效** → offdom S6/S7 停在 ch17（16/30）
- 恢复后需先做真实 chat completion probe（HTTP 200）再重启 driver

## experiments

- `docs/06_experiments/` + `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`

## next_actions

1. 恢复外部模型服务授权
2. 真实 chat completion probe 返回 HTTP 200
3. 从 offdom ch17 重启 driver 续跑 S6/S7
