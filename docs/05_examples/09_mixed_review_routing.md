# 示例：ReviewReminder 与 ReviewIssue 并存分流

## 文档目的
本文件提供一个混合审查样例，用于验证以下情况能否稳定分流：

- 一个 `ReviewReminder` 仍然处于 active 状态
- 同时又出现一个新的正式 `ReviewIssue`
- 系统需要决定下一步进入 `Continue`、`Rewrite` 还是 `Replan`

它主要验证的不是单条 reminder 的升级，而是：

**当提醒层和正式问题层同时存在时，审查结果能否给出不混乱的动作路由。**

本文件对应：

- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/06_review_strategy_decisions.md`

---

## 1. 测试定位

这份样例验证的是一个很常见的中段状态：

- 系统手里已经挂着一个近程 reminder
- 新写出来的单元又真的坏了一个地方
- 但这个新问题还没有上升到 arc 级失衡

此时正确路由不应是：

- 把所有东西都当 warning 继续拖
- 也不应直接跳到 `Replan`

而应是：

- 保留仍然有效的 reminder
- 为正式失真建 `ReviewIssue`
- 进入局部 `Rewrite`

---

## 2. 测试前提

延续：

- [08_reviewreminder_chain.md](d:/Desktop/novel/docs/05_examples/08_reviewreminder_chain.md)

但这次不采用“超窗升级”的分支，而采用另一条分支：

- `rr_scene014_01` 仍在窗口内
- 新生成的 `pu_scene_015` 虽然还没处理旧伤 / 追踪 reminder
- 却额外写坏了 `c001 -> c002` 的关系节奏

也就是说：

- reminder 指向的是“后果尚未兑现”
- 新 issue 指向的是“关系跳变已发生”

这两者不是同一问题。

---

## 3. 输入状态

### 3.1 仍然活跃的 reminder

```json id="exrm09reminder"
[
  {
    "reminder_id": "rr_scene014_01",
    "reminder_type": "missing_consequence",
    "title": "scene_014 的后果需在近程兑现",
    "summary": "旧伤、追踪与保密压力已被激活，后续 2 个 PlotUnit 内必须兑现至少一项。",
    "source_object_type": "PlotUnit",
    "source_object_id": "pu_scene_014",
    "plotunit_ref": "pu_scene_014",
    "review_pass_ref": "review_pass_scene014",
    "related_issue_type": "missing_consequence",
    "supporting_refs": ["f_016", "f_017", "f_019", "fg_002"],
    "window_type": "plotunit_count",
    "window_value": "2",
    "window_note": "当前仍在近程窗口内。",
    "escalation_rule": "若两个近程单元都不兑现后果，则升级为正式 missing_consequence。",
    "severity": "low",
    "status": "active",
    "created_at": "review_pass_scene014",
    "last_updated": "review_pass_scene014",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "当前只是一条 reminder，不构成正式失败。"
  }
]
```

### 3.2 新生成但失真的 `pu_scene_015`

这次故意让 `pu_scene_015 / 雨后藏迹` 出现一个局部正式问题：

- `c001` 在一次短对话后突然决定完全信任 `c002`
- 甚至直接把撤离计划细节交给对方
- 但前序对象层并没有足够桥接

这不是“未来可能会坏”，而是“现在已经坏了”。

---

## 4. 本轮 Review 结果

### 4.1 reminder 侧判断

`rr_scene014_01` 当前仍应保留为 active，因为：

- 其窗口尚未耗尽
- reminder 指向的后果兑现问题尚未转成正式失败

### 4.2 issue 侧判断

本轮应新增一个正式 `ReviewIssue`：

- `issue_type = relationship_jump`

因为：

- 关系跳变已经发生
- 它不是等待后续补偿就能自动成立的问题
- 当前单元本身需要被修

### 4.3 推荐审查结论

推荐结论应是：

- 本轮：失败（局部）
- 分流：进入 `Rewrite`
- reminder：继续保留
- 不直接升级为 `Replan`

原因是：

- 当前正式问题是局部关系失真
- 并未出现多个 formal issue 指向同一结构层
- 当前仍属于“局部改写可修”的范围

---

## 5. 本轮生成的正式问题

```json id="exrm09issue"
[
  {
    "issue_id": "ri_scene015_relation_01",
    "issue_type": "relationship_jump",
    "title": "scene_015 中 c001 对 c002 的信任跳变过快",
    "summary": "c001 在缺少足够桥接的情况下，将撤离计划细节直接交给 c002，导致关系推进从半合作边缘跳到高信任位。",
    "object_type": "PlotUnit",
    "object_id": "pu_scene_015",
    "level": "scene",
    "plotunit_ref": "pu_scene_015",
    "chapter_ref": "chapter_06",
    "scene_ref": "scene_015",
    "violated_rule": "关系变化必须由前序互动、风险交换或明确桥接支持，不能直接跨过关键过渡段。",
    "supporting_facts": ["f_018"],
    "contradictory_facts": [],
    "missing_elements": ["relationship_bridge"],
    "evidence_note": "scene_014 只建立了高风险半合作边缘，并未建立稳定信任。",
    "impact_scope": "scene",
    "affected_characters": ["c001", "c002"],
    "affected_threads": ["fg_002"],
    "affected_states": ["s_015_scene"],
    "downstream_risk": "若不修正，后续保密线与立场试探线会失去张力。",
    "suggested_fix_type": "scene_split",
    "suggested_fix_note": "降低信任跃迁幅度，改为有限信息交换或加入明确桥接事件。",
    "rewrite_needed": true,
    "replanning_needed": false,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "non_blocking",
    "fix_order": 1,
    "status": "open",
    "created_at": "review_pass_scene015",
    "last_updated": "review_pass_scene015",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "这是局部正式失真，优先进入 Rewrite。"
  }
]
```

---

## 6. 同轮保留的 reminder

```json id="exrm09reminder_after_review"
[
  {
    "reminder_id": "rr_scene014_01",
    "reminder_type": "missing_consequence",
    "title": "scene_014 的后果需在近程兑现",
    "summary": "虽然本轮出现了新的关系跳变问题，但旧伤、追踪与保密压力的 reminder 仍未关闭。",
    "source_object_type": "PlotUnit",
    "source_object_id": "pu_scene_014",
    "plotunit_ref": "pu_scene_014",
    "review_pass_ref": "review_pass_scene015",
    "related_issue_type": "missing_consequence",
    "supporting_refs": ["pu_scene_014", "pu_scene_015", "f_016", "f_017", "fg_002"],
    "window_type": "plotunit_count",
    "window_value": "1",
    "window_note": "Rewrite 后仍需继续处理该 reminder。",
    "escalation_rule": "若下一有效单元仍未兑现后果，则升级为正式 missing_consequence。",
    "severity": "medium",
    "status": "active",
    "created_at": "review_pass_scene014",
    "last_updated": "review_pass_scene015",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "formal issue 的出现并不会自动关闭仍有效的 reminder。"
  }
]
```

---

## 7. 正确分流动作

### 7.1 不应怎么走

错误路径 A：

- 只因为 reminder 还没超窗，就把整个结果判成“通过但有警告”

错误原因：

- 忽略了已经成立的正式关系失真

错误路径 B：

- 因为同时有 reminder 和 issue，就直接升级到 `Replan`

错误原因：

- 当前只有一个局部 formal issue
- 尚未出现多 issue 指向同一结构弱点

### 7.2 当前正确路由

当前建议路由是：

```text
Review
  -> 保留 rr_scene014_01 为 active
  -> 生成 ri_scene015_relation_01
  -> 进入 Rewrite
  -> Rewrite 后重新进入 Review
  -> reminder 若仍未兑现，则继续保留或按窗口升级
```

---

## 8. 这个样例在验证什么

这份样例主要验证 4 件事：

### 8.1 reminder 和 issue 可以并存

它们不是互相覆盖的关系，而是职责不同。

### 8.2 formal issue 优先决定是否进入 Rewrite

只要当前已经正式失真，就不应再把整轮结果伪装成“只有 warning”。

### 8.3 active reminder 不会因为新 issue 出现而被静默吞掉

否则 `Continue` 和复审会失去对近程后果链的追踪。

### 8.4 reminder + issue 并存不等于 Replan

只有当多个 formal issue 开始共同指向结构失衡时，才应升级为 `Replan`。

---

## 9. 当前结论

如果这份样例成立，可以认为系统已经能区分三种情况：

- 只有 reminder：带约束继续推进
- reminder + 局部 issue：进入 `Rewrite`
- 多个 issue 指向同一结构失衡：升级为 `Replan`

---

## 10. 一句话总结

`09_mixed_review_routing.md` 的任务，是证明 reminder 层和正式问题层同时存在时，系统仍然能给出稳定、不夸张、不过度保守的分流动作。
