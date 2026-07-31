# ForeshadowGraph

## 文档目的
定义伏笔图对象 `ForeshadowGraph`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`ForeshadowGraph` 是对小说中**伏笔、悬念、误导、承诺与回收关系**的结构化追踪系统。

它不只是记录“这里埋了个伏笔”，而是要记录：

- 这个伏笔是什么
- 它何时被建立
- 它向读者承诺了什么
- 它目前推进到哪一步
- 它计划如何回收
- 它是否已经过期、失效、变形或被遗忘

可以把它理解为：

- 叙事承诺追踪图
- 悬念生命周期系统
- 回收关系网络
- 长程张力管理器

---

## 2. 它不是什么

`ForeshadowGraph` 不是：

- 事实账本
- 普通剧情摘要
- 读后感
- 单纯的谜题列表
- 审稿意见集合

它不负责记录“已经成立的硬事实”，那是 `FactLedger` 的职责。  
它也不负责记录“当前局势”，那是 `NarrativeState` 的职责。

它只负责回答：

**“作品已经答应了读者什么，这些承诺现在走到哪一步了。”**

---

## 3. 它解决什么问题

`ForeshadowGraph` 的存在，是为了防止系统在长篇叙事里：

- 只会不断开新坑
- 忘记旧伏笔
- 突然回收，毫无铺垫
- 回收方式和建立方式不匹配
- 误把误导当真相
- 把应该慢慢逼近的承诺过早揭穿

它主要解决这几类问题：

### 3.1 防止承诺遗失
小说一旦提出问题、制造异常、暗示秘密，其实就在向读者做承诺。

### 3.2 防止回收突兀
伏笔不是“最后想起来再解释”，而是应有推进链。

### 3.3 防止误导失控
误导需要被管理，否则系统会把假线索写成真设定。

### 3.4 为长程结构提供稳定支架
一个长篇之所以能“吊着读者”，很大程度上靠承诺管理，而不是靠即时文风。

---

## 4. 核心定义

### 定义
`ForeshadowGraph` 是一个用于记录、连接和追踪叙事承诺、伏笔节点、推进节点、误导节点与回收节点的结构化图谱对象。

### 一句话理解
它定义“哪些坑已经挖了，怎么填，填到哪了”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`PlotUnit`
→ 建立 / 推进 / 回收 `ForeshadowGraph`

`ForeshadowGraph`
→ 反向约束后续 `PlotUnit`
→ 影响 `NarrativeState` 的开放问题层
→ 与 `FactLedger` 协作
→ 参与 `ReviewIssue`

### 具体影响

#### 与 PlotUnit 的关系
- 一个 PlotUnit 可以新增伏笔
- 可以推进已有伏笔
- 可以误导读者
- 可以回收承诺
- 可以延后兑现

#### 与 NarrativeState 的关系
- 当前有哪些开放问题
- 哪些承诺逼近回收窗口
- 哪些悬念已拖太久

#### 与 FactLedger 的关系
- `FactLedger` 记录“已经成立的事实”
- `ForeshadowGraph` 记录“尚未兑现或正在推进的承诺关系”
- 当伏笔被正式回收时，往往会同步生成新的事实

#### 与 ReviewIssue 的关系
- 审查器可据此判断：
  - 承诺遗失失败
  - 回收突兀失败
  - 误导失控失败
  - 铺垫不足失败

---

## 6. 设计原则

### 6.1 承诺优先于“神秘感”
不是所有神秘都值得追踪，只有会约束后续叙事的承诺才应进入图谱。

### 6.2 生命周期优先
伏笔不只是一个点，而是一个过程：
- 建立
- 推进
- 延迟
- 变形
- 回收 / 作废

### 6.3 连接优先于堆积
重点不是“有多少伏笔”，而是它们与哪些 PlotUnit、角色、事实、主题连接。

### 6.4 误导也要管理
假线索不是随手扔的烟雾弹，也应有来源、作用和终止条件。

### 6.5 回收应有匹配关系
回收方式应和伏笔建立时的级别、显著度、情绪权重匹配。

---

## 7. 建议包含的层

第一版建议把 `ForeshadowGraph` 分成 7 层。

---

### 7.1 承诺层

用于定义作品已经向读者建立了哪些预期。

#### 典型内容
- 主角身世会被解释
- 某段关系会迎来决裂或确认
- 某个异常现象终将有来源
- 某个制度性问题终将爆发

#### 作用
把“读者被吊住的东西”正式对象化。

---

### 7.2 伏笔节点层

用于定义具体的伏笔建立点。

#### 典型内容
- 一句不寻常对白
- 一个异常物品
- 一段不合理行为
- 一条被掩盖的历史
- 一个看似无关的细节

#### 作用
记录承诺从哪里开始被建立。

---

### 7.3 推进节点层

用于定义伏笔在中途被如何强化、偏转或收紧。

#### 典型内容
- 新证据出现
- 角色怀疑加深
- 读者信息边界改变
- 旧解释被推翻
- 新问题覆盖旧问题

#### 作用
避免伏笔“埋了就没动静”。

---

### 7.4 误导节点层

用于定义系统故意制造的错误方向。

#### 典型内容
- 假嫌疑人
- 错误身世解释
- 看似合理但最终无效的推论
- 被操纵的信息

#### 作用
管理悬念的复杂度，但防止误导被写成永久设定。

---

### 7.5 回收节点层

用于定义承诺如何被兑现。

#### 典型内容
- 真相揭露
- 关系确认
- 身份公开
- 规则解释
- 物品用途揭晓
- 伏笔转化为代价

#### 作用
确保回收有来源、有路径、有后果。

---

### 7.6 状态层

用于定义每个承诺/伏笔当前处于什么状态。

#### 状态示例
- open
- active
- delayed
- transformed
- resolved
- abandoned
- false_path

#### 作用
避免系统把所有伏笔当成一团未分类信息。

---

### 7.7 风险层

用于定义承诺管理中的危险点。

#### 典型内容
- overdue_risk：拖太久
- abrupt_payoff_risk：回收太突兀
- overexposure_risk：提前说穿
- duplication_risk：重复同类悬念
- collapse_risk：误导太多导致主线失焦

#### 作用
为审查提供风险预警。

---

## 8. 建议字段

### 8.1 基础标识字段

#### thread_id
承诺/伏笔线程唯一 ID。

#### thread_type
线程类型。

例如：
- identity
- relation
- mystery
- item
- world_rule
- betrayal
- prophecy
- hidden_past

#### title
短标题。

#### scope_level
作用范围。

例如：
- book
- arc
- chapter
- scene

---

### 8.2 承诺字段

#### promise_statement
该线程向读者建立的核心预期。

#### thematic_link
与主题的关联。

#### emotional_weight
情感权重。

#### narrative_importance
叙事重要度。

例如：
- core
- major
- support
- minor

---

### 8.3 建立字段

#### introduced_in
首次建立位置。

#### setup_nodes
建立节点列表。

#### setup_visibility
建立时的显性程度。

例如：
- explicit
- noticeable
- subtle
- hidden_from_reader

#### initial_reader_question
建立后读者最自然会问的问题。

---

### 8.4 推进字段

#### advancement_nodes
推进节点列表。

#### narrowing_events
缩小答案范围的事件。

#### expansion_events
扩大悬念范围的事件。

#### transformed_meaning
中途是否发生意义转向。

---

### 8.5 误导字段

#### false_paths
相关误导路径。

#### misinformation_sources
误导来源。

#### false_suspects_or_explanations
假解释列表。

#### misdirection_status
误导当前状态。

例如：
- active
- exposed
- retired

---

### 8.6 回收字段

#### payoff_nodes
回收节点列表。

#### payoff_mode
回收方式。

例如：
- reveal
- reversal
- emotional_confirmation
- consequence
- symbolic_payoff
- partial_payoff

#### payoff_quality_note
回收质量备注。

#### payoff_cost
回收是否伴随代价。

---

### 8.7 状态字段

#### status
当前状态。

例如：
- open
- active
- delayed
- transformed
- resolved
- abandoned
- false_path

#### progress_stage
推进阶段序号。

#### urgency_to_payoff
离回收窗口的迫近程度。

#### overdue_risk
拖延风险。

---

### 8.8 关联字段

#### linked_characters
关联角色。

#### linked_facts
关联事实 ID。

#### linked_plotunits
关联 PlotUnit ID。

#### linked_questions
关联开放问题。

#### dependency_threads
依赖其他承诺线程的项目。

---

### 8.9 审查字段

#### review_priority
审查优先级。

#### abrupt_payoff_risk
突兀回收风险。

#### forgotten_risk
被遗忘风险。

#### duplication_risk
与其他承诺重复风险。

#### notes
备注。

---

## 9. 字段分类建议

`ForeshadowGraph` 的字段建议分三类。

### 9.1 结构字段
描述这个承诺线程是什么。

例如：
- thread_id
- thread_type
- promise_statement
- narrative_importance

### 9.2 生命周期字段
描述它推进到哪了。

例如：
- setup_nodes
- advancement_nodes
- payoff_nodes
- status
- progress_stage

### 9.3 风险字段
描述它目前的管理风险。

例如：
- overdue_risk
- abrupt_payoff_risk
- forgotten_risk
- duplication_risk

---

## 10. 写入原则

不是所有“看起来有悬念”的内容都应进入 `ForeshadowGraph`。  
建议只有满足以下条件之一的内容才进入：

### 10.1 会约束后文
例如：
- 明确建立了一个未来必须回应的问题

### 10.2 会影响读者预期
例如：
- 某角色身份明显不对劲
- 某物品用途被刻意隐藏

### 10.3 会影响结构安排
例如：
- 这个承诺需要在后期特定位置回收

### 10.4 会影响审查判断
例如：
- 若长期不推进，将明显削弱作品

---

## 11. 更新原则

`ForeshadowGraph` 需要随着 PlotUnit 持续更新。

### 11.1 建立
当一个新承诺被明确提出时，新增线程或节点。

### 11.2 推进
当新证据、新异常、新误导出现时，更新推进节点。

### 11.3 转义
当线程意义改变时，标记 `transformed`。

### 11.4 部分回收
当只兑现了一部分时，保留线程但更新状态。

### 11.5 完整回收
当承诺被明确兑现时，标记 `resolved`。

### 11.6 放弃
若项目决定不再兑现，必须显式标记 `abandoned`，而不是默认遗忘。

---

## 12. 判定标准

一个好的 `ForeshadowGraph` 应满足以下条件。

### 12.1 能追踪承诺
系统应能知道自己答应过读者什么。

### 12.2 能追踪推进
系统应能知道某承诺是否长期没有新动作。

### 12.3 能追踪回收质量
系统应能判断一个回收是自然、突兀还是空泛。

### 12.4 能区分真线与假线
误导必须被管理，而不是污染事实层。

### 12.5 能支持审查
审查器可据此发现：
- 承诺遗失
- 铺垫不足
- 回收失衡
- 重复悬念

---

## 13. 常见错误

### 13.1 只记“有个伏笔”，不记承诺内容
错误例子：
- 只写“这里有伏笔”，但不知道它答应了什么。

### 13.2 建得多，推进少
错误例子：
- 前 20 章不断开问题，后面 50 章没有收紧。

### 13.3 回收时没有路径
错误例子：
- 真相突然揭露，但中间没有任何逼近过程。

### 13.4 误导和真相混账
错误例子：
- 假线索一直没有被澄清，最后系统自己也分不清。

### 13.5 所有伏笔权重都一样
错误例子：
- 核心身世谜团和一个普通配角的小秘密被同等管理。

---

## 14. 最小版本建议

第一版 `ForeshadowGraph` 不需要很大。  
建议先保留这些最小字段：

- thread_id
- thread_type
- promise_statement
- introduced_in
- setup_nodes
- advancement_nodes
- payoff_nodes
- status
- urgency_to_payoff
- linked_characters
- linked_plotunits
- forgotten_risk

只要这些字段稳定，已经足够支撑地基阶段。

---

## 15. 示例

```json id="r15f8s"
[
  {
    "thread_id": "fg_001",
    "thread_type": "identity",
    "title": "c001 的真实身世",
    "scope_level": "book",
    "promise_statement": "c001 的出身与体内残魂及王城旧案有关，未来必须揭示其来源与意义。",
    "thematic_link": ["身份认同", "命运", "代价"],
    "emotional_weight": 0.86,
    "narrative_importance": "core",
    "introduced_in": "chapter_01",
    "setup_nodes": [
      "主角对王城秘牢产生异常熟悉感",
      "残魂对旧地图有反应"
    ],
    "setup_visibility": "noticeable",
    "initial_reader_question": "主角到底是谁，为什么会和旧案有关？",
    "advancement_nodes": [
      "c002 提到主角被逐的流程异常",
      "王城旧档中出现与主角年龄相符的失踪记录"
    ],
    "narrowing_events": [
      "残魂并非随机寄宿，而像是主动绑定"
    ],
    "expansion_events": [
      "旧案牵涉到监察司和宗门联合封口"
    ],
    "transformed_meaning": "从个人身世谜团扩大为制度性秘密",
    "false_paths": [
      "主角可能只是某位大人物的私生子"
    ],
    "misinformation_sources": [
      "民间传闻",
      "c003 的刻意误导"
    ],
    "false_suspects_or_explanations": [
      "单纯血统问题"
    ],
    "misdirection_status": "active",
    "payoff_nodes": [],
    "payoff_mode": null,
    "payoff_quality_note": null,
    "payoff_cost": null,
    "status": "active",
    "progress_stage": 2,
    "urgency_to_payoff": "medium",
    "overdue_risk": "low",
    "linked_characters": ["c001", "c002", "c003"],
    "linked_facts": ["f_015"],
    "linked_plotunits": ["pu_scene_014"],
    "linked_questions": [
      "主角为什么会对秘牢有记忆残响",
      "残魂为何与王城旧案相关"
    ],
    "dependency_threads": ["fg_003"],
    "review_priority": "critical",
    "abrupt_payoff_risk": "medium",
    "forgotten_risk": "low",
    "duplication_risk": "low",
    "notes": "全书核心承诺线程之一"
  },
  {
    "thread_id": "fg_002",
    "thread_type": "relation",
    "title": "c002 是否会替 c001 保密",
    "scope_level": "arc",
    "promise_statement": "c002 已察觉 c001 的异常，后续必须回答他会保护、利用还是揭发对方。",
    "thematic_link": ["信任", "依赖", "风险交换"],
    "emotional_weight": 0.73,
    "narrative_importance": "major",
    "introduced_in": "scene_014",
    "setup_nodes": [
      "c002 确认异常力量痕迹",
      "c001 仍试图隐瞒"
    ],
    "setup_visibility": "explicit",
    "initial_reader_question": "c002 会不会把秘密说出去？",
    "advancement_nodes": [],
    "narrowing_events": [],
    "expansion_events": [],
    "transformed_meaning": null,
    "false_paths": [],
    "misinformation_sources": [],
    "false_suspects_or_explanations": [],
    "misdirection_status": "retired",
    "payoff_nodes": [],
    "payoff_mode": null,
    "payoff_quality_note": null,
    "payoff_cost": null,
    "status": "open",
    "progress_stage": 1,
    "urgency_to_payoff": "high",
    "overdue_risk": "medium",
    "linked_characters": ["c001", "c002"],
    "linked_facts": ["f_015"],
    "linked_plotunits": ["pu_scene_014"],
    "linked_questions": [
      "c002 的立场会如何变化"
    ],
    "dependency_threads": [],
    "review_priority": "high",
    "abrupt_payoff_risk": "low",
    "forgotten_risk": "medium",
    "duplication_risk": "low",
    "notes": "适合作为近中期关系推进节点"
  }
]
```

