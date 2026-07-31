# PlotUnit Schema

## 文档目的
将 `01_concepts/05_plotunit.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`PlotUnit`

---

## 2. Schema 目标

`PlotUnit` 用于定义一次有效叙事推进。

它应支持系统回答：

- 这个单元的目标是什么
- 这个单元从什么状态开始
- 谁在推动、谁在阻碍
- 发生了什么关键事件
- 付出了什么代价
- 最终哪些状态发生了变化
- 这个单元对伏笔、承诺和审查产生了什么影响

它不是纯文本段落，也不是泛泛的“剧情摘要”，而是一个可记录、可审查、可回写的状态转移对象。

---

## 3. 顶层结构

```json
{
  "unit_id": "",
  "level": "",
  "title_or_label": "",
  "parent_unit": "",
  "previous_unit": "",
  "next_unit": "",
  "unit_goal": "",
  "local_goal": "",
  "hidden_goal": "",
  "success_condition": "",
  "failure_condition": "",
  "input_state_ref": "",
  "active_characters": [],
  "active_conflicts": [],
  "current_constraints": [],
  "active_promises_in_scope": [],
  "initiator": "",
  "responders": [],
  "key_decision": "",
  "conflict_type": "",
  "tactics_used": [],
  "cost_paid": [],
  "compromise_or_escalation": "",
  "event_summary": "",
  "decisive_moment": "",
  "reveal_event": "",
  "reversal_event": "",
  "fallout_event": "",
  "output_state_ref": "",
  "state_change_summary": [],
  "goal_shift": {},
  "relation_shift": {},
  "information_shift": [],
  "conflict_shift": [],
  "risk_shift": [],
  "foreshadowing_added": [],
  "foreshadowing_advanced": [],
  "foreshadowing_resolved": [],
  "false_leads_added": [],
  "promises_opened": [],
  "promises_delayed": [],
  "progression_strength": "",
  "legality_status": "",
  "character_consistency_status": "",
  "redundancy_risk": "",
  "removable_without_loss": false,
  "review_notes": [],
  "notes": ""
}
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `unit_id` | string | 是 | 硬字段 | 单元唯一 ID |
| `level` | enum string | 是 | 硬字段 | 叙事层级 |
| `title_or_label` | string | 否 | 标识字段 | 短标题或功能标签 |
| `parent_unit` | string | 否 | 引用字段 | 上级单元 ID |
| `previous_unit` | string | 否 | 引用字段 | 前一单元 ID |
| `next_unit` | string | 否 | 引用字段 | 后一单元 ID |
| `unit_goal` | string | 是 | 目标字段 | 本单元主要目标 |
| `local_goal` | string | 否 | 目标字段 | 局部目标 |
| `hidden_goal` | string | 否 | 推断字段 | 未明说但起作用的目标 |
| `success_condition` | string | 否 | 目标字段 | 成功条件 |
| `failure_condition` | string | 否 | 目标字段 | 失败条件 |
| `input_state_ref` | string | 是 | 引用字段 | 输入状态 ID |
| `active_characters` | string[] | 是 | 当前事实字段 | 参与角色 |
| `active_conflicts` | string[] | 否 | 当前事实字段 | 当前冲突 |
| `current_constraints` | string[] | 否 | 当前事实字段 | 当前约束 |
| `active_promises_in_scope` | string[] | 否 | 引用字段 | 当前作用中的承诺线程 |
| `initiator` | string | 是 | 行动字段 | 发起关键行动者 |
| `responders` | string[] | 否 | 行动字段 | 主要回应者 |
| `key_decision` | string | 是 | 行动字段 | 本单元关键决策 |
| `conflict_type` | enum string | 是 | 行动字段 | 冲突类型 |
| `tactics_used` | string[] | 否 | 行动字段 | 使用的策略 |
| `cost_paid` | string[] | 否 | 结果字段 | 付出的代价 |
| `compromise_or_escalation` | enum string | 否 | 结果字段 | 妥协/升级结果 |
| `event_summary` | string | 是 | 事件字段 | 事件简述 |
| `decisive_moment` | string | 否 | 事件字段 | 决定性时刻 |
| `reveal_event` | string | 否 | 事件字段 | 信息揭露事件 |
| `reversal_event` | string | 否 | 事件字段 | 反转事件 |
| `fallout_event` | string | 否 | 事件字段 | 即时后果事件 |
| `output_state_ref` | string | 是 | 引用字段 | 输出状态 ID |
| `state_change_summary` | string[] | 是 | 结果字段 | 状态变化摘要 |
| `goal_shift` | object | 否 | 结果字段 | 目标变化 |
| `relation_shift` | object | 否 | 结果字段 | 关系变化 |
| `information_shift` | string[] | 否 | 结果字段 | 信息变化 |
| `conflict_shift` | string[] | 否 | 结果字段 | 冲突变化 |
| `risk_shift` | string[] | 否 | 结果字段 | 风险变化 |
| `foreshadowing_added` | string[] | 否 | 承诺字段 | 新增伏笔 |
| `foreshadowing_advanced` | string[] | 否 | 承诺字段 | 推进的伏笔 |
| `foreshadowing_resolved` | string[] | 否 | 承诺字段 | 回收的伏笔 |
| `false_leads_added` | string[] | 否 | 承诺字段 | 新增误导 |
| `promises_opened` | string[] | 否 | 承诺字段 | 新开的叙事承诺 |
| `promises_delayed` | string[] | 否 | 承诺字段 | 延后的承诺 |
| `progression_strength` | enum string | 是 | 审查字段 | 推进强度 |
| `legality_status` | enum string | 否 | 审查字段 | 合法性状态 |
| `character_consistency_status` | enum string | 否 | 审查字段 | 角色一致性状态 |
| `redundancy_risk` | enum string | 否 | 审查字段 | 冗余风险 |
| `removable_without_loss` | boolean | 否 | 审查字段 | 可删而不伤主线 |
| `review_notes` | string[] | 否 | 审查字段 | 审查备注 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `unit_id`

#### 类型

`string`

#### 必填

是

#### 说明

单元唯一标识。

#### 示例

- `pu_scene_014`
- `pu_chapter_06`
- `pu_arc_02`

---

### 5.2 `level`

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

统一表示不同粒度的推进单元。

---

### 5.3 `title_or_label`

#### 类型

`string`

#### 必填

否

#### 说明

短标题或功能标签。

#### 示例

- `雨夜夺令`
- `第一次公开对抗`
- `中段关系反转`

---

### 5.4 引用字段

#### `parent_unit`

所属上级单元 ID。

#### `previous_unit`

前一单元 ID。

#### `next_unit`

后一单元 ID。

#### 说明

用于建立单元之间的结构关系，不建议复制嵌套全文内容。

---

### 5.5 目标字段

#### `unit_goal`

##### 类型

`string`

##### 必填

是

##### 说明

本单元存在的主要理由。

#### `local_goal`

##### 类型

`string`

##### 必填

否

##### 说明

更具体、更局部的操作目标。

#### `hidden_goal`

##### 类型

`string`

##### 必填

否

##### 说明

文本中未直接说出，但在行动层面实际起作用的目标。

#### `success_condition`

##### 类型

`string`

##### 必填

否

##### 说明

什么算这个单元完成。

#### `failure_condition`

##### 类型

`string`

##### 必填

否

##### 说明

什么算这个单元失败。

---

### 5.6 输入字段

#### `input_state_ref`

##### 类型

`string`

##### 必填

是

##### 说明

引用进入该单元前的 `NarrativeState`。

#### `active_characters`

##### 类型

`string[]`

##### 必填

是

##### 说明

当前参与推进的角色 ID。

#### `active_conflicts`

##### 类型

`string[]`

##### 必填

否

##### 说明

本单元当前实际处理的冲突。

#### `current_constraints`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前世界、关系、时间、资源等约束。

#### `active_promises_in_scope`

##### 类型

`string[]`

##### 必填

否

##### 说明

当前会被本单元影响的承诺线程或伏笔线程 ID / 标签。

---

### 5.7 行动字段

#### `initiator`

##### 类型

`string`

##### 必填

是

##### 说明

发起关键动作或关键决策的角色。

#### `responders`

##### 类型

`string[]`

##### 必填

否

##### 说明

对关键行动作出回应的角色。

#### `key_decision`

##### 类型

`string`

##### 必填

是

##### 说明

本单元最关键的选择。

#### `conflict_type`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `interpersonal`
- `internal`
- `social`
- `environmental`
- `informational`
- `mixed`

#### `tactics_used`

##### 类型

`string[]`

##### 必填

否

##### 说明

采取的手段、策略或推进方式。

#### `cost_paid`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色或局势为本单元付出的代价。

#### `compromise_or_escalation`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `compromise`
- `stalemate`
- `escalation`
- `collapse`
- `partial_resolution`

---

### 5.8 事件字段

#### `event_summary`

##### 类型

`string`

##### 必填

是

##### 说明

本单元发生了什么的简明描述。

#### `decisive_moment`

##### 类型

`string`

##### 必填

否

##### 说明

真正改变局势的瞬间。

#### `reveal_event`

##### 类型

`string`

##### 必填

否

##### 说明

有无关键揭露。

#### `reversal_event`

##### 类型

`string`

##### 必填

否

##### 说明

有无关键反转。

#### `fallout_event`

##### 类型

`string`

##### 必填

否

##### 说明

即时后果事件。

---

### 5.9 输出字段

#### `output_state_ref`

##### 类型

`string`

##### 必填

是

##### 说明

本单元结束后的 `NarrativeState`。

#### `state_change_summary`

##### 类型

`string[]`

##### 必填

是

##### 说明

本单元导致的关键状态变化摘要。

#### `goal_shift`

##### 类型

`object`

##### 必填

否

##### 推荐结构

```json
{
  "c001": "从夺令转为撤离并封口",
  "c002": "从旁观试探转为决定是否帮助隐瞒"
}
```

#### `relation_shift`

##### 类型

`object`

##### 必填

否

##### 推荐结构

```json
{
  "c001->c002": "信任进一步摇摆",
  "c002->c001": "由怀疑转为复杂同情与警惕"
}
```

#### `information_shift`

##### 类型

`string[]`

##### 必填

否

##### 说明

谁获得了什么信息、什么被暴露或被遮蔽。

#### `conflict_shift`

##### 类型

`string[]`

##### 必填

否

##### 说明

冲突如何升级、缓解或转移。

#### `risk_shift`

##### 类型

`string[]`

##### 必填

否

##### 说明

风险如何变化。

---

### 5.10 承诺字段

#### `foreshadowing_added`

##### 类型

`string[]`

##### 必填

否

##### 说明

新埋设的伏笔。

#### `foreshadowing_advanced`

##### 类型

`string[]`

##### 必填

否

##### 说明

被推进的伏笔或承诺线程。

#### `foreshadowing_resolved`

##### 类型

`string[]`

##### 必填

否

##### 说明

被回收的伏笔。

#### `false_leads_added`

##### 类型

`string[]`

##### 必填

否

##### 说明

新增误导项。

#### `promises_opened`

##### 类型

`string[]`

##### 必填

否

##### 说明

本单元新建立的叙事承诺。

#### `promises_delayed`

##### 类型

`string[]`

##### 必填

否

##### 说明

被明确延后的承诺。

---

### 5.11 审查字段

#### `progression_strength`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `none`
- `weak`
- `medium`
- `strong`

##### 说明

描述本单元推进力度。

#### `legality_status`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `valid`
- `valid_with_cost`
- `warning`
- `invalid`

#### `character_consistency_status`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `valid`
- `valid_with_cost`
- `warning`
- `invalid`

#### `redundancy_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `low`
- `medium`
- `high`

#### `removable_without_loss`

##### 类型

`boolean`

##### 必填

否

##### 说明

若删除本单元，是否几乎不伤主线。

#### `review_notes`

##### 类型

`string[]`

##### 必填

否

##### 说明

审查层备注。

---

### 5.12 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者补充说明。

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段定义单元基本身份，不应轻易改：

- `unit_id`
- `level`
- `input_state_ref`
- `output_state_ref`

---

### 6.2 目标字段

这些字段定义单元为何存在：

- `unit_goal`
- `local_goal`
- `hidden_goal`
- `success_condition`
- `failure_condition`

---

### 6.3 行动字段

这些字段定义推进如何发生：

- `initiator`
- `responders`
- `key_decision`
- `conflict_type`
- `tactics_used`
- `cost_paid`
- `compromise_or_escalation`

---

### 6.4 结果字段

这些字段定义推进后发生了什么变化：

- `event_summary`
- `decisive_moment`
- `reveal_event`
- `reversal_event`
- `fallout_event`
- `state_change_summary`
- `goal_shift`
- `relation_shift`
- `information_shift`
- `conflict_shift`
- `risk_shift`

---

### 6.5 承诺字段

这些字段定义本单元如何影响伏笔与承诺：

- `foreshadowing_added`
- `foreshadowing_advanced`
- `foreshadowing_resolved`
- `false_leads_added`
- `promises_opened`
- `promises_delayed`

---

### 6.6 审查字段

这些字段定义本单元的质量判断：

- `progression_strength`
- `legality_status`
- `character_consistency_status`
- `redundancy_risk`
- `removable_without_loss`
- `review_notes`

---

## 7. 合法性检查建议

一个合法的 `PlotUnit` 至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `unit_id`
- `level`
- `unit_goal`
- `input_state_ref`
- `active_characters`
- `initiator`
- `key_decision`
- `conflict_type`
- `event_summary`
- `output_state_ref`
- `state_change_summary`
- `progression_strength`

### 7.2 必须存在状态变化

`state_change_summary` 不应为空。

### 7.3 输入输出应可对应

`output_state_ref` 应与 `input_state_ref` 存在合理转移关系。

### 7.4 决策与行动不能脱节

`key_decision` 应与 `event_summary` 和 `state_change_summary` 有明确关联。

### 7.5 冲突与代价应至少有其一成立

若冲突强但毫无代价，通常要给出说明；若无冲突又无变化，通常为弱单元或无效单元。

---

## 8. 更新规则

### 8.1 每次有效推进新增一个 PlotUnit

不建议覆盖旧单元。

### 8.2 审查字段可后补

允许先生成主要字段，再在审查阶段写入：

- `legality_status`
- `character_consistency_status`
- `redundancy_risk`
- `review_notes`

### 8.3 结果字段应与输出状态联动

若修改：

- `state_change_summary`
- `goal_shift`
- `relation_shift`
- `information_shift`
- `conflict_shift`
- `risk_shift`

则应同步检查 `output_state_ref` 对应内容。

### 8.4 承诺字段应与 ForeshadowGraph 联动

若本单元新增、推进或回收了承诺，后续应同步更新 `ForeshadowGraph`。

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
{
  "unit_id": "",
  "level": "",
  "unit_goal": "",
  "input_state_ref": "",
  "active_characters": [],
  "initiator": "",
  "key_decision": "",
  "active_conflicts": [],
  "event_summary": "",
  "output_state_ref": "",
  "state_change_summary": [],
  "foreshadowing_added": [],
  "foreshadowing_resolved": [],
  "progression_strength": ""
}
```

---

## 10. 示例

```json
{
  "unit_id": "pu_scene_014",
  "level": "scene",
  "title_or_label": "雨夜夺令",
  "parent_unit": "chapter_06",
  "previous_unit": "pu_scene_013",
  "next_unit": "pu_scene_015",
  "unit_goal": "在巡查队到来前决定是否夺取令牌",
  "local_goal": "逼出 c002 的真实立场",
  "hidden_goal": "让 c003 通过试探诱发 c001 异常反应",
  "success_condition": "c001 拿到令牌且秘密未暴露",
  "failure_condition": "巡查队到场前局面失控",
  "input_state_ref": "s_014_scene",
  "active_characters": ["c001", "c002", "c003"],
  "active_conflicts": [
    "令牌争夺",
    "信任危机",
    "身份暴露风险"
  ],
  "current_constraints": [
    "暴雨影响判断",
    "巡查队正在接近",
    "c001 无法长时间正面斗法"
  ],
  "active_promises_in_scope": [
    "残魂秘密会在高压场景下逼近暴露",
    "c002 的真实立场终将显明"
  ],
  "initiator": "c003",
  "responders": ["c001", "c002"],
  "key_decision": "c001 决定不再等待 c002 表态，而是冒险先手夺令",
  "conflict_type": "mixed",
  "tactics_used": [
    "言语试探",
    "假动作诱敌",
    "短时越位抢夺"
  ],
  "cost_paid": [
    "c001 旧伤复发",
    "残魂反应被 c002 察觉到异常"
  ],
  "compromise_or_escalation": "escalation",
  "event_summary": "c001 抢到令牌，但在高压中出现异常反应，c002 由此确认其体内确有隐患。",
  "decisive_moment": "c001 在 c003 逼迫下强行发动异常感知能力完成反抢",
  "reveal_event": "c002 首次确认 c001 身上存在非正常力量痕迹",
  "reversal_event": "c003 原以为能逼 c001 失控，却反而让其拿到了令牌",
  "fallout_event": "巡查队被灵压波动吸引，提前改变路线",
  "output_state_ref": "s_015_scene",
  "state_change_summary": [
    "令牌归属改变",
    "c002 对 c001 的怀疑转为半确认",
    "秘密暴露风险显著上升",
    "巡查队威胁从潜在变为迫近"
  ],
  "goal_shift": {
    "c001": "从夺令转为撤离并封口",
    "c002": "从旁观试探转为决定是否帮助隐瞒"
  },
  "relation_shift": {
    "c001->c002": "信任进一步摇摆",
    "c002->c001": "由怀疑转为复杂同情与警惕",
    "c001->c003": "敌意升级"
  },
  "information_shift": [
    "c002 获得关于 c001 异常状态的新证据",
    "巡查队可能因灵压痕迹追踪到此地"
  ],
  "conflict_shift": [
    "局部争夺结束",
    "逃离压力和封口压力上升"
  ],
  "risk_shift": [
    "身份暴露风险上升至 high",
    "身体损耗风险上升至 medium"
  ],
  "foreshadowing_added": [
    "c002 将来可能成为秘密见证者"
  ],
  "foreshadowing_advanced": [
    "残魂秘密正在逼近首次正式揭露"
  ],
  "foreshadowing_resolved": [],
  "false_leads_added": [
    "巡查队可能误以为异常来自 c003"
  ],
  "promises_opened": [
    "c002 是否会替 c001 保密"
  ],
  "promises_delayed": [
    "被逐真相仍未揭露"
  ],
  "progression_strength": "strong",
  "legality_status": "valid",
  "character_consistency_status": "valid_with_cost",
  "redundancy_risk": "low",
  "removable_without_loss": false,
  "review_notes": [
    "本单元同时推进了目标、信息、关系与风险，属于强推进",
    "角色决策符合 c001 在高压下冒险的模式，但必须在后续体现旧伤后果"
  ],
  "notes": "当前重点是保持“强推进”同时不提前完成主线回收。"
}
```

---

## 11. 一句话总结

`PlotUnit Schema` 的任务，是把一次叙事推进压缩成一份**可追踪输入、可描述行动、可记录结果、可联动状态与承诺、可直接审查的状态转移对象**。
