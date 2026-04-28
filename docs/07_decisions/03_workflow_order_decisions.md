# 工作流顺序决策

## 文档目的
本文件用于收束当前阶段已经基本确定的工作流顺序、分流条件、写回顺序与升级条件相关决策。

它回答的不是某一条 workflow 具体怎么写，而是更上层的问题：

- 为什么这几条 workflow 要按当前顺序协作
- 什么情况下必须先 `Rebuild`
- 为什么 `Continue` 后不能直接再 `Continue`
- 为什么 `Rewrite` 必须由正式问题对象驱动
- 当多个对象都需要更新时，应该先改谁、后改谁
- 当不同对象之间出现冲突时，当前以谁为准

本文件的作用，是防止后续扩展时出现：

- workflow 顺序混乱
- 审查缺位
- 改写入口不清
- 局部修复与结构重排混用
- 对象回写顺序不稳定

---

## 1. 文档定位

[01_foundation_decisions.md](01_foundation_decisions.md) 固定总体方向。  
[02_model_boundary_decisions.md](02_model_boundary_decisions.md) 固定对象边界。  
本文件固定的是：

**这套系统“先做什么、后做什么、什么时候转向、对象按什么顺序写回”的流程级共识。**

它主要影响：

- `04_workflows/`
- `03_rules/07_review_rules.md`
- `02_data_models/09_field_rules.md`
- `05_examples/`
- `06_experiments/`

---

## 2. 当前需要固定的顺序问题

当前最值得固定的顺序类问题主要有 11 个：

1. 为什么 `Rebuild` 先于 `Continue`
2. 为什么 `Review` 是 workflow 中枢
3. 为什么 `Continue` 后必须立即进入 `Review`
4. 为什么 `Rewrite` 必须由正式问题对象驱动
5. 什么情况下 warning 先留在推进链，而不是立即改写
6. 什么情况下应从 `Rewrite` 升级为 `Replan`
7. 为什么当前不把“正文生成”独立成第一优先 workflow
8. 为什么当前 workflow 先服务 mock case，而不是先服务大规模通用输入
9. `Continue` 内部的对象写回顺序如何固定
10. `Rewrite` 内部的联动修复顺序如何固定
11. 当多个对象记录不一致时，当前以谁为准

---

## 3. DEC-20260326-16

### 决策标题

当当前状态不清时，必须先 `Rebuild`，再 `Continue`

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

很多任务表面上像“继续写”，但系统实际上并不清楚：

- 故事当前推进到哪里
- 当前谁在场
- 当前主目标是什么
- 当前冲突是什么
- 谁知道什么
- 哪些承诺已经建立

如果此时直接进入 `Continue`，续写就会退化成基于印象的自由推进。

### 备选方案

- 方案 A：只要用户说“继续”，就直接走 `Continue`
- 方案 B：若当前状态不清，则必须先走 `Rebuild`

### 最终选择

采用方案 B。

### 选择理由

1. `Continue` 的前提是已有可用的 `NarrativeState`
2. 没有当前状态，续写最容易丢失目标、信息边界和承诺线程
3. `Rebuild` 的本质就是给 `Continue` 提供合法起点

### 影响范围

- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/03_continue_workflow.md`

### 风险 / 待验证项

- 仍需验证：是否存在“轻量 rebuild”即可支撑继续推进的场景

### 后续动作

`watch`

---

## 4. DEC-20260326-17

### 决策标题

`Review` 是四条 workflow 的中枢

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

在 workflow 关系中，`Review` 不能只是一个可选附加检查，而必须承担正式分流职责。

### 备选方案

- 方案 A：把 `Review` 视为可选附加步骤
- 方案 B：把 `Review` 视为所有运行 workflow 的中枢节点

### 最终选择

采用方案 B。

### 选择理由

1. `Rebuild` 后需要 `Review` 判断对象层是否足够稳定
2. `Continue` 后需要 `Review` 判断本轮推进能否放行
3. `Rewrite` 后需要 `Review` 做复检
4. 没有 `Review`，workflow 之间就没有统一的转向标准

### 影响范围

- `04_workflows/02_review_workflow.md`
- 其余 workflow 的出口设计

### 风险 / 待验证项

- 后续仍需通过连续运行样例验证：`Review` 作为中枢是否会让流程过重

### 后续动作

`watch`

---

## 5. DEC-20260326-18

### 决策标题

`Continue` 后必须立即 `Review`，不允许连续跳过审查多轮推进

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

一个自然诱惑是：为了提高推进速度，是否允许连续生成多个 `PlotUnit` 后再统一审查。

### 备选方案

- 方案 A：可先连续推进多轮，再批量审查
- 方案 B：每轮关键续写后都应立即审查

### 最终选择

采用方案 B。

### 选择理由

1. 当前阶段优先验证的是稳定运行，而不是吞吐量
2. 连续跳过审查会放大角色漂移、信息越界、承诺遗失和世界失效
3. 早发现比晚返工更符合本项目的 review-first 方向

### 影响范围

- `04_workflows/03_continue_workflow.md`
- `04_workflows/02_review_workflow.md`
- `06_experiments/`

### 风险 / 待验证项

- 未来进入实现阶段后，可能要区分“轻审查 / 重审查”

### 后续动作

`watch`

---

## 6. DEC-20260326-19

### 决策标题

`Rewrite` 必须由正式问题对象驱动，而不是由“感觉不好”直接触发

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

改写最容易失控的原因，就是没有明确问题入口，只凭主观感受进入修补。

### 备选方案

- 方案 A：只要觉得不够好，就直接进入 `Rewrite`
- 方案 B：正式 `Rewrite` 必须由 `ReviewIssue` 或等价正式问题对象驱动

### 最终选择

采用方案 B。

### 选择理由

1. 没有问题对象，改写范围会快速膨胀
2. `Rewrite` 的价值在于“最小修复”，前提是先知道到底坏在哪里
3. 否则系统会把局部问题改成全局污染

### 影响范围

- `04_workflows/04_rewrite_workflow.md`
- `04_workflows/02_review_workflow.md`

### 风险 / 待验证项

- 轻量语言润色是否需要完整 issue 驱动，后续可再细分

### 后续动作

`keep`

---

## 7. DEC-20260326-20

### 决策标题

只有正式问题才进入 `Rewrite`，提醒与预警优先留在继续推进链中处理

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

很多审查结果并不是“当前单元已经失败”，而是“短期内必须补偿，否则会恶化”。

### 备选方案

- 方案 A：只要出现 warning，就立即进入 `Rewrite`
- 方案 B：warning 优先保留在推进链中处理，只有正式问题才进入 `Rewrite`

### 最终选择

采用方案 B。

### 选择理由

1. 不是所有 warning 都意味着当前单元失败
2. 很多近程后果更合理的处理方式是下一单元兑现，而不是回头改上一单元
3. 如果 warning 一律触发改写，系统会过度保守且停滞

### 影响范围

- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`

### 风险 / 待验证项

- 仍需实验确定：warning 保留多久应升级为正式问题

### 后续动作

`watch`

---

## 8. DEC-20260326-21

### 决策标题

当多个 `ReviewIssue` 指向同一结构失衡时，应升级为 `Replan`，而不是反复局部 `Rewrite`

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

有些问题不是某一个 `PlotUnit` 坏了，而是整段结构方向已经偏了。

### 备选方案

- 方案 A：尽量都用局部 `Rewrite` 修补
- 方案 B：当问题已上升到段落 / arc 层时，升级为 `Replan`

### 最终选择

采用方案 B。

### 选择理由

1. 局部问题适合改写
2. 结构问题适合重排
3. 如果用局部补丁修结构错误，只会不断制造新 issue

### 当前升级信号

- 多个 issue 指向同一承诺线程停滞
- 多个 issue 指向同一关系线节奏失衡
- 支线长期遮蔽主线
- 连续多个 `PlotUnit` 建立在错误局势假设上

### 影响范围

- `04_workflows/04_rewrite_workflow.md`
- 后续可能新增的 `replan` 文档或动作层

### 风险 / 待验证项

- `Rewrite` 与 `Replan` 的切换阈值仍需更多实验压实

### 后续动作

`patch`

---

## 9. DEC-20260326-22

### 决策标题

当前不把“正文生成”独立成第一优先 workflow

### 决策类型

`project`

### 决策状态

`adopted`

### 背景问题

从产品直觉上，最像系统能力的是正文生成。但在当前阶段，它不应压过对象层与审查闭环。

### 备选方案

- 方案 A：尽快定义正文生成 workflow
- 方案 B：先把 `Rebuild / Continue / Review / Rewrite` 跑稳，再考虑表达层 workflow

### 最终选择

采用方案 B。

### 选择理由

1. 当前真正难的是对象、约束、连续性和修复闭环
2. 正文生成属于表达层，不是当前地基层的核心瓶颈
3. 没有稳定对象层与审查闭环，正文 workflow 只会制造“表面可读、结构不稳”的文本

### 影响范围

- 当前项目边界
- workflow 层优先级安排

### 风险 / 待验证项

- 未来进入实现阶段后，需要专门补一层“对象层 -> 文本层”的 workflow

### 后续动作

`defer`

---

## 10. DEC-20260326-23

### 决策标题

当前 workflow 先服务 mock case，后服务通用化输入

### 决策类型

`example`

### 决策状态

`adopted`

### 背景问题

workflow 可以一开始就朝“泛化”写，也可以先围绕统一案例压实。

### 备选方案

- 方案 A：先写成很通用，但较抽象
- 方案 B：先围绕 mock case 验证，再从案例中提炼通用模式

### 最终选择

采用方案 B。

### 选择理由

1. 真实案例最容易暴露 workflow 断点
2. 抽象流程图很容易“看起来都对”，但落地时缺输入、缺状态、缺回写
3. mock case 已经统一世界、角色、状态与主线，最适合作为第一轮压力测试

### 影响范围

- `05_examples/`
- `06_experiments/`
- `04_workflows/`

### 风险 / 待验证项

- 后续仍需验证：当前 workflow 是否过度贴合既有题材

### 后续动作

`watch`

---

## 11. DEC-20260326-24

### 决策标题

`Continue` 内部对象写回顺序固定为：`PlotUnit -> NarrativeState -> FactLedger -> ForeshadowGraph -> CharacterModel -> Review`

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

续写工作流不仅要决定“下一步写什么”，还要决定“写完后先把变化写回哪一层”。如果没有固定写回顺序，就会出现：

- 账本先改了，但状态还没变
- 角色知识先改了，但硬事实还没成立
- 承诺线程先推进了，但事件本身还没被定义
- 审查时读到的是半同步状态

### 备选方案

- 方案 A：谁先想到就先更新谁
- 方案 B：为 `Continue` 固定对象写回顺序

### 最终选择

采用方案 B，顺序固定为：

1. `PlotUnit`
2. `NarrativeState`
3. `FactLedger`
4. `ForeshadowGraph`
5. `CharacterModel`
6. `Review`

### 选择理由

1. `PlotUnit` 是本轮变化的因果源头，必须先成立
2. `NarrativeState` 记录的是这次推进之后的即时运行态，应直接承接 `PlotUnit`
3. `FactLedger` 只记录已经成立并约束后文的硬事实，因此应在输出状态明确后再写
4. `ForeshadowGraph` 记录的是本轮事件对承诺线程的影响，依赖事件与事实层都已明确
5. `CharacterModel` 的运行态与可成长字段更新，应该建立在本轮状态变化和事实变化已经落定之后
6. `Review` 必须读取的是一次完整同步后的对象集，而不是半成品

### 详细写回规则

#### 11.1 `PlotUnit`

先确认：

- 本轮目标
- 关键决策
- 冲突与约束
- `state_change_summary`

如果这一步不成立，后续对象都不应写回。

#### 11.2 `NarrativeState`

随后写出：

- 当前时间 / 地点
- 在场角色
- 主目标
- 当前冲突
- 当前信息分布
- 当前开放问题
- 当前活跃承诺压力

它回答的是：“事件发生之后，现在的局面是什么。”

#### 11.3 `FactLedger`

只写入已经成立的硬约束，例如：

- 资源归属变化
- 关键事件已发生
- 某角色已知某事实
- 某制度后果已启动
- 某关系事实已正式成立

不把纯推断和临时情绪写入账本。

#### 11.4 `ForeshadowGraph`

只记录本轮对承诺线程的影响，例如：

- 新承诺建立
- 旧承诺推进
- 假线索建立或失效
- 部分回收
- 回收窗口逼近

#### 11.5 `CharacterModel`

仅更新允许成长或允许运行态化的字段，例如：

- `short_term_goal`
- `knowledge_state`
- `misinformation`
- `available_resources`
- `relations`
- `arc_stage`
- `self_image`

不在这里无理由改写角色核心定义。

#### 11.6 `Review`

只有在上述对象已经完成同步后，才进入正式审查。

### 影响范围

- `04_workflows/03_continue_workflow.md`
- `02_data_models/09_field_rules.md`
- `03_rules/05_information_release_rules.md`
- `03_rules/06_foreshadow_rules.md`

### 风险 / 待验证项

- `CharacterModel.knowledge_state` 与 `FactLedger.known_by` 的主从关系仍需继续压实
- relation 信息何时进入 `FactLedger` 仍需更多样例校准

### 后续动作

`patch`

---

## 12. DEC-20260326-25

### 决策标题

`Rewrite` 必须先修根因对象，再按依赖顺序联动同步，而不是多对象并行乱改

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

改写时最容易出现的问题，不是“改不动”，而是“同时改太多层，最后谁也说不清谁是根因、谁是联动修复”。

### 备选方案

- 方案 A：看到相关对象都不对，就并行一起改
- 方案 B：先锁定主根因对象，再按依赖顺序同步其余对象

### 最终选择

采用方案 B。

### 选择理由

1. `Rewrite` 的目标是最小修复，不是大范围重写
2. 先锁定主根因对象，才能控制污染范围
3. 同步顺序固定后，复检和追责都会更清晰

### 根因优先规则

先判断问题主根因位于哪一层：

- `PlotUnit`
- `NarrativeState`
- `FactLedger`
- `ForeshadowGraph`
- `CharacterModel`
- `arc / plan`

然后先修主根因对象，再同步依赖对象。

### 联动顺序规则

#### 12.1 若主根因在 `PlotUnit`

按以下顺序联动：

1. 改 `PlotUnit`
2. 同步 `NarrativeState`
3. 同步 `FactLedger`
4. 同步 `ForeshadowGraph`
5. 必要时同步 `CharacterModel`
6. 进入 `Review`

#### 12.2 若主根因在 `NarrativeState`

按以下顺序联动：

1. 改 `NarrativeState`
2. 检查前后相关 `PlotUnit` 的输入 / 输出引用
3. 同步 `FactLedger`
4. 同步 `ForeshadowGraph`
5. 必要时同步 `CharacterModel`
6. 进入 `Review`

#### 12.2.a bounded runtime-first exception 只允许局部起步，不允许跨轮拖延

若主根因在 `PlotUnit` / `NarrativeState`，且 `FactLedger` 本身不是根因，则允许 rewrite 从运行态局部修复起步。

但该例外只允许：

- 作为同一 repair packet 的起点

不允许：

- 跨 handoff 再补 `FactLedger`
- 先 `Review` 后补 `FactLedger`
- 先改 `CharacterModel` 摘要再等待事实层追认

只要本轮 rewrite 已明确某条新硬事实成立，就必须在进入 `Review` 前完成 `FactLedger` 同轮写回。

#### 12.3 若主根因在 `FactLedger`

按以下顺序联动：

1. 改 `FactLedger`
2. 同步 `NarrativeState` 中对应的信息分布或局势约束
3. 同步 `CharacterModel.knowledge_state`
4. 如该事实影响承诺线程，再同步 `ForeshadowGraph`
5. 进入 `Review`

#### 12.4 若主根因在 `ForeshadowGraph`

按以下顺序联动：

1. 改 `ForeshadowGraph`
2. 同步 `NarrativeState.open_questions / active_promises`
3. 检查相关 `PlotUnit` 的推进标记是否还成立
4. 必要时同步 `ReviewIssue`
5. 进入 `Review`

#### 12.5 若主根因在 `CharacterModel`

按以下顺序联动：

1. 改 `CharacterModel`
2. 同步当前 `NarrativeState`
3. 检查相关 `PlotUnit` 的动机与决策是否仍成立
4. 必要时同步 `FactLedger` 与 `ForeshadowGraph`
5. 进入 `Review`

#### 12.6 若主根因已上升到 `arc / plan`

不继续扩大 `Rewrite`，应升级到：

- `Replan`

### 影响范围

- `04_workflows/04_rewrite_workflow.md`
- `04_workflows/02_review_workflow.md`
- `02_data_models/09_field_rules.md`

### 风险 / 待验证项

- 某些复合问题可能跨多个根因层，后续仍需实验验证“主根因”判定稳定性
- bounded runtime-first exception 虽已被负例样例进一步收紧，但仍需更多 mixed-chain counterexample 验证不会在更长 handoff 链里回弹成默认顺序

### 后续动作

`patch`

---

## 13. DEC-20260326-26

### 决策标题

当对象记录冲突时，当前按“主存对象优先、运行态次之、审查结果只负责分流”的优先级处理

### 决策类型

`workflow`

### 决策状态

`adopted`

### 背景问题

当前系统刻意采用多对象分层，所以冲突并不是“会不会出现”，而是“出现时按什么优先级裁决”。

### 备选方案

- 方案 A：谁最后更新就信谁
- 方案 B：预先固定冲突裁决优先级

### 最终选择

采用方案 B。

### 总体裁决原则

#### 13.1 项目级与世界级硬约束优先

当 `WorkSpec`、`WorldModel` 与运行对象冲突时：

- 以 `WorkSpec` / `WorldModel` 为准

因为它们定义的是顶层方向与世界合法性，不应由运行态反向覆盖。

#### 13.2 已成立硬事实优先于角色视角与局势推断

当 `FactLedger` 与 `NarrativeState` / `CharacterModel` 冲突时：

- 关于“世界中是否已成立”这类问题，以 `FactLedger` 为准

例如：

- 某资源是否已易主
- 某事实是否已公开
- 某制度后果是否已启动

#### 13.3 角色结构优先于场景瞬时状态

当 `CharacterModel` 与 `NarrativeState` 冲突时：

- 关于长期角色结构，以 `CharacterModel` 为准
- 关于当前场景运行态，以 `NarrativeState` 为准

也就是：

- “这个人本质上是谁”看 `CharacterModel`
- “他此刻处于什么局、短期目标是什么”看 `NarrativeState`

#### 13.4 承诺线程状态优先于开放问题列表

当 `ForeshadowGraph` 与 `NarrativeState.open_questions / active_promises` 冲突时：

- 关于承诺线程是否已建立、推进、回收，以 `ForeshadowGraph` 为准
- `NarrativeState` 只保留当前局面中的活跃表现

#### 13.5 `PlotUnit` 只裁定本轮变化，不单独覆盖长期对象

当 `PlotUnit.state_change_summary` 与长期对象冲突时：

- 先检查它是否已经被正确写回
- 如果尚未写回，不能直接用 `PlotUnit` 覆盖长期对象
- 如果已经写回，则应以主存对象为准，而不是继续把 `PlotUnit` 当长期记录层

#### 13.6 `ReviewIssue` 只负责分流，不负责定义事实本体

`ReviewIssue` 可以决定：

- 是否进入 `Rewrite`
- 是否升级到 `Replan`
- 哪条规则被违反

但不能单独充当：

- 事实来源
- 状态来源
- 承诺来源

### 影响范围

- `02_data_models/09_field_rules.md`
- `04_workflows/02_review_workflow.md`
- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`

### 风险 / 待验证项

- `knowledge_state` 与 `known_by` 的最终主存位置仍需继续收束
- 关系事实与关系运行态的裁决边界仍需更多实验校准

### 后续动作

`re-evaluate`

---

## 14. 当前推荐的总分流图

基于以上决策，当前建议的总分流关系如下：

```text
输入材料
  -> 当前状态是否清楚？
     -> 否：Rebuild
          -> Review
          -> 可进入 Continue / 需补重建
     -> 是：Continue
          -> Review
          -> 通过：进入下一轮 Continue
          -> 警告：带约束 Continue
          -> 正式问题：Rewrite
               -> Review 复检
               -> 通过：Continue
               -> 仍失败：Replan
          -> 结构失衡：Replan
```

---

## 15. 当前不建议打破的顺序约束

以下顺序当前视为高优先级约束：

1. 状态不清时，不能直接 `Continue`
2. `Continue` 后，不能跳过 `Review`
3. `Rewrite` 前，必须先有正式问题对象
4. `Rewrite` 后，必须复检
5. 多个 issue 指向结构问题时，不应继续局部补丁
6. `Continue` 的对象写回必须按固定顺序执行
7. `Rewrite` 必须先修主根因对象，再联动同步

---

## 16. 当前最值得继续验证的流程问题

虽然主顺序已经基本固定，但以下问题仍需实验验证：

### 16.1 Warning 到正式 Issue 的阈值

需要实验回答：多少轮未补偿应升级。

### 16.2 `Rewrite` 到 `Replan` 的切换阈值

需要实验回答：多大范围的问题仍算局部，什么时候必须上升到 arc 层。

### 16.3 Rebuild 的粒度

需要实验回答：是否存在“轻量 rebuild”足以启动 `Continue` 的场景。

### 16.4 知识与关系的联动顺序是否稳定

需要实验回答：

- `FactLedger.known_by`
- `CharacterModel.knowledge_state`
- `NarrativeState.private_information_map`

以及：

- `CharacterModel.relations`
- `NarrativeState.active_relation_tensions`
- `FactLedger relation`

在多轮继续推进与链式改写下，当前顺序是否真的足够稳定。

---

## 17. 后续动作建议

这个文件补完后，下一步最自然的是继续补强：

- `04_workflows/03_continue_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `02_data_models/09_field_rules.md`

重点不是再发明新对象，而是把以下内容收紧到一致：

- 写回顺序
- 主存对象
- 冲突裁决优先级
- `warning -> issue -> rewrite -> replan` 的升级条件

---

## 18. 一句话总结

`03_workflow_order_decisions.md` 的作用，是把这套系统里“先做什么、后做什么、什么时候转向、对象按什么顺序写回、冲突时以谁为准”的关键流程秩序固定下来，避免 workflow 变成谁都能随时跳进跳出、但没有统一分流标准和同步规则的流程泥团。
