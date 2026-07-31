# 示例：CharacterModel Supporting Evidence Leakback 压测

## 文档目的

本文档提供一个 second-recovery mixed-loop 样例，用于验证：

- 当 `knowledge_state`、`relations`、`misinformation`、`self_image`、`arc_stage` 都已有合法更新时，supporting evidence 是否会在下一次 `Rebuild` / handoff 中重新漏写回字段本体
- repeated `Continue / Review / Rebuild` 之后，`CharacterModel` 是否还能继续只保留长期结构，而不退化成“字段结论 + 证据说明 + 当前压力”的压缩混合包
- 成长推进、误判衰减、关系稳固的证据，是否仍被放在 `PlotUnit`、`NarrativeState`、handoff supporting context 与 `Review` supporting context，而不是塞回角色字段

它验证的不是：

- `CharacterModel` 字段是否不允许更新

它验证的是：

- 即使字段本体可以合法更新，支持这些更新的多轮证据也不应反向写成字段内容的一部分

本文档主要对应：

- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 1. 测试定位

前面的两份 mixed-field 样例已经分别压过：

- `26_charactermodel_cross_field_recovery.md`
  - 多字段一起变化时，长期结构、稳定误判、当前工作面、成长依据不能混写
- `27_charactermodel_rollback_misinformation.md`
  - `self_image` / `arc_stage` 合法推进后，旧 `misinformation` 仍可能残留并在 rollback 里复燃

但还缺一个更接近真实交接失败的场景：

- 字段本体已经有 first-pass 合法更新
- 系统也已经积累了更多 supporting evidence
- 到第二次恢复或第二次 handoff 时，这些证据因为“看起来都很重要”而被重新写回字段本体

如果这层不压，系统最容易出现四种坏结果：

1. `knowledge_state` 里开始夹带多轮协作过程说明
2. `relations` 里开始夹带“最近几轮怎么一起扛风险”的证据叙述
3. `self_image` 与 `arc_stage` 被写成长句论证，而不再只是长期结构结论
4. `CharacterModel` 在 repeated recovery 里重新膨胀成半个 handoff package

---

## 2. 测试前提

沿用当前 mock case，并假设在 `27_charactermodel_rollback_misinformation.md` 之后，`c001` 已经被正确恢复为：

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

同时，handoff supporting context 中已经累计了这些证据：

- `c001` 曾两次主动把关键风险判断交给 `c002` 共决
- 这样做带来过真实代价，但 `c001` 没有永久退回旧模式
- `c002` 在高压与可疑场景下仍连续选择保密
- rollback 场景里，旧误判会复燃，但不会完全抹掉已成立的成长偏移

这里最关键的是：

- 字段本体已经有合法 first-pass 结论
- supporting evidence 也确实越来越多
- 下一轮最危险的失败，不再是“字段该不该更”，而是“证据会不会漏回字段正文”

---

## 3. Loop 1：第二次恢复前的新增压力

### 3.1 新推进

在后续若干轮 `Continue` 中，又连续发生了这些变化：

1. `c001` 在并未被当场逼迫时，仍主动让 `c002` 参与撤离路线判断
2. 一次判断失误后，`c001` 出现短时回摆，但下一轮没有彻底切断协作
3. `c002` 在可自保的窗口中，仍选择不对外揭发 `c001`
4. `c001` 开始承认：
   - “自己单独承担，并没有比共同承担更能控制局势”
5. `Review` 对这些推进给出的 supporting note 越来越长，因为它们都在证明：
   - 关系稳固是真的
   - 自我认知偏移是真的
   - 旧误判在衰减也是真的

### 3.2 这里最危险的误写诱因

因为这些证据跨了多轮、带了代价、也经受过 rollback，系统很容易开始想：

- “既然这些依据都已经很稳定，不如直接写进字段里，免得下次 handoff 丢失”

这会诱发一种很隐蔽的错法：

- 不是把字段写错
- 而是把字段写得“过于有理有据”

也就是把：

- 字段结论
- supporting evidence
- 当前工作面压力

重新混成一个更长、更像摘要、但边界更差的字段本体

---

## 4. 第二次 `Rebuild` 时最容易出现的错误恢复

错误恢复最可能长成这样：

```json
{
  "knowledge_state": [
    "知道 c002 已在最近数轮高压、可疑与可自保窗口里连续选择保密，并在一次路线判断失误后仍继续协作，因此目前可以把关键风险判断交给 c002 共同处理"
  ],
  "relations": [
    {
      "target_id": "c002",
      "relation_type": "guarded_ally",
      "notes": "最近几轮反复共同承担路线、暴露与诱敌风险，且在 rollback 后仍维持互相接应"
    }
  ],
  "misinformation": [
    "虽然已经开始承认共同承担有用，但在高压时仍会本能想把全部风险揽回自己身上，因为只有这样才觉得秘密可控"
  ],
  "self_image": "经历多轮共同承担、失败回摆与再次协作后，开始承认自己并非只能一个人活下去",
  "arc_stage": "因最近多轮共享风险、付出代价且 rollback 后未完全回退，进入开始怀疑只靠独活旧信念的阶段"
}
```

这份恢复看起来“内容更完整”，但实际已经犯了同一种结构错误：

- `knowledge_state` 吞进了路线策略与协作证据
- `relations` 吞进了关系依据与 sequence 描述
- `misinformation` 吞进了行为论证句
- `self_image` 与 `arc_stage` 吞进了成长说明，而不再只是字段结论

换句话说：

- 第二次恢复失败，不一定表现为字段更新错误
- 更常见的表现，是字段边界再次膨胀

---

## 5. 正确恢复应如何分层

### 5.1 `CharacterModel` 字段本体应保留什么

正确恢复更接近：

```json
{
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

重点不是完全不变，而是：

- 只保留已经成立的长期压缩结论
- 不把“为什么成立”一起写进字段本体

### 5.2 supporting evidence 应留在哪里

以下内容应留在 supporting context，而不是回写 `CharacterModel`：

- 哪几轮共享了什么风险
- 哪次失败后如何回摆、如何再次协作
- 哪次路线判断失误仍没有打断长期偏移
- `c002` 在哪些具体窗口里继续保密
- 哪些代价构成了 `self_image` 与 `arc_stage` 的推进依据

更合适的承载位置是：

- `PlotUnit` 的状态变化说明
- `NarrativeState` 当前工作面
- `Rebuild` / handoff supporting context
- `Review` supporting notes

### 5.3 为什么这样不会“丢证据”

因为系统真正需要保住的不是：

- 每个字段自己携带全部论证

而是：

- 结论与证据分层后，后续 workflow 仍能找到证据来源

也就是说，防丢失的正确做法是：

- 保留 supporting context 的位置与引用

而不是：

- 把 supporting context 倒灌进字段正文

---

## 6. 这类失败为什么会在第二次恢复更高发

第一次恢复时，系统更容易犯的是：

- 误把误判清零
- 误把成长回滚掉

第二次恢复时，系统更容易犯的是：

- 因为“证据积累更多了”，就想把这些证据和字段结论一起永久压缩保存

这正是 long-chain recovery 的一个典型风险：

- 越到后面，越容易把“多轮证据”误当成“字段本体的一部分”

如果不在这里立规则，`CharacterModel` 会逐步退化成：

- 看似稳定
- 实则把 handoff supporting context 偷藏进字段里

---

## 7. 最小裁定表

| 候选内容 | 正确去向 | keep / drop | 核心理由 |
|---|---|---|---|
| `c002` 在 repeated high-pressure context 下更倾向保密 | `CharacterModel.knowledge_state` 压缩条目 | keep | 稳定认知负担 |
| “最近三轮分别在哪些窗口继续保密” | handoff / review supporting context | drop from `knowledge_state` | 这是证据，不是字段本体 |
| `guarded_ally` 关系基底 | `CharacterModel.relations` | keep | 长期关系结构 |
| “最近几轮怎样一起扛路线与暴露风险” | supporting context | drop from `relations` | 这是关系依据，不是关系字段 |
| 旧“独自承担更安全”的误判仍会在高压下复燃 | `CharacterModel.misinformation` | keep | 稳定错误信念仍在支配行为 |
| “因为哪次失败所以又想独扛” | `PlotUnit` / `NarrativeState` / supporting context | drop from `misinformation` | 这是具体触发证据 |
| `仍难完全信任他人，但已不再把独自承担视为唯一方式` | `CharacterModel.self_image` | keep | 稳定自我定义偏移 |
| “最近几轮共同承担且付出代价，所以自我认知改变” | supporting context | drop from `self_image` | 这是成长依据 |
| `开始怀疑只靠独活的旧信念` | `CharacterModel.arc_stage` | keep | 阶段结论 |
| “最近几轮共享风险、rollback 后未完全回退” | supporting context | drop from `arc_stage` | 这是阶段依据，不是阶段标签 |

---

## 8. 这份样例验证了什么

这份样例主要验证六件事：

1. mixed-field 边界在第二次恢复时，真正危险的是 evidence leakback，而不只是字段是否更新
2. `CharacterModel` 字段可以合法更新，但 supporting evidence 仍必须留在字段外
3. `knowledge_state`、`relations`、`self_image`、`arc_stage` 都不能因为证据变多就长成“结论 + 论证”的复合句
4. repeated `Rebuild` 想保真，应该保留证据位置与引用，而不是把证据回灌到字段本体
5. “怕丢信息”不是把字段写长的理由；真正要防丢的是 handoff 与 review supporting context
6. 一个稳定的 `CharacterModel` 不是信息越来越多，而是长期结构与 supporting evidence 的分层越来越稳

---

## 9. 一句话总结

`CharacterModel` 在 long-chain recovery 里的稳定性，不只要求字段更新正确，还要求 supporting evidence 不会因为 repeated `Rebuild` 而漏回字段本体；结论留在字段里，依据留在 supporting context 里，这个分层必须越恢复越稳，而不是越恢复越糊。
