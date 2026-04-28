# 示例：跨 Arc 退化与 Rebuild 恢复

## 文档目的
本文件提供一个长链路压力样例，用于验证以下问题：

- 当系统跨过多个 `PlotUnit` 或一个局部 arc 后出现上下文退化
- 当前工作集已经不足以稳定继续
- `Rebuild` 能否把已有材料重新压缩成可运行状态包

它验证的不是普通续写，而是：

**长上下文工作在发生漂移、缺失或局部失忆后，系统能否通过 `Rebuild` 恢复到可继续工作的状态。**

本文件对应：

- `04_workflows/01_rebuild_workflow.md`
- `07_decisions/08_context_packaging_decisions.md`
- `00_project/05_narrative_agent_harness.md`

---

## 1. 测试定位

前面的样例已经验证了：

- reminder only -> `Continue`
- reminder + local issue -> `Rewrite`
- multiple formal issue -> `Replan`

但还缺一类更长链路的失败：

- 系统不是“当前单元写坏了”
- 而是“当前工作集已经不够用了”

这类情况通常表现为：

- 当前 `NarrativeState` 与 `FactLedger` 的对应关系开始松动
- 活跃线程列表不完整
- 近几轮提醒与正式问题只剩局部片段
- agent 还能继续写，但置信度越来越低

此时正确动作不是继续强写，也不是直接 `Rewrite`，而是：

- 触发 `Rebuild`
- 重新生成静态记忆包与可运行状态包

---

## 2. 测试前提

沿用当前 mock case：

- 作品：`残雪归宗`
- 当前已跨过一个局部 arc 小段
- 最近经历过：
  - 若干 `Continue`
  - 一次 mixed routing
  - 一次 structural `Replan` 决策

假设现在系统手头的输入只剩：

- 近期 3 个 `PlotUnit`
- 部分 `FactLedger` 条目
- 部分 `ForeshadowGraph` 条目
- 最近一次审查摘要
- 一段作者备注

同时丢失了：

- 完整的当前 `NarrativeState`
- 一部分 `CharacterModel` 当前知情与目标偏移
- 多条 active reminder 的最新状态

这就是典型的 bounded package 已不够，但全文又不必重读的恢复场景。

---

## 3. 当前退化症状

### 3.1 表层症状

系统会出现以下表现：

- 能说出最近发生了什么
- 但说不清当前“主目标 / 主冲突 / 主线程”哪个最优先
- 能列出若干事实
- 但无法高置信判断哪些仍是当前局势核心

### 3.2 对象层症状

当前缺口主要体现在：

- `NarrativeState` 缺失或置信度过低
- `ForeshadowGraph` 的 active thread 列表不完整
- `ReviewReminder` 的 active / escalated 状态不完整
- `CharacterModel` 的当前局势偏移未被稳定保留

### 3.3 为什么这时不能直接 Continue

如果此时继续 `Continue`，很容易出现：

- 明明主线该推进，却误读为关系线优先
- 已关闭或已升级的 reminder 被当作还在 active
- 当前风险排序与历史约束不一致

也就是说：

这已经不是单个问题对象能修的事，而是当前运行态缺失。

---

## 4. 当前输入材料包

### 4.1 仍然可用的材料

```text
- pu_scene_016
- pu_scene_017
- pu_scene_018
- FactLedger: f_016, f_017, f_018, f_021
- ForeshadowGraph: fg_001, fg_002 的部分摘录
- 最近一次 review 摘要
- 一段作者备注：当前段落应回到主线压力，不要继续空转关系试探
```

### 4.2 已缺失的材料

```text
- 最新 NarrativeState 正式对象
- 若干 CharacterModel 当前目标偏移
- ReviewReminder 最新状态快照
- 当前局部段落的完整 handoff package
```

### 4.3 该如何判定

这类输入不适合：

- 直接高置信 `Continue`
- 直接对某一 scene 做 `Rewrite`

它适合：

- 进入 `Rebuild`
- 先恢复静态记忆包
- 再恢复当前可运行状态包

---

## 5. 正确的 Rebuild 输出

### 5.1 静态记忆包

`Rebuild` 首先应重新抽取并确认：

- `WorkSpec` 仍无根本变化
- `WorldModel` 的关键约束仍然有效
- `CharacterModel` 的长期结构基线仍成立
- `FactLedger` 中哪些事实仍是高约束事实
- `ForeshadowGraph` 中哪些线程仍处于 active

这一步的目标不是恢复细枝末节，而是恢复长期稳定约束。

### 5.2 可运行状态包

在当前案例中，较合理的恢复结果应是：

```json id="exrb11state"
{
  "state_id": "s_rebuild_arc01",
  "time_anchor": "chapter_06 after scene_018",
  "primary_location": "黑水泽撤离路径外缘",
  "active_characters": ["c001", "c002"],
  "primary_goal": "在保持令牌与秘密不扩散的前提下脱离巡查风险，并重新把推进焦点拉回 fg_001",
  "active_conflicts": [
    "巡查与追踪压力仍未解除",
    "c002 的立场仍未完全稳定",
    "主线推进在最近几个单元中出现停滞"
  ],
  "active_threads": ["fg_001", "fg_002"],
  "state_confidence": "medium"
}
```

这不是完整恢复一切，而是恢复到“可以重新进入保守 `Review` 或受限 `Continue`”的程度。

### 5.3 修复与不确定性包

好的 `Rebuild` 还应显式输出：

```json id="exrb11uncertainty"
{
  "missing_information": [
    "c002 当前私下判断的精确置信度",
    "最近一轮 reminder 的完整关闭记录"
  ],
  "conflict_risk": [
    "fg_002 的推进节奏是否已在上一轮被重排",
    "部分关系推进是否已在局部 rewrite 中被修正"
  ],
  "recommended_next_step": "先进行一次保守 Review，再决定是否 Continue",
  "rebuild_confidence": "medium"
}
```

这一步的意义是：

- 把“不知道”保留为对象化输出
- 防止后续 workflow 把恢复结果误当成高确定性真相

---

## 6. Rebuild 后的正确路由

### 6.1 不应直接怎么走

错误路径 A：

- 跳过 `Rebuild`，直接继续写下一 scene

问题：

- 当前工作集已不足，继续写只会放大漂移

错误路径 B：

- 以为缺失的是某个 formal issue，直接进入 `Rewrite`

问题：

- 当前缺的是整体可运行状态，不是某个 scene 的单点修复

### 6.2 当前正确路由

推荐路由是：

```text
bounded packages become insufficient
  -> Rebuild
  -> recover static memory package
  -> recover runnable state package
  -> run conservative Review
  -> only then decide whether Continue is safe
```

---

## 7. 这个样例在验证什么

这份样例主要验证 4 件事：

### 7.1 `Rebuild` 不是初始化特例

它也是长期运行中的恢复动作。

### 7.2 上下文退化不是自动等于 formal issue

有时问题不在某个 scene，而在当前可运行工作集已经不足。

### 7.3 恢复的目标不是“还原全部历史”

而是恢复：

- 长期稳定约束
- 当前可运行状态
- 明确的不确定性包

### 7.4 `Rebuild` 后仍应先审查再继续

因为恢复结果本身也有置信度和缺口，不应直接假装已经回到高确定性运行。

---

## 8. 当前结论

如果这份样例成立，可以认为：

- 项目已经不只是在做短链路分流
- 它开始覆盖长上下文工作中的退化与恢复
- `Rebuild` 终于真正进入 harness 视角，而不是只作为初始化说明存在

---

## 9. 一句话总结

`11_cross_arc_rebuild_recovery.md` 的任务，是证明当当前工作集已经不足以稳定续写时，系统可以通过 `Rebuild` 恢复到“可继续工作但保留不确定性”的状态，而不是继续硬写或误入局部修补。
