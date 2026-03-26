# ReviewIssue

## 文档目的
定义审查问题对象 `ReviewIssue`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`ReviewIssue` 是系统在审查过程中识别出的**可定位、可分类、可处理的问题对象**。

它的任务不是笼统地说“这里不太好”，而是明确指出：

- 哪里有问题
- 问题属于哪一类
- 严重程度如何
- 影响了哪些对象
- 违反了哪条规则
- 应该优先怎么处理

可以把它理解为：

- 叙事错误记录单
- 审查结果对象
- 修正任务入口
- 生成闭环的反馈节点

---

## 2. 它不是什么

`ReviewIssue` 不是：

- 抽象的读后感
- 纯审美评价
- “我觉得不行”式评论
- 不可定位的模糊反馈
- 单纯的文本润色建议

它不负责回答：
- 这段文风够不够美
- 这段是不是更有文学性
- 作者个人喜不喜欢这种写法

它只负责回答：

**“这个系统性问题是什么，它在哪里，它为什么成立，它该怎么修。”**

---

## 3. 它解决什么问题

`ReviewIssue` 的存在，是为了防止系统“能生成，但不知道自己坏在哪”。

它主要解决这几类问题：

### 3.1 防止审查结果空泛
没有问题对象，系统容易只给出：
- 节奏有点问题
- 人设有点飘
- 好像哪里不对

这种反馈无法用于修正。

### 3.2 为修正器提供明确入口
修正器需要知道：
- 修什么
- 修哪一层
- 优先修哪个
- 修完后看什么是否改善

### 3.3 为实验迭代积累失败类型
单次失败不可怕，最怕失败后没有记录、不能复盘、不能归类。

### 3.4 为“审查优先于优化”提供结构支撑
先知道哪里错，再谈如何更强。
`ReviewIssue` 就是“哪里错了”的正式对象。

---

## 4. 核心定义

### 定义
`ReviewIssue` 是一个描述叙事问题的结构化对象，包含问题类型、严重程度、发生位置、受影响范围、违反规则、修复建议和处理状态。

### 一句话理解
它定义“系统哪里坏了，以及该怎么动手修”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`ReviewIssue`
← 由 `PlotUnit`、`NarrativeState`、`FactLedger`、`ForeshadowGraph`、`CharacterModel`、`WorldModel` 审查得到

`ReviewIssue`
→ 影响修正器
→ 影响后续 `PlotUnit`
→ 影响实验记录
→ 影响决策日志

### 具体影响

#### 来自 PlotUnit
- 推进不足
- 冗余
- 冲突无代价
- 回收突兀
- 章尾钩子失效

#### 来自 NarrativeState
- 当前局势断裂
- 后果未延续
- 冲突重点错置
- 信息权限失控

#### 来自 FactLedger
- 事实冲突
- 时间顺序冲突
- 物品/资格状态冲突
- 已知与未知混乱

#### 来自 ForeshadowGraph
- 承诺遗失
- 推进停滞
- 假线索污染主线
- 回收级别不匹配

#### 来自 CharacterModel
- 行为无依据
- 关系突变
- 成长跳变
- 恐惧/缺陷失效

#### 来自 WorldModel
- 世界规则越界
- 代价消失
- 制度反应缺席
- 资源逻辑破裂

---

## 6. 设计原则

### 6.1 可定位
每个问题都应尽量定位到：
- 哪个层级
- 哪个 PlotUnit
- 哪个对象
- 哪段文本或哪条规则

### 6.2 可分类
问题必须能归入稳定类别，否则后续无法积累与分析。

### 6.3 可处理
问题对象应至少给出一种处理方向，而不是只指出失败。

### 6.4 可排序
多个问题同时存在时，系统应知道先修哪个。

### 6.5 可关闭
问题不是永远挂着。修完后应能标记状态，形成闭环。

---

## 7. 建议包含的层

第一版建议把 `ReviewIssue` 分成 7 层。

---

### 7.1 类型层

用于定义问题属于哪一类。

#### 典型类型
- fact_conflict
- character_distortion
- world_violation
- timeline_error
- weak_progression
- promise_loss
- abrupt_payoff
- redundancy
- information_leak
- style_drift

#### 作用
让问题进入可统计、可复盘的分类系统。

---

### 7.2 定位层

用于定义问题发生在哪里。

#### 典型内容
- object_type
- object_id
- level
- chapter_ref
- scene_ref
- plotunit_ref

#### 作用
让修正器知道从哪一层下手。

---

### 7.3 证据层

用于定义为什么判定这里有问题。

#### 典型内容
- violated_rule
- supporting_facts
- contradictory_facts
- missing_transition
- missing_payoff
- evidence_excerpt

#### 作用
防止问题判定变成无依据的主观猜测。

---

### 7.4 影响层

用于定义问题会造成什么后果。

#### 典型内容
- impact_scope
- affected_characters
- affected_threads
- affected_states
- downstream_risk

#### 作用
有些问题只是局部瑕疵，有些会污染整条主线。

---

### 7.5 处理层

用于定义问题怎么修。

#### 典型内容
- suggested_fix_type
- suggested_fix_note
- rewrite_needed
- replanning_needed
- memory_update_needed

#### 作用
把“发现问题”转换成“可执行修复”。

---

### 7.6 优先级层

用于定义先修什么。

#### 典型内容
- severity
- urgency
- blocking_status
- fix_order

#### 作用
避免系统把轻微风格问题排在核心事实冲突前面。

---

### 7.7 生命周期层

用于定义这个问题当前处理到了哪一步。

#### 典型内容
- status
- created_at
- last_updated
- resolved_by
- resolution_note

#### 状态示例
- open
- acknowledged
- in_progress
- mitigated
- resolved
- dismissed

#### 作用
形成修复闭环。

---

## 8. 建议字段

### 8.1 基础标识字段

#### issue_id
问题唯一 ID。

#### issue_type
问题类型。

#### title
问题短标题。

#### summary
一句话问题摘要。

---

### 8.2 定位字段

#### object_type
问题主要指向的对象类型。

例如：
- PlotUnit
- NarrativeState
- FactLedger
- ForeshadowGraph
- CharacterModel
- WorldModel

#### object_id
对象 ID。

#### level
问题所在层级。

例如：
- book
- arc
- chapter
- scene

#### plotunit_ref
相关 PlotUnit。

#### chapter_ref
相关章节。

#### scene_ref
相关场景。

---

### 8.3 证据字段

#### violated_rule
违反的规则。

#### supporting_facts
支持判定的问题依据。

#### contradictory_facts
与之冲突的事实。

#### missing_elements
缺失的关键元素。

例如：
- missing_transition
- missing_cost
- missing_payoff
- missing_motivation

#### evidence_note
证据说明。

---

### 8.4 影响字段

#### impact_scope
影响范围。

例如：
- local
- arc
- bookwide

#### affected_characters
受影响角色。

#### affected_threads
受影响的承诺线程或伏笔线程。

#### affected_states
受影响状态。

#### downstream_risk
若不修复，后续风险是什么。

---

### 8.5 处理字段

#### suggested_fix_type
建议修复方式。

例如：
- local_rewrite
- state_update
- fact_correction
- foreshadow_advancement
- character_motivation_patch
- arc_replanning

#### suggested_fix_note
修复建议说明。

#### rewrite_needed
是否需要重写正文。

#### replanning_needed
是否需要调整规划。

#### memory_update_needed
是否需要更新账本/图谱/状态。

---

### 8.6 优先级字段

#### severity
严重程度。

例如：
- low
- medium
- high
- critical

#### urgency
修复紧迫度。

例如：
- backlog
- soon
- immediate

#### blocking_status
是否阻断后续生成。

例如：
- non_blocking
- warning
- blocking

#### fix_order
建议修复顺序。

---

### 8.7 生命周期字段

#### status
处理状态。

#### created_at
创建时间。

#### last_updated
最后更新时间。

#### resolved_by
由哪个修正动作关闭。

#### resolution_note
修复说明。

---

## 9. 字段分类建议

`ReviewIssue` 的字段建议分三类。

### 9.1 判定字段
用于证明“这里确实有问题”。

例如：
- issue_type
- violated_rule
- supporting_facts
- contradictory_facts

### 9.2 调度字段
用于决定“先修哪个、怎么修”。

例如：
- severity
- urgency
- blocking_status
- suggested_fix_type
- fix_order

### 9.3 生命周期字段
用于决定“修到哪了”。

例如：
- status
- created_at
- last_updated
- resolved_by

---

## 10. 写入原则

不是所有小瑕疵都要生成正式 `ReviewIssue`。  
建议满足以下条件之一时再正式建单：

### 10.1 会破坏一致性
例如：
- 事实冲突
- 时间错误
- 世界规则越界

### 10.2 会破坏推进
例如：
- 单元无状态变化
- 大段冗余
- 回收突兀

### 10.3 会破坏角色逻辑
例如：
- 行为无动机
- 关系跳变
- 成长断裂

### 10.4 会破坏长程承诺
例如：
- 核心伏笔长期无推进
- 关键承诺被遗忘
- 假线索污染真线

### 10.5 会阻断后续生成
例如：
- 当前状态定义错误，导致下一场根本无法稳定生成

---

## 11. 问题优先级原则

建议按以下顺序处理问题：

### 第一优先
事实与规则问题
- fact_conflict
- world_violation
- timeline_error

### 第二优先
角色与推进问题
- character_distortion
- weak_progression
- missing_cost

### 第三优先
承诺与结构问题
- promise_loss
- abrupt_payoff
- duplication_of_threads

### 第四优先
表达与风格问题
- style_drift
- tonal_mismatch
- surface_redundancy

### 原则
先修“会让系统整体失真”的问题，再修“让文本不够好看”的问题。

---

## 12. 判定标准

一个好的 `ReviewIssue` 应满足以下条件。

### 12.1 说得清楚
看完后应能明确知道问题是什么。

### 12.2 找得到位置
应能定位到对象、层级和场景。

### 12.3 立得住依据
不是直觉，而是能引用规则、事实或状态差异。

### 12.4 指得出处理方向
至少能说出应该补什么、改什么、删什么。

### 12.5 能形成闭环
修完后能被标记为已处理，而不是反复悬挂。

---

## 13. 常见错误

### 13.1 只有评价，没有问题对象
错误例子：
- “这里不太自然”
但没有说哪里不自然、违反了什么。

### 13.2 一个问题塞太多内容
错误例子：
- 把事实冲突、角色失真、节奏塌陷写成一个 issue。

### 13.3 没有证据
错误例子：
- “主角这里不符合人设”
但没有引用角色模型或前置状态。

### 13.4 没有修复方向
错误例子：
- 只指出“伏笔回收不好”，但不说是要补铺垫、延后回收还是改回收方式。

### 13.5 不区分严重程度
错误例子：
- 把小的语言重复和核心时间线冲突放同一优先级。

---

## 14. 最小版本建议

第一版 `ReviewIssue` 不需要很大。  
建议先保留这些最小字段：

- issue_id
- issue_type
- summary
- object_type
- object_id
- violated_rule
- supporting_facts
- impact_scope
- suggested_fix_type
- severity
- status

只要这些字段稳定，已经足够支撑地基阶段。

---

## 15. 示例

```json id="7ph10u"
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
      "c001 的 fear 是再次失去保护者",
      "c001 对 c003 的 conflict_level 长期偏高",
      "scene_014 后 c001 对外部试探显著提高警惕"
    ],
    "contradictory_facts": [
      "scene_018 中未提供新的信任证据"
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
    "resolved_by": null,
    "resolution_note": null
  },
  {
    "issue_id": "ri_002",
    "issue_type": "promise_loss",
    "title": "核心身世线程推进停滞过久",
    "summary": "fg_001 在最近两个 arc 中缺乏有效推进，存在承诺遗失风险。",
    "object_type": "ForeshadowGraph",
    "object_id": "fg_001",
    "level": "arc",
    "plotunit_ref": null,
    "chapter_ref": null,
    "scene_ref": null,
    "violated_rule": "核心叙事承诺应在合理跨度内得到推进、收紧或转义，不能长期无动作。",
    "supporting_facts": [
      "fg_001 的 narrative_importance 为 core",
      "最近两个 arc 仅重复旧问题，没有新增 narrowing_events 或 advancement_nodes"
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
    "resolved_by": null,
    "resolution_note": null
  }
]
```

