
# 规则索引

## 文档目的
本文件是 `03_rules/` 目录的总入口，用于统一说明自动小说系统中各类规则的职责、适用范围、调用顺序与相互关系。

它不直接定义某一条具体规则，而是回答：

- 当前规则层包含哪些文件
- 每个规则文件解决什么问题
- 规则之间的先后顺序是什么
- 一次正式审查应该先调用哪些规则
- 哪些规则属于运行规则，哪些属于审查规则，哪些属于失败归类规则

---

## 1. 规则层的定位

规则层位于：

- 项目层之下
- 概念层之上
- 数据模型层之后
- 工作流层之前

它的作用是把前面已经定义好的：

- 概念对象
- 数据结构
- 字段更新方式

转化成：

- 系统如何运行
- 系统如何判断
- 系统如何发现失败
- 系统如何形成修正闭环

---

## 2. 当前规则层文件清单

当前规则层包含以下文件：

- `03_rules/00_rule_index.md`
- `03_rules/01_state_transition_rules.md`
- `03_rules/02_world_legality_rules.md`
- `03_rules/03_character_consistency_rules.md`
- `03_rules/04_timeline_rules.md`
- `03_rules/05_information_release_rules.md`
- `03_rules/06_foreshadow_rules.md`
- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`

---

## 3. 各规则文件的职责

---

## 3.1 `01_state_transition_rules.md`
### 作用
定义状态如何从 A 变成 B。

### 主要回答
- 一个 `PlotUnit` 什么时候算成立
- 什么叫有效推进
- 输入状态和输出状态如何连接
- 推进后哪些对象必须同步更新

### 核心服务对象
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`

---

## 3.2 `02_world_legality_rules.md`
### 作用
定义世界规则、资源、制度、环境和后果是否被正确遵守。

### 主要回答
- 这件事在这个世界里能不能发生
- 发生之后要不要付代价
- 世界规则有没有被跳过
- 制度反应有没有缺席

### 核心服务对象
- `WorldModel`
- `PlotUnit`
- `FactLedger`

---

## 3.3 `03_character_consistency_rules.md`
### 作用
定义角色的行动、关系与成长是否仍然符合角色模型。

### 主要回答
- 这个角色为什么会这样做
- 这个选择是否有足够动机
- 这段关系变化是不是跳了
- 这个成长是不是突然发生的

### 核心服务对象
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`

---

## 3.4 `04_timeline_rules.md`
### 作用
定义事件顺序、因果顺序、知情顺序与并行线同步是否合法。

### 主要回答
- 这件事是不是发生得太早或太晚
- 结果是不是早于原因
- 角色是不是在不可能的时间点知道了某件事
- 多线推进是否互相冲突

### 核心服务对象
- `NarrativeState`
- `PlotUnit`
- `FactLedger`

---

## 3.5 `05_information_release_rules.md`
### 作用
定义信息应该什么时候、以什么方式、被谁知道。

### 主要回答
- 当前哪些信息可以释放
- 哪些信息只能对读者开放
- 哪些信息还必须保密
- 信息释放后有没有产生后果

### 核心服务对象
- `NarrativeState`
- `CharacterModel`
- `FactLedger`
- `ForeshadowGraph`

---

## 3.6 `06_foreshadow_rules.md`
### 作用
定义伏笔、承诺、误导与回收的建立、推进和管理规则。

### 主要回答
- 什么算正式承诺
- 承诺是否被推进
- 回收是否突兀
- 假线索是否失控
- 主线承诺是否被遗失

### 核心服务对象
- `ForeshadowGraph`
- `PlotUnit`
- `NarrativeState`

---

## 3.7 `07_review_rules.md`
### 作用
定义系统如何做正式审查。

### 主要回答
- 审查先看什么
- 审查顺序是什么
- 审查结果怎么转成 `ReviewIssue`
- 哪些问题先修，哪些后修

### 核心服务对象
- 所有核心对象
- 尤其是 `ReviewIssue`

---

## 3.8 `08_failure_types.md`
### 作用
定义失败字典，用统一分类描述“系统哪里坏了”。

### 主要回答
- 什么叫 `fact_conflict`
- 什么叫 `world_violation`
- 什么叫 `promise_loss`
- 什么叫 `abrupt_payoff`
- 哪些失败属于阻断型问题

### 核心服务对象
- `ReviewIssue`
- 审查日志
- 实验记录

---

## 4. 规则层的三大类别

为了方便后续使用，建议把规则层分成三类。

---

## 4.1 运行规则
用于定义系统“怎么动”。

包括：

- `01_state_transition_rules.md`

### 特点
- 直接服务生成与推进
- 主要决定从前态到后态的合法路径
- 偏运行时逻辑

---

## 4.2 审查规则
用于定义系统“怎么查”。

包括：

- `02_world_legality_rules.md`
- `03_character_consistency_rules.md`
- `04_timeline_rules.md`
- `05_information_release_rules.md`
- `06_foreshadow_rules.md`
- `07_review_rules.md`

### 特点
- 直接服务审查与修复
- 主要决定某次推进是否成立
- 偏校验逻辑

---

## 4.3 失败归类规则
用于定义系统“查出来的问题怎么命名”。

包括：

- `08_failure_types.md`

### 特点
- 服务问题归类
- 服务实验记录
- 服务修复优先级排序

---

## 5. 规则调用顺序

建议正式审查时，规则按以下顺序调用。

### 第一步：状态转移检查
先确认这次推进本身是否构成有效状态变化。

调用：
- `01_state_transition_rules.md`

### 第二步：硬合法性检查
再确认有没有直接破坏系统成立。

调用：
- `02_world_legality_rules.md`
- `04_timeline_rules.md`
- `05_information_release_rules.md`

### 第三步：角色与关系检查
再判断角色行为和关系变化是否成立。

调用：
- `03_character_consistency_rules.md`

### 第四步：承诺与结构检查
再判断主线、伏笔、承诺是否失控。

调用：
- `06_foreshadow_rules.md`

### 第五步：综合审查与问题建单
最后汇总结果，生成审查结论与 `ReviewIssue`。

调用：
- `07_review_rules.md`
- `08_failure_types.md`

---

## 6. 一次标准审查的推荐顺序

推荐用下面这个顺序做一次完整审查：

1. 当前 `PlotUnit` 是否造成状态变化  
2. 当前推进是否违反世界规则  
3. 当前推进是否违反时间顺序  
4. 当前推进是否发生信息越界  
5. 当前角色行为是否符合模型  
6. 当前关系变化是否有桥接  
7. 当前承诺是否得到推进或被正确管理  
8. 当前是否需要生成 `ReviewIssue`  
9. 当前问题属于哪种失败类型  
10. 当前问题的修复优先级是什么  

---

## 7. 规则之间的依赖关系

建议按如下关系理解规则层：

```text
01_state_transition_rules
    ↓
02_world_legality_rules
03_character_consistency_rules
04_timeline_rules
05_information_release_rules
06_foreshadow_rules
    ↓
07_review_rules
    ↓
08_failure_types
```

### 含义

- `01` 决定有没有“推进”
- `02` 到 `06` 决定“推进是否成立”
- `07` 决定“如何汇总审查结果”
- `08` 决定“把失败叫什么”

---

## 8. 规则层与其他目录的关系

## 8.1 与 `01_concepts/` 的关系

概念层回答：

- 它是什么
- 它不是什么
- 它与谁有关

规则层回答：

- 它什么时候成立
- 它什么时候失效
- 它什么时候出错

---

## 8.2 与 `02_data_models/` 的关系

数据模型层回答：

- 字段有哪些
- 字段如何分类
- 字段由谁更新

规则层回答：

- 什么时候该更新这些字段
- 字段更新后如何判断是否合法

---

## 8.3 与 `04_workflows/` 的关系

规则层定义：

- 能不能这样做
- 做完怎么判断对不对

工作流层则会定义：

- 实际按什么顺序做
- 输入输出如何串联
- 哪一步生成、哪一步审查、哪一步修正

---

## 9. 规则层的使用建议

### 9.1 先用总规则，再看专项规则

若先快速判断一次推进是否成立，优先看：

- `01_state_transition_rules.md`
- `07_review_rules.md`

若要细查具体问题，再进入专项规则：

- 世界 → `02`
- 角色 → `03`
- 时间 → `04`
- 信息 → `05`
- 伏笔 → `06`

---

## 9.2 规则不替代作者判断

规则的作用是：

- 帮你发现明显失真
- 帮你稳定系统边界
- 帮你把问题对象化

规则不直接替代作者决定：

- 哪个方向更有美学价值
- 哪种取舍更符合你的作品气质

---

## 9.3 规则要优先服务 mock case

如果某条规则无法落到样例上，它就还不够成熟。

---

## 10. 当前规则层已覆盖的问题

当前规则层已经能够覆盖：

- 状态推进是否成立
- 世界是否合法
- 角色是否失真
- 时间是否冲突
- 信息是否越界
- 承诺是否遗失
- 回收是否突兀
- 问题如何建单
- 失败如何归类

这意味着规则层已经具备“最小可审查系统”的雏形。

---

## 11. 当前规则层还未覆盖的内容

虽然规则主干已经成型，但还没有进入：

- 真实 workflow 串联
- mock case 全链路验证
- 批量实验日志
- 修复策略模板库

这些内容将在后续目录中继续补齐：

- `04_workflows/`
- `05_examples/`
- `06_experiments/`
- `07_decisions/`

---

## 12. 最小使用清单

当你准备审查一个 `PlotUnit` 时，最少按下面顺序看：

1. `01_state_transition_rules.md`
2. `02_world_legality_rules.md`
3. `03_character_consistency_rules.md`
4. `04_timeline_rules.md`
5. `05_information_release_rules.md`
6. `06_foreshadow_rules.md`
7. `07_review_rules.md`
8. `08_failure_types.md`

---

## 13. 一句话总结

`03_rules/00_rule_index.md` 的作用，是把整套规则层整理成一张可执行地图，让系统知道：

**先怎么推进，再怎么检查，最后怎么命名失败。**
