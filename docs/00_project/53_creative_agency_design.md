# 53. 观点记录：创作 agency 设计校准（NOEMA: The Nature of Free Will in the Age of AI）

状态：研究观点（2026-08-23 记录；2026-08-23 三机制已实现为独立研究轨代码包）。本文不提供具体算法，
只把文章的设计原则映射到本项目现状，并给出一套可测试的 agency 验收标准。

来源：NOEMA — [The Nature Of Free Will In The Age Of AI](https://www.noemamag.com/the-nature-of-free-will-in-the-age-of-ai/)

## 0. 一句话校准

> 不要试图让 AI 拥有更多"好小说规则"；要让创作选择越来越成为这个系统自己的因果结果。

项目的目标因此从"模拟一个优秀作者的输出"进一步推向**"构造一个能够成为创作决策因果节点的系统"**。

## 1. 文章核心观点（转写为设计语言）

### 1.1 主体性 ≠ "没有外部原因"

主体性不是"无外部原因的自由"，而是：

```text
外部信息
+ 自身历史
+ 内部状态
+ 反思
+ 未来模拟
        ↓
这个系统成为真正的决策节点
```

William James 两阶段结构：**先产生可能性 → 再理性选择**。

### 1.2 关键引语（Kevin Mitchell）

> 生物体根据自身结构与历史赋予信息意义。
> information whose meaning is internal to their structure and history.

**同一个信息，因为不同历史，必须产生不同选择。** 这不是"记忆更多信息"，这是"意义的作品内部性"。

### 1.3 先验 ≠ 主体

遗传/过去经历/环境/教育影响主体，但**不等于当前行动者本身**。
映射到本项目：AuthorModel 是**先验**，不能直接"决定下一步怎么写"；它必须经当前作品历史、
当前情境、反思/rollout 之后才进入最终选择。

### 1.4 Frankfurt 二阶欲望 → 创作层的 reflective endorsement

一阶：我能不能这么写（LLM 默认套路）。
二阶：我是否认可自己这么写（是否掉进默认吸引子 / 人物是否会这么做 / 是否破坏既有变化 / 是否有更属于这本书的答案）。

## 2. 与项目现状的映射（已存在骨架）

| 文章阶段 | 项目现有机制 | 状态 |
|---|---|---|
| 产生可能性 | P3 Structural Search（多候选生成） | ✅ 已实现 |
| 评价候选 | Structural diversity gate + Pareto 多维前沿 | ✅ 已实现 |
| 模拟后果 | 3–5 章状态级 Rollout（`StructuralSearchEngine(rollout_steps)`） | ✅ 已实现 |
| 选择前冻结依据 | Candidate Precommit | ✅ 已实现 |
| 选择 | Pareto + Selection（含 Manual/Pareto/tie-break） | ✅ 已实现 |
| 承担后果 | ChoiceLedger 记录 → Hindsight 回填真实后果 | ✅ 已实现 |
| 经验更新 | Hindsight → AuthorModelV3/AuthorKernel 原则更新 | ✅ 已实现 |
| 分叉对照 | Shadow（A/B 分叉，B 后来是否更好） | ✅ 已实现 |
| 结构近重复检测 | `diversity_report.near_duplicates`（防伪装多样性） | ✅ 已实现 |

项目已经拥有文章的**完整骨架**。文章的价值不是新增机制，而是**确认这条链就是创作的核心**，
并指出当前架构中"节点"与"装饰"的区分标准。

## 3. 校准后应调整的设计重点

### 3.1 目标定义：Structural Search + Selection 优先于 Prose Generation

- ✅ 已在 P3 明确：正文生成边界 = 只对最终保留的少量候选生成正文；正文不得改核心选择。
- 校准确认：**搜索与选择是创作核心，正文生成是外围执行**。

### 3.2 Work Experience / Meaning View：作品自身历史是因果节点，不是记忆

项目新设计方向（与文章 §1.2 直接对应）：

```text
同一个"朋友背叛"：
普通 LLM → 按小说规律 → 背叛制造冲突
作品级   → 本书过去 70 章信任史 + 主角因此改变 + 上次类似选择的后果
         → 这一次背叛对"这本书"意味着什么 → 再选择
```

- **Experience Ledger / Meaning View 的目的不是"记更多"，而是"让相同信息因不同历史产生不同选择"**。
- 验收锚（P2 Orchestrator 已有同构先例）："事实状态相同但编排历史不同 → 优先级不同"。

### 3.3 AuthorModel 放回先验位置（闭环外侧）

- ✅ P5 已规定：先以 shadow / candidate prior / tie-break 接入，跨作品证据不足前不成硬门禁。
- 校准确认：Author Prior 影响系统，但不等于系统；当前作品历史必须在作者先验与最终选择之间。

### 3.4 Reflective Override（二阶欲望）对应 Default Attractor Detection

- 一阶：这段最自然怎么写（默认套路）。
- 二阶：系统再问"我是否认可这个最容易的答案"——掉进默认吸引子 / 破坏人物变化 / 连续同类冲突。
- 项目现状：结构近重复检测（候选层）已存在；**选择层的 reflective endorsement 尚待实现**（见 §5 缺口）。

## 4. 五个可测试的 agency 验收标准（工程化定义）

不问"AI 有没有意识/情感"，只问五件可实验的事：

| # | 标准 | 可测试实验 | 对应机制 |
|---|---|---|---|
| ① | **Historical Dependence** 历史依赖 | 过去不同（作品历史/角色变化），当前选择是否不同 | Work Experience / State 历史 |
| ② | **Reason Responsiveness** 理由响应 | 改变理由（情境/目标/约束），选择是否合理改变 | Candidate rationale / situation |
| ③ | **Reflective Override** 反思否决 | 第一反应很强时，系统能否拒绝它 | Default Attractor Detection / 二阶欲望 |
| ④ | **Counterfactual Deliberation** 反事实推演 | 能否比较多个未来，而不是生成一个再解释 | P3 Rollout + Pareto |
| ⑤ | **Experience Plasticity** 经验可塑性 | 一次选择的真实后果，能否改变以后类似情境的选择 | ChoiceLedger → Hindsight → AuthorModel 更新 |

**验收阈值**：五条都没有 → 再复杂的系统也只是"高级文本生成器"；
逐渐具备 → 功能意义上正在形成创作 agency。

## 5. 关键缺口与终极消融实验

### 5.1 缺口清单（现状 vs 文章标准）

| 缺口 | 说明 | 建议 |
|---|---|---|
| Reflective Override 未实现 | 结构近重复在候选层检测，但"这一章是否认可这个选择"的二阶检查未成机制 | 在 Selection 前加二阶 check（默认吸引子 / 人物忠实 / 既有变化破坏 / 连续同类） |
| Work Experience 未成因果节点 | 当前有 ChoiceLedger + 状态历史，但"同一信息因不同历史产生不同选择"未做对照验证 | Experience Ablation 实验（见下） |
| Causal node 验证缺失 | 未验证"删掉作品自身历史后决策是否还一样" | Experience Ablation |

### 5.2 终极消融实验：Experience Ablation

```text
A：当前状态 + 100 章作品经验
B：当前状态完全相同 + 无作品经验

若 A≈B（长期选择几乎一样）→ Work Experience / Meaning / Identity 都不是因果节点，只是 prompt 装饰。
若 A≠B（相同事实 + 不同历史 → 不同但都合理的未来），且人类长期盲评 A 更好
→ 作品历史真正进入创作因果链。这是最强的 agency 证据。
```

### 5.3 文章不能给项目什么（边界）

- 没有证明 agency = 会写出大神小说。
- 没有给出 Meaning Graph / Experience 编码 / Taste 训练 / Hindsight 回看频率 / Rollout 层数的具体方案。
- 没有证明系统有意识。
- 它给的是**设计原则**，不是**技术方案**。

## 6. 结论：项目最终形态

```text
生成模型     → 我可以写什么
Structural Search → 我有哪些未来
Author Prior → 过去的作者通常怎样选择
Work Experience → 这本作品经历过什么
Reflection/Taste → 我是否认可最容易的答案
Rollout      → 不同选择可能造成什么
Selection    → 所以这一次我为什么偏偏选它
Hindsight    → 事实证明这次选择对不对
Experience Update → 这件事以后会怎样改变我
```

**文章最大价值：把项目从"模拟一个优秀作者的输出"推向"构造一个能够成为创作决策因果节点的系统"。**
当前项目已具备链条骨架（P3/P5/Hindsight/Shadow 全部在架），下一步优先级 = Work Experience 因果节点化 + Reflective Override 二阶机制 + Experience Ablation 消融验证。

## 7. 已实现：独立研究轨三机制（2026-08-23）

三项缺口已实现为独立研究轨代码包（纯标准库、不注入生产依赖、不新增 pytest 文件保持合同锁 3018）：

| 机制 | 代码 | 验证 |
|---|---|---|
| Work Experience 因果节点化 | `src/research_agency/experience_ledger.py`（ExperienceLedger 主题索引 + MeaningView） | `--selftest` exit 0：同 plot_context + 不同历史 → 不同且非空 MeaningView |
| Reflective Override（二阶欲望） | `src/research_agency/reflective_override.py`（DefaultAttractorDetector 连续≥3 检测 + endorse/override 裁决） | `--selftest` exit 0：默认吸引子候选 override，非常规候选 endorse |
| Experience Ablation | `src/research_agency/experience_ablation.py`（run_ablation A/B 分叉 + AblationReport 判定） | `--selftest` exit 0：有经验 vs 无经验分叉>0 → `EXPERIENCE_IS_CAUSAL_NODE`；同历史重跑分叉=0 |
| 聚合验证 | `scripts/verify_creative_agency.py` | exit 0：3/3 selftests PASS |

研究结论（合成夹具层面）：三机制全部按设计意图工作——相同信息因不同历史产生不同意义视图；连续同类处理触发二阶否决；有/无经验产生确定性分叉且可复现。真实作品语料验证（Experience Ablation 在真实 ChoiceLedger 上运行）留作下一步，与生产强依赖隔离。
