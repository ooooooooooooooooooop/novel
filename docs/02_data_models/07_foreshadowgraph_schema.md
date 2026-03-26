# ForeshadowGraph Schema

## 文档目的
将 `01_concepts/07_foreshadowgraph.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`ForeshadowGraph`

---

## 2. Schema 目标

`ForeshadowGraph` 用于记录小说中的：

- 叙事承诺
- 伏笔建立点
- 推进节点
- 误导路径
- 回收节点
- 生命周期状态
- 承诺管理风险

它应支持系统回答：

- 已经向读者答应了什么
- 哪些承诺已经建立
- 哪些承诺正在推进
- 哪些承诺长期没动
- 哪些误导仍在生效
- 哪些回收已经接近窗口
- 哪些承诺已经兑现、变形或被放弃

它不是事实账本，而是自动小说系统中的**承诺与悬念管理层**。

---

## 3. 顶层结构

```json
[
  {
    "thread_id": "",
    "thread_type": "",
    "title": "",
    "scope_level": "",
    "promise_statement": "",
    "thematic_link": [],
    "emotional_weight": 0.0,
    "narrative_importance": "",
    "introduced_in": "",
    "setup_nodes": [],
    "setup_visibility": "",
    "initial_reader_question": "",
    "advancement_nodes": [],
    "narrowing_events": [],
    "expansion_events": [],
    "transformed_meaning": "",
    "false_paths": [],
    "misinformation_sources": [],
    "false_suspects_or_explanations": [],
    "misdirection_status": "",
    "payoff_nodes": [],
    "payoff_mode": "",
    "payoff_quality_note": "",
    "payoff_cost": "",
    "status": "",
    "progress_stage": 0,
    "urgency_to_payoff": "",
    "overdue_risk": "",
    "linked_characters": [],
    "linked_facts": [],
    "linked_plotunits": [],
    "linked_questions": [],
    "dependency_threads": [],
    "review_priority": "",
    "abrupt_payoff_risk": "",
    "forgotten_risk": "",
    "duplication_risk": "",
    "notes": ""
  }
]
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `thread_id` | string | 是 | 硬字段 | 承诺线程唯一 ID |
| `thread_type` | enum string | 是 | 硬字段 | 线程类型 |
| `title` | string | 是 | 标识字段 | 线程短标题 |
| `scope_level` | enum string | 是 | 硬字段 | 生效范围层级 |
| `promise_statement` | string | 是 | 硬字段 | 向读者建立的核心预期 |
| `thematic_link` | string[] | 否 | 结构字段 | 与主题的关联 |
| `emotional_weight` | float | 否 | 结构字段 | 情感权重 |
| `narrative_importance` | enum string | 是 | 硬字段 | 叙事重要度 |
| `introduced_in` | string | 是 | 溯源字段 | 首次建立位置 |
| `setup_nodes` | string[] | 否 | 生命周期字段 | 建立节点 |
| `setup_visibility` | enum string | 否 | 生命周期字段 | 建立时显性程度 |
| `initial_reader_question` | string | 否 | 结构字段 | 初始读者问题 |
| `advancement_nodes` | string[] | 否 | 生命周期字段 | 推进节点 |
| `narrowing_events` | string[] | 否 | 生命周期字段 | 收紧答案范围的事件 |
| `expansion_events` | string[] | 否 | 生命周期字段 | 扩大悬念范围的事件 |
| `transformed_meaning` | string | 否 | 生命周期字段 | 中途意义转向 |
| `false_paths` | string[] | 否 | 误导字段 | 假线索路径 |
| `misinformation_sources` | string[] | 否 | 误导字段 | 误导来源 |
| `false_suspects_or_explanations` | string[] | 否 | 误导字段 | 假解释列表 |
| `misdirection_status` | enum string | 否 | 误导字段 | 误导当前状态 |
| `payoff_nodes` | string[] | 否 | 生命周期字段 | 回收节点 |
| `payoff_mode` | enum string | 否 | 生命周期字段 | 回收方式 |
| `payoff_quality_note` | string | 否 | 审查字段 | 回收质量备注 |
| `payoff_cost` | string | 否 | 生命周期字段 | 回收代价 |
| `status` | enum string | 是 | 状态字段 | 线程当前状态 |
| `progress_stage` | integer | 否 | 状态字段 | 当前推进阶段 |
| `urgency_to_payoff` | enum string | 否 | 状态字段 | 距回收窗口远近 |
| `overdue_risk` | enum string | 否 | 风险字段 | 拖延风险 |
| `linked_characters` | string[] | 否 | 引用字段 | 关联角色 |
| `linked_facts` | string[] | 否 | 引用字段 | 关联事实 |
| `linked_plotunits` | string[] | 否 | 引用字段 | 关联推进单元 |
| `linked_questions` | string[] | 否 | 引用字段 | 关联开放问题 |
| `dependency_threads` | string[] | 否 | 引用字段 | 依赖其他承诺线程 |
| `review_priority` | enum string | 否 | 审查字段 | 审查优先级 |
| `abrupt_payoff_risk` | enum string | 否 | 风险字段 | 突兀回收风险 |
| `forgotten_risk` | enum string | 否 | 风险字段 | 被遗忘风险 |
| `duplication_risk` | enum string | 否 | 风险字段 | 重复承诺风险 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `thread_id`

#### 类型

`string`

#### 必填

是

#### 说明

承诺线程唯一标识。

#### 示例

- `fg_001`
- `promise_identity_01`
- `thread_relation_c001_c002`

#### 约束建议

- 在项目内不可重复
- 一旦被 `PlotUnit`、`NarrativeState` 或 `ReviewIssue` 引用，不应中途修改

---

### 5.2 `thread_type`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `identity`
- `relation`
- `mystery`
- `item`
- `world_rule`
- `betrayal`
- `hidden_past`
- `prophecy`
- `institution_secret`
- `survival_risk`

#### 说明

用于标识承诺线程的性质。

---

### 5.3 `title`

#### 类型

`string`

#### 必填

是

#### 说明

线程的短标题，便于在文档和审查中引用。

#### 示例

- `c001 的真实身世`
- `c002 是否会替 c001 保密`
- `试炼令牌的真正用途`

---

### 5.4 `scope_level`

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

表示这个承诺主要在哪个层级起作用。

---

### 5.5 `promise_statement`

#### 类型

`string`

#### 必填

是

#### 说明

该线程向读者建立的核心预期。

#### 要求

- 应是完整承诺，而不是一句模糊备注
- 应回答“未来必须回应什么”

#### 好例子

- `c001 的出身与体内残魂及王城旧案有关，未来必须揭示其来源与意义。`

#### 坏例子

- `这里有个伏笔`
- `以后会揭晓一点东西`

---

### 5.6 `thematic_link`

#### 类型

`string[]`

#### 必填

否

#### 说明

该承诺与哪些主题相关。

#### 示例

- `身份认同`
- `命运`
- `信任`
- `代价`

---

### 5.7 `emotional_weight`

#### 类型

`float`

#### 必填

否

#### 建议范围

`0.0` 到 `1.0`

#### 说明

该承诺的情感权重，而非结构权重。

#### 示例判断

- 核心身世谜团：`0.8` 以上
- 小型工具谜题：`0.2` 到 `0.4`

---

### 5.8 `narrative_importance`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `core`
- `major`
- `support`
- `minor`

#### 说明

决定审查优先级、拖延容忍度和回收要求。

---

### 5.9 溯源字段

#### `introduced_in`

##### 类型

`string`

##### 必填

是

##### 说明

首次建立位置，可写章节、场景或 PlotUnit ID。

#### `setup_nodes`

##### 类型

`string[]`

##### 必填

否

##### 说明

建立该承诺的具体节点列表。

#### `setup_visibility`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `explicit`
- `noticeable`
- `subtle`
- `hidden_from_reader`

##### 说明

表示建立时对读者显不显眼。

#### `initial_reader_question`

##### 类型

`string`

##### 必填

否

##### 说明

建立后读者最自然会问出的核心问题。

---

### 5.10 推进字段

#### `advancement_nodes`

##### 类型

`string[]`

##### 必填

否

##### 说明

推动这个承诺线程向前走的节点。

#### `narrowing_events`

##### 类型

`string[]`

##### 必填

否

##### 说明

把答案范围缩小的事件。

##### 示例

- `残魂并非随机寄宿，而像是主动绑定`

#### `expansion_events`

##### 类型

`string[]`

##### 必填

否

##### 说明

使原本局部问题扩大为更大问题的事件。

##### 示例

- `旧案牵涉到监察司和宗门联合封口`

#### `transformed_meaning`

##### 类型

`string`

##### 必填

否

##### 说明

中途若承诺意义发生变化，在此记录。

##### 示例

- `从个人身世谜团扩大为制度性秘密`

---

### 5.11 误导字段

#### `false_paths`

##### 类型

`string[]`

##### 必填

否

##### 说明

与该承诺相关的假线索路径。

#### `misinformation_sources`

##### 类型

`string[]`

##### 必填

否

##### 说明

误导来源。

##### 示例

- `民间传闻`
- `c003 的刻意误导`
- `被篡改的档案`

#### `false_suspects_or_explanations`

##### 类型

`string[]`

##### 必填

否

##### 说明

具体的假嫌疑人、假解释或假真相。

#### `misdirection_status`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `active`
- `exposed`
- `retired`

##### 说明

误导当前是否仍在生效。

---

### 5.12 回收字段

#### `payoff_nodes`

##### 类型

`string[]`

##### 必填

否

##### 说明

已发生的回收节点列表。

#### `payoff_mode`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `reveal`
- `reversal`
- `emotional_confirmation`
- `consequence`
- `symbolic_payoff`
- `partial_payoff`

##### 说明

承诺如何被兑现。

#### `payoff_quality_note`

##### 类型

`string`

##### 必填

否

##### 说明

对回收质量的简短备注。

#### `payoff_cost`

##### 类型

`string`

##### 必填

否

##### 说明

回收时是否伴随明显代价。

---

### 5.13 状态字段

#### `status`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `open`
- `active`
- `delayed`
- `transformed`
- `resolved`
- `abandoned`
- `false_path`

##### 说明

线程当前总体状态。

#### `progress_stage`

##### 类型

`integer`

##### 必填

否

##### 说明

推进阶段序号。

##### 建议

- 从 `0` 或 `1` 开始
- 只用于相对比较，不要求跨作品统一标准

#### `urgency_to_payoff`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`
- `imminent`

##### 说明

距离合理回收窗口有多近。

#### `overdue_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`

##### 说明

拖延不推进会不会明显伤害结构。

---

### 5.14 关联字段

#### `linked_characters`

##### 类型

`string[]`

##### 必填

否

##### 说明

与该承诺直接相关的角色 ID。

#### `linked_facts`

##### 类型

`string[]`

##### 必填

否

##### 说明

与该承诺关联的事实 ID。

#### `linked_plotunits`

##### 类型

`string[]`

##### 必填

否

##### 说明

与该承诺建立、推进、误导或回收相关的 PlotUnit ID。

#### `linked_questions`

##### 类型

`string[]`

##### 必填

否

##### 说明

与该承诺相连的开放问题。

#### `dependency_threads`

##### 类型

`string[]`

##### 必填

否

##### 说明

本线程依赖的其他承诺线程。

##### 示例

- `身世谜团` 依赖 `旧案档案线`
- `关系确认` 依赖 `信任是否建立`

---

### 5.15 审查与风险字段

#### `review_priority`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `critical`
- `high`
- `medium`
- `low`

#### `abrupt_payoff_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`

##### 说明

若现在回收，是否会显得突兀。

#### `forgotten_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`

##### 说明

该承诺是否存在被长期遗忘的风险。

#### `duplication_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`

##### 说明

该承诺是否与其他线程高度重复。

---

### 5.16 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者补充说明。

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段定义承诺线程本体，不应轻易改：

- `thread_id`
- `thread_type`
- `title`
- `scope_level`
- `promise_statement`
- `narrative_importance`
- `introduced_in`

---

### 6.2 生命周期字段

这些字段描述承诺线程处于什么阶段：

- `setup_nodes`
- `setup_visibility`
- `advancement_nodes`
- `narrowing_events`
- `expansion_events`
- `transformed_meaning`
- `payoff_nodes`
- `payoff_mode`
- `payoff_cost`
- `status`
- `progress_stage`
- `urgency_to_payoff`

---

### 6.3 误导字段

这些字段管理假线索和错误方向：

- `false_paths`
- `misinformation_sources`
- `false_suspects_or_explanations`
- `misdirection_status`

---

### 6.4 风险字段

这些字段用于支持审查：

- `overdue_risk`
- `review_priority`
- `abrupt_payoff_risk`
- `forgotten_risk`
- `duplication_risk`

---

### 6.5 引用字段

这些字段连接其他对象：

- `linked_characters`
- `linked_facts`
- `linked_plotunits`
- `linked_questions`
- `dependency_threads`

---

### 6.6 派生字段

这些字段不建议主存，可后续推导：

- 当前主线承诺压力总值
- 当前关系线承诺拖延程度
- 某线程是否已过最佳回收窗口
- 当前章节涉及的承诺线程集合

---

## 7. 合法性检查建议

一个合法的 `ForeshadowGraph` 条目至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `thread_id`
- `thread_type`
- `title`
- `scope_level`
- `promise_statement`
- `narrative_importance`
- `introduced_in`
- `status`

### 7.2 promise_statement 必须是承诺，不是备注

例如：

- `未来必须回应什么`

而不是：

- `这里有个点`
- `感觉以后能用`

### 7.3 生命周期与状态一致

例如：

- `status = resolved` 但没有 `payoff_nodes`
- `status = active` 但既无 `setup_nodes` 也无 `advancement_nodes`

### 7.4 误导不能污染真线

若存在 `false_paths`，应能区分其与真正承诺内容的边界。

### 7.5 核心承诺不能长期无推进

若 `narrative_importance = core` 且长时间无推进，应触发高风险。

---

## 8. 更新规则

### 8.1 建立

当一个新承诺被明确提出时，新增线程。

### 8.2 推进

当新线索、新异常、新证据出现时，更新：

- `advancement_nodes`
- `narrowing_events`
- `expansion_events`
- `progress_stage`

### 8.3 转义

当该承诺意义改变时，更新：

- `transformed_meaning`
- `status = transformed`

### 8.4 部分回收

当只兑现部分内容时：

- 新增 `payoff_nodes`
- 保持 `status = active` 或 `delayed`
- 更新 `urgency_to_payoff`

### 8.5 完整回收

当承诺被正式兑现时：

- `status = resolved`
- 填写 `payoff_nodes`
- 填写 `payoff_mode`

### 8.6 放弃

若项目决定不再兑现：

- `status = abandoned`
- 在 `notes` 中记录原因

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
[
  {
    "thread_id": "",
    "thread_type": "",
    "title": "",
    "promise_statement": "",
    "introduced_in": "",
    "setup_nodes": [],
    "advancement_nodes": [],
    "payoff_nodes": [],
    "status": "",
    "urgency_to_payoff": "",
    "linked_characters": [],
    "linked_plotunits": [],
    "forgotten_risk": ""
  }
]
```

---

## 10. 示例

```json
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
    "payoff_mode": "",
    "payoff_quality_note": "",
    "payoff_cost": "",
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
    "transformed_meaning": "",
    "false_paths": [],
    "misinformation_sources": [],
    "false_suspects_or_explanations": [],
    "misdirection_status": "retired",
    "payoff_nodes": [],
    "payoff_mode": "",
    "payoff_quality_note": "",
    "payoff_cost": "",
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

---

## 11. 一句话总结

`ForeshadowGraph Schema` 的任务，是把作品中的承诺、伏笔、误导与回收压缩成一组**可追踪生命周期、可连接其他对象、可支持审查和回收调度的叙事线程对象**。
