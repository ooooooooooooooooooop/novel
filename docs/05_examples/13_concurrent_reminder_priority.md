# 示例：并发 ReviewReminder 优先级压测

## 文档目的

本文件提供一个多 `active ReviewReminder` 并发样例，用于验证：

- 同时存在多个 active reminder 时
- 系统如何判断哪些可以并存
- 哪些不应简单合并
- 下一轮 `Continue` 应优先补偿哪一个
- 何时从“多个 reminder 并存”升级为更正式的修复动作

它验证的不是单条 reminder 的窗口设计。

它验证的是：

**当 reminder 不再只有一条时，review-layer handoff 是否仍然清楚。**

本文件主要对应：

- `07_decisions/11_reviewreminder_escalation_matrix.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`

---

## 1. 测试定位

前面的样例已经验证了：

- 单条 reminder 的创建、复查与升级
- reminder 与 formal issue 的并存分流

但还缺一类更接近真实运行的情况：

- 当前没有 formal issue
- 但手里同时挂着两到三条 active reminder
- 下一步只能优先补其中一部分

这类情况下最容易出现三种坏结果：

1. reminder 被粗暴合并，丢失真正的来源差异
2. reminder 数量一多，`Continue` 不知道先补什么
3. 某条更高风险 reminder 被其他低风险 reminder 稀释

---

## 2. 测试前提

沿用当前 mock case：

- `scene_014` 已建立强推进
- `scene_015` 尚未正式失败
- 当前仍处于“可继续，但必须带约束”的状态

假设经过一次复审后，系统手头同时有以下两条 active reminder。

### 2.1 reminder A：后果兑现

```json id="exrr13a"
{
  "reminder_id": "rr_scene014_01",
  "reminder_type": "missing_consequence",
  "title": "scene_014 的后果需在近程兑现",
  "summary": "旧伤、追踪与保密压力已被激活，后续 1 个 PlotUnit 内必须兑现至少一项。",
  "source_object_type": "PlotUnit",
  "source_object_id": "pu_scene_014",
  "plotunit_ref": "pu_scene_014",
  "review_pass_ref": "review_pass_scene015",
  "related_issue_type": "missing_consequence",
  "supporting_refs": ["f_016", "f_017", "fg_002"],
  "window_type": "plotunit_count",
  "window_value": "1",
  "window_note": "窗口已进入最后一轮。",
  "escalation_rule": "若下一有效单元仍不兑现至少一项后果，则升级为正式 missing_consequence。",
  "severity": "medium",
  "status": "active"
}
```

### 2.2 reminder B：关系桥接

```json id="exrr13b"
{
  "reminder_id": "rr_scene015_02",
  "reminder_type": "relationship_bridge_needed",
  "title": "c001 与 c002 的关系推进需要补桥",
  "summary": "当前互信与协作意愿正在升高，但下一单元若继续推进关系，不得跳过桥接。",
  "source_object_type": "NarrativeState",
  "source_object_id": "s_015",
  "plotunit_ref": "pu_scene_015",
  "review_pass_ref": "review_pass_scene015",
  "related_issue_type": "relationship_jump",
  "supporting_refs": ["f_018", "s_015"],
  "window_type": "plotunit_count",
  "window_value": "1",
  "window_note": "若下一单元继续升温，必须补桥。",
  "escalation_rule": "若下一有效单元直接进入更高信任或明确联盟而无桥接，则升级为正式 relationship_jump。",
  "severity": "medium",
  "status": "active"
}
```

---

## 3. 当前问题：这两条 reminder 能不能合并

结论应是：

- 不能简单合并成一条“大致注意后果和关系”

因为两者虽然都来自同一局部链路，但它们的：

- 来源对象不同
- 升级目标不同
- 补偿动作不同
- 危险方式不同

### 3.1 reminder A 的本质

它要求：

- 兑现已建立后果

如果不处理，会滑向：

- `missing_consequence`

### 3.2 reminder B 的本质

它要求：

- 若要继续推进关系，必须补桥

如果不处理，会滑向：

- `relationship_jump`

### 3.3 正确的并存原则

当 reminder 的：

- `related_issue_type`
- `source_object_type`
- `compensation action`

明显不同，就不应强行合并。

---

## 4. 下一轮 Continue 应先补哪条

这一步是本样例最关键的问题。

### 4.1 当前正确优先级

推荐优先级应是：

1. `rr_scene014_01 / missing_consequence`
2. `rr_scene015_02 / relationship_bridge_needed`

### 4.2 原因

因为 reminder A：

- 窗口已经耗到最后一轮
- 一旦继续拖延，会 retroactively 削弱已成立强推进
- 不处理时更接近结构性后果链断裂

而 reminder B：

- 只在“下一单元继续升高关系”时才会立刻触发
- 如果下一单元暂不推进关系，它仍可能继续保持为 active，但不立即爆炸

### 4.3 当前最合理的 Continue 策略

下一单元应优先选择：

- 兑现旧伤、追踪或保密压力中的至少一项

并且：

- 暂不让 `c001 / c002` 的关系再跨一个阶段

这意味着：

- `Continue` 不必一次性关闭所有 reminder
- 但应先处理最接近升级边缘、且对结构伤害更直接的一条

---

## 5. 第一种正确结果：先补 A，保留 B

### 5.1 新单元结果

生成 `pu_scene_016 / 夜林追压`，其中：

- 巡查队逼近
- `c001` 旧伤发作
- `c002` 被迫临时掩护撤离
- 但两人关系并未继续明显升温

### 5.2 正确处理

此时应：

- 关闭 `rr_scene014_01`
- 保留 `rr_scene015_02`

### 5.3 为什么 B 仍应保留

因为：

- 当前关系线危险并没有自动消失
- 只是这一单元没有继续推进关系，所以暂未触发升级

这说明 reminder 并发时，允许出现：

- 一条被补偿关闭
- 一条继续 active

而不是要求整组同时关闭。

---

## 6. 第二种错误结果：为了补 A，顺手把 B 写坏

### 6.1 错误续写

生成 `pu_scene_016 / 夜林追压` 时，为了表现 `c002` 的掩护动作，文本直接写成：

- `c001` 立即彻底交出秘密
- 两人默认形成稳定互信

### 6.2 正确审查结论

这时系统不应说：

- “反正 reminder A 已补了，所以整体通过”

而应判断：

- reminder A 被补偿
- reminder B 被踩爆，升级为正式 `relationship_jump`

也就是说，多 reminder 并发时，补偿一条并不抵消另一条被正式踩坏。

---

## 7. 第三种错误结果：低优先级 reminder 反向抢占

### 7.1 错误继续策略

下一轮系统把全部注意力放在“关系补桥”上，写了大量试探、停顿、眼神与犹豫。

结果：

- `rr_scene015_02` 被温和补桥
- 但 `rr_scene014_01` 所要求的旧伤、追踪、保密后果仍完全没兑现

### 7.2 正确审查结论

此时不应因为“有一条 reminder 被补了”就给整体放行。

而应判断：

- `rr_scene015_02` 可关闭
- `rr_scene014_01` 因窗口耗尽而升级为正式 `missing_consequence`

### 7.3 这一步验证什么

它验证：

- reminder 的关闭不应按数量统计
- 而应按每条 reminder 的独立风险轨迹判断

---

## 8. 当前 first-pass 并发规则

基于这个样例，当前至少可得到以下 first-pass 规则。

### 8.1 并发不等于合并

只有当多条 reminder 同时满足以下条件时，才建议考虑合并：

- `reminder_type` 相同
- `related_issue_type` 相同
- `source_object_type` 接近
- 补偿动作本质相同

否则应保留为独立 reminder。

### 8.2 优先级先看升级迫近度，再看结构伤害

默认优先看：

1. 谁的窗口更接近耗尽
2. 谁一旦失守更容易伤害已成立强推进或主线结构
3. 谁是否依赖下一单元的特定动作才会触发

### 8.3 单条关闭不代表整组关闭

一轮 `Continue` 可以：

- 关闭一条
- 保留一条
- 升级一条

这是正常结果，不应被视为流程不整齐。

### 8.4 formal issue 的出现优先于 reminder 数量感受

无论当前还有几条 active reminder，只要其中一条已被踩爆成正式失败，就应按 issue 路由，而不是继续把整轮理解为“只是 warning 多了一点”。

---

## 9. 这份样例验证了什么

这份样例主要验证五件事：

1. reminder 并发时，系统不会粗暴合并不同风险
2. `Continue` 可以有优先补偿顺序
3. 并发 reminder 允许分别关闭、保留、升级
4. 某条 reminder 被补偿，不会自动替其他 reminder 洗白
5. 多 reminder 问题首先是 priority / merge 问题，不等于自动 `Replan`

---

## 10. 一句话总结

并发 reminder 的关键，不是把提醒变少，而是让每条提醒在共享 handoff 中仍保有清楚的来源、优先级和独立升级轨迹。
