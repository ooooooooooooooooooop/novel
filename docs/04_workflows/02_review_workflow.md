# 审查工作流

## 文档目的
本文件用于定义自动小说系统中的“正式审查工作流”。

它回答的不是“用哪些规则审查”，而是：

- 一次审查从哪里开始
- 审查前需要准备哪些对象
- 审查按什么顺序执行
- 审查结果如何生成 `ReviewIssue`
- `warning`、正式问题、`Rewrite`、`Replan` 如何分流
- 审查结果如何写回系统而不越权改写主存对象

本文件主要连接以下对象与规则：

- `PlotUnit`
- `NarrativeState`
- `CharacterModel`
- `WorldModel`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

以及：

- `03_rules/01_state_transition_rules.md`
- `03_rules/02_world_legality_rules.md`
- `03_rules/03_character_consistency_rules.md`
- `03_rules/04_timeline_rules.md`
- `03_rules/05_information_release_rules.md`
- `03_rules/06_foreshadow_rules.md`
- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`

---

## 1. 工作流定位

审查工作流的任务不是生成内容，而是判断：

1. 这次推进是否成立
2. 这次推进是否与系统其余对象一致
3. 这次推进坏在什么层
4. 当前问题是否阻断后续继续推进
5. 若不放行，系统应进入 `Rewrite` 还是 `Replan`

### 一句话定义

审查工作流就是把一次推进，从“看起来写完了”变成“系统确认它能不能进入下一轮”。

---

## 2. 适用场景

本工作流适用于以下情况：

### 2.1 单个 PlotUnit 审查

例如：

- 刚生成一场戏
- 想判断这场戏是否成立

### 2.2 单章审查

例如：

- 一章写完后，检查是否有逻辑崩坏
- 检查这一章推进是否有效

### 2.3 阶段性审查

例如：

- 一个 arc 结束后，检查主线、关系线、承诺线是否稳定
- 检查最近一段是否开始跑偏

### 2.4 重建结果复核

例如：

- 从已有文本抽取对象后，检查重建结果是否失真
- 检查 `FactLedger` 与 `ForeshadowGraph` 是否严重漏项

---

## 3. 工作流输入

一次正式审查至少应准备以下输入。

### 3.1 核心必需输入

### 当前审查对象

至少需要其一：

- `PlotUnit`
- `chapter bundle`
- `arc bundle`

但当前推荐的最小审查粒度仍然是：

**单个 `PlotUnit`**

### 对应状态

- `input_state_ref`
- `output_state_ref`

### 相关对象

- 当前相关 `CharacterModel`
- 当前相关 `WorldModel`
- 当前相关 `FactLedger`
- 当前相关 `ForeshadowGraph`

### 3.2 补充输入

如条件允许，建议额外读取：

- 前一单元 `previous_unit`
- 下一单元规划摘要
- 相关 `ReviewIssue` 历史记录
- 相关实验日志

### 3.3 输入不足时的处理规则

若缺少以下输入之一，应降低审查置信度：

- `input_state_ref`
- `output_state_ref`
- 相关 `CharacterModel`
- 相关 `FactLedger`

### 处理方式

可输出：

- `通过但信息不足`
- `警告：审查条件不完整`

但不应轻易生成高置信、阻断型结论。

---

## 4. 工作流输出

一次正式审查至少应产出以下内容。

### 4.1 审查结论

三选一：

- `通过`
- `通过但有警告`
- `失败`

### 4.2 PlotUnit 审查字段回写

至少更新：

- `progression_strength`
- `legality_status`
- `character_consistency_status`
- `redundancy_risk`
- `review_notes`

### 4.3 问题对象

若存在正式问题，应生成一个或多个：

- `ReviewIssue`

### 4.4 后续动作建议

至少选择其一：

- 允许继续推进
- 允许继续推进，但带警告
- 进入改写工作流
- 升级为 `Replan`

### 4.5 审查回写边界

审查的职责是：

- 判定
- 分类
- 生成问题对象
- 决定分流

审查不应直接改写以下主存对象的事实内容：

- `FactLedger`
- `ForeshadowGraph`
- `CharacterModel`
- `NarrativeState`

如果发现这些对象本身有问题，应该：

- 生成 `ReviewIssue`
- 或写入 `review_notes`

而不是在审查阶段静默修正它们。

---

## 5. 审查工作流总顺序

建议一次标准审查按以下顺序执行：

```text
读取输入
  ↓
检查输入完整性
  ↓
状态转移检查
  ↓
硬合法性检查
  ↓
角色与关系检查
  ↓
承诺与结构检查
  ↓
综合结论
  ↓
失败归类
  ↓
生成 ReviewIssue 或 warning 记录
  ↓
回写审查字段
  ↓
给出 Continue / Rewrite / Replan 分流
```

---

## 6. 详细步骤

## 6.1 第一步：读取审查对象

### 目标

明确“这次到底在审什么”。

### 最小动作

读取：

- 当前 `PlotUnit`
- `input_state_ref`
- `output_state_ref`

### 输出

得到一个明确的审查单元。

### 注意

如果当前审查对象不是单个 `PlotUnit`，建议先拆成：

- 章节内多个 `PlotUnit`
- 或 arc 内关键 `PlotUnit` 列表

避免直接对一大段文本做模糊审查。

---

## 6.2 第二步：检查输入完整性

### 目标

判断这次审查是否具备足够上下文。

### 检查清单

- 是否有输入状态
- 是否有输出状态
- 是否有相关角色模型
- 是否有相关事实账本
- 是否有相关承诺线程

### 输出

给出以下之一：

- `输入完整`
- `输入部分缺失`
- `输入不足，仅能做低置信审查`

### 处理原则

输入不足时：

- 可以继续审查
- 但不轻易生成 `critical` 或 `blocking` 级正式问题

---

## 6.3 第三步：状态转移检查

### 调用规则

- `03_rules/01_state_transition_rules.md`

### 检查目标

确认本次推进本身是否构成有效状态变化。

### 必查问题

- 是否有明确输入状态
- 是否有关键决策
- 是否有阻力
- 是否有输出状态
- `state_change_summary` 是否成立

### 输出

至少给出：

- `progression_strength`
- 是否存在 `weak_progression`

### 若失败

进入候选失败类型：

- `weak_progression`
- `redundancy`

### 路由原则

仅有轻度推进不足，但未破坏其他对象时，可先记为 warning。  
若推进无效到“当前单元几乎可删”，则应进入正式问题。

---

## 6.4 第四步：硬合法性检查

这一阶段优先检查会直接破坏系统成立的问题。

### 6.4.1 世界合法性检查

调用：

- `03_rules/02_world_legality_rules.md`

候选失败类型：

- `world_violation`
- `missing_cost`
- `missing_consequence`

### 6.4.2 时间合法性检查

调用：

- `03_rules/04_timeline_rules.md`

候选失败类型：

- `timeline_error`

### 6.4.3 信息释放检查

调用：

- `03_rules/05_information_release_rules.md`

候选失败类型：

- `information_leak`
- `abrupt_payoff`
- `promise_loss`
- `missing_consequence`

### 路由原则

以下问题默认优先视为正式问题，而不是普通 warning：

- `fact_conflict`
- `world_violation`
- `timeline_error`
- 严重 `information_leak`

因为它们会直接污染后续继续推进。

---

## 6.5 第五步：角色与关系检查

### 调用规则

- `03_rules/03_character_consistency_rules.md`

### 检查目标

确认角色仍然像“这个角色”，而不是剧情工具。

### 必查问题

- 关键决策是否符合目标
- 是否符合 `fear` / `flaw` / `blind_spot`
- 是否有足够动机承接
- 关系变化是否过快
- 成长是否跳变

### 候选失败类型

- `character_distortion`
- `motivation_gap`
- `relationship_jump`

### 路由原则

以下情况通常应升级为正式问题：

- 角色核心决策失真
- 关系跳变已经破坏当前单元成立
- 缺失动机已导致行为只为剧情服务

以下情况可暂记为 warning：

- 关系变化已逼近边界，但尚未越线
- 动机略薄，但仍可在下一单元补桥

---

## 6.6 第六步：承诺与结构检查

### 调用规则

- `03_rules/06_foreshadow_rules.md`

### 检查目标

确认主线、支线、伏笔、误导和回收是否仍被正确管理。

### 必查问题

- 当前线程是否有推进
- 是否有承诺遗失
- 是否回收过早
- 是否假线索失控
- 是否主线被次级线遮蔽

### 候选失败类型

- `promise_loss`
- `abrupt_payoff`
- `duplication_of_threads`
- `missing_consequence`

### 路由原则

以下情况通常只记 warning：

- 某核心线程 1 到 2 个单元内必须推进
- 某后果已建立但尚未兑现
- 某关系线已逼近需要补桥的边缘

以下情况应升级为正式问题：

- 核心承诺线程已明显脱轨或停摆
- 某回收已经突兀成立
- 多个线程开始互相冲突

若问题已不再是单个 `PlotUnit`，而是 arc 层结构失衡，应直接标记为 `Replan` 候选。

---

## 6.7 第七步：综合审查结论

### 调用规则

- `03_rules/07_review_rules.md`

### 目标

把前面分项结果汇总成单一结论。

### 结论分类

#### 通过

满足：

- 无阻断型硬错误
- `progression_strength` 不为 `none`
- 角色未正式失真
- 承诺线程未正式失控

#### 通过但有警告

满足：

- 当前没有阻断错误
- 但存在 1 至 3 个单元内若不补偿就会升级的问题

#### 失败

满足任一条件：

- 存在阻断型硬错误
- 当前推进无效且不应放行
- 角色严重失真
- 核心承诺线程已明显失控
- 若不修正将直接污染下一步生成

---

## 6.8 第八步：失败归类

### 调用规则

- `03_rules/08_failure_types.md`

### 目标

把已确认的问题映射成稳定失败类型。

### 原则

- 一个核心问题尽量只选一个主失败类型
- 可附带次失败类型
- 主失败类型应最靠近根因

### 输出字段

- `issue_type`
- `severity`
- `blocking_status`
- `suggested_fix_type`

---

## 6.9 第九步：生成 ReviewIssue 或 warning 记录

### 目标

把正式问题对象化，同时把非阻断风险留在正确层级。

### 生成正式 ReviewIssue 的条件

满足以下任一条件时，生成正式 `ReviewIssue`：

1. 存在阻断型硬错误
2. 当前单元已经失真，而不是“尚可补偿”
3. 当前问题若不修将直接污染下一轮继续推进
4. 局部 `Rewrite` 已经明显优于继续拖延
5. arc 层结构失衡已经显形

### 只生成 warning / review_notes 的条件

满足以下特征时，优先不生成正式 `ReviewIssue`：

- 当前尚未失败
- 问题可在后续 1 到 3 个 `PlotUnit` 内自然补偿
- 当前问题更适合下一单元兑现，而不是回头重写上一单元

### warning 升级规则

当以下任一条件成立时，warning 不应继续停留在备注层：

1. 同一 warning 连续 2 次审查仍未补偿
2. 某 warning 已开始污染主线、关系线或知识边界
3. 多个 warning 指向同一结构弱点

此时应升级为正式 `ReviewIssue`。

### 记录方式

#### 正式问题

- 生成 `ReviewIssue`

#### warning

- 写入 `PlotUnit.review_notes`
- 必要时写入轻量 reminder note

当前不建议把所有 warning 都强行建单。

---

## 6.10 第十步：回写审查结果

### 目标

让审查结果真正进入系统，而不是停留在口头判断。

### 必回写字段

在 `PlotUnit` 上更新：

- `progression_strength`
- `legality_status`
- `character_consistency_status`
- `redundancy_risk`
- `review_notes`

### 回写边界

审查阶段正式写回的核心对象应限于：

- `PlotUnit` 的审查字段
- 新生成的 `ReviewIssue`

不建议在审查阶段直接修正：

- `NarrativeState`
- `FactLedger`
- `ForeshadowGraph`
- `CharacterModel`

如果这些对象有问题，应通过：

- `ReviewIssue`
- `Rewrite`
- `Replan`

来修复。

---

## 6.11 第十一步：决定后续动作

### 目标

给出这次审查后系统该怎么走。

### 可能结果

#### 继续推进

适用：

- 审查通过
- 或只有低级 warning

#### 带警告继续推进

适用：

- 当前问题不阻断
- 但未来 1 到 3 个单元内必须补偿

#### 进入改写工作流

适用：

- 当前单元本身失真
- 根因主要位于单元层、状态层或局部关系层

#### 升级为 Replan

适用：

- 多个 `ReviewIssue` 指向同一结构弱点
- arc 级方向失衡
- 主线与支线权重错位
- 局部 `Rewrite` 不再是合理修法

### 总分流规则

#### 通过

- 进入下一轮 `Continue`

#### 通过但有警告

- 带约束进入下一轮 `Continue`
- 并记录 warning 的补偿窗口

#### 失败且问题局部

- 进入 `Rewrite`

#### 失败且问题结构性

- 升级为 `Replan`

---

## 7. 审查结论的判定条件

## 7.1 通过

满足以下全部条件：

1. 无 `fact_conflict`
2. 无 `world_violation`
3. 无 `timeline_error`
4. 无严重 `information_leak`
5. `progression_strength` 不为 `none`
6. 无正式 `character_distortion`
7. 无正式 `promise_loss`

---

## 7.2 通过但有警告

满足：

- 当前没有阻断错误
- 但存在至少一条短期内会升级的问题

例如：

- `missing_cost` 尚未兑现，但可在后续补
- 某承诺线程 1 到 2 个单元内必须推进
- 某关系变化尚可成立，但必须补桥

---

## 7.3 失败

满足以下任一条件：

- 存在阻断型硬错误
- 当前推进无效且不应放行
- 角色严重失真
- 主承诺线严重失控
- 问题将直接污染下一步生成

---

## 8. warning 与正式问题的区分

### 8.1 warning

特征：

- 当前尚未完全失败
- 若不处理将升级
- 可先记录，不一定立刻阻断

### 示例

- 旧伤后果尚未体现
- 核心线程已两章未推进
- 关系变化已逼近过快边缘

### 处理

- 写入 `review_notes`
- 标注补偿窗口
- 仅在连续未补偿时升级

---

### 8.2 正式问题

特征：

- 当前已经违反规则
- 当前已经污染结构
- 若不修正就不应继续推进

### 处理

- 生成正式 `ReviewIssue`
- 给出修复方向
- 视情况阻断继续生成

---

## 9. 审查结果模板

```text
审查工作流输出

审查对象：
- PlotUnit：
- 输入状态：
- 输出状态：

一、输入完整性
- 是否完整：
- 缺失项：

二、状态转移结果
- progression_strength：
- 是否构成有效推进：

三、硬合法性结果
- 世界合法性：
- 时间合法性：
- 信息释放合法性：

四、角色与关系结果
- 角色一致性：
- 关系连续性：

五、承诺与结构结果
- 线程推进情况：
- 是否存在遗失 / 突兀回收：

六、失败归类
- 主失败类型：
- 次失败类型：

七、问题对象
- 是否生成 ReviewIssue：
- issue_id / issue_type：

八、最终结论
- 通过 / 通过但有警告 / 失败

九、后续动作
- Continue / 带警告 Continue / Rewrite / Replan
```

---

## 10. 示例：对“雨夜夺令”执行审查工作流

### 10.1 输入完整性

已具备：

- `pu_scene_014`
- `s_014_scene`
- `s_015_scene`
- 相关 `CharacterModel`
- 相关 `WorldModel`
- 相关 `FactLedger`
- 相关 `ForeshadowGraph`

结论：输入完整

### 10.2 状态转移检查

- 有输入状态
- 有关键决策
- 有明确冲突
- 有输出状态
- 改变了目标、信息、关系、风险

结论：

- `progression_strength = strong`

### 10.3 硬合法性检查

- 无世界硬规则越界
- 时间顺序成立
- 信息知情顺序成立
- 但后续必须体现旧伤与巡查压力

结论：

- 当前可放行，但挂 warning

### 10.4 角色与关系检查

- `c001` 的决策符合其高压下冒险模式
- 对 `c002` 没有突然完全信任
- 关系变化是摇摆，不是跳变

结论：

- `character_consistency_status = valid_with_cost`

### 10.5 承诺与结构检查

- `残魂秘密` 得到推进
- `c002 是否保密` 被正式打开
- 旧案真相尚未推进，但未达正式遗失阈值

结论：

- 当前承诺管理成立，但挂一条后续推进 warning

### 10.6 是否生成 ReviewIssue

当前不生成阻断型 issue。

保留 warning：

- 旧伤后果
- 巡查压力
- 保密压力

### 10.7 最终结论

**通过但有警告**

### 10.8 后续动作

允许继续推进，但未来 1 到 2 个 `PlotUnit` 内必须体现：

- 旧伤后果
- 巡查压力
- 保密压力

若连续两次审查仍未兑现，则 warning 升级为正式问题。

---

## 11. 工作流成功标准

一次审查工作流算成功，不是因为“挑出了很多毛病”，而是因为它完成了以下五件事：

1. 明确知道审查对象是什么
2. 明确知道哪里成立、哪里不成立
3. 明确知道问题属于哪种失败类型
4. 明确知道当前应记 warning 还是建正式问题
5. 明确知道下一步该继续、改写还是重规划

---

## 12. 一句话总结

审查工作流的核心，是把一次生成结果从“写完了”推进到“系统确认它该继续、该改写，还是该重规划”，也就是：

**先检查，后归类，再建单，最后决定放行、返工或升级。**
