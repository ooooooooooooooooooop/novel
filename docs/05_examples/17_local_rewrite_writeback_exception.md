# 示例：Local Rewrite 写回顺序例外压测

## 文档目的

本文档提供一个最小但连续的 local `Rewrite` 压测样例，用于验证：

- 什么时候允许先修 `PlotUnit` / `NarrativeState`
- 什么时候必须在同一轮修复里补写 `FactLedger`
- 为什么这种例外不能被误用成默认写回顺序

它验证的不是：

- `Rewrite` 可以随意倒置所有对象顺序

它验证的是：

- root-cause-first 规则下，是否存在 bounded runtime-first exception

本文档主要对应：

- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/04_rewrite_workflow.md`

---

## 1. 测试定位

前面的 decision 已经固定了两件事：

1. ownership-sensitive 默认写回顺序是：先长期硬约束，再当前工作集，最后角色侧摘要
2. `Rewrite` 必须先修主根因对象，再按依赖顺序同步其余对象

因此当前真正待压测的，不是“能不能乱改顺序”，而是：

- 当根因本来就在 `PlotUnit` 或 `NarrativeState`
- 而 `FactLedger` 本身并没有记错

这时是否允许先修运行态，再决定是否需要补账。

如果这层不压，系统最容易出现三种坏结果：

1. 把 runtime-first exception 滥用成默认规则
2. 用“局部 rewrite”当借口，把应入账变化拖到下一轮
3. 先改 `CharacterModel` 摘要，再倒逼事实层配合

---

## 2. 测试前提

沿用当前 mock case，并假设以下硬约束已经成立：

```text
FactLedger
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

当前需要修的不是账本，而是一个局部失败单元：

```text
PlotUnit pu_scene_024
- 把 c001 写成仍准备试探东侧山门
- 把当前局面写得像“东侧也许还可混过去”
```

对应的 `ReviewIssue` 指向：

- 当前 `PlotUnit` 输出与 `FactLedger` 已成立 route / mission state 冲突
- 当前 `NarrativeState.current_route` 被错误写回旧路线假设

这里的关键判断是：

- 根因在局部 `PlotUnit` / `NarrativeState`
- 不在 `FactLedger`

---

## 3. 压测场景 A：允许的局部例外

### 3.1 问题形态

当前失败的 scene 只是把局部运行态写错了：

- 东侧封锁事实并没有错
- 强制撤离任务状态也没有错
- 错的是当前单元仍按旧路线理解局面

### 3.2 正确处理

这时允许先做：

1. 修正 `PlotUnit`，去掉“继续试探东侧山门”的错误推进
2. 修正 `NarrativeState.current_route`、`active_conflicts`、`open_questions`
3. 复查现有 `FactLedger` 条目是否仍足够支撑该局面
4. 如无新增正式状态变化，则不新增账本条目，直接进入 `Review`

### 3.3 为什么这是允许例外

因为这里并不是：

- 长期硬约束尚未落账

而是：

- 已落账硬约束没有被当前运行态正确继承

所以 runtime-first 在这里不是颠倒主从，而是：

- 先修主根因对象
- 再确认账本无需追加改动

### 3.4 这一步不该做什么

不应为了“顺手统一”去：

- 重写 `f_031`
- 重写 `f_032`
- 无理由改动 `CharacterModel.relations`

因为这些对象在本场景里不是根因，只需验证，不需乱改。

---

## 4. 压测场景 B：允许先修局部，但不能把补账拖到下一轮

### 4.1 新问题

在修这场戏时，团队发现原 scene 还漏掉了一个已正式成立的新变化：

- 巡查已当众收缴 `c001` 的出界令牌

如果本次 rewrite 决定把这条变化正式纳入修复结果，它就不再只是局部气氛调整，而是：

- resource / access state 已被外部动作改写

### 4.2 正确处理

此时可以先修：

- `PlotUnit`
- `NarrativeState`

但不能停在这里。

必须在同一轮 repair packet 里补上新的 `FactLedger` 条目，例如：

```json
{
  "fact_id": "f_033",
  "fact_type": "resource",
  "category": "token_confiscated",
  "statement": "c001 的出界令牌已被巡查当众收缴",
  "established_in": "scene_024_rewrite",
  "source_plotunit": "pu_scene_024_rewrite",
  "visibility": "public",
  "known_by": ["c001", "c002", "巡查相关角色", "reader"],
  "status": "active",
  "mutable": true
}
```

然后再进入 `Review`。

### 4.3 为什么这仍不算违背顺序

因为这里的例外只允许：

- 先修局部根因对象

但不允许：

- 把新成立的硬事实继续留在运行态里过一轮

也就是说，runtime-first 只允许出现在：

- repair packet 的起点

不能出现在：

- handoff 之后

---

## 5. 压测场景 C：不允许的假例外

### 5.1 错误做法

系统先把 scene 和 `NarrativeState` 修顺，然后说：

- “`FactLedger` 下轮再补”

此时 handoff 里留下的是：

- 当前路线已改
- 令牌已丢
- 任务压力更重

但账本仍未记录“令牌已被正式收缴”。

### 5.2 为什么这是错误

因为进入下一轮之后：

- `Continue` 会读取到一个仍然过旧的长期约束层
- `Rebuild` 也可能把这次正式变化当成只是当前压力

这会直接破坏：

- admission threshold
- ownership-sensitive writeback order
- review 复核的对象一致性

### 5.3 最小裁定

“先修运行态后补账”的允许范围，不包括：

- 跨 handoff
- 跨 `Review`
- 跨下一轮 `Continue`

---

## 6. 压测场景 D：不允许的 `CharacterModel`-first 修法

### 6.1 错误做法

系统试图通过先改：

- `CharacterModel.relations`
- `CharacterModel.knowledge_state`

来解释当前 scene 的合理性，例如：

- 先把 `c002` 写成“已稳定视 c001 为必须保护的盟友”
- 再倒推 scene 为什么会这样发展

### 6.2 为什么这是错误

因为 `CharacterModel` 在这里不是主根因对象。

如果：

- `FactLedger` 尚未成立新的 relation fact
- `NarrativeState` 也尚未同步新的当前压力与信息分布

那先改角色摘要只会制造一种假稳定：

- 像是角色长期结构已经变化
- 但世界约束层和运行态都还没跟上

### 6.3 最小裁定

local `Rewrite` 的允许例外不包括：

- 先改角色侧长期摘要，再等事实层追认

---

## 7. 四个场景的最小裁定表

| 场景 | 根因位置 | 是否允许 runtime-first | 额外要求 | 核心理由 |
|---|---|---|---|---|
| A. 局部旧路线残留 | `PlotUnit` / `NarrativeState` | 允许 | 仅复查现有 `FactLedger` 是否已足够 | 账本不是根因，局部修复即可 |
| B. 修局部时同时明确了新硬事实 | `PlotUnit` / `NarrativeState` 起步，但会触发新入账 | 允许起步，但不允许停在运行态 | 同一 repair packet 内补写 `FactLedger` | 新硬事实不能跨 handoff 留白 |
| C. 先修运行态，下轮再补账 | 表面像局部根因，实则把硬事实拖延 | 不允许 | 直接判定 repair 不完整 | 会让长期约束层对后续 workflow 失真 |
| D. 先改 `CharacterModel` 摘要 | 根因判断错误 | 不允许 | 应回到事实层或运行态层修复 | 摘要不能反向定义事实是否成立 |

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. local `Rewrite` 确实存在 bounded runtime-first exception
2. 这个例外只在根因位于 `PlotUnit` / `NarrativeState` 时成立
3. 一旦 rewrite 本轮产生新的正式状态变化，就必须在同一轮补账
4. `CharacterModel` 不能被拿来做事实层与运行态层之间的跳板
5. “允许例外”不等于“默认顺序可以倒过来”

---

## 9. 一句话总结

local `Rewrite` 只在修复局部根因时允许先改运行态，但任何在本轮正式成立的新硬事实都必须在同一轮补写回 `FactLedger`，不能跨 handoff 拖延。
