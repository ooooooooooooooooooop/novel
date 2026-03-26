# 模型边界决策

## 文档目的
本文件用于收束当前阶段已经基本确定的对象边界相关决策。

它关注的不是某个字段怎么写，而是更底层的问题：

- 哪个对象负责记录什么
- 哪个对象不应该承担什么职责
- 对象之间如何分工
- 为什么一些看似相近的内容必须拆开
- 当信息重复出现时，主存应该放在哪里

本文件的作用，是防止后续扩展时出现职责重叠、多处主存、运行态和静态层混写、事实与承诺混写，以及推进单元与状态对象混写。

---

## 1. 文档定位

[01_foundation_decisions.md](d:\Desktop\novel\docs\07_decisions\01_foundation_decisions.md) 收束的是地基总方向。  
本文件收束的是核心对象之间的边界。

它主要影响：

- `01_concepts/`
- `02_data_models/`
- `03_rules/`
- `04_workflows/`
- `05_examples/`

尤其影响：

- 对象是否会不断膨胀
- 工作流是否会因为职责不清而混乱
- 审查时能否明确追责到正确对象

---

## 2. 当前需要固定的边界问题

当前最值得固定的边界主要有 7 个：

1. `CharacterModel` 与 `NarrativeState` 的边界
2. `PlotUnit` 与 `NarrativeState` 的边界
3. `PlotUnit` 与 `FactLedger` 的边界
4. `FactLedger` 与 `ForeshadowGraph` 的边界
5. `CharacterModel.relations` 与 `FactLedger relation` 的边界
6. `WorldModel` 与 `FactLedger world_rule` 的边界
7. `ReviewIssue` 与普通审查备注的边界

---

## 3. DEC-20260326-09

### 决策标题

`CharacterModel` 记录角色结构，`NarrativeState` 记录角色此刻处境。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

在设计角色与状态时，最容易混的是：

- 当前目标写在哪
- 当前情绪写在哪
- 当前在场与否写在哪
- 当前知道什么写在哪
- 长期恐惧和短期反应怎么区分

如果不分清，就会出现两种坏结果：

1. `CharacterModel` 变成不断膨胀的运行态容器
2. `NarrativeState` 变成重复复制角色信息的大缓存

### 备选方案

- 方案 A：把角色的大部分当前状态都放进 `CharacterModel`
- 方案 B：`CharacterModel` 保留角色结构，`NarrativeState` 负责当前局势中的运行态

### 最终选择

采用方案 B。

### 选择理由

`CharacterModel` 负责：

- 身份
- 外在目标结构
- 内在需求
- 恐惧
- 缺陷
- 盲区
- 关系长期基底
- 成长弧方向
- 可成长字段

`NarrativeState` 负责：

- 当前谁在场
- 当前主目标是什么
- 当前冲突是什么
- 当前信息分布是什么
- 当前情绪温度是什么
- 当前开放问题是什么

这样分工有四个直接好处：

1. `CharacterModel` 更专注解释“这个人为什么会这么选”
2. `NarrativeState` 更专注描述“现在的局是什么”
3. 同一个角色进入不同局势时，不必每次都污染角色档案
4. 审查时更容易区分是角色结构失真，还是当前状态没更新

### 影响范围

- [03_charactermodel.md](d:\Desktop\novel\docs\01_concepts\03_charactermodel.md)
- [04_narrativestate.md](d:\Desktop\novel\docs\01_concepts\04_narrativestate.md)
- 对应 schema
- 续写 workflow
- 角色一致性规则

### 风险 / 待验证项

- `knowledge_state` 既可能像角色结构，又可能像当前运行态，需要继续压边界
- 后续需通过连续续写实验验证：两者分工是否足够稳定

### 后续动作

`watch`

---

## 4. DEC-20260326-10

### 决策标题

`PlotUnit` 记录这一步怎么发生，`NarrativeState` 记录这一步之后局势变成什么。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

`PlotUnit` 和 `NarrativeState` 都会涉及：

- 当前目标
- 当前冲突
- 当前参与者
- 状态变化

所以很容易混成：

- 一个对象重复写全过程
- 另一个对象只剩下壳

### 备选方案

- 方案 A：让 `PlotUnit` 自己承担大部分状态信息，`NarrativeState` 弱化
- 方案 B：`PlotUnit` 只负责一次推进的因果结构，`NarrativeState` 负责该推进前后的局势快照

### 最终选择

采用方案 B。

### 选择理由

`PlotUnit` 负责：

- 输入状态引用
- 目标
- 关键决策
- 冲突与约束
- 事件发生
- 输出状态引用
- 状态变化摘要

`NarrativeState` 负责：

- 某一时刻的局势全貌
- 当前主目标
- 当前冲突
- 当前信息权限
- 当前情绪温度
- 当前活跃承诺

这能保证：

1. `PlotUnit` 的本体始终是状态转移过程
2. `NarrativeState` 的本体始终是时刻快照
3. 续写和审查都有明确运行起点

### 影响范围

- [04_narrativestate.md](d:\Desktop\novel\docs\01_concepts\04_narrativestate.md)
- [05_plotunit.md](d:\Desktop\novel\docs\01_concepts\05_plotunit.md)
- 对应 schema
- 状态转移规则
- Continue Workflow

### 风险 / 待验证项

- `state_change_summary` 和输出状态字段之间的边界，仍需通过更多样例校正

### 后续动作

`keep`

---

## 5. DEC-20260326-11

### 决策标题

`PlotUnit` 记录发生了什么变化，`FactLedger` 记录哪些变化已经成为硬事实。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

`PlotUnit` 和 `FactLedger` 都会提到：

- 谁拿到了什么
- 谁知道了什么
- 关系怎么变了
- 风险怎么变了

容易出现的问题是：

- 一次变化既写在 `PlotUnit`，又写在 `FactLedger`，但不知道谁是主存
- 后续修改 `PlotUnit` 时，账本忘了同步

### 备选方案

- 方案 A：让 `PlotUnit` 承担全部变化记录，账本只做少量补充
- 方案 B：`PlotUnit` 负责“这次变了什么”，`FactLedger` 负责“哪些变化已经成为可约束后文的硬事实”

### 最终选择

采用方案 B。

### 选择理由

`PlotUnit` 负责：

- 本次推进的状态变化摘要
- 谁做了什么
- 事件如何发生
- 变化方向是什么

`FactLedger` 负责：

- 已正式成立的资源归属
- 已正式成立的知情状态
- 已正式成立的事件后果
- 已正式成立的关系状态
- 已正式成立的世界 / 制度触发结果

核心理由是：

1. `PlotUnit` 是过程记录
2. `FactLedger` 是跨单元连续性约束层
3. 并不是 `PlotUnit` 里每个变化都值得长期记账

### 影响范围

- [05_plotunit.md](d:\Desktop\novel\docs\01_concepts\05_plotunit.md)
- [06_factledger.md](d:\Desktop\novel\docs\01_concepts\06_factledger.md)
- 对应 schema
- Continue Workflow
- Review Workflow

### 风险 / 待验证项

- 关系变化哪些该入账、哪些只留在运行态，后续仍需更多样例

### 后续动作

`watch`

---

## 6. DEC-20260326-12

### 决策标题

`FactLedger` 只记录已经算数的东西，`ForeshadowGraph` 只记录未来必须回应的东西。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

很多内容既像事实又像承诺，例如：

- `c002` 看见了异常
- 读者会想知道 `c002` 会不会保密

这两者常常在叙事上同时发生，但不能放进同一个层。

### 备选方案

- 方案 A：事实和承诺共存于单一对象
- 方案 B：继续严格拆分，并明确各自主存责任

### 最终选择

采用方案 B。

### 选择理由

`FactLedger` 负责：

- `c002` 看见了异常
- 令牌归属已改变
- 旧伤已加重
- 追踪概率已提高

`ForeshadowGraph` 负责：

- `c002` 是否会保密
- 残魂秘密会不会正式揭露
- 旧案线何时继续收紧
- 误导路径何时揭穿

这能保证：

1. 事实是已经成立
2. 承诺是未来必须回应
3. 同一事件可以同时写入两个对象，但内容和用途不同

### 影响范围

- FactLedger / ForeshadowGraph 的所有 schema 与 workflow
- 信息释放规则
- 伏笔规则

### 风险 / 待验证项

- 某些局势事实与承诺推进节点容易相邻出现，后续仍需样例压边界

### 后续动作

`keep`

---

## 7. DEC-20260326-13

### 决策标题

`CharacterModel.relations` 记录长期关系基底，`FactLedger relation` 记录已成立的关键关系事实。

### 决策类型

`model`

### 决策状态

`provisional`

### 背景问题

关系信息目前会同时出现在：

- `CharacterModel.relations`
- `FactLedger` 的 relation 条目
- `PlotUnit.relation_shift`
- `NarrativeState` 的当前关系张力

这是最容易重复和混乱的一块。

### 备选方案

- 方案 A：所有关系都只保存在 `CharacterModel`
- 方案 B：关系分层存储，不同对象负责不同粒度

### 最终选择

采用方案 B，但目前仍视为 `provisional`，需要继续压实。

### 选择理由

`CharacterModel.relations` 负责：

- 长期关系基底
- 相对稳定的信任 / 依赖 / 冲突 / 情感权重
- 角色对他人的结构性态度

`PlotUnit.relation_shift` 负责：

- 本次推进里关系怎么偏移

`NarrativeState` 负责：

- 当前局里的关系张力是否已成为主冲突组成部分

`FactLedger relation` 负责：

- 已成立、会强约束后文的关系状态事实
- 例如已形成保密共同体、已正式决裂、已明确公开结盟

这样分层虽然复杂，但更符合关系在小说里的真实运行方式。

### 影响范围

- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`

### 风险 / 待验证项

- 这仍是当前对象层最脆弱的边界之一
- 后续实验应专门验证：
  - 关系跳变时，哪个对象先改
  - 关系确认时，何时入账本

### 后续动作

`re-evaluate`

---

## 8. DEC-20260326-14

### 决策标题

`WorldModel` 记录世界规则原型，`FactLedger` 记录当前项目中已经被调用或成立的世界事实。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

一些世界内容既像设定，又像事实，例如：

- 禁术会留下痕迹
- 当前这个角色已经留下痕迹
- 王城内禁止斗法
- 某次斗法已触发监察风险

### 备选方案

- 方案 A：世界规则全部只放 `WorldModel`
- 方案 B：世界规则原型放 `WorldModel`，而当前被触发 / 被调用 / 被证明有效的具体实例进入 `FactLedger`

### 最终选择

采用方案 B。

### 选择理由

`WorldModel` 负责：

- 规则原型
- 资源分布逻辑
- 制度结构
- 环境威胁
- 后果机制
- 升级路径

`FactLedger` 负责：

- 哪条规则在当前剧情里已经被具体触发
- 哪种风险已经进入当前局
- 哪个后果已经被激活
- 哪种权限当前已生效 / 失效

这样既避免世界模型被运行细节污染，也避免运行层失去世界依托。

### 影响范围

- 世界合法性规则
- FactLedger schema
- Continue Workflow
- Review Workflow

### 风险 / 待验证项

- 仍需继续验证：哪些世界规则值得映射进账本，哪些不必

### 后续动作

`watch`

---

## 9. DEC-20260326-15

### 决策标题

`ReviewIssue` 只记录正式问题对象，普通审查备注不自动升级为 issue。

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

审查过程中会产生很多层次不同的反馈：

- 明确错误
- 高风险预警
- 轻量提醒
- 风格建议
- 可能未来会变坏的点

如果全部都建成 `ReviewIssue`，系统会很快出现问题单泛滥；如果全部都不建单，又会失去闭环能力。

### 备选方案

- 方案 A：所有审查发现都建 `ReviewIssue`
- 方案 B：只有正式问题建单，预警和轻量提醒留在 `review_notes` 或 reminder 层

### 最终选择

采用方案 B。

### 选择理由

`ReviewIssue` 负责：

- 已成立的正式问题
- 需要排序、修复、关闭的问题
- 阻断型或结构型问题
- 明确需要进入改写或重规划的问题

`review_notes` / reminder 负责：

- 还没坏，但短期必须注意的点
- 近程后果兑现提醒
- 轻量风格提醒
- 非阻断型观察项

这样能保证 issue 保持信号价值，不被提醒层淹没。

### 影响范围

- `Review Workflow`
- `ReviewIssue Schema`
- 审查样例
- 改写 workflow

### 风险 / 待验证项

- reminder 层目前还未完全独立建模，暂时依赖 `review_notes` 和低级 issue 表达

### 后续动作

`patch`

---

## 10. 当前对象边界的主存原则

基于以上决策，当前建议的主存关系如下：

- `WorkSpec`：作品方向与顶层约束
- `WorldModel`：世界规则原型与秩序结构
- `CharacterModel`：角色决策结构与长期关系基底
- `NarrativeState`：当前局势快照
- `PlotUnit`：一次推进的因果过程
- `FactLedger`：已成立的硬事实与可约束后文的状态
- `ForeshadowGraph`：未来必须回应的承诺与回收线程
- `ReviewIssue`：正式问题对象

---

## 11. 当前最不稳定的边界

虽然大部分对象边界已经清晰，但以下 3 块仍是高风险区域：

### 11.1 关系信息的多层分布

容易在 `CharacterModel`、`NarrativeState`、`PlotUnit`、`FactLedger` 之间重复或漂移。

### 11.2 知情状态的主存位置

`CharacterModel.knowledge_state` 与 `FactLedger.known_by` 的边界还需要持续实验。

### 11.3 局势事实是否应入账本

例如主目标切换、撤离压力升级，这类内容入账本的粒度仍需继续试。

---

## 12. 后续动作建议

这个文件写完后，下一步最自然的是补：

`07_decisions/03_workflow_order_decisions.md`

重点收束：

- Rebuild / Continue / Review / Rewrite 的顺序关系
- 为什么续写后必须审查
- 为什么改写必须由问题对象驱动
- 什么时候局部改写要升级成重规划

这样决策层就会从对象边界进一步进入流程边界。

---

## 13. 一句话总结

`02_model_boundary_decisions.md` 的作用，是把这套系统里最容易互相侵占职责的对象边界固定下来，确保后面继续扩展时，系统不会变成每个对象都什么都记一点，最后谁也说不清自己到底负责什么。
