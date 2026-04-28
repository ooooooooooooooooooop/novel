# 审查策略决策

## 文档目的
本文件用于收束当前阶段已经基本确定的审查策略相关决策。

它关注的不是某条审查规则本身写了什么，而是更上层的问题：

- 审查到底在系统里扮演什么角色
- 什么问题算 warning，什么问题算正式 issue
- 什么问题应该阻断，什么问题可以带警告放行
- 审查结论如何影响后续 workflow
- 为什么当前采用“通过 / 通过但有警告 / 失败”三段式结论
- 为什么审查优先解决成立性，而不是优先评价“文笔好不好”

本文件的作用，是防止后续扩展时出现审查过宽、审查过松、issue 泛滥、warning 没有升级规则，以及 workflow 被审查结论拖乱。

---

## 1. 文档定位

前面的决策文件已经固定了：

- 总方向
- 对象边界
- workflow 顺序
- schema 粒度
- 示例策略

本文件固定的是：

这套系统如何判断“现在能不能放行”，以及发现问题后该以什么力度进入后续流程。

它主要影响：

- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`

---

## 2. 当前需要固定的审查策略问题

当前最值得固定的审查策略问题主要有 8 个：

1. 审查优先级为什么是“成立性优先于精彩性”
2. 为什么采用三段式结论，而不是简单通过 / 失败
3. warning 与正式 issue 如何分层
4. 什么问题默认阻断
5. 什么问题可以带警告放行
6. warning 何时升级为正式问题
7. 为什么 issue 不应泛滥
8. 审查结果如何驱动 Continue / Rewrite / Replan 分流

---

## 3. DEC-20260326-40

### 决策标题

审查优先判断是否成立，而不是优先判断是否好看。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

自动小说系统中的审查很容易滑向泛评价，比如：

- 这段好像不够精彩
- 这里气氛一般
- 这里不够抓人
- 文风还可以更浓一点

这些判断不是没价值，但如果太早进入，会掩盖更基础的问题。

### 备选方案

- 方案 A：审查同时高权重处理成立性与表达性
- 方案 B：审查先判断成立性，再考虑表达性

### 最终选择

采用方案 B。

### 选择理由

1. 当前阶段的核心目标是系统能稳定运行
2. 若连事实、时间、角色、承诺都站不住，再谈表达优化没有意义
3. 成立性问题更适合对象化、建单、修复和统计
4. 表达性问题更适合在系统后期、或独立层中处理

### 影响范围

- [07_review_rules.md](d:\Desktop\novel\docs\03_rules\07_review_rules.md)
- [08_failure_types.md](d:\Desktop\novel\docs\03_rules\08_failure_types.md)
- 所有 review 结论口径

### 风险 / 待验证项

- 后续当表达层 workflow 出现时，需要重新定义成立性审查和表达性审查的协作关系

### 后续动作

`keep`

---

## 4. DEC-20260326-41

### 决策标题

审查结论采用三段式：通过 / 通过但有警告 / 失败。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

审查结果最简单可以做成二段式：

- 通过
- 不通过

但在实际运行中，很多结果并不适合落到这两个极端之一。

### 备选方案

- 方案 A：二段式结论（通过 / 失败）
- 方案 B：三段式结论（通过 / 通过但有警告 / 失败）

### 最终选择

采用方案 B。

### 选择理由

1. 大量健康推进其实是“当前可放行，但短期必须补偿”
2. 如果只用二段式，会把很多可推进结果错误打回，或者把很多需要注意的问题直接吞掉
3. 三段式更符合小说连续生成的实际状态：现在没坏，但再不处理就会坏

### 影响范围

- `Review Workflow`
- 示例层的审查样例
- 实验层的结论模板

### 风险 / 待验证项

- 三段式内部的 warning 判定阈值仍需更多样例压实

### 后续动作

`keep`

---

## 5. DEC-20260326-42

### 决策标题

warning 与正式 issue 严格分层，不自动等价。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

审查中会发现很多“有风险但还没坏”的点。它们是否应当立刻成为正式 `ReviewIssue`，需要明确。

### 备选方案

- 方案 A：所有 warning 都建 issue
- 方案 B：warning 与正式 issue 分层管理

### 最终选择

采用方案 B。

### 选择理由

warning 表示：

- 当前未正式失真
- 但短期内必须补偿或继续观察
- 不一定阻断
- 可以只写入 `review_notes` 或 `ReviewReminder`

正式 issue 表示：

- 当前已经违反规则
- 已构成可定位、可修复、可关闭的问题对象
- 需要排序和后续动作

这样分层的原因是：

1. warning 的任务是提前预警，不是扩大问题单池
2. issue 的任务是形成修复闭环，不是记录所有担忧
3. 如果 warning 全部建单，系统很快会失去问题优先级感

### 影响范围

- [08_reviewissue_schema.md](d:\Desktop\novel\docs\02_data_models\08_reviewissue_schema.md)
- [02_review_workflow.md](d:\Desktop\novel\docs\04_workflows\02_review_workflow.md)
- [04_rewrite_workflow.md](d:\Desktop\novel\docs\04_workflows\04_rewrite_workflow.md)

### 风险 / 待验证项

- `ReviewReminder` 已作为轻量正式层建立，但 reminder 建立阈值仍需继续压实

### 后续动作

`keep`

---

## 6. DEC-20260326-43

### 决策标题

硬错误默认阻断，结构性问题条件阻断，表达性问题通常不阻断。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

不同失败类型的危险程度不同。如果全部一刀切，系统不是过度保守，就是过度松散。

### 备选方案

- 方案 A：所有正式问题一律阻断
- 方案 B：按问题层级决定阻断强度

### 最终选择

采用方案 B。

### 选择理由

当前阻断分层如下：

默认阻断：

- `fact_conflict`
- `world_violation`
- `timeline_error`

条件性阻断：

- `information_leak`
- `character_distortion`
- `abrupt_payoff`
- `promise_loss`（核心线程时）

通常不阻断：

- `redundancy`
- `style_drift`
- 一般性 `missing_consequence`
- 轻量 `weak_progression`

这样做的原因是：

1. 硬错误会直接污染后续所有对象
2. 结构性问题要看影响范围和严重度
3. 表达性问题更多影响读感，不总是值得中断主流程

### 影响范围

- [08_failure_types.md](d:\Desktop\novel\docs\03_rules\08_failure_types.md)
- `Review Workflow`
- Rewrite / Replan 分流

### 风险 / 待验证项

- 某些结构性问题的阻断阈值仍需更多连续案例压实

### 后续动作

`watch`

---

## 7. DEC-20260326-44

### 决策标题

允许带警告放行，但 warning 必须有近程处理窗口。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

既然允许“通过但有警告”，就必须解决另一个问题：

- 警告能挂多久
- 挂着不处理算不算问题

### 备选方案

- 方案 A：warning 只作为提醒，不设明确处理窗口
- 方案 B：warning 必须绑定近程处理窗口

### 最终选择

采用方案 B。

### 选择理由

warning 应尽量带上：

- 未来 1 到 3 个 `PlotUnit`
- 或一个明确阶段窗口

也就是要求系统知道：

- 最迟什么时候要兑现
- 最迟什么时候要推进
- 最迟什么时候要补桥

没有窗口的 warning 最容易永久悬挂，最终会污染审查、混淆 issue，并让 workflow 失去紧迫性。

### 影响范围

- `Review Workflow`
- 实验层的观察模板
- `ReviewReminder` 的具体窗口模板

### 风险 / 待验证项

- 1 到 3 个 `PlotUnit` 的窗口是否普适，后续仍需按问题类型细化

### 后续动作

`watch`

---

## 8. DEC-20260326-45

### 决策标题

warning 若跨过处理窗口仍未处理，应升级为正式问题。

### 决策类型

`review`

### 决策状态

`provisional`

### 背景问题

warning 如果长期不兑现，就会从风险变成问题。但何时升级，当前仍需要规则化。

### 备选方案

- 方案 A：warning 永远不自动升级
- 方案 B：warning 超过窗口后应升级为 issue

### 最终选择

采用方案 B，但目前保持 `provisional`，需要实验继续压阈值。

### 选择理由

当前建议升级逻辑是：

1. 近程后果 1 到 2 个 `PlotUnit` 内完全未体现
2. 关键关系桥接 2 到 3 个 `PlotUnit` 内完全未补
3. 核心承诺线超过一个合理窗口仍无推进
4. 已被多次复查提醒却无动作

之所以采用这一方向，是因为：

1. 不升级，warning 就会沦为摆设
2. 升级太快，又会导致 system 过度焦虑
3. 所以阈值需要实验层逐步压实

### 影响范围

- `Review Workflow`
- `06_experiments/`
- 不同 `ReviewReminder` 类型的升级阈值设计

### 风险 / 待验证项

- 不同 warning 类型可能需要不同升级阈值

### 后续动作

`re-evaluate`

---

## 9. DEC-20260326-46

### 决策标题

issue 数量应受控，优先提高单条 issue 的信号质量。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

很多审查系统的问题不是发现太少，而是发现太多但都不重要。

### 备选方案

- 方案 A：尽量多抓问题，宁可错报
- 方案 B：控制 issue 数量，优先保证每条 issue 都有较强信号价值

### 最终选择

采用方案 B。

### 选择理由

1. 当前项目只有作者和 AI，不适合维护巨量问题池
2. issue 的价值在于可定位、可排序、可修
3. 如果 issue 泛滥，真正高优先问题反而会被淹没

当前口径是：

- 轻量局部提醒 → 优先 `review_notes`
- 中度风险 → warning
- 正式失真 → issue
- 阻断性错误 → 高优先 issue

### 影响范围

- `Review Workflow`
- `ReviewIssue Schema`
- 决策层整体审查节奏

### 风险 / 待验证项

- 过度收缩 issue 数量也可能掩盖系统性问题，需要靠实验层补平衡

### 后续动作

`keep`

---

## 10. DEC-20260326-47

### 决策标题

审查结果必须驱动明确分流，不允许“审完了但不知道下一步做什么”。

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

很多系统的审查只是输出结论，却不负责分流。这会导致看到了问题，但 workflow 不知道该往哪走。

### 备选方案

- 方案 A：审查只输出判断，不输出动作建议
- 方案 B：审查必须输出分流动作

### 最终选择

采用方案 B。

### 选择理由

当前分流口径如下：

- 通过 → 进入下一轮 `Continue`
- 通过但有警告 → 带约束进入下一轮 `Continue`
- 失败（局部） → 进入 `Rewrite`
- 失败（结构性） → 升级为 `Replan`

这样做的原因是：

1. 审查的真正价值不只是“看见”
2. 而是“决定下一步要怎么处理”
3. 没有分流，审查只是评论，不是 workflow 节点

### 影响范围

- [02_review_workflow.md](d:\Desktop\novel\docs\04_workflows\02_review_workflow.md)
- [03_continue_workflow.md](d:\Desktop\novel\docs\04_workflows\03_continue_workflow.md)
- [04_rewrite_workflow.md](d:\Desktop\novel\docs\04_workflows\04_rewrite_workflow.md)

### 风险 / 待验证项

- 仍需通过实验验证：当前 `ReviewReminder` 与 low severity issue 的边界阈值

### 后续动作

`keep`

---

## 11. 当前审查策略的总原则

基于以上决策，当前建议统一遵守以下原则：

1. 先判断成立，再判断质量
2. warning 与 issue 分层
3. 阻断分层
4. warning 必须有窗口
5. 审查必须推动 workflow

---

## 12. 当前最值得继续实验验证的审查策略问题

虽然主策略已定，但以下问题仍需后续实验继续压实：

### 12.1 warning 升级阈值

需要更多连续运行样例验证 1、2、3 个单元哪个阈值更稳。

### 12.2 结构性问题的阻断条件

例如 `promise_loss` 到什么程度必须立刻阻断。

### 12.3 低优先 issue 是否值得长期保留

需要验证 `ReviewReminder` 与 low severity issue 的边界。

### 12.4 Review 的节奏是否会过于频繁

需要在实验层观察当前 per-`PlotUnit` 审查是否足够高效。

---

## 13. 后续动作建议

这个文件写完后，下一步最自然的是补：

`07_decisions/07_experiment_strategy_decisions.md`

重点收束：

- 实验应该如何分批展开
- 哪些实验优先
- 什么叫“结构验证”通过
- 什么时候从 mock case 验证转向泛化验证

这样决策层就会从基础、边界、顺序、粒度、示例策略、审查策略，继续推进到实验推进策略本身。

---

## 14. 一句话总结

`06_review_strategy_decisions.md` 的作用，是把这套系统里“审查怎么看、warning 怎么挂、issue 怎么建、什么时候放行、什么时候返工”的关键口径固定下来，避免后面把审查做成要么什么都拦、要么什么都放的失衡阀门。
