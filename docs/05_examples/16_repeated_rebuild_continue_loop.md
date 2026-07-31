# 示例：Repeated Rebuild / Continue Loop 压测

## 文档目的

本文档提供一个 repeated `degradation -> rebuild -> review -> continue` 长链样例，用于验证：

- `FactLedger` admission threshold 在多轮恢复后是否仍稳定
- `Rebuild` 是否会丢失已成立的 knowledge / relation / situation fact
- `Continue` 是否会在恢复后把已成立状态误写回未成立状态

它验证的不是：

- 单次 `Rebuild` 能不能工作

它验证的是：

- repeated loop 下的 threshold stability

本文档主要对应：

- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`

---

## 1. 测试定位

前面的样例已经覆盖了：

- 单次跨 arc 的 `Rebuild` 恢复
- knowledge / relation admission threshold
- situation change admission threshold

但还缺一个更接近真实 harness 运行的场景：

- 系统不是只退化一次
- 而是在多轮 `Continue` 之后再次退化
- 每次恢复都必须继续尊重前面已成立的入账结果

如果这层不压，系统很容易出现三种坏结果：

1. 第一次 `Rebuild` 能恢复，第二次开始丢账
2. 已入账事实在后续 `Continue` 中被写回“只是当前压力”
3. handoff 里保留了 prose 摘要，但 object-level constraint 没真正被继承

---

## 2. 测试前提

沿用当前 mock case，并假设当前链路已经发生过一次恢复后的继续运行。

已成立的关键约束如下：

```text
FactLedger
- f_022: c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

当前系统不是从“纯净工作集”继续，而是从：

- 一次 `Rebuild`
- 一次保守 `Review`
- 若干次受约束 `Continue`

之后再次进入 bounded-package 不足状态。

---

## 3. Loop 1：第一次退化与恢复

### 3.1 退化前的正确状态

在第一次退化前，系统已经明确知道：

- `c002` 的隐瞒动作已是硬事实
- 临时同盟已是关系事实
- 东侧外环封锁已是地点状态事实
- 主任务已转入强制撤离

### 3.2 第一次退化

bounded package 丢失后，系统只剩：

- 最近 2 到 3 个 `PlotUnit`
- 部分 `NarrativeState`
- 压缩后的 handoff prose

但较完整的 `FactLedger` 仍可读。

### 3.3 第一次 `Rebuild` 的正确结果

此时 `Rebuild` 应恢复出：

- 当前不可再按潜离逻辑运行
- 东侧路线不可直接使用
- `c001 / c002` 已不是单纯试探关系

也就是说，第一次 `Rebuild` 不应把以下内容降级回运行态：

- `f_022`
- `f_023`
- `f_031`
- `f_032`

---

## 4. Loop 1 后的 `Continue`

### 4.1 正确继续

第一次恢复后的 `Continue` 可以继续生成：

- 新的撤离路径尝试
- 新的 consequence pressure
- 新的局部知情分布

但它必须把以下内容当作已成立输入读取：

- 封锁已成立
- 强制撤离任务已成立
- 同盟关系已成立

### 4.2 不应出现的错误

错误写法 A：

- 把东侧外环重新写成“也许还能试一试”

错误写法 B：

- 把 `c001 / c002` 又写回“仅仅处于试探与犹疑”

错误写法 C：

- 把 `c002` 的隐瞒动作重新降级成“似乎暂时没有揭发”

这些都说明：

- admission threshold 在恢复后没有被稳定继承

---

## 5. Loop 2：再次退化

### 5.1 新一轮推进后的新变化

在第一次恢复后的若干个 `Continue` 中，又发生了两类新变化：

1. `c001` 的撤离资格被正式剥夺
2. 西侧水路尚未封锁，但危险显著上升

这里两者不应被同样处理。

### 5.2 正确入账差异

第一类变化：

- “资格被正式剥夺”

应进入 `FactLedger`，因为它已改变 authority / legality。

第二类变化：

- “水路危险显著上升”

默认先留在 `NarrativeState`，因为它仍是 tactical pressure，而不是正式 world-state change。

### 5.3 第二次退化后的风险

如果系统第二次退化后只剩压缩包，它最容易犯的错误就是：

- 把“资格被正式剥夺”和“水路更危险了”都当成同一种局势变化

这会导致：

- 一个应保留为硬事实
- 一个只该保留为当前工作面

的边界被抹平。

---

## 6. 第二次 `Rebuild` 的正确结果

第二次 `Rebuild` 后，系统至少应恢复出如下分层：

### 6.1 仍必须保留为 `FactLedger` 的

- 已成立的隐瞒事实
- 已成立的临时同盟
- 已成立的封锁状态
- 已成立的强制撤离任务状态
- 已成立的资格剥夺状态

### 6.2 只应恢复为当前运行态的

- 当前西侧水路压力升高
- 当前追捕距离缩短
- 当前最优路径需要临时换线

### 6.3 如果恢复错了，会说明什么

如果第二次 `Rebuild` 把两类变化都压成一层，说明：

- handoff contract 不足以支撑 repeated loop
- 或 `FactLedger admission threshold` 在长链中并不稳定

---

## 7. 当前最小 handoff 要求

这个样例同时验证：如果要支撑 repeated loop，handoff 里至少要保住以下内容。

### 7.1 对已入账事实

handoff 必须明确：

- 哪些 `FactLedger.fact_id` 仍是当前高约束事实
- 它们约束的是 knowledge / relation / situation 的哪一层

### 7.2 对当前工作面

handoff 必须明确：

- 当前哪些压力只是运行态
- 哪些只是 route choice，而不是 world-state change

### 7.3 对不确定性

handoff 必须明确：

- 当前缺口是什么
- 缺的是工作面，还是缺的是硬事实

如果这三层不分开，第二次以后很容易混账。

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. repeated `Rebuild` 不应把已成立事实不断降级
2. `Continue` 不应在恢复后把硬事实写回局部判断
3. situation change 的 admission threshold 在 repeated loop 中仍应成立
4. handoff package 必须区分 hard facts 与 current pressures
5. 单次成功恢复不等于长链稳定恢复

---

## 9. 一句话总结

真正的 harness 稳定性，不是单次 `Rebuild` 能恢复，而是 repeated `Rebuild / Continue` 后仍不把硬事实写回临时状态。
