# Ownership Matrix Decisions

## 文档目的

本文件用于收束当前项目中最容易漂移的 ownership 问题：

- `CharacterModel`
- `NarrativeState`
- `FactLedger`

它关注的不是某个字段怎么命名。
它关注的是：

- 同一类信息到底谁是主存
- 谁可以保留当前工作集表达
- 谁只能保留角色侧摘要
- 冲突出现时按什么优先级裁决
- `Continue` / `Rewrite` 写回时应先改哪层

---

## 1. 文档定位

`02_model_boundary_decisions.md` 已经固定了对象级大边界。

但以下两组问题仍然反复出现：

1. knowledge ownership
2. relation ownership

如果这两组问题继续只靠局部 prose 处理，就会持续出现：

- `CharacterModel.knowledge_state` 与 `FactLedger.known_by` 重叠
- `NarrativeState.private_information_map` 与长期知情状态混写
- `CharacterModel.relations` 与 `FactLedger relation` 同时像主存
- 当前关系张力和已成立关系事实互相覆盖

本文件的作用，是把这两组边界从“散点提醒”收束成 first-pass ownership matrix。

---

## 2. 术语说明

### 2.1 主存对象

某类信息真正算数时，最终应以哪个对象为准。

### 2.2 运行态表达

某类信息在“当前这轮工作”里如何被压缩成工作集。

### 2.3 角色侧摘要

某类信息如何以角色为中心被保留，用来支持未来决策与一致性检查。

### 2.4 入账阈值

某类变化从“本轮局势变化”升级为“可约束后文的长期事实”所需的最低条件。

---

## 3. 当前需要固定的矩阵问题

当前最需要固定的 ownership matrix 主要有 4 个：

1. 已成立知情事实谁主存
2. 当前信息分布谁主存
3. 已成立关系事实谁主存
4. 当前关系张力谁主存

---

## 4. DEC-20260326-65

### 决策标题

knowledge ownership 采用三层分工：`FactLedger` 负责已成立知情事实，`NarrativeState` 负责当前工作集信息分布，`CharacterModel` 只保留角色侧长期摘要

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

当前最模糊的 knowledge 边界是：

- 某角色知道什么，应该写在哪
- 哪些知情变化必须变成长期硬约束
- 哪些知情内容只在当前场景里有意义
- `CharacterModel.knowledge_state` 是否会变成第二个账本

### 最终选择

采用以下三层分工。

#### A. `FactLedger.known_by` 是已成立知情事实的主存

适用于：

- 某角色已知某条会约束后文的事实
- 某秘密已被谁正式知晓
- 某知识权限变化会影响合法性、冲突、误导或后续审查

它不是：

- 当前场景里所有零碎感受
- 尚未成立的猜测
- 仅为这轮工作临时整理的局部信息图

#### B. `NarrativeState.private_information_map` 是当前工作集信息分布的主存

适用于：

- 当前局势里谁知道什么
- 哪些秘密、误解、暴露边缘正在影响本轮决策
- 本轮 `Continue` / `Review` 必须直接读取的信息分布

它不是：

- 长期知情事实的最终裁决层
- 角色长期认知结构档案

#### C. `CharacterModel.knowledge_state` 只保留角色侧长期摘要

适用于：

- 长期持续影响角色决策的秘密负担
- 角色稳定持有的重要误判或偏置信念
- 不依赖单一 scene 才成立的认知结构摘要

它不是：

- 当前所有已知事实的完整列表
- 替代 `FactLedger.known_by` 的知情总账
- 替代 `NarrativeState.private_information_map` 的当前工作集

### Knowledge Ownership Matrix

| 信息类型 | 主存对象 | 运行态表达 | 角色侧摘要 | 说明 |
|---|---|---|---|---|
| 已成立且约束后文的知情事实 | `FactLedger.known_by` | `NarrativeState.private_information_map` 中可读取相关子集 | 仅在长期影响决策时写入 `CharacterModel.knowledge_state` | 长期连续性问题先看账本 |
| 当前局势中的私人信息分布 | `NarrativeState.private_information_map` | 同主存 | 不要求同步回 `CharacterModel` | 当前工作面先看状态 |
| 稳定误判 / 长期认知偏差 | `CharacterModel.knowledge_state` | 必要时投影到 `NarrativeState.misinformation_in_effect` | 同主存 | 角色一致性问题先看角色模型 |
| 尚未成立的猜测或临时判断 | 不主存到 `FactLedger` | `NarrativeState` 局部字段或派生判断 | 必要时保留在角色侧误判摘要 | 不得伪装成硬事实 |

### 写回规则

1. 本轮若出现新的高约束知情成立，先更新 `FactLedger`
2. 再同步当前 `NarrativeState.private_information_map`
3. 只有当该知情会长期塑造角色决策时，才更新 `CharacterModel.knowledge_state`

### 冲突裁决

- “世界中谁已经正式知道了某事实”看 `FactLedger`
- “当前这轮谁掌握了哪些关键私人信息”看 `NarrativeState`
- “这个角色长期背着什么知识负担或稳定误判”看 `CharacterModel`

### 风险 / 待验证项

- 哪些知情变化足够重要，必须从 `NarrativeState` 升级写入 `FactLedger`
- `CharacterModel.knowledge_state` 的粒度仍需通过长链样例压测

### 后续动作

`watch`

---

## 5. DEC-20260326-66

### 决策标题

relation ownership 采用三层分工：`FactLedger` 负责已成立关系事实，`NarrativeState` 负责当前关系张力，`CharacterModel` 负责长期关系基底

### 决策类型

`model`

### 决策状态

`adopted`

### 背景问题

当前 relation 边界最容易混成三种坏状态：

1. `CharacterModel.relations` 变成关系总账
2. `FactLedger relation` 把所有情绪波动都记进去
3. `NarrativeState.active_relation_tensions` 被误当作已成立关系事实

### 最终选择

采用以下三层分工。

#### A. `CharacterModel.relations` 负责长期关系基底

适用于：

- 角色之间较稳定的关系结构
- 会持续影响行为选择的关系方向
- 关系弧中的阶段性位置

它不是：

- 当前 scene 的气氛条
- 某次争执后的即时波动
- 所有已正式公开或制度化的关系事件总账

#### B. `NarrativeState.active_relation_tensions` 负责当前关系张力

适用于：

- 当前局面中的戒备、暧昧、敌对、互信摇摆
- 这轮推进最重要的关系压力
- 当前 `Review` 需要检查的关系热区

它不是：

- 长期关系基底
- 已正式成立的关系事实

#### C. `FactLedger relation` 负责已成立关系事实

适用于：

- 已正式确认的联盟、决裂、背叛暴露、婚约、师徒认定
- 会持续约束后文的关系状态变化
- 关系变化已经不只是气氛，而是世界中“算数了”

它不是：

- 每次信任升降的即时波动
- 只在当前状态里起作用的局部张力

### Relation Ownership Matrix

| 信息类型 | 主存对象 | 运行态表达 | 长期角色表达 | 说明 |
|---|---|---|---|---|
| 已成立且约束后文的关系事实 | `FactLedger` relation 条目 | `NarrativeState.active_relation_tensions` 可投影当前热区 | `CharacterModel.relations` 需同步长期基底 | 长期连续性先看账本 |
| 当前局势关系张力 | `NarrativeState.active_relation_tensions` | 同主存 | 必要时参考 `CharacterModel.relations` 解释原因 | 当前工作面先看状态 |
| 长期关系基底 / 弧段位置 | `CharacterModel.relations` | 必要时投影到当前 tension | 同主存 | 角色一致性先看角色模型 |
| 一次局部关系波动但未正式算数 | 不写入 `FactLedger` | 保留在 `NarrativeState` 或 `PlotUnit.relation_shift` | 不强制改 `CharacterModel` | 防止关系总账膨胀 |

### 入账阈值

关系变化至少满足以下其一，才建议进入 `FactLedger`：

1. 已被明确确认，而非仅停留在气氛
2. 会持续约束后续选择、权限或阵营位置
3. 若后文忽略，会形成明显连续性错误
4. 已被公开、制度化或具有高后果

### 写回规则

1. 当前关系波动先体现在 `PlotUnit` 与 `NarrativeState`
2. 若已跨过入账阈值，再写入 `FactLedger`
3. 若该变化也改变长期行为基底，再同步 `CharacterModel.relations`

### 冲突裁决

- “世界中这段关系是否已正式算数”看 `FactLedger`
- “当前这场戏里关系最紧张的点是什么”看 `NarrativeState`
- “这两个人长期的关系基底与行为惯性是什么”看 `CharacterModel`

### 风险 / 待验证项

- 某些半公开、半确认关系是否应提前入账，仍需样例压测
- `CharacterModel.relations` 的更新频率仍需防止膨胀

### 后续动作

`watch`

---

## 6. DEC-20260326-67

### 决策标题

ownership matrix 的默认写回顺序为：先长期硬约束，再当前工作集，最后角色侧长期摘要

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

即使主存对象已经明确，如果写回顺序不固定，仍会出现：

- 当前状态先改了，但长期约束没落账
- 角色摘要先改了，但世界中其实还没正式成立
- `Review` 读取到的对象层彼此错位

### 最终选择

默认按以下顺序处理 ownership-sensitive 写回：

1. 先确认是否已达到 `FactLedger` 入账条件
2. 若达到，先写长期硬约束
3. 再同步当前 `NarrativeState` 工作集表达
4. 最后只在必要时更新 `CharacterModel` 长期摘要

### 适用含义

对 knowledge：

- `FactLedger.known_by`
- `NarrativeState.private_information_map`
- `CharacterModel.knowledge_state`

对 relation：

- `FactLedger` relation 条目
- `NarrativeState.active_relation_tensions`
- `CharacterModel.relations`

### 选择理由

1. 先落长期硬约束，能避免后续 workflow 重猜“到底算不算数”
2. 当前工作集应承接已成立约束，而不是反过来替它裁决
3. 角色侧摘要最容易被滥写，所以应放在最后，并保持克制

### 风险 / 待验证项

- 已通过 `17_local_rewrite_writeback_exception.md` 做 first-pass 压测：只有当根因位于 `PlotUnit` / `NarrativeState` 且 `FactLedger` 本身不是根因时，才允许 bounded runtime-first repair
- 仍需更多 counterexample 验证该例外是否会被误扩张成默认顺序

### 后续动作

`watch`

---

## 7. 当前推荐的 Ownership Matrix 总表

| 问题 | 主存对象 | 当前工作集 | 长期角色摘要 | 当前状态 |
|---|---|---|---|---|
| 已成立知情事实 | `FactLedger.known_by` | `NarrativeState.private_information_map` 的相关子集 | 必要时 `CharacterModel.knowledge_state` | first-pass fixed |
| 当前信息分布 | `NarrativeState.private_information_map` | 同主存 | 一般不要求同步 | first-pass fixed |
| 稳定误判 / 长期认知偏差 | `CharacterModel.knowledge_state` | `NarrativeState.misinformation_in_effect` | 同主存 | first-pass fixed |
| 已成立关系事实 | `FactLedger` relation 条目 | `NarrativeState.active_relation_tensions` 的相关投影 | `CharacterModel.relations` 同步长期基底 | first-pass fixed |
| 当前关系张力 | `NarrativeState.active_relation_tensions` | 同主存 | 必要时参考 `CharacterModel.relations` | first-pass fixed |
| 长期关系基底 | `CharacterModel.relations` | 必要时投影到当前状态 | 同主存 | first-pass fixed |

---

## 8. 仍未完全结束的边界

本文件解决的是 ownership 的 first-pass 主体。

仍需继续压测的，不再是“谁大致负责什么”，而是：

- knowledge 变化何时必须升级入账
- relation 变化何时跨过入账阈值
- 局部 rewrite 的例外写回顺序
- 长链运行中 `CharacterModel` 摘要的 pruning / compaction 规则仍需更多反例压测

---

## 9. 一句话总结

`CharacterModel`、`NarrativeState`、`FactLedger` 的关系不应再被理解为三个都能记同一件事，而应被理解为：硬约束、当前工作面、角色侧长期摘要三层分工。
