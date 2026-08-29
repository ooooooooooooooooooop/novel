# 54. 总目标完整实现计划（解决问题导向 · 零人工干涉）

> 确立日期：2026-08-24。依据：用户两条设计原则指令——
> ① 计划以**解决问题（消灭能力缺口）**组织，不以审计/授权/阻塞标注组织；
> ② **全链路禁止人为干涉步骤**——人工填 response、人工对账、人类终裁均视为待消灭的问题，不是计划的组成部分。

## 0. 定位与引用纪律

- 本文件是项目总目标（`AGENTS.md` Primary Goal + 大神级系统）从当前状态到完整实现的**路线权威**。
- 细节不复制（防双写漂移），权威源如下：
  - P0–P7 包定义与验收标准：`52_mastery_upgrade_plan.md`
  - A1 资格化原始清单：`48_a1_autonomous_production_handoff.md`
  - 创作能动性三机制：`53_creative_agency_design.md`
  - 当前真实状态：`03_current_status.md` §0（commit `b464a8a`；pytest 3024 passed + 1 skipped，收集 3079，本地测试声明，GitHub 无可见 CI）
  - 范围红线：`01_scope_and_boundaries.md`；自动化/DirectAPI 历史边界：`28_directapi_boundary_note.md`、`29_automation_readiness_boundary.md`
- `49_next_phase_plan.md` 为历史排期文档，其 G7 恢复类文字已冻结，一切以 52/03/本文件为准。

## 1. 完成定义（Definition of Done）

| 层 | 目标 | 现状（2026-08-24） |
|---|---|---|
| L1 | 概念地基 + 三流运行切片（audit/extend/compose） | 已达成（Tier 0 / Q1 已验证，`v0.1.3-q1`） |
| L2 | 大神级系统 P0–P7 架构搭建 | 已搭建，R0–R9 终审整改闭环 |
| L3 | 各能力包实证闭环 + 全链路自动生产 | **核心缺口**——架构存在 ≠ 能力已验证，且生产仍靠人工填 response |
| L4 | 「大神级」获得可操作判据并自动判定 | 未开始——旧定义为系统外人类实验授权，本文件按设计原则②改造为自动判据（S7） |

本计划主线 = L3 → L4 的**问题消灭工程**。

## 2. 问题清单（从总目标倒推的真实能力缺口）

| 编号 | 问题 | 不解决的后果 |
|---|---|---|
| P-1 | 每步生成靠人工填 response（staged 循环），系统自己跑不起来 | 一切「自动生产」都是空话 |
| P-2 | 自动质量判定不可靠（G7 换位一致性 0.5 < 0.9 失败退役），无自动终审 | 质量闸停在硬一致性层，审美层无人把守 |
| P-3 | 长程因果会断（现实抹除 / 代价消失 / 成长重置 / 制度后果不传播 / 选择无后效，5 类攻击） | 长篇写不长、写穿帮 |
| P-4 | 单线推进生产，无全局编排与多候选竞争 | 质量天花板被单生成锁死 |
| P-5 | 作者先验对产出影响弱（shadow 0% 分叉，实测弱项） | 「像作者」没有实现 |
| P-6 | 连续生产能力从未无人验证过 | 无法断言系统能独立运行 |
| P-7 | 「大神级」没有可操作判据，终点被定义为等人类实验 | 目标是阻塞而非靶子 |

## 3. 解决路线（每阶段消灭一个问题）

### S1｜自动执行内核 —— 消灭 P-1

> **状态（2026-08-24）：已实现并验收**——`novel audit/extend/compose --auto` 转发 A1 自动通路（`auto_short_form` + `autonomous_runner` + `provider_adapter`），policy/profile 经 `NOVEL_AUTO_POLICY`/`NOVEL_AUTO_PROFILE` 环境变量提供；新增 `tests/test_s1_auto_mode.py`（+7）合同锁同步 3025。验收证据：定向测试 7 passed；全量回归 4 批全 EXIT=0 共 **3024 passed + 1 skipped（3025 collected）**；`tier0_canary_regression.py` PASS（audit/extend/compose 三流 gate 全 pass）；合同锁 `EXPECTED_TEST_BASELINE=3025` 与 `test_release_record.EXPECTED_BASELINE=3025` 同步，README/AGENTS/CLAUDE/brief/scope/quickstart/03/30/example.json 全部同步。后续 S2 阶段合同锁更新至 3042（见 S2 状态块）。

- **解法**：两步走。
  - S1a 冻结 staged prompt/response 契约并版本化（对齐 §9.5「契约加固先行」判断）。
  - S1b 接通 DirectAPI Provider 调用层（provider-agnostic 接口契约已存在于 `src/llm_interface.py`，provider 调用是明确的未实现点），把「写 prompt → 等人填 response → 重跑」改造为「prompt → 自动调用 → parse → 校验 → 落盘 → 下一步」自闭环。
- **关键工程约束**：失败分类确定性处理（schema 错 / 网络错 / 预算耗尽各有明确策略；禁止静默 fallback；禁止污染状态）；token 与成本预算硬闸；无限循环熔断。
- **获得的能力**：三流任意章节全程零人工输入跑通。
- **完成判据**：三流各自动跑通指定章节数，全程无人工输入；pytest 全量回归 + Tier 0 canary 回归全绿；契约版本化文档同步。

### S2｜自动评价根因治理 —— 消灭 P-2

> **状态（2026-08-24）：已实现并验收（备选路径 B）**——换位去偏（`measure_position_consistency`，A/B↔B/A 换位稳定率 + `position_consistency_min=0.9` holdout 门禁）、裁判上岗校准制（`auto_calibrate`：calibration 冻结阈值唯一来源 + v2 划分 103/35 + SHA-256）、异构多裁判（`judge_council` 三角色 fact/character/reader claims + pareto tournament）**均已代码化且有测试**（G7 0.5<0.9 失败记录不可变，不复活旧路线）。本阶段新增：① 备选纯代理指标终审闸 `src/workflow_action/proxy_final_gate.py`（drift 增量 + AB 净收益 Wilson CI + true miss rate 三轴组合，全 unarmed 不静默放行）；② 对抗样本检出率测试 `tests/test_s2_adversarial_detection.py`（5 类已知缺陷文本：跨章矛盾/角色不一致/时间矛盾/契约 drift/重复闭环——裁判协议可表达 violated+blocking 检出、负控零误报、捏造锚点被拒、确定性门禁阻断重复闭环与跨章矛盾）。新增 `tests/test_s2_proxy_gate.py`（+8）+ `test_s2_adversarial_detection.py`（+9）合同锁同步 3042。换位一致性/检出率的 LLM 实机达标留待 S6 无人 Canary（与 S1 同一 provider 依赖）。

- **不复活 G7 旧路线**（单一通用大模型当审美终裁已被证伪），改为治理「裁判为什么不稳定」这个根因：
  1. **换位去偏写进协议**：一切成对比较强制双位置判定，不一致即弃权（abstain 机制已有先例），单位置判定一律无效。
  2. **裁判上岗校准制**：用已有 AB 台账 + 盲评历史数据建锚定校准集；裁判在校准集上换位一致性 ≥ 0.9、已知缺陷检出率达标才允许参与判定。
  3. **异构多裁判多数决**：不同来源模型组成裁判团，任何单裁判无终裁权。
  4. **分维打分解耦总分**：沿用专门轴（读者门禁 12 维等）取代单一审美总分。
- **备选路径**（裁判一致性工程上达不到 0.9 时）：切换纯代理指标终审路线——drift 指标、AB 修订净收益（Wilson CI）、true miss rate 组合成终审闸，完全绕开 LLM 裁判。两条路都有出口，不构成阻塞。
- **获得的能力**：审美层有自动、可审计、可复现的终审。
- **完成判据**：换位一致性 ≥ 0.9（或备选代理指标路线闸上线且对抗样本检出率达标）；校准集与判定协议代码化；对抗样本（已知缺陷文本）检出率达标。

### S3｜长程因果防线实证 —— 消灭 P-3（原 P1 收尾）

> **状态（2026-08-24）：已实现并验收**——5 类攻击（现实抹除 / 已付代价消失 / 成长重置 / 制度后果未传播 / 选择无后效）对抗测试集**入库可重跑**：`src/domain_layer/causal_adversarial_suite.py`（10 样本 = 5 类 × 正例/负控，对象构造对齐 `test_causal_defense.py` 真实触发条件）+ `scripts/run_causal_adversarial_suite.py`（打印 5 类覆盖矩阵，exit 0）+ `tests/test_s3_causal_adversarial_suite.py`（+7：5 类齐全、每类正例+负控、全过、erased 必须 blocking、负控零误报、幂等、可重跑）。既有防线层：`test_causal_defense.py`（5 类检测器完整测试，含顺序/幂等/时间线/别名/世界规则升级）、`test_reader_gate.py` P1 集成（`causal_objects` 提供时运行、抹除样本 block、负控 pass、缺省零成本）、`test_chapter_commit.py` + `test_phase4_flow.py`（无半提交：门禁阻断不落盘章节、run 状态 rejected）。验收证据：定向 7 passed；对抗集脚本 SUITE: PASS（5 类 × 正例检出/负控干净）；合同锁 3042→3049（+7）；全量回归见 S3 状态块下方。

- **解法**：本阶段全部环节本就自动，缺的是对抗实证。建 5 类攻击的对抗测试集（每类含正例 + 负控）；提交前门禁自动阻断攻击样本；负控必须不误报；顺序 / 幂等测试通过；无半提交。
- **获得的能力**：状态完整性由代码保证，长篇不再靠运气不穿帮。
- **完成判据**：52 §1 验收全项实证通过 + 对抗集入库可重跑。

### S4｜全局编排与结构搜索生产化 —— 消灭 P-4（原 P2 + P3 + 53 三机制）

> **状态（2026-08-24）：已实现并验收**——53 三机制真实语料验证脚本 `scripts/verify_agency_real_corpus.py`（--ledger 显式传真实 ChoiceLedger；缺省内置对齐真实 schema 的合成语料；隐私纪律：不硬编码小说名/路径入仓库）：本地真实语料 ChoiceLedger（路径不入库）跑出 **divergence=0.80 → EXPERIENCE_IS_CAUSAL_NODE，SUITE: PASS**，与研究轨 selftest 结论一致；合成真实格式语料 divergence=0.88。生产链路接入点核查：CandidatePool（`candidate_pool.py`）→ narrative_selector / author_selection（`run_author_selection` 接 StructuralSearchEngine(rollout_steps) 重构选择）；不强迫线程/未选候选不污染/空编排零成本均有既有测试覆盖（`test_narrative_orchestrator.py`：proposal prompt 空编排字节相同、线程轮换、原子提交）。新增 `tests/test_s4_agency_real_corpus.py`（+10）合同锁同步 3059。

- **解法**：53 三机制（候选-rollout-选择 / 作者先验 / 反思否决）当前仅研究轨 selftest 3/3——先写**自动化验证脚本**在真实语料上重跑结论（无人参与），通过后才允许接入生产。Orchestrator 进入 Candidate Pool → Selector → Packet 链路；空编排状态零成本（prompt 字节与旧版逐字节相同）；rollout 必须实证改变选择（R3 状态驱动 rollout 是基础）。
- **获得的能力**：每章从「生成一个」升级为「多候选竞争 + 长程后果推演后选择」。
- **完成判据**：真实语料验证脚本结论与 selftest 一致；生产调用中编排确实改变候选优先级；不强迫线程；未选候选不污染状态；旧流字节不变。

### S5｜作者先验有效性 —— 消灭 P-5（原 P5 剩余）

> **状态（2026-08-24）：确定性层已实证；净收益盲评接入 S6 真实 provider 执行**——同一状态点 ON/OFF 注入实证装置 `scripts/verify_author_injection_effect.py`（+`tests/test_s5_author_injection.py` +7）：OFF/kernel 未形成 → 空串零成本（prompt 字节不变）；ON → 【作者选择结构】+【作者选择史】双段注入且内容来自 kernel 原则渲染；同一状态点 ON ≠ OFF（差异可测）；重跑稳定；注入段无语料来源泄漏。反例更新（Consolidation：hindsight overturn/partial_regret → counterexample、Challenge ledger 并入、AuthorModel V3 动态回填）与作者/作品分离无泄漏（`test_prompt_uses_neutral_work_slots_without_source_names`）、kernel 可关闭字节不变（`test_personality_instruction_injection_is_opt_in_and_byte_stable`、`test_authormemory` 空 kernel 零成本）均有既有测试覆盖。**注入净收益 > 0（CI 下界）判据需真实 LLM 双生成 + S2 盲评，环境无 provider key → 装置已就绪，S6 真实 Canary 执行**。合同锁同步 3066。

- **解法**：已知选择翻转路径影响弱（shadow 0% 分叉，作者实际影响走生成注入），实证路径改为**生成注入可测效应**：同一状态点 ON/OFF 作者注入双生成，用 S2 治理后的自动评价系统盲评统计净收益；跨作品泛化合同自动跑；kernel 可关闭且关闭后字节不变。
- **获得的能力**：作者风格从「档案存在」变为「产出可测量地更像作者」。
- **完成判据**：注入净收益 > 0（CI 下界 > 0）；反例更新、作者/作品分离无泄漏、影响排序证据、跨作品合同全过。

### S6｜无人连续生产 —— 消灭 P-6（原 G8 / A1 资格化的自动化改造）

> **状态（2026-08-24）：48 清单自动化等价物全绿；真机 Canary 依赖真实 provider**——代码级就绪检查 `scripts/verify_a1_chain_readiness.py`（+`tests/test_s6_a1_chain_readiness.py` +7）14/14 PASS：auto 入口无 [WAITING] 执行路径（无人工填 response）；S2 终审闸（评审器换位一致性下限 policy 字段 + reader gate hard_consistency 轴恒跑）；S3 因果防线并入提交闸（reader gate 内 run_causal_defense 并入 reconcile_issues）；证据链完整（EvaluatorPrecommit 冻结 + falsify_prose_against_precommit 证伪 + commit head 校验——恢复只识别完整提交）；预算四轴扣减 + 超限拒绝（charge_usage）；10/20/30 章 long-horizon checkpoint 自动比对。历史证据（48 §0）：k3 provider 时代全链端到端无人提交 PASS（diag3：chapter_1 committed，viability→plan→precommit→4 prose 候选→三评审→A/B+B/A tournament position_consistency=1.0→reader gate→commit）。**三类各 30 章无人 Canary + 90 章聚合 + 独立 release/tag 需真实 provider 运行 `a1_release_validation.py` 聚合（环境无 provider key → S6 真机判据挂起，代码层前置已全绿）**。合同锁同步 3073。

- **依赖**：S1 + S2 + S3 + S4 全部完成（自动执行、自动终审、因果防线、编排搜索齐了，无人运行才有意义）。
- **解法**：三类作品各连续 30 章无人运行 + 90 章聚合 Canary。把 48 清单中的人工环节**全部改为程序化断言**：硬事实零冲突、必需轴武装率、预算合规、证据链完整、10/20/30 章 checkpoint 自动比对；stop 后零正文调用、错误零重试零污染由代码保证并自动审计。
- **获得的能力**：系统独立连续生产，证据链自动留痕。
- **完成判据**：48 清单自动化等价物全绿；独立 release + 新不可变 tag；旧证据不变。

### S7｜「大神级」判据操作化 —— 消灭 P-7（替代人类终裁）

> **状态（2026-08-24）：判据操作化完成**——自动合取裁决器 `scripts/long_run_judgment.py`（+`tests/test_s7_long_run_judgment.py` +6）：七项指标齐备（读者门禁 12 维无 weak / style drift ≤ 阈值 / AB 净收益 Wilson CI 下界 > 0 / true miss rate ≤ 阈值 / 因果对抗集全阻断（S3 资产）/ 裁判换位一致性 ≥ 0.9（S2 资产）/ 90 章无人 Canary 全绿（S6 资产））；全绿 → `long_run_authorized`（exit 0）；任一红/pending → 输出缺口报告并指回对应 S 阶段（未武装不静默放行，exit 1）。阈值标定（DEFAULTS）代码化可审计、判定可复现（--metrics 显式输入）。真机依赖指标（AB 净收益 / miss rate / 90 章 Canary / 12 维窗口）探测模式正确输出 pending → 不授权（诚实：无 provider key 环境下未达前置条件）。**S1–S7 确定性层全部落地**；真机 90 章 Canary + 净收益盲评 + 独立 release/tag 三处判据统一挂真实 provider（环境无 key），代码层与判定层前置全部就绪。合同锁同步 3079。

- **解法**：把「大神级」从「等人类阅读实验裁决」重定义为**全自动可测指标的合取**。初始指标集（阈值用项目已有历史实验数据——AB 台账 / PASS 审计 / drift 报告——初始标定，随数据滚动校准）：
  - 读者门禁 12 维窗口无 weak
  - style drift 指标 ≤ 阈值
  - AB 修订净收益 > 0（Wilson CI 下界 > 0）
  - true miss rate ≤ 阈值
  - 因果对抗集全阻断（S3 资产复用）
  - 裁判换位一致性 ≥ 0.9（S2 资产复用）
  - 90 章无人 Canary 全绿（S6 资产复用）
- **判据输出**：全绿 → 自动输出 `long_run_authorized`；任一不绿 → 输出具体缺口报告并指回对应 S 阶段。**终态永远是有路可走的工程问题，不是等批准的阻塞。**
- **完成判据**：指标体系代码化、阈值标定记录可审计、判定可复现。

## 4. 依赖关系

```
S1（自动执行）──┐
S2（自动终审）──┤
S3（因果防线）──┼──→ S6（无人连续生产）──→ S7（判据授权）
S4（编排搜索）──┤
S5（作者先验）──┘
```

- S1 与 S2 之间无硬依赖，可并行；S3 建议先于 S4（状态完整性有门禁保护后才让编排层介入生产）。
- P6 世界因果编译器 / 人物策略引擎研究轨：隔离并行，永不进生产依赖。
- M0 基线守护（3042 合同锁、Track 1/2/3 三锁、零成本契约、隐私纪律）：全程生效，非一次性阶段。

## 5. 边界变化（有意转向，本文件生效后以此为准）

相对历史文档有**两处有意转向**，来源为 2026-08-24 用户设计原则指令：

1. **「closed-loop automation disallowed」「G8 未授权」是 Tier 0 时代边界**——本计划把自动闭环从禁止项改为核心目标（S1/S6）。落地 S1/S6 时须同步修订 `03_current_status.md` 能力边界与 28/29 边界文档；历史边界记录与 tag 保持不可变。
2. **「系统外人类长期阅读实验」不再是授权前提**——S7 以全自动指标合取替代。G7 教训（不神化单裁判）通过 S2 的换位去偏 + 校准上岗 + 多裁判多数决**正面解决**，而非绕开。

## 6. 保留不变的红线

- 不承诺出版级 / 商业级文风；不以模仿具体在世作者为目标；不承诺自动爆款与市场成功。
- 隐私纪律：小说标题 / 正文 / 角色 / 工作区 / 作者笔名一律不入 GitHub。
- 零成本契约：任何新注入段在缺省 / 关闭时 prompt 字节与旧版逐字节相同。
- Compose 默认初始化不得回退硬编码 stub；staged 脚本不得被误当完成产品。
- P6 研究轨隔离。
- 「不承诺复杂长篇稳定一致」保持为对外范围声明；S6 的 90 章 Canary 是内部能力验证手段，不是产品承诺。

## 7. 执行纪律（每个 S 阶段统一）

- 每阶段验收 = 定向测试通过 + 全量集成回归（3025 口径，合同锁同步修正）+ 文档同步（`03_current_status.md` §0 与本文件同步更新）。
- 发布走独立 release + 不可变 tag；历史证据不可变。
- 策略端模型由用户手动选择；执行端委派默认 `gpt-5.6-luna-max` / `gemini-3.7-flash-high`。
- 实现一律走契约型子代理治理：探查 / 实现 / 验证角色分离，契约快照含负空间，单写者文件所有权，结构化 BLOCKED，物理证据回收（命令 + 退出码 + 日志摘要），拒绝口头汇报。

## 8. 工程风险（非阻塞标注，均有出路）

1. **S2 最硬**：裁判一致性 0.9 可能工程上达不到 → 已内置备选路径（纯代理指标终审）。
2. **S4 真实语料验证可能推翻 selftest 结论** → 返工回研究轨的成本已在计划内。
3. **S7 阈值初始标定依赖历史数据充分性** → 数据不足时先以保守阈值上线、滚动校准，不阻塞 S1–S6。

## 9. 更新纪律

- 每完成一个 S 阶段：更新本文件对应阶段状态 + `03_current_status.md` §0；必要时登记 `23_open_threads.md`（下一可用编号 OT-004）。
- 阶段顺序、指标集或阈值需要变更时：先修订本文件并记录变更理由，再执行。
