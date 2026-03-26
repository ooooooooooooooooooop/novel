
# 示例索引

## 文档目的
本文件是 `05_examples/` 目录的总入口，用于统一说明自动小说系统中样例文件的职责、使用顺序、验证目标与覆盖范围。

它不直接定义某一个对象，也不直接承担工作流功能，而是回答：

- 示例层为什么存在
- 当前应该准备哪些样例
- 每个样例文件验证什么
- 示例层如何与概念层、数据模型层、规则层、工作流层衔接
- 一次 mock case 应该如何使用这些样例

---

## 1. 示例层的定位

示例层位于：

- 项目层之后
- 概念层之后
- 数据模型层之后
- 规则层之后
- 工作流层之后

它的作用是把前面已经建立好的：

- 概念对象
- schema
- 规则系统
- 工作流系统

放进一个**可验证、可复盘、可试跑**的具体案例里。

### 一句话定义
示例层的任务，不是再讲一遍理论，而是证明这套理论能不能真的落地。

---

## 2. 为什么必须有示例层

如果没有示例层，前面所有内容虽然“结构上成立”，但仍然可能存在以下问题：

1. 概念定义彼此边界不清  
2. schema 字段太多但不好用  
3. 规则写得正确但无法执行  
4. 工作流顺序看起来合理，但实际跑不通  
5. 多个对象之间的引用关系在真实案例里出现冲突  
6. 审查规则在案例里找不到足够支点  

因此，示例层的目标是：

- 验证抽象是否可用
- 验证字段是否足够
- 验证规则是否可执行
- 验证工作流是否闭环
- 为后续实验与决策提供样本

---

## 3. 示例层文件清单

当前建议包含以下文件：

- `05_examples/00_example_index.md`
- `05_examples/01_sample_workspec.md`
- `05_examples/02_sample_worldmodel.md`
- `05_examples/03_sample_characters.md`
- `05_examples/04_sample_plotunit.md`
- `05_examples/05_sample_factledger.md`
- `05_examples/06_sample_review.md`
- `05_examples/07_mock_project_case.md`

---

## 4. 各示例文件的职责

## 4.1 `01_sample_workspec.md`
### 作用
提供一个最小但完整的作品规格样例。

### 验证目标
验证：
- `WorkSpec Schema` 是否足够表达作品方向
- 作品级约束是否能真正约束后续对象
- genre、theme、pacing、narration_mode 等字段是否足够清晰

### 主要对应
- `01_concepts/01_workspec.md`
- `02_data_models/01_workspec_schema.md`

---

## 4.2 `02_sample_worldmodel.md`
### 作用
提供一个可运行的世界模型样例。

### 验证目标
验证：
- 世界规则是否能支撑剧情约束
- 资源、制度、代价、阵营是否足够构成合法性检查
- `WorldModel` 是否不是装饰背景，而是真正参与运行

### 主要对应
- `01_concepts/02_worldmodel.md`
- `02_data_models/02_worldmodel_schema.md`
- `03_rules/02_world_legality_rules.md`

---

## 4.3 `03_sample_characters.md`
### 作用
提供一组角色模型样例。

### 验证目标
验证：
- `CharacterModel` 是否真能解释角色决策
- 关系字段是否足以推动冲突
- 恐惧、缺陷、目标、成长字段是否能服务审查与续写

### 主要对应
- `01_concepts/03_charactermodel.md`
- `02_data_models/03_charactermodel_schema.md`
- `03_rules/03_character_consistency_rules.md`

---

## 4.4 `04_sample_plotunit.md`
### 作用
提供一个完整推进单元样例。

### 验证目标
验证：
- `PlotUnit` 是否真能表达“状态从 A 到 B 的转移”
- 输入状态、关键决策、冲突、事件、输出状态之间是否能闭环
- `state_change_summary` 是否足以支持审查

### 主要对应
- `01_concepts/05_plotunit.md`
- `02_data_models/05_plotunit_schema.md`
- `03_rules/01_state_transition_rules.md`

---

## 4.5 `05_sample_factledger.md`
### 作用
提供一组事实账本条目样例。

### 验证目标
验证：
- 哪些内容应该进入账本
- 事实、误导、推断是否能被分开
- `visibility`、`known_by`、`status` 等字段是否足够支撑连续性与信息合法性检查

### 主要对应
- `01_concepts/06_factledger.md`
- `02_data_models/06_factledger_schema.md`
- `03_rules/04_timeline_rules.md`
- `03_rules/05_information_release_rules.md`

---

## 4.6 `06_sample_review.md`
### 作用
提供一个正式审查样例。

### 验证目标
验证：
- 一次完整审查如何落地
- 失败类型如何映射为 `ReviewIssue`
- `Review Workflow` 是否真正能闭环

### 主要对应
- `01_concepts/08_reviewissue.md`
- `02_data_models/08_reviewissue_schema.md`
- `03_rules/07_review_rules.md`
- `03_rules/08_failure_types.md`
- `04_workflows/02_review_workflow.md`

---

## 4.7 `07_mock_project_case.md`
### 作用
提供一个贯穿式 mock case。

### 验证目标
验证一套最小项目能否从以下对象全链路串起来：
- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

### 主要对应
- 全目录联调验证

---

## 5. 示例层的三种用途

## 5.1 结构验证
用于检验对象与 schema 是否能表达真实案例。

### 重点看
- 字段是否够用
- 字段是否冗余
- 字段边界是否清晰
- 是否存在“只能理论成立，不能实际填写”的情况

---

## 5.2 规则验证
用于检验规则是否能对样例做出稳定判断。

### 重点看
- 世界合法性规则能否抓到越界
- 角色一致性规则能否抓到失真
- 信息释放规则能否抓到知情越界
- 承诺规则能否抓到遗失或突兀回收

---

## 5.3 工作流验证
用于检验一条工作流是否真的能跑通。

### 重点看
- 输入是否足够
- 中间步骤是否合理
- 输出是否可回写
- 审查后是否能形成下一步动作

---

## 6. 示例层的使用顺序

建议按以下顺序使用样例文件。

### 第一步：静态对象样例
先看：
- `01_sample_workspec.md`
- `02_sample_worldmodel.md`
- `03_sample_characters.md`

目标：
先验证项目底座。

### 第二步：运行单元样例
再看：
- `04_sample_plotunit.md`
- `05_sample_factledger.md`

目标：
验证推进与记账。

### 第三步：审查样例
再看：
- `06_sample_review.md`

目标：
验证规则与失败归类。

### 第四步：贯穿样例
最后看：
- `07_mock_project_case.md`

目标：
验证整套系统是不是能真的跑一遍。

---

## 7. 示例层与前面目录的关系

## 7.1 与概念层的关系
概念层定义：
- 它是什么

示例层验证：
- 它在真实案例里是不是还能保持这个定义

---

## 7.2 与数据模型层的关系
数据模型层定义：
- 字段有哪些

示例层验证：
- 这些字段能不能真的填
- 填完是否足够支持后续步骤

---

## 7.3 与规则层的关系
规则层定义：
- 什么时候成立
- 什么时候出错

示例层验证：
- 这些规则是不是能在具体案例里抓到问题
- 是否存在“规则写得很全，但一落地就模糊”的情况

---

## 7.4 与工作流层的关系
工作流层定义：
- 实际怎么跑

示例层验证：
- 这条流程拿样例跑时，会不会中途断掉
- 是否需要补对象、补字段、补规则

---

## 8. 示例设计原则

所有样例建议遵守以下原则。

### 8.1 小而完整
不要一开始就做特别大的案例。  
先保证：
- 样例小
- 结构完整
- 能闭环

### 8.2 一例多用
一个样例最好同时能验证多个对象和规则。

例如：
“雨夜夺令”这种例子，就能同时验证：
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- 审查规则

### 8.3 先强约束，再扩丰富度
先保证样例中的：
- 主目标
- 主冲突
- 主承诺
- 主后果
足够清楚

不要一开始就追求复杂支线。

### 8.4 样例必须能复跑
最好让一个样例能被：
- 重建工作流使用
- 续写工作流使用
- 审查工作流使用
- 改写工作流使用

---

## 9. 推荐的示例统一世界

为了降低复杂度，建议当前示例层先统一使用一个 mock 项目世界。

### 推荐统一案例
以你前面已经反复使用的这套案例为默认示例：

- 主角：`c001 / 沈青`
- 核心背景：被逐出宗门、体内封存残魂
- 当前阶段：试炼前夜、黑水泽外围
- 主承诺：
  - 身世之谜
  - 残魂秘密
  - c002 是否会保密
- 核心事件：
  - 雨夜夺令
- 当前风险：
  - 巡查队逼近
  - 旧伤复发
  - 半暴露状态

### 这样做的好处
- 所有样例都能互相衔接
- 可以很快组成一个完整 mock case
- 不需要每份样例都重新发明世界

---

## 10. 示例层的完成标准

示例层不要求“内容多”，而要求“验证有效”。

建议以下条件满足时，可视为示例层初步完成：

1. 至少有一份完整 `WorkSpec` 示例  
2. 至少有一份完整 `WorldModel` 示例  
3. 至少有三位主要角色的 `CharacterModel` 示例  
4. 至少有一个完整 `PlotUnit` 示例  
5. 至少有一组 `FactLedger` 示例  
6. 至少有一份正式审查样例  
7. 至少有一个从输入到审查的贯穿 mock case  

---

## 11. 当前建议的编写顺序

建议按以下顺序继续写：

### 第一优先
`05_examples/01_sample_workspec.md`

### 第二优先
`05_examples/02_sample_worldmodel.md`

### 第三优先
`05_examples/03_sample_characters.md`

### 第四优先
`05_examples/04_sample_plotunit.md`

### 第五优先
`05_examples/05_sample_factledger.md`

### 第六优先
`05_examples/06_sample_review.md`

### 第七优先
`05_examples/07_mock_project_case.md`

---

## 12. 示例层的输出目标

当示例层跑通后，你会得到三种非常重要的东西：

### 12.1 可验证模板
以后每次做新项目时，不需要从零猜对象怎么写。

### 12.2 可复盘案例
以后发现规则有问题，可以拿样例回头验证。

### 12.3 可训练地基
无论以后是给 Codex 看、给自己复用，还是做进一步实现，样例层都会成为最重要的“最小真数据”。

---

## 13. 一句话总结

`05_examples/00_example_index.md` 的作用，是把前面已经搭好的系统，从“理论结构”推进到“可验证结构”，让每一个对象、规则和工作流，都有一个真正能落地的样例可以对照。
