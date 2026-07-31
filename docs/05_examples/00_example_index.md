
# 示例索引

## 文档目的
本文件是 `05_examples/` 目录的总入口，用于统一说明自动小说系统中样例文件的职责、使用顺序、验证目标与覆盖范围。

它不直接定义某一个对象，也不直接承担工作流功能，而是回答：

- 示例层为什么存在
- 当前应该准备哪些样例
- 每个样例文件验证什么
- 示例层如何与概念层、数据模型层、规则层、工作流层衔接
- 一次 mock case 应该如何使用这些样例

---

## 1. 示例层的定位

示例层位于：

- 项目层之后
- 概念层之后
- 数据模型层之后
- 规则层之后
- 工作流层之后

它的作用是把前面已经建立好的：

- 概念对象
- schema
- 规则系统
- 工作流系统

放进一个**可验证、可复盘、可试跑**的具体案例里。

### 一句话定义
示例层的任务，不是再讲一遍理论，而是证明这套理论能不能真的落地。

---

## 2. 为什么必须有示例层

如果没有示例层，前面所有内容虽然“结构上成立”，但仍然可能存在以下问题：

1. 概念定义彼此边界不清  
2. schema 字段太多但不好用  
3. 规则写得正确但无法执行  
4. 工作流顺序看起来合理，但实际跑不通  
5. 多个对象之间的引用关系在真实案例里出现冲突  
6. 审查规则在案例里找不到足够支点  

因此，示例层的目标是：

- 验证抽象是否可用
- 验证字段是否足够
- 验证规则是否可执行
- 验证工作流是否闭环
- 为后续实验与决策提供样本

---

## 3. 示例层文件清单

当前建议包含以下文件：

- `05_examples/00_example_index.md`
- `05_examples/01_sample_workspec.md`
- `05_examples/02_sample_worldmodel.md`
- `05_examples/03_sample_characters.md`
- `05_examples/04_sample_plotunit.md`
- `05_examples/05_sample_factledger.md`
- `05_examples/06_sample_review.md`
- `05_examples/07_mock_project_case.md`
- `05_examples/08_reviewreminder_chain.md`
- `05_examples/09_mixed_review_routing.md`
- `05_examples/10_structural_replan_routing.md`
- `05_examples/11_cross_arc_rebuild_recovery.md`
- `05_examples/12_ownership_matrix_pressure_test.md`
- `05_examples/13_concurrent_reminder_priority.md`
- `05_examples/14_same_family_reminder_merge.md`
- `05_examples/15_situation_change_admission.md`
- `05_examples/16_repeated_rebuild_continue_loop.md`
- `05_examples/17_local_rewrite_writeback_exception.md`
- `05_examples/18_charactermodel_summary_bloat.md`
- `05_examples/19_charactermodel_rebuild_pruning.md`
- `05_examples/20_charactermodel_keep_vs_drop.md`
- `05_examples/21_charactermodel_self_image_boundary.md`
- `05_examples/22_charactermodel_arc_stage_boundary.md`
- `05_examples/23_mixed_threshold_recovery_chain.md`
- `05_examples/24_second_recovery_handoff_split.md`
- `05_examples/25_rewrite_exception_misuse_chain.md`
- `05_examples/26_charactermodel_cross_field_recovery.md`
- `05_examples/27_charactermodel_rollback_misinformation.md`
- `05_examples/28_charactermodel_supporting_evidence_leakback.md`
- `05_examples/29_three_track_convergence_pressure_test.md`

---

## 4. 各示例文件的职责

## 4.1 `01_sample_workspec.md`
### 作用
提供一个最小但完整的作品规格样例。

### 验证目标
验证：
- `WorkSpec Schema` 是否足够表达作品方向
- 作品级约束是否能真正约束后续对象
- genre、theme、pacing、narration_mode 等字段是否足够清晰

### 主要对应
- `01_concepts/01_workspec.md`
- `02_data_models/01_workspec_schema.md`

---

## 4.2 `02_sample_worldmodel.md`
### 作用
提供一个可运行的世界模型样例。

### 验证目标
验证：
- 世界规则是否能支撑剧情约束
- 资源、制度、代价、阵营是否足够构成合法性检查
- `WorldModel` 是否不是装饰背景，而是真正参与运行

### 主要对应
- `01_concepts/02_worldmodel.md`
- `02_data_models/02_worldmodel_schema.md`
- `03_rules/02_world_legality_rules.md`

---

## 4.3 `03_sample_characters.md`
### 作用
提供一组角色模型样例。

### 验证目标
验证：
- `CharacterModel` 是否真能解释角色决策
- 关系字段是否足以推动冲突
- 恐惧、缺陷、目标、成长字段是否能服务审查与续写

### 主要对应
- `01_concepts/03_charactermodel.md`
- `02_data_models/03_charactermodel_schema.md`
- `03_rules/03_character_consistency_rules.md`

---

## 4.4 `04_sample_plotunit.md`
### 作用
提供一个完整推进单元样例。

### 验证目标
验证：
- `PlotUnit` 是否真能表达“状态从 A 到 B 的转移”
- 输入状态、关键决策、冲突、事件、输出状态之间是否能闭环
- `state_change_summary` 是否足以支持审查

### 主要对应
- `01_concepts/05_plotunit.md`
- `02_data_models/05_plotunit_schema.md`
- `03_rules/01_state_transition_rules.md`

---

## 4.5 `05_sample_factledger.md`
### 作用
提供一组事实账本条目样例。

### 验证目标
验证：
- 哪些内容应该进入账本
- 事实、误导、推断是否能被分开
- `visibility`、`known_by`、`status` 等字段是否足够支撑连续性与信息合法性检查

### 主要对应
- `01_concepts/06_factledger.md`
- `02_data_models/06_factledger_schema.md`
- `03_rules/04_timeline_rules.md`
- `03_rules/05_information_release_rules.md`

---

## 4.6 `06_sample_review.md`
### 作用
提供一个正式审查样例。

### 验证目标
验证：
- 一次完整审查如何落地
- 失败类型如何映射为 `ReviewIssue`
- 非阻断 warning 如何映射为 `ReviewReminder`
- `Review Workflow` 是否真正能闭环

### 主要对应
- `01_concepts/08_reviewissue.md`
- `02_data_models/08_reviewissue_schema.md`
- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`
- `04_workflows/02_review_workflow.md`

---

## 4.7 `07_mock_project_case.md`
### 作用
提供一个贯穿式 mock case。

### 验证目标
验证一套最小项目能否从以下对象全链路串起来：
- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

### 主要对应
- 全目录联调验证

---

## 4.8 `08_reviewreminder_chain.md`
### 作用
提供一个最小多轮链路样例，用于验证 `ReviewReminder` 的创建、跨轮传递、复查与升级。

### 验证目标
验证：
- `ReviewReminder` 是否能脱离 prose 备注独立工作
- `Continue` 是否会真正读取 active reminder
- warning 是否会在窗口耗尽后稳定升级为正式 `ReviewIssue`

### 主要对应
- `01_concepts/09_reviewreminder.md`
- `02_data_models/10_reviewreminder_schema.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`

---

## 4.9 `09_mixed_review_routing.md`
### 作用
提供一个 reminder 与正式 issue 并存的审查样例，用于验证 `Continue / Rewrite / Replan` 的分流边界。

### 验证目标
验证：
- active `ReviewReminder` 不会因为新 issue 出现而被静默吞掉
- 局部正式失真会优先把结果送进 `Rewrite`
- reminder + 单个 issue 并存时，不会过度升级到 `Replan`

### 主要对应
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`

---

## 4.10 `10_structural_replan_routing.md`
### 作用
提供一个多个 formal issue 指向同一结构弱点的样例，用于验证何时应从局部修补升级为 `Replan`。

### 验证目标
验证：
- `Replan` 不是单纯由问题数量触发
- 多 issue 的共同结构指向能否被稳定识别
- 当前局部修法是否已经失效

### 主要对应
- `04_workflows/02_review_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`

---

## 4.11 `11_cross_arc_rebuild_recovery.md`
### 作用
提供一个跨 arc 的退化与恢复样例，用于验证 bounded package 失效后，系统是否会正确切换到 `Rebuild`。

### 验证目标
验证：
- 当前工作集不足时，不会误继续强写
- `Rebuild` 能恢复静态记忆与可运行状态包
- 恢复后的 workflow route 仍然清楚

### 主要对应
- `04_workflows/01_rebuild_workflow.md`
- `07_decisions/08_context_packaging_decisions.md`
- `00_project/05_narrative_agent_harness.md`

---

## 4.12 `12_ownership_matrix_pressure_test.md`
### 作用
提供一个 ownership 压测样例，用于验证 knowledge 与 relation 两组高风险边界在长上下文工作里是否足够稳定。

### 验证目标
验证：
- 哪些知情变化只应留在 `NarrativeState`
- 哪些知情变化必须升级到 `FactLedger`
- 哪些关系变化只是当前张力
- 哪些关系变化已经成为正式 relation fact

### 主要对应
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/02_review_workflow.md`

---

## 4.13 `13_concurrent_reminder_priority.md`
### 作用
提供一个多 active reminder 并发样例，用于验证 reminder 的并存、优先级、独立关闭与独立升级。

### 验证目标
验证：
- 不同 family 的 reminder 何时不能粗暴合并
- `Continue` 应优先补偿哪一条 reminder
- 一条 reminder 关闭不会自动关闭其他 reminder
- 并发 reminder 不等于自动升级到 `Replan`

### 主要对应
- `07_decisions/11_reviewreminder_escalation_matrix.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`

---

## 4.14 `14_same_family_reminder_merge.md`
### 作用
提供一个同 family reminder 的合并压测样例，用于验证 grouped handoff 与 true merge 的边界。
### 验证目标
验证：
- 同 family reminder 不应因类型相同而直接压成一条总提醒
- grouped handoff 可以共享摘要，但不能抹掉 child reminder 的来源、窗口与升级轨迹
- 默认优先级应继承最短窗口，而不是平均窗口或最新窗口

### 主要对应
- `07_decisions/11_reviewreminder_escalation_matrix.md`
- `07_decisions/12_concurrent_reminder_routing_decisions.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`

---

## 4.15 `15_situation_change_admission.md`
### 作用
提供一个 `situation change` 的入账阈值压测样例，用于验证 tactical pressure 与 world-state change 的边界。
### 验证目标
验证：
- 哪些局势变化只应留在 `NarrativeState`
- 哪些 route / legality / mission state 变化已经必须进入 `FactLedger`
- situation change 不应因“局势更紧”就过早入账

### 主要对应
- `07_decisions/13_factledger_admission_thresholds.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/02_review_workflow.md`

---

## 4.16 `16_repeated_rebuild_continue_loop.md`
### 作用
提供一个 repeated `degradation -> rebuild -> review -> continue` 长链样例，用于验证恢复链路下的阈值稳定性。
### 验证目标
验证：
- repeated `Rebuild` 不应把已成立 `FactLedger` 事实不断降级回运行态
- `Continue` 在恢复后不应把硬事实写回临时判断
- handoff package 是否足以支撑第二次及之后的恢复

### 主要对应
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`

---

## 4.17 `17_local_rewrite_writeback_exception.md`
### 作用
提供一个 local `Rewrite` 写回顺序例外压测样例，用于验证何时允许先修运行态，以及何时必须在同一轮补写 `FactLedger`。

### 验证目标
验证：
- 当根因位于 `PlotUnit` / `NarrativeState` 时，runtime-first repair 是否属于允许例外
- rewrite 本轮一旦明确了新的硬事实，是否必须在同一 repair packet 内补账
- `CharacterModel` 摘要不会被误用成事实层与运行态层之间的跳板

### 主要对应
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/04_rewrite_workflow.md`

---

## 4.18 `18_charactermodel_summary_bloat.md`
### 作用
提供一个 `CharacterModel` 长期摘要膨胀压测样例，用于验证 `knowledge_state` 与 `relations` 在长链运行里何时仍是角色侧长期摘要，何时已经开始吞掉当前工作面。

### 验证目标
验证：
- repeated `Continue / Rebuild` 是否会把当前路线、当前风险、当前关系温度错误沉积进 `CharacterModel`
- `knowledge_state` 只保留长期决策负担，而不是抄写当前局势
- `relations` 只保留长期关系基底，而不是 scene-by-scene 温度流水账

### 主要对应
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.19 `19_charactermodel_rebuild_pruning.md`
### 作用
提供一个 `CharacterModel` 的 `Rebuild pruning` 压测样例，用于验证当角色摘要已经吸收过多运行态噪音时，恢复链路应如何把它压回长期角色基底。

### 验证目标
验证：
- `Rebuild` 是否能把 stale runtime cache 从 `knowledge_state` 与 `relations` 中剔除
- pruning 不会误删真正的长期认知负担与长期关系基底
- handoff 会明确说明删掉了什么，以及这些内容回到了哪一层

### 主要对应
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`

---

## 4.20 `20_charactermodel_keep_vs_drop.md`
### 作用
提供一个 `CharacterModel` 的 keep-vs-drop 边界压测样例，用于验证哪些“半长期、半当前”的条目应留在角色侧长期摘要，哪些应回退到当前工作面、handoff 证据层或误判层。

### 验证目标
验证：
- repeated loop 下，连续出现几轮的条目不会因为“看起来重要”就被误沉积进 `CharacterModel`
- 稳定认知负担与长期关系基底可以保留，但 scene 级证据说明应被剥离
- 强主观押注优先进入 `misinformation`，而不是伪装成 `knowledge_state`

### 主要对应
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.21 `21_charactermodel_self_image_boundary.md`
### 作用
提供一个 `CharacterModel.self_image` 边界压测样例，用于验证长期自我认知修正与当前羞耻、自责、逞强、顺风自满之间的分界。

### 验证目标
验证：
- `self_image` 不会吸收当前情绪解释或一场戏后的自我评价波动
- 只有跨多轮选择反复显现的新自我定义，才会更新到 `CharacterModel`
- 成长依据与 `self_image` 字段本身保持分离，不把过程证据写成长字段

### 主要对应
- `07_decisions/04_schema_granularity_decisions.md`
- `02_data_models/03_charactermodel_schema.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.22 `22_charactermodel_arc_stage_boundary.md`
### 作用
提供一个 `CharacterModel.arc_stage` 边界压测样例，用于验证成长阶段推进与“看起来像成长”的单次偏移之间的分界。

### 验证目标
验证：
- `arc_stage` 不会因为一次高压下的正确选择就被过早推进
- 只有跨多轮、带代价且可回看的行为基底变化，才会更新成长阶段
- 成长依据与 `arc_stage` 字段本身保持分离，不把过程证据写成阶段标签

### 主要对应
- `02_data_models/03_charactermodel_schema.md`
- `03_rules/03_character_consistency_rules.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.23 `23_mixed_threshold_recovery_chain.md`
### 作用
提供一个 mixed-family repeated recovery 样例，用于把 knowledge、relation、situation 三类 admission threshold 放进同一条退化与恢复链里压测。

### 验证目标
验证：
- mixed change family 在 repeated `Rebuild / Continue / Review` 下仍能保持 ledger-vs-state split
- 已成立的 knowledge / relation / situation fact 不会在后续恢复里被压回一句模糊 handoff prose
- 当前关系张力、主观怀疑、战术路线压力不会因为长链恢复而被误升级为 `FactLedger`

### 主要对应
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 4.24 `24_second_recovery_handoff_split.md`
### 作用
提供一个 second-recovery handoff 样例，用于验证 repeated `Rebuild` 之后，handoff package 是否仍能把 `FactLedger` 硬约束、当前工作面压力、置信缺口分开交代。

### 验证目标
验证：
- 第二次恢复后的 handoff 不会把已成立 knowledge / relation / situation fact 压成模糊 prose 摘要
- 当前争执、怀疑、路线压力不会因为 handoff 压缩而误升为 `FactLedger`
- 下一轮 `Continue` 仍能明确读取哪些内容是硬约束，哪些只是当前热区

### 主要对应
- `07_decisions/08_context_packaging_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 4.25 `25_rewrite_exception_misuse_chain.md`
### 作用
提供一个连续负例样例，用于验证 bounded runtime-first `Rewrite` exception 不能跨 handoff、跨复检、或借 `CharacterModel` 摘要被拖成错误顺序。

### 验证目标
验证：
- 本轮已明确的新硬事实不能 ledger-late repair
- `Review` 不应读取半同步的 rewrite 结果
- `CharacterModel` 不能被用作事实层拖延的缓冲层

### 主要对应
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`

---

## 4.26 `26_charactermodel_cross_field_recovery.md`
### 作用
提供一个 mixed-field repeated recovery 样例，用于验证 `knowledge_state`、`relations`、`misinformation`、`self_image`、`arc_stage` 在同一条长链里一起变化时，`CharacterModel` 是否仍能保持清晰边界。

### 验证目标
验证：
- `misinformation` 不会被误写进 `knowledge_state`
- 关系依据不会被误写进 `relations`
- `self_image` 与 `arc_stage` 更新后也不会把成长依据一起沉积进字段本体

### 主要对应
- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.27 `27_charactermodel_rollback_misinformation.md`
### 作用
提供一个 rollback-heavy repeated recovery 样例，用于验证 `self_image`、`arc_stage` 合法推进后，旧 `misinformation` 仍可能残留并在高压场景中复燃，不能被系统过早清空。

### 验证目标
验证：
- 成长推进不等于误判清零
- repeated `Rebuild` 后能同时保住已推进的成长结构和未完全退出的旧误判
- rollback 证据不会被误读成“成长全都不算数”

### 主要对应
- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 4.28 `28_charactermodel_supporting_evidence_leakback.md`
### 作用
提供一个 second-recovery mixed-loop 样例，用于验证当 `CharacterModel` 多字段已经有合法更新后，supporting evidence 仍不能在下一次 `Rebuild` / handoff 中漏回字段本体。

### 验证目标
验证：
- `knowledge_state`、`relations`、`misinformation`、`self_image`、`arc_stage` 即使合法更新，也不能把多轮依据一并写回字段正文
- repeated `Rebuild` 想保真时，应保留 supporting context 的位置与引用，而不是把证据倒灌进 `CharacterModel`
- 第二次恢复最危险的失败，不只是字段更错，而是字段边界因“怕丢信息”而重新膨胀

### 主要对应
- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 4.29 `29_three_track_convergence_pressure_test.md`
### 作用
提供一个三轨合流压测样例，用于同时验证 `FactLedger` hard fact 阈值、bounded runtime-first `Rewrite` exception 与 `CharacterModel` keep-vs-drop 边界在同一 repair packet 里不会互相补偿失真。

### 验证目标
验证：
- 新 hard fact 没有同轮写回时，handoff prose 不能代替正式对象同步
- `Rewrite` packet 不完整时，不能靠更详细的 handoff 或更长的 `CharacterModel` 字段伪装成“已修好”
- 三轨同时闭合时，hard fact、当前压力、未升级推断与角色长期字段必须继续分层

### 主要对应
- `04_workflows/04_rewrite_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/08_context_packaging_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `02_data_models/09_field_rules.md`

---

## 5. 示例层的三种用途

## 5.1 结构验证
用于检验对象与 schema 是否能表达真实案例。

### 重点看
- 字段是否够用
- 字段是否冗余
- 字段边界是否清晰
- 是否存在“只能理论成立，不能实际填写”的情况

---

## 5.2 规则验证
用于检验规则是否能对样例做出稳定判断。

### 重点看
- 世界合法性规则能否抓到越界
- 角色一致性规则能否抓到失真
- 信息释放规则能否抓到知情越界
- 承诺规则能否抓到遗失或突兀回收

---

## 5.3 工作流验证
用于检验一条工作流是否真的能跑通。

### 重点看
- 输入是否足够
- 中间步骤是否合理
- 输出是否可回写
- 审查后是否能形成下一步动作

---

## 6. 示例层的使用顺序

建议按以下顺序使用样例文件。

### 第一步：静态对象样例
先看：
- `01_sample_workspec.md`
- `02_sample_worldmodel.md`
- `03_sample_characters.md`

目标：
先验证项目底座。

### 第二步：运行单元样例
再看：
- `04_sample_plotunit.md`
- `05_sample_factledger.md`

目标：
验证推进与记账。

### 第三步：审查样例
再看：
- `06_sample_review.md`

目标：
验证规则与失败归类。

### 第四步：贯穿样例
最后看：
- `07_mock_project_case.md`
- `08_reviewreminder_chain.md`
- `09_mixed_review_routing.md`
- `10_structural_replan_routing.md`
- `11_cross_arc_rebuild_recovery.md`

目标：
验证整套系统是不是能真的跑一遍，以及长链路中的分流、退化与恢复是否稳定。

---

## 7. 示例层与前面目录的关系

## 7.1 与概念层的关系
概念层定义：
- 它是什么

示例层验证：
- 它在真实案例里是不是还能保持这个定义

---

## 7.2 与数据模型层的关系
数据模型层定义：
- 字段有哪些

示例层验证：
- 这些字段能不能真的填
- 填完是否足够支持后续步骤

---

## 7.3 与规则层的关系
规则层定义：
- 什么时候成立
- 什么时候出错

示例层验证：
- 这些规则是不是能在具体案例里抓到问题
- 是否存在“规则写得很全，但一落地就模糊”的情况

---

## 7.4 与工作流层的关系
工作流层定义：
- 实际怎么跑

示例层验证：
- 这条流程拿样例跑时，会不会中途断掉
- 是否需要补对象、补字段、补规则

---

## 8. 示例设计原则

所有样例建议遵守以下原则。

### 8.1 小而完整
不要一开始就做特别大的案例。  
先保证：
- 样例小
- 结构完整
- 能闭环

### 8.2 一例多用
一个样例最好同时能验证多个对象和规则。

例如：
“雨夜夺令”这种例子，就能同时验证：
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- 审查规则

### 8.3 先强约束，再扩丰富度
先保证样例中的：
- 主目标
- 主冲突
- 主承诺
- 主后果
足够清楚

不要一开始就追求复杂支线。

### 8.4 样例必须能复跑
最好让一个样例能被：
- 重建工作流使用
- 续写工作流使用
- 审查工作流使用
- 改写工作流使用

---

## 9. 推荐的示例统一世界

为了降低复杂度，建议当前示例层先统一使用一个 mock 项目世界。

### 推荐统一案例
以你前面已经反复使用的这套案例为默认示例：

- 主角：`c001 / 沈青`
- 核心背景：被逐出宗门、体内封存残魂
- 当前阶段：试炼前夜、黑水泽外围
- 主承诺：
  - 身世之谜
  - 残魂秘密
  - c002 是否会保密
- 核心事件：
  - 雨夜夺令
- 当前风险：
  - 巡查队逼近
  - 旧伤复发
  - 半暴露状态

### 这样做的好处
- 所有样例都能互相衔接
- 可以很快组成一个完整 mock case
- 不需要每份样例都重新发明世界

---

## 10. 示例层的完成标准

示例层不要求“内容多”，而要求“验证有效”。

建议以下条件满足时，可视为示例层初步完成：

1. 至少有一份完整 `WorkSpec` 示例  
2. 至少有一份完整 `WorldModel` 示例  
3. 至少有三位主要角色的 `CharacterModel` 示例  
4. 至少有一个完整 `PlotUnit` 示例  
5. 至少有一组 `FactLedger` 示例  
6. 至少有一份正式审查样例  
7. 至少有一个从输入到审查的贯穿 mock case  

---

## 11. 当前建议的编写顺序

建议按以下顺序继续写：

### 第一优先
`05_examples/01_sample_workspec.md`

### 第二优先
`05_examples/02_sample_worldmodel.md`

### 第三优先
`05_examples/03_sample_characters.md`

### 第四优先
`05_examples/04_sample_plotunit.md`

### 第五优先
`05_examples/05_sample_factledger.md`

### 第六优先
`05_examples/06_sample_review.md`

### 第七优先
`05_examples/07_mock_project_case.md`

---

## 12. 示例层的输出目标

当示例层跑通后，你会得到三种非常重要的东西：

### 12.1 可验证模板
以后每次做新项目时，不需要从零猜对象怎么写。

### 12.2 可复盘案例
以后发现规则有问题，可以拿样例回头验证。

### 12.3 可训练地基
无论以后是给 Codex 看、给自己复用，还是做进一步实现，样例层都会成为最重要的“最小真数据”。

---

## 13. 一句话总结

`05_examples/00_example_index.md` 的作用，是把前面已经搭好的系统，从“理论结构”推进到“可验证结构”，让每一个对象、规则和工作流，都有一个真正能落地的样例可以对照。
