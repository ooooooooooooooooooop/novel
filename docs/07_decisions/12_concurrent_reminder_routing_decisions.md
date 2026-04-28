# Concurrent Reminder Routing Decisions

## 文档目的

本文件用于收束多个 `active ReviewReminder` 同时存在时的最小路由规则。

它关注的不是：

- 单条 reminder 的窗口设计

它关注的是：

- 多条 reminder 是否可以合并
- 下一轮 `Continue` 先补哪条
- 一条 reminder 被关闭时，其他 reminder 是否仍然保留
- reminder 并发何时仍属于 `Continue`，何时应转向 `Rewrite` 或更高层动作

---

## 1. 文档定位

当前项目已经具备：

- 单条 reminder 的 schema
- reminder family 的默认升级矩阵
- 单条 reminder 升级样例
- reminder 与 formal issue 并存分流样例

但还缺一层并发规则。

如果这层规则不固定，系统很容易出现：

- 多条 reminder 被粗暴压成一条
- `Continue` 没有明确优先级
- 一条 reminder 被补后，其他 reminder 被误当作自动关闭
- active reminder 数量一多，就因为“看起来复杂”而误升到 `Replan`

本文件的任务，是把这些问题收束成 first-pass routing defaults。

---

## 2. 适用边界

### 2.1 本文件定义什么

- reminder 合并的最低条件
- reminder priority 的默认判断顺序
- reminder 独立关闭 / 独立升级原则
- 多 reminder 并发时的默认 workflow route

### 2.2 本文件不定义什么

- 实现期的最终排序算法
- 多 reminder 并发时的数值打分系统
- formal issue 与 reminder 并发的所有极端例外

---

## 3. 总体原则

### 3.1 reminder 先按独立风险对象理解，不按“提醒总数”理解

reminder 的数量本身不是问题。

真正的问题是：

- 它们是否指向同一风险
- 是否需要相同补偿动作
- 是否在共享同一升级轨迹

### 3.2 并发 reminder 不应默认合并

合并只能在确有同源、同类、同补偿动作时发生。

### 3.3 priority 先看升级迫近度，再看结构伤害

谁更接近窗口耗尽、谁更容易伤害已成立结构，谁优先。

### 3.4 reminder 可以独立关闭、独立保留、独立升级

一轮 `Continue` 的正常结果可以是：

- 关闭一条
- 保留一条
- 升级一条

这不意味着流程失控，而意味着 reminder 真正在工作。

---

## 4. DEC-20260326-70

### 决策标题

并发 `ReviewReminder` 默认按独立风险对象处理；同 family 默认只允许 grouped handoff，只有在同 branch identity、同窗口语义、同补偿动作时才 true merge

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

当多个 reminder 同时存在时，最常见的错误是把它们压缩成一句：

- “后续注意后果、关系和信息边界”

这种写法看似简洁，实际会破坏 handoff，因为它抹掉了：

- 不同的升级目标
- 不同的窗口
- 不同的补偿动作

### 最终选择

默认不 true merge。

同 family reminder 的 first-pass 默认动作是：

1. 先按独立 child reminder 保留
2. 允许在 handoff 层做 grouped handoff summary
3. 只有在 child reminder 已被证明指向同一 branch identity 时，才考虑 true merge

这里区分两种动作：

- grouped handoff：共享一条摘要，但 child reminder 继续保留各自来源、窗口与升级轨迹
- true merge：用一条 reminder 真正替代多条 child reminder

只有同时满足以下条件时，才建议考虑 true merge：

1. `reminder_type` 相同
2. `related_issue_type` 相同
3. 指向同一 branch identity，而不只是同 family
4. `window_type` 与窗口耗尽语义相同
5. 补偿动作本质相同
6. 合并后不会削弱来源可追溯性

### 不应 true merge 的典型情况

- `missing_consequence` 与 `relationship_bridge_needed`
- `knowledge_check_needed` 与 `missing_cost`
- 同 family 但一个已在最后窗口、另一个刚创建
- 同 family、同 `related_issue_type`，但来自不同 `PlotUnit` branch

### 允许 grouped handoff 但不允许 true merge 的典型情况

- 两条 `missing_consequence` 都需要近程处理，但一条在追旧后果链，另一条在追新 consequence branch
- 两条 reminder 可以共享“当前 consequence 类风险不止一条”的摘要，但仍必须保留独立 child reminder

### 后续动作

`keep`

---

## 5. DEC-20260326-71

### 决策标题

并发 reminder 的默认优先级顺序是：升级迫近度 -> 结构伤害 -> 条件触发性 -> 其余 reminder 保留成本

### 决策类型

`review`

### 决策状态

`adopted`

### 默认判断顺序

#### 第一优先：升级迫近度

先看：

- 哪条 reminder 的窗口最接近耗尽
- 哪条 reminder 已进入最后一轮可补偿窗口

#### 第二优先：结构伤害

再看：

- 若该 reminder 失守，是否会 retroactively 削弱已成立强推进
- 是否会更快污染主线、合法性或角色连续性

#### 第三优先：条件触发性

再看：

- 该 reminder 是否只有在“下一单元继续做某种动作”时才会爆炸

例如：

- `relationship_bridge_needed` 往往依赖“下一单元继续推进关系”
- `knowledge_check_needed` 往往依赖“下一单元让角色基于非法知识行动”

这类 reminder 在未触发该动作前，通常可以排在更迫近的 reminder 后面。

#### 第四优先：其余 reminder 的保留成本

最后看：

- 若优先补 A，保留 B 是否仍然可控
- 若优先补 B，A 是否会直接超窗

### 后续动作

`keep`

---

## 6. DEC-20260326-72

### 决策标题

并发 reminder 的默认 route 不因数量升级；只有当 formal issue 已出现或多个 reminder 已共同指向结构失衡时，才离开带约束 `Continue`

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

提醒一多，最容易出现两种误判：

- 误判 A：反正都还是 reminder，就继续拖
- 误判 B：提醒太多了，直接当结构失衡处理

### 最终选择

默认 route 如下：

#### 6.1 只有并发 reminder，尚无 formal issue

默认仍属于：

- 带约束 `Continue`

前提是：

- 至少还存在一个可操作补偿路径
- reminder 尚未共同指向不可局部修复的结构问题

#### 6.2 某条 reminder 被踩爆为 formal issue

则按 formal issue route：

- 优先进入 `Rewrite`

并保留其余仍有效的 reminder。

#### 6.3 多条 reminder 虽未形式升级，但已共同指向同一结构失衡

这类情况不应只看“还没有 formal issue”。

如果系统已经能判断：

- 多条 reminder 指向同一主线停滞
- 局部补偿已不足以修复

则应考虑：

- 先进入更强审查
- 必要时升级为 `Replan`

### 说明

并发 reminder 的数量不是升级条件。

真正的升级条件是：

- formal failure 已发生
- 或结构失衡已清楚到不能再假装是局部近程风险

### 后续动作

`watch`

---

## 7. 当前 first-pass 并发规则总表

| 问题 | 默认规则 | 当前状态 |
|---|---|---|
| reminder 是否默认合并 | 否，默认独立处理 | fixed |
| 同 family 是否自动 true merge | 否，默认只允许 grouped handoff | fixed |
| 何时允许 true merge | 同 family、同 branch identity、同窗口语义、同补偿动作、且不削弱可追溯性 | fixed |
| 先补哪条 | 先看升级迫近度，再看结构伤害 | fixed |
| 一条关闭是否自动关闭其他 reminder | 否 | fixed |
| 并发 reminder 是否自动升级为 `Replan` | 否 | fixed |
| 何时离开带约束 `Continue` | formal issue 已出现，或 reminder 已共同指向结构失衡 | fixed |

---

## 8. 当前仍未完全固定的点

本文件解决的是 first-pass 并发 routing defaults。

仍需继续压测的是：

- 不同 source layer 但可能仍指向同一 branch identity 时，alias 识别是否还需要更细规则
- “共同指向结构失衡”的判断门槛
- 带 `Rewrite` 返回后 reminder 的重新排序是否需要单独规则

---

## 9. 一句话总结

并发 reminder 的核心不是把提醒数量压少，而是在多条风险同时存在时，仍能保持独立轨迹、清楚优先级和不过度升级的分流。
