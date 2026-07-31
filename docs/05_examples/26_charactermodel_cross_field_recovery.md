# 示例：CharacterModel Cross-Field Recovery 压测

## 文档目的

本文档提供一个 mixed-field repeated recovery 样例，用于验证：

- `knowledge_state`、`relations`、`misinformation`、`self_image`、`arc_stage` 在同一条长链里一起变化时，是否仍能保持清晰边界
- `Continue / Review / Rebuild` repeated loop 下，`CharacterModel` 会不会把当前工作面、关系证据、成长依据、主观押注压成一团
- `Rebuild` 后是否还能稳定区分“应保留的角色侧长期结构”和“应回退到当前工作面或 supporting context 的内容”

它验证的不是：

- 单一字段在孤立场景下能否被裁定

它验证的是：

- 多字段同时变化时，keep-vs-drop 规则会不会重新塌成“凡是重要都写进 `CharacterModel`”

本文档主要对应：

- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 1. 测试定位

前面的样例已经分别压过：

- `18_charactermodel_summary_bloat.md`
- `19_charactermodel_rebuild_pruning.md`
- `20_charactermodel_keep_vs_drop.md`
- `21_charactermodel_self_image_boundary.md`
- `22_charactermodel_arc_stage_boundary.md`

但它们大多仍是：

- 单字段
- 或双字段

边界压测。

仓库当前最缺的是一个更接近真实长链工作的场景：

- 角色长期知情负担在变化
- 长期关系基底在变化
- 主观误判也在同步变化
- 自我认知开始偏移
- 成长阶段也出现推进诱因

如果这层不压，系统最容易出现四种坏结果：

1. `misinformation` 被写进 `knowledge_state`
2. 关系推进依据被写进 `relations`
3. `self_image` 与 `arc_stage` 把 scene 级证据直接吞进去
4. repeated `Rebuild` 后，`CharacterModel` 变成一个压缩得很差的“当前局势总摘要”

---

## 2. 测试前提

沿用当前 mock case，并假设 `c001` 的相关基线如下：

```json
{
  "character_id": "c001",
  "knowledge_state": [
    "知道 c002 已掌握自己异常存在，并做出过一次正式保密动作"
  ],
  "relations": [
    {
      "target_id": "c002",
      "relation_type": "guarded_risk_bound_ally",
      "trust_baseline": "low_to_medium"
    }
  ],
  "misinformation": [
    "误以为只要自己继续单独承担，就还能控制秘密外泄"
  ],
  "self_image": "不值得被长期信任，只适合一个人活下去",
  "arc_stage": "未觉醒"
}
```

当前还存在以下已成立约束：

```text
FactLedger
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

这里最关键的是：

- 角色模型里已经有第一层长期知情负担与长期关系基底
- 但自我认知、成长阶段与误判层都还处于容易混写的边缘状态

---

## 3. Loop 1：多字段一起受到诱因

### 3.1 新推进

在若干个 `Continue` 中，连续发生了这些变化：

1. `c002` 在第二次高压场景里继续选择保密，而不是上报
2. `c001` 在一次危机中被迫把部分撤离信息共享给 `c002`
3. `c001` 开始怀疑“也许自己并不需要永远单独承担”
4. 一次短暂顺利撤离后，`c001` 又冒出强烈自信：
   - “也许我一个人还是能兜住所有风险”
5. 在三次高压决策里，`c001` 都没有完全退回旧模式，而是继续让 `c002` 参与关键判断

### 3.2 这里的危险

如果系统贪图“都很重要”，最容易直接把以下内容同时塞进 `CharacterModel`：

- `knowledge_state`: “知道祭典路线比水路更稳”
- `relations`: “最近三次高压都共同承担风险”
- `misinformation`: “也许自己一个人就能稳住全部局势”
- `self_image`: “最近已经不是只能独活的人”
- `arc_stage`: “最近三次都共享风险，成长已明显推进”

表面上看像很完整，实际上已经把：

- 当前路线判断
- 关系依据
- 主观押注
- 自我认知证据
- 成长阶段依据

全部混成了一层。

---

## 4. Loop 1 的正确分层

### 4.1 `knowledge_state` 可保留什么

可以保留的压缩内容是：

- `c002` 在 repeated high-pressure context 下更倾向保密而非即时揭发

因为这已经形成：

- 稳定知情负担
- 会持续影响后续求助与共享判断

不应保留的是：

- “祭典路线比水路更稳”

因为这仍是：

- 当前任务态路线判断

### 4.2 `relations` 可保留什么

可以保留：

- `guarded_risk_bound_ally` 向更稳的 `guarded_ally` 基底偏移

不应直接保留：

- “最近三次高压都共同承担风险”

因为这仍是：

- 关系推进依据
- supporting context

而不是长期关系字段本身。

### 4.3 `misinformation` 应保留什么

应保留：

- “只要自己继续单独承担，就还能控制秘密外泄”

如果这条误判在 repeated loop 中仍持续支配决策，它仍属于：

- 稳定错误信念

而不应被误升级为：

- `knowledge_state`

### 4.4 `self_image` 这时能不能更新

此时仍不应直接更新成：

- “已经不是只能独活的人”

因为目前还更接近：

- 反复出现的偏移证据

而不是：

- 已稳定落定的新自我定义

更合适的处理是：

- 把相关证据留在 `PlotUnit`、`Review` supporting context、handoff 里

### 4.5 `arc_stage` 这时能不能推进

此时也不应直接从 `未觉醒` 推到更高阶段。

因为虽然已经出现 repeated pattern，但仍需要继续验证：

- 是否带代价
- 是否经受回退压力
- 是否不是单纯高压下的暂时偏移

所以这里更像：

- growth evidence accumulating

而不是：

- stage transition completed

---

## 5. 第一次 `Rebuild` 后的正确恢复

如果第一次退化后进入 `Rebuild`，正确恢复应至少做到：

### 5.1 仍保留在 `CharacterModel` 的

- `knowledge_state` 中关于 `c002` 在高压下更倾向保密的压缩认知负担
- `relations` 中更稳的 guarded alliance 基底
- `misinformation` 中“自己继续单独承担就能控制局势”的稳定错误信念

### 5.2 不应被恢复进 `CharacterModel` 的

- 当前祭典路线是否更优
- 最近三次高压共同承担的具体 sequence 描述
- “这几轮已经明显成长”的 prose 判断
- 某次顺风后的自满高估

### 5.3 为什么这一轮最容易混账

因为 `Rebuild` 最容易看到的是：

- repeated pattern

然后把 pattern evidence 直接写进：

- `relations`
- `self_image`
- `arc_stage`

这会让角色模型看起来“很有根据”，但其实已经把：

- 字段本体
- 字段依据

写在了一起。

---

## 6. Loop 2：真正的跨字段稳定偏移

### 6.1 新推进

在第一次恢复之后，后续若干轮又出现这些变化：

1. `c001` 在并未被逼迫时，主动把关键风险判断交给 `c002` 共同决定
2. 这样做带来了明确代价：
   - 暴露边缘上升
   - 自己对控制权的心理安全感下降
3. 在一次失败后，`c001` 虽然出现短时自责，但下一轮没有完全退回旧模式
4. “只要自己单独承担就能控制局势”的旧误判开始被反复撞穿

### 6.2 这时的正确裁定

#### `knowledge_state`

仍只保留：

- 与 `c002` 保密倾向、协作可靠性相关的长期认知负担

不把：

- 每轮具体协作策略

写进去。

#### `relations`

可进一步稳定为：

- `guarded_ally`

但仍不把：

- “最近几轮共同承担风险”

这种证据说明写进字段。

#### `misinformation`

原有误判可以：

- 保留为正在动摇的旧误判
- 或在证据充分后从主导误判降级

但不能直接被删掉得像从未存在过。

#### `self_image`

这时可以更新为更稳定的压缩表达，例如：

- `仍难完全信任他人，但已不再把单独承担视为唯一可接受的生存方式`

因为它已经满足：

- 跨多轮
- 带代价
- 未快速回退

#### `arc_stage`

这时也可以从：

- `未觉醒`

推进到：

- `开始怀疑只能独活的旧信念`

因为成长依据已经具备：

- repeated pattern
- 明确代价
- 回退测试后仍成立

---

## 7. 第二次 `Rebuild` 后最容易犯的错

第二次恢复时，系统最容易犯三种错：

### 7.1 把 `misinformation` 误删成“角色已经想通了”

如果旧误判只是动摇，还未完全脱离，就不能因为：

- `self_image` 更新了
- `arc_stage` 前移了

就把误判层直接清空。

### 7.2 把 `self_image` 的更新依据写进字段本体

例如恢复成：

- “最近多轮都愿意共同承担，所以开始承认不能独活”

这会让 `self_image` 变成成长流水账。

### 7.3 把 `arc_stage` 写成带论证的长句

例如：

- “因为最近几轮共享风险且付出代价，所以进入第一次稳定偏移”

这会让：

- stage label
- stage evidence

混成一层。

---

## 8. 最小 cross-field 裁定表

| 候选内容 | 正确去向 | keep / drop | 核心理由 |
|---|---|---|---|
| `c002` 在高压下更倾向保密而非即时揭发 | `CharacterModel.knowledge_state` 压缩版 | keep | 稳定认知负担 |
| 当前祭典路线更可行 | `NarrativeState` / handoff current working set | drop | 当前任务态判断 |
| `guarded_ally` 关系基底 | `CharacterModel.relations` | keep | 长期关系基底 |
| “最近三次共同承担风险” | handoff / review supporting context | drop from `relations` | 关系依据，不是字段本体 |
| “自己一个人还是能兜住全部风险” | `CharacterModel.misinformation` | keep there | 稳定错误信念，不是知情事实 |
| 一次顺风后的高估 | `NarrativeState` 或 `misinformation` | drop from `self_image` | 当前偏移，不是稳定自我认知 |
| `仍难完全信任他人，但已不再把单独承担视为唯一方式` | `CharacterModel.self_image` | keep | 稳定新自我定义 |
| `开始怀疑只能独活的旧信念` | `CharacterModel.arc_stage` | keep | 已形成阶段推进 |
| “最近几轮都共享风险所以成长推进” | handoff / review supporting context | drop from `arc_stage` | 成长依据，不是阶段标签 |

---

## 9. 这份样例验证了什么

这份样例主要验证六件事：

1. 多字段一起变化时，最容易发生的不是单点错判，而是字段彼此偷职责
2. `knowledge_state` 与 `misinformation` 必须继续区分“稳定认知负担”和“稳定错误信念”
3. `relations` 只能保留长期关系基底，不能吞掉 sequence 级证据
4. `self_image` 与 `arc_stage` 更新后，也不能把成长依据一起沉积进字段本体
5. repeated `Rebuild` 会放大 cross-field 污染，因为 evidence、state、summary 很容易一起被压缩
6. 真正稳定的 `CharacterModel` 不是字段更长，而是每个字段只保留它该保留的长期结构

---

## 10. 一句话总结

`CharacterModel` 的 cross-field recovery 稳定性，不在于把所有重要变化都记进去，而在于即使多字段一起变化，也始终分清什么是长期结构、什么是稳定误判、什么是当前工作面、什么只是 supporting evidence。
