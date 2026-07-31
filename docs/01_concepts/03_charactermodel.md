# CharacterModel

## 文档目的
定义角色模型对象 `CharacterModel`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`CharacterModel` 是对角色作为“叙事行动者”和“决策体”的结构化定义。

它不是为了写一份好看的人设简介，而是为了让系统回答：

- 这个角色想要什么
- 这个角色害怕什么
- 这个角色在当前状态下最可能怎么做
- 这个角色为什么会这样做
- 这个角色能做到什么、做不到什么
- 这个角色会如何改变

可以把它理解为：

- 角色决策模型
- 角色约束模型
- 角色成长轨迹模型
- 角色信息权限模型

---

## 2. 它不是什么

`CharacterModel` 不是：

- 只有外貌和性格标签的人设卡
- 纯装饰性人物介绍
- 与剧情无关的背景设定堆叠
- 一组抽象形容词
- 只能描述“这个人是什么样”的静态档案

如果一个角色定义不能帮助系统判断“他在下一步会怎么做”，那它就不是一个合格的 `CharacterModel`。

---

## 3. 它解决什么问题

`CharacterModel` 的存在，是为了防止系统出现“角色失真”和“人物沦为剧情工具”的问题。

它主要解决这几类问题：

### 3.1 防止人物前后不一致
没有角色模型，系统容易出现：
- 前面胆怯，后面突然极端勇猛
- 明明在乎某人，后面却毫无反应
- 性格和选择没有因果关系
- 人物行为只为剧情服务，不为自身逻辑服务

### 3.2 为 PlotUnit 提供行为来源
情节推进不该是“作者想让他这样做”，  
而应该是“在当前状态下，这个角色倾向这样做”。

### 3.3 为冲突提供动因
一个好的角色模型应天然产生冲突，例如：
- 目标冲突
- 价值冲突
- 资源冲突
- 信息冲突
- 依赖与背叛
- 欲望与底线冲突

### 3.4 为成长与变化提供轨迹
角色的变化不能无中生有，需要知道：
- 他原来是什么状态
- 他经历了什么压力
- 他怎么偏移
- 他是否付出了代价

---

## 4. 核心定义

### 定义
`CharacterModel` 是一个描述角色身份、目标、需求、恐惧、缺陷、能力、秘密、关系、信息边界和成长阶段的结构化对象。

### 一句话理解
它定义“这个人为什么会做出这样的选择”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`WorkSpec`
→ 约束 `CharacterModel`

`WorldModel`
→ 限制 `CharacterModel`

`CharacterModel`
→ 参与 `NarrativeState`
→ 驱动 `PlotUnit`
→ 进入 `FactLedger`
→ 参与 `ForeshadowGraph`
→ 参与 `ReviewIssue`

### 具体影响

#### 对 NarrativeState 的影响
- 当前出场角色是谁
- 当前谁知道什么
- 当前谁对谁有压力
- 当前谁在推动冲突

#### 对 PlotUnit 的影响
- 决定谁会采取行动
- 决定谁会回避冲突
- 决定谁会撒谎、隐瞒、攻击、妥协
- 决定某次转折是否合理

#### 对 FactLedger 的影响
- 角色身份、关系、秘密暴露情况、关键选择都应进入事实账本

#### 对 ForeshadowGraph 的影响
- 角色的秘密、欲望、创伤、承诺常常构成长期伏笔与回收点

#### 对 ReviewIssue 的影响
- 审查器可据此判断“角色失真失败”
- 某个决定是否缺少铺垫
- 某段关系变化是否过快

---

## 6. 角色模型的设计原则

### 6.1 决策优先于描写
优先定义能影响行为的字段，而不是外形和标签。

### 6.2 目标必须明确
角色至少要有某种“想得到”或“想避免”的东西。

### 6.3 缺陷必须可触发
缺陷不是美学标签，而应能在情节中制造问题。

### 6.4 信息边界必须存在
角色不应知道一切。知道什么，不知道什么，会直接影响行动。

### 6.5 成长必须可追踪
角色变化必须能被记录，而不是靠文风暗示。

### 6.6 关系必须能改变行为
关系字段不应只是“朋友/仇人”，而应影响选择。

---

## 7. 角色模型建议包含的层

第一版建议把 `CharacterModel` 分成 8 层。

---

### 7.1 身份层

用于定义角色在世界中的位置。

#### 典型内容
- 姓名
- 年龄
- 性别（如必要）
- 身份
- 阶层/门第/组织归属
- 职责
- 社会标签

#### 作用
解释角色为什么拥有某些权力、限制和资源。

---

### 7.2 目标层

用于定义角色想要什么。

#### 典型内容
- outer_goal：外在目标
- short_term_goal：当前短期目标
- long_term_goal：长期目标
- avoidance_goal：想避免的结果

#### 作用
解释角色为什么会行动。

#### 例子
- 想进入宗门
- 想保住家族
- 想隐藏真实身份
- 想阻止某人知道真相

---

### 7.3 需求层

用于定义角色真正缺的是什么。

#### 典型内容
- inner_need：内在需求
- emotional_need：情感需求
- moral_need：价值层缺口

#### 作用
解释角色“表面目标”与“深层变化”之间的差异。

#### 例子
- 想被认可
- 想获得归属感
- 想摆脱羞耻
- 想停止自我欺骗

---

### 7.4 缺陷层

用于定义角色会如何自己制造问题。

#### 典型内容
- flaw：核心缺陷
- fear：核心恐惧
- blind_spot：认知盲区
- weakness：能力短板
- trigger_points：触发点
- bottom_line：底线

#### 作用
让角色不是“完美推进器”，而是会被自己的局限卡住。

#### 例子
- 害怕被抛弃
- 关键时刻逃避决断
- 过度自尊
- 对权威天然顺从
- 一旦涉及家人就失去理智

---

### 7.5 能力层

用于定义角色能做什么、不能做什么。

#### 典型内容
- strengths：优势
- skills：技能
- resources：个人资源
- permissions：权限
- constraints：个人限制

#### 作用
决定角色用什么方式解决问题。

#### 核心问题
- 他是否有资格这么做
- 他是否有能力做到
- 他是否要为此付代价

---

### 7.6 秘密层

用于定义角色有哪些未公开信息。

#### 典型内容
- secret：核心秘密
- hidden_past：隐藏过去
- concealed_relation：隐藏关系
- exposure_risk：暴露风险
- reveal_condition：暴露条件

#### 作用
提供悬念、反转、冲突升级点。

---

### 7.7 关系层

用于定义角色与他人的连接方式。

#### 典型内容
- relation_type：关系类型
- trust_level：信任度
- dependency_level：依赖度
- conflict_level：冲突度
- obligation：责任/亏欠
- desire_direction：情感倾向
- threat_perception：威胁感知

#### 作用
关系不是静态标签，而是影响行为的力量场。

#### 核心问题
- 他更在乎谁
- 他愿意为了谁破例
- 他害怕被谁发现
- 他会向谁撒谎

---

### 7.8 成长层

用于定义角色的变化轨迹。

#### 典型内容
- arc_type：成长类型
- arc_start：起点状态
- arc_target：目标状态
- arc_stage：当前阶段
- transformation_cost：变化代价
- unresolved_internal_conflict：未解决内部冲突

#### 作用
让角色不是“从头到尾一个样”，也不是“突然顿悟”。

---

## 8. 建议字段

### 8.1 基础标识字段

#### character_id
角色唯一 ID。

#### name
角色名称。

#### role
角色在作品中的作用。

例如：
- protagonist
- deuteragonist
- antagonist
- mentor
- foil
- ally
- rival
- witness

#### narrative_importance
叙事重要度。

例如：
- core
- major
- support
- minor

---

### 8.2 身份字段

#### identity
身份说明。

#### affiliation
所属组织/阵营。

#### social_position
社会位置。

#### public_label
公开标签。

#### private_truth
真实身份或隐藏事实。

---

### 8.3 目标字段

#### outer_goal
外在目标。

#### short_term_goal
短期目标。

#### long_term_goal
长期目标。

#### avoidance_goal
想避免的结果。

#### priority_order
目标优先级。

---

### 8.4 需求与心理字段

#### inner_need
内在需求。

#### fear
核心恐惧。

#### flaw
核心缺陷。

#### blind_spot
认知盲区。

#### self_image
自我认知。

#### emotional_pattern
常见情绪模式。

---

### 8.5 能力字段

#### strengths
优势列表。

#### skills
技能列表。

#### available_resources
可调用资源。

#### permissions
社会/制度/身份权限。

#### limitations
能力或环境限制。

---

### 8.6 秘密字段

#### secrets
秘密列表。

#### hidden_history
隐藏经历。

#### exposure_risks
暴露风险列表。

#### reveal_triggers
触发暴露的条件。

---

### 8.7 关系字段

#### relations
与他人的关系集合。

建议每条关系至少包含：
- target_id
- relation_type
- trust_level
- dependency_level
- conflict_level
- obligation_level
- emotional_weight
- current_status

---

### 8.8 信息字段

#### knowledge_state
角色当前知道的信息。

#### misinformation
角色当前持有的错误信息。

#### unknown_critical_info
角色尚未知但关键的信息。

#### perspective_limit
视角限制说明。

---

### 8.9 成长字段

#### arc_type
成长类型。

例如：
- 成熟
- 堕落
- 觉醒
- 自毁
- 认知修正
- 信念崩塌
- 关系修复

#### arc_start
起点状态。

#### arc_target
目标状态。

#### arc_stage
当前阶段。

#### transformation_cost
成长代价。

---

## 9. 字段分类建议

`CharacterModel` 的字段建议分三类。

### 9.1 硬字段
相对稳定、不可随便改动。

例如：
- name
- role
- identity
- affiliation
- 核心秘密的存在
- 初始缺陷
- 初始恐惧

### 9.2 可成长字段
会随着叙事推进发生变化。

例如：
- short_term_goal
- trust_level
- conflict_level
- arc_stage
- self_image
- emotional_pattern 的表现强度

### 9.3 运行依赖字段
在 NarrativeState 中频繁调用的即时信息。

例如：
- 当前目标
- 当前知道的信息
- 当前最在乎的人
- 当前威胁判断
- 当前冲突倾向

---

## 10. 判定标准

一个好的 `CharacterModel` 应满足以下条件。

### 10.1 能解释行为
系统能据此判断角色为什么会做某个决定。

### 10.2 能制造冲突
角色的目标、恐惧、关系和缺陷应能自然制造矛盾。

### 10.3 能支持变化
角色不只是静态标签，而是能追踪成长和偏移。

### 10.4 能参与审查
审查器能据此判断：
- 是否角色失真
- 是否关系突变
- 是否成长无铺垫
- 是否行为越过底线却没代价

### 10.5 不依赖空泛形容词
“高冷”“温柔”“聪明”这类词可以存在，但不能替代行为依据。

---

## 11. 常见错误

### 11.1 只有性格词，没有行为逻辑
错误例子：
- “她很坚强，很聪明，很善良”
但系统仍不知道她遇事会怎么做。

### 11.2 目标不明确
错误例子：
- 角色“想变强”，但不知道为什么、怎么变、为了什么变。

### 11.3 缺陷不产生后果
错误例子：
- 写“他太骄傲”，但骄傲从不影响任何选择。

### 11.4 秘密只是设定亮点，不参与剧情
错误例子：
- 角色有惊人身世，但从头到尾不影响冲突。

### 11.5 关系只是标签
错误例子：
- 写“师徒”“恋人”“宿敌”，但这些关系不影响决策和代价。

### 11.6 成长是跳变
错误例子：
- 前文毫无铺垫，角色突然彻底成熟或黑化。

---

## 12. 最小版本建议

第一版 `CharacterModel` 不需要过大。  
建议先保留这些最小字段：

- character_id
- name
- role
- identity
- affiliation
- outer_goal
- inner_need
- fear
- flaw
- strengths
- limitations
- secrets
- relations
- knowledge_state
- arc_stage

只要这些字段稳定，已经足够支撑地基阶段。

---

## 13. 示例

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
  "arc_type": "认知修正 + 成长",
  "arc_start": "自我否定、孤立求生",
  "arc_target": "能主动建立信任并承担选择后果",
  "arc_stage": "未觉醒",
  "transformation_cost": "必须承认自己对他人的依赖，并冒暴露秘密的风险"
}
```

