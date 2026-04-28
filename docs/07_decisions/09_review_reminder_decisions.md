# 审查提醒层决策

## 文档目的
本文件用于收束 `warning / reminder` 轻量正式层的设计决策。

它关注的不是 warning 怎么写得更像自然语言，而是：

- warning 与 `ReviewIssue` 的边界到底怎么落
- 是否需要独立的轻量对象层
- 什么时候只写 `review_notes`
- 什么时候必须建立 reminder
- reminder 如何升级为正式问题

---

## 1. 文档定位

本文件是在以下文档基础上的补强：

- `02_model_boundary_decisions.md`
- `06_review_strategy_decisions.md`
- `08_context_packaging_decisions.md`

它主要影响：

- `01_concepts/09_reviewreminder.md`
- `02_data_models/10_reviewreminder_schema.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `05_examples/06_sample_review.md`

---

## 2. 当前需要固定的问题

当前最值得固定的提醒层问题主要有 4 个：

1. warning 是判断，还是对象
2. 是否应建立独立 reminder 层
3. reminder 与 `review_notes` 如何分工
4. reminder 升级为 `ReviewIssue` 的最小规则是什么

---

## 3. DEC-20260326-61

### 决策标题

warning 是审查判断层，`ReviewReminder` 是 warning 的轻量承载对象。

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

过去文档中常把 warning、reminder、`review_notes` 混着说，导致：

- 有时 warning 只是结论标签
- 有时 warning 又像一个对象
- 有时 reminder 又被写成低级 issue

### 备选方案

- 方案 A：继续让 warning / reminder 混用
- 方案 B：把 warning 视为判断，把 `ReviewReminder` 视为对象

### 最终选择

采用方案 B。

### 选择理由

1. warning 本质上是审查结果的分类
2. 需要跨 workflow 传递时，分类本身不足以承载窗口和升级信息
3. 用单独对象承载，才能把 warning 与 issue 真正分开

### 影响范围

- review 结论口径
- reminder schema
- workflow handoff

### 风险 / 待验证项

- 某些极轻提醒是否只保留在 `review_notes` 里，仍需样例压实

### 后续动作

`keep`

---

## 4. DEC-20260326-62

### 决策标题

引入 `ReviewReminder`，但不把它提升为第九个核心叙事对象。

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

warning 需要正式承载层，但如果直接把 reminder 提升为核心对象，又会让系统主结构继续膨胀。

### 备选方案

- 方案 A：不建模，只保留 prose reminder
- 方案 B：建立辅助 review-layer object，但不纳入 8 个核心对象
- 方案 C：把 reminder 升级为新的核心对象

### 最终选择

采用方案 B。

### 选择理由

1. 它解决的是 review-layer handoff 问题，不是新的叙事本体问题
2. 它应服务 `Review -> Continue / Rewrite`，而不是重写主数据流
3. 这样能补职责空缺，又不破坏当前核心对象边界

### 影响范围

- `00_model_index.md`
- `Review Workflow`
- `Continue / Rewrite` 输入包

### 风险 / 待验证项

- 未来如果 reminder 层负担过重，需重新检查是否字段设计失控

### 后续动作

`keep`

---

## 5. DEC-20260326-63

### 决策标题

局部备注留在 `review_notes`，跨轮近程 warning 建立 `ReviewReminder`。

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

不是所有 warning 都值得独立成对象。

### 备选方案

- 方案 A：所有 warning 都建立 reminder
- 方案 B：只要需要跨轮交接和复查的 warning 才建立 reminder

### 最终选择

采用方案 B。

### 选择理由

`review_notes` 负责：

- 当前单元局部备注
- 不一定需要后续 workflow 追踪的轻提示

`ReviewReminder` 负责：

- 有明确补偿窗口的近程 warning
- 需要后续 `Continue` 优先读取的约束
- 需要未来复审判断是否升级的提醒

### 影响范围

- `Review Workflow`
- `PlotUnit.review_notes`
- 审查样例

### 风险 / 待验证项

- reminder 建立阈值过低，会形成新的轻量对象泛滥

### 后续动作

`watch`

---

## 6. DEC-20260326-64

### 决策标题

`ReviewReminder` 必须带处理窗口与升级目标，超过窗口后转为正式 `ReviewIssue`。

### 决策类型

`review`

### 决策状态

`provisional`

### 背景问题

如果 reminder 没有窗口和升级目标，它仍然会沦为更结构化的 prose。

### 备选方案

- 方案 A：reminder 只记录提醒，不强制窗口和升级目标
- 方案 B：reminder 建立时就写明窗口和升级目标

### 最终选择

采用方案 B，但保留 `provisional`，因为不同 reminder 类型的窗口阈值仍需实验压实。

### 选择理由

1. 没有窗口，就无法判断何时该复查
2. 没有升级目标，就无法稳定进入正式修复链
3. 这正是 reminder 层和普通 `review_notes` 的核心差异

### 当前最小口径

- 默认写明处理窗口
- 默认写明升级目标 issue type
- 连续两次复审未补偿，或已开始污染对象层时，应升级

### 影响范围

- `10_reviewreminder_schema.md`
- `Review Workflow`
- experiment 压测设计

### 风险 / 待验证项

- 不同 reminder 类型可能需要不同窗口长度

### 后续动作

`re-evaluate`

---

## 7. 一句话总结

`09_review_reminder_decisions.md` 固定了当前项目对 warning 层的正式口径：warning 是判断，`ReviewReminder` 是轻量对象，只有正式失败才进入 `ReviewIssue`。
