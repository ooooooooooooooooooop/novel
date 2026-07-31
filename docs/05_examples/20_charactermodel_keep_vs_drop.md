# 示例：CharacterModel Keep-vs-Drop 边界压测

## 文档目的

本文档提供一个 borderline counterexample，用于验证：

- 哪些“半长期、半当前”的条目应保留在 `CharacterModel`
- 哪些看似重要但其实仍应回退到 `NarrativeState` 或 `FactLedger`
- pruning 不应只靠“感觉像摘要”来裁定

它验证的不是：

- 所有模糊条目都能被一次规则彻底解决

它验证的是：

- first-pass keep-vs-drop 边界是否已经足够稳定，能避免随手乱留或乱删

本文档主要对应：

- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 1. 测试定位

前两个样例已经分别压过：

- `CharacterModel` 会不会膨胀
- `Rebuild` 如何把明显的 stale runtime cache 剪掉

但仍有一类更难裁定的内容：

- 它不是纯当前工作面
- 也还不像明确的长期结构

如果这层不压，系统最容易出现两种相反错误：

1. 过度保留  
   把“最近几场戏连续出现”的局部判断都沉积成角色长期摘要
2. 过度删除  
   把已经开始稳定影响角色决策的认知负担一并删掉

因此这份样例关注的不是明显 case，而是：

- keep-vs-drop 的灰区

---

## 2. 测试前提

沿用当前 mock case，并假设在 repeated `Continue / Rebuild` 之后，系统遇到以下三类 borderline 条目。

### 2.1 候选条目 A

`c001.knowledge_state` 中出现：

- “知道 c002 在高压下更倾向保密而不是立刻上报”

### 2.2 候选条目 B

`c001.knowledge_state` 中出现：

- “知道祭典人流是当前最可行脱身路线”

### 2.3 候选条目 C

`c001.relations` 中出现：

```json
{
  "target_id": "c002",
  "relation_type": "guarded_ally",
  "trust_baseline": "medium",
  "recent_pattern_note": "最近三次高压场景里，对方都选择了保密与协助"
}
```

这三类内容都不属于最容易一眼裁定的 case。

---

## 3. Borderline 场景 A：可保留的半结构化长期认知负担

### 3.1 情况说明

`c001` 不是只经历过一次“c002 没有上报”。

而是在多个高压单元里，连续观察到：

- `c002` 已做出过一次正式保密动作
- 后续又多次在灰区内偏向保护而不是揭发

这会逐步形成一种稳定认知负担：

- `c001` 会在后续决策里默认把 `c002` 视作“高压下更可能保密的人”

### 3.2 正确裁定

这类条目可以保留在 `CharacterModel.knowledge_state`，但必须压缩表达，例如：

- “知道 c002 在高压场景下更倾向保密而非即时揭发”

### 3.3 为什么允许保留

因为它已经不是：

- 当前 scene 的一次即时判断

而是：

- 经 repeated interaction 形成的稳定认知负担

它会持续影响：

- 风险评估
- 是否求助
- 是否共享更深信息

### 3.4 保留时的限制

即使允许保留，也不应写成：

- “c002 一定会保护自己”
- “c002 已完全站到自己这边”

因为那会把稳定倾向误写成硬事实或关系总账。

---

## 4. Borderline 场景 B：应删除的高价值当前路线判断

### 4.1 情况说明

“祭典人流是当前最可行脱身路线”看起来很重要，而且可能连续几轮都成立。

这很容易让系统误以为：

- 既然它跨了几轮，就可以沉积进 `CharacterModel`

### 4.2 正确裁定

这类条目仍应删除出 `CharacterModel`，保留到：

- `NarrativeState.current_route`
- `NarrativeState.primary_goal`
- handoff 的 current working set

### 4.3 为什么必须删除

因为它回答的仍然是：

- 当前怎么走

而不是：

- 这个角色长期知道什么

它即使跨了几轮，也仍是：

- 任务态判断
- 场景约束读取

不是角色结构。

### 4.4 最常见误判

系统最容易因为“连续三轮都成立”就把它误写成长期摘要。

但“连续成立”不等于“角色结构化”。

---

## 5. Borderline 场景 C：可保留，但必须裁剪掉 scene 痕迹的关系基底

### 5.1 情况说明

`c001.relations` 中出现：

```json
{
  "target_id": "c002",
  "relation_type": "guarded_ally",
  "trust_baseline": "medium",
  "recent_pattern_note": "最近三次高压场景里，对方都选择了保密与协助"
}
```

这里混合了两层内容：

1. 长期关系基底  
   `guarded_ally`
2. scene / sequence 级证据说明  
   “最近三次高压场景……”

### 5.2 正确裁定

应保留：

- `relation_type = guarded_ally`
- `trust_baseline = medium`

应删除或迁出：

- `recent_pattern_note`

### 5.3 为什么这样分

因为关系基底已经开始稳定影响后续行为选择，所以可以保留。

但“最近三次高压场景”的说明仍更像：

- handoff 证据
- review supporting context
- 关系变化依据

而不是长期关系字段本身。

### 5.4 正确压缩后的版本

```json
{
  "target_id": "c002",
  "relation_type": "guarded_ally",
  "trust_baseline": "medium"
}
```

---

## 6. Borderline 场景 D：应回到误判层，而不是留作稳定知情

### 6.1 情况说明

另一类模糊条目可能写成：

- “知道 c002 最终不会背叛自己”

它看起来像长期判断，也会强烈影响决策。

### 6.2 正确裁定

这类条目默认不应保留在 `knowledge_state` 作为稳定知情。

它更应被理解为：

- 角色的稳定误判
- 或高风险主观押注

如果确实要保留，应优先放到：

- `CharacterModel.misinformation`

而不是：

- `CharacterModel.knowledge_state`

### 6.3 为什么这点重要

否则系统会把：

- 角色强信念

误读成：

- 世界中已成立的认知事实

这会同时污染：

- 角色一致性
- 信息合法性
- review 裁定

---

## 7. 最小 keep-vs-drop 裁定表

| 候选条目 | 正确去向 | keep / drop | 核心理由 |
|---|---|---|---|
| `知道 c002 在高压下更倾向保密而非即时揭发` | `CharacterModel.knowledge_state` 压缩版 | keep | 已形成跨场景稳定认知负担 |
| `知道祭典人流是当前最可行脱身路线` | `NarrativeState` / handoff current working set | drop | 这是任务态路线判断，不是角色结构 |
| `guarded_ally + trust_baseline=medium` | `CharacterModel.relations` | keep | 已形成长期关系基底 |
| `recent_pattern_note: 最近三次高压场景...` | handoff / review supporting context | drop | 这是关系依据，不是长期关系字段 |
| `知道 c002 最终不会背叛自己` | `CharacterModel.misinformation` 或不保留 | drop from `knowledge_state` | 这是主观押注，不是稳定知情 |

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. keep-vs-drop 不能只看“这条信息重不重要”
2. 连续出现几轮，不等于就能进入长期角色摘要
3. 真正该保留的是稳定决策负担与长期关系基底
4. scene / sequence 级证据说明应留在 handoff、review 或当前工作面
5. 强主观押注应优先走 `misinformation`，而不是伪装成 `knowledge_state`

---

## 9. 一句话总结

`CharacterModel` 的 keep-vs-drop 边界，不在于“这条信息是不是有用”，而在于“它是否已经从当前任务判断沉淀成会持续塑造角色决策的长期结构”。 
