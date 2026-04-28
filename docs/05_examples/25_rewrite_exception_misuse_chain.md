# 示例：Rewrite Exception Misuse Chain 压测

## 文档目的

本文档提供一个连续负例样例，用于验证：

- bounded runtime-first `Rewrite` exception 不能跨 handoff 被拖延
- 任何在本轮被明确为已成立的新硬事实，都不能 ledger-late repair
- `CharacterModel` 不能被拿来做 runtime-first shortcut 的缓冲层

它验证的不是：

- local `Rewrite` 是否完全不允许先修运行态

它验证的是：

- 例外一旦离开同一 repair packet，就会退化成错误顺序

本文档主要对应：

- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`

---

## 1. 测试定位

`17_local_rewrite_writeback_exception.md` 已经压出了 first-pass 边界：

- 当根因位于 `PlotUnit` / `NarrativeState`
- 且 `FactLedger` 本身不是根因

可以允许 bounded runtime-first repair 起步。

但仓库当前仍待压实的，不再是“例外能不能存在”，而是：

- 它会不会被误读成一种可跨 handoff 延迟补账的宽松通道
- 它会不会被误扩张成“先把角色摘要改顺，再慢慢补事实层”

如果这层不压，系统最容易出现三种坏结果：

1. 本轮已成立的新硬事实被拖到下一轮才写账
2. 下一轮 `Review` 或 `Continue` 读到一个过旧的长期约束层
3. `CharacterModel` 被误用成事实层与运行态层之间的过渡缓存

---

## 2. 测试前提

沿用当前 mock case，并假设以下条目已经成立：

```text
FactLedger
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

当前正式问题对象为：

```text
ReviewIssue ri_024
- issue_type: continuity_failure
- object_type: PlotUnit
- object_id: pu_scene_024
- summary: 当前 scene 仍按旧 access 与旧路线理解局势，且漏掉了一个已在 scene 中被明确写出的 access state change
```

scene 内被明确写出的新变化是：

- 巡查已当众收缴 `c001` 的出界令牌

这里最关键的是：

- root cause 起点仍在 `PlotUnit` / `NarrativeState`
- 但修复过程中会明确暴露一个新的 formal situation fact

---

## 3. 负例链 A：cross-handoff delay

### 3.1 错误修法

系统先做了这些修改：

1. 改写 `pu_scene_024`
2. 修正 `NarrativeState.current_route`
3. 在 handoff 中补一句“令牌已丢，局势进一步恶化”
4. 计划让下轮 `Continue` 或下轮 `Rewrite` 再正式补写 `FactLedger`

### 3.2 为什么它看起来像“还能接受”

因为表面上：

- 当前运行态已经顺了
- issue 对应 scene 也被改过了
- handoff prose 似乎已经提醒后续注意令牌问题

### 3.3 为什么它实际上不允许

因为这里已经不是：

- 本轮尚未确定是否有新硬事实

而是：

- 本轮已经明确写出了一个外部动作成立后的 access change

这意味着：

- `FactLedger` 写回已成为 repair completeness 的一部分
- 不能再被 handoff prose 暂时代管

### 3.4 最小裁定

只要新硬事实已在本轮 `Rewrite` 中被正式承认：

- 就不允许跨 handoff 拖延补账

否则应直接判定：

- 当前 repair packet 不完整

---

## 4. 负例链 B：ledger-late repair after re-review

### 4.1 错误修法

系统先把改过的 `PlotUnit` / `NarrativeState` 送去 `Review`，想着：

- “如果复检通过，再统一回写 `FactLedger`”

### 4.2 为什么这是更隐蔽的错误

这比跨 `Continue` 拖延更像“流程上仍然谨慎”，因为它没有跳过复检。

但它仍然错误，因为：

- `Review` 读取到的是半同步对象集
- 它会在 `FactLedger` 尚未更新的情况下，评估一个已经默认承认“令牌被收缴”的修复版本

换句话说：

- 复检对象集和修复对象集不是同一版本

### 4.3 这会带来的后果

最容易出现两种漂移：

1. `Review` 误以为当前只是路线压力更强，而不是 access state 已改变
2. 下一轮 `Rebuild` 或 `Continue` 继续沿用旧 access 约束

### 4.4 最小裁定

bounded runtime-first exception 的允许范围，不包括：

- 先复检
- 后补账

只要本轮修复已经承认新硬事实成立，`FactLedger` 必须先进入同一 repair packet，再进入 `Review`。

---

## 5. 负例链 C：`CharacterModel`-first patching

### 5.1 错误修法

系统没有先补 `FactLedger`，而是先改：

- `CharacterModel.available_resources`
- `CharacterModel.knowledge_state`
- `CharacterModel.relations`

试图让角色摘要先解释当前 scene，例如：

- `c001` 已习惯在失去出界令牌后行动
- `c002` 已把当前撤离限制视为稳定合作前提

### 5.2 为什么这种修法特别危险

因为它制造了一个假稳定层：

- 长期角色摘要看起来已经吸收了新局势
- 但正式 world/access constraint 其实还没进入 `FactLedger`

这会让后续 workflow 产生错觉：

- 好像长期对象已经统一
- 实际上只是角色侧摘要先替事实层背锅

### 5.3 最小裁定

只要新成立的约束本质上属于：

- resource / access / authority / route / legality change

就不能先靠 `CharacterModel` 摘要兜底。

`CharacterModel` 最多只能在：

- `FactLedger`
- `NarrativeState`

都已经完成同轮同步后，再承接允许保留的长期角色侧变化。

---

## 6. 正确链路对照

如果这个例外被正确使用，链路应是：

1. 先修主根因对象 `PlotUnit`
2. 同步 `NarrativeState`
3. 判断 scene 中是否已明确新硬事实成立
4. 若是，则在同一 repair packet 内补写 `FactLedger`
5. 只有在对象集完成同步后，才进入 `Review`
6. 必要时最后再检查 `CharacterModel` 是否需要承接允许长期化的变化

这里的关键不是“永远不能先修运行态”，而是：

- 运行态优先只能出现在同一 repair packet 的起点
- 不能出现在 handoff 之后
- 不能出现在 re-review 之后
- 不能出现在 `CharacterModel` 之前置兜底

---

## 7. 三条负例的裁定表

| 负例 | 表面理由 | 实际问题 | 是否允许 | 最小裁定 |
|---|---|---|---|---|
| A. cross-handoff delay | 当前 scene 已修顺，后面再补账 | 新硬事实被 handoff prose 暂时代管 | 不允许 | repair packet 不完整 |
| B. ledger-late after re-review | 先复检更稳妥 | `Review` 读取半同步对象集 | 不允许 | 必须先补账再复检 |
| C. `CharacterModel`-first patching | 先让角色摘要解释 scene | 角色侧摘要越权代替事实层 | 不允许 | 必须回到事实层与运行态层同步 |

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. bounded runtime-first exception 只是一种 repair packet 起步顺序，不是跨轮宽限
2. 只要本轮明确了新硬事实，ledger-late repair 就应被判为不完整
3. `Review` 不应读取半同步的 rewrite 结果
4. `CharacterModel` 不能被用作事实层拖延的缓冲层
5. “先修运行态”只有在同轮同步闭合时才合法

---

## 9. 一句话总结

local `Rewrite` 的 runtime-first 例外，只允许出现在同一 repair packet 的开头，不允许跨 handoff、跨复检、也不允许借 `CharacterModel` 摘要绕开事实层同步。
