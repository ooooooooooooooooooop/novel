# NarrativeState Schema

## 文档目的
将 `01_concepts/04_narrativestate.md` 中的概念定义，压缩为可操作的数据结构说明。

本文件关注：

- 字段列表
- 字段类型
- 必填/选填
- 字段分类
- 合法取值建议
- 更新规则
- 最小版本建议

---

## 1. 对象名称

`NarrativeState`

---

## 2. Schema 目标

`NarrativeState` 用于定义故事在某一时刻的运行态。

它应支持系统回答：

- 现在故事发生在什么时间、什么地点
- 现在谁在场，谁虽未出场但仍在影响局势
- 现在最主要的目标是什么
- 现在最紧迫的冲突和压力是什么
- 现在谁知道什么，谁不知道什么
- 现在有哪些悬念仍然处于打开状态
- 现在的情绪和关系张力是什么

它不是静态设定表，而是一个会随着 `PlotUnit` 推进而不断更新的运行态对象。

---

## 3. 顶层结构

```json
{
  "state_id": "",
  "parent_level": "",
  "derived_from": "",
  "current_time": "",
  "relative_time_marker": "",
  "current_location": "",
  "location_condition": [],
  "scene_context": "",
  "active_characters": [],
  "offstage_influencers": [],
  "pov_character": "",
  "action_leader": "",
  "primary_goal": "",
  "secondary_goals": [],
  "blocked_goals": [],
  "hidden_goals": [],
  "immediate_need": "",
  "active_conflicts": [],
  "urgency_level": "",
  "pressure_sources": [],
  "escalation_risk": "",
  "resolution_options": [],
  "public_information": [],
  "private_information_map": {},
  "hidden_information": [],
  "misinformation_in_effect": [],
  "exposure_edges": [],
  "emotional_temperature": "",
  "dominant_feelings": [],
  "active_relation_tensions": [],
  "trust_map_delta": {},
  "open_questions": [],
  "active_promises": [],
  "near_payoff_items": [],
  "overdue_items": [],
  "notes": ""
}
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `state_id` | string | 是 | 硬字段 | 状态唯一 ID |
| `parent_level` | enum string | 是 | 硬字段 | 所属叙事层级 |
| `derived_from` | string | 否 | 对比字段 | 来源状态 ID |
| `current_time` | string | 是 | 当前事实字段 | 当前时间点 |
| `relative_time_marker` | string | 否 | 当前事实字段 | 相对时间标记 |
| `current_location` | string | 是 | 当前事实字段 | 当前地点 |
| `location_condition` | string[] | 否 | 当前事实字段 | 地点当前条件 |
| `scene_context` | string | 否 | 当前事实字段 | 当前场景背景说明 |
| `active_characters` | string[] | 是 | 当前事实字段 | 当前直接参与角色 |
| `offstage_influencers` | string[] | 否 | 当前事实字段 | 未出场但影响局势的角色/组织 |
| `pov_character` | string | 否 | 当前事实字段 | 当前视角角色 |
| `action_leader` | string | 否 | 当前推断字段 | 当前主动推动局面的角色 |
| `primary_goal` | string | 是 | 当前事实字段 | 当前最主要目标 |
| `secondary_goals` | string[] | 否 | 当前事实字段 | 次要目标 |
| `blocked_goals` | string[] | 否 | 当前事实字段 | 当前被阻断的目标 |
| `hidden_goals` | string[] | 否 | 当前推断字段 | 未明说但在起作用的目标 |
| `immediate_need` | string | 否 | 当前事实字段 | 眼前最紧迫的需求 |
| `active_conflicts` | string[] | 是 | 当前事实字段 | 当前冲突列表 |
| `urgency_level` | enum string | 是 | 当前推断字段 | 当前紧迫度 |
| `pressure_sources` | string[] | 否 | 当前事实字段 | 当前压力来源 |
| `escalation_risk` | string | 否 | 当前推断字段 | 当前恶化风险 |
| `resolution_options` | string[] | 否 | 当前推断字段 | 当前可见解决路径 |
| `public_information` | string[] | 否 | 当前事实字段 | 当前公开信息 |
| `private_information_map` | object | 否 | 当前事实字段 | 私人信息分布图 |
| `hidden_information` | string[] | 否 | 当前事实字段 | 当前隐藏信息 |
| `misinformation_in_effect` | string[] | 否 | 当前事实字段 | 正在起作用的误解/假信息 |
| `exposure_edges` | string[] | 否 | 当前推断字段 | 接近暴露边缘的事实/秘密 |
| `emotional_temperature` | enum string | 否 | 当前推断字段 | 当前整体情绪温度 |
| `dominant_feelings` | string[] | 否 | 当前推断字段 | 当前主导情绪 |
| `active_relation_tensions` | string[] | 否 | 当前推断字段 | 当前关系张力 |
| `trust_map_delta` | object | 否 | 对比字段 | 与前一状态相比的信任变化 |
| `open_questions` | string[] | 否 | 当前事实字段 | 当前仍未回答的问题 |
| `active_promises` | string[] | 否 | 当前事实字段 | 当前仍生效的叙事承诺 |
| `near_payoff_items` | string[] | 否 | 当前推断字段 | 接近回收窗口的项目 |
| `overdue_items` | string[] | 否 | 当前推断字段 | 已拖延过久的项目 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `state_id`

#### 类型

`string`

#### 必填

是

#### 说明

状态对象唯一标识。

#### 约束建议

- 在项目内不可重复
- 建议包含层级信息
- 一旦被 `PlotUnit` 引用，不应中途更名

#### 示例

- `s_014_scene`
- `state_arc_02_end`
- `chapter_06_open_state`

---

### 5.2 `parent_level`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `book`
- `arc`
- `chapter`
- `scene`

#### 说明

表示这个状态服务于哪个叙事层级。

---

### 5.3 `derived_from`

#### 类型

`string`

#### 必填

否

#### 说明

表示该状态从哪个前序状态演化而来。

#### 作用

用于追踪状态变化链。

---

### 5.4 `current_time`

#### 类型

`string`

#### 必填

是

#### 说明

当前绝对时间点或叙事时间节点。

#### 示例

- `试炼开始前夜`
- `第三日清晨`
- `母舰断供前六小时`

---

### 5.5 `relative_time_marker`

#### 类型

`string`

#### 必填

否

#### 说明

当前相对时间描述。

#### 示例

- `当夜`
- `三日后`
- `大战前一刻`

---

### 5.6 `current_location`

#### 类型

`string`

#### 必填

是

#### 说明

当前主要地点。

#### 示例

- `黑水泽外围废弃驿亭`
- `王城档案塔下层`
- `第七码头控制室`

---

### 5.7 `location_condition`

#### 类型

`string[]`

#### 必填

否

#### 说明

当前地点的即时条件。

#### 示例

- `暴雨`
- `受监视`
- `灵压不稳`
- `出口被封锁`
- `视线受阻`

---

### 5.8 `scene_context`

#### 类型

`string`

#### 必填

否

#### 说明

当前局势背景的一句话总结。

#### 示例

- `巡查队逼近，三方试探尚未撕破`
- `表面审问，实则互相套话`

---

### 5.9 `active_characters`

#### 类型

`string[]`

#### 必填

是

#### 说明

当前直接参与局势、能立即影响结果的角色 ID 列表。

---

### 5.10 `offstage_influencers`

#### 类型

`string[]`

#### 必填

否

#### 说明

当前虽未出场，但对局势施加影响的人物或组织。

#### 示例

- `王城监察司`
- `执法堂`
- `母舰指挥部`

---

### 5.11 `pov_character`

#### 类型

`string`

#### 必填

否

#### 说明

当前主要视角角色。

#### 作用

帮助系统管理信息权限与叙事合法性。

---

### 5.12 `action_leader`

#### 类型

`string`

#### 必填

否

#### 说明

当前最主动推动局面的角色。

#### 注意

这可以与 `pov_character` 不同。

---

### 5.13 目标字段

#### `primary_goal`

##### 类型

`string`

##### 必填

是

##### 说明

当前局势中最主要的目标。

#### `secondary_goals`

##### 类型

`string[]`

##### 必填

否

##### 说明

次要目标或伴随目标。

#### `blocked_goals`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前被阻断、暂时无法完成的目标。

#### `hidden_goals`

##### 类型

`string[]`

##### 必填

否

##### 说明

未公开表述但实际在运作的目标。

#### `immediate_need`

##### 类型

`string`

##### 必填

否

##### 说明

眼前最立即需要处理的问题。

---

### 5.14 冲突字段

#### `active_conflicts`

##### 类型

`string[]`

##### 必填

是

##### 说明

当前主要冲突列表。

##### 示例

- `令牌争夺`
- `信任危机`
- `身份暴露风险`

#### `urgency_level`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `low`
- `medium`
- `high`
- `critical`

##### 说明

当前局势紧迫度。

#### `pressure_sources`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前压力来源。

##### 示例

- `巡查队接近`
- `资源耗尽`
- `关系即将破裂`
- `时间窗口快结束`

#### `escalation_risk`

##### 类型

`string`

##### 必填

否

##### 说明

若当前状态持续下去，最可能恶化成什么。

#### `resolution_options`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前角色能看见或系统能推断出的解决路径。

---

### 5.15 信息字段

#### `public_information`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前已公开、至少在当前局势中可被多人共享的信息。

#### `private_information_map`

##### 类型

`object`

##### 必填

否

##### 推荐结构

```json
{
  "c001": ["..."],
  "c002": ["..."]
}
```

##### 说明

记录当前私人信息分布。

#### `hidden_information`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前仍未公开、但与当前局势强相关的信息。

#### `misinformation_in_effect`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前还在起作用的误解、假消息、错误判断。

#### `exposure_edges`

##### 类型

`string[]`

##### 必填

否

##### 说明

已接近暴露边缘的秘密、事实、物品或关系。

---

### 5.16 情绪与关系字段

#### `emotional_temperature`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `平稳`
- `压抑`
- `敌对`
- `暧昧`
- `惊惧`
- `失控前夜`

##### 说明

当前整体情绪氛围。

#### `dominant_feelings`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前主导情绪。

##### 示例

- `戒备`
- `羞耻`
- `怀疑`
- `愤怒`
- `依赖`

#### `active_relation_tensions`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前关系层面的主要张力。

#### `trust_map_delta`

##### 类型

`object`

##### 必填

否

##### 推荐结构

```json
{
  "c001->c002": -0.08,
  "c002->c001": 0.05
}
```

##### 说明

与前一状态相比，信任或关系强度的变化。

---

### 5.17 开放承诺字段

#### `open_questions`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前仍未回答的问题。

#### `active_promises`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前仍生效、尚未兑现的叙事承诺。

#### `near_payoff_items`

##### 类型

`string[]`

##### 必填

否

##### 说明

接近回收窗口的伏笔、悬念或承诺。

#### `overdue_items`

##### 类型

`string[]`

##### 必填

否

##### 说明

已拖延过久、存在遗失风险的项目。

---

### 5.18 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者保留备注区，用于写暂未结构化但重要的局势说明。

---

## 6. 字段分类汇总

### 6.1 当前事实字段

这些字段描述当前已成立的运行事实：

- `current_time`
- `relative_time_marker`
- `current_location`
- `location_condition`
- `scene_context`
- `active_characters`
- `offstage_influencers`
- `pov_character`
- `primary_goal`
- `secondary_goals`
- `blocked_goals`
- `active_conflicts`
- `pressure_sources`
- `public_information`
- `private_information_map`
- `hidden_information`
- `misinformation_in_effect`
- `open_questions`
- `active_promises`

---

### 6.2 当前推断字段

这些字段是系统对当前局势的工作性判断：

- `action_leader`
- `hidden_goals`
- `urgency_level`
- `escalation_risk`
- `resolution_options`
- `exposure_edges`
- `emotional_temperature`
- `dominant_feelings`
- `active_relation_tensions`
- `near_payoff_items`
- `overdue_items`

---

### 6.3 对比字段

这些字段依赖与前态对比：

- `derived_from`
- `trust_map_delta`

---

### 6.4 派生字段

这些字段不建议主存，可后续推导：

- 当前局势危险指数
- 当前信息失衡指数
- 当前冲突主导方向
- 当前承诺拖延风险总分

---

## 7. 合法性检查建议

一个合法的 `NarrativeState` 至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `state_id`
- `parent_level`
- `current_time`
- `current_location`
- `active_characters`
- `primary_goal`
- `active_conflicts`
- `urgency_level`

### 7.2 不违背既有事实

例如：

- 角色已离场却仍出现在 `active_characters`
- 秘密已公开，却仍被写作完全未知
- 已被销毁的物品仍被默认可用

### 7.3 当前目标与当前冲突有关联

不能出现：

- 当前最主要目标与当前冲突完全脱节
- 当前局势很危险，但目标仍停留在无关琐事上，且无说明

### 7.4 情绪与后果不完全断裂

例如：

- 上一场刚发生背叛，当前状态却没有任何关系张力或情绪残留

---

## 8. 更新规则

### 8.1 每个有效 PlotUnit 后必须更新

至少应更新以下之一：

- 目标
- 冲突
- 信息权限
- 地点
- 情绪温度
- 关系张力
- 开放问题

### 8.2 高频更新字段

这些字段会几乎每个场景变化：

- `current_time`
- `current_location`
- `active_characters`
- `primary_goal`
- `active_conflicts`
- `urgency_level`
- `public_information`
- `emotional_temperature`

### 8.3 中频更新字段

这些字段在中短期推进中变化：

- `hidden_goals`
- `resolution_options`
- `active_relation_tensions`
- `trust_map_delta`
- `near_payoff_items`

### 8.4 低频更新字段

这些字段通常在较大转折后变化：

- `parent_level`
- `offstage_influencers`
- `active_promises`
- `overdue_items`

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
{
  "state_id": "",
  "parent_level": "",
  "current_time": "",
  "current_location": "",
  "active_characters": [],
  "pov_character": "",
  "primary_goal": "",
  "active_conflicts": [],
  "urgency_level": "",
  "public_information": [],
  "hidden_information": [],
  "emotional_temperature": "",
  "open_questions": []
}
```

---

## 10. 示例

```json
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
  "scene_context": "三方试探尚未撕破，但局势已经逼近失控。",
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
  "overdue_items": [],
  "notes": "当前重点是让“令牌争夺”与“信任危机”双线同时推进，而不提前打破主线秘密。"
}
```

---

## 11. 一句话总结

`NarrativeState Schema` 的任务，是把故事“此刻的局”压缩成一份**可读、可更新、可承接、可审查的运行态对象**，让后续 `PlotUnit` 不再凭印象续写，而是从明确状态出发推进。
