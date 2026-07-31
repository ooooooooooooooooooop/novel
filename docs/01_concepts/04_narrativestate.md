# NarrativeState

## 文档目的
定义叙事状态对象 `NarrativeState`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`NarrativeState` 是故事在某一时刻的**运行态快照**。

它描述的不是“这个世界本来是什么样”，也不是“角色总体设定是什么”，而是：

- 现在到了哪里
- 现在谁在场
- 现在什么最紧迫
- 现在谁知道什么
- 现在冲突压到什么程度
- 现在有哪些悬念仍在打开

可以把它理解为：

- 当前局势对象
- 故事运行态
- 当前叙事压力面板
- 下一步推进的起点

---

## 2. 它不是什么

`NarrativeState` 不是：

- `WorldModel`
- `CharacterModel`
- 长期事实总表
- 章节正文
- 大纲摘要
- 静态设定档案

它不负责回答“世界永远如何”，  
也不负责回答“角色本质上是谁”。

它只负责回答：

**“此时此刻，故事的实际运行条件是什么。”**

---

## 3. 它解决什么问题

`NarrativeState` 的存在，是为了防止系统一边生成，一边忘记“现在到底进行到哪”。

它主要解决这几类问题：

### 3.1 防止推进失焦
没有运行态，系统容易出现：
- 上一场刚打完，这一场情绪像没发生过
- 明明秘密刚暴露，下一场没人受影响
- 角色已经换地点，但行为像还在原地
- 当前最紧迫的问题被系统忽略

### 3.2 为 PlotUnit 提供输入状态
每个情节单元都必须从一个明确状态开始。  
如果没有 `NarrativeState`，系统只能“凭印象续写”。

### 3.3 管理当前信息权限
小说不是所有事实都立刻开放给每个人。  
`NarrativeState` 需要告诉系统：
- 读者当前知道什么
- 主视角当前知道什么
- 某角色当前知道什么
- 某秘密当前是否处于暴露边缘

### 3.4 管理当前冲突压力
当前推动故事往前走的，不是全书总目标，而是当下最紧迫的压力组合。

---

## 4. 核心定义

### 定义
`NarrativeState` 是对某一叙事时刻下，当前时空位置、参与角色、信息分布、冲突压力、目标结构和开放悬念的结构化表示。

### 一句话理解
它定义“故事现在正在什么局面里”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`WorldModel` + `CharacterModel` + `FactLedger`
→ 共同约束 `NarrativeState`

`NarrativeState`
→ 作为 `PlotUnit` 的输入
→ 影响 `ForeshadowGraph` 的状态更新
→ 进入 `ReviewIssue` 的判断

### 具体影响

#### 受 WorldModel 影响
- 当前地点意味着什么
- 当前行为是否受制度约束
- 当前风险是否在生效
- 当前资源是否可用

#### 受 CharacterModel 影响
- 当前谁在场
- 当前谁主导行动
- 当前谁在回避
- 当前谁知道真相

#### 受 FactLedger 影响
- 当前状态不能违背已确认事实
- 当前信息分布不能忘记已发生事件

#### 对 PlotUnit 的影响
- 决定下一单元从哪里起步
- 决定哪些行动合理
- 决定哪些冲突最有张力
- 决定哪些信息可释放

#### 对 ForeshadowGraph 的影响
- 某些伏笔在当前状态下变得可回收
- 某些承诺在当前状态下被延迟或强化

#### 对 ReviewIssue 的影响
- 审查器可据此判断是否：
  - 忘记前态
  - 跳过情绪后果
  - 错置冲突重点
  - 误放信息

---

## 6. 叙事状态的设计原则

### 6.1 它必须是运行态
它描述的是“现在”，不是“总设定”。

### 6.2 它必须能驱动下一步
一个好的 `NarrativeState` 应该天然指向：
- 下一步谁会行动
- 下一步什么冲突会先爆
- 下一步什么信息最危险

### 6.3 它必须能被更新
每个有效 `PlotUnit` 之后，`NarrativeState` 都应发生变化。

### 6.4 它必须包含压力信息
仅有地点和人物不够，还要知道当前压力来自哪里。

### 6.5 它必须管理信息边界
叙事张力很大程度来自“谁知道什么、谁不知道什么”。

---

## 7. 叙事状态建议包含的层

第一版建议把 `NarrativeState` 分成 7 层。

---

### 7.1 时空层

用于定义当前故事发生在什么时间、什么地点。

#### 典型内容
- current_time
- relative_time_marker
- current_location
- location_condition
- scene_context

#### 例子
- 夜半
- 王城禁街
- 黑水泽外围
- 天衡宗外门刑台
- 大雨封路状态

#### 作用
决定行动可行性、风险和氛围。

---

### 7.2 出场层

用于定义当前真正参与局势的人。

#### 典型内容
- active_characters
- absent_but_influential_characters
- pov_character
- local_power_holder

#### 作用
不是所有角色都在“当前局”里。  
系统要知道现在谁能直接行动，谁只能间接影响。

---

### 7.3 目标层

用于定义当前局势中的任务结构。

#### 典型内容
- primary_goal
- secondary_goals
- blocked_goals
- hidden_goals
- immediate_need

#### 作用
解释当前为什么不是去做别的事，而是先处理这个问题。

---

### 7.4 冲突层

用于定义当前最实际的张力来源。

#### 典型内容
- active_conflicts
- conflict_pressure
- opposition_sources
- urgency_level
- escalation_risk

#### 作用
告诉系统当前最能推动故事的力在哪里。

#### 冲突来源示例
- 对手在场
- 时间不够
- 身份快暴露
- 资源快耗尽
- 误会即将扩大
- 规则即将触发惩罚

---

### 7.5 信息层

用于定义当前信息权限分布。

#### 典型内容
- public_information
- restricted_information
- hidden_information
- reader_known_but_character_unknown
- character_known_but_reader_unknown
- misinformation_in_effect

#### 作用
决定悬念、误导、反转和对话策略。

---

### 7.6 情绪与关系层

用于定义当前局势中的情绪温度和关系张力。

#### 典型内容
- emotional_temperature
- trust_shifts_in_effect
- resentment_in_effect
- attraction_in_effect
- fear_in_effect
- shame_in_effect

#### 作用
避免场景只处理事件，不处理事件后的情绪惯性。

---

### 7.7 开放承诺层

用于定义当前仍处于打开状态的悬念、伏笔和未完成问题。

#### 典型内容
- open_questions
- active_foreshadowing
- near_payoff_items
- overdue_promises
- false_leads_in_effect

#### 作用
提醒系统：哪些东西不能忘，哪些东西已经接近兑现窗口。

---

## 8. 建议字段

### 8.1 基础标识字段

#### state_id
状态对象的唯一 ID。

#### parent_level
该状态属于哪个层级。

例如：
- book
- arc
- chapter
- scene

#### derived_from
该状态从哪个上一个状态演化而来。

---

### 8.2 时空字段

#### current_time
当前绝对或叙事时间点。

#### relative_time_marker
相对时间标记。

例如：
- 当夜
- 三日后
- 试炼开始前一刻

#### current_location
当前位置。

#### location_condition
地点当前条件。

例如：
- 封闭
- 暴雨
- 易暴露
- 受监视
- 灵压不稳

---

### 8.3 出场字段

#### active_characters
当前直接参与角色。

#### offstage_influencers
未出场但仍影响局势的角色或组织。

#### pov_character
当前主要视角角色。

#### action_leader
当前主动推动局面的人。

---

### 8.4 目标字段

#### primary_goal
当前最主要目标。

#### secondary_goals
次要目标列表。

#### blocked_goals
当前被阻断的目标。

#### hidden_goals
未明说但正在发挥作用的目标。

#### immediate_need
眼下立刻要解决的问题。

---

### 8.5 冲突字段

#### active_conflicts
当前冲突列表。

#### urgency_level
紧迫度，建议分级。

例如：
- low
- medium
- high
- critical

#### pressure_sources
压力来源列表。

#### escalation_risk
当前局势继续恶化的风险。

#### resolution_options
当前可见解决路径。

---

### 8.6 信息字段

#### public_information
当前公开信息。

#### private_information_map
当前私人信息分布图。

#### hidden_information
当前仍隐藏的信息。

#### misinformation_in_effect
当前仍在生效的误解或假消息。

#### exposure_edges
接近暴露边缘的秘密/事实。

---

### 8.7 情绪与关系字段

#### emotional_temperature
当前整体情绪温度。

例如：
- 平稳
- 压抑
- 敌对
- 暧昧
- 惊惧
- 失控前夜

#### dominant_feelings
当前主导情绪列表。

#### active_relation_tensions
当前正在起作用的关系张力。

#### trust_map_delta
与前一状态相比的信任变化。

---

### 8.8 开放承诺字段

#### open_questions
当前仍未回答的问题。

#### active_promises
当前仍有效的叙事承诺。

#### near_payoff_items
接近回收窗口的项目。

#### overdue_items
拖延过久的悬念或伏笔。

---

## 9. 字段分类建议

`NarrativeState` 的字段建议分三类。

### 9.1 当前事实字段
当前已成立的运行事实。

例如：
- current_location
- active_characters
- current_time
- public_information

### 9.2 当前推断字段
对当前局势的工作性判断。

例如：
- urgency_level
- escalation_risk
- emotional_temperature
- dominant_feelings

### 9.3 更新后对比字段
用于和上一状态比较的变化项。

例如：
- trust_map_delta
- goal_shift
- conflict_delta
- information_delta

---

## 10. NarrativeState 的更新原则

每个有效 `PlotUnit` 之后，`NarrativeState` 都应至少更新以下一项：

- 位置变化
- 出场角色变化
- 信息权限变化
- 关系张力变化
- 冲突压力变化
- 目标变化
- 悬念状态变化

如果一个 PlotUnit 结束后，`NarrativeState` 几乎没有变化，那么它很可能是无效推进或弱推进。

---

## 11. 判定标准

一个好的 `NarrativeState` 应满足以下条件。

### 11.1 可回答“现在在哪里”
系统应能明确当前时空位置和局势边界。

### 11.2 可回答“现在最紧迫的是什么”
系统应能识别当前优先冲突。

### 11.3 可回答“谁知道什么”
系统应能明确当前信息分布。

### 11.4 可回答“下一步最可能从哪里动”
系统应能据此生成下一单元，而不是盲目续写。

### 11.5 可回答“哪些后果还在生效”
系统应记住上一单元留下的情绪、关系和制度后果。

---

## 12. 常见错误

### 12.1 只记录地点和人物，不记录压力
错误例子：
- 只知道“主角在宗门”，不知道他此刻正面临什么风险。

### 12.2 忘记上一场的后果
错误例子：
- 刚发生背叛，下一场关系张力却归零。

### 12.3 信息边界模糊
错误例子：
- 某角色突然知道了自己不可能知道的内容。

### 12.4 情绪状态断裂
错误例子：
- 角色刚失去重要之人，下一场像没事发生过。

### 12.5 开放承诺无人追踪
错误例子：
- 某关键谜团刚被强化，下一段叙事却完全忘记。

---

## 13. 最小版本建议

第一版 `NarrativeState` 不需要很大。  
建议先保留这些最小字段：

- state_id
- parent_level
- current_time
- current_location
- active_characters
- pov_character
- primary_goal
- active_conflicts
- urgency_level
- public_information
- hidden_information
- emotional_temperature
- open_questions

只要这些字段稳定，已经足够支撑地基阶段。

---

## 14. 示例

```json id="m5j8jz"
{
  "state_id": "s_014_scene",
  "parent_level": "scene",
  "derived_from": "s_013_scene",
  "current_time": "试炼开始前夜",
  "relative_time_marker": "当夜子时后",
  "current_location": "黑水泽外围废弃驿亭",
  "location_condition": [
    "暴雨",
    "视线受阻",
    "附近有巡查队经过风险"
  ],
  "active_characters": ["c001", "c002", "c003"],
  "offstage_influencers": ["王城监察司", "天衡宗执法堂"],
  "pov_character": "c001",
  "action_leader": "c003",
  "primary_goal": "在不暴露身份的前提下拿到试炼令牌",
  "secondary_goals": [
    "确认 c002 是否仍值得信任"
  ],
  "blocked_goals": [
    "立刻返回宗门求证旧案"
  ],
  "hidden_goals": [
    "c003 想逼 c001 当场失控"
  ],
  "immediate_need": "在巡查队到来前做出交易或脱身",
  "active_conflicts": [
    "令牌争夺",
    "信任危机",
    "身份暴露风险"
  ],
  "urgency_level": "high",
  "pressure_sources": [
    "巡查队接近",
    "暴雨影响判断",
    "c003 持续试探"
  ],
  "escalation_risk": "若 c001 使用异常感知能力，将引发秘密暴露",
  "resolution_options": [
    "与 c002 临时合作",
    "强行夺取后撤离",
    "放弃令牌保命"
  ],
  "public_information": [
    "试炼名额有限",
    "c003 手上有一枚有效令牌"
  ],
  "private_information_map": {
    "c001": [
      "知道自己一旦情绪失控可能触发残魂反应"
    ],
    "c002": [
      "怀疑 c003 背后有人操控"
    ],
    "c003": [
      "知道巡查队会提前经过此地"
    ]
  },
  "hidden_information": [
    "令牌本身带有可追踪标记",
    "c002 曾替 c001 隐瞒过一次异常"
  ],
  "misinformation_in_effect": [
    "c001 误以为 c002 可能已经转向宗门执法堂"
  ],
  "exposure_edges": [
    "残魂护主反应",
    "旧地图来源",
    "与王城秘牢相关的记忆"
  ],
  "emotional_temperature": "压抑且敌对",
  "dominant_feelings": [
    "戒备",
    "羞耻",
    "怀疑"
  ],
  "active_relation_tensions": [
    "c001 对 c002 的信任摇摆",
    "c001 与 c003 的竞争升级"
  ],
  "trust_map_delta": {
    "c001->c002": -0.08,
    "c001->c003": -0.15
  },
  "open_questions": [
    "c002 到底站在哪边",
    "c003 背后是谁在指使",
    "令牌为什么会提前流出"
  ],
  "active_promises": [
    "被逐真相终将揭开",
    "残魂秘密会在高压场景下逼近暴露"
  ],
  "near_payoff_items": [
    "c002 曾替 c001 隐瞒异常的事实"
  ],
  "overdue_items": []
}
```

