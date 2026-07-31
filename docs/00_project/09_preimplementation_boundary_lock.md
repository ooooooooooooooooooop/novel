# Pre-Implementation Boundary Lock

## 目的

本文档用于把当前最容易在 implementation pressure 下回弹的三条边界锁成明确约束。

它回答的不是：

- 当前边界有没有被样例压过

它回答的是：

- 进入实现规划前，哪些边界绝不能被放宽
- 哪些结论必须被视为 no-regression item
- 实现讨论可以继承什么
- 实现讨论不允许重新打开什么

---

## 1. 当前锁定结论

当前结论是：

- Track 1、Track 2、Track 3 已具备 pre-implementation lock 条件

这不表示：

- implementation 已经开始

它表示：

- foundation 已经把最危险的边界回弹点写成了不应放宽的约束

---

## 2. Track 1 Lock

## 2.1 锁定对象

- `FactLedger` admission threshold

## 2.2 不可放宽项

进入实现规划后，不允许重新放宽为以下做法：

- 把已成立 hard fact 重新退回当前压力描述
- 用 handoff prose 替代已成立 `FactLedger` 条目
- 把 knowledge / relation / situation 三类 hard fact 混写成一句“局势更复杂了”

## 2.3 必须继承的结论

实现讨论必须继承：

- `FactLedger` 只记录世界里已经算数的变化
- hard fact、当前工作面、未升级推断必须继续分层
- `23 / 24 / 29` 是当前 Track 1 的最小 anchor set

## 2.4 No-Regression Item

- `FactLedger` 不能被 prose handoff 或 runtime pressure 替代

---

## 3. Track 2 Lock

## 3.1 锁定对象

- bounded runtime-first `Rewrite` exception

## 3.2 不可放宽项

进入实现规划后，不允许重新放宽为以下做法：

- cross-handoff delay
- review-late ledger writeback
- `CharacterModel`-first patching
- 用更详细 handoff 替代未完成的 same-packet formal writeback

## 3.3 必须继承的结论

实现讨论必须继承：

- runtime-first 只是一种 same-packet 起步例外
- 不是 alternate default writeback order
- `17 / 25 / 29` 是当前 Track 2 的最小 anchor set

## 3.4 No-Regression Item

- 只要本轮 `Rewrite` 已明确新 hard fact，`FactLedger` 就必须在同一 repair packet 内完成写回

---

## 4. Track 3 Lock

## 4.1 锁定对象

- `CharacterModel` cross-field keep-vs-drop

## 4.2 不可放宽项

进入实现规划后，不允许重新放宽为以下做法：

- 把 supporting evidence 漏回 `knowledge_state`
- 把关系依据与 recent sequence 漏回 `relations`
- 把成长依据与 rollback 说明漏回 `self_image` / `arc_stage`
- 为了降低 handoff 成本，把更多工作面信息永久沉积进 `CharacterModel`

## 4.3 必须继承的结论

实现讨论必须继承：

- `CharacterModel` 字段本体只保留长期压缩结论
- supporting evidence 继续留在 `PlotUnit`、`NarrativeState`、handoff supporting context 与 `Review` supporting context
- `26 / 27 / 28 / 29` 是当前 Track 3 的最小 anchor set

## 4.4 No-Regression Item

- evidence leakback 视为 implementation 前不得回弹的高优先级禁项

---

## 5. 实现规划允许讨论什么

进入 implementation planning 后，可以讨论：

- serialization 形状
- runtime orchestration
- storage layout
- tool / model / stack choice
- UI 和产品工作流

前提是：

- 不得改写上面的三条边界锁定结论

---

## 6. 实现规划不允许重新打开什么

进入 implementation planning 后，不允许重新把以下问题当成开放问题：

1. `FactLedger` 是否可以被 handoff prose 临时代替
2. bounded runtime-first `Rewrite` 是否可以跨 packet 延迟补账
3. `CharacterModel` 是否可以为了方便交接而吸收更多 supporting evidence

这些问题在当前 foundation 结论里已经不再是“待探索”，而是：

- `locked`

---

## 7. 最小交接表达

```text
Pre-implementation boundary lock

- Track 1 lock:
  hard fact cannot be downgraded into prose pressure
- Track 2 lock:
  bounded runtime-first Rewrite cannot escape same-packet writeback
- Track 3 lock:
  CharacterModel cannot absorb supporting evidence as a convenience layer
- implementation planning may proceed only if these locks are inherited unchanged
```

---

## 8. 一句话总结

当前 foundation 的真正成果，不只是把边界压出来，而是把 implementation 最容易重新放松的三条边界正式锁成了不可放宽项。
