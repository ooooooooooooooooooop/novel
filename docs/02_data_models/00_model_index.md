# 数据模型总览

## 文档目的
本文件作为 `02_data_models/` 目录的总入口，统一说明自动小说系统中 8 个核心对象的数据建模方式、依赖关系、字段分类原则与更新责任。

它不替代各对象的 schema 文档，而是提供：

- 总体结构图
- 对象之间的引用关系
- 字段分类标准
- 更新与写入原则
- 建模阶段的优先顺序

---

## 1. 建模目标

本项目的数据模型不是为了“存文本”，而是为了存放：

- 可约束叙事的结构
- 可更新的运行状态
- 可审查的事实与问题
- 可追踪的伏笔与承诺
- 可复用的作品规格与角色逻辑

因此，本目录下的数据模型应优先支持以下能力：

1. 连续性维护
2. 合法性检查
3. 状态转移
4. 审查与修正
5. 长程记忆
6. 示例化验证

---

## 2. 核心对象清单

当前系统使用以下 8 个核心对象：

1. `WorkSpec`
2. `WorldModel`
3. `CharacterModel`
4. `NarrativeState`
5. `PlotUnit`
6. `FactLedger`
7. `ForeshadowGraph`
8. `ReviewIssue`

---

## 3. 对象职责总览

| 对象 | 主要职责 | 回答的问题 |
|---|---|---|
| `WorkSpec` | 定义作品目标与全局约束 | 这本书要长成什么样？ |
| `WorldModel` | 定义世界规则、秩序、资源与代价 | 这个世界允许什么发生？ |
| `CharacterModel` | 定义角色作为决策体的逻辑 | 这个人为什么会这样做？ |
| `NarrativeState` | 定义当前运行态 | 故事现在进行到哪里？ |
| `PlotUnit` | 定义一次有效推进 | 这次推进改变了什么？ |
| `FactLedger` | 记录已确认事实 | 哪些东西已经算数了？ |
| `ForeshadowGraph` | 追踪承诺、伏笔、误导与回收 | 哪些坑已经挖了，填到哪了？ |
| `ReviewIssue` | 记录审查中发现的问题 | 系统哪里坏了，怎么修？ |

---

## 4. 对象依赖顺序

建议采用以下依赖顺序理解整个系统：

```text
WorkSpec
  ↓
WorldModel + CharacterModel
  ↓
NarrativeState
  ↓
PlotUnit
  ↓
FactLedger + ForeshadowGraph
  ↓
ReviewIssue
```

### 含义说明

- `WorkSpec` 提供顶层方向和约束
- `WorldModel` 与 `CharacterModel` 提供可运行的世界与行动者
- `NarrativeState` 表示当前时刻的运行局面
- `PlotUnit` 负责从前态推进到后态
- `FactLedger` 与 `ForeshadowGraph` 负责把推进结果记账
- `ReviewIssue` 负责指出哪里失真、失效或失控

---

## 5. 数据流总览

### 5.1 初始化阶段

初始化阶段主要建立静态或半静态对象：

- `WorkSpec`
- `WorldModel`
- `CharacterModel`

### 5.2 运行阶段

运行阶段主要反复读写：

- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`

### 5.3 审查阶段

审查阶段主要产出：

- `ReviewIssue`

### 5.4 修正阶段

修正阶段会反向影响：

- `PlotUnit`
- `NarrativeState`
- `FactLedger`
- `ForeshadowGraph`

必要时也会反向修正 `CharacterModel` 或 `WorldModel`。

---

## 6. 字段分类规则

所有对象中的字段，建议统一分为 4 类。

### 6.1 硬字段

一旦确认，不应轻易变动。

特征：

- 约束性强
- 变更代价高
- 常作为一致性检查依据

例子：

- `WorkSpec.genre`
- `WorldModel.hard_rules`
- `CharacterModel.identity`
- `FactLedger.statement` 中的已确认死亡或血缘

### 6.2 可成长字段

会在叙事推进中逐步变化，但变化应可追踪。

特征：

- 不是运行态瞬时值
- 但也不是永远固定
- 常用于角色成长、关系变化、势力变化

例子：

- `CharacterModel.arc_stage`
- `CharacterModel.relations`
- `ForeshadowGraph.status`
- `FactLedger.status`

### 6.3 运行态字段

只在当前叙事阶段有效，并会频繁更新。

特征：

- 强依赖当前局势
- 常由 `PlotUnit` 推进后更新
- 属于运行态快照内容

例子：

- `NarrativeState.current_location`
- `NarrativeState.primary_goal`
- `NarrativeState.active_conflicts`
- `NarrativeState.emotional_temperature`

### 6.4 派生字段

不是人工直接设定，而是由其他字段综合得出。

特征：

- 可计算或可推断
- 应尽量避免手工硬写死
- 主要用于辅助审查与规划

例子：

- 推荐钩子密度
- 当前冲突强度等级
- 承诺遗失风险
- 回收迫近程度

---

## 7. 对象写入原则

### 7.1 WorkSpec

由项目初始化写入，后续仅允许小幅人工修订。

### 7.2 WorldModel

初始化为主，后续仅在世界新规则被正式确认时补充。

### 7.3 CharacterModel

初始化后持续维护，尤其是：

- 关系变化
- 成长阶段
- 信息权限
- 当前目标偏移

### 7.4 NarrativeState

每个有效 `PlotUnit` 之后都应更新。

### 7.5 PlotUnit

每次有效推进都应新增一个单元对象。

### 7.6 FactLedger

只有“已成立并足以约束后文”的内容才写入。

### 7.7 ForeshadowGraph

只有“已向读者建立预期或会影响后续结构”的内容才写入。

### 7.8 ReviewIssue

只有满足正式审查条件的问题才建单，不把所有细碎意见都写成 issue。

---

## 8. 对象之间的引用关系

建议采用“对象 ID + 轻量引用”的方式，而不是深层复制嵌套。

### 8.1 NarrativeState 推荐引用

- `active_characters` → `CharacterModel.character_id`
- `linked_open_threads` → `ForeshadowGraph.thread_id`
- `current_facts_in_scope` → `FactLedger.fact_id`

### 8.2 PlotUnit 推荐引用

- `input_state_ref` → `NarrativeState.state_id`
- `output_state_ref` → `NarrativeState.state_id`
- `active_characters` → `CharacterModel.character_id`
- `active_promises_in_scope` → `ForeshadowGraph.thread_id`

### 8.3 FactLedger 推荐引用

- `involved_entities` → 角色 / 地点 / 组织 / 物品 ID
- `source_plotunit` → `PlotUnit.unit_id`

### 8.4 ForeshadowGraph 推荐引用

- `linked_characters` → `CharacterModel.character_id`
- `linked_facts` → `FactLedger.fact_id`
- `linked_plotunits` → `PlotUnit.unit_id`

### 8.5 ReviewIssue 推荐引用

- `object_id` → 被指出问题的对象 ID
- `plotunit_ref` → `PlotUnit.unit_id`
- `affected_threads` → `ForeshadowGraph.thread_id`
- `supporting_facts` / `contradictory_facts` → `FactLedger.fact_id`

---

## 9. 对象边界原则

### 9.1 WorkSpec 与 WorldModel

- `WorkSpec` 负责作品级方向
- `WorldModel` 负责世界级规则
- 不要把世界设定细节塞进 `WorkSpec`

### 9.2 CharacterModel 与 NarrativeState

- `CharacterModel` 负责角色长期逻辑
- `NarrativeState` 负责角色当前处境
- 不要把“当前情绪”长期写死在角色模型里

### 9.3 FactLedger 与 ForeshadowGraph

- `FactLedger` 记录已确认事实
- `ForeshadowGraph` 记录尚在推进或等待回收的承诺
- 不要把“悬念”写成“事实”

### 9.4 PlotUnit 与 ReviewIssue

- `PlotUnit` 负责记录推进
- `ReviewIssue` 负责指出推进中的问题
- 不要把问题描述混进推进对象本身

---

## 10. MVP 建模优先级

建议按以下顺序建立 schema。

### 第一优先

- `WorkSpec`
- `WorldModel`
- `CharacterModel`

原因：它们构成系统的静态底座。

### 第二优先

- `NarrativeState`
- `PlotUnit`

原因：它们构成运行主链路。

### 第三优先

- `FactLedger`
- `ForeshadowGraph`

原因：它们构成长程连续性与承诺管理。

### 第四优先

- `ReviewIssue`

原因：它依赖前面对象的稳定性。

---

## 11. 建模约束

### 11.1 先保证概念稳定，再扩字段

不要因为“以后可能有用”就过早添加过多字段。

### 11.2 每个对象优先保留最小可用字段集

先保证能跑通一个 mock case，再扩展复杂度。

### 11.3 每个字段都要能回答“它服务于什么”

若一个字段不能支持生成、审查、更新或检索，就暂不加入。

### 11.4 尽量避免混合字段

例如：

- 不要把“事实 + 解释 + 情绪”塞进同一字段
- 不要把“角色关系 + 当前状态变化”写成一个静态值

---

## 12. 目录对应关系

本目录下建议按以下文件拆分：

- `01_workspec_schema.md`
- `02_worldmodel_schema.md`
- `03_charactermodel_schema.md`
- `04_narrativestate_schema.md`
- `05_plotunit_schema.md`
- `06_factledger_schema.md`
- `07_foreshadowgraph_schema.md`
- `08_reviewissue_schema.md`
- `09_field_rules.md`

---

## 13. 最小检查清单

当一个对象 schema 初稿写完后，至少检查以下问题：

- 这个对象的字段是否和概念文档一致？
- 这些字段是否能支撑该对象的主要职责？
- 是否混入了其他对象的职责？
- 是否区分了硬字段、运行态字段和派生字段？
- 是否方便后续引用和更新？
- 是否能服务于至少一个 mock case？

---

## 14. 一句话总结

本目录的任务，不是把对象写得复杂，而是把自动小说系统中最核心的 8 个对象，建成一组边界清晰、关系稳定、可更新、可审查、可复用的数据结构。
