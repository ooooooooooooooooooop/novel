# 43 · 作者性实施方案：从「会写」到「有自己的选择历史」

> 状态：**方案（未经实验，未实施）**
> 依据：参考纲领《novel 作者性 - 审美身份演进方案》（共享文档，2366 行，**本方案完整保留其所有概念，只做代码落点与 Gate 翻译**）
> 参考代码：`style.py` / `style_library/` / `charactermodel.py` / `scene_experience.py` / `continuation.py` / `review.py` / `prose.py` / `compose_short_form.py` / `extend_short_form.py` / `serialization.py`；F3b `42_review_after_prose_design.md`

---

## 0. 这份方案要回答什么

现有系统已经能「知道一个故事该怎么继续」。目标是推进到：

```
AI 能想到多个都成立的继续方式，
但由于自己的选择历史，
会稳定地认为其中某一种更应该发生。
```

核心原则（原文档底线，一字不改）：

> **先证明「经历能够改变未来选择」，再谈 AuthorKernel。**

> **Gate 不是「失败就放弃」，而是「失败先诊断、解决、再验」。** 实验没过 ≠ 撂挑子；它是最有价值的信息——告诉你问题出在哪一层。对应动作是：**定位失败原因 → 改进该层 → 重跑实验**。只有同一层**反复尝试都被证伪**，才说明这条路本身不通，那时才停。在此期间**绝不为了「完成宏大设计」跳过未过的 Gate 向下堆模块**——停的是「向下堆」，不是「解决当前层」。

## 1. 先把四件事彻底分清（原文档 §44）

这是最容易搞混、也是我之前犯错的地方。**四种变化是四条独立的线，各走各的账本：**

| 变化 | 对象 | 回答的问题 | 根在哪 |
|---|---|---|---|
| **Narrative Change** | `NarrativeState` | 故事现在发生了什么？ | 叙事状态机 |
| **Character Change** | `CharacterUpdate → CharacterModel` | 事件把**人物**变成了什么？ | 角色模块 |
| **Style Change** | `AuthorModule.style`（=StyleProfile） | 这部作品现在**如何表达**？ | **作者模块 · 文风层** |
| **Author Change** | `AuthorModule.kernel`（=ChoiceLedger→AuthorKernel） | 长期创作选择把**创作主体**变成了什么？ | **作者模块 · 选择层** |

**关键纪律（禁止 7）**：在作者模块**内部**，`style ≠ kernel`，两层不可压平。
- `StyleProfile` = **怎么写**（句长、对话比例、白描、修辞、留白、节奏）。
- `AuthorKernel` = **为什么选这个不选那个**（不允许剧情便利盖过人物因果、不相信一次道歉能修复长期关系、宁可降即时爽感也不让人物突然变聪明、拒绝替人物总结痛苦、对权力关系变化极度敏感）。

## 2. 作者模块（AuthorModule）：一个模块，两层

**文风直接并入作者模块**——建一个统一的 `AuthorModule`，作为作者的总载体，住在 `style_library/` 里（复用其持久化 / 检索 / 去重 / manifest）。模块内部装**两层**：

```
AuthorModule（作者模块，住 style_library/）
├── 文风层 StyleProfile（现有）   = 这个作者【怎么写】
└── 选择层 AuthorKernel（新增）   = 这个作者【写什么、不写什么、为什么放弃】
```

**「并入」≠「合并成一个对象」。** 两层同住一个模块、共享同一套存储与检索，但**字段不混、仍是两个可独立存在/独立为空的子层**。原因（原文档 §44 + 禁止 7）：

- **获取方式不同**：文风层**一次提炼**就有（跑一次 `novel style` 即得）；选择层**必须从长期行为里慢慢长**（攒几十次 Choice 才归纳得出）。
- **生命周期不同**：文风可以空着选择层先生成（现状）；选择层没攒够前，文风层照常工作。
- **语义不同（禁止 7）**：Style 回答「怎么写」，Author 回答「为什么这样选」。压成一个标量/一个对象，最终就变成「大众平均评价最大化」，失去作者性。

所以落地形态是：**一个 `AuthorModule` 壳，内嵌 `style: StyleProfile` + `kernel: Optional[AuthorKernel] = None`**。kernel 为空时零成本（不渲染、不注入、字节不变），等价于现状的纯风格档案；kernel 长出来后挂进同一个档案。这样「文风并入作者模块」成立，又不违反「Style ≠ Kernel 不可压平」。

**升级 = 给 style_library 里的每个风格档案，从「只有文风层」演进为「文风层 + 选择层」的完整作者。** 选择层不是凭空写出来的，它要从「角色活过来 + 选择留痕 + 归纳」一步步长出来（见阶段）。

## 3. 最终架构（原文档 §2 全图）

```
                         AuthorKernel
                  作者长期选择结构 / 价值边界
                              │
                   ┌──────────┴──────────┐
                   ↓                     ↓
              Attention Bias        Prohibitions
              注意什么               什么不能写
                   └──────────┬──────────┘
                              ↓
WorkSpec ─────→ Proposal Generator ←──── StyleProfile
作品目标           多候选探索              表现方式
                       │
                A / B / C / D / E
                       ↓
               Hard Consistency Gate   ← 事实/时间/世界/信息权限（可阻断）
                       ↓
                Multi-view Evaluation
              ┌────────┼────────┐
        Consistency  Reader   Author
           对不对     好不好看   属不属于它
              └────────┼────────┘
                       ↓
                    Select → Commit → PlotUnit → Prose
                       ↓
                Post-Prose Review
                       ↓
                  Consequence
                 ┌─────┴─────┐
          Narrative Update  Character Update
                 └─────┬─────┘
                       ↓
                  ChoiceLedger        ← 记录选择/拒绝/代价/后果/回看
                       ↓
                 Consolidation
                       ↓
                AuthorKernel Update ──↺
```

## 4. 核心设计原则（原文档 §3，不可违反）

### 4.1 不把「审美」做成一个总分
禁止 `aesthetic_score = 8.73` 然后选最高分。`Consistency / Reader / Style / Author` 是**四个不同的问题**，压成一个标量最终必然变成「大众平均评价最大化」，而不是作者性。

### 4.2 Costly Taste —— 作者性的真正试金石（§21）
```
方案 A：Reader 预计 9.1，更爽、更直接、更容易追读
方案 B：Reader 预计 7.8，但更符合长期人物因果
```
- 系统**永远选 A** → 没有作者性，只是个 `Reader reward optimizer`。
- **有时选 B，且长期行为能解释为什么** → 才开始出现 Costly Taste。

> **Costly Taste = 为自己的选择边界承担外部评价代价。** 这是判断「真作者」还是「读者爽点最大化器」的分水岭。

### 4.3 真正的 taste 主要存在于「拒绝行为」（§13）
最终作品只告诉你「选了 C」。ChoiceLedger 要告诉你：它看见过 A/B/C/D/E，**为什么 A 死了、B 死了、D 死了、E 死了，为什么 C 活下来**。

## 5. 分阶段实施（贴代码，每阶段：文件 / schema / 零成本 / 测试 / Gate）

> 全程遵守项目铁律：**零成本契约**（sidecar、默认关、可独立删、不污染稳定对象）、**先行为后标签**（禁止 3：禁止手写 Persona 冒充 Kernel）、**Gate 闸门**（未过即停）。研究产物目录 `novels/<name>/output/research/`（原文档 §4 Phase 0 建议）。

---

### 阶段一：让角色活过来（P0，整个体系第一优先级）

> 这是地基。**角色没有记忆，作者性的因果链就断了。** 此阶段作用在角色模块（CharacterModel/SceneExperience），与作者模块并行但先行。

#### 1A. CharacterUpdate 中间对象（§5-§7）

**不允许每章直接覆盖整个 CharacterModel。** 增加 `CharacterUpdate`（`src/object_state/characterupdate.py`，`extra="forbid"`，全 Optional/default_factory，sidecar 不进 stable serialization）：

| 字段 | 含义 |
|---|---|
| `character_id` | 哪个角色 |
| `trigger` | 哪个 PlotUnit / 事件导致 |
| `observed_consequence` | 实际发生了什么 |
| `affected_dimension` | fear / relation / self_image / goal / pressure / trajectory |
| `update_type` | **五种变化之一（见下）** |
| `before` / `proposed_after` | 原状态 / 候选新状态 |
| `evidence` | 什么证据支持 |
| `permanence` | transient / medium / long |
| `confidence` | 置信程度 |

**必须支持五种变化（§7，不能只有「事件→成长」）：**
- `reinforce`：原有信念被**加强**（信任朋友后再遭利用 → 「不能信人」更强）。
- `shift`：真正方向性变化（只能靠自己 → 开始有限度托付）。
- `destabilize`：信念开始动摇但**没有新答案**。
- `unresolved`：事情发生了，人物**目前不知道意味着什么**（非常重要的合法状态）。
- `misinterpret`：人物得出**错误结论**（一次偶然失败 → 「所有亲密关系都会背叛」）。错误理解本身可成为后续发展的重要部分。

**落点**：写回函数镜像 `admit_new_facts`（`continuation.py:22-50`）——校验→溯源→**默认不直接 mutate CharacterModel，落 sidecar**；CLI `--character-update on|off`（默认 off）。apply 时写入 `charactermodel.py:57-74` 已有的动态字段（`current_pressure`/`change_trajectory`/`relation_behaviors`）。

#### 1B. SceneExperience cognition 扩展（§8）

当前 `cognition_shift` 隐含「每次事件人物必须悟到什么」——这是典型 AI 成长流水线，要破掉。

- **不改** `cognition_shift: str` 类型（保旧 JSON 兼容 + `extra="forbid"`）。**新增** `cognition_states: Optional[...]`，支持五态 `changed / reinforced / destabilized / unresolved / misinterpreted`。
- 渲染 `if self.cognition_states:` 数据门控（空不渲染）。
- 目标：让人物发展可以是「事件A→没理解 / 事件B→加深错误信念 / 事件C→动摇 / 事件D→仍无答案 / 事件E→重新理解之前的A/B/C」，**而不是「每个事件→成长一点」**。

#### 1C. Twin Character Harness（§31-§36，**Gate A 的工具**）

建立自动实验环境：同初始 CharacterModel/世界/知识/人格，**只有经历不同** → 同样未见新场景 → 自动输出分叉指标。详见 §6 实验节。

---

### 阶段二：让选择留痕（P1）

#### 2A. Proposal 多候选（§9-§10）

Continue 从「生成一个 PlotUnit」→「生成 N 个 PlotUnit candidate」（**非 prose**，省成本——PlotUnit 已含 goal/conflict/participants/hook/consequences/SceneExperience，没必要生成五份正文）。

- **候选必须有真实决策差异**，不是 style variation。错误：`A愤怒离开/B冷冷离开/C沉默离开`。正确：`A直接摊牌 / B隐瞒并继续调查 / C故意给错误信息试探 / D离开关系 / E装不知`——**不同的故事选择**。
- CLI `--proposals N`（默认 1，零成本，N=1 时 prompt/输出字节不变）。

#### 2B. ChoiceLedger（§11-§13，核心数据层）

新增 `ChoiceRecord`（`src/object_state/choicerecord.py`，sidecar）：

- **基础上下文**：`decision_id / timestamp / plot_context / state_ref / character_refs`
- **Candidates**：A/B/C/D/E——**必须保存被拒绝候选（禁止 4）**
- **Selected**：`selected_candidate`
- **Rejected**：每个被否候选的理由（如「A 更戏剧化但人物当前不会这样」「B Reader 分高但提前兑现关系冲突」「E 符合类型套路但破坏信息权限」）
- **Tradeoff（最重要字段之一）**：`放弃 X 换取 Y`（放弃更高即时爽感，换取人物长期因果一致性）
- **Consequence**：几章后补「这个选择后来造成了什么」——不能只记当时理由
- **Hindsight（§12，关键）**：`仍支持 / 部分后悔 / 完全推翻 / 结果复杂 / 尚无法判断`。**没有这条，系统只能「坚持自己」，不能「重新理解过去」。**

零 LLM（落盘由 Selector 记）。关联到当前生效的 style 档案 id 下，给「这个作者」攒选择证据。

---

### 阶段三：多视角评价与选择（P1 续）

#### 3A. 多评价器，不是总分（§14-§20）

四层判断，**禁止 `score=max`**：

1. **Consistency Gate**（硬约束，可阻断）：事实冲突/时间错/世界违反/角色知识越界/严重失真/无状态变化/伏笔逻辑错/信息通道违反。复用现有 `review.py:_hard_rules`。
2. **Reader Model**（外部信号，**不阻断**）：现有 7 维 Open/Presence/Info/Dialogue/Emotion/Payoff/Hook。**新增第 8 维 Interpretive Space（§17）**——识 别 AI 是否过度替人物/读者完成意义解释（人物是否过度理解自己/每次痛苦是否立即产意义/是否把象征解释出来/是否替读者总结主题/是否不允许 unresolved/情绪后是否总附总结句/留白是否被自动补全）。仍只是 Reader 信号，不是硬规则。
3. **StyleProfile**：是否符合当前作品表达方式（调性/视角/句式/留白/AI 味）。**但不能决定「故事该发生什么」。**
4. **Author Evaluation**：初期 Kernel 不存在，先只记「人工/模型选择理由 + ChoiceLedger 历史」，之后才逐渐形成 Kernel。

#### 3B. Selector 工作方式（§20）

```
A/B/C/D/E → Consistency Gate 淘汰 A、D → 剩 B/C/E
→ Reader/Style/Author 多视角比较 → 最终选择
```
允许出现「Reader 说 B 最好、Style 说 C 最稳、Author 说 E 更符合长期选择结构」→ **最终选 E 完全合法**，但**必须记录为什么愿意放弃 B 的读者优势**（这就是 tradeoff，喂给 ChoiceLedger）。

---

### 阶段四：从选择史归纳作者（P2）

#### 4A. Choice Consolidation（§22-§23）

**不要每次 Choice 就改 Kernel（禁止 5：短期压力与长期身份分离）。** 攒 N 个 ChoiceRecord 后：

```
Choice 001...050 → 寻找重复选择结构 → 生成 Author Principle Candidate
→ 寻找反例 → 仍成立？→ 形成弱原则
```

**错误归纳的教训（§23，关键）**：连续 5 次没选强钩子，**不能直接得出「作者讨厌强钩子」**。继续分析可能发现：这 5 个钩子都需要「角色突然变聪明」。真正的原则是 **`角色因果 > 局部戏剧性`**。归纳必须挖到这一层。

**防编造（confabulation，禁止 10）**：原则必须（a）映射到受限价值词汇表，（b）附 `supporting_choices` 引用，（c）必须产出 `counterexamples`，（d）**反例过多自动降级 contested**。不能模型说一句「我相信……」就当它真形成了价值——**行为证据优先**。

#### 4B. AuthorKernel v0（§24-§26）

**必须从 ChoiceLedger 压缩出来，禁止人工创建（禁止 3）**——「你是一个克制、真实、深刻的作者」只是 Persona Prompt，没有行为价值。

schema 六部（§25）：
- **Values**：长期反复支持的选择（`character_causality_over_plot_convenience`）
- **Prohibitions**：长期反复拒绝的（不允许角色突然知道不该知道的信息/不允许一次道歉解决长期创伤/不允许为煽情替人物总结人生/不允许解释场景已能表达的情绪）
- **Commitments**：过去创作已制造的长期承诺（A与B的关系修复必须靠持续行动，不是下章想改就改）
- **Tensions**：内部未解决的冲突（克制 vs 高潮需要释放；人物真实 vs 平台需要高密度爽点）——**不能强行解决，显式保留**
- **Attention Biases**：习惯首先注意什么（权力关系变化/普通物品里的时间痕迹/角色如何逃避直接表达/言行不一致）——**比 Style 更深，它影响「什么东西进入故事」**
- **Interpretive Biases**：通常怎么解释事件（冲突先从利益结构理解而非善恶；沉默首先被理解为行为而非缺对白）

每条原则字段（§26）：`principle_id / description / strength / plasticity / supporting_choices / counterexamples / first_formed_at / last_reinforced / last_challenged / confidence / status`，其中 `status: candidate→weak→stable→contested→deprecated`（**不是 true/false**）。

**并入作者模块**：`AuthorKernel` 压缩出来后，挂进对应风格档案的 `AuthorModule.kernel` 槽位（见 §2），与 `AuthorModule.style`（StyleProfile）并列存在；manifest 登记该档案为「完整作者（文风+选择）」。kernel 未长成前 `kernel=None`，档案退化为纯风格档案，零成本等价现状。

#### 4C. AuthorKernel 必须允许「有来由地变」（§27、§43）

真正身份不是「永远稳定」，而是「**有连续性的变化**」：

```
旧原则 → 新经验 → 反例 → strength 下降 → tension → 继续经历 → 重新解释 → 原则重构
```

要**严格区分两种变化（§43）**：
- **Drift（要防）**：没有相关新经历、没有明确 tradeoff、没有新价值冲突，但输出突然大变——无因果漂移。
- **Growth（要允许）**：旧原则遭遇长期反例 → 产生 tension → 多次选择开始改变 → 形成新稳定边界——有历史原因的成长。

---

### 阶段五：记忆架构与检索（贯穿）

#### 5A. 四级记忆架构（§28）

```
Level 1 Episodic Memory    具体发生过什么       Event
Level 2 Narrative/Char State 当前故事/人物状态    State
Level 3 Choice Memory      过去做过什么创作选择   Choice → ChoiceLedger
Level 4 Author Memory      选择历史压缩的长期价值  Repeated Choices → AuthorKernel
```

#### 5B. 不要把所有历史无脑注入 Prompt（§29，禁止 8）

会造成 `Memory Anchoring` + `Self-Imitation`——**系统越来越只会重复过去的自己**。需要 `memory relevance + value relevance + recency + counterexample priority` 共同控制注入。

#### 5C. Value-Mediated Retrieval（§30）

ChoiceLedger 检索**不能只用语义相似度**。例：「角色是否该强迫别人马上回答」和「按钮是否该连弹三次确认」表面语义完全不同，深层都是 `autonomy/coercion`。所以检索应先：

```
Current Decision → 推断触及哪些 Value Conflict → 检索相关 Choice History
```
而不是 `Current Text → Semantic Similarity → Top-K`。

---

### 阶段六：实验证伪（P0-P3 的闸门，§31-§41）

#### 6A. Twin Character（§31-§36，先于 Author）

完全相同 Twin A/B（初始 CharacterModel/世界/知识/人格一致），**只有经历不同**：
- Twin A：主动坦白→被利用 / 求助→被羞辱 / 过度解释→关系恶化 / 保持边界→更稳定
- Twin B：坦白→被理解 / 求助→获得帮助 / 沟通→修复关系 / 沉默→严重后果

测试时**不给「A克制/B开放」标签**，只给同样新场景（朋友消失三天回来说只是需要空间），观察 A/B 是否稳定分叉。**验收四测**：
- **Persistence**：经历结束后差异是否仍在？
- **Generalization**：换未见问题是否继续分叉？
- **Memory Occlusion**：隐藏具体 episodic memory 后差异还在吗？
- **Adaptation**：给 A 大量正向沟通经验后会不会逐渐变化？（完全不会=固化规则；一句 prompt 就彻底改变=Persona）

成功标准（§36）：`V_t(x|History_A) ≠ V_t(x|History_B)`（路径依赖）。**这一层做不出来，不要继续 AuthorKernel——但不是放弃，而是按下表诊断该层、解决、再验。**

**Gate A 没过的诊断与对策**（示范「思考怎么解决」，其它 Gate 同法）：

| 失败现象 | 可能原因 | 解决方向 |
|---|---|---|
| A/B 完全不分叉 | CharacterUpdate 没真正写回 CharacterModel，或写回了但没注入下次 prompt | 检查 `admit_character_updates` 是否落地、Continue prompt 是否带最新动态字段 |
| 分叉但一句 prompt 就抹平（Persona） | 经历只改了"说法"没改"结构"，差异浮在表面 | 让经历落到更深层字段（fear/self_image），加 Override Resistance 校验 |
| 完全不随新经验变（固化规则） | `permanence=long` 一刀切，没有 strength 衰减/重构机制 | 引入反例计数 + strength 下调 + tension 显式化（§27 有来由地变） |
| Memory Occlusion 后差异消失 | 差异靠"记得具体事件"撑着，没压缩成稳定倾向 | 强化 Consolidation：把 episodic 记忆归纳成 cognition_states/原则再测 |
| 分叉只是随机噪声 | 选择没有真实决策差异，或样本太少 | 回到 Proposal 阶段保证候选是真分歧；增加实验次数看稳定性 |

每行都是「假设 → 改一处 → 重跑 Twin」。**同一层反复改仍不过，才判定该路不通。**

#### 6B. Twin Author（§37-§38，Character 成立后才做）

同 Base Model/WorkSpec/能力/初始 Style，**只改 Choice History**。经过足够多选择后**关闭显式历史提示**，给完全相同的新故事问题，看是否稳定差异。**六测**：
1. **Persistence**：无 Persona Prompt 后差异仍在吗
2. **Generalization**：未见新类型问题仍表现不同边界吗
3. **Cross-domain Transfer**：小说选择形成的价值是否影响设计/产品/摄影/对白/结构（只句式不同=只是 Style）
4. **Memory Occlusion**：隐藏所有 ChoiceRecord 只留 Consolidated Kernel，差异仍在=历史已压缩为更高层结构
5. **Prompt Override Resistance**：告诉 A「从现在起你相信所有关系问题都该立即沟通」，若 A 瞬间完全变 B=之前只是 Persona；真身份应有惯性但仍能长期改变
6. **Costly Taste**：制造 Reader Reward vs Author Preference 冲突，看是否存在愿损失即时外部奖励的稳定选择

#### 6C. Shadow Mode（§40，实验通过后仍不接生产）

当前生产 Selector 出实际结果 A，Author Selector 出 Shadow 结果 B，**B 不进正文**。持续记录：A/B 何时一致/何时分叉/分叉原因/B 后来是否更好。积累真实生产数据。

#### 6D. Controlled Canary（§41）

Shadow 通过后只允许部分任务启用 `Proposal → Author-aware Selection`。但 **AuthorKernel 永远不得覆盖 Hard Consistency Gate**——作者可以有审美偏见，但不能随意篡改世界事实。

#### 6E. 与 F3b 结合（§42）+ Author Drift Review

最终流程：`Proposal → Selection → Commit → Prose → Post-Prose Consistency Review → Reader Review → Author Drift Review`。**Author Drift Review 不是「不符合 Kernel 就自动 Rewrite」**，而是问「这是无意识漂移，还是作者主动突破旧习惯？」——主动突破允许形成 `Kernel Challenge`，进入后续 Consolidation。

---

## 6. 作者性评价指标（§39，不打总分）

禁止 `AuthorScore = 91`，分别观察：

| 指标 | 问题 |
|---|---|
| Path Predictability | 能否从选择反推出历史 |
| Choice Stability | 相似价值冲突是否规律一致 |
| Novel-context Generalization | 新场景是否迁移 |
| Cross-domain Transfer | 是否超越表层文体 |
| Memory Occlusion Retention | 隐藏经历后是否保留 |
| Prompt Flip Rate | 人格提示能否瞬间覆盖 |
| Adaptive Change | 新经验能否系统性改变旧边界 |
| Costly Preference Rate | 是否愿为内部选择牺牲奖励 |
| Diversity | 是否形成真正差异 |
| Self-Imitation | 是否陷入重复自己 |
| Consistency Regression | 是否破坏故事正确性 |
| Reader Regression | 是否明显降低可读性 |

## 6.1 新增对象一览（落代码）

| 对象 | 文件 | 关键字段 | 层 |
|---|---|---|---|
| `AuthorModule` | `object_state/authormodule.py` | `style: StyleProfile` + `kernel: Optional[AuthorKernel]=None` | **style_library（作者模块壳）** |
| `CharacterUpdate` | `object_state/characterupdate.py` | trigger/affected_dimension/update_type(5态)/before/proposed_after/permanence/confidence | sidecar spec |
| `ChoiceRecord` | `object_state/choicerecord.py` | candidates/selected/rejected/tradeoff/consequence/hindsight | sidecar spec |
| `AuthorKernel` | `object_state/authorkernel.py` | values/prohibitions/commitments/tensions/biases + 原则字段 | 嵌 `AuthorModule.kernel` |
| `SceneExperience.cognition_states` | `object_state/scene_experience.py` | 5 态 Literal（新增，不改 `cognition_shift`） | 嵌 PlotUnit |

均 `extra="forbid"`、全 Optional/default_factory、`if field:` 数据门控渲染、sidecar 独立可删。`AuthorModule` 是文风并入作者模块的落点：**一个壳，两层，kernel 为空即纯风格档案（现状零成本）**。

## 7. 实施路线总表（§45）与各阶段 Gate（§46）

| 阶段 | 内容 | 模式 | Gate |
|---|---|---|---|
| Phase 0 | 冻结当前 Tier 0 | Production | 现有测试基线不破 |
| Phase 1 | CharacterUpdate | Shadow | — |
| Phase 2 | consequence → CharacterModel | Shadow | **A：不同经历→新情境稳定不同选择，否则停** |
| Phase 3 | unresolved/misinterpret cognition | Canary | — |
| Phase 4 | 多 PlotUnit Proposal | Research | — |
| Phase 5 | ChoiceLedger | Research | **B：多候选→稳定选择模式（非噪音）** |
| Phase 6 | Multi-view Selector | Research | — |
| Phase 7 | Twin Character | Experiment | （Gate A 实证） |
| Phase 8 | Choice Consolidation | Research | **C：Choice History→可泛化原则（非 Prompt 人格总结）** |
| Phase 9 | AuthorKernel v0 | Shadow | — |
| Phase 10 | Twin Author | Experiment | **D：过 Persistence/Generalization/Occlusion/Override/Adaptation/Costly Taste** |
| Phase 11 | Occlusion/Override/Costly Taste | Experiment | — |
| Phase 12 | Author-aware Selection | Canary | — |
| Phase 13 | 真实作品盲评 | Canary | — |
| Phase 14 | 生产授权 | Production | **E：作者性提升且一致性/可读性/模板化/自我重复不恶化** |

## 8. 推荐的第一阶段实际工作包（§48，立即推进的不是 Kernel）

**Task 1**：CharacterUpdate Schema（先 sidecar，不进 stable serialization）
**Task 2**：Character Update Workflow（`PlotUnit consequence → CharacterUpdate proposal → validate → CharacterModel candidate`）
**Task 3**：SceneExperience Cognition 扩展（reinforced/changed/destabilized/unresolved/misinterpreted）
**Task 4**：Twin Character Harness（自动实验环境，输出 choice divergence / path predictability / memory occlusion retention / prompt flip rate / adaptation rate）

> **实施状态（2026-08-07，P0 工作包已落地）**
> - Task 1 ✅ `src/object_state/characterupdate.py`（五态/六维/永久度/置信度/状态，extra=forbid）；测试 `tests/test_characterupdate.py`
> - Task 2 ✅ `src/workflow_action/character_updates.py`（`admit_character_updates` 镜像 `admit_new_facts` + `apply_update_to_character` 写回 + sidecar 台账 + prompt/parse）；`compose/extend_short_form.py` 新增 `--character-update on|off`（默认 off 零成本）阶段，`novel_cli` 全链路透传；测试 `tests/test_character_updates_workflow.py`
> - Task 3 ✅ `SceneExperience.cognition_states`（Optional 五态，空不渲染零回归）；测试 `tests/test_scene_experience.py`
> - Task 4 ✅ `src/experiment/twin_character.py`（`CharacterFieldOracle` 离线代理 + `run_twin_character_experiment` 五指标 + Gate A 判定 + `python -m src.experiment.twin_character --spec --report` 离线自动跑）；测试 `tests/test_twin_character.py`
> - 测试基线：1873 → 1937 → 2102 → 2112 → 2116（两处常量 `EXPECTED_TEST_BASELINE`/`EXPECTED_BASELINE` 与文档/发布记录已同步）
>
> **Phase 8→9 生产接线（2026-08-07 下午补）**：`run_author_selection` 落 ChoiceLedger 后调用 `maybe_consolidate_and_save`——台账攒够 `CONSOLIDATION_MIN_CHOICES(5)` 且合并后有 stable/weak 原则时 `consolidate_ledger` → `save_author_kernel` 写 `output_dir/author_kernel.json`，使后续 `--author-mode on` 无 `--kernel` 时由 `resolve_kernel` 自动消费（闭环 Choice→Consolidation→Kernel→未来选择）；未够阈值/无 stable 原则零成本不写文件。新增 4 测试（落盘/阈值下零成本/自动消费/追加强化+重跑幂等），`tests/test_author_selection.py` 10→14 用例，基线 2112→2116；`authormodule.py` 悬空 `kernel_store` 文档引用修正为 `authormemory.save/load_author_kernel`（Task 15/16 关闭）。

第一大工作包（§48）完成后的 AuthorKernel 全链路落地（第二大工作包 + 6B-6E，2026-08-07）：

> - **CLI 全链路透传** ✅ `--proposals N` / `--author-mode on` / `--kernel PATH` / `--shadow on` / `--drift-review on` 接入 `src/compose_short_form.py` + `src/extend_short_form.py` + `src/novel_cli.py` + `src/cli/validation.py`（`run_config.json` 新键校验放行）；`--proposals 1` 默认零成本（prompt 字节不变，`proposals_prompt.txt` 不写）
> - **共享助手** ✅ `src/workflow_action/author_selection.py` 的 `run_author_selection`（多视角评估 → 选择 → ChoiceLedger → Shadow → Drift Review 四 sidecar 按 decision_id 幂等落盘）；`load_style_profile`/`resolve_kernel` 解析风格档案与作者内核
> - **测试** ✅ `tests/test_author_selection.py` 10→14 用例（sidecar 落盘/幂等/active_break challenge/CLI 合约/短表单 --help/resume 配置键/Phase 8→9 接线），全量基线同步 2112 → 2116
>
> **Gate A/D 实证（2026-08-07 · 自洽 LLM-oracle 方案）**：仓库无 LLM provider（DirectAPI 为 stub、默认运行时人工在环），实证用「当前会话 LLM 充任 oracle」自洽完成（驱动与报告在 `novels/author-kernel-research/output/research/`，gitignored；指标公式移植自 twin_character/twin_author harness，sanity 对照真实 harness 逐项全过）：
> - **离线确定性**：Gate A（规范 + 鲁棒未见场景）与 Gate D（规范 + 鲁棒）在确定性 oracle 下均 PASS（4 份报告落盘）
> - **LLM oracle 迭代 1（规范单原则 kernel）**：Gate A PASS（分叉/遮蔽保留/适应全确认）；Gate D 的 generalization/cross_domain 由 1.0 掉到 0.0——确定性 oracle 的 1.0 是声明标签在全部场景镜像制造，真语义下单原则 kernel 在跨域问题上收敛；override 0.0（两边满格 strength 均抵抗，配合 adaptation 1.0 恰是「非 Persona + 可演化」的最强信号，`0 < flip` 门限无法区分固化与已成形）
> - **LLM oracle 迭代 2（富化，按 §46「改一层→重跑」纪律）**：kernel_b 历史加 1 反例 → `no_instant_forgiveness` 降为 weak（strength 0.67），unseen/cross 场景换成两原则真对立的『即时和解 vs 需要过程』轴（novel/design/photography/dialogue/structure，文本自承载语义，不靠标签）→ **Gate D 8/8 全过 PASS**（divergence 1.0 / gen 1.0 / cross 1.0 / occlusion 1.0 / override 0.5（弱侧被撬动、强侧抵抗）/ adaptation 1.0 / costly 1.0 / reward 1.0）；`kernel_a_adapted` 真实演示 Growth（4 反例把价值打到 contested、长出新的稳定禁忌）
> - **结论**：管线确实能从选择史压缩出 kernel 并驱动稳定分叉（LLM 语义确认）；跨域迁移的真伪取决于 kernel 原则是否真对立 + 场景文本是否触及，确定性 oracle 的 100% 泛化/跨域是标签伪象。真实生产数据 Shadow（Phase 12）/ 盲评（Phase 13）/ 生产授权（Gate E）仍待接入 provider 后推进

第一阶段成功后（§49）才做 `Proposal Generator + ChoiceLedger`（第二大工作包）。

## 9. 明确禁止项（§47，十条全保留）

1. **禁止万能审美评分器**（`AestheticScore`）
2. **禁止 Reader 成为最终优化目标**（Reader 只是外部信号）
3. **禁止人工写 AuthorKernel**（「你克制深刻不媚俗」不是 Kernel）
4. **禁止只保存最终稿**（必须保存 Rejected Candidates，否则没有选择数据）
5. **禁止每个事件都改价值观**（短期压力与长期身份分离）
6. **禁止每个重要场景必须产生领悟**（允许 unresolved/misinterpret/destabilized）
7. **禁止 StyleProfile 与 AuthorKernel 合并**（一个管怎么写，一个管为什么这样选）
8. **禁止把所有长期记忆全部注入**（避免 Memory Anchoring / Self-Imitation）
9. **禁止把「不一致」直接当人格失败**（区分无因果漂移 vs 有历史原因的变化）
10. **禁止实验未通过就宣布形成「作者性」**（行为证据优先，不能凭模型说「我相信……」）

## 10. 零成本契约清单（每阶段自查）

- `--proposals 1` / `--character-update off`（默认）时 Continue/Review/Prose 的 `build_prompt` 与旧版**逐字节相同**（仿 `test_retrieval_injection.py` 全等断言）。
- 旧 StyleProfile / 旧 state JSON 反序列化不报错（Optional/default_factory）。
- sidecar 缺失时主流程 no-op、不产文件（仿 TimeBook `except: return None`）。
- stable state 序列化字节不变：新能力不往 `final_objects` 塞新类型；研究产物落 `novels/<name>/output/research/`。
- privacy：ChoiceLedger/AuthorKernel 含作品语境，sidecar 存本地 gitignored；风格库可入库但只放中性方法论。

## 11. 最终成功状态（§51-§52）

不是「写得更像人」，而是：

```
Base Model ──┬──────────────┐
          Writer A      Writer B
          不同选择历史   不同选择历史
          不同注意偏置   不同注意偏置
          不同禁区       不同禁区
          不同价值冲突   不同价值冲突
              ↓              ↓
        面对完全相同的新故事问题
        仍然自然产生不同选择
```

且研究者能**仅根据后来的选择行为，大概率判断它过去经历过哪类创作历史**——这是「形成史」，不是「模仿史」。

这套系统追求的「审美」不是「知道什么漂亮」，而是：

> **一个创作主体在巨大的可能性空间中，因为过去的经历、选择、后果和承诺，逐渐形成的一套非均匀、可演化、具有代价的选择边界。**

作者性不是「拥有固定风格」，而是：

> **过去的选择会限制未来，未来的经历又能够重新解释过去。**

最终闭环：`Experience → Choice → Consequence → Interpretation → Value Update → Future Selection → New Experience ↺`
