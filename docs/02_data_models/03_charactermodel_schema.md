# CharacterModel Schema

## 文档目的
将 `01_concepts/03_charactermodel.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`CharacterModel`

---

## 2. Schema 目标

`CharacterModel` 用于定义角色作为“决策体”的结构。

它应支持系统回答：

- 这个角色想要什么
- 这个角色害怕什么
- 这个角色有哪些局限
- 这个角色知道什么，不知道什么
- 这个角色和谁有关系，关系如何影响行为
- 这个角色在成长弧线上处于什么阶段

它不是人物简介，而是一个可用于驱动 `PlotUnit`、约束 `NarrativeState`、支撑审查的角色逻辑对象。

---

## 3. 顶层结构

```json
{
  "character_id": "",
  "name": "",
  "role": "",
  "narrative_importance": "",
  "identity": "",
  "affiliation": "",
  "social_position": "",
  "public_label": "",
  "private_truth": "",
  "outer_goal": "",
  "short_term_goal": "",
  "long_term_goal": "",
  "avoidance_goal": "",
  "priority_order": [],
  "inner_need": "",
  "fear": "",
  "flaw": "",
  "blind_spot": "",
  "self_image": "",
  "emotional_pattern": "",
  "strengths": [],
  "skills": [],
  "available_resources": [],
  "permissions": [],
  "limitations": [],
  "secrets": [],
  "hidden_history": [],
  "exposure_risks": [],
  "reveal_triggers": [],
  "relations": [],
  "knowledge_state": [],
  "misinformation": [],
  "unknown_critical_info": [],
  "perspective_limit": "",
  "arc_type": "",
  "arc_start": "",
  "arc_target": "",
  "arc_stage": "",
  "transformation_cost": "",
  "notes": ""
}
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `character_id` | string | 是 | 硬字段 | 角色唯一 ID |
| `name` | string | 是 | 硬字段 | 角色名称 |
| `role` | enum string | 是 | 硬字段 | 角色在作品中的叙事作用 |
| `narrative_importance` | enum string | 是 | 硬字段 | 叙事重要度 |
| `identity` | string | 是 | 硬字段 | 角色身份 |
| `affiliation` | string | 否 | 硬字段 | 所属组织/阵营 |
| `social_position` | string | 否 | 可成长字段 | 社会位置 |
| `public_label` | string | 否 | 可成长字段 | 外界对其公开认知 |
| `private_truth` | string | 否 | 硬字段 | 真实身份或隐藏真相 |
| `outer_goal` | string | 是 | 可成长字段 | 外在目标 |
| `short_term_goal` | string | 否 | 运行态字段 | 当前短期目标 |
| `long_term_goal` | string | 否 | 可成长字段 | 长期目标 |
| `avoidance_goal` | string | 否 | 可成长字段 | 想避免的结果 |
| `priority_order` | string[] | 否 | 可成长字段 | 目标优先级 |
| `inner_need` | string | 是 | 硬字段 | 内在需求 |
| `fear` | string | 是 | 硬字段 | 核心恐惧 |
| `flaw` | string | 是 | 硬字段 | 核心缺陷 |
| `blind_spot` | string | 否 | 硬字段 | 认知盲区 |
| `self_image` | string | 否 | 可成长字段 | 自我认知 |
| `emotional_pattern` | string | 否 | 可成长字段 | 常见情绪模式 |
| `strengths` | string[] | 否 | 硬字段 | 优势 |
| `skills` | string[] | 否 | 可成长字段 | 技能 |
| `available_resources` | string[] | 否 | 运行态字段 | 当前可调用资源 |
| `permissions` | string[] | 否 | 硬字段 | 身份/制度权限 |
| `limitations` | string[] | 否 | 硬字段 | 限制条件 |
| `secrets` | string[] | 否 | 硬字段 | 秘密列表 |
| `hidden_history` | string[] | 否 | 硬字段 | 隐藏经历 |
| `exposure_risks` | string[] | 否 | 运行态字段 | 暴露风险 |
| `reveal_triggers` | string[] | 否 | 运行态字段 | 暴露触发条件 |
| `relations` | object[] | 否 | 可成长字段 | 关系集合 |
| `knowledge_state` | string[] | 否 | 运行态字段 | 当前已知信息 |
| `misinformation` | string[] | 否 | 运行态字段 | 当前持有的错误信息 |
| `unknown_critical_info` | string[] | 否 | 运行态字段 | 当前未知但关键的信息 |
| `perspective_limit` | string | 否 | 硬字段 | 视角/认知边界 |
| `arc_type` | enum string | 否 | 硬字段 | 成长类型 |
| `arc_start` | string | 否 | 硬字段 | 成长起点 |
| `arc_target` | string | 否 | 可成长字段 | 成长目标 |
| `arc_stage` | string | 否 | 可成长字段 | 当前成长阶段 |
| `transformation_cost` | string | 否 | 可成长字段 | 成长代价 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `character_id`

#### 类型

`string`

#### 必填

是

#### 说明

角色唯一标识。

#### 约束建议

- 在项目内不可重复
- 建议使用稳定短 ID
- 一旦引用，不建议中途改名

#### 示例

- `c001`
- `hero_main`
- `mentor_01`

---

### 5.2 `name`

#### 类型

`string`

#### 必填

是

#### 说明

角色名称。

#### 约束建议

- 建议 1 到 20 字符
- 可与 `character_id` 分离
- 名称可改，但需保持别名映射一致

---

### 5.3 `role`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `protagonist`
- `deuteragonist`
- `antagonist`
- `mentor`
- `ally`
- `rival`
- `foil`
- `witness`
- `support`

#### 说明

定义角色在叙事中的功能位置。

---

### 5.4 `narrative_importance`

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

影响：

- 是否需要长期维护状态
- 是否需要完整成长弧
- 是否进入高优先级审查

---

### 5.5 `identity`

#### 类型

`string`

#### 必填

是

#### 说明

角色真实身份或基础身份。

#### 示例

- `被逐出外门的前宗门弟子`
- `王城监察司见习官`
- `黑市信息贩子`

---

### 5.6 `affiliation`

#### 类型

`string`

#### 必填

否

#### 说明

角色当前正式所属组织、阵营或集团。

#### 示例

- `天衡宗`
- `王城监察司`
- `无正式归属`

---

### 5.7 `social_position`

#### 类型

`string`

#### 必填

否

#### 说明

角色在社会结构中的位置。

#### 示例

- `边缘散修`
- `世家嫡系`
- `低级调查员`

---

### 5.8 `public_label`

#### 类型

`string`

#### 必填

否

#### 说明

外界对角色的公开认知、社会标签、流言式形象。

#### 示例

- `资质平庸`
- `命硬`
- `危险人物`

---

### 5.9 `private_truth`

#### 类型

`string`

#### 必填

否

#### 说明

角色不公开的真实身份、血缘、处境或真相。

#### 示例

- `体内封存上古残魂`
- `真实身份是失踪皇族后裔`

---

### 5.10 目标字段

#### `outer_goal`

##### 类型

`string`

##### 必填

是

##### 说明

角色最显性的主要目标。

#### `short_term_goal`

##### 类型

`string`

##### 必填

否

##### 说明

当前阶段正在追求的短期目标。

#### `long_term_goal`

##### 类型

`string`

##### 必填

否

##### 说明

长期目标或阶段性终极目标。

#### `avoidance_goal`

##### 类型

`string`

##### 必填

否

##### 说明

角色强烈想避免发生的结果。

#### `priority_order`

##### 类型

`string[]`

##### 必填

否

##### 说明

当多个目标冲突时的优先顺序。

##### 示例

```json
["活下去", "隐藏秘密", "回宗", "查真相"]
```

---

### 5.11 心理与需求字段

#### `inner_need`

##### 类型

`string`

##### 必填

是

##### 说明

角色深层真正需要解决的缺口。

#### `fear`

##### 类型

`string`

##### 必填

是

##### 说明

核心恐惧，应能直接影响行为。

#### `flaw`

##### 类型

`string`

##### 必填

是

##### 说明

核心缺陷，应能在剧情中制造问题。

#### `blind_spot`

##### 类型

`string`

##### 必填

否

##### 说明

角色认知盲区或稳定误判区域。

#### `self_image`

##### 类型

`string`

##### 必填

否

##### 说明

角色如何理解自己。

#### `emotional_pattern`

##### 类型

`string`

##### 必填

否

##### 说明

常见情绪反应模式。

---

### 5.12 能力字段

#### `strengths`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色的长期优势。

#### `skills`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色掌握的具体技能。

#### `available_resources`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色当前可调用的资源。

##### 说明补充

与长期拥有不同，这里更偏“当前可使用”。

#### `permissions`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色因身份、组织、职位获得的权限。

#### `limitations`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色的能力边界、环境限制、身体限制或社会限制。

---

### 5.13 秘密字段

#### `secrets`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色持有或构成角色风险的秘密。

#### `hidden_history`

##### 类型

`string[]`

##### 必填

否

##### 说明

被隐藏的过去经历、关键历史、创伤事件。

#### `exposure_risks`

##### 类型

`string[]`

##### 必填

否

##### 说明

秘密或真实身份可能暴露的风险来源。

#### `reveal_triggers`

##### 类型

`string[]`

##### 必填

否

##### 说明

会触发暴露的条件。

---

### 5.14 `relations`

#### 类型

`object[]`

#### 必填

否

#### 推荐结构

```json
{
  "target_id": "",
  "relation_type": "",
  "trust_level": 0.0,
  "dependency_level": 0.0,
  "conflict_level": 0.0,
  "obligation_level": 0.0,
  "emotional_weight": 0.0,
  "current_status": ""
}
```

#### 字段说明

- `target_id`：关联角色 ID
- `relation_type`：关系类型
- `trust_level`：信任度
- `dependency_level`：依赖度
- `conflict_level`：冲突度
- `obligation_level`：责任/亏欠
- `emotional_weight`：情感权重
- `current_status`：当前关系说明

#### 数值建议

- `0.0` 到 `1.0`
- 不要求对称
- 应允许随剧情变化

---

### 5.15 信息字段

#### `knowledge_state`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色当前已经确认知道的信息。

#### `misinformation`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色当前持有的错误认知。

#### `unknown_critical_info`

##### 类型

`string[]`

##### 必填

否

##### 说明

角色尚未知道、但对后续关键的信息。

#### `perspective_limit`

##### 类型

`string`

##### 必填

否

##### 说明

角色的视角边界、判断边界、认知限制方式。

---

### 5.16 成长字段

#### `arc_type`

##### 类型

`enum string`

##### 必填

否

##### 推荐取值

- `成长`
- `堕落`
- `觉醒`
- `认知修正`
- `自毁`
- `关系修复`
- `信念崩塌`

#### `arc_start`

##### 类型

`string`

##### 必填

否

##### 说明

成长弧起点状态。

#### `arc_target`

##### 类型

`string`

##### 必填

否

##### 说明

成长弧希望抵达的目标状态。

#### `arc_stage`

##### 类型

`string`

##### 必填

否

##### 说明

当前成长阶段。

##### 示例

- `未觉醒`
- `开始怀疑`
- `第一次偏移`
- `强迫对抗`
- `阶段性突破`

#### `transformation_cost`

##### 类型

`string`

##### 必填

否

##### 说明

成长所需承担的代价。

---

### 5.17 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者保留备注区，用于写暂未结构化但重要的说明。

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段不应轻易改动：

- `character_id`
- `name`
- `role`
- `narrative_importance`
- `identity`
- `affiliation`
- `inner_need`
- `fear`
- `flaw`
- `blind_spot`
- `permissions`
- `limitations`
- `perspective_limit`
- `arc_type`
- `arc_start`

---

### 6.2 可成长字段

这些字段会随叙事推进稳定变化：

- `social_position`
- `public_label`
- `outer_goal`
- `long_term_goal`
- `avoidance_goal`
- `priority_order`
- `self_image`
- `emotional_pattern`
- `skills`
- `relations`
- `arc_target`
- `arc_stage`
- `transformation_cost`

---

### 6.3 运行态字段

这些字段会被 `NarrativeState` 高频调用或更新：

- `short_term_goal`
- `available_resources`
- `exposure_risks`
- `reveal_triggers`
- `knowledge_state`
- `misinformation`
- `unknown_critical_info`

---

### 6.4 派生字段

这些字段不建议主存，可后续推导：

- 当前最脆弱关系
- 当前最强冲突对象
- 当前暴露风险等级
- 当前成长推进率
- 当前行为保守/激进倾向

---

## 7. 合法性检查建议

一个合法的 `CharacterModel` 至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `character_id`
- `name`
- `role`
- `narrative_importance`
- `identity`
- `outer_goal`
- `inner_need`
- `fear`
- `flaw`

### 7.2 目标与心理不完全空转

例如：

- 有目标但没有恐惧和缺陷，角色会过于工具化
- 有创伤和性格词，但没有目标，角色难以驱动剧情

### 7.3 不自相矛盾

例如：

- `fear = 被抛弃`，但关系线对任何人都完全无感，且无说明
- `flaw = 冲动`，但所有行动都极度谨慎，且无成长过程说明
- `limitations` 极强，但 `available_resources` 和剧情要求完全忽略这些限制

### 7.4 关系字段能影响行为

如果存在 `relations`，应至少能在 `PlotUnit` 层影响信任、敌意、责任或依赖。

---

## 8. 更新规则

### 8.1 可频繁更新的字段

允许在叙事推进中持续更新：

- `short_term_goal`
- `available_resources`
- `relations`
- `knowledge_state`
- `misinformation`
- `unknown_critical_info`
- `arc_stage`

### 8.2 可阶段性更新的字段

允许在篇章或阶段节点更新：

- `public_label`
- `outer_goal`
- `priority_order`
- `self_image`
- `emotional_pattern`
- `transformation_cost`

### 8.3 不建议频繁修改的字段

若改动，应记录到决策日志：

- `identity`
- `inner_need`
- `fear`
- `flaw`
- `blind_spot`
- `arc_type`
- `arc_start`

### 8.4 需要版本化处理的字段

若以下字段发生重大变化，建议视为角色版本更新：

- 核心身份改变
- 核心缺陷改变
- 核心恐惧改变
- 角色叙事功能改变，例如从 `ally` 变成 `antagonist`

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
{
  "character_id": "",
  "name": "",
  "role": "",
  "narrative_importance": "",
  "identity": "",
  "affiliation": "",
  "outer_goal": "",
  "inner_need": "",
  "fear": "",
  "flaw": "",
  "strengths": [],
  "limitations": [],
  "secrets": [],
  "relations": [],
  "knowledge_state": [],
  "arc_stage": ""
}
```

---

## 10. 示例

```json
{
  "character_id": "c001",
  "name": "沈青",
  "role": "protagonist",
  "narrative_importance": "core",
  "identity": "被逐出外门的前宗门弟子",
  "affiliation": "无正式归属，曾属天衡宗",
  "social_position": "边缘散修",
  "public_label": "资质平庸、命硬",
  "private_truth": "体内封存上古残魂",
  "outer_goal": "在三年内重返天衡宗",
  "short_term_goal": "拿到进入黑水泽试炼的资格",
  "long_term_goal": "查清被逐真相并保住性命",
  "avoidance_goal": "不让体内秘密暴露给监察司",
  "priority_order": [
    "活下去",
    "隐藏秘密",
    "回宗",
    "查真相"
  ],
  "inner_need": "摆脱被抛弃感并建立稳定自我认同",
  "fear": "再次失去唯一愿意保护自己的人",
  "flaw": "关键时刻倾向逃避真正的情感决断",
  "blind_spot": "总把求助理解为软弱",
  "self_image": "不值得被长期信任的人",
  "emotional_pattern": "平时克制，涉及亲近之人时会突然失控",
  "strengths": [
    "感知异常敏锐",
    "忍耐力强",
    "擅长观察他人情绪漏洞"
  ],
  "skills": [
    "低阶符术",
    "野外求生",
    "快速记忆地形"
  ],
  "available_resources": [
    "残缺护身符",
    "已故师兄留下的旧地图"
  ],
  "permissions": [],
  "limitations": [
    "经脉旧伤未愈",
    "缺乏正式宗门庇护",
    "无法长时间正面斗法"
  ],
  "secrets": [
    "体内残魂会在重伤时短暂夺取感知",
    "被逐事件与宗门内斗有关"
  ],
  "hidden_history": [
    "幼时曾在王城秘牢短暂生活"
  ],
  "exposure_risks": [
    "搜魂",
    "高压对战失控",
    "接触特定古阵"
  ],
  "reveal_triggers": [
    "灵识过载",
    "残魂主动护主",
    "与王城旧档接触"
  ],
  "relations": [
    {
      "target_id": "c002",
      "relation_type": "mentor_like",
      "trust_level": 0.72,
      "dependency_level": 0.61,
      "conflict_level": 0.18,
      "obligation_level": 0.84,
      "emotional_weight": 0.76,
      "current_status": "信任但隐瞒核心秘密"
    },
    {
      "target_id": "c003",
      "relation_type": "rival",
      "trust_level": 0.12,
      "dependency_level": 0.07,
      "conflict_level": 0.83,
      "obligation_level": 0.05,
      "emotional_weight": 0.54,
      "current_status": "表面敌对，实则互相试探"
    }
  ],
  "knowledge_state": [
    "自己被逐并非单纯违规",
    "黑水泽试炼名额被人为操控"
  ],
  "misinformation": [
    "误以为当年的师父主动放弃了自己"
  ],
  "unknown_critical_info": [
    "真正推动逐出决定的人来自监察司",
    "残魂与自己身世有关"
  ],
  "perspective_limit": "只能根据他人表情、动作和已知历史推断其真实意图",
  "arc_type": "认知修正",
  "arc_start": "自我否定、孤立求生",
  "arc_target": "能主动建立信任并承担选择后果",
  "arc_stage": "未觉醒",
  "transformation_cost": "必须承认自己对他人的依赖，并冒暴露秘密的风险",
  "notes": "当前重点是让 fear、flaw 和 relation 三者在前两个 arc 里稳定联动。"
}
```

---

## 11. 一句话总结

`CharacterModel Schema` 的任务，是把角色压缩成一份**可驱动决策、可限制行为、可追踪成长、可支持审查的角色逻辑对象**，让剧情推进来自人物，而不是来自外部强推。
