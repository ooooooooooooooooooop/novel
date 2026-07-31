# 示例：同 Family Reminder 合并压测

## 文档目的

本文档提供一个同 family `ReviewReminder` 的边界样例，用于验证：

- 同 family reminder 是否可以直接视为一条风险
- 什么情况下只能做 grouped handoff，而不能做 true merge
- 合并判断是否会因为同类型而错误抹平不同来源、不同窗口、不同补偿动作

它验证的不是 reminder family 本身是否合理。
它验证的是：

**当两条 reminder 都属于同一 family 时，系统是否仍能保留清晰的子风险轨迹。**

本文档主要对应：

- `07_decisions/11_reviewreminder_escalation_matrix.md`
- `07_decisions/12_concurrent_reminder_routing_decisions.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`

---

## 1. 测试定位

前一个并发 reminder 样例主要验证的是：

- 不同 family reminder 可以并存
- 系统需要有优先级
- 单条 reminder 可以独立关闭、保留或升级

但它还没有压到一个更细的边界：

- 两条 reminder 属于同一 family
- 但来源对象不同
- 窗口不同
- 补偿动作也不完全相同

这类情况最容易诱发一种错误简化：

- 因为“看起来都是 `missing_consequence`”，就把它们压成一条总提醒

如果这样做，系统会失去：

- 哪一条更接近升级
- 哪一条来自哪个 `PlotUnit`
- 哪一条已经进入最后补偿窗口
- 哪一条仍然只是较新的 consequence branch

---

## 2. 测试前提

沿用当前 mock case，并假设经过一次复审后，系统手头有两条同 family active reminder。

### 2.1 reminder A：旧后果链已进入最后窗口

```json
{
  "reminder_id": "rr_scene014_01",
  "reminder_type": "missing_consequence",
  "title": "scene_014 的追压后果必须在下一有效单元兑现",
  "summary": "巡查逼近、旧伤复发与保密压力已被同时激活，下一 PlotUnit 若仍无兑现，应升级。",
  "source_object_type": "PlotUnit",
  "source_object_id": "pu_scene_014",
  "plotunit_ref": "pu_scene_014",
  "review_pass_ref": "review_pass_scene015",
  "related_issue_type": "missing_consequence",
  "supporting_refs": ["f_016", "f_017", "fg_002"],
  "window_type": "plotunit_count",
  "window_value": "1",
  "window_note": "当前已是最后一个可补偿窗口。",
  "escalation_rule": "若下一有效单元仍不兑现至少一项后果，则升级为正式 missing_consequence。",
  "severity": "medium",
  "status": "active"
}
```

### 2.2 reminder B：新 consequence branch 刚被打开

```json
{
  "reminder_id": "rr_scene015_03",
  "reminder_type": "missing_consequence",
  "title": "scene_015 新建立的风险暴露需要在近程得到回应",
  "summary": "新暴露的目击者风险刚被建立，后续 2 个 PlotUnit 内应出现追踪、掩盖或成本兑现。",
  "source_object_type": "PlotUnit",
  "source_object_id": "pu_scene_015",
  "plotunit_ref": "pu_scene_015",
  "review_pass_ref": "review_pass_scene015",
  "related_issue_type": "missing_consequence",
  "supporting_refs": ["f_019", "f_020"],
  "window_type": "plotunit_count",
  "window_value": "2",
  "window_note": "这是新建立的 consequence branch，还未进入最后窗口。",
  "escalation_rule": "若 2 个有效单元后仍无追踪、掩盖或代价兑现，则升级为正式 missing_consequence。",
  "severity": "medium",
  "status": "active"
}
```

---

## 3. 当前问题：这两条 reminder 能不能真合并

结论应是：

- 不能因为它们同属 `missing_consequence` 就直接 true merge

因为它们虽然 family 相同，但仍有三处关键差异：

- 来源对象不同
- 升级距离不同
- 补偿目标不同

### 3.1 来源对象不同

reminder A 对应的是：

- `pu_scene_014` 已经建立的旧后果链

reminder B 对应的是：

- `pu_scene_015` 新打开的 consequence branch

如果直接合并，handoff 会失去：

- 到底是哪一个 scene 的后果正在被追踪

### 3.2 升级距离不同

reminder A：

- 只剩 1 个有效单元

reminder B：

- 还有 2 个有效单元

如果直接合并，系统很容易错误地：

- 把 B 也压成最后窗口
- 或把 A 的升级紧迫度错误放宽到 B 的节奏

### 3.3 补偿目标不同

reminder A 需要的是：

- 兑现旧伤、巡查、保密压力中的至少一项后果

reminder B 需要的是：

- 回应新建立的目击者风险

它们都叫 consequence，但不是同一条 consequence branch。

---

## 4. 正确处理：grouped handoff，而不是真合并

当前更合理的 first-pass 做法是：

- 允许 grouped handoff
- 不允许丢失子 reminder

也就是说，可以在 handoff 摘要里写成：

- 当前存在两条 `missing_consequence` active reminder，需要按最短窗口优先处理

但底层仍必须保留：

- `rr_scene014_01`
- `rr_scene015_03`

### 4.1 grouped handoff 可以做什么

它可以：

- 帮助 `Continue` 快速看见“当前 consequence 类风险不止一条”
- 提醒优先看最短窗口
- 降低 handoff prose 的冗长度

### 4.2 grouped handoff 不能做什么

它不能：

- 抹掉 child reminder 的来源
- 抹掉 child reminder 的窗口差异
- 抹掉 child reminder 的独立升级轨迹

---

## 5. 第一种正确结果：先补 A，保留 B

### 5.1 新单元结果

生成 `pu_scene_016`，其中：

- 巡查压力正式落地
- `c001` 为掩盖旧伤暴露付出即时代价
- 但新目击者风险还没有得到后续回应

### 5.2 正确处理

此时应：

- 关闭 `rr_scene014_01`
- 保留 `rr_scene015_03`

这验证了：

- 同 family reminder 不应整组自动关闭

---

## 6. 第二种错误结果：为了 grouped handoff，误把 B 也压成最后窗口

### 6.1 错误做法

系统把两条 reminder 聚合成一句：

- “下一单元必须处理 consequence，否则升级”

结果在执行时默认认为两条 reminder 都已进入最后窗口。

### 6.2 错误后果

这会导致：

- B 的升级被人为提前
- 新 consequence branch 失去本来允许的近程缓冲

正确结论应是：

- grouped handoff 可以共享摘要
- 但窗口必须仍按 child reminder 单独计算

---

## 7. 第三种错误结果：为了保留新 branch，反而稀释 A 的紧迫度

### 7.1 错误做法

系统因为看到还有一条 `window_value = 2` 的同 family reminder，就把整体 consequence 类风险理解成：

- “还有两步空间，可以稍后再补”

### 7.2 错误后果

这会导致：

- A 被错误延迟
- 已经进入最后窗口的旧后果链被拖过阈值

正确结论应是：

- grouped handoff 的默认优先级应继承最短窗口，而不是平均窗口

---

## 8. 当前 first-pass 规则

基于这个样例，当前至少可以收束出以下 first-pass 规则。

### 8.1 同 family 不等于 true merge

即使：

- `reminder_type` 相同
- `related_issue_type` 相同

只要以下任一条件成立，仍应保留为独立 child reminder：

- `source_object_id` 不同
- `window_value` 不同
- 补偿目标不是同一条 consequence branch

### 8.2 grouped handoff 可以共享摘要，但不能共享升级轨迹

handoff 层可以写一条 grouped summary。

但运行层仍必须保留：

- 每条 child reminder 的来源
- 每条 child reminder 的窗口
- 每条 child reminder 的关闭或升级状态

### 8.3 默认优先级继承最短窗口

当同 family reminder 允许 grouped handoff 时，默认优先级应：

- 先看最短窗口的 child reminder

而不是：

- 取平均窗口
- 以最新 reminder 为准

---

## 9. 这份样例验证了什么

这份样例主要验证四件事：

1. 同 family reminder 仍可能不是同一条风险
2. grouped handoff 与 true merge 是两件不同的事
3. child reminder 的窗口与来源不能在摘要层被抹平
4. reminder 共享 family 时，默认优先级仍要受最短窗口约束

---

## 10. 一句话总结

同 family reminder 可以共享 handoff 视图，但不能因此丢失各自的来源、窗口和独立升级轨迹。
