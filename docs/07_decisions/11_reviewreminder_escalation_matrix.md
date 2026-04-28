# ReviewReminder Escalation Matrix

## 文档目的

本文件用于把 `ReviewReminder` 的升级规则从“有窗口、有升级目标”进一步收束为：

- 哪类 reminder 默认使用什么窗口
- 哪类 reminder 默认升级成什么 issue
- 哪些情况下应提前升级
- 哪些情况下不该建立 reminder，而应直接建正式问题

它关注的不是：

- reminder 是否存在

它关注的是：

- reminder 作为轻量对象时，默认应该怎么用

---

## 1. 文档定位

`09_review_reminder_decisions.md` 已经固定了：

- warning 是判断
- `ReviewReminder` 是 warning 的承载对象
- reminder 必须带窗口与升级目标

但当前仍缺一层更可执行的默认口径：

- `missing_consequence` 默认给多长窗口
- `relationship_bridge_needed` 默认在什么边界前必须补桥
- `knowledge_check_needed` 到什么程度不再是 reminder，而应直接进入 `information_leak`
- `promise_followup_needed` 如何避免被无限拖延

本文件的任务，是把这些问题压成 first-pass escalation matrix。

---

## 2. 适用边界

### 2.1 本文件定义什么

- reminder family 的默认使用场景
- 默认窗口类型与默认窗口值
- 默认升级目标 issue type
- 默认提前升级条件
- 默认补偿关闭条件

### 2.2 本文件不定义什么

- 所有极端例外
- 多 reminder 并发时的最终裁决策略
- 最终实现期计数器机制

### 2.3 当前阶段性质

当前阶段仍是 foundation design。

因此这里固定的是：

- first-pass defaults

而不是：

- 永久不变的最终阈值系统

---

## 3. 总体原则

### 3.1 reminder 只服务近程、可补偿、未正式失败的问题

如果问题已经满足正式失败条件，应直接生成 `ReviewIssue`。

### 3.2 不同 family 的窗口不应一刀切

代价与后果类问题通常更近程。
承诺类问题通常更跨段落。
信息越界类问题通常更短窗口，甚至不适合 reminder。

### 3.3 默认窗口是保守默认，不是不可覆盖硬编码

如果当前 case 有更强约束，可以缩短。
若 case 的结构允许，也可在决策有据时适度放宽。

### 3.4 提前升级比拖延升级更安全

如果 reminder 已开始污染对象层，不应继续把它留在 reminder 层。

---

## 4. reminder family 总表

当前 first-pass 建议支持以下 family：

1. `missing_consequence`
2. `missing_cost`
3. `relationship_bridge_needed`
4. `promise_followup_needed`
5. `knowledge_check_needed`

---

## 5. DEC-20260326-68

### 决策标题

`ReviewReminder` 采用分 family 的默认升级矩阵，而不是所有 reminder 共用同一窗口逻辑

### 决策类型

`review`

### 决策状态

`adopted`

### 背景问题

此前项目已固定：

- reminder 必须带窗口
- reminder 必须带升级目标

但如果不同 family 仍共用一套模糊窗口，后续就会出现：

- 后果类问题被拖得过长
- 承诺类问题被过早升级
- 信息边界类问题被错误地当作可慢慢观察

### 最终选择

采用分 family 默认矩阵。

### 选择理由

1. 不同 family 的风险扩散速度不同
2. reminder 的价值在于“近程可操作”，而不是“统一格式好看”
3. 这能把当前 reminder gap 从抽象问题收窄到默认策略问题

### 后续动作

`keep`

---

## 6. DEC-20260326-69

### 决策标题

first-pass `ReviewReminder` escalation matrix 如下

### 决策类型

`review`

### 决策状态

`adopted`

### Escalation Matrix

| reminder_type | 默认使用场景 | 默认窗口 | 默认升级目标 | 默认提前升级条件 | 默认补偿关闭条件 |
|---|---|---|---|---|---|
| `missing_consequence` | 强推进已建立后果，但近程尚未兑现 | `plotunit_count = 2` | `missing_consequence` | 已连续两次复审未体现任何核心后果；或后果缺失已开始削弱既有强推进成立性 | 后续 1 个有效单元内兑现至少一项核心后果 |
| `missing_cost` | 高代价行为已发生，但代价尚未落地 | `plotunit_count = 1~2`，默认 `1` 对高危，默认 `2` 对中危 | `missing_cost` | 本轮后若继续零代价运行；或已开始造成世界合法性失真 | 已明确体现代价、损耗、追责或资源消耗 |
| `relationship_bridge_needed` | 关系正在接近跃迁，但当前桥接仍不足 | `plotunit_count = 1`，若下一单元即将进入更高关系阶段则必须补桥 | `relationship_jump` 或 `motivation_gap` | 下一单元已直接跨阶段；或关系推进已开始违背角色逻辑 | 已补一段能解释关系推进的桥接或代价 |
| `promise_followup_needed` | 承诺线程未正式遗失，但已进入危险停滞 | `phase_window`，默认 `before_local_arc_turn`；近程样例可退化为 `plotunit_count = 2` | `promise_loss` 或 `missing_consequence` | 核心线程被连续遮蔽；或同线程 reminder 再次出现 | 已明确推进、收紧、偏转或有意延迟并写明代价 |
| `knowledge_check_needed` | 当前信息边界复杂，下一步极易越界，但当前尚未正式 leak | `plotunit_count = 1` | `information_leak` | 下一单元若继续保持模糊且角色已基于非法知识行动，应直接升级 | 已澄清当前谁知道什么，且下一步行动与信息边界一致 |

### 说明

#### 6.1 `missing_consequence`

它适合：

- 后果已被建立
- 但当前仍可在近程补偿

它不适合：

- 后果缺失已经跨越多个单元，且已经明显伤害结构

#### 6.2 `missing_cost`

它默认比 `missing_consequence` 窗口更短。

因为代价缺失更容易快速演变成世界合法性问题。

#### 6.3 `relationship_bridge_needed`

它不是“关系线慢一点也无所谓”的提醒。

它本质上是在说：

- 若下一个关系升级动作没有桥接，就会掉进正式 `relationship_jump`

因此默认窗口应极短。

#### 6.4 `promise_followup_needed`

它是少数允许使用 phase window 的 family。

因为承诺类问题天然跨更长结构。

但若当前线程已经是核心主线，则不得无限拖延。

#### 6.5 `knowledge_check_needed`

这是最不适合长期挂起的 family 之一。

如果下一单元已经出现非法知情行动，就不应继续保留 reminder，而应直接进入 `information_leak`。

### 后续动作

`watch`

---

## 7. 什么时候不该建立 reminder

以下情况默认不建 reminder，直接建正式 issue：

### 7.1 已正式发生 `information_leak`

如果角色已经基于非法知识行动，就不是 `knowledge_check_needed`，而是正式失败。

### 7.2 已正式发生 `relationship_jump`

如果关系已经跨阶段跳变，就不是“bridge needed”，而是已经掉进 issue。

### 7.3 已正式发生高危 `missing_cost`

若世界合法性、制度后果或资源逻辑已经明显失真，不应继续挂 reminder。

### 7.4 核心承诺已被明显遗失

若主线承诺已持续被遮蔽并开始破坏结构，应直接进入 `promise_loss`。

---

## 8. 默认 severity 建议

| reminder_type | 默认 severity | 说明 |
|---|---|---|
| `missing_consequence` | `low` -> `medium` | 首轮通常 `low`，复查未补后可升 `medium` |
| `missing_cost` | `medium` | 因其更接近合法性风险 |
| `relationship_bridge_needed` | `medium` | 因其默认窗口极短 |
| `promise_followup_needed` | `low` 或 `medium` | 视线程重要性决定 |
| `knowledge_check_needed` | `medium` | 因其极易滑向 `information_leak` |

原则：

- `ReviewReminder` 默认不承载 `high / critical`
- 一旦达到 `high` 语义，应优先考虑正式 issue

---

## 9. 当前仍未完全固定的点

本文件把 reminder 问题从“完全没有默认策略”推进到“已有 first-pass default matrix”。

仍待继续压测的是：

- 同时存在多个 active reminder 时，如何合并与排序
- 同一 family 在不同题材中的窗口弹性范围
- `promise_followup_needed` 的 phase window 是否还需更细分
- `knowledge_check_needed` 是否需要拆成更细类型

---

## 10. 一句话总结

`ReviewReminder` 的关键不只是“有窗口”，而是不同 family 必须带着不同的默认窗口、升级目标和提前升级条件进入 workflow。
