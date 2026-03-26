# WorkSpec Schema

## 文档目的
将 `01_concepts/01_workspec.md` 中的概念定义，压缩为可操作的数据结构说明。

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

`WorkSpec`

---

## 2. Schema 目标

`WorkSpec` 用于定义作品级约束，而不是剧情内容。

它应该回答：

- 这是什么类型的作品
- 面向谁
- 核心主题是什么
- 节奏和结构偏向是什么
- 哪些内容必须避免
- 哪些叙事成分应被优先强化

---

## 3. 顶层结构

```json
{
  "title": "",
  "premise": "",
  "project_mode": "",
  "genre": "",
  "subgenre": [],
  "audience": "",
  "theme": [],
  "tone_family": "",
  "narrative_priority": [],
  "pacing": "",
  "hook_density": "",
  "structure_preference": [],
  "narration_mode": "",
  "prose_density": "",
  "dialogue_ratio": "",
  "romance_weight": 0.0,
  "mystery_weight": 0.0,
  "action_weight": 0.0,
  "politics_weight": 0.0,
  "introspection_weight": 0.0,
  "hard_constraints": [],
  "soft_constraints": [],
  "taboo_items": [],
  "notes": ""
}
```

---

## 4. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `title` | string | 是 | 硬字段 | 作品名或项目名 |
| `premise` | string | 是 | 硬字段 | 一句话设定/核心卖点 |
| `project_mode` | enum string | 是 | 硬字段 | 项目模式 |
| `genre` | enum string | 是 | 硬字段 | 主类型 |
| `subgenre` | string[] | 否 | 硬字段 | 子类型列表 |
| `audience` | enum string | 是 | 硬字段 | 目标读者 |
| `theme` | string[] | 是 | 硬字段 | 主题列表 |
| `tone_family` | enum string | 否 | 可调整字段 | 调性家族 |
| `narrative_priority` | string[] | 否 | 可调整字段 | 叙事优先级排序 |
| `pacing` | enum string | 是 | 可调整字段 | 节奏倾向 |
| `hook_density` | enum string | 否 | 可调整字段 | 钩子密度要求 |
| `structure_preference` | string[] | 否 | 可调整字段 | 结构偏好 |
| `narration_mode` | enum string | 是 | 硬字段 | 叙述方式 |
| `prose_density` | enum string | 否 | 可调整字段 | 语言密度 |
| `dialogue_ratio` | enum string | 否 | 可调整字段 | 对话占比倾向 |
| `romance_weight` | float | 否 | 可调整字段 | 感情线权重 |
| `mystery_weight` | float | 否 | 可调整字段 | 悬疑权重 |
| `action_weight` | float | 否 | 可调整字段 | 动作权重 |
| `politics_weight` | float | 否 | 可调整字段 | 权谋/制度权重 |
| `introspection_weight` | float | 否 | 可调整字段 | 内省权重 |
| `hard_constraints` | string[] | 否 | 硬字段 | 不可轻易违反的约束 |
| `soft_constraints` | string[] | 否 | 可调整字段 | 尽量遵循的约束 |
| `taboo_items` | string[] | 否 | 硬字段 | 禁用项 |
| `notes` | string | 否 | 备注字段 | 作者补充说明 |

---

## 5. 字段详细说明

### 5.1 `title`

#### 类型

`string`

#### 必填

是

#### 说明

作品名、工作名或项目代号。

#### 约束建议

- 长度建议：1 到 60 字符
- 可暂用占位名
- 后续允许修改，不影响系统结构

---

### 5.2 `premise`

#### 类型

`string`

#### 必填

是

#### 说明

一句话描述作品的核心设定或核心卖点。

#### 作用

它通常用于：

- 帮助后续规划器锁定作品方向
- 帮助审查器判断文本是否偏离核心 premise

#### 约束建议

- 长度建议：20 到 120 字符
- 应尽量包含：主角 / 困境 / 目标 / 风险 中的至少两项
- 不建议写成空泛宣传语

---

### 5.3 `project_mode`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `original`
- `rebuild`
- `continuation`
- `rewrite`

#### 说明

定义项目属于原创、重建、续写还是改写。

---

### 5.4 `genre`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `玄幻`
- `仙侠`
- `悬疑`
- `科幻`
- `言情`
- `历史`
- `都市`
- `都市异能`
- `奇幻`
- `现实`
- `恐怖`
- `冒险`
- `群像`

#### 说明

主类型应尽量保持单一；复杂作品可借助 `subgenre` 补充。

---

### 5.5 `subgenre`

#### 类型

`string[]`

#### 必填

否

#### 示例

- `宗门成长`
- `学院`
- `复仇`
- `无限流`
- `朝堂权谋`
- `身世之谜`
- `女性成长`

#### 约束建议

- 建议 1 到 5 项
- 过多会削弱系统约束力

---

### 5.6 `audience`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `女频`
- `男频`
- `出版向`
- `青少年`
- `类型文学读者`
- `网文读者`

#### 说明

影响：

- 钩子密度
- 角色配置
- 节奏
- 信息释放方式

---

### 5.7 `theme`

#### 类型

`string[]`

#### 必填

是

#### 示例

- `成长`
- `命运`
- `代价`
- `孤独`
- `身份认同`
- `权力腐蚀`
- `信任`

#### 约束建议

- 建议 1 到 4 项
- 超过 5 项通常说明主题失焦

---

### 5.8 `tone_family`

#### 类型

`enum string`

#### 必填

否

#### 推荐取值

- `冷峻`
- `轻快`
- `热血`
- `压抑`
- `治愈`
- `克制`
- `荒诞`
- `悲壮`
- `悬冷`

#### 说明

用于全局表达偏置，不直接替代 `Style Memory`。

---

### 5.9 `narrative_priority`

#### 类型

`string[]`

#### 必填

否

#### 示例

```json
["角色成长", "悬念推进", "感情线", "世界展开"]
```

#### 说明

表示作品级叙事排序。

#### 约束建议

- 建议按优先级排序
- 最多 5 项

---

### 5.10 `pacing`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `前快中稳后爆`
- `持续高压`
- `低速铺陈`
- `分段爆发`
- `日常穿插主线`
- `慢热递增`

#### 说明

它不是章节长度，而是全局推进倾向。

---

### 5.11 `hook_density`

#### 类型

`enum string`

#### 必填

否

#### 推荐取值

- `每章强钩子`
- `每2-3章一个中型转折`
- `每卷一个大型反转`
- `低频钩子高强回收`

#### 说明

影响章节规划与审查标准。

---

### 5.12 `structure_preference`

#### 类型

`string[]`

#### 必填

否

#### 示例

- `单主线`
- `多线并行`
- `群像交错`
- `任务驱动`
- `谜题递进`
- `分卷成长`

---

### 5.13 `narration_mode`

#### 类型

`enum string`

#### 必填

是

#### 推荐取值

- `第一人称`
- `限制第三人称`
- `多视角第三人称`
- `全知视角`

#### 说明

属于高约束字段，不建议在中后期频繁变动。

---

### 5.14 `prose_density`

#### 类型

`enum string`

#### 必填

否

#### 推荐取值

- `简洁`
- `中等`
- `浓密`

#### 说明

用于控制表达密度，不直接等于文风优劣。

---

### 5.15 `dialogue_ratio`

#### 类型

`enum string`

#### 必填

否

#### 推荐取值

- `低`
- `中`
- `高`

#### 说明

影响文本中对话与叙述的相对占比。

---

### 5.16 权重字段

#### 字段列表

- `romance_weight`
- `mystery_weight`
- `action_weight`
- `politics_weight`
- `introspection_weight`

#### 类型

`float`

#### 必填

否

#### 建议范围

`0.0` 到 `1.0`

#### 说明

这些字段是**相对偏置**，不是严格数学总和。

#### 建议规则

- 每个字段范围在 0 到 1
- 建议至少有 1 项 `>= 0.4`
- 不要求总和等于 1
- 若五项都低于 0.2，通常说明方向不清

---

### 5.17 `hard_constraints`

#### 类型

`string[]`

#### 必填

否

#### 示例

- `不允许无代价复活`
- `主视角信息必须受限`
- `不允许现代网络语言`
- `结局必须闭环`

#### 说明

高优先级约束，违反时应优先触发审查。

---

### 5.18 `soft_constraints`

#### 类型

`string[]`

#### 必填

否

#### 示例

- `尽量避免大段设定说明`
- `尽量通过行动暴露人物`
- `尽量减少纯解释性对白`

#### 说明

可被权衡，但应作为优化方向。

---

### 5.19 `taboo_items`

#### 类型

`string[]`

#### 必填

否

#### 示例

- `过度恶搞`
- `强行洗白核心反派`
- `纯靠巧合破局`
- `突发穿越设定`

#### 说明

与 `hard_constraints` 相似，但更偏“禁用内容/手法”。

---

### 5.20 `notes`

#### 类型

`string`

#### 必填

否

#### 说明

作者保留备注区，用于写：

- 当前阶段特别关注点
- 暂时未结构化的信息
- 后续待决策项

---

## 6. 字段分类汇总

### 6.1 硬字段

这些字段一旦定下，不应轻易变化：

- `title`
- `premise`
- `project_mode`
- `genre`
- `audience`
- `theme`
- `narration_mode`
- `hard_constraints`
- `taboo_items`

---

### 6.2 可调整字段

这些字段可以在前期迭代中微调：

- `tone_family`
- `narrative_priority`
- `pacing`
- `hook_density`
- `structure_preference`
- `prose_density`
- `dialogue_ratio`
- 各类 `*_weight`
- `soft_constraints`

---

### 6.3 派生字段

这些字段不建议直接存为主字段，可在后续规则层推导：

- 推荐章节长度
- 推荐钩子频率
- 推荐角色密度
- 推荐信息释放速度
- 推荐关系线占比

---

## 7. 合法性检查建议

一个合法的 `WorkSpec` 至少应满足：

### 7.1 必填字段完整

以下字段不能为空：

- `title`
- `premise`
- `project_mode`
- `genre`
- `audience`
- `theme`
- `pacing`
- `narration_mode`

### 7.2 不自相矛盾

例如：

- `低速铺陈` 与 `每章强钩子` 并存时，需要备注解释
- `限制第三人称` 与“任意角色内心全开放”不能共存
- `克制` 与“持续极端高密情绪宣泄”不能无说明并存

### 7.3 权重不全空

至少一个权重字段应明显高于其他字段。

### 7.4 premise 不得过空

不应只写：

- `一个波澜壮阔的故事`
- `关于成长与命运的传奇`

这类文本无法约束系统。

---

## 8. 更新规则

### 8.1 可直接修改的字段

允许在前期迭代中人工调整：

- `tone_family`
- `pacing`
- `hook_density`
- `structure_preference`
- 权重字段
- `soft_constraints`
- `notes`

### 8.2 不建议频繁改动的字段

若改动，应记录到决策日志：

- `genre`
- `audience`
- `theme`
- `narration_mode`
- `project_mode`

### 8.3 需要版本化处理的字段

若发生重大变化，建议视为新版本 `WorkSpec`：

- 核心 premise 完全改变
- 主类型改变
- 目标读者改变
- 全局叙事模式改变

---

## 9. 最小可用版本（MVP）

第一版建议最少保留以下字段：

```json
{
  "title": "",
  "premise": "",
  "project_mode": "",
  "genre": "",
  "subgenre": [],
  "audience": "",
  "theme": [],
  "pacing": "",
  "narration_mode": "",
  "romance_weight": 0.0,
  "mystery_weight": 0.0,
  "action_weight": 0.0,
  "hard_constraints": []
}
```

---

## 10. 示例

```json
{
  "title": "残雪归宗",
  "premise": "被逐出宗门的少女必须在三年内重返仙门，否则体内残魂将彻底吞噬她。",
  "project_mode": "original",
  "genre": "仙侠",
  "subgenre": ["宗门成长", "身世之谜", "女性成长"],
  "audience": "女频",
  "theme": ["成长", "代价", "命运"],
  "tone_family": "克制",
  "narrative_priority": ["角色成长", "悬念推进", "关系变化", "世界展开"],
  "pacing": "前快中稳后爆",
  "hook_density": "每2-3章一个中型转折",
  "structure_preference": ["单主线", "分卷成长", "谜题递进"],
  "narration_mode": "限制第三人称",
  "prose_density": "中等",
  "dialogue_ratio": "中",
  "romance_weight": 0.25,
  "mystery_weight": 0.45,
  "action_weight": 0.30,
  "politics_weight": 0.15,
  "introspection_weight": 0.40,
  "hard_constraints": [
    "不允许无代价复活",
    "主视角信息必须受限",
    "结局必须闭环"
  ],
  "soft_constraints": [
    "尽量减少纯解释性对白",
    "尽量通过行动暴露人物"
  ],
  "taboo_items": [
    "突发穿越设定",
    "强行洗白核心反派"
  ],
  "notes": "当前阶段优先验证：悬念推进和角色成长能否稳定共存。"
}
```

---

## 11. 一句话总结

`WorkSpec Schema` 的任务，是把作品级方向、偏置和约束压缩成一份**可引用、可校验、可调整、可复用的顶层规格对象**，为后续所有叙事对象提供统一边界。
