# 工作流交接契约

## 文档目的

本文件用于定义自动小说系统中四条主工作流共享的最小交接契约。

它回答的不是：

- 某个 workflow 具体按哪一步执行

它回答的是：

- 一个 workflow 完成后，最少必须交代什么
- 下一个 workflow 不应再重新猜什么
- 哪些内容属于正式交接
- 哪些内容仍只是局部说明或原始材料

本文件主要连接：

- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/08_context_packaging_decisions.md`
- `02_data_models/09_field_rules.md`

---

## 1. 定位

工作流交接契约不是新的 workflow。

它是四条主 workflow 之间共享的最小交接层。

一句话定义：

**工作流交接契约就是把“本轮到底做了什么、留下了什么、下一轮该接什么”写成稳定接口。**

---

## 2. 为什么需要这个文件

项目已经确定：

- context package 是正式 operating interface
- handoff 不能依赖隐含理解
- bounded package 是默认模式

但如果这些要求只分散写在各 workflow 里，仍然容易出现：

- `Rebuild` 和 `Continue` 对“当前可运行状态”的交代口径不同
- `Continue` 和 `Review` 对“本轮到底改了哪些对象”的交代粒度不同
- `Review` 和 `Rewrite` 对“未解决问题”与“待观察 warning”的边界不同
- 不同 agent 重新发明自己的 handoff prose

所以本文件的任务不是替代 workflow 细节。
而是把四条主 workflow 共同依赖的最小交接语义固定下来。

---

## 3. 契约边界

### 3.1 本文件定义什么

- 交接必须回答的问题
- 交接包的共享字段骨架
- 四条主 workflow 的最小差异化要求
- 交接与 memory tiers 的对应关系

### 3.2 本文件不定义什么

- 实现期的最终 JSON API
- 每个对象的完整 schema
- 每个 workflow 的完整步骤
- 每种 failure type 的细分判定

### 3.3 当前阶段约束

当前阶段仍是 foundation design。

因此这里定义的是：

- 最小共享 contract

而不是：

- 最终机器执行格式

---

## 4. 每次交接必须回答的五个问题

任意 workflow 在交接时，最少都应让后续 workflow 能直接回答：

1. 本轮从什么对象或状态开始
2. 本轮产出了什么对象或状态
3. 本轮实际更新了什么
4. 还有什么没有解决
5. 下一条 workflow 预期要做什么

如果这五个问题答不清，交接就是不合格的。

---

## 5. 共享最小交接骨架

每条主 workflow 的正式交接，建议至少包含以下七部分。

### 5.1 `handoff_header`

用于说明这份交接属于哪一轮。

最少应包含：

- `workflow_name`
- `handoff_id`
- `round_ref` 或等价轮次标记
- `generated_at_stage`

### 5.2 `input_anchor`

用于说明本轮是从哪里起跑的。

最少应包含：

- 核心起点对象引用
- 必要的 `state_ref` / `issue_ref` / `review_target_ref`
- 输入完整度或输入类型说明

### 5.3 `output_anchor`

用于说明本轮产生了什么可被后续读取的结果。

最少应包含：

- 核心输出对象引用
- 是否形成新的可运行状态
- 是否生成新的 formal issue / reminder / plot unit

### 5.4 `change_set`

用于说明本轮真实改变了什么，而不是重复整份对象。

最少应包含：

- `changed_objects`
- 每个对象的变化摘要
- 哪些变化只是派生判断
- 哪些变化已经正式写回主存对象

当同一份 handoff 同时涉及：

- 已成立硬事实
- 当前工作面压力
- 尚未升级的推断或怀疑

不得把三者压成一条“局势更复杂了”的趋势摘要。

至少应能拆开为等价层次，例如：

- `stable_constraints_confirmed`
- `working_state_restored`
- `not_promoted`

如果某条新 hard fact 在上一 workflow 中本应正式写回却没有写回，也不允许：

- 用更详细的 handoff prose 假装它已经被完整交代
- 用 `CharacterModel` 字段扩写去补偿 handoff 风险

一句话说：

- handoff 可以说明已完成的同步
- handoff 不能替代未完成的同步

### 5.5 `open_items`

用于说明哪些内容尚未关闭。

最少应包含：

- 未关闭 `ReviewIssue`
- 未关闭 `ReviewReminder`
- 仍未确认的事实或推断
- 残留风险

### 5.6 `confidence_and_gaps`

用于说明这次交接有多可靠。

最少应包含：

- 当前置信度
- 已知缺失
- 是否存在冲突输入
- 哪些结论只是一阶推断

### 5.7 `next_route`

用于说明后续应如何接续。

最少应包含：

- 推荐下一条 workflow
- 进入下一条 workflow 前必须优先读取什么
- 当前不建议做什么

---

## 6. 交接与 memory tiers 的关系

交接包不是把所有信息塞在一起。

它应尽量保持与 memory tiers 对齐。

### 6.1 稳定记忆层

通常对应：

- `WorkSpec`
- `WorldModel`
- `CharacterModel` 的长期基线
- 已成立 `FactLedger`
- 已建立 `ForeshadowGraph`

### 6.2 当前工作层

通常对应：

- 当前 `NarrativeState`
- 当前局势摘要
- 当前活跃目标、冲突、角色、线程

### 6.3 修复控制层

通常对应：

- `ReviewIssue`
- `ReviewReminder`
- 局部修复边界
- 残留风险

### 6.4 置信与缺口层

通常对应：

- 输入完整度
- 已知缺失
- 冲突标记
- 本轮判断的置信度

原则：

- 稳定记忆不要被临时推断覆盖
- 修复层不要伪装成事实层
- 置信信息不要省略成“默认高确定性”

### 6.5 repeated recovery 下的防压平规则

当 handoff 来自 repeated `degradation -> rebuild -> review -> continue` 链时，最容易出现的错误不是字段缺失，而是层级被 prose 压平。

因此至少要避免：

- 把 `FactLedger` 条目压回“现在知道得更多了”
- 把 pact / alliance / route closure 压回“关系更复杂了”或“局势更糟了”
- 把当前 tension、怀疑、战术压力写成已经成立的 object-layer 约束

如果 handoff 做不到这层分开，下一轮 workflow 看到的就不是接口，而是模糊印象。

---

## 7. 四条主 workflow 的最小差异化要求

共享骨架之外，每条 workflow 还必须补上自己的关键交接项。

### 7.1 `Rebuild`

最少还应明确：

- `reconstruction_level`
- 是否只完成静态重建
- 是否形成可运行 `NarrativeState`
- 当前恢复结果更适合进入 `Review` 还是受限 `Continue`

`Rebuild` 的交接重点是：

- 恢复出了哪些稳定对象
- 当前是否已经有可工作的运行态
- 不确定性具体落在哪些地方

### 7.2 `Continue`

最少还应明确：

- `input_state_ref`
- `output_state_ref`
- 新生成的 `PlotUnit`
- 本轮写回了哪些对象
- 哪些 warning / issue 仍未关闭

`Continue` 的交接重点是：

- 本轮状态到底如何变化
- 长期记忆层是否被正式更新
- 接下来进入 `Review` 时应该重点检查哪里

### 7.3 `Review`

最少还应明确：

- `review_target_ref`
- `review_conclusion`
- failure / warning 分类
- 生成了哪些 `ReviewIssue` 或 `ReviewReminder`
- 路由到 `Continue` / `Rewrite` / `Replan`

`Review` 的交接重点是：

- 不是“我觉得这段怎么样”
- 而是“系统确认它现在能去哪一条后续链路”

### 7.4 `Rewrite`

最少还应明确：

- `repaired_issue_ref`
- 主根因对象
- 联动同步了哪些对象
- 哪些风险仍需复检
- 下一步复核应读取什么

`Rewrite` 的交接重点是：

- 不是“改了一版”
- 而是“哪一个问题被怎么修、哪些依赖已同步、还剩什么风险”

---

## 8. 当前最小表达模板

当前阶段不要求固定成最终机器格式。

但一份合格交接，至少应能被稳定整理成类似结构：

```json
{
  "handoff_header": {},
  "input_anchor": {},
  "output_anchor": {},
  "change_set": {},
  "open_items": {},
  "confidence_and_gaps": {},
  "next_route": {}
}
```

如果某个 workflow 只能给出散乱 prose，而无法整理进这个骨架，说明它的交接仍然不够稳定。

---

## 9. 最小示例

以下示例只展示 contract 形状，不代表完整业务字段。

```json
{
  "handoff_header": {
    "workflow_name": "Continue",
    "handoff_id": "hf_continue_scene_015",
    "round_ref": "round_015",
    "generated_at_stage": "post_continue_pre_review"
  },
  "input_anchor": {
    "input_state_ref": "s_014",
    "supporting_refs": ["cm_c001", "wm_main", "fg_001"],
    "input_completeness": "sufficient"
  },
  "output_anchor": {
    "plotunit_ref": "pu_scene_015",
    "output_state_ref": "s_015",
    "runnable_state_available": true
  },
  "change_set": {
    "changed_objects": ["PlotUnit", "NarrativeState", "FactLedger"],
    "change_summary": [
      "主目标从夺取令牌转为撤离与封口",
      "追踪风险正式上升并写入 FactLedger"
    ]
  },
  "open_items": {
    "active_reminders": ["rr_scene014_01"],
    "open_issues": [],
    "residual_risks": ["c002 立场仍未稳定"]
  },
  "confidence_and_gaps": {
    "confidence": "medium",
    "known_gaps": [],
    "inferred_only": ["c002 当前真实意图"]
  },
  "next_route": {
    "recommended_workflow": "Review",
    "must_read_first": ["pu_scene_015", "s_014", "s_015", "rr_scene014_01"],
    "do_not_skip": ["后果兑现检查"]
  }
}
```

如果交接来自恢复后的 mixed chain，`change_set` 建议进一步显式拆成：

- 哪些 `FactLedger` 约束仍成立
- 哪些只恢复为当前工作面压力
- 哪些仍只是推断，不应升级

否则示例层虽然能写出边界，contract 层却仍会默许 handoff 压平。

---

## 10. 当前使用规则

在 foundation phase，建议这样使用本文件：

1. 起草或修改任一 workflow 文档时，对照本文件检查交接是否能整理进共享骨架
2. 写样例时，至少让关键 workflow 结果能映射到这七部分
3. 发现某 workflow 需要频繁破坏骨架时，先检查是否是 object ownership 没定清，而不是立刻扩张 contract

---

## 11. 一句话总结

工作流交接契约的目标，不是让 workflow 看起来更正式，而是让下一轮工作少靠重猜，多靠稳定接口。
