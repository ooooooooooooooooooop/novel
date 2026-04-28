# 示例：CharacterModel 长期摘要膨胀压测

## 文档目的

本文档提供一个 long-chain counterexample，用于验证：

- `CharacterModel` 在 repeated `Continue / Rebuild` 下会不会吸收过多当前工作面
- `knowledge_state` 与 `relations` 何时仍是角色侧长期摘要
- 何时它们已经开始膨胀成第二个 `NarrativeState`

它验证的不是：

- `CharacterModel` 能不能随叙事推进而变化

它验证的是：

- 角色侧长期摘要的允许粒度与失控边界

本文档主要对应：

- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `02_data_models/09_field_rules.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 1. 测试定位

当前项目已经固定了两层共识：

1. `CharacterModel` 不应膨胀成第二个 `NarrativeState`
2. `knowledge_state` / `relations` 只能保留角色侧长期摘要，而不是吞掉账本或当前工作集

但在长链运行里，仍存在一个容易被低估的问题：

- 每次 `Continue` 都“顺手补一点角色摘要”
- 每次 `Rebuild` 又把上一轮摘要继续压回角色模型

结果会让 `CharacterModel` 慢慢变成：

- 当前路线记录
- 当前风险列表
- 当前局势解释器
- 当前关系温度流水账

如果这层不压，系统最容易出现三种坏结果：

1. `CharacterModel.knowledge_state` 变成第二个 `FactLedger` 加第二个 `NarrativeState`
2. `CharacterModel.relations` 变成按 scene 记温度的关系流水账
3. `Rebuild` 开新工作面时，agent 误把过期运行态当成长久角色基底

---

## 2. 测试前提

沿用当前 mock case，并假设以下约束已经成立：

```text
FactLedger
- f_022: c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

在这一阶段，`CharacterModel` 的合理长期摘要应仍然比较克制，例如：

```json
{
  "c001": {
    "relations": [
      {
        "target_id": "c002",
        "relation_type": "guarded_risk_bound_ally",
        "trust_baseline": "low_to_medium"
      }
    ],
    "knowledge_state": [
      "知道 c002 已察觉自己身上的异常并做出过一次保密动作"
    ]
  },
  "c002": {
    "relations": [
      {
        "target_id": "c001",
        "relation_type": "guarded_protective_alignment",
        "trust_baseline": "guarded"
      }
    ],
    "knowledge_state": [
      "知道 c001 身上存在危险异常，但仍未掌握真实来源"
    ]
  }
}
```

这里保留的是：

- 持续影响后续判断的长期负担
- 长期关系基底

而不是：

- 当前走哪条路
- 当前哪条哨卡更近
- 当前这一场戏的具体情绪温度

---

## 3. Loop 1：第一次膨胀诱因

### 3.1 新推进

在后续若干个 `Continue` 中，又连续出现了这些变化：

- 西侧水路风险上升
- `c001` 一度想放弃令牌
- `c002` 在一场争执后短暂提高了对 `c001` 的信任
- 当前最优目标从“保令撤离”改成“优先活着出界”

### 3.2 错误写法

系统如果每次都把这些内容直接写回 `CharacterModel`，就会得到类似结果：

```json
{
  "c001": {
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
    ],
    "short_term_goal": "优先活着从西侧水路离开"
  }
}
```

### 3.3 为什么这是膨胀

因为这里混进来的内容里，有大量本应属于：

- `NarrativeState`
- `FactLedger`
- `PlotUnit`

的当前工作面信息。

它们不是角色侧长期摘要，而是：

- 当前路径判断
- 当前战术策略
- 当前场景温度
- 当前单元的关系摆动

---

## 4. Loop 1 后的第一次错误恢复

### 4.1 退化条件

bounded package 不足后，系统进入一次 `Rebuild`。

此时如果 agent 读到的是一个已经膨胀的 `CharacterModel`，它很容易误判：

- “西侧水路是这个角色长期认知里最关键的信息”
- “当前 softening 的关系温度已经是长期关系基底”
- “当前最优撤离策略已经是角色稳定目标”

### 4.2 错误结果

错误恢复会把这些过期运行态误当成角色结构：

- 把临时路线选择误读为角色长期偏好
- 把一次争执后的温度变化误读为关系基底已升级
- 把当前保命策略误写成稳定长目标

### 4.3 为什么这会污染长链

因为下一轮 `Continue` 会基于这些假长期摘要继续写。

这会造成：

- 角色判断越来越被旧运行态绑死
- 当前工作面与角色模型互相复制
- `Rebuild` 越做越像在读过期状态缓存

---

## 5. 正确写法：吸收长期负担，不吸收工作面噪音

### 5.1 正确保留的内容

如果这些推进确实带来了长期角色侧影响，`CharacterModel` 可以只吸收如下压缩结果：

- `c001` 知道 `c002` 已不再只是旁观者，而是曾承担实际保密成本
- `c002` 知道自己已被卷入与 `c001` 绑定的高风险选择
- 两人的关系基底可从“半合作边缘”压成“guarded risk-bound alliance”

### 5.2 不该吸收的内容

以下内容不应继续沉积在 `CharacterModel`：

- 当前哪条路线更优
- 当前哪处哨卡更危险
- 当前追捕距离有没有缩短
- 当前 scene 里信任温度是升是降
- 当前是否“暂时不会背叛”

这些应分别留在：

- `NarrativeState`
- `FactLedger`
- `PlotUnit`

### 5.3 正确压缩后的角色侧摘要

正确的 `CharacterModel` 更像：

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

而不是把所有当前压力逐条抄进去。

---

## 6. Loop 2：第二次膨胀诱因

### 6.1 新推进

在第一次恢复后的后续推进中，又发生：

- `c001` 的出界资格被正式剥夺
- `c002` 对外中立身份进一步受损
- 当前最优方案从水路改成借祭典人流脱离

### 6.2 正确分层

这里应分成三层处理：

1. 资格剥夺与身份受损  
   先看是否进入 `FactLedger`
2. 当前改走祭典人流  
   留在 `NarrativeState`
3. 若这些变化长期改变两人的行为基底  
   才压缩回 `CharacterModel`

### 6.3 错误写法

如果系统继续把这些内容都加进 `CharacterModel`，就会得到一种越来越重的伪摘要：

- 像是“什么都记了”
- 但其实把长期结构、当前局势和账本事实全混到一起

这类“全记”不是稳，而是：

- 失去层次
- 失去主从
- 失去可恢复性

---

## 7. 最小裁定表

| 候选内容 | 正确去向 | 是否应沉积进 `CharacterModel` | 核心理由 |
|---|---|---|---|
| `c002` 曾正式替 `c001` 保密 | `FactLedger`，必要时压缩进 `knowledge_state` | 可压缩保留 | 这是长期决策负担 |
| 东侧外环已封锁 | `FactLedger` | 不应直接作为角色摘要主存 | 这是世界状态，不是角色结构 |
| 当前西侧水路更危险 | `NarrativeState` | 不应保留 | 这是当前工作面 |
| 本场戏争执后信任短暂回升 | `NarrativeState` / `PlotUnit` | 不应按 scene 沉积 | 这是局部温度，不是长期基底 |
| 两人已进入 guarded risk-bound alliance | `FactLedger relation` + `CharacterModel.relations` | 可保留压缩版本 | 这是长期关系基底变化 |
| 当前撤离计划改成借祭典人流 | `NarrativeState` | 不应保留 | 这是当前策略，不是角色长期结构 |

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. `CharacterModel` 可以成长，但不能吸收整个当前工作面
2. `knowledge_state` 只应保留长期影响决策的认知负担
3. `relations` 只应保留长期关系基底，而不是 scene-by-scene 温度记录
4. repeated `Rebuild` 会放大膨胀问题，因为过期运行态会被误读成角色结构
5. “摘要更长”不等于“系统更稳”

---

## 9. 一句话总结

`CharacterModel` 的长期摘要只该吸收会持续改变角色决策基底的内容，而不该把当前路线、当前风险和当前关系温度一路沉积成第二个 `NarrativeState`。
