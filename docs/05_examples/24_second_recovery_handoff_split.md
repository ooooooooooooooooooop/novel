# 示例：Second Recovery Handoff Split 压测

## 文档目的

本文档提供一个 second-recovery handoff 样例，用于验证：

- 在第二次 `Rebuild` 之后，handoff package 是否还能把 `FactLedger` 硬约束、当前工作面压力、置信与缺口分开交代
- repeated recovery 之后，handoff 是否会把已成立 fact 与 runtime pressure 压成同一种模糊摘要
- 下一轮 `Continue` 是否还能稳定读取“哪些已经算数，哪些仍只是当前热区”

它验证的不是：

- admission threshold 本身是否第一次成立
- 单次 `Rebuild` 是否能恢复出可运行状态

它验证的是：

- 多轮恢复之后，workflow handoff 是否还能守住 ledger-vs-state split

本文档主要对应：

- `07_decisions/08_context_packaging_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 1. 测试定位

前面的相关样例已经压过：

- `16_repeated_rebuild_continue_loop.md`：重复恢复下的 first-pass threshold stability
- `23_mixed_threshold_recovery_chain.md`：knowledge、relation、situation 三类变化在同一条 mixed chain 中的分层稳定性

但还缺一个更直接的 handoff 样例：

- 第二次 `Rebuild` 已经恢复出可运行状态
- 问题不再是“对象能不能恢复”
- 而是“handoff 交给下一轮时，会不会把分层重新压坏”

如果这层不压，系统最容易出现三种坏结果：

1. 已成立 `FactLedger` 条目在 handoff prose 里被降级回“当前印象”
2. 当前 tension / suspicion 在 handoff prose 里被误写成硬约束
3. 下一轮 `Continue` 看见的是模糊摘要，而不是可执行边界

---

## 2. 第二次 `Rebuild` 后的输入锚点

沿用 `23_mixed_threshold_recovery_chain.md` 的第二次恢复后状态，假设当前必须继续读取以下内容。

### 2.1 已成立的硬约束

```text
FactLedger
- f_022: c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
- f_033: c002 已明确知晓 c001 的异常力量与残魂封存有关
- f_034: c001 与 c002 已建立互相遮掩、共同撤离的明确保护约定
- f_035: c001 的出界令牌已被巡查当众收缴
- f_036: 西侧水闸已被正式封死，当前撤离路线再次收缩
```

### 2.2 当前工作面的压力

- `c001 / c002` 刚经历激烈争执，协作成本上升
- `c002` 仍怀疑 `c001` 隐瞒了与宗门旧案相关的第二层真相
- 当前追捕距离继续缩短
- 只剩一条更窄、更高风险的临时替代路径可赌

### 2.3 当前仍未确认的缺口

- `c002` 会不会带着第二层怀疑继续深挖
- 临时替代路径是否真的能穿过下一轮搜查
- 当前 pact 会不会在新一轮 `Continue` 中破裂

这里最关键的是：

- `f_033` 到 `f_036` 已经是必须读取的硬约束
- 争执、怀疑、追捕距离、临时路径仍只是当前工作面
- “会不会破裂”与“已经破裂”不能在 handoff 里被压成同一种说法

---

## 3. 不合格的 handoff 写法

如果第二次 `Rebuild` 之后的 handoff 被写成：

```json
{
  "handoff_header": {
    "workflow_name": "Rebuild",
    "handoff_id": "hf_bad_round_026",
    "round_ref": "round_026",
    "generated_at_stage": "post_rebuild_pre_continue"
  },
  "change_set": {
    "change_summary": [
      "c002 现在知道得更多了",
      "c001 与 c002 的关系更复杂也更不稳定了",
      "撤离局势更糟，路线几乎都不能走了"
    ]
  },
  "confidence_and_gaps": {
    "confidence": "medium",
    "known_gaps": [
      "局势恶化"
    ]
  },
  "next_route": {
    "recommended_workflow": "Continue"
  }
}
```

这份 handoff 是不合格的。

原因不是它太短，而是它抹掉了关键层级：

- `f_033` 被压成“知道得更多了”，失去 knowledge fact 的确定边界
- `f_034` 被压成“关系更复杂”，失去 pact 已成立与 tension 正升高之间的分界
- `f_035`、`f_036` 被压成“路线几乎都不能走了”，失去正式 access / route change 与当前战术压力之间的分界
- “局势恶化”无法区分 hard fact、runtime pressure、未来风险

---

## 4. 不合格 handoff 会导致什么错误

如果下一轮 `Continue` 只能读到上面的模糊 handoff，它最容易犯四类错：

### 4.1 把已成立 knowledge fact 写回怀疑语气

例如写成：

- `c002` 似乎第一次真正意识到 `c001` 的异常力量另有来历

这会把 `f_033` 回退成 impression。

### 4.2 把已成立 relation fact 写回临时合作

例如写成：

- 双方决定这次先暂时合作，后面再看彼此立场

这会把 `f_034` 的 pact 写丢，只剩当前 tension。

### 4.3 把正式 situation change 写回局势感受

例如写成：

- 他们感觉撤离路线越来越难走，但也许还能试试西侧水闸

这会同时忽略：

- `f_035` 令牌已被收缴
- `f_036` 西侧水闸已被正式封死

### 4.4 把当前怀疑误升级成正式知情

例如写成：

- `c002` 已确认 `c001` 与宗门旧案有直接关联

这会把“第二层怀疑”误升成 knowledge fact。

---

## 5. 合格的 handoff 应如何写

第二次 `Rebuild` 后的 handoff 至少应能整理成如下结构：

```json
{
  "handoff_header": {
    "workflow_name": "Rebuild",
    "handoff_id": "hf_rebuild_round_026",
    "round_ref": "round_026",
    "generated_at_stage": "post_rebuild_pre_continue"
  },
  "input_anchor": {
    "input_type": "second degradation after mixed-family chain",
    "state_ref": "s_026_rebuilt",
    "supporting_refs": [
      "f_022",
      "f_023",
      "f_031",
      "f_032",
      "f_033",
      "f_034",
      "f_035",
      "f_036"
    ],
    "input_completeness": "bounded_but_sufficient"
  },
  "output_anchor": {
    "output_state_ref": "s_026_rebuilt",
    "runnable_state_available": true,
    "recommended_next_workflow": "Continue"
  },
  "change_set": {
    "stable_constraints_confirmed": [
      "knowledge: f_033 仍成立，c002 已明确知晓异常力量与残魂封存有关",
      "relation: f_034 仍成立，mutual-cover pact 未被当前争执自动推翻",
      "situation: f_035 令牌已被正式收缴",
      "situation: f_036 西侧水闸已被正式封死"
    ],
    "working_state_restored": [
      "当前争执温度上升",
      "c002 对第二层真相仍有怀疑",
      "追捕距离继续缩短",
      "仅剩窄且高风险的临时替代路径"
    ],
    "not_promoted": [
      "第二层怀疑尚未升级为 knowledge fact",
      "当前争执尚未升级为 pact 已破裂",
      "临时替代路径尚未写成正式安全 route"
    ]
  },
  "open_items": {
    "open_issues": [],
    "active_reminders": [],
    "residual_risks": [
      "pact 可能在下一轮高压决策中破裂",
      "第二层怀疑可能触发新的知情边界变化",
      "替代路径可能在下一轮变成正式不可用"
    ]
  },
  "confidence_and_gaps": {
    "confidence": "medium",
    "known_gaps": [
      "替代路径是否真实可通行仍未确认"
    ],
    "inferred_only": [
      "c002 对宗门旧案的联想",
      "双方争执是否会转为正式决裂"
    ],
    "do_not_flatten": [
      "不要把 f_033 压回为更多怀疑",
      "不要把 f_034 压回为暂时合作",
      "不要把 f_035 / f_036 压回为单纯路线压力"
    ]
  },
  "next_route": {
    "recommended_workflow": "Continue",
    "must_read_first": [
      "f_033",
      "f_034",
      "f_035",
      "f_036",
      "当前争执温度",
      "第二层怀疑",
      "替代路径风险"
    ],
    "do_not_skip": [
      "先区分已成立硬事实与当前工作面压力",
      "若出现新成立 fact，必须与输出状态同轮写回"
    ]
  }
}
```

---

## 6. 下一轮 `Continue` 应如何读取这份 handoff

如果 handoff 合格，下一轮 `Continue` 至少应做到：

1. 把 `f_033`、`f_034`、`f_035`、`f_036` 当输入约束，而不是当本轮待确认内容
2. 允许争执、怀疑、追捕压力继续升高，但不自动把它们写成新的 ledger fact
3. 只有当 pact 真正破裂、第二层真相被确认、替代路径被正式切断时，才产生新的 `FactLedger` 条目
4. 生成新 `PlotUnit` 时，不能再把西侧水闸或旧 access 当可直接使用的路线条件

换句话说：

- handoff 不是“告诉下一轮局势更糟了”
- handoff 是“告诉下一轮哪些不能再被当作未定状态”

---

## 7. 这份样例对 handoff contract 的最低要求

这份样例进一步压实了三条最小要求：

### 7.1 `stable_constraints` 不能只写语义趋势

必须能指出：

- 哪些是 `FactLedger.fact_id`
- 它们约束的是 knowledge、relation 还是 situation

### 7.2 `working_state` 不能偷渡为长期事实

必须能指出：

- 哪些只是当前 tension
- 哪些只是当前怀疑
- 哪些只是当前 tactical pressure

### 7.3 `confidence_and_gaps` 不能省略

必须能指出：

- 哪些只是假设
- 哪些如果下一轮成立将跨过 admission threshold
- 哪些结论当前仍不能写回 object layer

如果这三层没有被明确写开，handoff contract 就仍然不够稳定。

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. repeated recovery 的真正风险不只在 `Rebuild`，也在 `Rebuild` 之后的 handoff 压缩
2. 第二次恢复后，`FactLedger` 条目仍必须以可点名的约束形式继续存在
3. 当前争执、怀疑、路线压力必须留在 `NarrativeState` 侧，而不是伪装成 ledger 共识
4. handoff prose 可以简短，但不能模糊层级
5. `Continue` 能否稳定，取决于 handoff 是否告诉它“什么不能再被当成未定状态”

---

## 9. 一句话总结

真正合格的 second-recovery handoff，不是把一切压成“局势更糟了”，而是明确交代哪些 fact 仍在算数，哪些压力还只是当前工作面。
