# PlotUnit

## 文档目的
定义情节单元对象 `PlotUnit`，明确它在自动小说系统中的作用、边界、核心字段和判断方式。

---

## 1. 它是什么

`PlotUnit` 是一次**有效叙事推进**的结构化单元。

它的本质不是“发生了一件事”，而是：

- 某个状态作为输入
- 角色在约束与压力下做出行动或决策
- 事件发生
- 状态被改变
- 新的信息、关系、后果或承诺被写入系统

可以把它理解为：

- 状态转移单元
- 推进单元
- 冲突处理单元
- 叙事最小工作单元

---

## 2. 它不是什么

`PlotUnit` 不是：

- 单纯的事件记录
- 纯文本段落
- 只有场面、没有变化的桥段
- 不影响后续的热闹片段
- 只是“这一章讲了什么”的摘要

如果一个内容没有造成可记录的状态变化，它就不应被视为强 `PlotUnit`。

---

## 3. 它解决什么问题

`PlotUnit` 的存在，是为了防止系统把小说理解成松散的事件堆叠。

它主要解决这几类问题：

### 3.1 让推进可判定
没有 `PlotUnit`，系统只能模糊地说“写了一段剧情”，但无法判断：
- 这段是否有效
- 这段推进了什么
- 这段是否只是重复
- 这段是否可删

### 3.2 让状态转移可追踪
系统需要知道：
- 从什么状态开始
- 谁做了决定
- 遇到了什么阻力
- 最终什么变了

### 3.3 让审查有依据
审查器需要基于 `PlotUnit` 判断：
- 推进是否成立
- 角色行为是否合理
- 信息释放是否越界
- 伏笔是否被正确推进或回收

### 3.4 让不同叙事层级可统一
全书、篇章、章节、场景虽然粒度不同，但都可以被统一看作不同层级的 `PlotUnit`。

---

## 4. 核心定义

### 定义
`PlotUnit` 是一个描述叙事如何在给定输入状态下，通过角色行动、冲突作用和世界约束，生成事件并导出输出状态的结构化对象。

### 一句话理解
它定义“这一次推进到底改变了什么”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`NarrativeState`
→ 作为 `PlotUnit` 的输入

`CharacterModel`
→ 驱动 `PlotUnit` 中的行动与决策

`WorldModel`
→ 约束 `PlotUnit` 的合法性与代价

`PlotUnit`
→ 更新 `NarrativeState`
→ 写入 `FactLedger`
→ 推动 `ForeshadowGraph`
→ 触发 `ReviewIssue`

### 具体影响

#### 对 NarrativeState 的关系
- 读取输入状态
- 输出更新后的状态
- 定义当前局势如何变化

#### 对 CharacterModel 的关系
- 谁主导行动
- 谁抵抗
- 谁让步
- 谁撒谎、暴露、崩溃、成长

#### 对 WorldModel 的关系
- 行动是否被允许
- 冲突是否有制度/资源/代价基础
- 事件后果如何反馈

#### 对 FactLedger 的关系
- 新增事实要记账
- 已确认关系变化要记账
- 已发生关键事件要记账
- 已暴露的秘密要记账

#### 对 ForeshadowGraph 的关系
- 可以埋设新伏笔
- 可以强化已有悬念
- 可以回收承诺
- 可以制造假线索

#### 对 ReviewIssue 的关系
- 无效推进
- 角色失真
- 世界越界
- 时间断裂
- 承诺遗失
都应在 `PlotUnit` 层被发现或定位

---

## 6. PlotUnit 的设计原则

### 6.1 变化优先于热闹
不是“发生了很多事”就叫推进，而是“状态发生了变化”才叫推进。

### 6.2 决策优先于描述
推进通常来自角色做出决定，而不是来自系统平铺说明。

### 6.3 冲突必须存在
没有阻力的推进，通常缺乏叙事价值。

### 6.4 后果必须可记录
每个有效 `PlotUnit` 都应至少留下某种后果。

### 6.5 可删性应可判断
如果删除一个 `PlotUnit`，故事几乎不受影响，那么它要么过弱，要么设计有问题。

---

## 7. PlotUnit 的统一层级

建议把所有叙事层都统一为 `PlotUnit` 的不同粒度。

### 7.1 Book-level PlotUnit
全书级推进单元。
关注：
- 全书主线
- 大型主题闭环
- 核心成长与终局

### 7.2 Arc-level PlotUnit
篇章级推进单元。
关注：
- 阶段目标
- 阶段冲突
- 阶段转折
- 阶段收束或升级

### 7.3 Chapter-level PlotUnit
章节级推进单元。
关注：
- 单章任务
- 信息释放
- 局部推进
- 章尾钩子

### 7.4 Scene-level PlotUnit
场景级推进单元。
关注：
- 一次具体互动
- 一次局部决策
- 一次具体冲突处理
- 一次即时状态变化

#### 原则
四层不是不同逻辑，而是同一逻辑的不同尺度。

---

## 8. PlotUnit 的基本公式

推荐使用以下公式理解：

**输入状态 + 角色决策 + 世界约束 + 冲突压力 = 事件 = 输出状态**

这意味着一个 `PlotUnit` 至少要回答 5 个问题：

1. 开始前是什么状态
2. 谁在推动什么目标
3. 遇到了什么阻力
4. 发生了什么事件
5. 结束后什么变了

---

## 9. PlotUnit 建议包含的层

第一版建议把 `PlotUnit` 分成 8 层。

---

### 9.1 层级层

用于定义这是哪个粒度的推进。

#### 典型内容
- unit_id
- level
- parent_unit
- previous_unit
- next_unit

#### 作用
帮助系统把当前推进放在整体结构中定位。

---

### 9.2 目标层

用于定义本单元想完成什么。

#### 典型内容
- unit_goal
- local_goal
- hidden_goal
- failure_condition
- success_condition

#### 作用
解释本单元为什么存在。

---

### 9.3 输入状态层

用于定义本单元开始前的局势。

#### 典型内容
- input_state_ref
- active_characters
- current_pressure
- current_constraints
- active_promises_in_scope

#### 作用
明确推进起点。

---

### 9.4 行动与冲突层

用于定义本单元内的实际对抗过程。

#### 典型内容
- initiator
- responders
- key_decision
- opposition
- tactics_used
- conflict_type
- cost_paid
- compromise_or_escalation

#### 作用
回答“推进是怎么发生的”。

---

### 9.5 事件层

用于定义本单元内真正发生了什么。

#### 典型内容
- event_summary
- decisive_moment
- reveal_event
- failure_event
- reversal_event

#### 作用
把“决策与冲突”落实为可记录的事。

---

### 9.6 输出状态层

用于定义本单元结束后世界变成什么样。

#### 典型内容
- output_state_ref
- goal_shift
- relation_shift
- information_shift
- conflict_shift
- risk_shift
- access_shift

#### 作用
回答“到底改变了什么”。

---

### 9.7 承诺与信息层

用于定义本单元对悬念和伏笔做了什么。

#### 典型内容
- foreshadowing_added
- foreshadowing_advanced
- foreshadowing_resolved
- false_leads_added
- promises_opened
- promises_narrowed

#### 作用
保证叙事承诺不会丢失。

---

### 9.8 审查层

用于定义如何评价这个单元。

#### 典型内容
- progression_strength
- legality_status
- character_consistency_status
- redundancy_risk
- review_notes

#### 作用
把生成和审查绑定起来。

---

## 10. 建议字段

### 10.1 基础标识字段

#### unit_id
单元唯一 ID。

#### level
层级类型。

例如：
- book
- arc
- chapter
- scene

#### title_or_label
该单元的短标题或功能标签。

#### parent_unit
所属上级单元。

#### previous_unit
前一个单元。

#### next_unit
后一个单元。

---

### 10.2 目标字段

#### unit_goal
本单元主要目标。

#### local_goal
局部操作目标。

#### hidden_goal
未表明但实际在起作用的目标。

#### success_condition
什么算本单元成功。

#### failure_condition
什么算本单元失败。

---

### 10.3 输入字段

#### input_state_ref
输入状态引用。

#### active_characters
参与者列表。

#### active_conflicts
当前冲突列表。

#### current_constraints
当前约束列表。

#### active_promises_in_scope
当前受影响的承诺/伏笔。

---

### 10.4 行动字段

#### initiator
发起关键行动的人。

#### responders
主要回应者。

#### key_decision
本单元关键决策。

#### conflict_type
冲突类型。

例如：
- interpersonal
- internal
- social
- environmental
- informational

#### tactics_used
采取的行动策略。

#### cost_paid
本单元付出的代价。

#### compromise_or_escalation
结果是妥协、僵持还是升级。

---

### 10.5 事件字段

#### event_summary
事件简述。

#### decisive_moment
决定性时刻。

#### reveal_event
信息暴露事件。

#### reversal_event
反转事件。

#### fallout_event
即时后果事件。

---

### 10.6 输出字段

#### output_state_ref
输出状态引用。

#### state_change_summary
状态变化摘要。

#### goal_shift
目标变化。

#### relation_shift
关系变化。

#### information_shift
信息权限变化。

#### conflict_shift
冲突变化。

#### risk_shift
风险变化。

---

### 10.7 伏笔与承诺字段

#### foreshadowing_added
新增伏笔。

#### foreshadowing_advanced
推进中的伏笔。

#### foreshadowing_resolved
已回收伏笔。

#### false_leads_added
新增误导项。

#### promises_opened
新建立的叙事承诺。

#### promises_delayed
被延后的承诺。

---

### 10.8 审查字段

#### progression_strength
推进强度。

例如：
- none
- weak
- medium
- strong

#### legality_status
合法性状态。

#### character_consistency_status
角色一致性状态。

#### redundancy_risk
冗余风险。

#### removable_without_loss
是否可删且不伤主线。

#### review_notes
审查备注。

---

## 11. PlotUnit 的更新原则

一个有效 `PlotUnit` 结束后，至少应更新以下一项：

- 目标
- 信息
- 关系
- 风险
- 冲突
- 可用资源
- 承诺状态
- 世界局势

如果这些都没变，那么这个单元很可能只是“表面有内容，实际无推进”。

---

## 12. 有效推进的判定标准

一个 `PlotUnit` 至少满足以下 4 条中的 1 条，才可视为有效推进：

### 12.1 目标变化
角色的目标建立、转移、受阻或失败。

### 12.2 信息变化
某个重要事实被发现、误解、隐藏、暴露或重新解释。

### 12.3 关系变化
角色之间的信任、依赖、敌意、责任发生明显变化。

### 12.4 风险或局势变化
当前风险升级、规则触发、资源变动、阵营态度变化。

#### 更强的推进
如果同一单元同时改变两项及以上，通常可视为中强推进或强推进。

---

## 13. 常见错误

### 13.1 只有热闹没有变化
错误例子：
- 打斗、争吵、追逐都发生了，但关系、信息、目标和局势都没变。

### 13.2 只有解释没有行动
错误例子：
- 一整段都在讲设定或回忆，却没有造成当前状态变化。

### 13.3 冲突存在但无代价
错误例子：
- 主角总能轻松脱身，没有损失，没有后果。

### 13.4 单元目的不清
错误例子：
- 看完不知道这段存在是为了什么。

### 13.5 回收与埋设失衡
错误例子：
- 不断开新悬念，但不推进旧悬念。

### 13.6 和上一个状态脱节
错误例子：
- 本单元像从真空中开始，没接住上一场后果。

---

## 14. 最小版本建议

第一版 `PlotUnit` 不需要很大。  
建议先保留这些最小字段：

- unit_id
- level
- unit_goal
- input_state_ref
- active_characters
- initiator
- key_decision
- active_conflicts
- event_summary
- output_state_ref
- state_change_summary
- foreshadowing_added
- foreshadowing_resolved
- progression_strength

只要这些字段稳定，已经足够支撑地基阶段。

---

## 15. 示例

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
  "conflict_type": "interpersonal + informational",
  "tactics_used": [
    "言语试探",
    "假动作诱敌",
    "短时越位抢夺"
  ],
  "cost_paid": [
    "c001 旧伤复发",
    "残魂反应被 c002 察觉到异常"
  ],
  "compromise_or_escalation": "升级",
  "event_summary": "c001 抢到令牌，但在高压中出现异常反应，c002 由此确认其体内确有隐患。",
  "decisive_moment": "c001 在 c003 逼迫下强行发动异常感知能力完成反抢",
  "reveal_event": "c002 首次确认 c001 身上存在非正常力量痕迹",
  "reversal_event": "c003 原以为能逼 c001失控，却反而让其拿到了令牌",
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
  ]
}
```

