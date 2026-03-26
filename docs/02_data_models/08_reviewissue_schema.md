# ReviewIssue Schema

## 文档目的
将 `01_concepts/08_reviewissue.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`ReviewIssue`

---

## 2. Schema 目标

`ReviewIssue` 用于记录系统在审查过程中识别出的**可定位、可分类、可处理、可关闭**的问题对象。

它应支持系统回答：

- 具体哪里出了问题
- 这个问题属于哪一类
- 问题有多严重
- 问题影响哪些对象和后续结构
- 违反了哪条规则或与哪些事实冲突
- 该优先怎么修
- 问题当前处理到哪一步

它不是模糊评价，也不是泛泛的“这里不太自然”，而是生成—审查—修正闭环中的正式问题单。

---

## 3. 顶层结构

```json
[
  {
    "issue_id": "",
    "issue_type": "",
    "title": "",
    "summary": "",
    "object_type": "",
    "object_id": "",
    "level": "",
    "plotunit_ref": "",
    "chapter_ref": "",
    "scene_ref": "",
    "violated_rule": "",
    "supporting_facts": [],
    "contradictory_facts": [],
    "missing_elements": [],
    "evidence_note": "",
    "impact_scope": "",
    "affected_characters": [],
    "affected_threads": [],
    "affected_states": [],
    "downstream_risk": "",
    "suggested_fix_type": "",
    "suggested_fix_note": "",
    "rewrite_needed": false,
    "replanning_needed": false,
    "memory_update_needed": false,
    "severity": "",
    "urgency": "",
    "blocking_status": "",
    "fix_order": 0,
    "status": "",
    "created_at": "",
    "last_updated": "",
    "resolved_by": "",
    "resolution_note": "",
    "notes": ""
  }
]
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `issue_id` | string | 是 | 硬字段 | 问题唯一 ID |
| `issue_type` | enum string | 是 | 硬字段 | 问题类型 |
| `title` | string | 是 | 标识字段 | 问题短标题 |
| `summary` | string | 是 | 判定字段 | 一句话问题摘要 |
| `object_type` | enum string | 是 | 定位字段 | 问题主要指向对象类型 |
| `object_id` | string | 是 | 定位字段 | 具体对象 ID |
| `level` | enum string | 是 | 定位字段 | 问题所在层级 |
| `plotunit_ref` | string | 否 | 引用字段 | 相关 PlotUnit |
| `chapter_ref` | string | 否 | 定位字段 | 相关章节 |
| `scene_ref` | string | 否 | 定位字段 | 相关场景 |
| `violated_rule` | string | 是 | 判定字段 | 违反的规则 |
| `supporting_facts` | string[] | 否 | 判定字段 | 支持判定的事实/依据 |
| `contradictory_facts` | string[] | 否 | 判定字段 | 与之冲突的事实 |
| `missing_elements` | string[] | 否 | 判定字段 | 缺失元素 |
| `evidence_note` | string | 否 | 判定字段 | 证据说明 |
| `impact_scope` | enum string | 是 | 影响字段 | 影响范围 |
| `affected_characters` | string[] | 否 | 影响字段 | 受影响角色 |
| `affected_threads` | string[] | 否 | 影响字段 | 受影响承诺线程 |
| `affected_states` | string[] | 否 | 影响字段 | 受影响状态 |
| `downstream_risk` | string | 否 | 影响字段 | 若不修复的后续风险 |
| `suggested_fix_type` | enum string | 是 | 处理字段 | 建议修复方式 |
| `suggested_fix_note` | string | 否 | 处理字段 | 修复建议说明 |
| `rewrite_needed` | boolean | 否 | 处理字段 | 是否需要重写正文 |
| `replanning_needed` | boolean | 否 | 处理字段 | 是否需要重规划 |
| `memory_update_needed` | boolean | 否 | 处理字段 | 是否需要更新状态/账本/图谱 |
| `severity` | enum string | 是 | 优先级字段 | 严重程度 |
| `urgency` | enum string | 是 | 优先级字段 | 修复紧迫度 |
| `blocking_status` | enum string | 是 | 优先级字段 | 是否阻断后续生成 |
| `fix_order` | integer | 否 | 优先级字段 | 建议修复顺序 |
| `status` | enum string | 是 | 生命周期字段 | 当前处理状态 |
| `created_at` | string | 否 | 生命周期字段 | 创建时间/轮次 |
| `last_updated` | string | 否 | 生命周期字段 | 最后更新时间 |
| `resolved_by` | string | 否 | 生命周期字段 | 由什么动作关闭 |
| `resolution_note` | string | 否 | 生命周期字段 | 修复说明 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `issue_id`

#### 类型

`string`

#### 必填

是

#### 说明

问题唯一标识。

#### 示例

- `ri_001`
- `issue_fact_014`
- `review_pass03_02`

#### 约束建议

- 在项目内不可重复
- 一旦进入实验记录或修复记录，不建议更改

---

### 5.2 `issue_type`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `fact_conflict`
- `character_distortion`
- `world_violation`
- `timeline_error`
- `weak_progression`
- `promise_loss`
- `abrupt_payoff`
- `missing_consequence`
- `missing_transition`
- `redundancy`
- `information_leak`
- `style_drift`
- `missing_cost`
- `motivation_gap`
- `relationship_jump`
- `duplication_of_threads`

#### 说明

问题大类。建议优先使用稳定、可统计的类型名称。

---

### 5.3 `title`

#### 类型

`string`

#### 必填

是

#### 说明

问题短标题。

#### 示例

- `c001 的冒险决策缺少前置动机承接`
- `核心身世线程推进停滞过久`
- `scene_021 与既有事实冲突`

---

### 5.4 `summary`

#### 类型

`string`

#### 必填

是

#### 说明

一句话说明问题。

#### 要求

- 指出问题是什么
- 尽量包含对象和症状
- 不写空泛评价

---

### 5.5 定位字段

#### `object_type`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `PlotUnit`
- `NarrativeState`
- `FactLedger`
- `ForeshadowGraph`
- `CharacterModel`
- `WorldModel`

##### 说明

问题主要指向的对象类型。

#### `object_id`

##### 类型

`string`

##### 必填

是

##### 说明

具体对象的 ID。

#### `level`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `book`
- `arc`
- `chapter`
- `scene`

##### 说明

问题所在层级。

#### `plotunit_ref`

##### 类型

`string`

##### 必填

否

##### 说明

若问题与具体推进单元有关，引用对应 `PlotUnit.unit_id`。

#### `chapter_ref`

##### 类型

`string`

##### 必填

否

##### 说明

定位到章节。

#### `scene_ref`

##### 类型

`string`

##### 必填

否

##### 说明

定位到场景。

---

### 5.6 判定字段

#### `violated_rule`

##### 类型

`string`

##### 必填

是

##### 说明

违反的规则、约束或审查标准。

#### `supporting_facts`

##### 类型

`string[]`

##### 必填

否

##### 说明

支持该问题判定的事实、角色字段、状态或承诺线程。

##### 建议

优先写可引用对象 ID 或明确条目，而不是空泛描述。

#### `contradictory_facts`

##### 类型

`string[]`

##### 必填

否

##### 说明

与当前输出明显冲突的事实或既有条件。

#### `missing_elements`

##### 类型

`string[]`

##### 必填

否

##### 推荐取值示例

- `missing_transition`
- `missing_cost`
- `missing_motivation`
- `missing_payoff`
- `missing_consequence`
- `missing_information_gate`

##### 说明

指出“缺了什么”。

#### `evidence_note`

##### 类型

`string`

##### 必填

否

##### 说明

补充证据说明。

---

### 5.7 影响字段

#### `impact_scope`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `local`
- `arc`
- `bookwide`

##### 说明

问题影响范围。

#### `affected_characters`

##### 类型

`string[]`

##### 必填

否

##### 说明

被该问题影响的角色。

#### `affected_threads`

##### 类型

`string[]`

##### 必填

否

##### 说明

被影响的承诺线程或伏笔线程。

#### `affected_states`

##### 类型

`string[]`

##### 必填

否

##### 说明

被影响的状态对象。

#### `downstream_risk`

##### 类型

`string`

##### 必填

否

##### 说明

若不修复，该问题最可能污染什么。

---

### 5.8 处理字段

#### `suggested_fix_type`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `local_rewrite`
- `state_update`
- `fact_correction`
- `foreshadow_advancement`
- `character_motivation_patch`
- `arc_replanning`
- `relationship_bridge_scene`
- `cost_insertion`
- `info_gate_adjustment`
- `reveal_split`
- `thread_cleanup`
- `scene_merge`
- `style_realignment`

##### 说明

建议的主要修复方向。

#### `suggested_fix_note`

##### 类型

`string`

##### 必填

否

##### 说明

更具体的修复建议。

#### `rewrite_needed`

##### 类型

`boolean`

##### 必填

否

##### 说明

是否需要改写当前正文或场景。

#### `replanning_needed`

##### 类型

`boolean`

##### 必填

否

##### 说明

是否需要改动后续规划。

#### `memory_update_needed`

##### 类型

`boolean`

##### 必填

否

##### 说明

是否需要同步更新：

- `NarrativeState`
- `FactLedger`
- `ForeshadowGraph`

---

### 5.9 优先级字段

#### `severity`

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

问题严重程度。

#### `urgency`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `backlog`
- `soon`
- `immediate`

##### 说明

修复紧迫度。

#### `blocking_status`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `non_blocking`
- `warning`
- `blocking`

##### 说明

是否阻断后续生成。

#### `fix_order`

##### 类型

`integer`

##### 必填

否

##### 说明

多个问题并存时的修复顺序。

---

### 5.10 生命周期字段

#### `status`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `open`
- `acknowledged`
- `in_progress`
- `mitigated`
- `resolved`
- `dismissed`

##### 说明

问题当前处理状态。

#### `created_at`

##### 类型

`string`

##### 必填

否

##### 说明

创建时间或审查轮次。

##### 示例

- `review_pass_03`
- `2026-03-25-pass-1`

#### `last_updated`

##### 类型

`string`

##### 必填

否

##### 说明

最后更新时间或轮次。

#### `resolved_by`

##### 类型

`string`

##### 必填

否

##### 说明

由哪个修复动作关闭。

##### 示例

- `rewrite_scene_018_v2`
- `arc_plan_patch_04`

#### `resolution_note`

##### 类型

`string`

##### 必填

否

##### 说明

修复说明。

---

### 5.11 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者补充说明。

---

## 6. 字段分类汇总

### 6.1 判定字段

这些字段用于证明“这里确实有问题”：

- `issue_type`
- `summary`
- `violated_rule`
- `supporting_facts`
- `contradictory_facts`
- `missing_elements`
- `evidence_note`

---

### 6.2 定位字段

这些字段用于明确“问题在哪里”：

- `object_type`
- `object_id`
- `level`
- `plotunit_ref`
- `chapter_ref`
- `scene_ref`

---

### 6.3 影响字段

这些字段用于判断“不修会怎样”：

- `impact_scope`
- `affected_characters`
- `affected_threads`
- `affected_states`
- `downstream_risk`

---

### 6.4 处理字段

这些字段用于决定“怎么修”：

- `suggested_fix_type`
- `suggested_fix_note`
- `rewrite_needed`
- `replanning_needed`
- `memory_update_needed`

---

### 6.5 优先级字段

这些字段用于决定“先修哪个”：

- `severity`
- `urgency`
- `blocking_status`
- `fix_order`

---

### 6.6 生命周期字段

这些字段用于追踪“修到哪了”：

- `status`
- `created_at`
- `last_updated`
- `resolved_by`
- `resolution_note`

---

### 6.7 派生字段

这些字段不建议主存，可后续推导：

- 当前未解决 critical issue 数量
- 当前章节的阻断问题数量
- 某角色相关问题密度
- 某条承诺线程的累计问题风险

---

## 7. 合法性检查建议

一个合法的 `ReviewIssue` 条目至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `issue_id`
- `issue_type`
- `title`
- `summary`
- `object_type`
- `object_id`
- `level`
- `violated_rule`
- `impact_scope`
- `suggested_fix_type`
- `severity`
- `urgency`
- `blocking_status`
- `status`

### 7.2 必须可定位

不能只有问题类型，没有具体对象和层级。

### 7.3 必须有依据

至少应有：

- `violated_rule`

或

- `supporting_facts`

中的一种明确依据，最好两者都有。

### 7.4 一个 issue 尽量只处理一个核心问题

避免把事实冲突、角色失真、节奏塌陷混在同一条。

### 7.5 修复方向必须存在

不能只说“这里不对”，却不给任何修复方向。

---

## 8. 更新规则

### 8.1 创建

当问题被正式识别且值得进入闭环时，新增一个 `ReviewIssue`。

### 8.2 处理中

修复过程中可更新：

- `status`
- `last_updated`
- `suggested_fix_note`
- `fix_order`

### 8.3 缓解

若问题未完全解决但已显著减轻，可设：

- `status = mitigated`

### 8.4 解决

若问题已修复：

- `status = resolved`
- 填写 `resolved_by`
- 填写 `resolution_note`

### 8.5 驳回

若问题被证明不成立或不需要处理：

- `status = dismissed`
- 建议在 `resolution_note` 记录原因

---

## 9. 问题优先级原则

建议默认处理顺序：

### 第一优先

- `fact_conflict`
- `world_violation`
- `timeline_error`

### 第二优先

- `character_distortion`
- `motivation_gap`
- `weak_progression`
- `missing_cost`

### 第三优先

- `promise_loss`
- `abrupt_payoff`
- `relationship_jump`

### 第四优先

- `redundancy`
- `style_drift`

---

## 10. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
[
  {
    "issue_id": "",
    "issue_type": "",
    "summary": "",
    "object_type": "",
    "object_id": "",
    "violated_rule": "",
    "supporting_facts": [],
    "impact_scope": "",
    "suggested_fix_type": "",
    "severity": "",
    "status": ""
  }
]
```

---

## 11. 示例

```json
[
  {
    "issue_id": "ri_001",
    "issue_type": "character_distortion",
    "title": "c001 的冒险决策缺少前置动机承接",
    "summary": "scene_018 中 c001 突然决定信任 c003，与其既有恐惧和关系张力不匹配。",
    "object_type": "PlotUnit",
    "object_id": "pu_scene_018",
    "level": "scene",
    "plotunit_ref": "pu_scene_018",
    "chapter_ref": "chapter_07",
    "scene_ref": "scene_018",
    "violated_rule": "角色关键决策必须与 CharacterModel 中的目标、恐惧、关系和前态一致，或有足够铺垫支持偏移。",
    "supporting_facts": [
      "c001.fear",
      "c001.relations[c003]",
      "s_017_scene"
    ],
    "contradictory_facts": [
      "scene_018 未提供新的信任证据"
    ],
    "missing_elements": [
      "missing_transition",
      "missing_motivation"
    ],
    "evidence_note": "当前文本直接跨过怀疑阶段进入合作，导致行为跳变。",
    "impact_scope": "arc",
    "affected_characters": ["c001", "c003"],
    "affected_threads": ["fg_002"],
    "affected_states": ["s_018_scene"],
    "downstream_risk": "若直接沿用，会削弱后续信任线的张力与成长可信度。",
    "suggested_fix_type": "character_motivation_patch",
    "suggested_fix_note": "补一个让 c001 被迫合作的外部压力，或增加 c003 提供关键证据的前置动作。",
    "rewrite_needed": true,
    "replanning_needed": false,
    "memory_update_needed": false,
    "severity": "high",
    "urgency": "immediate",
    "blocking_status": "blocking",
    "fix_order": 1,
    "status": "open",
    "created_at": "review_pass_03",
    "last_updated": "review_pass_03",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "优先修复，否则后续关系线会失真。"
  },
  {
    "issue_id": "ri_002",
    "issue_type": "promise_loss",
    "title": "核心身世线程推进停滞过久",
    "summary": "fg_001 在最近两个 arc 中缺乏有效推进，存在承诺遗失风险。",
    "object_type": "ForeshadowGraph",
    "object_id": "fg_001",
    "level": "arc",
    "plotunit_ref": "",
    "chapter_ref": "",
    "scene_ref": "",
    "violated_rule": "核心叙事承诺应在合理跨度内得到推进、收紧或转义，不能长期无动作。",
    "supporting_facts": [
      "fg_001.narrative_importance = core",
      "fg_001.advancement_nodes 无新增"
    ],
    "contradictory_facts": [],
    "missing_elements": [
      "missing_payoff_progress"
    ],
    "evidence_note": "主线身世承诺被关系线和局部行动线长期遮蔽。",
    "impact_scope": "bookwide",
    "affected_characters": ["c001"],
    "affected_threads": ["fg_001"],
    "affected_states": [],
    "downstream_risk": "读者会逐渐失去对主线谜团的期待，主线聚焦度下降。",
    "suggested_fix_type": "foreshadow_advancement",
    "suggested_fix_note": "在下一 arc 前三章加入一条能缩小答案范围的新证据，而不是直接揭晓真相。",
    "rewrite_needed": false,
    "replanning_needed": true,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "warning",
    "fix_order": 3,
    "status": "open",
    "created_at": "review_pass_03",
    "last_updated": "review_pass_03",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "属于结构性问题，不一定需要重写，但需要改后续规划。"
  }
]
```

---

## 12. 一句话总结

`ReviewIssue Schema` 的任务，是把审查结果压缩成一组**可定位、可证明、可排序、可执行修复、可关闭的问题对象**，让自动小说系统真正形成稳定的审查—修正闭环。
