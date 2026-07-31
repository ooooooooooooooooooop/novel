# WorldModel Schema

## 文档目的
将 `01_concepts/02_worldmodel.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`WorldModel`

---

## 2. Schema 目标

`WorldModel` 用于定义故事世界中：

- 什么允许发生
- 什么禁止发生
- 什么会产生代价
- 什么资源稀缺
- 什么秩序在起作用
- 什么冲突会天然出现

它不是世界观散文，而是一个可约束叙事、可支持审查、可服务状态转移的结构化对象。

---

## 3. 顶层结构

```json
{
  "world_name": "",
  "world_type": "",
  "reality_mode": "",
  "time_setting": "",
  "geography_scope": [],
  "civilization_level": "",
  "supernatural_presence": false,
  "death_rule": "",
  "hard_rules": [],
  "soft_rules": [],
  "exception_rules": [],
  "scarce_resources": [],
  "resource_owners": [],
  "resource_exchange_logic": [],
  "access_constraints": [],
  "power_structure": "",
  "institution_map": [],
  "rank_system": [],
  "punishment_system": [],
  "protection_system": [],
  "factions": [],
  "faction_relations": [],
  "unstable_balances": [],
  "long_term_conflicts": [],
  "exposure_risks": [],
  "action_costs": [],
  "forbidden_actions": [],
  "environmental_threats": [],
  "time_pressures": [],
  "consequence_rules": [],
  "escalation_paths": [],
  "rumor_or_info_flow": [],
  "recovery_limits": [],
  "notes": ""
}
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `world_name` | string | 否 | 硬字段 | 世界名或当前叙事区域名 |
| `world_type` | enum string | 是 | 硬字段 | 世界类型 |
| `reality_mode` | enum string | 是 | 硬字段 | 现实模式 |
| `time_setting` | string | 是 | 硬字段 | 时间背景 |
| `geography_scope` | string[] | 否 | 可扩展字段 | 主要地理范围 |
| `civilization_level` | enum string | 是 | 硬字段 | 文明/技术水平 |
| `supernatural_presence` | boolean | 是 | 硬字段 | 是否存在超自然力量 |
| `death_rule` | string | 是 | 硬字段 | 死亡/复活边界 |
| `hard_rules` | string[] | 是 | 硬字段 | 世界硬规则 |
| `soft_rules` | string[] | 否 | 可扩展字段 | 世界软规则 |
| `exception_rules` | string[] | 否 | 可扩展字段 | 例外规则 |
| `scarce_resources` | string[] | 否 | 硬字段 | 稀缺资源 |
| `resource_owners` | object[] | 否 | 可扩展字段 | 资源掌握方 |
| `resource_exchange_logic` | string[] | 否 | 可扩展字段 | 资源流动逻辑 |
| `access_constraints` | string[] | 否 | 运行依赖字段 | 获取资源门槛 |
| `power_structure` | string | 是 | 硬字段 | 权力结构概述 |
| `institution_map` | object[] | 否 | 可扩展字段 | 制度/组织结构表 |
| `rank_system` | string[] | 否 | 硬字段 | 等级体系 |
| `punishment_system` | string[] | 否 | 硬字段 | 惩罚机制 |
| `protection_system` | string[] | 否 | 可扩展字段 | 庇护机制 |
| `factions` | string[] / object[] | 否 | 可扩展字段 | 主要阵营 |
| `faction_relations` | object[] | 否 | 可扩展字段 | 阵营关系 |
| `unstable_balances` | string[] | 否 | 可扩展字段 | 不稳定平衡 |
| `long_term_conflicts` | string[] | 否 | 可扩展字段 | 长期冲突 |
| `exposure_risks` | string[] | 否 | 运行依赖字段 | 暴露风险 |
| `action_costs` | object[] | 否 | 运行依赖字段 | 行动代价表 |
| `forbidden_actions` | string[] | 否 | 硬字段 | 禁行动作 |
| `environmental_threats` | string[] | 否 | 运行依赖字段 | 环境威胁 |
| `time_pressures` | string[] | 否 | 运行依赖字段 | 时间压力源 |
| `consequence_rules` | string[] | 是 | 硬字段 | 后果规则 |
| `escalation_paths` | string[] | 否 | 可扩展字段 | 冲突升级路径 |
| `rumor_or_info_flow` | string[] | 否 | 可扩展字段 | 情报/舆论传播逻辑 |
| `recovery_limits` | string[] | 否 | 硬字段 | 恢复边界 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `world_name`

#### 类型

`string`

#### 必填

否

#### 说明

世界名称、区域名称、当前叙事空间名称。

#### 示例

- `北衡界`
- `永夜城`
- `第七殖民带`
- `王城内廷`

---

### 5.2 `world_type`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `古代仙侠`
- `架空历史`
- `近未来都市`
- `后末世`
- `高幻想`
- `太空殖民`
- `克苏鲁式现实`
- `都市异能`
- `现实主义`
- `魔法学院`

#### 说明

世界类型是世界模型的一级约束字段。

---

### 5.3 `reality_mode`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `写实`
- `架空写实`
- `魔法现实`
- `高幻想`
- `设定驱动科幻`

#### 说明

用于定义世界运作的现实性强弱和奇观容忍度。

---

### 5.4 `time_setting`

#### 类型

`string`

#### 必填

是

#### 说明

描述世界所在时代或历史阶段。

#### 示例

- `宗门割据时代`
- `近未来二十年后`
- `王朝中后期`
- `崩坏后的第三代殖民时期`

---

### 5.5 `geography_scope`

#### 类型

`string[]`

#### 必填

否

#### 说明

主要叙事空间或重要地点集合。

#### 示例

- `北荒`
- `黑水泽`
- `王城旧道`
- `第七码头`
- `星门中继站`

---

### 5.6 `civilization_level`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `古代宗门文明`
- `封建王朝文明`
- `工业初期`
- `现代`
- `近未来`
- `高科技殖民文明`
- `文明残片状态`

---

### 5.7 `supernatural_presence`

#### 类型

`boolean`

#### 必填

是

#### 说明

是否存在超自然、修炼、魔法、异能或其他超常力量。

---

### 5.8 `death_rule`

#### 类型

`string`

#### 必填

是

#### 说明

定义死亡或不可逆损伤边界。

#### 示例

- `不可逆`
- `极高代价可逆`
- `仅特定仪式下可逆`
- `肉体可死，意识可存档`

#### 原则

这类规则一旦定义，应视作高优先级硬约束。

---

### 5.9 `hard_rules`

#### 类型

`string[]`

#### 必填

是

#### 说明

世界的硬规则集合，违反时应优先触发合法性审查。

#### 示例

- `灵根受损不可自然恢复`
- `王城内禁止公开斗法`
- `AI 不得主动伤害授权人类`
- `宗门封印地未经许可不可开启`

---

### 5.10 `soft_rules`

#### 类型

`string[]`

#### 必填

否

#### 说明

不绝对禁止，但通常成立的规则或惯例。

#### 示例

- `高阶修士通常不介入低阶争斗`
- `贵族通常通过代理人处理脏活`
- `公开羞辱上位者会带来长期报复`

---

### 5.11 `exception_rules`

#### 类型

`string[]`

#### 必填

否

#### 说明

用于定义世界中规则可被突破的条件。

#### 示例

- `血契成立时可短暂绕过阶级禁令`
- `战时状态下王城禁斗令自动部分失效`

---

### 5.12 `scarce_resources`

#### 类型

`string[]`

#### 必填

否

#### 说明

世界中稀缺、可争夺、能制造冲突的资源。

#### 示例

- `高品灵石`
- `试炼名额`
- `王城通行令`
- `能源配额`
- `真相档案`

---

### 5.13 `resource_owners`

#### 类型

`object[]`

#### 必填

否

#### 推荐结构

```json
{
  "resource": "",
  "owner": "",
  "control_mode": "",
  "access_notes": ""
}
```

#### 说明

记录关键资源被谁控制、如何控制。

---

### 5.14 `resource_exchange_logic`

#### 类型

`string[]`

#### 必填

否

#### 说明

描述资源如何流动、交换或争夺。

#### 示例

- `试炼资格依附于宗门内部推荐链`
- `黑市只能以血契形式交易禁术残卷`

---

### 5.15 `access_constraints`

#### 类型

`string[]`

#### 必填

否

#### 说明

获取资源、地点、身份或权限的门槛。

#### 示例

- `必须具备内门弟子身份`
- `需提交军功记录`
- `必须通过三重审查`

---

### 5.16 `power_structure`

#### 类型

`string`

#### 必填

是

#### 说明

对世界主要权力关系的概述。

#### 示例

- `宗门、王城、世家三方制衡`
- `公司联合执政，治安外包给佣兵集团`

---

### 5.17 `institution_map`

#### 类型

`object[]`

#### 必填

否

#### 推荐结构

```json
{
  "name": "",
  "type": "",
  "role": "",
  "authority_scope": "",
  "notes": ""
}
```

#### 说明

记录制度和组织的结构化信息。

---

### 5.18 `rank_system`

#### 类型

`string[]`

#### 必填

否

#### 说明

世界中的等级体系、职级体系、修为体系或身份阶层。

#### 示例

- `外门 → 内门 → 真传`
- `见习调查员 → 正式调查员 → 巡查官`

---

### 5.19 `punishment_system`

#### 类型

`string[]`

#### 必填

否

#### 说明

描述越界、犯法、违规后通常会遭遇什么惩罚。

#### 示例

- `逐出宗门`
- `废去修为`
- `冻结权限`
- `公开审判`

---

### 5.20 `protection_system`

#### 类型

`string[]`

#### 必填

否

#### 说明

描述世界中的庇护、背书、豁免或保护机制。

#### 示例

- `真传弟子默认受长老保护`
- `军功足够可换取一次司法豁免`

---

### 5.21 `factions`

#### 类型

`string[]` 或 `object[]`

#### 必填

否

#### 说明

记录主要势力、阵营或组织。

#### 建议

若只是初版，可先用 `string[]`。  
若需要扩展，可改成对象：

```json
{
  "name": "",
  "type": "",
  "goal": "",
  "power_level": "",
  "notes": ""
}
```

---

### 5.22 `faction_relations`

#### 类型

`object[]`

#### 必填

否

#### 推荐结构

```json
{
  "from": "",
  "to": "",
  "relation": "",
  "stability": "",
  "notes": ""
}
```

#### 示例

- `敌对`
- `竞争`
- `合作`
- `表面结盟`
- `附属`
- `冷战`

---

### 5.23 `unstable_balances`

#### 类型

`string[]`

#### 必填

否

#### 说明

描述世界中暂时平衡但容易崩的结构。

#### 示例

- `王城默认不干预宗门继承，但前提是宗门不触碰禁术`
- `黑市和官方默契共存，但一旦死人过多就会清洗`

---

### 5.24 `long_term_conflicts`

#### 类型

`string[]`

#### 必填

否

#### 说明

定义世界层面的长期冲突源。

#### 示例

- `宗门与王城对封印地的归属争端`
- `殖民地与母星政府的资源分配冲突`

---

### 5.25 `exposure_risks`

#### 类型

`string[]`

#### 必填

否

#### 说明

角色或事实暴露后会引发的系统性风险来源。

#### 示例

- `身份审查`
- `搜魂`
- `权限追踪`
- `舆论清算`

---

### 5.26 `action_costs`

#### 类型

`object[]`

#### 必填

否

#### 推荐结构

```json
{
  "action": "",
  "cost": "",
  "scope": "",
  "notes": ""
}
```

#### 示例

```json
{
  "action": "短时越阶斗法",
  "cost": "经脉裂伤，三月内不可再战",
  "scope": "修行者",
  "notes": "高风险行为"
}
```

---

### 5.27 `forbidden_actions`

#### 类型

`string[]`

#### 必填

否

#### 说明

明确哪些行为属于高禁止项。

#### 示例

- `私传禁术`
- `在王城公开斗法`
- `未经授权开启封印地`

---

### 5.28 `environmental_threats`

#### 类型

`string[]`

#### 必填

否

#### 说明

地理、环境、生态、技术或空间本身带来的威胁。

#### 示例

- `黑水泽瘴气`
- `废城区监控盲区中的猎杀机器人`
- `星门跳跃不稳定区`

---

### 5.29 `time_pressures`

#### 类型

`string[]`

#### 必填

否

#### 说明

世界层面的期限、窗口、倒计时机制。

#### 示例

- `三年内必须回宗`
- `试炼令牌只在月蚀前有效`
- `母舰将在七日后关闭补给线`

---

### 5.30 `consequence_rules`

#### 类型

`string[]`

#### 必填

是

#### 说明

定义这个世界如何反馈行为，是合法性检查的核心字段。

#### 示例

- `高调越界必引来制度性反扑`
- `资源争夺会改变阵营关系`
- `秘密暴露会改变保护链和追杀链`

---

### 5.31 `escalation_paths`

#### 类型

`string[]`

#### 必填

否

#### 说明

记录冲突升级的典型路径。

#### 示例

- `个人冲突 → 宗门调查 → 阵营对抗`
- `信息泄露 → 身份怀疑 → 公开追捕`

---

### 5.32 `rumor_or_info_flow`

#### 类型

`string[]`

#### 必填

否

#### 说明

定义情报、流言、舆论、档案是如何传播和反馈的。

#### 示例

- `王城流言通常先出现在酒肆和牌楼告示`
- `监察司档案只在三级权限以上可调阅`

---

### 5.33 `recovery_limits`

#### 类型

`string[]`

#### 必填

否

#### 说明

定义哪些损失可恢复，哪些不可恢复。

#### 示例

- `身体创伤可治`
- `名誉受损可部分恢复`
- `根基损毁不可逆`
- `阵营背叛不可撤销`

---

### 5.34 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者保留备注区，写暂未结构化但重要的世界说明。

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段一旦定下，不应轻易修改：

- `world_type`
- `reality_mode`
- `time_setting`
- `civilization_level`
- `supernatural_presence`
- `death_rule`
- `hard_rules`
- `power_structure`
- `consequence_rules`
- `forbidden_actions`
- `recovery_limits`

---

### 6.2 可扩展字段

这些字段可以随着案例细化逐渐补充：

- `geography_scope`
- `soft_rules`
- `exception_rules`
- `resource_owners`
- `resource_exchange_logic`
- `institution_map`
- `factions`
- `faction_relations`
- `unstable_balances`
- `long_term_conflicts`
- `rumor_or_info_flow`
- `notes`

---

### 6.3 运行依赖字段

这些字段会被 `NarrativeState` 和 `PlotUnit` 高频调用：

- `access_constraints`
- `action_costs`
- `exposure_risks`
- `environmental_threats`
- `time_pressures`

---

### 6.4 派生字段

这些字段不建议作为主字段直接写死，可后续推导：

- 当前地区危险等级
- 当前权力压制强度
- 当前资源稀缺度排序
- 某角色越界成本等级

---

## 7. 合法性检查建议

一个合法的 `WorldModel` 至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `world_type`
- `reality_mode`
- `time_setting`
- `civilization_level`
- `supernatural_presence`
- `death_rule`
- `hard_rules`
- `power_structure`
- `consequence_rules`

### 7.2 不自相矛盾

例如：

- `death_rule = 不可逆`，但 `hard_rules` 又允许随意复活
- `civilization_level = 现代`，但所有组织结构仍按纯宗法古代逻辑运行，且无说明
- `supernatural_presence = false`，但大量规则默认存在修炼能力

### 7.3 至少具备一种冲突源

系统应能从以下至少一类中找到冲突来源：

- 资源
- 秩序
- 阵营
- 风险
- 时间压力

### 7.4 至少具备一种代价机制

若世界允许高能力或高风险行动，必须定义相应成本或后果。

---

## 8. 更新规则

### 8.1 可直接补充的字段

允许随着案例推进增补：

- `geography_scope`
- `institution_map`
- `factions`
- `faction_relations`
- `notes`

### 8.2 不建议频繁修改的字段

若改动，应记录到决策日志：

- `world_type`
- `reality_mode`
- `death_rule`
- `hard_rules`
- `power_structure`
- `consequence_rules`

### 8.3 需要版本化处理的字段

若以下字段发生重大改变，建议视为新版本 `WorldModel`：

- 世界基础规则体系改变
- 世界类型改变
- 死亡规则改变
- 权力结构逻辑改变
- 核心资源体系改变

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
{
  "world_type": "",
  "reality_mode": "",
  "time_setting": "",
  "civilization_level": "",
  "supernatural_presence": false,
  "death_rule": "",
  "hard_rules": [],
  "scarce_resources": [],
  "power_structure": "",
  "factions": [],
  "forbidden_actions": [],
  "action_costs": [],
  "consequence_rules": []
}
```

---

## 10. 示例

```json
{
  "world_name": "北衡界",
  "world_type": "古代仙侠",
  "reality_mode": "高幻想",
  "time_setting": "宗门割据时代",
  "geography_scope": ["北荒", "天衡宗", "黑水泽", "王城旧道"],
  "civilization_level": "古代宗门文明",
  "supernatural_presence": true,
  "death_rule": "极高代价可逆，但不可稳定复活",
  "hard_rules": [
    "灵根受损不可自然恢复",
    "宗门内门弟子不得私自离山三月以上",
    "公开弑师会触发宗门联查",
    "夺舍必须满足血契与神识压制双条件"
  ],
  "soft_rules": [
    "高阶修士通常不直接介入低阶争斗",
    "王城势力默认不干预宗门内部继承"
  ],
  "exception_rules": [
    "战时状态下宗门禁令可由掌门临时解除部分条款"
  ],
  "scarce_resources": [
    "高品灵石",
    "筑基丹",
    "古修遗卷",
    "进入秘境的名额"
  ],
  "resource_owners": [
    {
      "resource": "进入秘境的名额",
      "owner": "天衡宗",
      "control_mode": "宗门配给",
      "access_notes": "需通过试炼和推荐链"
    }
  ],
  "resource_exchange_logic": [
    "高阶资源主要在宗门与世家之间流动",
    "禁术残卷多通过黑市交易"
  ],
  "access_constraints": [
    "进入核心秘境需持有试炼令牌",
    "调阅王城旧档需三级权限以上"
  ],
  "power_structure": "宗门、王城、世家三方制衡",
  "institution_map": [
    {
      "name": "王城监察司",
      "type": "官方机构",
      "role": "审查与追缉",
      "authority_scope": "跨宗门调查",
      "notes": "拥有特殊档案权限"
    }
  ],
  "rank_system": [
    "外门弟子",
    "内门弟子",
    "真传弟子",
    "长老"
  ],
  "punishment_system": [
    "逐出宗门",
    "废去修为",
    "封档追缉"
  ],
  "protection_system": [
    "真传弟子默认受直系长老庇护"
  ],
  "factions": [
    "天衡宗",
    "赤霄宗",
    "王城监察司",
    "沈氏世家",
    "黑水散修盟"
  ],
  "faction_relations": [
    {
      "from": "天衡宗",
      "to": "王城监察司",
      "relation": "表面合作",
      "stability": "脆弱",
      "notes": "涉及封印地时关系恶化"
    }
  ],
  "unstable_balances": [
    "王城默认不干预宗门继承，但前提是宗门不触碰禁术"
  ],
  "long_term_conflicts": [
    "宗门对封印地归属权的争夺",
    "监察司对旧案真相的封口"
  ],
  "exposure_risks": [
    "搜魂",
    "权限追踪",
    "异常灵压监测"
  ],
  "action_costs": [
    {
      "action": "短时越阶斗法",
      "cost": "经脉裂伤，三月内不可再战",
      "scope": "修行者",
      "notes": "高风险行为"
    },
    {
      "action": "使用禁术搜魂",
      "cost": "施术者会留下可追踪痕迹",
      "scope": "掌握禁术者",
      "notes": "高暴露风险"
    }
  ],
  "forbidden_actions": [
    "在王城公开斗法",
    "私传禁术",
    "未经许可开启宗门封印地"
  ],
  "environmental_threats": [
    "黑水泽瘴气",
    "古阵残留反噬"
  ],
  "time_pressures": [
    "试炼令牌只在月蚀前有效",
    "三年内必须回宗"
  ],
  "consequence_rules": [
    "高调越界必引来制度性反扑",
    "资源争夺会改变阵营关系",
    "秘密暴露会改变保护链和追杀链"
  ],
  "escalation_paths": [
    "个人争斗升级为宗门调查",
    "秘密暴露升级为跨阵营追缉"
  ],
  "rumor_or_info_flow": [
    "王城流言通常先在酒肆和告示坊扩散",
    "监察司档案只在高权限下可调阅"
  ],
  "recovery_limits": [
    "身体创伤可治",
    "根基损毁不可逆",
    "名誉受损可部分恢复"
  ],
  "notes": "当前重点是让资源争夺、制度反扑和秘密暴露三条机制能彼此联动。"
}
```

---

## 11. 一句话总结

`WorldModel Schema` 的任务，是把世界的规则、秩序、资源、风险和后果机制压缩成一份**可约束剧情、可支持状态转移、可支撑合法性审查的结构化世界对象**。
