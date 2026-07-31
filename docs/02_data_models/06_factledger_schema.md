# FactLedger Schema

## 文档目的
将 `01_concepts/06_factledger.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`FactLedger`

---

## 2. Schema 目标

`FactLedger` 用于记录**已确认、可检索、可校验、可约束后文**的叙事实。

它应支持系统回答：

- 哪些事实已经成立
- 这些事实何时成立
- 这些事实对谁可见
- 这些事实当前是否仍有效
- 这些事实来自哪个 `PlotUnit` 或规则源
- 后续生成是否与这些事实冲突

它不是摘要库，也不是评论库，更不是伏笔库。  
它是自动小说系统的**硬记忆层**。

---

## 3. 顶层结构

```json
[
  {
    "fact_id": "",
    "fact_type": "",
    "category": "",
    "statement": "",
    "involved_entities": [],
    "scope": "",
    "established_in": "",
    "source_plotunit": "",
    "source_event": "",
    "evidence_type": "",
    "confidence": "",
    "established_time": "",
    "effective_from": "",
    "effective_until": "",
    "chronological_order": 0,
    "visibility": "",
    "known_by": [],
    "unknown_to": [],
    "misinformation_link": "",
    "status": "",
    "mutable": false,
    "revision_rule": "",
    "review_priority": "",
    "contradiction_risk": "",
    "notes": ""
  }
]
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `fact_id` | string | 是 | 硬字段 | 事实唯一 ID |
| `fact_type` | enum string | 是 | 硬字段 | 事实类型 |
| `category` | string | 否 | 分类字段 | 更细的事实分类 |
| `statement` | string | 是 | 硬字段 | 事实陈述 |
| `involved_entities` | string[] | 否 | 引用字段 | 涉及的角色/地点/物品/组织 |
| `scope` | enum string | 否 | 硬字段 | 作用范围 |
| `established_in` | string | 是 | 溯源字段 | 建立位置 |
| `source_plotunit` | string | 否 | 引用字段 | 来源 PlotUnit |
| `source_event` | string | 否 | 溯源字段 | 来源事件 |
| `evidence_type` | enum string | 否 | 判定字段 | 确认方式 |
| `confidence` | enum string | 是 | 判定字段 | 确认强度 |
| `established_time` | string | 否 | 时间字段 | 建立时间 |
| `effective_from` | string | 否 | 时间字段 | 生效时间 |
| `effective_until` | string | 否 | 时间字段 | 失效时间 |
| `chronological_order` | integer | 是 | 时间字段 | 全局时间顺序 |
| `visibility` | enum string | 是 | 权限字段 | 可见性级别 |
| `known_by` | string[] | 否 | 权限字段 | 哪些角色已知 |
| `unknown_to` | string[] | 否 | 权限字段 | 哪些角色明确未知 |
| `misinformation_link` | string | 否 | 权限字段 | 关联误解对象 |
| `status` | enum string | 是 | 状态字段 | 当前状态 |
| `mutable` | boolean | 是 | 状态字段 | 是否允许后续变更 |
| `revision_rule` | string | 否 | 状态字段 | 在何种条件下更新 |
| `review_priority` | enum string | 否 | 审查字段 | 审查优先级 |
| `contradiction_risk` | enum string | 否 | 审查字段 | 写错后冲突风险 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `fact_id`

#### 类型

`string`

#### 必填

是

#### 说明

事实唯一标识。

#### 示例

- `f_001`
- `fact_item_014`
- `f_relation_023`

#### 约束建议

- 在项目内不可重复
- 一旦被其他对象引用，不应中途修改

---

### 5.2 `fact_type`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `world_rule`
- `character_identity`
- `relation`
- `event`
- `resource`
- `knowledge`
- `status_change`
- `location_state`
- `institution_rule`

#### 说明

定义这条事实属于哪一大类。

---

### 5.3 `category`

#### 类型

`string`

#### 必填

否

#### 说明

对 `fact_type` 的进一步细分。

#### 示例

- `death_rule`
- `item_ownership`
- `alliance_status`
- `exposure_status`
- `pursuit_trigger`

---

### 5.4 `statement`

#### 类型

`string`

#### 必填

是

#### 说明

事实的核心陈述。

#### 规则

- 尽量简洁
- 尽量单一命题
- 避免把事实、解释、评价揉在一起

#### 好例子

- `黑水泽试炼令牌当前归 c001 所有。`
- `c002 已确认 c001 身上存在异常力量痕迹。`

#### 坏例子

- `主角很可能因为孤独所以开始信任 c002。`

这更接近推断，不是事实。

---

### 5.5 `involved_entities`

#### 类型

`string[]`

#### 必填

否

#### 说明

该事实涉及的实体 ID 或实体名。

#### 可包含

- 角色 ID
- 地点
- 组织
- 物品
- 规则对象

---

### 5.6 `scope`

#### 类型

`enum string`

#### 必填

否

#### 推荐取值

- `global`
- `faction`
- `local`
- `character_specific`
- `relationship_specific`

#### 说明

表示这条事实作用于多大范围。

---

### 5.7 溯源字段

#### `established_in`

##### 类型

`string`

##### 必填

是

##### 说明

建立位置，可是章节、场景或初始化节点。

#### `source_plotunit`

##### 类型

`string`

##### 必填

否

##### 说明

若来源于具体推进，写对应 `PlotUnit.unit_id`。

#### `source_event`

##### 类型

`string`

##### 必填

否

##### 说明

来源事件的简述。

---

### 5.8 判定字段

#### `evidence_type`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `system_rule`
- `direct_observation`
- `verified_action`
- `public_record`
- `confession`
- `documented_history`

##### 说明

说明为什么这条事实可被写入账本。

#### `confidence`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `confirmed`
- `highly_likely`
- `disputed`

##### 建议

第一版主账本优先只收 `confirmed`。  
其余可作为辅助层或暂不写入。

---

### 5.9 时间字段

#### `established_time`

##### 类型

`string`

##### 必填

否

##### 说明

事实被建立的叙事时间。

#### `effective_from`

##### 类型

`string`

##### 必填

否

##### 说明

从何时开始生效。

#### `effective_until`

##### 类型

`string`

##### 必填

否

##### 说明

到何时失效；若长期有效可为空。

#### `chronological_order`

##### 类型

`integer`

##### 必填

是

##### 说明

全局时间顺序索引。

---

### 5.10 权限字段

#### `visibility`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `public`
- `restricted`
- `hidden`
- `reader_only`
- `character_specific`

##### 说明

定义这条事实对谁可见。

#### `known_by`

##### 类型

`string[]`

##### 必填

否

##### 说明

明确知道这条事实的角色集合。

#### `unknown_to`

##### 类型

`string[]`

##### 必填

否

##### 说明

明确不知道这条事实的角色集合。

#### `misinformation_link`

##### 类型

`string`

##### 必填

否

##### 说明

若该事实存在对应误解，可写关联误解对象 ID 或标签。

---

### 5.11 状态字段

#### `status`

##### 类型

`enum string`

##### 必填

是

##### 推荐取值

- `active`
- `inactive`
- `superseded`
- `revoked`
- `destroyed`
- `revealed`

##### 说明

表示这条事实当前的生效状态。

#### `mutable`

##### 类型

`boolean`

##### 必填

是

##### 说明

该事实是否允许后续发生状态变化。

#### `revision_rule`

##### 类型

`string`

##### 必填

否

##### 说明

若允许变更，在什么条件下更新。

##### 示例

- `令牌被夺走、上交或销毁时更新`
- `若 c002 向他人披露，则更新 visibility 与 known_by`

---

### 5.12 审查字段

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

##### 说明

这条事实在审查中的重要性。

#### `contradiction_risk`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `high`
- `medium`
- `low`

##### 说明

若后文写错这条事实，造成冲突的风险程度。

---

### 5.13 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者补充说明。

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段定义事实本体，不应轻易改：

- `fact_id`
- `fact_type`
- `statement`
- `scope`
- `established_in`
- `confidence`
- `chronological_order`

---

### 6.2 权限字段

这些字段定义这条事实对谁可见：

- `visibility`
- `known_by`
- `unknown_to`
- `misinformation_link`

---

### 6.3 状态字段

这些字段定义事实当前是否仍有效、如何更新：

- `status`
- `mutable`
- `revision_rule`
- `effective_from`
- `effective_until`

---

### 6.4 审查字段

这些字段用于支持审查与优先级控制：

- `review_priority`
- `contradiction_risk`

---

### 6.5 派生字段

这些字段不建议主存，可后续推导：

- 某角色当前掌握事实总数
- 某条事实的泄露风险等级
- 某条事实与主线冲突的权重
- 当前章节涉及的关键事实集合

---

## 7. 合法性检查建议

一个合法的 `FactLedger` 条目至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `fact_id`
- `fact_type`
- `statement`
- `established_in`
- `confidence`
- `chronological_order`
- `visibility`
- `status`
- `mutable`

### 7.2 statement 为单一命题

不要把多个事实混在同一条里。

### 7.3 不把推断当事实

例如：

- `c001 已经爱上 c002`

若只是暧昧暗示，不应直接写入账本。

### 7.4 时间与状态一致

- 已销毁物品不应仍 `active`
- 已公开秘密不应仍完全 `hidden` 且无说明

### 7.5 可见性可解释

`visibility` 应与 `known_by` / `unknown_to` 基本一致。

---

## 8. 更新规则

### 8.1 新增

当某条新事实第一次被确认时，新增条目。

### 8.2 状态变更

当事实仍成立但状态变化时，更新：

- `status`
- `visibility`
- `known_by`
- `effective_until`

等字段。

### 8.3 被替代

若旧事实被新事实覆盖，不删除旧事实，改为：

- `status = superseded`

### 8.4 被撤销

若资格、权限、盟约失效，改为：

- `status = revoked`

### 8.5 被销毁

若物品、地点、组织不再存在，改为：

- `status = destroyed`

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
[
  {
    "fact_id": "",
    "fact_type": "",
    "statement": "",
    "involved_entities": [],
    "established_in": "",
    "chronological_order": 0,
    "visibility": "",
    "known_by": [],
    "status": "",
    "review_priority": ""
  }
]
```

---

## 10. 示例

```json
[
  {
    "fact_id": "f_001",
    "fact_type": "world_rule",
    "category": "death_rule",
    "statement": "灵根受损不可自然恢复。",
    "involved_entities": ["北衡界", "修行体系"],
    "scope": "global",
    "established_in": "worldmodel_init",
    "source_plotunit": "",
    "source_event": "system_rule_definition",
    "evidence_type": "system_rule",
    "confidence": "confirmed",
    "established_time": "project_init",
    "effective_from": "project_init",
    "effective_until": "",
    "chronological_order": 1,
    "visibility": "public",
    "known_by": ["all_relevant_characters", "reader"],
    "unknown_to": [],
    "misinformation_link": "",
    "status": "active",
    "mutable": false,
    "revision_rule": "",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "世界硬规则"
  },
  {
    "fact_id": "f_014",
    "fact_type": "resource",
    "category": "item_ownership",
    "statement": "黑水泽试炼令牌当前归 c001 所有。",
    "involved_entities": ["c001", "黑水泽试炼令牌"],
    "scope": "character_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "雨夜夺令",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 48,
    "visibility": "restricted",
    "known_by": ["c001", "c002", "c003"],
    "unknown_to": ["王城监察司"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "令牌被夺走、上交或销毁时更新",
    "review_priority": "high",
    "contradiction_risk": "high",
    "notes": "影响后续试炼资格与追踪风险"
  },
  {
    "fact_id": "f_015",
    "fact_type": "knowledge",
    "category": "exposure_status",
    "statement": "c002 已确认 c001 身上存在异常力量痕迹。",
    "involved_entities": ["c001", "c002"],
    "scope": "character_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "异常反应暴露",
    "evidence_type": "direct_observation",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 49,
    "visibility": "character_specific",
    "known_by": ["c002"],
    "unknown_to": ["c003", "监察司"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若 c002 向他人披露，则更新 visibility 与 known_by",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "关键秘密已进入半暴露状态"
  }
]
```

---

## 11. 一句话总结

`FactLedger Schema` 的任务，是把“已经算数的东西”压缩成一组**可检索、可追溯、可校验、可更新的事实条目**，为连续性、合法性和审查提供硬基础。
