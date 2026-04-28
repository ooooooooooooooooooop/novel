# ReviewReminder Schema

## 文档目的
将 `01_concepts/09_reviewreminder.md` 中的概念定义，压缩为可操作的数据结构说明。

本文件关注：

- 字段列表
- 字段类型
- 必填/选填
- 字段分类
- 合法取值建议
- 生命周期规则

---

## 1. 对象名称

`ReviewReminder`

---

## 2. Schema 目标

`ReviewReminder` 用于记录审查中发现的近程 warning，使其能够被后续 workflow 读取、复查、补偿或升级。

它应支持系统回答：

- 当前提醒是什么
- 它来自哪里
- 最迟什么时候必须处理
- 不处理会升级成什么
- 现在处理到哪一步

---

## 3. 顶层结构

```json
[
  {
    "reminder_id": "",
    "reminder_type": "",
    "title": "",
    "summary": "",
    "source_object_type": "",
    "source_object_id": "",
    "plotunit_ref": "",
    "review_pass_ref": "",
    "related_issue_type": "",
    "supporting_refs": [],
    "window_type": "",
    "window_value": "",
    "window_note": "",
    "escalation_rule": "",
    "severity": "",
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
| `reminder_id` | string | 是 | 标识字段 | reminder 唯一 ID |
| `reminder_type` | enum string | 是 | 分类字段 | 提醒类型 |
| `title` | string | 是 | 标识字段 | 提醒短标题 |
| `summary` | string | 是 | 判定字段 | 一句话提醒摘要 |
| `source_object_type` | enum string | 是 | 来源字段 | 来源对象类型 |
| `source_object_id` | string | 是 | 来源字段 | 来源对象 ID |
| `plotunit_ref` | string | 否 | 引用字段 | 相关 PlotUnit |
| `review_pass_ref` | string | 否 | 引用字段 | 生成该 reminder 的 review 轮次 |
| `related_issue_type` | string | 否 | 升级字段 | 若升级，建议升级成的 issue 类型 |
| `supporting_refs` | string[] | 否 | 判定字段 | 支撑提醒的相关对象或事实引用 |
| `window_type` | enum string | 是 | 窗口字段 | 处理窗口类型 |
| `window_value` | string | 是 | 窗口字段 | 处理窗口值 |
| `window_note` | string | 否 | 窗口字段 | 对窗口的补充说明 |
| `escalation_rule` | string | 是 | 升级字段 | 升级触发说明 |
| `severity` | enum string | 是 | 优先级字段 | 提醒强度 |
| `status` | enum string | 是 | 生命周期字段 | 当前状态 |
| `created_at` | string | 否 | 生命周期字段 | 创建时间或轮次 |
| `last_updated` | string | 否 | 生命周期字段 | 最后更新时间 |
| `resolved_by` | string | 否 | 生命周期字段 | 由什么动作关闭 |
| `resolution_note` | string | 否 | 生命周期字段 | 关闭说明 |
| `notes` | string | 否 | 备注字段 | 补充说明 |

---

## 5. 字段详细说明

### 5.1 `reminder_id`

#### 类型

`string`

#### 必填

是

#### 示例

- `rr_001`
- `rem_scene014_cost`

---

### 5.2 `reminder_type`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `missing_consequence`
- `missing_cost`
- `relationship_bridge_needed`
- `promise_followup_needed`
- `knowledge_check_needed`

#### 说明

优先使用能与规则层和 issue 层对齐的稳定命名。

---

### 5.3 `source_object_type` / `source_object_id`

#### 推荐取值

`source_object_type` 建议为：

- `PlotUnit`
- `NarrativeState`
- `CharacterModel`
- `FactLedger`
- `ForeshadowGraph`

#### 说明

用于明确 reminder 到底在提醒哪一层的兑现或补桥。

---

### 5.4 `plotunit_ref`

#### 类型

`string`

#### 必填

否

#### 说明

当 reminder 与某次局部推进直接相关时，建议填写。

---

### 5.5 `review_pass_ref`

#### 类型

`string`

#### 必填

否

#### 示例

- `review_pass_03`
- `sample_review_pass_01`

---

### 5.6 `related_issue_type`

#### 类型

`string`

#### 必填

否

#### 说明

用于说明 reminder 若升级，最可能转化成哪类正式 `ReviewIssue`。

---

### 5.7 `supporting_refs`

#### 类型

`string[]`

#### 必填

否

#### 说明

可引用：

- 相关 fact ID
- 相关 thread ID
- 相关 state ID
- 相关 plotunit ID

---

### 5.8 窗口字段

#### `window_type`

##### 类型

`enum string`

##### 推荐取值

- `plotunit_count`
- `chapter_boundary`
- `phase_window`

#### `window_value`

##### 类型

`string`

##### 示例

- `2`
- `before_chapter_end`
- `before_arc_turn`

#### `window_note`

##### 类型

`string`

##### 说明

对窗口的自然语言补充说明。

---

### 5.9 `escalation_rule`

#### 类型

`string`

#### 必填

是

#### 示例

- `若后续 2 个 PlotUnit 内仍未体现至少一项后果，则升级为 missing_consequence`
- `若连续 2 次复审仍未补桥，则升级为 relationship_jump`

---

### 5.10 `severity`

#### 类型

`enum string`

#### 推荐取值

- `low`
- `medium`

#### 说明

`ReviewReminder` 默认不承载 `high` 或 `critical`。

若风险已到高危，通常应直接进入正式 issue。

---

### 5.11 生命周期字段

#### `status`

##### 类型

`enum string`

##### 推荐取值

- `active`
- `compensated`
- `escalated`
- `dismissed`

#### `resolved_by`

##### 说明

可写：

- `continue_pass_04`
- `rewrite_pass_02`
- `manual_dismissal`

---

## 6. 写入原则

建议仅在满足以下条件时写入 `ReviewReminder`：

1. 当前尚未正式失败
2. 需要跨 workflow handoff
3. 存在明确处理窗口
4. 存在明确升级逻辑

以下情况通常不要写：

- 只是一次性局部备注
- 没有窗口的泛化担忧
- 已经应当建正式 `ReviewIssue`

---

## 7. 生命周期建议

### 7.1 创建

通常由 `Review Workflow` 创建。

### 7.2 读取

至少应被以下 workflow 读取：

- `Continue`
- 下一轮 `Review`
- 必要时 `Rewrite`

### 7.3 关闭

可由以下动作关闭：

- 后续推进已经补偿
- 改写中被显式修复
- 升级成正式 `ReviewIssue`
- 判定无需继续跟踪

---

## 8. 最小样例

```json
[
  {
    "reminder_id": "rr_scene014_01",
    "reminder_type": "missing_consequence",
    "title": "scene_014 的后果需在近程兑现",
    "summary": "旧伤、追踪与保密压力已被激活，后续 1 到 2 个 PlotUnit 内必须兑现至少一项。",
    "source_object_type": "PlotUnit",
    "source_object_id": "pu_scene_014",
    "plotunit_ref": "pu_scene_014",
    "review_pass_ref": "sample_review_pass_01",
    "related_issue_type": "missing_consequence",
    "supporting_refs": ["f_016", "f_017", "f_019"],
    "window_type": "plotunit_count",
    "window_value": "2",
    "window_note": "当前可放行，但不能继续空转。",
    "escalation_rule": "若后续 2 个 PlotUnit 内仍未兑现至少一项后果，则升级为正式 missing_consequence。",
    "severity": "low",
    "status": "active",
    "created_at": "sample_review_pass_01",
    "last_updated": "sample_review_pass_01",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "默认不阻断，只作为近程 warning 的正式承载层。"
  }
]
```

---

## 9. 一句话总结

`ReviewReminder Schema` 的任务，是把近程 warning 压缩成可交接、可追踪、可升级、可关闭的轻量对象，而不是让它继续漂在 prose 备注里。
