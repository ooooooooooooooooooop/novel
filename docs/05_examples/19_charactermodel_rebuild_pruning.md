# 示例：CharacterModel Rebuild Pruning 压测

## 文档目的

本文档提供一个 repeated-loop 样例，用于验证：

- 当 `CharacterModel` 已经吸收了过多运行态噪音时，`Rebuild` 应如何做 pruning
- pruning 不应把真正的长期角色负担一并删掉
- handoff 里应如何区分“保留的角色基底”和“应回退到当前工作面”的内容

它验证的不是：

- `Rebuild` 只要能恢复一个大概状态就算完成

它验证的是：

- `Rebuild` 是否能把 stale runtime cache 压回角色侧长期摘要

本文档主要对应：

- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`

---

## 1. 测试定位

前一个样例已经证明：

- `CharacterModel` 会在 repeated `Continue / Rebuild` 中膨胀

但还缺一层更关键的验证：

- 当膨胀已经发生，`Rebuild` 如何把它压回正确层次

如果没有这层，项目会落入两种同样糟糕的错误：

1. 为了防膨胀，把角色摘要删得过空，连长期负担也丢掉
2. 为了保守起见，什么都不删，让过期运行态继续伪装成长期角色结构

因此这份样例的重点不是“提醒要克制”，而是：

- 给出 first-pass pruning 裁定

---

## 2. 测试前提

沿用 `18_charactermodel_summary_bloat.md` 的错误膨胀版本，并假设系统经历过：

- 多轮 `Continue`
- 一次不充分 handoff
- 一次 bounded-package 不足后的 `Rebuild`

此时一个错误膨胀的 `CharacterModel` 可能像这样：

```json
{
  "c001": {
    "short_term_goal": "优先活着从西侧水路离开",
    "knowledge_state": [
      "知道 c002 已察觉异常",
      "知道西侧水路当前风险更高",
      "知道东侧哨卡口令已经失效",
      "知道今晚不宜正面突破",
      "知道 c002 暂时不会背叛自己"
    ],
    "relations": [
      {
        "target_id": "c002",
        "relation_type": "ally",
        "trust_baseline": "medium_to_high",
        "current_temperature": "strained_but_softening",
        "latest_scene_shift": "scene_027 after argument"
      }
    ]
  }
}
```

而当前更可靠的对象层还包括：

```text
FactLedger
- f_022: c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

这里最关键的判断是：

- `CharacterModel` 已经混进了账本事实、当前运行态、scene 温度

---

## 3. Pruning 场景 A：应被回退到当前工作面的内容

### 3.1 候选内容

以下内容出现在 `CharacterModel` 中：

- “西侧水路当前风险更高”
- “今晚不宜正面突破”
- `short_term_goal = 优先活着从西侧水路离开`
- `latest_scene_shift = scene_027 after argument`

### 3.2 正确处理

`Rebuild` 应把这些内容视为：

- 当前工作面
- 或局部历史痕迹

而不是角色长期结构。

因此应：

1. 从 `CharacterModel.knowledge_state` 删除“当前路线 / 当前风险 / 当前战术判断”
2. 从 `CharacterModel.relations` 删除 `current_temperature`、`latest_scene_shift` 这类 scene 级痕迹
3. 若这些内容当前仍有用，应回写到新的 `NarrativeState` 或 handoff `current_working_set`

### 3.3 为什么不能保留

因为这些内容回答的是：

- 这一轮怎么走
- 这一场戏气氛如何

而不是：

- 这个角色长期知道什么
- 这个角色与对方的长期关系基底是什么

---

## 4. Pruning 场景 B：不应被删掉的长期负担

### 4.1 候选内容

以下内容虽然也出现在 `CharacterModel.knowledge_state` / `relations`，但不应被 pruning 掉：

- `c001` 知道 `c002` 已经掌握自己异常存在，并做出过保密动作
- `c002` 与 `c001` 已进入 guarded risk-bound alliance

### 4.2 正确处理

`Rebuild` 应保留它们的压缩版本，例如：

```json
{
  "c001": {
    "knowledge_state": [
      "知道 c002 已掌握自己异常存在，并在高压下做出过保密选择"
    ],
    "relations": [
      {
        "target_id": "c002",
        "relation_type": "guarded_risk_bound_ally",
        "trust_baseline": "low_to_medium"
      }
    ]
  }
}
```

### 4.3 为什么这些要保留

因为这些内容会持续影响：

- 信任判断
- 选择成本
- 后续协作边界

它们不是当前工作面的临时噪音，而是角色后续决策的长期基底。

---

## 5. Pruning 场景 C：账本事实不应被错误吸进角色摘要

### 5.1 候选内容

`CharacterModel.knowledge_state` 中包含：

- “东侧哨卡口令已经失效”
- “宗门东侧外环已被正式封锁”

### 5.2 正确处理

`Rebuild` 应判断：

- 这些是世界状态
- 主存仍应看 `FactLedger`

因此不应把它们当成角色侧摘要主存继续保留。

如果它们确实仍影响当前 scene，应：

- 保持在 `FactLedger`
- 由新的 `NarrativeState` 读取当前可运行子集

### 5.3 为什么这一步重要

因为如果把这些世界状态长期塞进 `CharacterModel`，后续 agent 很容易误以为：

- 这是角色结构的一部分

而不是：

- 角色当前读取到的一组外部约束

---

## 6. Pruning 场景 D：不要把 pruning 变成无脑删减

### 6.1 错误做法

为了防膨胀，系统把 `knowledge_state` 和 `relations` 几乎清空，只留下：

```json
{
  "c001": {
    "knowledge_state": [],
    "relations": []
  }
}
```

### 6.2 为什么这同样错误

因为这会让 `Rebuild` 之后的角色模型失去：

- 持续性的认知负担
- 长期关系基底
- 对后续行为选择的稳定解释力

这类过度 pruning 会导致：

- 角色重新变成只靠当前状态驱动
- 长链一致性被另一种方式破坏

### 6.3 最小裁定

pruning 不是：

- “越少越好”

而是：

- 只删掉当前工作面噪音，保留长期决策基底

---

## 7. Rebuild 后的最小交接要求

如果 `Rebuild` 对 `CharacterModel` 做了 pruning，handoff 至少应明确三件事。

### 7.1 保留了什么

例如：

- 哪些 `knowledge_state` 条目被保留为长期负担
- 哪些 `relations` 条目被保留为长期关系基底

### 7.2 删掉了什么

例如：

- 哪些内容被判定为 scene 级温度
- 哪些内容被判定为当前路线或当前风险

### 7.3 被删掉的内容回到了哪里

例如：

- 回到 `NarrativeState`
- 回到 handoff 的 current working set
- 回到 `FactLedger` 的相关引用

如果只说“已简化 CharacterModel”，而不说明删了什么、为什么删、删后去哪，交接仍然不合格。

---

## 8. 最小裁定表

| 候选内容 | Pruning 后去向 | 是否保留在 `CharacterModel` | 核心理由 |
|---|---|---|---|
| 当前西侧水路更危险 | `NarrativeState` | 不保留 | 当前工作面 |
| 今晚不宜正面突破 | `NarrativeState` / handoff current working set | 不保留 | 当前战术判断 |
| `scene_027` 后信任短暂回升 | `PlotUnit` / `NarrativeState` | 不保留 | scene 级关系温度 |
| `c002` 已做过正式保密动作 | `FactLedger` + 压缩进 `knowledge_state` | 保留压缩版 | 长期决策负担 |
| guarded risk-bound alliance | `FactLedger relation` + `CharacterModel.relations` | 保留压缩版 | 长期关系基底 |
| 东侧封锁已成立 | `FactLedger`，必要时投影到 `NarrativeState` | 不作为角色摘要主存保留 | 世界状态，不是角色结构 |

---

## 9. 这份样例验证了什么

这份样例主要验证五件事：

1. `Rebuild` 不只是恢复对象，也应在必要时修剪膨胀的角色摘要
2. pruning 的目标是删掉 stale runtime cache，而不是删空角色结构
3. `CharacterModel` 保留的是长期负担与长期关系基底
4. 当前路线、当前风险、scene 级温度应回退到 `NarrativeState` 或局部对象
5. handoff 必须说明 pruning 删除了什么以及这些内容回到了哪里

---

## 10. 一句话总结

`Rebuild` 对 `CharacterModel` 的 pruning 不是把摘要删薄，而是把过期运行态从角色模型里赶回它原本所属的当前工作层，同时保住真正的长期决策基底。
