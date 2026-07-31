# 改写工作流

## 文档目的
本文件用于定义自动小说系统中的“改写工作流”。

它回答的不是“推倒重来怎么写”，而是：

- 当某个 `PlotUnit`、某段关系线、某条承诺线程或某个局部结构已经失败时，系统如何在不破坏整体系统的前提下修正
- 如何判断应该改哪一层对象
- 如何按固定顺序同步相关对象
- 什么时候局部改写足够，什么时候必须升级为 `Replan`

本文件主要连接以下对象与规则：

- `PlotUnit`
- `NarrativeState`
- `CharacterModel`
- `WorldModel`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`
- `ReviewReminder`

以及：

- `04_workflows/02_review_workflow.md`
- `03_rules/01_state_transition_rules.md`
- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`

---

## 1. 工作流定位

改写工作流的任务不是“重写一版更漂亮的文本”，而是：

**针对已经识别出的失败点，用最小代价把系统修回可继续运行的状态。**

这意味着改写不是默认全盘重写，而是先回答：

1. 问题真正坏在哪一层
2. 应该先修哪个对象
3. 需要联动同步哪些对象
4. 修完后是否通过复检

### 一句话定义

改写工作流就是把一个已经失败的局部，修回系统可继续推进的状态。

---

## 2. 适用场景

本工作流适用于以下情况：

### 2.1 单个 PlotUnit 失败

例如：

- 这一场戏无效推进
- 这一场戏角色失真
- 这一场戏世界越界
- 这一场戏信息释放错误

### 2.2 局部关系线失真

例如：

- 信任跳变
- 情感确认过早
- 背叛后没有余波

### 2.3 局部承诺线失衡

例如：

- 某个伏笔回收突兀
- 某条主线长期停摆
- 某个假线索污染真线

### 2.4 中段结构跑偏，但尚未到全盘重做

例如：

- 当前 arc 还能救，但已经不能只改一句两句
- 若不重写最近几个 `PlotUnit`，后面无法继续

---

## 3. 工作流输入

一次改写工作流至少应准备以下输入。

### 3.1 核心必需输入

- 一个或多个 `ReviewIssue`
- 相关失败对象，至少包括以下之一：
  - 失败的 `PlotUnit`
  - 对应 `NarrativeState`
  - 被污染的 `FactLedger` 条目
  - 被污染的 `ForeshadowGraph` 线程
  - 相关 `CharacterModel`

### 3.2 补充输入

如条件允许，建议额外读取：

- 前一到三个 `PlotUnit`
- 失败对象的上下游状态
- 当前 arc 目标
- 当前未关闭 `ReviewReminder` 列表
- 作者额外改写约束

### 3.3 输入不足时的处理规则

若只有“感觉这里不对”，但没有明确问题对象或失败定位，不建议直接进入正式改写。

### 处理方式

先进入：

- `Review Workflow`

先把问题对象化，再进入改写。

---

## 3.4 输入上下文包

从 harness 视角看，`Rewrite` 读取的不是“哪里看着不对”，而是一组已经进入修复链的上下文包。

### A. 问题定位包

必须优先读取：

- 一个或多个 `ReviewIssue`
- 失败对象的类型与 ID
- `violated_rule`
- `supporting_facts`
- `suggested_fix_type`

这是判断“为什么修、先修哪里”的起点。

### B. 失败对象包

必须按需读取：

- 失败的 `PlotUnit`
- 对应 `NarrativeState`
- 被污染的 `FactLedger`
- 被污染的 `ForeshadowGraph`
- 相关 `CharacterModel`

这部分决定问题实际蔓延到了哪一层。

### C. 上下游影响包

如条件允许，建议额外读取：

- 前一到三个 `PlotUnit`
- 失败对象的输入 / 输出引用
- 当前 arc 目标
- 未关闭 `ReviewReminder`

这部分帮助判断当前修复范围是 `point`、`chain`，还是 `segment`。

### D. 修复边界包

进入改写前，应能回答：

- 主根因对象是哪一个
- 哪些对象必须联动同步
- 哪些对象不应被这次修复波及

如果这组边界不清，改写很容易从局部修复滑向失控重写。

---

## 4. 工作流输出

一次改写工作流至少应产出以下内容。

### 4.1 必产出

- 修正后的目标对象
  - 通常是新的 `PlotUnit`
  - 或新的 `NarrativeState`

### 4.2 条件更新

- `FactLedger`
- `ForeshadowGraph`
- `CharacterModel` 中允许成长或运行态化的字段
- `ReviewIssue.status`

### 4.3 必要复检

改写完成后，必须重新调用：

- `04_workflows/02_review_workflow.md`

以确认：

- 原问题是否真正解决
- 是否引入了新的问题

---

## 4.4 输出状态包

`Rewrite` 的结果应被理解为一组修复包，而不只是“改过一版”。

### A. 根因修复包

至少包含：

- 被修复的主对象
- 修复方式
- 修复后的关键变化摘要

### B. 联动同步包

按情况输出：

- 新的 `PlotUnit`
- 新的 `NarrativeState`
- 修正后的 `FactLedger`
- 修正后的 `ForeshadowGraph`
- 必要时更新后的 `CharacterModel`

这部分负责把单点修复真正同步回依赖层。

### bounded runtime-first exception 的限制

当主根因位于 `PlotUnit` / `NarrativeState`，且 `FactLedger` 本身不是根因时，允许 bounded runtime-first repair 起步。

但这只表示：

- repair packet 可以先修局部运行态根因

不表示：

- 可以把新硬事实拖到下一轮再补账
- 可以先把结果送去 `Review`，之后再补 `FactLedger`
- 可以先改 `CharacterModel` 摘要来替事实层兜底

只要本轮 `Rewrite` 已明确某条新硬事实成立，就必须在同一 repair packet 内完成 `FactLedger` 写回，然后再进入 `Review`。

### C. 问题状态包

至少包含：

- `ReviewIssue.status`
- `resolution_note`
- 是否仍有残留 `ReviewReminder`
- 是否需要升级为 `Replan`

### D. 复核入口包

在重新进入 `Review` 前，至少应能清楚交付：

- 修了哪个 issue
- 改了哪些对象
- 哪些字段被联动同步
- 哪些风险仍未关闭

如果这组信息交不清楚，复核就很难判断这次改写到底解决了什么。

---

## 5. 改写工作流总顺序

建议按以下顺序执行：

```text
读取 ReviewIssue
  ↓
定位主根因层
  ↓
判断改写范围
  ↓
选择最小修复策略
  ↓
先修主根因对象
  ↓
按依赖顺序同步相关对象
  ↓
重新审查
  ↓
关闭 / 缓解 / 保留 Issue
```

---

## 6. 详细步骤

## 6.1 第一步：读取 ReviewIssue

### 目标

明确“为什么要改”。

### 读取重点

- `issue_type`
- `object_type`
- `object_id`
- `violated_rule`
- `supporting_facts`
- `missing_elements`
- `suggested_fix_type`
- `severity`
- `blocking_status`

### 输出

得到一份明确的问题说明。

### 原则

没有明确问题对象，就不要直接改写。

---

## 6.2 第二步：定位主根因层

### 目标

判断问题到底坏在哪一层。

### 可能层级

#### A. 单元层问题

通常表现为：

- 当前 `PlotUnit` 无效
- 某场戏角色失真
- 某次揭露突兀

#### B. 状态层问题

通常表现为：

- 当前 `NarrativeState` 与前态脱节
- 情绪后果丢失
- 当前主目标错误

#### C. 事实层问题

通常表现为：

- `FactLedger` 错记、漏记
- 已有事实与文本冲突

#### D. 承诺层问题

通常表现为：

- `ForeshadowGraph` 线程停摆
- 假线索失控
- 回收窗口管理错误

#### E. 角色层问题

通常表现为：

- `CharacterModel` 的运行态或可成长字段未同步
- 关系变化没落定
- 当前行为与角色结构脱节

#### F. 规划层问题

通常表现为：

- 不是某一场坏了，而是连续几场方向都错了
- 当前 arc 需要重排

### 输出

定位“主根因层”。

### 原则

改写优先修主根因，而不是只修表面症状。

---

## 6.3 第三步：判断改写范围

### 目标

决定这次改写是点状修、链状修，还是段状重写。

### 三种范围

#### 6.3.1 点状改写

只改一个对象。

适用于：

- 单次信息释放错误
- 单次代价漏写
- 单个桥接缺失

#### 6.3.2 链状改写

改一个对象及其上下游对象。

适用于：

- 改一个 `PlotUnit` 会影响前后状态
- 改一个关系节点会影响下一场
- 改一个知识状态要联动账本与承诺线程

#### 6.3.3 段状改写

改连续若干单元或一段 arc。

适用于：

- 当前主线方向错了
- 局部补丁已无法修复
- 多个 issue 指向同一段结构失衡

### 输出

得到改写范围：

- `point`
- `chain`
- `segment`

---

## 6.4 第四步：选择最小修复策略

### 目标

在不扩大污染的前提下，选择最小可行修法。

### 常见修复策略

- `local_rewrite`
- `character_motivation_patch`
- `relationship_bridge_scene`
- `cost_insertion`
- `info_gate_adjustment`
- `foreshadow_advancement`
- `fact_correction`
- `state_update`
- `arc_replanning`

### 选择原则

优先选择：

- 最小
- 最接近根因
- 不会制造连锁新问题

---

## 6.5 第五步：先修主根因对象

### 目标

先把真正出错的对象修正，而不是多对象并行乱改。

### 对象优先规则

#### 如果问题在 `PlotUnit`

优先修改：

- `unit_goal`
- `key_decision`
- `event_summary`
- `state_change_summary`
- `cost_paid`
- `relation_shift`
- `information_shift`

#### 如果问题在 `NarrativeState`

优先修改：

- `primary_goal`
- `active_conflicts`
- `public_information`
- `hidden_information`
- `emotional_temperature`
- `open_questions`

#### 如果问题在 `FactLedger`

优先修改：

- `statement`
- `known_by`
- `status`
- `chronological_order`

#### 如果问题在 `ForeshadowGraph`

优先修改：

- `advancement_nodes`
- `status`
- `urgency_to_payoff`
- `false_paths`
- `payoff_nodes`

#### 如果问题在 `CharacterModel`

优先修改：

- `short_term_goal`
- `knowledge_state`
- `relations`
- `arc_stage`
- `self_image`

### 原则

改写先改主根因对象，再考虑联动同步。

### bounded runtime-first 的局部例外

如果问题主根因位于：

- `PlotUnit`
- `NarrativeState`

并且现有 `FactLedger` 不是根因对象，只是尚未被当前局部正确继承，则允许先修运行态根因。

但这个局部例外只成立到：

- `FactLedger` 是否需要新增 / 更正条目被确认之前

一旦本轮修复已经确认新硬事实成立，就不能继续把它留在运行态或 prose handoff 中等待后补。

---

## 6.6 第六步：按依赖顺序同步相关对象

### 目标

避免“改了一处，但系统其他层还停留在旧版本”。

### 总原则

不要把“相关对象都要改”理解成“同时乱改”。
应按以下顺序执行：

1. 先修主根因对象
2. 再同步它直接依赖的运行态
3. 再同步硬事实层
4. 再同步承诺线程层
5. 最后同步角色运行态与成长字段

### 联动规则

#### 如果主根因在 `PlotUnit`

按以下顺序同步：

1. `PlotUnit`
2. `NarrativeState`
3. `FactLedger`
4. `ForeshadowGraph`
5. 必要时 `CharacterModel`

#### 如果主根因在 `NarrativeState`

按以下顺序同步：

1. `NarrativeState`
2. 相关 `PlotUnit` 的输入 / 输出引用
3. `FactLedger`
4. `ForeshadowGraph`
5. 必要时 `CharacterModel`

#### 如果主根因在 `FactLedger`

按以下顺序同步：

1. `FactLedger`
2. `NarrativeState` 中对应的信息分布或局势约束
3. `CharacterModel.knowledge_state`
4. 如影响承诺线程，再同步 `ForeshadowGraph`

#### 如果主根因在 `ForeshadowGraph`

按以下顺序同步：

1. `ForeshadowGraph`
2. `NarrativeState.open_questions / active_promises`
3. 相关 `PlotUnit` 的推进标记
4. 必要时 `ReviewIssue`

#### 如果主根因在 `CharacterModel`

按以下顺序同步：

1. `CharacterModel`
2. 当前 `NarrativeState`
3. 相关 `PlotUnit` 的动机与决策
4. 必要时 `FactLedger`
5. 必要时 `ForeshadowGraph`

### 原则

不允许“文本逻辑已经改了，但对象层仍然是旧的”。

也不允许以下三种误用：

1. 先修运行态，跨 handoff 再补 `FactLedger`
2. 先复检 rewrite 结果，之后再补 `FactLedger`
3. 先改 `CharacterModel` 摘要，再倒逼事实层追认

---

## 6.7 第七步：重新审查

### 目标

确认这次改写不是“换一种坏法”。

### 调用

- `04_workflows/02_review_workflow.md`

### 必查

- 原问题是否消失
- 是否引入新问题
- 是否降低了推进强度
- 是否制造新的冲突或新的空转

### 输出

得到：

- `通过`
- `通过但有警告`
- `仍失败`

### 原则

只有在所有相关对象完成同步后，才进入复检。

---

## 6.8 第八步：更新 ReviewIssue 状态

### 目标

让问题单进入闭环。

### 可能结果

#### `resolved`

原问题已被修复。

#### `mitigated`

问题仍有残留，但显著减轻，不再阻断。

#### `in_progress`

改写尚未完成，或需要继续第二轮修补。

#### `dismissed`

复检后发现原 issue 判定不成立。

### 建议更新字段

- `status`
- `last_updated`
- `resolved_by`
- `resolution_note`

---

## 7. 改写范围判定规则

什么情况下只改一场，什么情况下必须升级到更大层级，建议按以下规则判断。

## 7.1 只改当前 PlotUnit 就够

适用于：

- 局部动机不足
- 单次信息泄露
- 单次代价漏写
- 单次回收过猛但可补桥

### 典型 issue

- `motivation_gap`
- `missing_cost`
- `information_leak`

---

## 7.2 需要联动前后状态

适用于：

- 当前局势定义错误
- 情绪后果断裂
- 知情范围写错
- 关系变化缺少承接

### 典型 issue

- `relationship_jump`
- `missing_consequence`
- `timeline_error`

---

## 7.3 必须升级为 Replan

适用于：

- 核心承诺线程长期失控
- 多条主线冲突
- 当前数个单元都建立在错误方向上
- 主线与支线权重严重错位

### 典型 issue

- `promise_loss`
- `duplication_of_threads`
- 严重 `abrupt_payoff`

---

## 8. 改写中的常见失败

### 8.1 只改表面句子，不改对象层

表现：

- 文本看起来顺了
- 但 `NarrativeState`、`FactLedger`、`ForeshadowGraph` 都没变

### 8.2 多对象并行乱改

表现：

- 每一层都动了
- 但说不清到底哪里是根因

### 8.3 修一个洞，开三个洞

表现：

- 修正关系跳变后，反而制造时间错误或信息越界

### 8.4 把局部问题升级成全盘推翻

表现：

- 一个 scene 的问题，直接推翻整个 arc

### 8.5 改完不复检

表现：

- 改完觉得“应该好了”
- 但没有重新审查

### 8.6 把 runtime-first 例外拖成跨轮 shortcut

表现：

- 本轮已明确新硬事实
- 却让 `FactLedger` 等到 handoff 后、复检后、或下一轮再补

### 8.7 先改 `CharacterModel` 解释 scene

表现：

- 角色摘要先吸收了新 access / route / authority 约束
- 事实层与运行态层仍停留在旧版本

---

## 9. 何时不适合进入改写工作流

以下情况不建议直接改写：

### 9.1 问题还没被明确定位

此时应先进入：

- `Review Workflow`

### 9.2 输入对象本身不完整

例如：

- 当前状态不清
- 账本严重缺失
- 承诺线程未重建

此时应先进入：

- `Rebuild Workflow`

### 9.3 问题已超出局部修复能力

例如：

- 当前 arc 的方向整体错误
- 多条主线互相冲突

此时应直接进入：

- `Replan`

而不是继续硬做局部改写。

---

## 10. 改写结果模板

```text id="rwttmpl01"
改写工作流输出

输入问题：
- issue_id：
- issue_type：
- object_type：
- object_id：

一、根因定位
- 主根因层：
- 次根因层：

二、改写范围
- point / chain / segment

三、修复策略
- suggested_fix_type：
- 实际采用策略：

四、改写对象
- PlotUnit：
- NarrativeState：
- FactLedger：
- ForeshadowGraph：
- CharacterModel：

五、同步更新
- 按什么顺序同步：
- 更新了哪些对象：
- 更新了哪些字段：

六、复检结果
- 通过 / 警告 / 失败

七、Issue 状态更新
- status：
- resolved_by：
- resolution_note：

八、后续动作
- 继续推进 / 再次改写 / 升级为 Replan
```

---

## 11. 示例：修复“c001 突然信任 c003”

### 输入问题

- `issue_type = character_distortion`
- `summary = c001 突然决定信任 c003，与既有 fear 和关系张力不匹配`

### 根因定位

- 主根因层：`PlotUnit`
- 次根因层：`NarrativeState`

### 改写范围

- `chain`

因为不仅要改当前单元，还要联动当前状态和关系字段。

### 修复策略

- `character_motivation_patch`
- `relationship_bridge_scene`

### 改写动作

把原来的：

- “c001 直接信任 c003”

改成：

- c003 先提供一条只有半知情者才可能知道的关键信息
- c001 不是完全信任，而是在高压下选择保留式合作

### 同步顺序

1. 改 `PlotUnit.key_decision`
2. 同步 `NarrativeState.active_relation_tensions`
3. 必要时同步 `FactLedger` 中的知情变化
4. 同步 `ForeshadowGraph` 中关系线程推进节点
5. 同步 `CharacterModel.relations`

### 复检

重新审查后：

- 不再构成 `character_distortion`
- 降为 `valid_with_cost`

### Issue 更新

- `status = resolved`
- `resolved_by = rewrite_scene_018_v2`
- `resolution_note = 将直接信任改为被迫合作，并补入证据触发点`

---

## 12. 工作流成功标准

一次改写工作流算成功，不是因为“改得更漂亮”，而是因为它完成了以下五件事：

1. 找到真正的主根因
2. 用最小范围修复问题
3. 没有把局部修复升级成全局污染
4. 把相关对象按顺序同步更新
5. 经过复检后，问题真正关闭或缓解

---

## 13. 一句话总结

改写工作流的核心，不是“重写一遍”，而是：

**针对已经明确的问题，先修主根因对象，再按依赖顺序同步对象层，让系统从坏掉的局部回到可继续运行的状态。**
