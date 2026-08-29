# novel-main — Project State（canonical · 随代码版本演进 · decisions 只增不改）

> 接手协议：新 agent 只读本文件 + Context Package，**禁止读聊天历史**。
> 更新：里程碑时由主 agent 更新；初始化 2026-08-28（来源：README、docs/00_project/releases/、运营侧工作记录）。

## goal

Automatic Novel Narrative System：解析叙事结构、维护叙事状态、规划故事推进、审查生成结果，支持 Rebuild/Continue/Rewrite。长期目标含后续落地实现工作。

## current_state

- **Tier 0 production-ready**（2026-07-28 判定）：local staged CLI v0，operator-in-the-loop
- 测试基线：**3079 passed + 1 skipped（3080 collected）**，本地测试声明，GitHub 无 CI（2026-08-29 收尾态实测复验）
- checkpoint tag：`v0.1.2-tier0`；release record：`docs/00_project/releases/tier0-release.json`
- 三条流水线代码完成并端到端验证：`audit_short_form` / `extend_short_form` / `compose_short_form`
- 一键回归门：`python scripts/tier0_canary_regression.py`
- **S6 90 章无人 Canary：certified（90/90，2026-08-28）**——三类各 30/30；聚合 `runtime/refs/cpa_active/s6_canary_aggregate.json`
- **S7 真机裁决：`long_run_not_authorized`（3 绿 / 4 红，无 pending）**——判据与缺口见 `03_current_status.md` §0.7
- **当前停机**：`blocked_upstream_503`——缺口闭环 prospective5 依赖的 `gemini-3.7-flash-high` 上游通道 503（2026-08-29 11:52 复测仍故障），非代码故障；恢复条件＝通道回 200 后重跑三路 prospective5 + swap5

## architecture

- 设计层 `docs/`（00_project … 07_decisions）+ 实现层 `src/`；流水线=分阶段 CLI
- 决策记录：`docs/07_decisions/`（12 份决策文档）
- 叙事数据/模板：`style_library/`、`author_models/`、`author_templates/`、`reference_texts/`

## decisions（摘要，全文见 docs/07_decisions/）

- 2026-07-28：Tier 0 判定标准与达成（tag v0.1.2-tier0）
- 模型边界 / 工作流顺序 / schema 粒度 / 示例策略 / 审查策略 / 实验策略 / context packaging / ownership matrix：见 02–11 各决策文档
- 2026-08-26：ch9 temperature=0 下无效 state ref 确定性死锁已修复（state ref 重映射 + 选中 PlotUnit 绑定，勿回退）
- 2026-08-29：S1–S7 在途代码/文档收尾入库（f0f6993 → 3614552 → 150fb55）；S6/S7 真机终态写入 `03_current_status.md` §0.7

## constraints

- 本地分阶段 CLI；操作员在环；无云端 CI
- 外部模型网关的可用授权是 production 跑批的前置条件
- 机器睡眠会冻结在途请求 → 醒后 HTTPError（已知运行风险）

## completed_work

- 三个实现切片全部端到端验证；extend/compose canary 通过 `novel gate` 四同标准
- S6 无人 Canary 90/90 章 certified（三类各 30 章，2026-08-24 至 08-28）；S7 首轮真机裁决完成（3 绿 / 4 红）
- 缺口闭环 CP1–CP7 机制修复（driver 连续性、Frame 继承、judge 严格解析、盲终审）；swap4 12/12 一致
- 2026-08-29：S1–S7 代码/文档收尾提交；26 个临时脚本与外部杂物移出仓库；隐私脱敏（54/CLAUDE.md）

## unresolved

- **上游 `gemini-3.7-flash-high` 503** → prospective5（3 类 × 5 章）0 章提交，S7 缺口闭环停摆（4 红指标待新证据）
- S7 裁决 4 红：读者窗口 weak（6/4/6）、hist drift 2.258>1.2、true miss 0.767>0.20、换位一致性 0.505<0.9
- git 历史存在既有隐私泄漏（CLAUDE.md 早期提交行、`scripts/attribution_2x2.py` 语料片段），工作区已脱敏，历史清洗待用户裁决

## experiments

- `docs/06_experiments/` + `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- S6/S7 真机证据（gitignored）：`runtime/refs/cpa_active/`（aggregate、s7_judgment、metrics_evidence、HANDOFF、checkpoint）

## next_actions

1. 等 `gemini-3.7-flash-high` 上游通道恢复（真实 chat completion probe HTTP 200）
2. 重跑三路 prospective5（offdom/mythic/hist，各 5 章）+ swap5，跑统一四指标评测
3. 四指标全绿后启动 90 章 `s7-canary5-*`（命名已定）+ 最终七指标 `long_run_judgment.py` 裁决
4. 全绿才允许 S6/A1 独立 release + 新不可变 tag（单一命令聚合，不手工造记录）
