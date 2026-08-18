# Automatic Novel Narrative System

## 这是什么

自动小说叙事系统的概念地基和运行切片。能解析叙事结构、维护状态、推进故事、审查结果。

## 当前状态

- 三流完成：audit（审核）、extend（续写）、compose（创作）
- 领域层：genre formula、hook taxonomy、情绪弧模板、结构节点-情绪映射、关键节点钩子质量要求、平台约束、genre 规则
- 长程编排：NarrativeFrameUnit 维护 book/arc/chapter/scene 层级（B4 已采纳并实现）
- 增量续写：`--resume` 模式支持从保存状态继续，自动推进 scene cursor
- 长文章节级处理：`chunking` 切章节、`reconcile` 跨章合并、`audit_report` 生成报告；audit/extend 入口支持 `--range`、`--batch-size`、`--max-chapters`、input hash 校验
- 结构概览：OutlineUnit 提供 `--outline-only` 模式，并已接入长文 audit / extend 主管线（30+ 章时作为 Rebuild 结构先验）
- 结构一致性：audit Reconcile 阶段使用 outline 检查角色与 genre 一致性；`check_temporal_contradictions` 做时间矛盾检测（死亡后仍活跃 / 过期事实仍被持有 / 时间感知否定）
- 信息凭证一致性：`09_information_warrant_rules.md` 定义"角色凭什么知道"（通道/时效/来源）；`info_warrant_knowledge.py` 存六通道谱系（亲历/转述/书面/公开/推断/记忆）+ P1-P4 凭证约束；review 弱信号检测 iss_info_channel（转述产亲历细节）/ iss_info_relay（转述时效）/ iss_info_scope（知识域翻转），与 `05_information_release_rules.md`（该不该知道）正交互补
- 事实时间有效性：`FactEntry.validity_interval`（ValidityInterval，None=始终有效），to_prompt_line 渲染 `(第三章~第五章)` 后缀；旧 state（无该字段）可反序列化
- 写作风格：`novel style` 提炼 StyleProfile（量化分析 + LLM 质性提炼），compose/extend 注入续写 prompt；`--lint` 做 AI 味检查；风格库（`--name` 另存 / `--style` 跨小说引用）
- **作者类模型（研究性）**：`novel corpus-author-model` 对本地语料做确定性方法层统计，staged `[WAITING]` 提取带置信度+章节证据锚的选择模式；一作者一份 `author_models/<中性id>.json`，提取器支持 N 个语料实例并存，产物 gitignored，不是生产资格或自动终审
- 读者体验：`10_reader_experience_rules.md` 定义正文层 7 维判定标准（开头/现场感/解释/对白/情绪/反馈/钩子）；`novel reader` 做分级标注（good/needs_work/weak，route=none 不阻断）+ 派生读者预期台账（ReaderExpectationLedger：读者在等什么，waiting/advanced/overdue/stale）；与一致性审查（ReviewUnit 可阻断）并行分离
- 动态角色建模：CharacterModel 支持 current_pressure（当前压力）/ change_trajectory（变化轨迹）/ relation_behaviors（关系→行为差异，同一角色对不同人行为不同）；Optional/default 向后兼容，空字段不渲染零回归
- 场景体验中间层：PlotUnit.scene_experience（SceneExperience：主角看见/阻碍/选择依据/结果/认知变化五维），Continue 生成、Prose 展开注入，让结构扩写带现场感
- 状态检索：以当前 NarrativeState 为 query，从 FactLedger/ForeshadowGraph 检索 top-k 相关条目注入 Continue prompt（【相关事实检索】段）；零依赖 TF-IDF/关键词（档 1）；`--retrieval on|off` 开关（默认 on，空语料/空 query 静默降级字节不变）
- 时间域：TimeBook 先验模型（`novels/<名>/output/time/time_book.json`），`novel time` 管理（--rebuild 锚提取 / --check 时间线报告 / --status）；FACTTRACK v2 检测 4/5/6（时间回退 / 先知逾期 / 季节历法违反）；extend/compose 的 Continue 以【时间上下文】段注入上章/本章/时代背景/时间规则；rubric 装配时间一致性维（8→9 维）
- 零成本契约：无 TimeBook → 无注入、无检测、无产物，prompt 字节与旧版逐字节相同（回归测试锁死）
- 内容分级（NSFW 开关）：贯通创作与审核一套语义——compose/extend `--nsfw on|off`（默认 off 正常向：off 时 Continue prompt 注入【内容分级】禁成人内容硬规则，on 时注入成人向授权）；compliance `--nsfw on|off`（默认 off：on 时跳过「涉黄」分类扫描，其余分类仍扫）；build_prompt 的 nsfw_context 缺省空串零成本不注入
- **续写可行性门禁（flow v3）**：extend/compose Continue 前跑确定性 viability 分析（`analyze_continuation_viability`——no_active_frame / open promises / 终止型 formula node / ReaderContract.ending_conditions 子串命中 → continue / needs_premise / stop；终止型节点歧义时 staged prompt 人工裁定）；deterministic stop/needs_premise 时写 `viability_report.json`（含 reasons + required_premise）并停下不继续生成；continue 时注入【续写可行性】note（终止型节点收束）；v2 逐字节不变零成本
- **读者契约（ReaderContract，flow v3）**：逐作品「读者为什么选择这本书」sidecar（`reader_contract.json`，不入 serialization 白名单）；`novel contract` CLI 管理（`--default` 零 LLM 确定性初始契约 / staged prompt→response→save / 已存在时检查模式）；forbidden_drifts 确定性子串命中阻断 Proposal Selector 候选（`contract_violation` blocking）；Continue/Proposals 注入【读者契约】段（continuation.py 拥有段头，调用方只传 body）；v3 Pre-Review 闸 SceneExperience 关键单元强制（conflict/released_information 非空且 is_effective 必须携带 scene_experience，缺失 → blocking missing_consequence / motivation_gap；过渡单元不强制）
- 统一入口：`novel` 命令管理 `novels/<小说名>/` 工作目录，并调用 audit / extend / compose / style / compliance / rubric / time staged CLI
- **Post-Prose Review（先成文、后审查）**：extend/compose 时序改为 Continue → Pre-Review(代码闸,零LLM) → Prose → Review(读正文)；Review prompt 注入【本章正文】+ 正文层 7 维审查（兑现/人物忠实/情绪落地/解读空间/场景在场/对白/AI 味），正文层独有缺陷（同章对白逐字重复、AI 味、情绪靠声明）第一次可被审查发现；route=rewrite 时正文已存在 → 正文层修订（`prose_revise`）优先，`--no-prose` 保持对象层修复；`output/.flow_version=2` + 旧版残留 fail-fast 迁移；`review.build_prompt(objects, ctx, prose_text=None)` 缺省与旧版逐字节相同（零成本契约）
- **Draft/Commit 分离**：Post-Prose PASS 前正文只是 staged draft（`output/prose_draft.txt`），不进入 `chapters/`；下游（continuity/excerpt/reader/state）不消费未提交稿；PASS 后才提交为正式 `chapter_N.txt`（落盘闸门 `is_duplicate_of_last` 在提交点兜底）；block 时无章节落盘，draft 留待人工
- **Post-Prose 修订 A/B 台账 + 盲评**：正文层修订（`prose_revise`）时把 `{cycle_id, issue_types, issue_severity, version_a, version_b, which_is_original, detection, revision_gain}` 记入 `output/prose_revision_ledger.json`（schema v2，A/B 顺序随机化、`which_is_original` 隐藏）。`novel ab` 盲评：**Revision Agent ≠ Judge**——judge prompt 不展示 issue / 修改建议 / 哪个是原文，只读文本；按 issue_type 分层统计 + 净收益（better−worse）+ Wilson 95% CI + Abstain（no_difference/uncertain，不强迫二选一）；分离 **Detection Precision**（说有问题时真有问题吗）与 **Revision Gain**（按它改真的更好吗）——不默认「Review 成功」
- **Style Drift 测量（measurement-only）**：`novel drift` 产出 `output/drift/drift_report.json`——AI 章 vs 人类 baseline 的表层（句长/段长/对白/破折号）与 AI 化指标（他意识到/明白、身体反应、不是A而是B、解释性收尾、比喻）逐章 delta；Draft vs Committed 比较判断 **Review 是否在制造 homogenization**（提交时归档 `output/prose_history/draft_chapter_N.txt`）。只测不改
- **PASS Blind Audit（测漏检率，version-aware + True Miss 口径）**：`novel audit-pass` 抽样 committed（route=pass）章节，独立 Blind Audit 自由找缺陷（不透露是 PASS 样本、不给原 Review 结果）。**口径：PASS ≠ Review 没发现 issue**——每章对比 O（原 Review issues，随提交记录在 `chapter_provenance.json`）与 A（audit findings），匹配要求 **同 issue_type + 连续较长公共片段（LCS≥4）**（不用任意 bigram，防公共 2-gram 把不同位置的同类问题误判为同一 issue）；audit 复现 Review 已报的 issue 是**一致判断，不算漏检**。输出：`audit_finding_rate` / `true_miss_rate` / `actionable_true_miss_rate` / `blocking_true_miss_rate` / `severity_disagreement_rate`。按审核世代分 cohort，历史旧章留作 failure archive
- **Deferred Issue Gain / Missed Improvement（A/B 实验）**：原 Review 报了但 PASS 的 issue → 做轻量修订 → 盲评 = **Deferred Issue Gain**（Review 的克制是否正确）；Blind Audit 报、原 Review 完全没报的 issue → 做审计引导修订 → 盲评 = **Missed Improvement**（真漏掉了一个改善机会）。样例：ch9『忽然』deferred=no_difference（克制对）、ch8 interpretive_space missed=better（轻度改善机会）
- **misinformation 生命周期**：Review 可声明 `misinformation_updates`（`disproven` 移除被击穿的信念 / `corrected` 用 `[{from,to}]` 替换为修正形态）；错误信念是 **belief state，与 knowledge truth 分离**——事实被证伪 ≠ 人物心理已接受，只移除确实不再持有的断言，不自动合并进 knowledge_state（`CharacterModel.reconcile_misinformation`）
- 状态生命周期审计：`docs/00_project/44_state_lifecycle_audit.md` 统一登记所有跨章节状态的创建者/修改者/消费者/生命周期/失效/替换/追加/删除/降级/调和/陈旧检测，判定 Current/Consumable 字段被当 Accumulating 存是跨章节污染根因（近 9 轮修复即逐个打补丁的同一语义错误）
- CharacterUpdate 长期写回门禁：`permanence=long` + `confidence≥0.8` + 方向变化（shift/reinforce）+ 非既有状态升级（防『恐惧再次升级』链式覆盖）才允许写 fear/outer_goal/self_image；transient/medium 只进 current_pressure/change_trajectory（`src/workflow_action/character_updates.py`）；台账按 char+dimension+proposed_after 去重、status 流转 applied/rejected——一次场景不能轻易重新定义一个人
- 文风/接续锚点拆分：`load_recent_excerpts`（接续：刚发生了什么，含已生成章）与 `load_original_style_sample`（文风：只取原书人类文本）职责分离——AI102 不再模仿 AI101 生成章，避免 Self-Imitation Drift（`src/workflow_action/excerpt.py`）
- 编辑人机回环：`novel gate --require-approval` 让 severity=critical 的 ReviewIssue 必须操作者人工 approve/reject（`approval_decision.json`）才推进；全 approve 跳转 ContinueUnit、blocking issue 严格不可审批（`src/boundary_control/approval_gate.py`）
- **Author 因果闭环（最终验收修复）**：把 Author 模块的断裂点接通——① 多候选 Proposal prompt 注入【作者选择结构】+【作者选择史】（`render_kernel_context`/`render_memory_context`，`build_author_prompt_context`，N≥2 才启用、空 kernel 零成本），让生成模型真的看见作者价值结构；② `novel hindsight` 从**真实已提交章节**回填 ChoiceRecord 的 consequence/hindsight（`src/workflow_action/hindsight.py`，evidence 必须滞后 ≥lag 章，禁止决策时刻即时自我解释），回填后下次 Consolidation 把它作为反例证据（hindsight ∈ overturned/partial_regret → counterexample）；③ Challenge ledger 并入 Consolidation（open KernelChallenge → 反例）；④ Consolidation 阈值参数化（`--consolidation-min/min-support/contested-ratio`，短程实验可调）。验收实验（碑下 ch14-18 三分支 ON/OFF）：Path Dependence 0.7、Occlusion retention 1.0、Counterfactual 5/10 选择翻转、Costly Taste 2/2、Adaptation 强度 1.0→0.6（PARTIAL）；但 shadow 0% 分叉说明 kernel 对确定性选择机制影响弱，作者实际影响走生成注入而非选择翻转
- **Frame 生命周期（实证发现）**：frame 是**陈旧状态参与生成**的一类——第一幕结束后 frame 仍注入 `resolution/余波/重建/升华`，与新一幕需要（rising_action/冲突升级）冲突（与旧 pressure/knowledge 同类）。**最小 expiry 修复**：`advance_cursor` 终止帧消费（last scene 无 successor 也标 completed + 完成父链）；`get_cursor` 无 active 返回 None；`build_continue_context` 处理 no-active-frame（不再注入陈旧终止帧，明确进入 needs-frame，不自动造新 arc，由人工/规划层决定下一幕）。`docs/00_project/44_state_lifecycle_audit.md` 的 Frame/Cursor 行已更新
- **正文偏短是 diagnostic signal 而非硬目标**：1645 从『目标』降级——低于带宽时**检查是否少了真正应该发生的内容**（不是必须扩）。Expansion Gain 盲测（ch9-12 retrospective）3/4 扩写更好，但更好的扩写补的是**叙事节拍**（线索/证词/行为）非篇幅；ch9 只加纹理→no_difference。**上游承载结构实验**：同一起点 A 单 PlotUnit=905 / B PlotUnit+beats=1759 / C 多 PlotUnit=819（更紧凑）——完整性来自 **beats 层**而非更多 PlotUnit，系统缺的可能是**正文前的章节展开层**（未做成模块，等 prospective 数据）。`prose_history/raw_chapter_N.txt` 归档首次 raw（prospective Expansion Gain 从 ch13 起无重建）
- 章节正文目录：续写/创作的章节正文统一存 `novels/<小说名>/chapters/`（如 `chapters/chapter_1197.txt`），与 `output/` 系统产物分离；小说工作区一律不提交 GitHub（`novels/*/` 已入 `.gitignore`，canary 证据目录 `novels/tier0-*-canary/` 反向放行），GitHub 仅保留工具框架（代码/测试/脚本/规则文档/运行配置/风格库积累）
- 续写篇幅与原文参考：有原文时，原文按章拆分入 `chapters/chapter_01.txt` 起（保留章节标题行），续写从下一编号续（原文 23 章 → 续写从 `chapter_24` 起），目录内编号连续；续写章节篇幅对齐原文章均（参考值：《示例小说丁》约 6,500 字符/章），不得明显偏短；续写须参考原文语感、意象系统（杨柳/水/套装/信等）与事件细节，不能凭空脱离原文
- 隐私纪律：所有具体小说信息（标题、正文、角色、工作区名、作者笔名）一律不提交 GitHub；git 历史中如有此类内容，push 前须用 `git filter-repo --path-*` 完整重写历史剔除（本项目已按此重写并 force-push）；正文仅存本地 `novels/<小说名>/chapters/`；写作风格综合积累可入库，统一放仓库根 `style_library/<name>.json`（中性文件名，不含小说名/作者笔名/机器路径）
- **提交点读者门禁链（Q1 Phase 4，零成本）**：flow v3 在 Review PASS 后、事务提交前跑 `evaluate_commit_reader_gate`——ProseEvidence 提取 → 跨章 `reconcile_prose_evidence` → `ReaderQualityGatePolicy`；确定性硬门禁始终内联（跨章硬一致性 / **重复闭环第二次即阻断**（draft 顿悟核心==上一章）/ 契约 forbidden_drifts 子串 / 纯氛围无推进），LLM 读者维度由操作者 `novel reader`（单章 7 维）或 `novel reader --window 3|5`（连续章 `serial_reader_report.json`，`SerialReaderUnit`/`SerialReaderReport` 12 维相邻+窗口）产报告后才生效（报告未武装→轴显式 unarmed，不静默放行）；route=block/manual → rejected 不提交、不推进 Frame；关键维（hook/payoff/presence/emotion）weak → rewrite 提示 prose 修订；通过后 `facts_package_hash` 写入 run manifest；`novel gate` 报告三轴（结构/连续性/读者质量）。`run_manifest` 支持**新 run 生命周期**（提交完一章续写下一章：归档旧 run 到 run_history/，同 run_id 仍严格五态）
- 测试：**2961 tests passing**（精确口径：**2960 passed + 1 skipped（收集 2961）**；**本地测试声明**，GitHub 无可见 CI；当前 HEAD `b464a8a`，validated_parent `157914ed`；R3 真实 staged 状态驱动 rollout 新增验收测试基线）
- **A1/G7 状态（2026-08-16）**：A1 自动调用与单章自动生产链已存在但**未获生产资格**；**G7 自动审美资格失败、已退役**（不再作为大神级自动终裁，`auto_calibrate` 保留为实验工具）；自动评价按五层分工（确定性硬门禁 → 专门轴 → 匿名盲评 → PASS 漏检审计 → 系统外人类盲评）。当前状态唯一权威入口：`docs/00_project/03_current_status.md` §0；升级计划：`docs/00_project/52_mastery_upgrade_plan.md`（P0–P7）。

## 怎么用（在 Codex 中）

### 准备

```bash
pip install -e .
```

### Audit 流（审核已有文本）

```bash
novel audit 示例小说甲 --input 示例小说甲.txt
```

- 第一次运行生成 `novels/示例小说甲/output/rebuild_prompt.txt` → 你生成响应保存到对应 response 文件 → 重跑
- 第二次生成 review prompt → 保存 review response → 重跑
- 完成，产物在 `novels/示例小说甲/output/`

长文用法：

```bash
novel audit 示例小说甲 --input 示例小说甲.txt --range 1-50 --batch-size 5
novel audit 示例小说甲 --outline-only   # 仅产出结构概览
```

### Extend 流（续写）

```bash
novel extend 示例小说乙 --input 示例小说乙.txt
```

- 三次重跑（Rebuild → Continue → Prose → Review；**先成文、后审查**——Review prompt 注入【本章正文】，正文层 7 维审查：兑现/人物忠实/情绪落地/解读空间/场景在场/对白/AI 味；成文前 Pre-Review 代码闸拦截结构硬错误）
- 产物：`novels/示例小说乙/output/extend_result.json`；章节正文（PlotUnit 展开成文）统一写入 `novels/示例小说乙/chapters/`，命名 `chapter_<编号>.txt`

### Compose 流（从 WorkSpec 创作）

```bash
novel compose 仙侠新作
novel compose 仙侠新作 --workspec workspec.json
```

- 两次重跑（Continue → Review）
- 产物：`novels/仙侠新作/output/compose_result.json`

### Style 流（写作风格提炼）

```bash
novel style 示例小说丙 --input 示例小说丙.txt
novel style 示例小说丙 --input 示例小说丙.txt --tone 克制 --genre 仙侠 --lint
```

- 两次重跑（量化分析 → LLM 提炼 → 合并）
- 产物：`novels/示例小说丙/output/style/style_profile.json`；`--lint` 额外产出 `style_lint_report.json`
- compose/extend 的 Continue 会自动读取 `output/style/style_profile.json`，以【写作风格】段注入续写 prompt（无档案时不注入，输出字节不变）

风格库（自动入库 + 中性命名 + 相似度去重 + 检索）：

```bash
novel style 示例小说丙 --input 示例小说丙.txt                # 自动入库 → style_library/克制-官商-001.json
novel style 示例小说丙 --input 示例小说丙.txt --name 克制风    # 另存到 style_library/克制风.json
novel style 示例小说丙 --style 克制风 --lint               # 引用库档案做禁忌词 lint（跳过提炼）
novel style 某作 --style-search "人物:衬托"                # 检索库内档案 id（支持 "要素:手法" 语法，如 描写:白描 / 对白:潜文本）
novel style 示例小说丙 --input 示例小说丙.txt --force        # 入库时忽略相似度提示，强制新建
novel style 示例小说丙 --input 示例小说丙.txt --no-library   # 只提炼不写库
novel compose 新作 --style 克制-官商-001                  # 新小说注入库档案（id 或文件名均可）
novel extend 续作 --style 克制风                          # 续写注入库档案
```

- 自动入库：未指定 `--name` 时，提炼结果自动生成风格化中性 id `<tone>-<genre>-<seq>`（如 `克制-官商-001`），写入 `style_library/<id>.json` 并登记到 `style_library/manifest.json`（语义索引，跨小说检索/引用用）
- 相似度去重：入库前与库内档案算相似度（数值 60% + 分类 20% + 质性 20%），≥ 0.90 且未 `--force` 时提示 `--style <top_id>` 复用，不盲目新建，避免库无限扩张
- `--name NAME` 把提炼结果另存为命名档案到 `style_library/<name>.json`（同样登记 manifest）
- `--style NAME` 引用库中已有档案（两路解析：manifest.id 优先，其次物理文件名）：style 流跳过提炼直接按禁忌词 lint；compose/extend 的 Continue 注入该档案
- `--style-search QUERY` 在 manifest 上做关键词检索（tone/genre/POV/句式/手法笔记），列出候选 id 后退出；支持 `"要素:手法"` 语法（如 `人物:衬托`、`描写:白描`），不要求输入文本
- `--force` 忽略相似度去重提示强制新建；`--no-library` 只提炼不写库
- 未指定 `--style` 时 compose/extend 回落到小说自身的 `output/style/style_profile.json`
- 隐私：id 只含风格词，manifest 不含作品名/作者名/路径；风格库是允许入库的中性积累

### 状态检索（compose / extend 的 Continue 注入）

```bash
novel compose 新作 --retrieval off   # 关闭检索注入
novel extend 续作 --retrieval on     # 显式开启（默认即 on）
```

- 以当前 NarrativeState 为 query，从 FactLedger / ForeshadowGraph 检索 top-k 相关条目，以【相关事实检索】段注入续写 prompt
- `--retrieval on|off`（默认 on，对齐 compliance `--sensitive` 开关先例）；`--retrieval off` 是运行时回滚旋钮
- 零依赖（纯 stdlib）TF-IDF/关键词：中文无分词走字符 2-gram，实体 ID 原样精确匹配；`current_facts_in_scope` 软 boost、伏笔仅取 `linked_open_threads` 交集
- 静默降级：空 query / 空语料 / 全零分返回空串，此时 prompt 字节与旧版逐字节相同（回归测试锁死）

### Compliance 流（内容合规扫描）

```bash
novel compliance 某作 --input 某作.txt --platform 通用
novel compliance 某作 --input 某作.txt --sensitive off      # 关闭词库扫描
novel compliance 某作 --input 某作.txt --nsfw on            # 跳过涉黄分类（成人向作品）
novel compliance 某作 --input 某作.txt --lexicon custom.json # 合并自定义词库
```

- **单遍扫描**（纯代码，无 response 阶段）：扫已有正文，产出 `compliance_report.json`（含 `route: "pass"`、risk_level、max_severity、位置锚点、分类、严重级、替换建议）
- `--platform 通用|番茄|起点|晋江`（默认 通用，未知回退通用）；`--sensitive on|off`（默认 on，off 时跳过词库扫描、platform 政策检查仍跑）
- `--nsfw on|off`（默认 off；on 时跳过「涉黄」分类扫描，其余分类仍扫；与 compose/extend 生成侧 `--nsfw` 联动——正常向作品扫描涉黄、成人向作品放行涉黄）
- `--lexicon FILE` 合并自定义敏感词条目（与内置词库去重）
- 章节字数下限：并入平台政策检查，每章去空白字符数低于平台 `chapter_length_target` 下限时产出 `compliance_chapter_length_<n>` warning issue（`--sensitive off` 时仍检查；route 保持 pass）
- prose 模式扫输入 .txt；无正文场景降级 object 模式扫 PlotUnit 字段（genre/hook/conflict）
- 注意：词库命中是风险提示不是平台封禁保证

### Rubric 流（WebNovelBench 8 维本地评测 rubric 导出）

```bash
novel rubric 某作
```

- **单遍导出**（纯代码，无输入文件 / 无 response 阶段）：产出 `novels/某作/output/rubric/rubric.json`
- 把 ReviewUnit domain rules + `web_fiction.py` 领域知识按 WebNovelBench 8 维（arXiv:2505.14818）映射，`offline:true`
- 诚实标注：角色一致性 / 跨场景衔接 strong，意境 / 语境 moderate，修辞 weak（负向代理），感官 / 角色平衡 / 对白独特 none（LLM-judge 维，对象层无正文文本）
- 若有 `output/time/timeline_report.json`，自动装配时间一致性维（wnb_09），8 维 → 9 维

### Reader 流（读者体验审查：章节正文 7 维分级标注）

```bash
novel reader 某作 --input novels/某作/chapters/chapter_1.txt   # 对第一章做读者体验审查
novel reader 某作 --input ... --no-expectations                 # 跳过读者预期台账
novel reader 某作 --input ... --style 克制风                    # 引用风格库档案辅助判断
```

- **两遍式**（对齐 style：量化代理分析纯代码 + LLM 质性分级标注的 [WAITING] 循环）：产出 `novels/某作/output/reader_experience/reader_report.json`
- 7 维判定标准（`docs/03_rules/10_reader_experience_rules.md`）：开头拖沓 / 场景现场感 / 解释过多 / 对白自然 / 情绪落地 / 高潮反馈 / 章末钩子，每维 good/needs_work/weak 分级 + 位置锚点 + 诊断 + 改法方向
- **route 恒为 none 不阻断**——正文质量是连续光谱，供人工/精修参考（与一致性审查 ReviewIssue 可阻断分离）
- 默认自动派生读者预期台账：从该小说 `output/extend/extend_rebuild_package.json` 的 ForeshadowGraph 生成「读者在等什么」清单（waiting/advanced/overdue/stale），写入 `reader_expectations.json`
- 复用：`recheck_against_prose`（F3a 正文相关度）为雏形、`analyze_style_metrics` 量化代理、`load_style_context` 风格档案

### Time 流（时间域：锚提取 / 时间线报告 / 状态查看）

```bash
novel time 某作 --input 某作.txt --rebuild   # 提取时间锚点，生成 time_book.json（无则创建，有则校准）
novel time 某作 --input 某作.txt --check     # 产出 output/time/timeline_report.json
novel time 某作 --status                     # 打印 TimeBook 状态（novel list 亦展示 time_status）
```

### Contract 流（读者契约：逐作品「读者为什么选择这本书」sidecar）

```bash
novel contract 某作 --default                # 零 LLM：写确定性默认初始契约（reader_contract.json）
novel contract 某作                          # 已存在 → 检查模式打印摘要；无契约 → [WAITING] staged prompt
novel contract 某作 --edit                   # 无契约时强制 staged 编辑（写 contract_prompt.txt → 填响应 → 重跑保存）
```

- **单遍式**：产出 `novels/某作/output/<extend|compose>/reader_contract.json`（sidecar，不入 serialization 白名单）
- mode 自动检测（extend 优先看 `output/extend/extend_rebuild_package.json`，否则 compose 看 `workspec.json`）
- 契约含 core_pleasures 2–4 项 / follow_reason / core_tension / chapter_pacing / opening_minimum_promise / must_keep / forbidden_drifts / valid_hooks / ending_conditions
- 消费（flow v3 门禁）：Continue/Proposals 注入【读者契约】段；forbidden_drifts 命中阻断 Selector 候选；ending_conditions 供可行性闸判定 stop；v3 Pre-Review 闸强制 SceneExperience
- 零成本契约：flow v2 不读取不注入；无契约时 prompt 字节与旧版逐字节相同

### AB 盲评、PASS 漏检审计 与 Style Drift（measurement-only）

```bash
novel ab 某作                      # A/B 盲评：写 judge prompt → 独立 Judge 填响应 → 重跑汇总
novel ab 某作 --judge judge_2      # 多 Judge 追加（schema 支持 3/3、2/3、split 共识）
novel ab 某作 --detection          # 只跑 Detection Precision pass（原文是否确有被标记缺陷）
novel audit-pass 某作              # PASS Blind Audit：独立盲审 route=pass 章节，估算漏检率
novel drift 某作                   # Style Drift：AI 化 drift + Draft vs Committed homogenization 检查
```

- A/B 台账 `output/prose_revision_ledger.json`（schema v2）在正文层修订时自动累积；`novel ab` 逐对物化盲评 prompt（不展示 issue/哪个是原文），Judge 填响应后重跑产出分层统计（by issue_type + net_rate + Wilson CI + Abstain + 多 Judge 共识）
- `novel audit-pass`：不告诉 Judge 这是 PASS 样本，自由找缺陷 → miss_rate 估算 + 按 issue_type 分层（Review 漏检率）
- `novel drift` 纯代码单遍：比较人类 baseline vs AI 各章的表层/AI 化指标（含 formula_node 叙事阶段标注），并比较 Draft vs Committed 判断 Review 是否在制造 homogenization

- **单遍执行**（纯代码，无 response 阶段）：`--rebuild` 是显式管理命令（split_by_chapters 切章 + 提取章节时间锚点）；`--check` 跑 build_timeline_report 写出时间线报告
- TimeBook 存 `novels/某作/output/time/time_book.json`（全 Optional，schema_version / initial / anchors / era / timelines / rules）
- 零成本契约：无 TimeBook 时 audit/extend 自动校准是 no-op、无【时间上下文】注入、无时间检测、无文件产出，prompt 字节不变
- compose 从 `workspec.time`（date/lunar/loc）初始化 TimeBook 初稿（无该字段 / 已有 TimeBook 时零成本）
- FACTTRACK v2 检测 4/5/6（anchor 时间回退 / 伏笔时间线逾期 / 季节历法违反）并入 run_time_audit，全 warning 非阻断

### Codex 提示词（直接复制使用）

审核小说：
执行以下循环直到脚本完成：1. 运行 novel audit 示例小说甲 --input 示例小说甲.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说甲/output/ 中最终产物的 route 和 issues 数量

续写小说：
执行以下循环直到脚本完成：1. 运行 novel extend 示例小说乙 --input 示例小说乙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说乙/output/ 中最终产物的 route 和 PlotUnit 概要

从零创作：
执行以下循环直到脚本完成：1. 运行 novel compose 仙侠新作 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/仙侠新作/output/ 中最终产物的 route 和 PlotUnit 概要

提炼写作风格：
执行以下循环直到脚本完成：1. 运行 novel style 示例小说丙 --input 示例小说丙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说丙/output/style/style_profile.json 的 tone_labels、POV 和 stats 概要

时间锚提取与时间线报告：
执行以下循环直到脚本完成：1. 运行 novel time 某作 --input 某作.txt --rebuild 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/某作/output/time/time_book.json 的 anchors 数量和 era 概要。若需时间线报告再加 --check，读 output/time/timeline_report.json 的 issues 数量

把上面提示词中的小说名、输入文件路径替换为实际值即可。长文加 --range 1-50 --batch-size 5。

查看与断点续跑：

```bash
novel list
novel resume 示例小说甲
```

## 核心对象

`WorkSpec`, `WorldModel`, `CharacterModel`, `NarrativeState`, `PlotUnit`, `FactLedger`, `ForeshadowGraph`, `ReviewIssue`

- StyleProfile：写作风格档案（spec，非状态），随 `novel style` 产出，compose/extend 以「已确认先验」消费；`--name` 另存为命名库档案（`style_library/`），`--style` 跨小说引用
- TimeBook：时间域先验模型（spec，非状态），随 `novel time --rebuild` / compose workspec.time 产出，extend/compose 以【时间上下文】注入消费；全字段 Optional，缺省零成本
- PlotUnit 新增 `formula_node`：关联结构模板节点（如 climax），用于情绪推荐与钩子质量检查
- WorkSpec 新增 `platform`：目标平台标识（如 web_novel_daily），用于平台约束注入

## 注意事项

- 所有入口脚本在 response 文件缺失时会提示 `[WAITING]` 并正常退出，不会报错
- 重新运行同一脚本即可继续
- 测试：`pytest tests/ -q`
