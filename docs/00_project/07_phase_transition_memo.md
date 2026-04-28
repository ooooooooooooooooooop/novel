# Phase Transition Memo

## 目的

本文档用于把 foundation checkpoint 的结论进一步落成可执行的阶段转移判断。

它回答的不是：

- 当前 foundation 有没有价值
- 哪个对象还能继续优化

它回答的是：

- 当前 residual risk 中，哪些已经可以接受
- 哪些必须在 implementation pressure 进入之前继续压实
- 哪些问题属于实现阶段再处理更合理
- 当前阶段为什么应继续留在 foundation design，而不是直接切到实现阶段

---

## 1. 当前转移结论

当前阶段转移结论是：

- `ready_for_transition_planning`

不是因为：

- foundation 还没成形

而是因为：

- foundation 已成形
- checkpoint、transition memo、phase gate 与 pre-implementation boundary lock 已经把最危险的 residual risk 锁成明确约束
- 当前最自然的下一步已从“继续补 foundation 反例”切换成“进入 transition planning”

一句话说：

**现在的正确动作，不是继续补本地反例，也不是直接开实现，而是基于已锁定边界进入 transition planning。**

---

## 2. 判断方法

本 memo 使用三档分类：

### 2.1 `accepted_for_now`

当前已足够稳定，可以在 foundation phase 内接受残留不完美，但不能被解释成“问题已经不存在”。

### 2.2 `must_inherit_unchanged_in_implementation_planning`

这些不是继续开放讨论的问题。
它们必须在 implementation planning 中原样继承。

### 2.3 `defer_to_implementation_phase`

这些问题目前不是 foundation 的主阻塞项。
它们应在真正进入实现期后，再用实现约束决定细节。

---

## 3. 当前可接受的 residual risk

以下 residual risk 当前可归入：

- `accepted_for_now`

## 3.1 还没有第二组独立 convergence family

适用对象：

- `FactLedger` threshold
- bounded runtime-first `Rewrite` exception
- `CharacterModel` cross-field keep-vs-drop

当前可接受的原因：

- 每个边界簇都已经有本地锚点
- 每个边界簇都至少有一个 convergence anchor
- 当前更缺的是 phase judgment，不是继续盲目加样例数量

为何仍不能误读为“已彻底稳定”：

- 它只表示 first-pass stable
- 不表示 implementation-phase 可直接无条件继承

## 3.2 当前还没有更严格的 handoff 机器格式

当前可接受的原因：

- foundation phase 的目标是 contract 语义稳定
- 当前 handoff contract、context packaging、memory tiers、workflow docs 已经互相对齐

为何仍不能误读为“格式问题已解决”：

- 这只说明操作接口语义稳定
- 不说明最终 serialization schema 已确定

## 3.3 Narrative agent harness 仍停留在概念与文档层

当前可接受的原因：

- 当前已经明确了对象、包层、交接、恢复、分流的基础接口
- foundation 的任务不是先定义运行时框架代码

为何仍不能误读为“harness 层已完成”：

- 当前完成的是 conceptual harness
- 不是 implementation harness

---

## 4. 进入实现规划时必须原样继承的 boundary lock

以下内容当前应归入：

- `must_inherit_unchanged_in_implementation_planning`

## 4.1 `FactLedger` threshold lock

必须继承：

- hard fact 不得降级成 prose pressure
- `FactLedger` 不得被 handoff prose 临时代替
- `23 / 24 / 29` 作为当前最小 Track 1 anchor set 不应被随意忽略

## 4.2 bounded runtime-first `Rewrite` lock

必须继承：

- runtime-first 只是 same-packet 起步例外
- 不得跨 handoff、跨复检、跨 `CharacterModel` 补偿
- `17 / 25 / 29` 作为当前最小 Track 2 anchor set 不应被随意忽略

## 4.3 `CharacterModel` evidence leakback lock

必须继承：

- `CharacterModel` 不能作为方便层吸收 supporting evidence
- evidence leakback 视为 no-regression item
- `26 / 27 / 28 / 29` 作为当前最小 Track 3 anchor set 不应被随意忽略

---

## 5. 可以延后到实现期再处理的事项

以下事项当前可归入：

- `defer_to_implementation_phase`

## 5.1 最终机器可执行格式

包括：

- JSON API
- serialization layout
- object storage format
- connector 或 runtime protocol

原因：

- 当前 foundation 已经给出足够稳定的语义边界
- 这些细节更适合在 implementation context 中定

## 5.2 技术栈与模型选型

原因：

- 当前 phase 不以技术落地为主
- 过早引入会反向扭曲 foundation 边界

## 5.3 UI、交互与产品工作流

原因：

- 当前仍是概念与运行规则设计期
- 产品层问题现在不是主阻塞项

## 5.4 自动化调度与系统性能问题

原因：

- 当前还未进入实现级 harness
- 现在讨论调度成本和吞吐，收益不高

---

## 6. 当前阶段最推荐的后续动作

基于本 memo，当前最推荐的后续动作是：

1. 进入 transition planning，而不是继续默认补 foundation 反例
2. 把 Track 1、2、3 当前 anchor set 当成 implementation planning 的继承约束
3. 在项目入口文档里明确：
   - foundation gate 已通过
   - 当前不是 implementation in progress
   - 当前是 ready for transition planning

---

## 7. 最小交接表达

如果后续只想快速说明当前 transition 状态，建议至少写成：

```text
Phase transition memo

- current transition status: ready_for_transition_planning
- accepted_for_now: no second convergence family yet, no final machine format yet
- must_inherit_unchanged_in_implementation_planning:
  - Track 1 lock
  - Track 2 lock
  - Track 3 lock
- defer_to_implementation_phase:
  - serialization
  - stack / model selection
  - UI / product workflow
  - runtime performance and orchestration
```

---

## 8. 一句话总结

当前还不直接开实现，不是因为 foundation 不够稳，而是因为现在最合适的动作是带着已经锁定的边界进入 transition planning，而不是越过规划直接开工。
