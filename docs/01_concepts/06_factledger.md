# FactLedger

## 文档目的
定义事实账本对象 `FactLedger`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`FactLedger` 是系统中用于记录**已确认叙事实**的结构化账本。

它的核心任务不是“总结故事”，而是：

- 记录哪些事实已经成立
- 记录这些事实何时成立
- 记录这些事实对谁可见
- 记录这些事实是否可变、是否已失效、是否仍具约束力
- 为后续生成和审查提供可检索的硬依据

可以把它理解为：

- 叙事世界的确认记录簿
- 一致性检查的基准库
- 长篇连续性的硬记忆层
- 从文本中剥离出来的“事实层”

---

## 2. 它不是什么

`FactLedger` 不是：

- 文本摘要
- 风格说明
- 推测列表
- 角色主观理解
- 情节评论
- 伏笔清单
- 审稿意见

它不负责回答：
- 这段写得好不好
- 这个角色为什么这么想
- 这个暗示意味着什么

它只负责回答：

**“哪些东西已经被确认，并足以约束后续叙事。”**

---

## 3. 它解决什么问题

`FactLedger` 的存在，是为了防止系统在长篇叙事中“把已经说过的话忘掉、改掉、混掉”。

它主要解决这几类问题：

### 3.1 防止事实冲突
没有事实账本，系统容易出现：
- 前面写死的规则后面变了
- 角色早就见过某人，后面像第一次见
- 某物品前文已毁，后文又出现
- 已知秘密被系统当作未揭露

### 3.2 防止事实与推断混淆
故事里有很多“猜测”“误解”“误导”。  
如果这些和已确认事实混在一起，系统后面会把误解当设定。

### 3.3 为审查器提供硬依据
审查器判断“事实冲突失败”时，必须基于账本，而不是基于模糊印象。

### 3.4 为长程记忆提供稳定锚点
长篇小说中，不是所有内容都要长期记住。  
真正要长期记住的是：

- 已确认的规则
- 已确认的关系
- 已发生的关键事件
- 已暴露或已封存的秘密
- 已建立的不可随意推翻的状态

---

## 4. 核心定义

### 定义
`FactLedger` 是一个由已确认叙事实组成的结构化记录系统，用于支持连续性、合法性和一致性判断。

### 一句话理解
它定义“哪些东西已经算数了”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`WorldModel` + `CharacterModel` + `PlotUnit` + `NarrativeState`
→ 共同写入 `FactLedger`

`FactLedger`
→ 约束 `NarrativeState`
→ 约束后续 `PlotUnit`
→ 支撑 `ReviewIssue`
→ 与 `ForeshadowGraph` 协同但不混同

### 具体影响

#### 受 WorldModel 影响
- 世界基础规则一旦确认，应进入账本
- 制度、禁令、边界、代价等关键信息应被可检索化

#### 受 CharacterModel 影响
- 角色身份、已确认关系、秘密暴露、关键选择应被记录

#### 受 PlotUnit 影响
- 每次有效推进后，应把新成立的事实写入账本
- 不是所有文本都写账，只有“已成立并有约束力”的内容写账

#### 对 NarrativeState 的影响
- 当前状态不能与账本冲突
- 当前信息权限应参考账本中“谁知道什么”的记录

#### 对 ReviewIssue 的影响
- 事实冲突、时间冲突、信息越界都要以账本为依据

#### 对 ForeshadowGraph 的影响
- 账本记录的是“已成立的事实”
- 伏笔图记录的是“尚未兑现的承诺”
- 两者相关，但不能混成一类对象

---

## 6. 事实账本的设计原则

### 6.1 只记录已确认内容
只有真正成立、足以约束后文的内容，才进入 `FactLedger`。

### 6.2 事实必须与推断分离
“他可能喜欢她”不应直接记成事实。  
“他在第 12 章表白”才是事实。

### 6.3 事实必须可追溯
每条事实最好都能知道：
- 来自哪里
- 何时建立
- 由什么事件确认

### 6.4 事实必须可检索
账本不是为了好看，而是为了后续查询和校验。

### 6.5 事实必须有状态
有些事实是：
- 仍然有效
- 已失效
- 已公开
- 仅部分角色知道
- 已被修正

不能把所有事实都当“永久不动”的同类条目。

---

## 7. 事实账本建议包含的层

第一版建议把 `FactLedger` 分成 7 层。

---

### 7.1 世界事实层

用于记录世界级已确认事实。

#### 典型内容
- 世界规则
- 技术/力量边界
- 禁令
- 身份制度
- 组织结构
- 死亡/复活边界
- 地理限制

#### 作用
为世界合法性检查提供硬依据。

---

### 7.2 角色事实层

用于记录角色级已确认事实。

#### 典型内容
- 真实身份
- 血缘关系
- 所属阵营
- 已确认能力
- 已确认创伤经历
- 已确认秘密
- 已暴露秘密

#### 作用
为角色一致性和信息权限检查提供依据。

---

### 7.3 关系事实层

用于记录角色之间已经成立的关系事实。

#### 典型内容
- 师徒关系已确认
- 婚约已成立
- 仇恨公开化
- 某人已知晓某人身份
- 某关系已决裂

#### 作用
防止关系线反复失忆。

---

### 7.4 事件事实层

用于记录已发生、不可被忽略的关键事件。

#### 典型内容
- 谁死了
- 谁离开了
- 谁获得了某物
- 谁暴露了秘密
- 哪场战斗谁赢了
- 哪个阵营关系改变了

#### 作用
构成长篇叙事的时间骨架。

---

### 7.5 信息权限层

用于记录“谁知道什么”。

#### 典型内容
- 读者已知信息
- 角色已知信息
- 角色未知关键信息
- 角色持有的错误信息
- 已公开/未公开事实

#### 作用
这层非常重要，因为很多叙事错误其实不是“事实错误”，而是“权限错误”。

---

### 7.6 物品与资源层

用于记录关键物品、资源、资格和权限状态。

#### 典型内容
- 某物品归属
- 某资源已消耗
- 某资格已获得/失去
- 某权限已被剥夺
- 某地通行令已作废

#### 作用
防止剧情里的物品和资格像空气一样漂浮。

---

### 7.7 状态变更层

用于记录会随情节更新的事实性结果。

#### 典型内容
- 关系已变化
- 地位已变化
- 阵营立场已变化
- 某秘密已从隐藏转为半公开
- 某规则对某角色已开始生效

#### 作用
帮助系统区分：
- 世界稳定设定
- 随故事推进而形成的新事实

---

## 8. 建议字段

### 8.1 基础标识字段

#### fact_id
事实唯一 ID。

#### fact_type
事实类型。

例如：
- world_rule
- character_identity
- relation
- event
- resource
- knowledge
- status_change

#### category
更细的分类标签。

例如：
- death_rule
- alliance_status
- item_ownership
- exposure_status

---

### 8.2 内容字段

#### statement
事实陈述。

要求：
- 尽量简洁
- 尽量单一命题
- 避免多层混合判断

#### involved_entities
涉及的实体。

例如：
- 角色
- 地点
- 组织
- 物品
- 规则对象

#### scope
事实作用范围。

例如：
- global
- faction
- local
- character_specific

---

### 8.3 来源字段

#### established_in
事实建立于哪个单元。

#### source_plotunit
来源 `PlotUnit`。

#### source_event
来源事件。

#### evidence_type
确认方式。

例如：
- direct_observation
- public_record
- confession
- system_rule
- verified_action

#### confidence
确认强度。

例如：
- confirmed
- highly_likely
- disputed

第一版建议只把 `confirmed` 写入主账本，其他可进辅助层。

---

### 8.4 时间字段

#### established_time
事实建立时间。

#### effective_from
从何时开始生效。

#### effective_until
到何时失效，如无则为空。

#### chronological_order
在全局时间线中的顺序位置。

---

### 8.5 可见性字段

#### visibility
可见性类型。

例如：
- public
- restricted
- hidden
- reader_only
- character_specific

#### known_by
哪些角色已知。

#### unknown_to
哪些角色明确未知。

#### misinformation_link
若与误解相关，记录对应错误认知对象。

---

### 8.6 状态字段

#### status
当前状态。

例如：
- active
- inactive
- superseded
- revoked
- destroyed
- revealed

#### mutable
是否允许后续变更。

#### revision_rule
若可变更，什么条件下可更新。

---

### 8.7 审查字段

#### review_priority
审查优先级。

例如：
- critical
- high
- medium
- low

#### contradiction_risk
若被忘记或写错，风险有多大。

#### notes
备注。

---

## 9. 字段分类建议

`FactLedger` 的字段建议分三类。

### 9.1 硬事实字段
一旦写入，就强约束后续叙事。

例如：
- 死亡
- 血缘关系
- 世界硬规则
- 某物品已毁
- 某组织归属已确认

### 9.2 可变事实字段
事实本身成立，但状态可能改变。

例如：
- 当前联盟关系
- 物品归属
- 某资格持有者
- 某角色当前职位

### 9.3 权限事实字段
事实成立，但仅部分角色知道。

例如：
- 某角色真实身份
- 某秘密暴露给了谁
- 某角色掌握某条关键证据

---

## 10. 事实写入原则

不是所有生成内容都应该写账本。  
建议只有满足以下条件之一的内容才写入：

### 10.1 它会约束后文
例如：
- 死亡
- 暴露
- 关系决裂
- 资格获得

### 10.2 它会影响合法性判断
例如：
- 世界规则确认
- 组织禁令
- 时间顺序

### 10.3 它会影响信息权限
例如：
- 谁知道了秘密
- 谁误会了谁
- 谁拿到了证据

### 10.4 它会影响长期连续性
例如：
- 某物品归属变化
- 某地被毁
- 某阵营立场变化

---

## 11. 事实更新原则

`FactLedger` 不只是追加，还要允许“受控更新”。

### 11.1 新增
当新事实第一次被确认时，新增条目。

### 11.2 状态变更
当事实仍成立，但状态改变时，更新状态字段。

例如：
- 某秘密从 hidden 变为 revealed
- 某关系从 active 变为 broken

### 11.3 被替代
当旧事实被新事实覆盖时，旧事实不应直接删除，而应标为 `superseded`。

### 11.4 被撤销
当某资格、权限、盟约失效时，标记为 `revoked`。

### 11.5 被销毁
当某物品、地点或组织不再存在时，标记为 `destroyed`。

---

## 12. 判定标准

一个好的 `FactLedger` 应满足以下条件。

### 12.1 能支持一致性检查
系统应能快速判断后文是否与既有事实冲突。

### 12.2 能支持信息权限检查
系统应能判断谁该知道、谁不该知道。

### 12.3 能支持长程记忆
系统应能在长篇中稳住关键事实，不靠模糊印象。

### 12.4 能支持可追溯性
每条关键事实应能追到来源。

### 12.5 不混入解释和评论
账本应尽量记录“是什么”，而不是“意味着什么”。

---

## 13. 常见错误

### 13.1 把推断当事实写入
错误例子：
- “c001 爱上了 c002”
如果文本中只是暧昧暗示，就不应直接写死。

### 13.2 一条事实太大太混
错误例子：
- “宗门很腐败而且主角被冤枉所以未来必然复仇”
这其实混了多个命题。

### 13.3 不记录可见性
错误例子：
- 只写“秘密已存在”，不写“谁知道”。

### 13.4 只追加不更新
错误例子：
- 同一个资格先后被三个人拿到，却没有状态变更链。

### 13.5 记录太碎或太泛
错误例子：
- 连“角色喝了一杯茶”都进账本  
或  
- “这一章发生了很多事”这种过于笼统的记录

---

## 14. 最小版本建议

第一版 `FactLedger` 不需要很大。  
建议先保留这些最小字段：

- fact_id
- fact_type
- statement
- involved_entities
- established_in
- chronological_order
- visibility
- known_by
- status
- review_priority

只要这些字段稳定，已经足够支撑地基阶段。

---

## 15. 示例

```json id="9zzv1v"
[
  {
    "fact_id": "f_001",
    "fact_type": "world_rule",
    "category": "death_rule",
    "statement": "灵根受损不可自然恢复。",
    "involved_entities": ["北衡界", "修行体系"],
    "scope": "global",
    "established_in": "worldmodel_init",
    "source_plotunit": null,
    "source_event": "system_rule_definition",
    "evidence_type": "system_rule",
    "confidence": "confirmed",
    "established_time": "project_init",
    "effective_from": "project_init",
    "effective_until": null,
    "chronological_order": 1,
    "visibility": "public",
    "known_by": ["all_relevant_characters", "reader"],
    "unknown_to": [],
    "misinformation_link": null,
    "status": "active",
    "mutable": false,
    "revision_rule": null,
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
    "effective_until": null,
    "chronological_order": 48,
    "visibility": "restricted",
    "known_by": ["c001", "c002", "c003"],
    "unknown_to": ["王城监察司"],
    "misinformation_link": null,
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
    "effective_until": null,
    "chronological_order": 49,
    "visibility": "character_specific",
    "known_by": ["c002"],
    "unknown_to": ["c003", "监察司"],
    "misinformation_link": null,
    "status": "active",
    "mutable": true,
    "revision_rule": "若 c002 向他人披露，则更新 visibility 与 known_by",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "关键秘密已进入半暴露状态"
  },
  {
    "fact_id": "f_016",
    "fact_type": "event",
    "category": "pursuit_trigger",
    "statement": "scene_014 的灵压波动已吸引巡查队改变路线。",
    "involved_entities": ["巡查队", "黑水泽外围", "c001"],
    "scope": "local",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "灵压波动外泄",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "scene_016_or_resolution",
    "chronological_order": 50,
    "visibility": "restricted",
    "known_by": ["reader"],
    "unknown_to": ["c001", "c002"],
    "misinformation_link": null,
    "status": "active",
    "mutable": true,
    "revision_rule": "巡查队到达或失去追踪后更新",
    "review_priority": "high",
    "contradiction_risk": "medium",
    "notes": "是下一单元紧迫度的重要来源"
  }
]
```

