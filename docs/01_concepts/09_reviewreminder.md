# ReviewReminder

## 文档目的
定义轻量审查对象 `ReviewReminder`，明确它在自动小说系统中的作用、边界、核心字段和生命周期。

---

## 1. 它是什么

`ReviewReminder` 是系统在审查过程中生成的**非阻断、近程、可跟踪的风险提醒对象**。

它用于承载这类判断：

- 当前还没正式失败
- 但短期内必须补偿、兑现或继续观察
- 这个提醒不能只停留在一条 prose 备注里

可以把它理解为：

- warning 的正式承载对象
- 审查到续写/复审之间的轻量交接件
- `review_notes` 和 `ReviewIssue` 之间的中间层

---

## 2. 它不是什么

`ReviewReminder` 不是：

- 第九个核心叙事对象
- 正式 `ReviewIssue`
- 任意读后感
- 长期挂起的问题池
- 用来替代 `FactLedger`、`NarrativeState` 或 `ForeshadowGraph` 的记忆层

它也不负责：

- 记录已经成立的硬错误
- 管理长期结构性失败
- 存放没有处理窗口的泛化担忧

---

## 3. 它解决什么问题

`ReviewReminder` 主要解决三个实际缺口。

### 3.1 让 warning 不再只漂在 prose 里

如果 warning 只写在 `review_notes` 里，后续 workflow 很容易漏读、漏跟踪、漏升级。

### 3.2 让 `Continue` 知道什么必须优先补偿

`Continue` 不该只读当前状态，还应读到：

- 哪些近程后果必须兑现
- 哪些关系桥接必须补
- 哪些风险窗口即将到期

### 3.3 让 warning 到 issue 的升级有承载层

如果没有独立对象，warning 升级为 `ReviewIssue` 时就会失去：

- 来源
- 窗口
- 升级触发条件
- 已观察轮次

---

## 4. 核心定义

### 定义

`ReviewReminder` 是一个用于记录近程 warning 的结构化对象，包含提醒类型、来源对象、补偿窗口、升级规则和当前状态。

### 一句话理解

它定义“这还没坏，但最迟什么时候必须处理，否则就会坏”。

---

## 5. 它与其他对象的关系

推荐关系如下：

`ReviewReminder`
← 由 `Review Workflow` 生成

`ReviewReminder`
→ 被 `Continue` 读取
→ 被下一轮 `Review` 复查
→ 必要时被 `Rewrite` 关闭或转化
→ 超过窗口时升级为 `ReviewIssue`

### 与 `review_notes` 的区别

`review_notes` 负责：

- 当前单元的局部备注
- 不一定跨轮追踪的轻提示

`ReviewReminder` 负责：

- 需要跨 workflow handoff 的 warning
- 带窗口的近程约束
- 需要后续复查和升级判断的提醒

### 与 `ReviewIssue` 的区别

`ReviewReminder` 表示：

- 当前未正式违反规则
- 当前默认不阻断
- 但若不处理将升级

`ReviewIssue` 表示：

- 当前已经违反规则或已经污染结构
- 已进入正式修复链
- 需要排序、修复、关闭

---

## 6. 设计原则

### 6.1 近程性

每个 `ReviewReminder` 都应有明确处理窗口。

没有窗口的 reminder 不应建立。

### 6.2 非阻断默认

`ReviewReminder` 默认不是阻断对象。

如果已经需要阻断，通常应直接升级为正式 `ReviewIssue`。

### 6.3 可升级

每个 reminder 都应能回答：

- 何时算已补偿
- 何时应升级
- 升级成哪类 `ReviewIssue`

### 6.4 数量受控

它不是问题池的低配副本。

同一轮审查只应保留少量高信号 reminder。

### 6.5 不替代主存

它只能提醒对象层需要兑现什么，不能替对象层存放长期状态。

---

## 7. 建议包含的层

第一版建议把 `ReviewReminder` 分成 5 层。

### 7.1 类型层

用于说明当前 warning 属于哪一类近程风险。

例如：

- `missing_consequence`
- `missing_cost`
- `relationship_bridge_needed`
- `promise_followup_needed`

### 7.2 来源层

用于说明 reminder 来自哪里。

例如：

- 哪次 review 生成
- 对应哪个 `PlotUnit`
- 主要指向哪个对象

### 7.3 窗口层

用于说明它最迟什么时候必须处理。

例如：

- 后续 1 到 2 个 `PlotUnit`
- 当前 chapter 结束前
- 当前局部段落切换前

### 7.4 升级层

用于说明 reminder 在什么条件下转为正式问题。

例如：

- 连续 2 次复审仍未补偿
- 已开始污染主线或知识边界
- 同类 reminder 重复叠加

### 7.5 生命周期层

用于说明 reminder 当前处于什么状态。

例如：

- `active`
- `compensated`
- `escalated`
- `dismissed`

---

## 8. 生命周期建议

建议采用以下最小生命周期：

```text
active
  ↓
compensated / escalated / dismissed
```

### active

当前仍需跟踪。

### compensated

后续推进已经兑现该 reminder 的核心要求。

### escalated

已转成正式 `ReviewIssue`。

### dismissed

判定为误报、已失效，或无需继续跟踪。

---

## 9. 什么时候应该建立它

建议满足以下特征时建立 `ReviewReminder`：

- 当前尚未正式失败
- 风险在近程内必须处理
- 不能只靠一条 `review_notes` 保证后续 workflow 读到
- 未来确实存在升级为正式问题的可能

---

## 10. 什么时候不该建立它

以下情况通常不应建立 `ReviewReminder`：

- 只是一次性的局部备注
- 纯风格喜好
- 已经构成正式规则违背
- 没有明确补偿窗口
- 没有明确来源对象

---

## 11. 小例子

### 例 1：适合 reminder

`scene_014` 已建立旧伤后果和追踪压力，但后续 1 到 2 个 `PlotUnit` 内仍需兑现至少一项。

这时：

- 不必立刻建 `ReviewIssue`
- 但应生成一个 `ReviewReminder`

### 例 2：不适合 reminder

`c002` 在未获知信息时直接做出正确判断，已经构成信息越界。

这时：

- 不应只挂 reminder
- 应直接生成正式 `ReviewIssue`

---

## 12. 一句话总结

`ReviewReminder` 的任务，是把“还没坏，但很快会坏”的 warning 变成一个能跨 workflow 传递、复查和升级的轻量正式对象。
