
# 失败类型

## 文档目的
本文件用于统一定义自动小说系统中的“失败类型”。

它回答的不是“哪里写得不够好看”，而是：

- 什么情况算系统性失败
- 不同失败类型之间如何区分
- 哪些失败属于阻断型问题
- 哪些失败属于结构性问题
- 哪些失败属于表达性问题
- 失败类型如何映射到 `ReviewIssue`

本文件主要连接以下对象：

- `PlotUnit`
- `NarrativeState`
- `CharacterModel`
- `WorldModel`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

---

## 1. 核心定义

### 1.1 失败类型是什么
失败类型是指：

**当一次叙事推进、一次状态更新、一次承诺管理或一次信息释放没有满足系统规则时，对其失败性质进行的稳定分类。**

它的作用不是批评文本，而是把失败变成：

- 可识别
- 可归类
- 可统计
- 可修复
- 可复盘

的问题对象。

### 1.2 为什么必须定义失败类型
如果不定义失败类型，系统只会输出：

- 这里不太对
- 这段有点怪
- 感觉人设飘了
- 节奏怪怪的

这种反馈无法形成闭环。

定义失败类型的目的，是把“模糊不对劲”压缩成：

- 具体问题名
- 具体触发条件
- 具体修复方向

---

## 2. 失败类型总原则

### 2.1 失败先于优化
先判断“成立不成立”，再讨论“高级不高级”。

### 2.2 一次失败尽量只归一个核心类
一个问题可以有关联类型，但应尽量确定主失败类型。

### 2.3 失败类型要服务修复
失败分类不是为了漂亮，而是为了知道下一步怎么改。

### 2.4 失败类型要服务统计
后续实验记录、审查日志、修复优先级都要依赖这套分类。

---

## 3. 一级失败类型总表

当前建议使用以下一级失败类型：

1. `fact_conflict`
2. `world_violation`
3. `timeline_error`
4. `information_leak`
5. `weak_progression`
6. `character_distortion`
7. `motivation_gap`
8. `relationship_jump`
9. `promise_loss`
10. `abrupt_payoff`
11. `missing_cost`
12. `missing_consequence`
13. `redundancy`
14. `style_drift`
15. `duplication_of_threads`

---

## 4. 分类框架

建议把失败类型分为四大层级。

### 4.1 硬错误层
一旦出现，优先阻断后续生成：

- `fact_conflict`
- `world_violation`
- `timeline_error`
- `information_leak`

### 4.2 推进与角色层
会快速污染后续剧情的中高风险问题：

- `weak_progression`
- `character_distortion`
- `motivation_gap`
- `relationship_jump`
- `missing_cost`

### 4.3 结构与承诺层
会伤害中长期阅读张力与整体结构：

- `promise_loss`
- `abrupt_payoff`
- `missing_consequence`
- `duplication_of_threads`

### 4.4 表达与表面层
通常不直接阻断系统成立，但会影响读感：

- `redundancy`
- `style_drift`

---

## 5. 硬错误层失败类型

---

## 5.1 `fact_conflict`

### 定义
当前输出与 `FactLedger` 中已确认事实直接冲突。

### 典型表现
- 死去角色再次正常出现
- 已毁物品重新被使用
- 已公开秘密又被写成完全无人知晓
- 已确立关系被写成未建立

### 触发条件
以下任一成立即可：
- 与高优先级事实直接矛盾
- 与时间顺序中的已确认事实矛盾
- 与已记录状态冲突，且无替代解释

### 常见修法
- `fact_correction`
- `state_update`
- `local_rewrite`

### 严重等级建议
通常至少为 `high`，多数情况下可视为 `critical`

---

## 5.2 `world_violation`

### 定义
当前事件、行为、结果或解法违反了 `WorldModel` 的规则、秩序、资源逻辑或因果逻辑。

### 典型表现
- 禁行动作零成本完成
- 世界硬规则被临时突破
- 制度后果完全缺席
- 稀缺资源被无限使用

### 触发条件
以下任一成立即可：
- 违反 `hard_rules`
- 违反 `forbidden_actions`
- 忽视 `consequence_rules`
- 无视身份/权限/资源边界

### 常见修法
- `local_rewrite`
- `cost_insertion`
- `arc_replanning`

### 严重等级建议
通常为 `high` 或 `critical`

---

## 5.3 `timeline_error`

### 定义
时间顺序、事件顺序、因果顺序或并行线同步发生冲突。

### 典型表现
- 结果早于原因
- 角色在两个地点同时存在
- 信息先被使用后被获得
- 插叙污染当前时间线

### 触发条件
以下任一成立即可：
- `chronological_order` 冲突
- 当前时间锚点与前后态冲突
- 并行线互相打架
- 因果顺序倒置

### 常见修法
- `state_update`
- `fact_correction`
- `local_rewrite`

### 严重等级建议
通常为 `high`，严重时为 `critical`

---

## 5.4 `information_leak`

### 定义
角色、视角或叙事层获得了不该在此时获得的信息。

### 典型表现
- 角色突然知道真相
- 限制视角越界到别人内心
- 假线索误入事实层
- 角色使用了尚未获得的信息

### 触发条件
以下任一成立即可：
- `private_information_map` 与文本不一致
- `known_by` 与角色行为不一致
- 当前 POV 获取非法信息
- 误导与真相混账

### 常见修法
- `info_gate_adjustment`
- `state_update`
- `local_rewrite`

### 严重等级建议
通常为 `high`

---

## 6. 推进与角色层失败类型

---

## 6.1 `weak_progression`

### 定义
当前 `PlotUnit` 没有形成足够有效的状态变化。

### 典型表现
- 热闹但不改变后续
- 情绪波动但无实质推进
- 重复旧信息
- 删除后几乎不伤主线

### 触发条件
以下任一成立即可：
- `state_change_summary` 为空或极弱
- 目标、信息、关系、风险、冲突均无明显变化
- 本单元只重复上一单元作用

### 常见修法
- `local_rewrite`
- `relationship_bridge_scene`
- `foreshadow_advancement`

### 严重等级建议
通常为 `medium`，连续出现可升级为 `high`

---

## 6.2 `character_distortion`

### 定义
角色行为明显违背 `CharacterModel`，且缺少足够路径或代价。

### 典型表现
- 人设突然反转
- 长期恐惧和缺陷消失
- 角色突然变成另一个人
- 行动只服务情节，不服务人物逻辑

### 触发条件
以下任一成立即可：
- 行为与 `fear` / `flaw` / `inner_need` 强冲突
- 无铺垫完成立场大转变
- 角色决策与自身目标结构脱节

### 常见修法
- `character_motivation_patch`
- `local_rewrite`
- `arc_replanning`

### 严重等级建议
通常为 `high`

---

## 6.3 `motivation_gap`

### 定义
角色行为方向可以理解，但缺少足够动机承接和桥接过程。

### 典型表现
- 突然信任
- 突然合作
- 突然坦白
- 突然改变优先目标

### 与 `character_distortion` 的区别
- `character_distortion` 更像“写成了另一个人”
- `motivation_gap` 更像“方向能理解，但中间缺了桥”

### 常见修法
- `character_motivation_patch`
- `relationship_bridge_scene`
- `local_rewrite`

### 严重等级建议
通常为 `medium` 到 `high`

---

## 6.4 `relationship_jump`

### 定义
关系强度或关系性质发生跳变，但缺少连续路径。

### 典型表现
- 极不信任突然托付秘密
- 宿敌突然和解
- 刚发生背叛，后续毫无余波
- 恋爱线突然确认

### 常见修法
- `relationship_bridge_scene`
- `state_update`
- `local_rewrite`

### 严重等级建议
通常为 `medium` 或 `high`

---

## 6.5 `missing_cost`

### 定义
某高风险行为、强能力使用、重大越界或关键关系推进缺少应有代价。

### 典型表现
- 越阶能力无反噬
- 公开越界无惩罚
- 情绪突破无代价
- 信任跃迁无风险

### 常见修法
- `cost_insertion`
- `state_update`
- `local_rewrite`

### 严重等级建议
通常为 `medium` 到 `high`

---

## 7. 结构与承诺层失败类型

---

## 7.1 `promise_loss`

### 定义
一条已建立的重要承诺线程长期未得到推进、回应或管理。

### 典型表现
- 主线谜团长期停摆
- 已建立关系承诺没有后续动作
- 某线程一直重复旧问题，不收紧不扩展
- 系统默认忘掉了某条承诺

### 常见修法
- `foreshadow_advancement`
- `arc_replanning`
- `state_update`

### 严重等级建议
视线程重要度而定，`core` 级可为 `high`

---

## 7.2 `abrupt_payoff`

### 定义
某条承诺的回收、揭晓、确认或反转来得过快、过猛、缺少路径。

### 典型表现
- 小铺垫硬拉大揭晓
- 两章前刚埋伏笔，下一章直接揭晓
- 情绪确认没有累积
- 世界规则解释像临时补丁

### 常见修法
- `foreshadow_advancement`
- `local_rewrite`
- `arc_replanning`

### 严重等级建议
通常为 `medium` 到 `high`

---

## 7.3 `missing_consequence`

### 定义
某次揭露、回收、越界、关系变化或世界反馈发生后，没有带来应有后果。

### 典型表现
- 秘密暴露后无人反应
- 关系确认后状态不变
- 制度真相揭晓后局势无变化
- 世界规则被解释后没有行动空间变化

### 常见修法
- `state_update`
- `cost_insertion`
- `fact_correction`

### 严重等级建议
通常为 `medium`，对核心线可升至 `high`

---

## 7.4 `duplication_of_threads`

### 定义
多个承诺线程、谜题线程或结构线程在本质上重复，导致注意力分散或主线混乱。

### 典型表现
- 三条不同“神秘身世”线本质讲同一件事
- 多条关系承诺争抢同一结构位置
- 同类谜题重复占位

### 常见修法
- `thread_cleanup`
- `arc_replanning`
- `state_update`

### 严重等级建议
通常为 `medium`

---

## 8. 表达与表面层失败类型

---

## 8.1 `redundancy`

### 定义
当前内容重复、注水或功能重叠严重。

### 典型表现
- 重复说明已知信息
- 重复关系温度
- 换地点说同样的话
- 本单元可以并入前后单元

### 常见修法
- `scene_merge`
- `local_rewrite`

### 严重等级建议
通常为 `low` 到 `medium`

---

## 8.2 `style_drift`

### 定义
输出在视角、调性、语言密度、情绪密度等方面明显偏离 `WorkSpec` 或当前表达策略。

### 典型表现
- 限制视角突然全知
- 克制文风突然极端外放
- 网文节奏突然大段空转抒情
- 多章间像换了叙述者

### 常见修法
- `style_realignment`
- `local_rewrite`

### 严重等级建议
通常为 `low` 到 `medium`，严重视角错误可升高

---

## 9. 失败类型之间的主次关系

一个问题可能同时触发多个失败类型，但建议只选一个**主失败类型**。

### 9.1 选择主类型的原则
优先选择：
1. 最直接破坏系统成立的类型
2. 最能指导修复的类型
3. 最靠近根因的类型

### 9.2 示例
#### 情况 A
角色突然信任宿敌，且没有桥接  
可触发：
- `motivation_gap`
- `relationship_jump`

主类型建议：
- `relationship_jump`  
若问题核心在关系跃迁本身

#### 情况 B
角色突然信任宿敌，且行为完全违背其核心恐惧  
可触发：
- `character_distortion`
- `motivation_gap`
- `relationship_jump`

主类型建议：
- `character_distortion`  
因为根因更深

---

## 10. 严重等级建议

建议失败类型默认严重度如下：

| 失败类型 | 默认严重度 |
|---|---|
| `fact_conflict` | high / critical |
| `world_violation` | high / critical |
| `timeline_error` | high / critical |
| `information_leak` | high |
| `character_distortion` | high |
| `motivation_gap` | medium / high |
| `relationship_jump` | medium / high |
| `weak_progression` | medium |
| `missing_cost` | medium / high |
| `promise_loss` | medium / high |
| `abrupt_payoff` | medium / high |
| `missing_consequence` | medium |
| `duplication_of_threads` | medium |
| `redundancy` | low / medium |
| `style_drift` | low / medium |

---

## 11. 阻断规则

建议以下失败类型默认具有阻断倾向：

### 默认阻断
- `fact_conflict`
- `world_violation`
- `timeline_error`

### 条件性阻断
- `information_leak`
- `character_distortion`
- `abrupt_payoff`

### 通常不阻断
- `redundancy`
- `style_drift`
- `duplication_of_threads`

---

## 12. 与 ReviewIssue 的映射规则

每一个正式失败类型，都应可以映射为一个 `ReviewIssue.issue_type`。

### 最小映射规则
- 失败类型 = `ReviewIssue.issue_type`
- 失败根因 = `violated_rule` + `supporting_facts`
- 修复方向 = `suggested_fix_type`
- 严重度 = `severity`
- 阻断性 = `blocking_status`

---

## 13. 最小判定模板

```text
失败类型判定

审查对象：
- PlotUnit：
- 状态：
- 相关对象：

一、是否存在硬错误
- fact_conflict：
- world_violation：
- timeline_error：
- information_leak：

二、是否存在推进或角色失败
- weak_progression：
- character_distortion：
- motivation_gap：
- relationship_jump：
- missing_cost：

三、是否存在承诺与结构失败
- promise_loss：
- abrupt_payoff：
- missing_consequence：
- duplication_of_threads：

四、是否存在表达层失败
- redundancy：
- style_drift：

五、主失败类型
- 主类型：
- 次类型：

六、处理建议
- issue_type：
- severity：
- suggested_fix_type：
```

---

## 14. 示例：雨夜夺令的失败类型判定

### 当前单元检查

- 无 `fact_conflict`
- 无 `world_violation`
- 无 `timeline_error`
- 无严重 `information_leak`

### 风险点

- 如果后续两章不体现旧伤和巡查压力，会转成：
- `missing_cost`
- `missing_consequence`
- 如果后续直接让 c002 完全信任 c001，会转成：
- `relationship_jump`
- `motivation_gap`
- 如果主线秘密推进后没有继续逼近，会转成：
- `promise_loss`

### 当前结论

当前单元没有正式失败类型，但存在三个**预警型潜在失败**。

这类潜在失败建议暂不建高优先级 issue，除非后续确认未处理。

---

## 15. 一句话总结

失败类型文档的核心作用，是把“写坏了”拆成一套稳定的失败字典，让系统知道：

**到底坏在哪一层、为什么坏、优先修哪一种坏法。**
