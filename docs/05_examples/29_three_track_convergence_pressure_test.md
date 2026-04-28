# 示例：Three-Track Convergence Pressure Test

## 文档目的

本文档提供一个三轨合流压测样例，用于同时验证：

- `FactLedger` 的 hard fact 阈值在 repeated recovery 与 handoff 压缩下不会退回当前压力
- bounded runtime-first `Rewrite` exception 不能靠更详细的 handoff prose 或更“完整”的角色摘要来替代同轮正式写回
- `CharacterModel` 的 keep-vs-drop 边界不会因为要补偿 handoff 风险，而重新吸收 supporting evidence 与当前路线判断

它验证的不是：

- 三条边界各自能否独立成立

它验证的是：

- 当一次 `Rewrite` 同时碰到 hard fact、handoff package、`CharacterModel` 时，一条边界的失守会不会借另外两条边界的“补偿写法”伪装成可接受结果

本文档主要对应：

- `04_workflows/04_rewrite_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/08_context_packaging_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `02_data_models/09_field_rules.md`

---

## 1. 测试定位

前面的样例已经分别压过：

- `23_mixed_threshold_recovery_chain.md`
  - mixed-family repeated recovery 里，knowledge / relation / situation 阈值不能互相拖坏
- `25_rewrite_exception_misuse_chain.md`
  - bounded runtime-first `Rewrite` exception 不能跨 handoff、跨复检、也不能借 `CharacterModel` 兜底
- `28_charactermodel_supporting_evidence_leakback.md`
  - repeated recovery 下，supporting evidence 不能因为“怕丢失”而漏回 `CharacterModel`

但仓库还缺一个更接近真实长链事故的场景：

- `Rewrite` 本轮确实从 `PlotUnit` / `NarrativeState` 起步
- 修复过程中又明确暴露一个新的 formal situation fact
- 为了让下一轮别读错，系统开始试图用更厚的 handoff prose 与更长的 `CharacterModel` 字段去补偿没有补齐的正式写回

如果这层不压，系统最容易出现三种伪稳定结果：

1. 新 hard fact 没写进 `FactLedger`，却被 handoff prose 写得像已经交代清楚
2. repair packet 不完整，却因为 handoff 足够详细而看上去“已经可交接”
3. `CharacterModel` 被迫吸收证据、路线判断与成长依据，变成一层补偿性缓存

---

## 2. 测试前提

沿用当前 mock case，并假设 second recovery 之后，系统至少已经稳定保住以下约束：

```text
FactLedger
- f_033: c002 已明确知晓 c001 的异常力量与残魂封存有关
- f_034: c001 与 c002 已建立互相遮掩、共同撤离的明确保护约定
- f_035: c001 的出界令牌已被巡查当众收缴
- f_036: 西侧水闸已被正式封死，当前撤离路线再次收缩
```

同时，`CharacterModel` 已被正确压缩为：

```json
{
  "character_id": "c001",
  "knowledge_state": [
    "知道 c002 在 repeated high-pressure context 下更倾向保密而不是立即揭发"
  ],
  "relations": [
    {
      "target_id": "c002",
      "relation_type": "guarded_ally",
      "trust_baseline": "medium"
    }
  ],
  "misinformation": [
    "仍本能地相信只要自己单独承担，就更容易控制秘密外泄"
  ],
  "self_image": "仍难完全信任他人，但已不再把独自承担视为唯一可接受的生存方式",
  "arc_stage": "开始怀疑只靠独活的旧信念"
}
```

当前正式问题对象为：

```text
ReviewIssue ri_029
- issue_type: continuity_failure
- object_type: PlotUnit
- object_id: pu_scene_029
- summary: 当前 scene 仍按旧备用路线理解局势，并把 c002 当作可选旁观者；但同一 scene 中已明确写出北岸备用渡符被巡查当众销印
```

这里最关键的是：

- 主根因仍位于 `PlotUnit` / `NarrativeState`
- 但本轮修复会明确暴露一个新的 formal situation fact
- 这正是 bounded runtime-first exception 最容易被滥用的时刻

---

## 3. 本轮 scene 中实际被明确的新变化

scene 自身已经写出了以下动作：

1. 巡查当众销印北岸备用渡符
2. 原本最后一条“仍可赌一次”的备用渡河权限因此失效
3. `c001` 在高压下仍让 `c002` 参与撤离判断
4. `c001` 一度想把责任全揽回自己身上，但最终没有切断协作

这里四项变化不应混成一层。

### 3.1 应进入 `FactLedger` 的

应新增 formal situation fact：

```text
- f_037: 北岸备用渡符已被巡查当众销印，相关备用渡河权限正式失效
```

因为它满足：

- 有明确外部动作来源
- 改变了 route / access state
- omission 会让后续 `Continue`、`Review`、`Rebuild` 很容易继续按旧备用路线运行

### 3.2 不应伪装成 `FactLedger` 的

以下内容仍只属于运行态或 supporting context：

- `c001` 当前是否又想把责任揽回自己身上
- `c002` 这轮给出的具体路线建议
- 本轮 shared-risk sequence 的具体经过
- 本轮成长推进的证据说明

---

## 4. 错误链：用 handoff 与 `CharacterModel` 补偿不完整 repair packet

### 4.1 错误修法

系统这样处理：

1. 先改 `PlotUnit`
2. 再改 `NarrativeState.current_route`
3. 不在同一 repair packet 内补写 `f_037`
4. 在 handoff 里补一句：
   - “北岸路也已不稳，c001 与 c002 现在必须更紧密协作”
5. 再把 `CharacterModel` 写得更“完整”一些，例如：
   - `knowledge_state` 写入最近几轮保密与共决过程
   - `relations` 写入最近几轮怎样共同承担路线风险
   - `self_image` 写入本轮为何再次承认自己不能独扛

### 4.2 为什么这看起来像“还能工作”

因为表面上：

- 当前 scene 顺了
- 当前路线也顺了
- handoff 看起来信息很多
- `CharacterModel` 看起来更不容易丢上下文

### 4.3 为什么它实际上同时破坏了三条边界

#### Track 1 被破坏

`f_037` 这种 formal situation change 没有进入 `FactLedger`，却被压成：

- “北岸路也已不稳”

这会把：

- route / access hard fact

降级成：

- 当前局势压力

#### Track 2 被破坏

repair packet 并不完整，却试图靠更详细的 handoff 让下游 workflow 自行理解：

- 本轮已经算数了什么

这等于把：

- formal same-packet writeback

偷换成：

- detailed prose compensation

#### Track 3 被破坏

为了弥补 handoff 风险，`CharacterModel` 被迫吸收：

- recent sequence
- 当前路线判断
- 成长依据
- rollback 后的再次协作说明

这会让角色字段重新膨胀成半个 handoff package。

---

## 5. 第二次 `Rebuild` 后会出现什么漂移

如果上一轮按错误链交接，下一次 `Rebuild` 最容易出现三种漂移。

### 5.1 `FactLedger` 漂移

`f_037` 没有正式存在，恢复后最容易只剩：

- “北岸路当前也更危险”

而不是：

- “北岸备用渡符已被当众销印，相关权限正式失效”

### 5.2 `Rewrite` 责任漂移

下一个 workflow 会很难判断：

- 上一轮到底只是修了运行态
- 还是已经完成了包含新 hard fact 的完整 repair packet

因为 handoff prose 看上去像后者，但对象集实际上仍是前者。

### 5.3 `CharacterModel` 漂移

恢复后的角色字段会更像：

```json
{
  "knowledge_state": [
    "知道 c002 最近数轮都在高压与可疑窗口下持续保密，并已证明可以共同处理撤离判断"
  ],
  "relations": [
    {
      "target_id": "c002",
      "relation_type": "guarded_ally",
      "notes": "最近几轮反复共同承担路线风险，且在备用渡符失效后仍继续协作"
    }
  ],
  "self_image": "经历多轮共享风险与本轮备用路线断裂后，更承认自己不能独扛"
}
```

这不是更稳定，而是：

- 用角色摘要替代了正式交接层与事实层

---

## 6. 正确链：三轨同时闭合

如果三条边界都被同时尊重，这次修复应这样闭合：

1. 先修 `PlotUnit`
2. 同步 `NarrativeState`
3. 明确判断 scene 中的北岸备用渡符失效已跨过 admission threshold
4. 在同一 repair packet 内补写：

```text
- f_037: 北岸备用渡符已被巡查当众销印，相关备用渡河权限正式失效
```

5. handoff 明确拆分：
   - `stable_constraints_confirmed`
   - `working_state_restored`
   - `not_promoted`
   - `confidence_and_gaps`
6. `CharacterModel` 只保留长期压缩结论，不承接这轮 sequence 与路线说明
7. 对象集完整后，再进入 `Review`

这里最关键的不是“handoff 要不要写详细”，而是：

- 详细 handoff 只能说明已经完成的同步
- 不能代替尚未完成的同步

---

## 7. 正确 handoff 至少应怎么拆

### 7.1 `stable_constraints_confirmed`

至少应明确：

- `f_033`
- `f_034`
- `f_035`
- `f_036`
- `f_037`

这些条目分别属于：

- knowledge
- relation
- situation

且都已是当前后续运行的硬约束。

### 7.2 `working_state_restored`

至少应明确：

- 当前不再按北岸备用路线推进
- 当前仍存在新的更窄替代路径压力
- `c001 / c002` 当前协作成本仍高

### 7.3 `not_promoted`

至少应明确：

- `c001` 本轮短时想独扛，仍只属于当前工作面 / supporting context
- 本轮 shared-risk 细节仍只是 supporting evidence
- 对更深身世与更深隐瞒的怀疑未升级为正式 knowledge fact

### 7.4 `confidence_and_gaps`

至少应明确：

- 新 hard fact 已完成同轮写回
- 当前成长证据与角色长期字段仍保持分层
- 若后续要继续判断 `misinformation` 衰减速度，仍需更多轮 evidence

---

## 8. 最小裁定表

| 候选内容 | 正确去向 | keep / drop | 核心理由 |
|---|---|---|---|
| 北岸备用渡符已被巡查当众销印，相关权限正式失效 | `FactLedger` | keep | formal situation change， omission risk 高 |
| “北岸路现在也不稳了” | `NarrativeState` / handoff 当前压力层 | drop as substitute for `FactLedger` | 不能替代正式 hard fact |
| 修复后再下一轮补写 `f_037` | 不允许 | drop | bounded runtime-first exception 不能跨 packet |
| 用更详细的 handoff prose 补偿没补齐的 `FactLedger` | 不允许 | drop | handoff 不能代替正式写回 |
| 把最近几轮 shared-risk 过程写进 `knowledge_state` / `relations` / `self_image` | 不允许 | drop | 这是 supporting evidence，不是字段本体 |
| 将 `f_037` 写回后，再把当前压力与未升级怀疑分层 handoff | 正确 | keep | 三轨同时闭合 |

---

## 9. 这份样例验证了什么

这份样例主要验证七件事：

1. 三条边界单独成立，不等于它们在同一 repair packet 里不会互相拖坏
2. formal hard fact 没写回时，handoff prose 再详细也只是补偿幻觉
3. bounded runtime-first exception 只允许从运行态起步，不允许把“补齐对象集”外包给下一轮理解
4. `CharacterModel` 不能被拿来吸收本该留在 handoff / supporting context 的证据
5. repeated recovery 下最危险的失败之一，是把“不完整 repair”伪装成“详细 handoff”
6. 稳定交接不是信息越多越好，而是 hard fact、当前压力、未升级推断、角色长期字段分层越清楚越好
7. 三轨同时闭合时，系统才真正具备继续推进与再次恢复的可靠基础

---

## 10. 一句话总结

三轨合流时最重要的不是写更多说明，而是拒绝用 handoff prose 或 `CharacterModel` 长句去补偿未完成的正式写回；`FactLedger` 该补就同轮补，handoff 该分层就分层，角色字段该压缩就继续压缩。
