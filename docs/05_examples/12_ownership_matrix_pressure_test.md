# 示例：Ownership Matrix 压测

## 文档目的

本文件提供一个最小但连续的 ownership 压测样例，用于验证：

- `CharacterModel`
- `NarrativeState`
- `FactLedger`

在 knowledge 与 relation 两组高风险边界上，是否已经有足够稳定的分工。

它验证的不是：

- 普通续写是否好看

它验证的是：

- 哪些知情变化只该留在当前工作集
- 哪些知情变化必须升级为 `FactLedger`
- 哪些关系变化只是当前张力
- 哪些关系变化已经跨过“正式算数”的阈值

本文件主要对应：

- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/03_workflow_order_decisions.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/02_review_workflow.md`

---

## 1. 测试定位

这份样例不追求大而全。

它只压两类最容易漂移的 ownership 问题：

1. knowledge ownership
2. relation ownership

一句话定义：

`ownership_matrix_pressure_test` 的任务，是验证系统能否区分：

- 当前这轮工作必须知道什么
- 世界中已经正式算数了什么

---

## 2. 测试前提

沿用当前 mock case：

- 作品：`残雪归宗`
- 当前人物：`c001 / 沈青`、`c002 / 顾临渊`
- 当前段落：令牌争夺后，进入撤离与封口阶段

假设当前已知基线如下。

### 2.1 角色侧长期摘要

```json
{
  "c001": {
    "relations": [
      {
        "target_id": "c002",
        "relation_type": "uncertain_dependence",
        "trust_baseline": "low_to_medium"
      }
    ],
    "knowledge_state": [
      "知道 c002 已察觉自己身上有异常",
      "不知道 c002 会保密、利用还是上报"
    ]
  },
  "c002": {
    "relations": [
      {
        "target_id": "c001",
        "relation_type": "protected_interest",
        "trust_baseline": "guarded"
      }
    ],
    "knowledge_state": [
      "知道 c001 身上存在异常力量痕迹",
      "不知道异常力量的真实来源"
    ]
  }
}
```

### 2.2 当前可运行状态

```json
{
  "state_id": "s_015",
  "primary_goal": "带令撤离，并控制秘密扩散范围",
  "private_information_map": {
    "c001": ["令牌已到手", "c002 已察觉异常"],
    "c002": ["c001 身上有异常力量痕迹", "尚未确认真相"]
  },
  "active_relation_tensions": [
    "c001 不确定 c002 会不会保密",
    "c002 在监察职责与个人判断之间摇摆"
  ]
}
```

### 2.3 已成立硬事实

```json
[
  {
    "fact_id": "f_015",
    "fact_type": "knowledge",
    "statement": "c002 已确认 c001 身上存在异常力量痕迹",
    "known_by": ["c002"]
  },
  {
    "fact_id": "f_018",
    "fact_type": "relation",
    "statement": "c001 与 c002 进入带保密压力的高风险半合作边缘",
    "known_by": ["c001", "c002", "reader"]
  }
]
```

---

## 3. 压测场景 A：知情变化还没到入账阈值

### 3.1 新事件

在撤离途中，`c002` 试探性地说：

- “我不会现在问你那股力量是什么。”

`c001` 因此得到一个新判断：

- `c002` 暂时不会立刻揭发自己

但此时并没有发生：

- 正式承诺
- 第三方见证
- 制度层立场转移
- 真相公开

### 3.2 正确的 ownership 处理

这一步应先写入：

- `NarrativeState.private_information_map`
- `NarrativeState.active_relation_tensions`
- 必要时 `PlotUnit.information_shift / relation_shift`

可以更新：

- `CharacterModel.knowledge_state` 的角色侧摘要
- `CharacterModel.relations` 的长期基底描述

但不应直接新增：

- “`c002` 已决定保密” 这种 `FactLedger` knowledge fact
- “`c001` 与 `c002` 已建立稳定互信” 这种 `FactLedger` relation fact

### 3.3 原因

因为此时成立的是：

- 当前工作集中的判断变化
- 当前关系张力的偏移

而不是：

- 世界中已经算数的长期硬约束

### 3.4 错误写法

错误写法 A：

- 直接在 `FactLedger` 新增“`c002` 已保密”

问题：

- 这会把暂时克制误写成正式立场

错误写法 B：

- 直接把 `CharacterModel.relations` 改成“stable trust”

问题：

- 这会让角色长期基底被单场景波动污染

---

## 4. 压测场景 B：知情变化跨过入账阈值

### 4.1 新事件

后续一单元里，`c002` 明确对巡查队说：

- 自己未发现与禁术失控有关的直接证据

并主动替 `c001` 拦下进一步盘查。

此时系统已能判断：

- `c002` 不只是“暂时没问”
- 而是正式做出一次会约束后文的保密动作

### 4.2 正确的 ownership 处理

此时应新增或更新一条 `FactLedger` knowledge / consequence fact，例如：

```json
{
  "fact_id": "f_022",
  "fact_type": "knowledge",
  "statement": "c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断",
  "known_by": ["c002", "reader"],
  "status": "active"
}
```

然后同步：

- `NarrativeState.private_information_map`
- `CharacterModel.knowledge_state`

### 4.3 为什么这次必须入账

因为它已经满足至少三个条件：

1. 不是单场景猜测，而是明确行动
2. 会约束后续合法性与立场判断
3. 若后文忽略，会直接造成连续性错误

### 4.4 这一步验证什么

它验证：

- knowledge ownership 不是“谁都能记”
- 而是要区分当前判断与已成立知情事实

---

## 5. 压测场景 C：关系张力变化还没到关系事实

### 5.1 新事件

`c001` 在林间短暂停步，把令牌暂时交给 `c002` 保管数息，以便自己处理旧伤。

这会立刻导致：

- 当前信任张力明显上升
- 当前关系风险明显变化

### 5.2 正确的 ownership 处理

应先更新：

- `PlotUnit.relation_shift`
- `NarrativeState.active_relation_tensions`
- 必要时 `trust_map_delta`

可以温和更新：

- `CharacterModel.relations` 中的长期基底描述

但不应立刻新增：

- “两人已建立稳定盟友关系” 这种 `FactLedger relation`

### 5.3 原因

因为这一步成立的是：

- 当前张力与局势偏移

而不是：

- 世界中已经被确认、公开或高后果化的关系事实

---

## 6. 压测场景 D：关系变化跨过入账阈值

### 6.1 新事件

后续一单元里，`c002` 在第三方可见的情况下替 `c001` 承担巡查风险，并由此失去原本的中立位置。

这意味着两人关系已不再只是：

- 当前互相试探

而是已经变成：

- 会持续约束后文阵营、风险与行为选择的正式关系转折

### 6.2 正确的 ownership 处理

此时应把关系变化写入 `FactLedger` relation，例如：

```json
{
  "fact_id": "f_023",
  "fact_type": "relation",
  "statement": "c001 与 c002 已在巡查压力下形成对外风险绑定的临时同盟",
  "status": "active",
  "known_by": ["c001", "c002", "巡查相关角色", "reader"]
}
```

然后同步：

- `NarrativeState.active_relation_tensions`
- `CharacterModel.relations`

### 6.3 为什么这次必须入账

因为它已经满足：

1. 关系变化被明确确认
2. 会持续约束后续阵营与行为
3. 若不入账，后文很容易把两人又写回普通试探状态

---

## 7. 四个场景的最小裁决表

| 场景 | 应先写哪里 | 不应直接写哪里 | 核心理由 |
|---|---|---|---|
| A. 暂时保密倾向 | `NarrativeState` | `FactLedger` 新保密事实 | 只是当前判断，不是正式算数 |
| B. 明确保密动作 | `FactLedger` -> `NarrativeState` -> `CharacterModel` | 只停在 `NarrativeState` | 已跨过长期约束阈值 |
| C. 当前信任上升 | `NarrativeState` | `FactLedger` 新稳定盟友事实 | 只是当前关系张力变化 |
| D. 对外风险绑定 | `FactLedger` -> `NarrativeState` -> `CharacterModel` | 只停在 `active_relation_tensions` | 已成为会约束后文的关系事实 |

---

## 8. 若系统写错，会出现什么

### 8.1 过早入账

会导致：

- `FactLedger` 膨胀
- 本来只是局部波动的东西，被误写成长期事实
- 后续 `Review` 误报连续性冲突

### 8.2 迟迟不入账

会导致：

- 长期连续性只能靠 `NarrativeState` 维持
- `Rebuild` 后容易丢失关键知情或关系转折
- 后续 `Continue` 重新猜测已成立事实

### 8.3 把角色摘要写成总账

会导致：

- `CharacterModel` 膨胀成第二个运行态对象
- 审查时无法判断到底是角色结构变了，还是只是当前局势变了

---

## 9. 这份样例验证了什么

这份样例主要验证四件事：

1. ownership matrix 至少已经能区分“当前变化”和“长期算数”
2. knowledge 与 relation 两类高风险信息都可以按同一三层结构理解
3. 默认写回顺序 `FactLedger -> NarrativeState -> CharacterModel` 在跨阈值场景里是可解释的
4. 当前 unresolved boundary 已从“谁负责什么”收窄为“什么时候跨阈值”

---

## 10. 一句话总结

ownership matrix 真正要解决的，不是谁能描述某个变化，而是谁有权把这个变化升级成会约束后文的正式状态。
