# 示例：ReviewReminder 链路压力测试

## 文档目的
本文件提供一组最小多轮样例，用于验证 `ReviewReminder` 是否真的能支撑：

- `Review` 创建 reminder
- `Continue` 读取 reminder 并决定是否补偿
- 下一轮 `Review` 复查 reminder
- 超过窗口后升级为正式 `ReviewIssue`

它不是新的概念文档，而是对现有 review-layer 设计做连续链路压力测试。

本文件对应：

- `01_concepts/09_reviewreminder.md`
- `02_data_models/10_reviewreminder_schema.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `07_decisions/09_review_reminder_decisions.md`

---

## 1. 测试定位

这份样例只验证一件事：

**一个近程 warning，能否从“提醒”稳定地走到“补偿”或“升级”。**

这里不追求：

- 多线程复杂博弈
- 大量对象变更
- 长链路世界扩展

这里只看 reminder 链路本身是否闭环。

---

## 2. 测试前提

沿用当前 mock case：

- 作品：`残雪归宗`
- 当前已审查单元：`pu_scene_014 / 雨夜夺令`
- 当前审查结论：通过但有警告

当前已知风险：

- `c001` 旧伤加重
- 巡查 / 追踪风险上升
- `c002` 已进入半知情保密压力位

这些风险还没有正式失真，但必须在近程单元内兑现至少一项。

---

## 3. 起始对象

### 3.1 起始 reminder

`Review` 在 `pu_scene_014` 后生成：

```json id="exrr08start"
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
    "window_note": "当前可放行，但不能继续空转。",
    "escalation_rule": "若后续 2 个 PlotUnit 内仍未兑现至少一项后果，则升级为正式 missing_consequence。",
    "severity": "low",
    "status": "active",
    "created_at": "review_pass_scene014",
    "last_updated": "review_pass_scene014",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "当前未失败，但已进入近程处理窗口。"
  }
]
```

### 3.2 起始判断

此时系统判断是：

- 当前允许继续推进
- 但 `Continue` 必须读取该 reminder
- 下一个或下下个 `PlotUnit` 应体现至少一项后果

---

## 4. 第一轮继续：未完全补偿，但仍未到升级点

### 4.1 故意制造的续写结果

生成 `pu_scene_015 / 雨后藏迹`，其中：

- `c001` 与 `c002` 先转入短时撤离
- 文本提到局势紧张
- 但没有真正体现旧伤恶化
- 没有体现追踪压力逼近
- 只轻触保密气氛

这是一种常见失败边缘：

- 作者以为“我已经写到紧张感了”
- 但对象层其实没有兑现 reminder 指向的后果

### 4.2 第一轮 Review 结论

这一轮通常不应立刻升级为正式 issue，因为：

- reminder 窗口还没用完
- 系统仍可在下一单元补偿

但也不能假装没事。

推荐结论：

- `pu_scene_015`：通过但有警告
- `rr_scene014_01`：继续 `active`
- 将其标记为“已消耗 1 个近程窗口”

### 4.3 第一轮复查后的 reminder

```json id="exrr08after015"
[
  {
    "reminder_id": "rr_scene014_01",
    "reminder_type": "missing_consequence",
    "title": "scene_014 的后果需在近程兑现",
    "summary": "scene_015 仍未兑现旧伤、追踪或保密压力中的任一核心后果，剩余 1 个 PlotUnit 窗口。",
    "source_object_type": "PlotUnit",
    "source_object_id": "pu_scene_014",
    "plotunit_ref": "pu_scene_014",
    "review_pass_ref": "review_pass_scene015",
    "related_issue_type": "missing_consequence",
    "supporting_refs": ["pu_scene_014", "pu_scene_015", "f_016", "f_017", "fg_002"],
    "window_type": "plotunit_count",
    "window_value": "1",
    "window_note": "下一单元必须兑现至少一项后果。",
    "escalation_rule": "若下一个 PlotUnit 仍未兑现，则升级为正式 missing_consequence。",
    "severity": "medium",
    "status": "active",
    "created_at": "review_pass_scene014",
    "last_updated": "review_pass_scene015",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "已复查一次，仍未补偿。"
  }
]
```

---

## 5. 第二轮继续：跨过窗口仍未兑现

### 5.1 故意制造的续写结果

生成 `pu_scene_016 / 林间对话`，其中：

- 重点转向 `c001` 与 `c002` 的试探对话
- 继续延后旧伤后果
- 巡查 / 追踪没有实质逼近
- 保密压力仍停留在气氛层

这时问题不再是“还可以等等”，而是：

- 两个近程单元都没有兑现 reminder
- `scene_014` 的强推进开始 retroactively 失去后果支撑

### 5.2 第二轮 Review 结论

这一轮应升级为正式问题。

推荐结论：

- `pu_scene_016`：失败，或至少触发正式问题建单
- `rr_scene014_01`：`escalated`
- 新增 `ReviewIssue(issue_type = missing_consequence)`

### 5.3 升级后的 reminder

```json id="exrr08escalated"
[
  {
    "reminder_id": "rr_scene014_01",
    "reminder_type": "missing_consequence",
    "title": "scene_014 的后果需在近程兑现",
    "summary": "提醒窗口已耗尽，后果仍未兑现，已升级为正式问题。",
    "source_object_type": "PlotUnit",
    "source_object_id": "pu_scene_014",
    "plotunit_ref": "pu_scene_014",
    "review_pass_ref": "review_pass_scene016",
    "related_issue_type": "missing_consequence",
    "supporting_refs": ["pu_scene_014", "pu_scene_015", "pu_scene_016"],
    "window_type": "plotunit_count",
    "window_value": "0",
    "window_note": "原近程窗口已结束。",
    "escalation_rule": "已触发升级。",
    "severity": "medium",
    "status": "escalated",
    "created_at": "review_pass_scene014",
    "last_updated": "review_pass_scene016",
    "resolved_by": "ri_scene014_consequence_01",
    "resolution_note": "升级为正式 missing_consequence 问题。",
    "notes": "不再作为 reminder 继续挂起。"
  }
]
```

### 5.4 新生成的正式问题

```json id="exrr08issue"
[
  {
    "issue_id": "ri_scene014_consequence_01",
    "issue_type": "missing_consequence",
    "title": "scene_014 已建立的后果在近程窗口内未兑现",
    "summary": "scene_014 激活的旧伤、追踪与保密压力，经过后续两个 PlotUnit 仍未兑现，导致强推进的后果链失真。",
    "object_type": "PlotUnit",
    "object_id": "pu_scene_014",
    "level": "scene",
    "plotunit_ref": "pu_scene_014",
    "chapter_ref": "chapter_06",
    "scene_ref": "scene_014",
    "violated_rule": "高风险行动建立后果链后，后续必须在合理近程窗口内兑现至少一项后果。",
    "supporting_facts": ["f_016", "f_017", "f_019"],
    "contradictory_facts": [],
    "missing_elements": ["near_term_consequence_payoff"],
    "evidence_note": "pu_scene_015 与 pu_scene_016 都未兑现已建立的后果压力。",
    "impact_scope": "arc",
    "affected_characters": ["c001", "c002"],
    "affected_threads": ["fg_002"],
    "affected_states": ["s_015_scene", "s_016_scene"],
    "downstream_risk": "若继续拖延，会削弱追踪线、保密线与强推进单元的可信度。",
    "suggested_fix_type": "state_update",
    "suggested_fix_note": "下一步应优先改写近程单元，明确兑现旧伤、追踪或保密压力中的至少一项。",
    "rewrite_needed": true,
    "replanning_needed": false,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "non_blocking",
    "fix_order": 1,
    "status": "open",
    "created_at": "review_pass_scene016",
    "last_updated": "review_pass_scene016",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "由 rr_scene014_01 超窗升级而来。"
  }
]
```

---

## 6. 这个压力样例在验证什么

这份样例主要验证 5 件事：

### 6.1 reminder 不是 prose 漂浮物

它能被正式创建，并进入后续 workflow 的输入包。

### 6.2 reminder 不等于 issue

第一轮未补偿时，系统仍可保留 reminder，而不必过早建单。

### 6.3 reminder 不是无限挂起

窗口耗尽后，它必须升级，而不是永远留在备注层。

### 6.4 升级必须保留来源链

正式 `ReviewIssue` 应能追溯到：

- 哪个 reminder 升级而来
- 原始风险源于哪个 `PlotUnit`
- 窗口是如何被耗尽的

### 6.5 `Continue` 的输入包必须真的读取 reminder

如果 `Continue` 读不到 active reminder，这条链就会断。

---

## 7. 当前结论

如果这套样例能稳定成立，可以认为：

- `ReviewReminder` 已不再只是概念补丁
- 它开始具备真实 workflow 价值
- 下一步可以继续做更复杂的多 reminder 并发样例

---

## 8. 一句话总结

`08_reviewreminder_chain.md` 的任务，是证明 `ReviewReminder` 不是一个更好看的 warning 说法，而是一个能稳定跨轮交接并升级的最小工作对象。
