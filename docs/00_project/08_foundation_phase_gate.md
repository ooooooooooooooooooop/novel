# Foundation Phase Gate

## 目的

本文档用于把 foundation phase 的离场条件压成最小 gate。

它回答的不是：

- 当前 foundation 有没有进展
- 哪个边界还值不值得再补样例

它回答的是：

- 什么情况下可以通过 foundation gate
- 什么情况下必须继续留在 foundation
- 当前为什么仍处于 blocked 状态

---

## 1. 当前 gate 结论

当前 gate 结论是：

- `pass`

当前项目已经具备：

- foundation skeleton
- object set
- workflow loop
- harness framing

并且现在已经具备：

- 足够明确的 pre-implementation boundary lock

所以当前状态不是：

- 设计缺块

而是：

- foundation gate 已通过，下一步应转入 transition planning

---

## 2. Gate 设计原则

当前 gate 只检查最小 through / block 条件。

它不检查：

- 最终实现方案
- 技术栈
- 机器格式
- UI

它只检查：

- foundation 是否已经足够稳定到值得让 implementation pressure 进入

---

## 3. Through 条件

只有当以下条件同时满足时，foundation phase 才能通过 gate。

## 3.1 `through_01` 项目边界稳定

要求：

- 当前阶段负责什么、不负责什么已经稳定
- 不再频繁引入新的顶层抽象
- 不再把实现压力当成当前设计的默认驱动

当前状态：

- `pass`

## 3.2 `through_02` 八个核心对象稳定

要求：

- 核心对象集合不再频繁变化
- 对象主职责明确
- 当前主要工作已从“补对象”转为“压边界”

当前状态：

- `pass`

## 3.3 `through_03` workflow 闭环稳定

要求：

- `Rebuild -> Review -> Continue / Rewrite / Replan` 已形成稳定顺序
- `Continue` 与 `Rewrite` 写回顺序明确
- handoff contract 已成为正式接口，而不是局部 prose 习惯

当前状态：

- `pass`

## 3.4 `through_04` example / rule / decision 三层可互证

要求：

- 关键规则已由样例压实
- 样例结论已写回规则与决策层
- onboarding 层能正确暴露这些结果

当前状态：

- `pass`

## 3.5 `through_05` 三个脆弱边界簇完成 pre-implementation lock

要求：

- Track 1 有明确“当前 anchor set 是否足够”的 gate 结论
- Track 2 有明确“bounded runtime-first exception 不得放宽”的 gate 结论
- Track 3 有明确“evidence leakback 属于 no-regression item”的 gate 结论

当前状态：

- `pass`

原因：

- checkpoint judgment、transition memo、phase gate 与 pre-implementation boundary lock 已形成闭环
- 三条边界已有明确 no-regression / no-loosening 结论

---

## 4. Block 条件

只要以下任一条件成立，就应继续留在 foundation。

## 4.1 `block_01` 边界仍主要依赖隐含理解

判定方式：

- 若关键边界仍要靠“懂的人自然懂”才能运作
- 或仍大量依赖局部 prose 提醒

则：

- `blocked`

当前状态：

- `pass`

说明：

- 规则、决策、样例、lock 文档都已成文

## 4.2 `block_02` hard fact / working state / supporting evidence 仍可能在实现压力下重新混层

判定方式：

- 若当前没有明确禁止回弹项
- implementation 进入后很可能重新出现：
  - hard fact 被 prose 代替
  - handoff 代替未完成同步
  - evidence leakback 重新合法化

则：

- `blocked`

当前状态：

- `pass`

## 4.3 `block_03` phase exit 仍无法用短句清楚交接

判定方式：

- 若一个新 agent 仍无法用短句说清：
  - 为什么现在不能进实现
  - 还差哪几项
  - 哪些风险现在接受

则：

- `blocked`

当前状态：

- `pass`

说明：

- checkpoint、transition memo、phase gate、boundary lock 已可形成短句交接

---

## 5. 当前 gate 裁定

### 已通过

- `through_01`
- `through_02`
- `through_03`
- `through_04`

### 当前阻塞

- none

一句话说：

- 当前 foundation gate 已通过
- 下一步不再是补 foundation 缺口，而是进入 transition planning

---

## 6. 当前最小通关动作

foundation gate 通过后，当前最小后续动作是：

1. 在 transition planning 中继承当前 boundary lock
2. 明确 implementation planning 可以讨论什么、不能重新打开什么
3. 继续保持“不直接跳过规划进入实现”

这意味着：

- 现在不需要再补新本地反例
- 现在需要把已有结论锁成 phase gate 约束

---

## 7. 最小 gate 模板

```text
Foundation phase gate

- gate_status: blocked
- passed:
  - project boundary stable
  - core object set stable
  - workflow loop stable
  - example / rule / decision alignment stable
- blocked_by:
  - no explicit pre-implementation lock on Track 1
  - no explicit pre-implementation lock on Track 2
  - no explicit pre-implementation lock on Track 3
- next_required_action:
   - enter transition planning with boundary locks inherited unchanged
```

---

## 8. 一句话总结

当前 foundation phase 已经通过 gate，不是因为问题都消失了，而是因为进入下一阶段前最容易回弹的三条边界已经被正式锁成了“不可放宽项”。
