# 示例：Situation Change 入账阈值压测

## 文档目的

本文档提供一个最小但连续的 `situation change` 压测样例，用于验证：

- 哪些局势变化只应留在 `NarrativeState`
- 哪些局势变化已经跨过 `FactLedger` admission threshold
- “当前压力变化”与“世界状态变化”如何区分

它验证的不是：

- 文本写得是否紧张
- 局势描写是否充分

它验证的是：

- 系统是否能区分 tactical pressure 与 world-state change

本文档主要对应：

- `07_decisions/13_factledger_admission_thresholds.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/02_review_workflow.md`

---

## 1. 测试定位

前面的 ownership 样例已经压过：

- knowledge admission threshold
- relation admission threshold

但还有一类更容易模糊的边界：

- situation change

因为它既不像 knowledge 那样有 `known_by`
也不像 relation 那样有明确双方关系条目。

它最容易出现两种错误：

1. 只要局势一紧，就过早写进 `FactLedger`
2. 明明世界状态已经变化，却仍只留在 `NarrativeState`

---

## 2. 测试前提

沿用当前 mock case，并假设：

- `c001` 与 `c002` 正在携令撤离
- 巡查压力正在逼近
- 当前任务仍被理解为“潜离宗门边界并控制秘密扩散”

当前可运行状态简化如下：

```json
{
  "state_id": "s_018",
  "primary_goal": "携令撤离并控制秘密扩散",
  "active_conflicts": [
    "巡查正在收缩外环",
    "c002 的立场仍可能摇摆"
  ],
  "open_questions": [
    "外环哨卡是否已经收到正式封锁令",
    "撤离路线是否仍合法可用"
  ]
}
```

此时 `FactLedger` 中尚未成立以下事实：

- 外环已正式封锁
- 主任务已从潜离转为强制撤离
- `c001` 已被正式通缉

---

## 3. 压测场景 A：撤离压力上升，但世界状态还没改

### 3.1 新事件

本轮里：

- 巡查脚步逼近
- 远处出现更多火把
- `c001` 判断原路线风险显著上升

但尚未发生：

- 正式封锁令
- 第三方公开通报
- 路线被制度性关闭

### 3.2 正确处理

这一变化应先写入：

- `NarrativeState.active_conflicts`
- `NarrativeState.open_questions`
- 必要时 `PlotUnit.state_change_summary`

但不应直接写入：

- `FactLedger.location_state`
- `FactLedger.status_change`

### 3.3 原因

因为这一步成立的是：

- 当前压力更强
- 当前决策空间变窄

而不是：

- 世界中的 route / legality / control 已被正式改写

---

## 4. 压测场景 B：外环收到正式封锁令，路线状态被改写

### 4.1 新事件

后续单元里，巡查队长在可见范围内下令：

- 封锁东侧外环
- 所有出界口令立即停用

且该命令已被多个哨点执行。

### 4.2 正确处理

此时应新增 `FactLedger` 条目，例如：

```json
{
  "fact_id": "f_031",
  "fact_type": "location_state",
  "category": "checkpoint_lockdown",
  "statement": "宗门东侧外环已被正式封锁，原撤离口令暂时失效",
  "established_in": "scene_019",
  "source_plotunit": "pu_scene_019",
  "visibility": "public",
  "known_by": ["c001", "c002", "巡查相关角色", "reader"],
  "status": "active",
  "mutable": true
}
```

然后同步：

- `NarrativeState.active_conflicts`
- `NarrativeState.primary_goal` 的当前可行路径

### 4.3 为什么这次必须入账

因为它已经满足：

1. 有明确且可追溯的成立来源
2. 路线 legality / availability 已被正式改变
3. 后续 scene 不能再按“原路线仍可用”运行

---

## 5. 压测场景 C：主角临时决定改走水路，但任务定义没正式变

### 5.1 新事件

`c001` 在压力下做出即时判断：

- 放弃东侧山门
- 先改走废弃水道

但这只是当前战术选择。
外部世界并未因此产生新的制度状态。

### 5.2 正确处理

应更新：

- `NarrativeState.primary_goal`
- `NarrativeState.current_route`
- `PlotUnit` 的当前决策输出

但不应因为“路线换了”就直接新增：

- `FactLedger.status_change = 撤离任务已正式改写`

### 5.3 原因

因为这一步成立的是：

- 当前策略变了

而不是：

- 世界中 mission state 已被外部事实正式改写

---

## 6. 压测场景 D：潜离失败已被公开承认，任务状态正式改写

### 6.1 新事件

后续单元里：

- 巡查方公开播报“令牌失控，立刻截捕”
- 原潜离窗口被正式关闭
- `c001 / c002` 必须转入强制逃逸与封口

此时主任务不再只是主角自己的战术理解，而是被外部世界正式改写。

### 6.2 正确处理

此时应新增 `FactLedger` 条目，例如：

```json
{
  "fact_id": "f_032",
  "fact_type": "status_change",
  "category": "mission_state_shift",
  "statement": "本轮行动已从潜离窗口转为公开截捕下的强制撤离",
  "established_in": "scene_020",
  "source_plotunit": "pu_scene_020",
  "visibility": "public",
  "known_by": ["c001", "c002", "巡查相关角色", "reader"],
  "status": "active",
  "mutable": true
}
```

然后同步：

- `NarrativeState.primary_goal`
- `NarrativeState.active_conflicts`
- 相关 `ForeshadowGraph` 或后续 route 决策

### 6.3 为什么这次必须入账

因为它已经不是：

- 当前角色的主观换路

而是：

- 外部世界已正式把任务状态改写成新的硬约束

如果不入账，后续很容易误写回“仍处于潜离窗口”。

---

## 7. 四个场景的最小裁定表

| 场景 | 应先写哪里 | 不应直接写哪里 | 核心理由 |
|---|---|---|---|
| A. 压力上升 | `NarrativeState` | `FactLedger` | 只是当前压力变化，不是世界状态改写 |
| B. 正式封锁 | `FactLedger` -> `NarrativeState` | 只停在 `open_questions` | route / legality 已被制度性改变 |
| C. 临时改道 | `NarrativeState` | `FactLedger` mission change | 只是当前策略变化，不是正式算数 |
| D. 任务状态被公开改写 | `FactLedger` -> `NarrativeState` | 只停在当前 goal 文本 | mission state 已成为硬约束 |

---

## 8. 如果系统写错，会出现什么

### 8.1 过早入账

会导致：

- `FactLedger` 充满短时战术变化
- `Rebuild` 读到过重且噪音过多的状态层
- 后续 agent 把“当前紧张”误当成“世界已变”

### 8.2 迟迟不入账

会导致：

- 已正式封锁的地点在后文像没封一样
- 已公开改写的任务状态被写回旧目标
- 长链恢复时丢失真实 route constraint

---

## 9. 这份样例验证了什么

这份样例主要验证四件事：

1. situation change 不是“局势一变就入账”
2. tactical pressure 与 world-state change 必须分开
3. route / legality / mission state 一旦被正式改写，就应进入 `FactLedger`
4. `NarrativeState` 仍是承接当前压力与即时策略的第一层

---

## 10. 一句话总结

`situation change` 只有在世界状态已被正式改写时才应入账，而不是在当前局势刚开始变紧时就入账。
