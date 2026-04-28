# Schema 粒度决策

## 文档目的
本文件用于收束当前阶段已经基本确定的数据粒度相关决策。

它关注的不是某个字段叫什么，而是更关键的问题：

- 一个对象应该细到什么程度
- 什么信息值得主存
- 什么信息只需要摘要
- 什么信息应该作为派生结果，而不是基础字段
- 什么时候对象太粗，导致无法审查
- 什么时候对象太细，导致维护成本失控

本文件的作用，是防止后续扩展时出现 schema 过重、字段堆积、主存过多，以及运行对象越来越像数据库垃圾堆。

---

## 1. 文档定位

[01_foundation_decisions.md](d:\Desktop\novel\docs\07_decisions\01_foundation_decisions.md) 固定总体方向。  
[02_model_boundary_decisions.md](d:\Desktop\novel\docs\07_decisions\02_model_boundary_decisions.md) 固定对象边界。  
[03_workflow_order_decisions.md](d:\Desktop\novel\docs\07_decisions\03_workflow_order_decisions.md) 固定流程顺序。

本文件固定的是：

对象该记多细、字段该写多重、什么该主存、什么不该主存。

它主要影响：

- `02_data_models/`
- `05_examples/`
- `06_experiments/`
- 所有 workflow 的输入输出负担

---

## 2. 当前需要固定的粒度问题

当前最值得固定的粒度问题主要有 8 个：

1. `PlotUnit` 的最小粒度是什么
2. `NarrativeState` 更新频率应多高
3. `FactLedger` 记到多细
4. `ForeshadowGraph` 线程要不要过度拆分
5. `ReviewIssue` 一条问题的粒度多大
6. `CharacterModel` 该保留多少运行态字段
7. 哪些指标只做派生，不进 schema
8. mock case 当前应该优先验证“轻而全”，而不是“细而满”

---

## 3. DEC-20260326-24

### 决策标题

`PlotUnit` 的推荐最小粒度是单次有效状态转移。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

`PlotUnit` 最容易出现两种极端：

- 太小：一两句对白、一次动作、一个情绪波动都单独成 unit
- 太大：一整章塞成一个 unit，内部已经发生多次目标与状态切换

这两种都会让后续审查和回写失真。

### 备选方案

- 方案 A：按文本自然结构切分，比如段落或场次
- 方案 B：按叙事功能切分，以“一次有效状态转移”为最小粒度
- 方案 C：按章节切分，一个章节一个 unit

### 最终选择

采用方案 B。

### 选择理由

一个 `PlotUnit` 至少应包含：

1. 一个明确输入状态
2. 一个关键行动者
3. 一个关键决策或关键转折
4. 一组主要阻力
5. 一个输出状态
6. 至少一项可验证状态变化

选择这个粒度的理由是：

1. 最适合接状态转移规则
2. 太细会让对象爆炸、审查负担爆炸
3. 太粗会让失败定位失去精度
4. 当前系统最重要的是可审查、可回写，而不是文本切片精致

### 影响范围

- [05_plotunit_schema.md](d:\Desktop\novel\docs\02_data_models\05_plotunit_schema.md)
- [01_state_transition_rules.md](d:\Desktop\novel\docs\03_rules\01_state_transition_rules.md)
- [03_continue_workflow.md](d:\Desktop\novel\docs\04_workflows\03_continue_workflow.md)
- [04_sample_plotunit.md](d:\Desktop\novel\docs\05_examples\04_sample_plotunit.md)

### 风险 / 待验证项

- 某些桥接性弱推进场景是否需要更小 unit，仍需实验验证

### 后续动作

`watch`

---

## 4. DEC-20260326-25

### 决策标题

`NarrativeState` 不要求每句都更新，但每个有效 `PlotUnit` 后必须检查是否更新。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

`NarrativeState` 如果更新太频繁，会变成高噪声对象；更新太稀，则会脱离真实局势。

### 备选方案

- 方案 A：每有文本就更新状态
- 方案 B：每个 `PlotUnit` 结束后检查是否需要更新
- 方案 C：只在章节结束时更新

### 最终选择

采用方案 B。

### 选择理由

每个 `PlotUnit` 结束后，必须检查以下是否变化：

- 时间
- 地点
- 在场角色
- 当前主目标
- 当前冲突
- 当前信息分布
- 当前开放问题
- 当前情绪温度
- 当前活跃承诺

如果无变化，可不生成全新状态；如果有关键变化，应生成或更新状态快照。

这能保证：

1. `NarrativeState` 足够及时，才能支撑续写
2. `NarrativeState` 又不会细到维护成本失控

### 影响范围

- [04_narrativestate_schema.md](d:\Desktop\novel\docs\02_data_models\04_narrativestate_schema.md)
- [03_continue_workflow.md](d:\Desktop\novel\docs\04_workflows\03_continue_workflow.md)
- [01_state_transition_rules.md](d:\Desktop\novel\docs\03_rules\01_state_transition_rules.md)

### 风险 / 待验证项

- “小改动是否要生成新 `state_id`” 还需后续实现时细化

### 后续动作

`patch`

---

## 5. DEC-20260326-26

### 决策标题

`FactLedger` 只记录会约束后文的事实，不记录所有剧情细节。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

账本最容易膨胀成剧情流水账。

如果所有发生过的东西都入账，会极重、难维护、难检索，也难做知情与连续性判断。

### 备选方案

- 方案 A：尽可能全面记录剧情事件
- 方案 B：只记录会约束后文、会参与审查或会影响续写的事实

### 最终选择

采用方案 B。

### 选择理由

一条内容通常只有满足以下至少一条时才应入账：

1. 会在后文继续约束角色行为
2. 会在后文继续约束世界、资源或权限
3. 会影响知情边界
4. 会影响时间或因果合法性
5. 会影响承诺推进或后果兑现
6. 若忘记会直接造成连续性问题

不建议入账的内容包括：

- 单纯情绪波动
- 一般性景物变化
- 无后续约束的闲聊
- 纯表达层修辞信息

### 影响范围

- [06_factledger_schema.md](d:\Desktop\novel\docs\02_data_models\06_factledger_schema.md)
- [05_sample_factledger.md](d:\Desktop\novel\docs\05_examples\05_sample_factledger.md)
- [03_continue_workflow.md](d:\Desktop\novel\docs\04_workflows\03_continue_workflow.md)
- 信息释放与时间规则

### 风险 / 待验证项

- 当前关系事实是否入账仍是灰区，需要继续实验

### 后续动作

`keep`

---

## 6. DEC-20260326-27

### 决策标题

`ForeshadowGraph` 不追求收录所有悬念，只收录正式承诺线程。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

如果把所有“读者可能好奇一下”的点都放进 `ForeshadowGraph`，承诺图会迅速失控。

### 备选方案

- 方案 A：凡是看起来有悬念感的都建线程
- 方案 B：只对正式承诺线程建图

### 最终选择

采用方案 B。

### 选择理由

通常满足以下至少两条才建议建线程：

1. 会影响读者长期预期
2. 会约束后续结构
3. 未来必须回应
4. 若不回应会造成明显阅读缺口
5. 会持续影响角色关系、目标或风险

不建议建线程的内容包括：

- 一次性小悬念
- 纯气氛型异常感
- 没有明确结构后果的小细节

选择这个方案的核心原因是：承诺图的价值在于可调度，不是全收集。

### 影响范围

- [07_foreshadowgraph_schema.md](d:\Desktop\novel\docs\02_data_models\07_foreshadowgraph_schema.md)
- [06_foreshadow_rules.md](d:\Desktop\novel\docs\03_rules\06_foreshadow_rules.md)
- [07_mock_project_case.md](d:\Desktop\novel\docs\05_examples\07_mock_project_case.md)

### 风险 / 待验证项

- 当前线程数量少时容易显得合理，后续要用多线程实验继续验证

### 后续动作

`watch`

---

## 7. DEC-20260326-28

### 决策标题

`ReviewIssue` 一条只处理一个核心问题，不做复合大问题单。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

审查时，一个失败单元往往会同时出现动机不足、关系跳变、后果缺失、承诺推进缺失等问题。

如果把它们全部塞进一条 issue，会导致根因、修复方向和关闭标准都变得模糊。

### 备选方案

- 方案 A：一个对象出问题就合并成一条大 issue
- 方案 B：每条 issue 尽量只处理一个核心问题

### 最终选择

采用方案 B。

### 选择理由

一条 `ReviewIssue` 应尽量满足：

- 一个主失败类型
- 一个主要对象
- 一条主要修复方向

允许附带次问题，但不应让 issue 失去单一闭环性。

这样做的价值在于：

1. 改写 workflow 需要清晰入口
2. 实验统计需要失败类型稳定
3. 复检时需要明确“这条问题算没算修掉”

### 影响范围

- [08_reviewissue_schema.md](d:\Desktop\novel\docs\02_data_models\08_reviewissue_schema.md)
- [02_review_workflow.md](d:\Desktop\novel\docs\04_workflows\02_review_workflow.md)
- [04_rewrite_workflow.md](d:\Desktop\novel\docs\04_workflows\04_rewrite_workflow.md)

### 风险 / 待验证项

- 某些高度耦合问题可能仍需“issue cluster”概念，后续再说

### 后续动作

`keep`

---

## 8. DEC-20260326-29

### 决策标题

`CharacterModel` 只保留少量必要运行态字段，不让角色模型膨胀成第二个 `NarrativeState`。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

`CharacterModel` 如果不断吸收当前情绪、当前所在位置、当前主冲突、当前局部策略、当前在场关系氛围，就会迅速膨胀成状态对象。

### 备选方案

- 方案 A：角色模型尽量多记当前状态，方便调用
- 方案 B：角色模型只保留少量必要运行态字段，其余交给 `NarrativeState`

### 最终选择

采用方案 B。

### 选择理由

当前允许保留的运行态 / 可成长字段包括：

- `short_term_goal`
- `knowledge_state`
- `misinformation`
- `available_resources`
- `relations`
- `arc_stage`
- `self_image`

不建议扩进来的字段包括：

- 当前地点
- 当前在场与否
- 当前局势总冲突
- 当前段落情绪温度
- 当前全局开放问题

这能保证角色模型的主任务仍是解释角色结构，而不是吞掉运行态。

### 影响范围

- [03_charactermodel_schema.md](d:\Desktop\novel\docs\02_data_models\03_charactermodel_schema.md)
- [03_sample_characters.md](d:\Desktop\novel\docs\05_examples\03_sample_characters.md)
- [02_model_boundary_decisions.md](d:\Desktop\novel\docs\07_decisions\02_model_boundary_decisions.md)

### 风险 / 待验证项

- 已通过 `18_charactermodel_summary_bloat.md` 做 first-pass 长链反例压测：`knowledge_state` 与 `relations` 不应吸收当前路线、当前风险与 scene 级关系温度
- 已通过 `19_charactermodel_rebuild_pruning.md` 做 first-pass 恢复后修剪压测：`Rebuild` 应把 stale runtime cache 从角色摘要中剔回当前工作层
- 已通过 `20_charactermodel_keep_vs_drop.md` 做 first-pass 边界压测：稳定认知负担与长期关系基底可保留，但 scene 级证据说明、路线判断与强主观押注不可混入长期摘要
- 已通过 `21_charactermodel_self_image_boundary.md` 做 first-pass 边界压测：`self_image` 只应记录跨多轮选择后稳定下来的自我定义变化，不应吸收当前羞耻、自责或顺风自满
- 已通过 `22_charactermodel_arc_stage_boundary.md` 做 first-pass 边界压测：`arc_stage` 只应在跨多轮、带代价且可回看的行为基底变化出现时推进
- 已通过 `26_charactermodel_cross_field_recovery.md` 做 first-pass 组合型压测：`knowledge_state`、`relations`、`misinformation`、`self_image`、`arc_stage` 在同一长链里一起变化时，也不得重新混成一个压缩很差的当前工作面摘要
- 已通过 `27_charactermodel_rollback_misinformation.md` 做 first-pass rollback 压测：`self_image` 与 `arc_stage` 的合法推进，不等于旧 `misinformation` 可以被同轮自动清空
- 已通过 `28_charactermodel_supporting_evidence_leakback.md` 做 second-pass mixed-loop 压测：即使 `CharacterModel` 字段已有合法 first-pass 更新，多轮 supporting evidence 也不得在第二次恢复里漏回字段本体
- 当前 `CharacterModel` keep-vs-drop 边界已从单字段压测推进到 mixed-loop 压测，但后续仍应在三轨合流压力下继续观察，避免被 `FactLedger` / `Rewrite` 侧压力重新拉糊

### 后续动作

`watch`

---

## 9. DEC-20260326-30

### 决策标题

派生指标默认不主存，只有在实验中证明高频必要时才考虑写回 schema。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

设计过程中很容易不断想到一些看起来很有用的指标：

- 当前危险指数
- 当前关系热度
- 当前承诺压力分
- 当前暴露风险总值
- 本章冲突密度

这些指标很诱人，但过早主存会导致 schema 过重。

### 备选方案

- 方案 A：想到有用指标就直接加字段
- 方案 B：默认视为派生指标，先不主存

### 最终选择

采用方案 B。

### 选择理由

当前默认只做派生的指标示例包括：

- 当前局势危险指数
- 当前承诺遗失压力
- 当前章节冲突密度
- 某关系线推进热度
- 某角色暴露风险总值

采用这一方案的核心原因是：

1. 能算出来的，不必先存
2. 派生字段反而容易和原始字段冲突
3. 当前阶段优先稳定基础对象，而不是堆指标体系

### 影响范围

- [09_field_rules.md](d:\Desktop\novel\docs\02_data_models\09_field_rules.md)
- 所有 schema 的未来扩展策略

### 风险 / 待验证项

- 若后续某指标被证明高频参与 workflow，可能需要升级为正式字段

### 后续动作

`watch`

---

## 10. DEC-20260326-31

### 决策标题

当前样例与 mock case 采用“轻而全”策略，不采用“细而满”策略。

### 决策类型

`example`

### 决策状态

`adopted`

### 背景问题

样例层可以有两种构建方式：

- 轻而全：覆盖全链路，但每层只放最关键内容
- 细而满：把一个案例尽可能写满、写细、写全

### 备选方案

- 方案 A：从一开始就做细而满的样例
- 方案 B：先做轻而全，确保全链路成立

### 最终选择

采用方案 B。

### 选择理由

1. 当前最重要的是验证链路闭环
2. 如果样例一开始过重，难以发现“到底是链路错还是内容太多”
3. 轻而全更适合第一轮实验与快速回改

### 影响范围

- `05_examples/`
- `06_experiments/`

### 风险 / 待验证项

- 轻样例可能掩盖复杂度问题，后续必须补复杂压力样例

### 后续动作

`keep`

---

## 11. 当前粒度控制的总原则

基于以上决策，当前建议统一遵守以下粒度原则：

1. 对象要足够细，能支撑审查
2. 对象不能细到维护崩溃
3. 只主存高约束信息
4. 派生先算，别急着存

---

## 12. 当前最值得继续实验验证的粒度问题

虽然主原则已定，但以下 4 类仍需实验继续压实：

### 12.1 关系粒度

哪些关系变化应该只在 `PlotUnit` 里记，哪些需要入账本。

### 12.2 知情粒度

哪些知情状态应留在角色模型，哪些需要成为账本条目。

### 12.3 状态粒度

是否每次目标变化都应生成新 `NarrativeState`。

### 12.4 线程粒度

一条承诺线何时该拆成两条，何时不该拆。

---

## 13. 后续动作建议

这个文件写完后，下一步最自然的是补：

`07_decisions/05_example_strategy_decisions.md`

重点收束：

- 为什么当前只用一个 mock case
- 为什么先做正例后做反例
- 什么时候应该引入第二题材样例
- 示例层和实验层如何分工

这样决策层就会从总方向、边界、顺序、粒度，继续推进到样例与验证策略。

---

## 14. 一句话总结

`04_schema_granularity_decisions.md` 的作用，是把这套系统中“到底记多细、什么值得主存、什么不值得”的关键判断固定下来，避免后面扩展时把 schema 变成看起来很全、实际上没人能长期维护的重型对象堆。
