# FactLedger Admission Threshold Decisions

## 文档目的

本文档用于收束 `FactLedger` 的 first-pass 入账阈值问题，重点回答三类变化何时必须从运行态升级为硬事实：

- knowledge changes
- relation changes
- situation changes

它关注的不是谁负责记录这些变化。
那一层已经由 ownership matrix 固定。

它关注的是：

- 变化什么时候还只是当前工作面
- 什么时候已经变成“世界中算数了”的状态
- 什么样的 situation change 值得进入 `FactLedger`

---

## 1. 文档定位

`10_ownership_matrix_decisions.md` 已经固定了：

- `FactLedger`
- `NarrativeState`
- `CharacterModel`

三者在 knowledge 与 relation 上的主从分工。

当前仍最容易漂移的，不再是“谁负责”，而是：

- 什么时候跨过入账阈值
- 什么时候仍应只留在 `NarrativeState`
- 哪些局势变化虽然不是关系或知情，但也已经足够约束后文

本文档的任务，是把这些问题压成 first-pass admission rules。

---

## 2. 总体原则

### 2.1 `FactLedger` 只接收已经算数的变化

一条变化只有在已经足够约束后文时，才应进入 `FactLedger`。

### 2.2 `NarrativeState` 先承接局部变化

局部压力、临时判断、当前目标、即时张力，默认先留在 `NarrativeState`。

### 2.3 入账判断优先看“世界是否已被改变”

不是看文本里是否提到过变化。
而是看：

- 世界状态是否已被确认改变
- 后续 workflow 是否必须把它当硬约束读取

### 2.4 omission risk 是核心判断量

如果这条变化不入账，后续 `Continue`、`Review` 或 `Rebuild` 很容易把它写丢、写错、写回未成立状态，那么它已经接近或达到入账阈值。

---

## 3. DEC-20260326-73

### 决策标题

`FactLedger` 入账采用“两段阈值”：必须先满足 base gate，再至少满足一个 strengthening condition

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

当前最常见的两类错误是：

- 过早入账，把局部波动写成硬事实
- 迟迟不入账，让真正已成立的状态只停留在运行态

如果不先固定一个最低门槛，knowledge、relation、situation 三类变化会继续用不同口径入账。

### 最终选择

一条变化要进入 `FactLedger`，默认先满足以下 base gate：

1. 有可追溯的成立来源  
   例如明确动作、公开表态、制度动作、状态变化、资源转移、对外可见事件，而不是纯推测或情绪读取。
2. 已经形成非局部约束  
   即后续不应再把它当成“只是当前场景里的临时感觉”。

在此基础上，至少再满足以下任一 strengthening condition：

1. 已被公开、制度化、第三方可见，或已产生对外后果
2. 改变了 ownership、access、route、location、authority、alignment 等硬状态
3. 若不入账，后续文本极易产生连续性错误或 `Rebuild` 丢失关键状态
4. 后续多个 workflow 都必须把它当硬约束读取，而不是只当局部参考

### 默认不够入账的信号

以下内容默认不足以单独触发入账：

- 暂时情绪升温
- 一次局部试探
- 尚未确认的猜测
- 当前最佳策略切换
- 只在本单元有效的战术压力

### 后续动作

`keep`

---

## 4. DEC-20260326-74

### 决策标题

knowledge、relation、situation changes 的 first-pass admission matrix 如下

### 决策类型

`model`

### 决策状态

`adopted`

### Admission Matrix

| change family | 默认运行层 | 何时进入 `FactLedger` | 推荐 `fact_type` | 默认不该直接入账的东西 |
|---|---|---|---|---|
| knowledge change | `NarrativeState.private_information_map` | 明确披露、隐瞒、承认、保护或权限变化已经成立；且 omission 会破坏信息合法性或后续判断 | `knowledge` / `event` / `status_change` | 猜测、试探、暂时不问、局部误读 |
| relation change | `NarrativeState.active_relation_tensions` / `PlotUnit.relation_shift` | 关系已被确认、公开、制度化、对外风险绑定，或 omission 会把双方错误写回旧关系 | `relation` / `event` / `status_change` | 一次信任升降、局部互帮、情绪波动 |
| situation change | `NarrativeState` 的目标、冲突、位置、资源、局势字段 | 局势变化已改变世界中的 control / availability / legality / route / mission state，且后续必须按新状态运行 | `status_change` / `location_state` / `resource` / `event` / `institution_rule` | 当前紧张感、一次战术选择、未确认风险、临时优先级 |

### 4.1 knowledge change

应该入账的典型情况：

- 某角色已明确知道某秘密
- 某角色已正式对外隐瞒、披露或伪造关键信息
- 某项知情权限已改变，后续合法性检查必须读取

不应直接入账的典型情况：

- “他似乎暂时不会揭发”
- “她大概猜到了真相”
- “当前这场戏里他开始怀疑对方”

### 4.2 relation change

应该入账的典型情况：

- 联盟、决裂、背叛、保护绑定、公开敌对已成立
- 关系变化已影响阵营、权限、对外站位或后续行动边界
- 若不入账，后文很容易把双方写回较早的关系基底

不应直接入账的典型情况：

- 当前信任稍有回升
- 一次短暂合作
- 只在当前局势里成立的情绪性缓和

### 4.3 situation change

这里的 situation change，指的不是泛泛“局势有变化”。
它指的是：

- 世界中的状态位已经变化
- 后续 scene 不能再按旧状态运行

应该入账的典型情况：

- 某地点被封锁、失守、占领、解除封锁
- 某资源、令牌、资格、通行权发生正式转移
- 某角色被正式通缉、赦免、授命、剥夺资格
- 主任务状态因外部已成立事件而改变，例如“潜入”正式转为“撤离”
- 某条追捕、封口、搜查、戒严已经从压力变成世界状态

不应直接入账的典型情况：

- 当前撤离压力更强了
- 这场戏里主角决定先跑再想
- 某角色觉得“现在不安全”
- 当前局部冲突热度上升

### 4.4 situation change 与 `NarrativeState` 的关系

默认先问：

- 这只是当前工作面的压力变化吗

如果是，就留在 `NarrativeState`。

只有当答案变成：

- 世界状态已被改变，后续必须按此读取

才升级进入 `FactLedger`。

### 后续动作

`watch`

---

## 5. 与现有文档的关系

本文件与以下文档配合使用：

- `10_ownership_matrix_decisions.md`
- `03_workflow_order_decisions.md`
- `06_factledger_schema.md`
- `09_field_rules.md`

它决定的是：

- 是否入账

它不单独决定：

- 全局写回顺序
- 最终实现期算法
- 每个极端 case 的唯一裁定

---

## 6. 当前仍待压测的点

本文件把 admission threshold 从“模糊经验”推进到了 first-pass decision。
仍需继续压测的是：

- repeated degradation / rebuild / continue loops 里，这套阈值是否仍稳定
- local rewrite 场景下，runtime-first exception 的允许范围虽已由 `17_local_rewrite_writeback_exception.md` 压出 first-pass 边界，但仍需更多 counterexample 验证其不会跨 handoff 被滥用
- 某些半公开、半制度化的 situation change 是否需要更细分类

---

## 7. 一句话总结

`FactLedger` 不记录“这轮看起来变了什么”，只记录“世界里已经算数了什么”。
