# Field Rules

## 文档目的
本文件用于统一规定自动小说系统中所有数据对象的字段分类、更新责任、写入原则、引用原则与变更边界。

它不是某一个对象的 schema，而是整个 `02_data_models/` 目录的共同规则层。

本文件主要回答：

- 什么是硬字段
- 什么是可成长字段
- 什么是运行态字段
- 什么是派生字段
- 不同字段由谁更新
- 哪些字段可以自动更新，哪些字段必须谨慎更新
- 多个对象都涉及同一信息时，谁是主存对象
- workflow 写回时，字段应按什么顺序同步

---

## 1. 适用范围

本文件适用于以下对象：

- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

---

## 2. 总体原则

### 2.1 状态优先于文本

字段设计优先服务于状态维护、状态转移和状态审查，而不是服务于文本好看。

### 2.2 事实优先于解释

能记录为事实的内容，不要直接写成解释或评论。

### 2.3 最小约束优先

字段存在的首要意义，是约束后续叙事或支持审查，而不是让系统显得完整。

### 2.4 对象边界必须清晰

不要让某个对象的字段承担另一个对象的职责。

### 2.5 更新责任必须明确

每类字段都应明确：

- 谁来写
- 何时更新
- 是否允许自动更新
- 修改后是否需要联动其他对象

---

## 3. 字段分类总则

本项目统一将字段分为 5 类：

1. 硬字段
2. 可成长字段
3. 运行态字段
4. 派生字段
5. 备注字段

---

### 3.1 记忆分层视角

从 narrative agent harness 的角度看，字段不只是在分类，也是在决定“哪些信息以什么形态跨轮保存”。

当前建议至少区分四层：

- 长期稳定记忆：`WorkSpec`、`WorldModel`、`CharacterModel` 的核心结构、已成立 `FactLedger`、已建立 `ForeshadowGraph`
- 当前工作集：`NarrativeState` 与少量角色运行态字段
- 临时推断层：派生字段、局部判断、待确认推断
- 正式修复层：`ReviewIssue` 与其他明确进入修复链的对象

如果一个字段被设计出来，却无法回答“它属于哪一层”，通常说明它的职责还不够清楚。

### 3.2 字段设计应支持上下文压缩

一个字段越适合作为长期 agent 工作接口，就越应该：

- 在不重读全文时仍可理解
- 不依赖大片正文才能解释
- 能清楚区分事实、运行态、推断和修复状态
- 能在 workflow 之间稳定传递

如果一个字段只有在携带大段原文时才有意义，它更像临时注释，而不是稳定接口。

---

## 4. 硬字段

### 4.1 定义

硬字段是指：

- 一旦确认就不应轻易改动
- 会强约束后续叙事
- 一旦写错会造成高成本冲突
- 常作为一致性检查依据

### 4.2 特征

- 稳定性高
- 修改成本高
- 应有明确来源
- 重大修改通常需要记录到 `07_decisions/`

### 4.3 常见示例

#### WorkSpec

- `genre`
- `audience`
- `theme`
- `narration_mode`

#### WorldModel

- `world_type`
- `death_rule`
- `hard_rules`
- `consequence_rules`

#### CharacterModel

- `identity`
- `inner_need`
- `fear`
- `flaw`

#### FactLedger

- `statement`
- `fact_type`
- `chronological_order`

#### ForeshadowGraph

- `thread_id`
- `promise_statement`
- `narrative_importance`

#### ReviewIssue

- `issue_type`
- `violated_rule`

### 4.4 更新规则

硬字段只允许在以下情况下更新：

1. 初始定义明确错误
2. 项目方向整体重构
3. 有新事实正式覆盖旧版本
4. 作者明确决定版本迁移

### 4.5 处理建议

- 尽量避免自动更新
- 与已有引用强绑定时，应优先考虑版本化而不是直接覆盖

---

## 5. 可成长字段

### 5.1 定义

可成长字段是指：

- 会随着叙事推进发生变化
- 但变化不是瞬时场景状态
- 更像“关系变化”“角色阶段变化”“承诺阶段变化”

### 5.2 特征

- 允许阶段性更新
- 更新应可追踪
- 通常与章节推进、关系推进、成长推进有关

### 5.3 常见示例

#### CharacterModel

- `outer_goal`
- `self_image`
- `relations`
- `arc_stage`

#### WorkSpec

- `pacing`
- `hook_density`
- `soft_constraints`

#### ForeshadowGraph

- `status`
- `progress_stage`
- `urgency_to_payoff`

#### FactLedger

- `status`
- `visibility`
- `known_by`

### 5.4 更新规则

可成长字段通常允许：

- 在 arc 结束后更新
- 在关系转折后更新
- 在承诺推进节点后更新
- 在角色完成关键选择后更新

### 5.5 处理建议

- 可以自动更新，但要保留更新依据
- 最好能追溯到具体 `PlotUnit`
- 不应无理由跳变

---

## 6. 运行态字段

### 6.1 定义

运行态字段是指：

- 描述“当前局面”的字段
- 高频变化
- 强依赖当前时刻、当前冲突、当前场景
- 主要存在于 `NarrativeState`，也会少量存在于 `CharacterModel`

### 6.2 特征

- 生命周期短
- 与当前单元强绑定
- 通常在每个有效 `PlotUnit` 后检查更新

### 6.3 常见示例

#### NarrativeState

- `current_location`
- `active_characters`
- `primary_goal`
- `active_conflicts`
- `public_information`
- `hidden_information`
- `open_questions`
- `active_promises`

#### CharacterModel

- `short_term_goal`
- `knowledge_state`
- `misinformation`
- `available_resources`

### 6.4 更新规则

运行态字段应在每次有效推进后检查是否改变：

- 时间
- 地点
- 出场角色
- 当前目标
- 冲突压力
- 信息权限
- 情绪温度
- 当前开放问题

### 6.5 处理建议

- 可自动更新
- 应与 `PlotUnit.output_state_ref` 联动
- 不建议长期沉积在静态对象中不清理

---

## 7. 派生字段

### 7.1 定义

派生字段是指：

- 由其他字段综合推导得出
- 不一定需要主存
- 可以按需计算
- 主要服务于审查、排序、监控和辅助规划

### 7.2 特征

- 不属于原始设定
- 可以重新计算
- 不应替代原始字段

### 7.3 常见示例

- 当前局势危险指数
- 当前承诺遗失风险总分
- 当前章节冲突密度
- 某角色当前暴露风险等级
- 某线程最佳回收窗口逼近度

### 7.4 更新规则

派生字段一般不需要人工维护。

### 7.5 处理建议

- 优先按需计算
- 如需主存，应明确其来源和刷新时机
- 不要让派生字段反向覆盖原始字段

---

## 8. 备注字段

### 8.1 定义

备注字段是给作者或系统保留的补充说明区。

### 8.2 特征

- 不参与硬逻辑判断
- 不作为硬约束
- 主要用于记录尚未结构化的信息

### 8.3 常见示例

- `notes`
- `review_notes`
- `resolution_note`

### 8.4 处理建议

- 备注字段可以存在，但不应取代正式字段
- 关键逻辑不要只写在备注里

---

## 9. 字段更新责任

建议将字段更新责任分为五类：

1. 作者手动维护
2. 系统初始化写入
3. `PlotUnit` 推进后更新
4. 审查阶段更新
5. 改写阶段修复

### 9.1 作者手动维护

适用于：

- 项目方向
- 核心世界规则
- 核心角色定义
- 重大结构变更
- 版本迁移

典型字段：

- `WorkSpec.genre`
- `WorldModel.hard_rules`
- `CharacterModel.identity`
- `CharacterModel.inner_need`

### 9.2 系统初始化写入

适用于：

- 初始设定阶段就能明确的字段
- 长期稳定字段

典型字段：

- `WorldModel.world_type`
- `CharacterModel.role`
- `ForeshadowGraph.promise_statement`
- `FactLedger` 中的世界硬规则映射

### 9.3 PlotUnit 推进后更新

适用于：

- 当前状态
- 关系变化
- 信息变化
- 风险变化
- 承诺推进
- 事实建立

典型字段：

- `NarrativeState.*`
- `CharacterModel.short_term_goal`
- `CharacterModel.knowledge_state`
- `FactLedger.status`
- `FactLedger.known_by`
- `ForeshadowGraph.advancement_nodes`

### 9.4 审查阶段更新

适用于：

- 问题对象
- 推进强度
- 残余风险
- 合法性状态
- 承诺遗失风险

典型字段：

- `PlotUnit.progression_strength`
- `PlotUnit.legality_status`
- `ReviewIssue.*`

### 9.5 改写阶段修复

适用于：

- 已被 `ReviewIssue` 指向的失败对象
- 被错误写入的状态、事实、承诺或角色运行态

典型字段：

- `PlotUnit.key_decision`
- `NarrativeState.primary_goal`
- `FactLedger.known_by`
- `ForeshadowGraph.status`
- `CharacterModel.relations`

---

## 10. 工作流写回顺序

字段允许自动更新，不等于允许任意顺序更新。

当前建议固定以下写回顺序：

1. `PlotUnit`
2. `NarrativeState`
3. `FactLedger`
4. `ForeshadowGraph`
5. `CharacterModel`
6. `ReviewIssue` 或其他审查结果字段

### 10.1 顺序理由

- `PlotUnit` 定义本轮发生了什么
- `NarrativeState` 定义事件之后当前局势是什么
- `FactLedger` 只记录已经成立的硬事实
- `ForeshadowGraph` 记录本轮事件对承诺线程的影响
- `CharacterModel` 最后吸收已经落定的知识、关系和阶段变化
- `ReviewIssue` 最后负责问题分流，而不是充当事实主存

### 10.2 禁止做法

- `NarrativeState` 尚未明确前，先写 `FactLedger`
- `FactLedger` 尚未落定前，先改 `CharacterModel.knowledge_state`
- `ForeshadowGraph` 先推进，但本轮事件和事实层还没落定
- 相关对象未同步完成，就直接进入 `Review`

### 10.3 `CharacterModel` 多字段同步原则

当同一轮推进同时影响：

- `knowledge_state`
- `relations`
- `misinformation`
- `self_image`
- `arc_stage`

也不应把它理解为“五个字段都顺手改一下”。

当前建议至少遵守以下顺序：

1. 先确认哪些内容已进入 `FactLedger` 或当前 `NarrativeState`
2. 再区分哪些属于稳定认知负担、哪些属于稳定错误信念
3. 再区分哪些只是关系依据，哪些已经形成长期关系基底
4. 最后才判断 `self_image` 与 `arc_stage` 是否具备跨多轮、带代价、未快速回退的更新条件

这能避免：

- `misinformation` 被误写进 `knowledge_state`
- 关系依据被误写进 `relations`
- 成长依据被直接写进 `self_image` 或 `arc_stage`

---

### 10.4 工作流上下文包原则

字段不应只按“对象归属”思考，也应按“workflow 会如何打包和读取”思考。

当前建议：

- `Rebuild` 重点产出可压缩的静态记忆包与可运行状态包
- `Continue` 重点读取当前工作集与稳定约束包，并只写回发生变化的字段
- `Review` 重点读取判定所需字段，不应默默接管长期记忆写回
- `Rewrite` 重点按根因对象修复，再同步依赖字段

这意味着字段设计应尽量支持：

- 最小读取
- 最小写回
- 明确变更来源
- 跨 workflow 稳定传递

---

## 11. 自动更新与人工更新边界

### 11.1 允许自动更新的字段

这类字段通常可由系统根据 `PlotUnit` 或审查结果更新：

- `NarrativeState` 大部分字段
- `CharacterModel.short_term_goal`
- `CharacterModel.knowledge_state`
- `FactLedger.status`
- `FactLedger.known_by`
- `ForeshadowGraph.progress_stage`
- `ForeshadowGraph.status`
- `ReviewIssue.status`

### 11.2 不建议自动更新的字段

这类字段如果自动更新，容易破坏系统地基：

- `WorkSpec.genre`
- `WorkSpec.audience`
- `WorldModel.death_rule`
- `WorldModel.hard_rules`
- `CharacterModel.identity`
- `CharacterModel.inner_need`
- `CharacterModel.fear`
- `CharacterModel.flaw`
- `ForeshadowGraph.promise_statement`

### 11.3 必须人工确认后更新的字段

- 核心设定
- 世界规则
- 角色核心逻辑
- 项目目标
- 叙事模式

### 11.4 自动更新不等于任意覆盖

即使某字段允许自动更新，也仍应遵守两条边界：

1. 只能在它的主存对象中更新
2. 只能在上游对象已经明确后更新

例如：

- `FactLedger.known_by` 不应在对应事实尚未成立时先行更新
- `CharacterModel.knowledge_state` 不应反向覆盖 `FactLedger`
- `NarrativeState.open_questions` 不应代替 `ForeshadowGraph` 决定某线程是否正式建立

### 11.5 `CharacterModel` cross-field 禁止混写

以下内容当前建议禁止混写进同一个 `CharacterModel` 字段：

- 当前路线、当前战术判断写进 `knowledge_state`
- 主观押注写进 `knowledge_state`，而不是 `misinformation`
- “最近几轮都如何如何”这类证据说明写进 `relations`
- 一次失败后的自责或一次顺风后的自满写进 `self_image`
- “最近三轮都怎样，所以成长推进”这类依据说明写进 `arc_stage`

一句话说：

- `CharacterModel` 字段本体只保留长期结构
- supporting evidence 留在 `PlotUnit`、`NarrativeState`、handoff 或 review supporting context

### 11.6 不要把成长推进误写成误判清零

当 `self_image` 或 `arc_stage` 合法更新时，也不应自动假设：

- 相关旧 `misinformation` 已完全失效

如果旧误判在 rollback 或高压场景里仍会重新支配行为，它就仍应保留为：

- 稳定错误信念
- 或正在衰减但尚未退出的误判

换句话说：

- 成长推进
- 误判消退

可以相关，但不要求同轮完成。

### 11.7 不要把 supporting evidence 回流写进 `CharacterModel` 字段本体

当 repeated `Rebuild`、handoff 或第二次恢复发生时，也不应因为“证据已经很多、很稳定”就把 supporting evidence 写回：

- `knowledge_state`
- `relations`
- `misinformation`
- `self_image`
- `arc_stage`

这些字段本体应只保留：

- 长期认知负担
- 长期关系基底
- 稳定错误信念
- 稳定自我定义
- 阶段性成长结论

而不应同时吞进：

- 最近几轮的 sequence 描述
- 成长依据
- rollback 经过
- 当前任务策略
- 当前压力下的证据说明

换句话说：

- 字段结论留在 `CharacterModel`
- supporting evidence 留在 `PlotUnit`、`NarrativeState`、handoff supporting context 与 `Review` supporting context

如果为了防止 handoff 丢信息而把 supporting evidence 倒灌回字段正文，`CharacterModel` 就会在 repeated recovery 中重新膨胀成半个当前工作包。

---

## 12. 字段引用规则

### 12.1 总原则

对象之间优先使用 **ID 引用**，不要深层复制。

#### 正确做法

- `NarrativeState.active_characters` 引用 `CharacterModel.character_id`
- `PlotUnit.input_state_ref` 引用 `NarrativeState.state_id`
- `ForeshadowGraph.linked_facts` 引用 `FactLedger.fact_id`

#### 不建议做法

- 在多个对象里重复复制完整角色数据
- 在状态对象中嵌入完整世界模型
- 在问题对象中复制整条 `PlotUnit`

### 12.2 引用字段应尽量轻量

引用应优先包含：

- 对象类型
- 对象 ID
- 必要时加一个短标签

### 12.3 引用失效处理

若某对象被版本化、废弃或替代：

- 旧引用不直接删除
- 应保留历史关系
- 必要时标记为 `superseded` / `legacy`

---

## 13. 写入原则

### 13.1 能不写的字段就先不写

一个字段只有在满足以下至少一条时，才值得进入模型：

- 能约束叙事
- 能支持审查
- 能支持更新
- 能支持检索
- 能支持样例验证

### 13.2 不写重复含义字段

如果两个字段表达的是同一件事，优先保留一个。

#### 错误示例

- 同时写 `core_goal`、`main_goal`、`primary_goal`，但没有边界差异

### 13.3 不把长段文本当字段

字段应尽量短、明确、结构化。

#### 错误示例

- 用整段散文描述关系变化
- 用大段分析替代 `status`

### 13.4 不把解释混进事实

#### 错误示例

- `FactLedger.statement = 主角因为孤独所以终于信任了导师`

更适合拆成：

- 事实
- 推断
- 审查备注

---

## 14. 变更原则

### 14.1 轻微变更

适用于：

- 备注补充
- 拼写修正
- 非核心字段微调

通常不必进入决策日志。

### 14.2 中等变更

适用于：

- 关系字段调整
- 承诺推进状态更新
- 审查优先级调整

建议至少记录到实验层或进度层。

### 14.3 重大变更

适用于：

- 核心对象边界变化
- 世界规则变化
- 角色核心逻辑变化
- 核心承诺线程重写

建议：

- 写入 `07_decisions/`
- 必要时生成对象新版本

---

## 15. 禁止事项

以下做法建议禁止：

### 15.1 把推断字段写成硬字段

例如：

- `她已经爱上他`

若没有明确证据，不应写死。

### 15.2 把运行态长期写死

例如：

- 一直把 `current_goal` 写在角色静态模型里不更新

### 15.3 用备注字段替代正式结构

例如：

- 重要秘密只写在 `notes`
- 关键承诺只写在备注里而不建线程

### 15.4 同一事实多处主存

例如：

- 在 `NarrativeState`、`CharacterModel`、`FactLedger` 中都把同一硬事实当主记录层

### 15.5 不区分“谁知道”和“世界真相”

这会直接导致信息权限错乱。

---

## 16. 推荐的主存关系

建议把对象之间的“主存位置”定清楚。

### 16.1 顶层方向

主存：`WorkSpec`

### 16.2 世界规则原型

主存：`WorldModel`

确认被触发后，必要时映射到：`FactLedger`

### 16.3 角色核心结构

主存：`CharacterModel`

### 16.4 当前局势

主存：`NarrativeState`

### 16.5 推进行为

主存：`PlotUnit`

### 16.6 已成立事实

主存：`FactLedger`

### 16.7 叙事承诺与伏笔线程

主存：`ForeshadowGraph`

### 16.8 审查问题

主存：`ReviewIssue`

### 16.9 当前建议的冲突裁决优先级

当多个对象记录出现冲突时，当前建议按以下优先级处理：

1. `WorkSpec` / `WorldModel`
2. `FactLedger`
3. `CharacterModel` 与 `NarrativeState` 各自负责的主存内容
4. `ForeshadowGraph`
5. `PlotUnit`
6. `ReviewIssue`

具体解释：

- 顶层方向和世界合法性看 `WorkSpec` / `WorldModel`
- “世界中是否已经成立”看 `FactLedger`
- “角色长期结构是什么”看 `CharacterModel`
- “角色此刻处于什么局面”看 `NarrativeState`
- “承诺线程是否正式建立或推进”看 `ForeshadowGraph`
- `PlotUnit` 只定义本轮变化，不单独充当长期记录层
- `ReviewIssue` 只负责问题分流，不负责定义事实本体

---

## 17. 最小检查清单

当你写完一个 schema 或新增字段时，至少检查这 10 个问题：

1. 这个字段属于哪一类？
2. 它是硬字段、可成长字段、运行态字段、派生字段还是备注字段？
3. 它由谁写入？
4. 它由谁更新？
5. 它能否支持审查？
6. 它是否与其他字段重复？
7. 它是否放在了正确对象里？
8. 它是否真的需要主存？
9. 它的上游写回对象是谁？
10. 当它与其他对象冲突时，以谁为准？
11. 它属于长期稳定记忆、当前工作集、临时推断层，还是正式修复层？
12. 它能否在上下文压缩后仍然被后续 workflow 可靠理解？
13. 它最常由哪个 workflow 读取，又最常由哪个 workflow 写回？

---

## 18. 一句话总结

`Field Rules` 的任务，是为整个自动小说系统建立一套统一的字段治理规则，让所有对象都能在**边界清晰、更新可控、引用稳定、主存明确、冲突可裁决**的前提下持续演化。
