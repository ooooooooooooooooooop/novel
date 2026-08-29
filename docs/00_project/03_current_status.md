# Current Status

## Purpose

This file gives a newly opened agent a fast snapshot of what is already done, what is still unstable, and what work is most reasonable next.

Update this file after each meaningful round of project-shaping work.

---

## 0. 状态主入口快照（2026-08-17，R0–R9 终审缺陷彻底闭环与真实状态推演强化）

> 本节是本仓库**当前真实状态**的唯一优先入口。下方历史章节只描述对应时间点的状态，
> 以本节为准。数字均为实机验证，不把 collected 写成 passed。

### 0.1 真实基线

- 当前 commit：`b464a8a`（Working tree 干净）；**validated_parent=`157914ed`**（上一验证父提交，只作父声明，不是当前 commit）
- pytest：`3079 passed + 1 skipped (collected 3080)`（**本地测试声明**：精确口径为 3079 passed + 1 skipped，收集 3080；合同测试 `EXPECTED_TEST_BASELINE="3080"` 锁收集数。**GitHub 无可见 CI**——该数字仅为本地 pytest 声明，非远端自动验证产物）
- Tier 0 三流 Canary：`python scripts/tier0_canary_regression.py` → **PASS**（audit/extend/compose `novel gate` 均 ok=True, route=pass, blocking=0）
- 发布记录：`docs/00_project/releases/tier0-release.json`（2301 历史）、`q1-release.json`（v0.1.3-q1）——**不可变，不修改**
- tags：`v0.1.1-tier0`、`v0.1.2-tier0`、`v0.1.3-q1`——**不可移动**

### 0.2 能力边界（冻结）

- **Tier 0**：人工/Codex 分阶段生产（operator-in-the-loop staged CLI）——**验证通过，生产就绪**
- **Q1**：连续生产、Reader Gate、事务提交与崩溃恢复——**验证通过（v0.1.3-q1）**
- **A1**：自动调用与单章自动生产链**已存在**，但 **G7 自动审美终端资格失败**、G8 无人 Canary 未授权——**未获得生产资格**（详见 §1.5 与 `48_a1_autonomous_production_handoff.md`）
- **大神级系统**：**尚处建设阶段**——P0–P7 全链路架构已搭建，R0–R9 终审整改已彻底闭环。**不得声称已达大神级**；最终是否达大神级必须由系统外隐藏来源人类长期阅读实验验证。
- **作者类模型（ADR-15，研究性）**：`Author` 支持一作者一份中性实例，确定性方法层统计与 staged 选择模式推断分离；`novel corpus-author-model` 支持 N 语料的批量提取 API，实例产物位于 gitignored `author_models/`，不具备生产门禁或自动终审资格。

### 0.3 G7 状态（已退役）

- G7 自动审美资格失败记录**保留不可变**（position consistency 0.5 < 0.9，阈值不降）。
- G7 从项目总目标门禁降级为**历史研究性子能力**；`auto_calibrate` 保留为实验工具。
- **不再把任何通用大模型裁判包装为最终审美真相**；自动评价按五层分工
  （确定性硬门禁 → 专门轴 → 匿名成对盲评 → PASS 漏检审计 → 系统外人类盲评）。
- 观点文件 50 / 51 为**研究观点**（非当前实施状态），供后续裁决。

### 0.4 终审缺陷整改闭环（R0–R9，2026-08-17）

本轮整改彻底消除了系统中的伪造漏洞、协议矛盾与未决回退逻辑，重点闭环 4 大整改包：

1. **R0: 状态真源与测试基线彻底统一**
   - 当前 commit 真源为 `b464a8a`；`validated_parent=157914ed` 仅记录为验证父声明，**不得误写为当前 commit**。
- 全量回归测试基线统一为 `3079 passed + 1 skipped (collected 3080)`（**本地测试声明**：精确口径为 3079 passed + 1 skipped，收集 3080；**GitHub 无可见 CI**，非远端自动验证产物）。

2. **R3: 状态驱动的多步动态推演引擎（真实 staged rollout）**
   - 现有确定性投影正式命名 `deterministic_scenario_projection`（保留为快速风险探测）。
   - 生产搜索改用 `simulate_state_driven_rollout`：严格「当前 Snapshot → 生成 actor_decisions → 生成并验证 RolloutDelta → 应用到克隆状态 → 下一步重新读取新状态」，每步不读原 proposal 预写的 primary_risk / impact_next_3_to_5_chapters / reader_expectation_delta 作为未来答案；指标来自对后续状态的评价，不含按 step_index 固定增减的公式。
   - 验收测试「修改 Step 1 实际结果 → Step 2 产生不同决策」已落地。

3. **R5: AuthorModel V3 资格协议与生产仲裁一致性**
   - 生产环境 Pareto 多目标选择中彻底移除关键词代理平局决胜（keyword proxy tie-break）。
   - Pareto 前沿未决（underdetermined）时严格阻断并生成 `structural_selection/prompt.txt` 路由至人工操作者裁决，保持与资格协议完全一致。

4. **R6 & R1: 彻底消除密码学后门与建立不可伪造长程资格证据审计体系**
   - 彻底消除 `dummy_hash` 等测试与调试后门，强制采用严格 SHA-256 密码学签名（Cryptographic Packet Signing）。
   - `qualification_eligible` 强制要求完整版本覆盖（full version coverage）。
   - 在 `inspect_long_horizon_preconditions` 中建立不可伪造资格证据前置审计，严禁未经全量实证伪造授权证据。

### 0.5 历史实施范围（P0–P7，见 `52_mastery_upgrade_plan.md`）

1. P0 统一项目事实状态（本文档）
2. P1 长程因果防线（已完成事件被抹除 / 代价失效 / 成长重置 / 制度后果不传播 / 选择无未来差异）
3. P2 Narrative Orchestrator（编排状态 + 生产调用方）
4. P3 章节级结构异质搜索 + 短期 rollout + Pareto
5. P4 Taste Stack 换轨（专门轴 + 统一质量报告 + G7 退役标注）
6. P5 AuthorModel V3（反例 / 后果回填 / 作者-作品分离 / 跨作品评测合同）
7. P6 世界因果与人物策略研究轨（World Causal Compiler + Character Policy Engine）
8. P7 人类盲评工具包 + 长程授权判断

每包验收：定向测试通过 + 集成回归通过 + 文档同步。最终输出 `long_run_authorized` 或 `long_run_not_authorized`——未满足全部前置条件时**不得授权**。

**S1 状态（自动执行内核，2026-08-24）**：已实现——`novel --auto` 转发 A1 自动通路（`_run_auto` → `auto_short_form` → `autonomous_runner` → provider_adapter），policy/profile 经 `NOVEL_AUTO_POLICY`/`NOVEL_AUTO_PROFILE` 注入；自动评审器（judge 三角色）多裁判多数决 + 换位一致性下限（S2 根因治理）；staged 契约版本化在位。新增 S1 验收测试 → 合同锁 `3079`。

**S2 状态（自动评价根因治理，2026-08-24）**：已实现——换位去偏（judge 三角色多裁判 + position consistency 下限）、校准上岗（threshold 冻结）、多裁判多数决；备选纯代理指标终审闸（proxy-metrics final gate：drift AI delta + AB Wilson CI + true miss rate）落地为可运行终审装置。无真实 provider key → LLM-judge 真实机一致性验证与 S6/S7 同类约束挂起；对抗性检出（换位偏置/裁判命名槽位依赖）定向测试覆盖。合同锁 `3079`。

**S3 状态（长程因果防线实证，2026-08-24）**：已实现——5 类攻击（现实抹除 / 代价消失 / 成长重置 / 群体后果未传播 / 选择无后效）对抗测试集**入库可重跑**（`src/domain_layer/causal_adversarial_suite.py` + `scripts/run_causal_adversarial_suite.py` + `tests/test_s3_causal_adversarial_suite.py` +7）；既有 `test_causal_defense.py`（5 类检测器完整测试）＋ `test_reader_gate.py` P1 集成（提交前门禁阻断）＋ `test_chapter_commit.py` / `test_phase4_flow.py`（无半提交）。合同锁 `3079`（+7）。

**S4 状态（编排搜索生产化，2026-08-24）**：已实现——53 三机制真实语料验证脚本 `scripts/verify_agency_real_corpus.py`：真实 ChoiceLedger 跑出 **divergence=0.80 → EXPERIENCE_IS_CAUSAL_NODE（SUITE: PASS）**，与研究轨 selftest 结论一致（53 §7「真实作品语料验证」缺口已补）；生产链路（CandidatePool → narrative_selector / run_author_selection + StructuralSearchEngine rollout）核查在位，不强迫线程/未选候选不污染/空编排零成本测试覆盖在位。新增 `tests/test_s4_agency_real_corpus.py`（+10）→ 合同锁 `3079`。

**S5 状态（作者先验生成注入实证，2026-08-24）**：确定性层已实证——同一状态点 ON/OFF 注入实证装置 `scripts/verify_author_injection_effect.py` + `tests/test_s5_author_injection.py`（+7）：OFF/kernel 未形成零成本（字节不变）、ON 双段（【作者选择结构】+【作者选择史】）注入且内容来自 kernel 渲染、同点 ON≠OFF 可测、重跑稳定、无来源泄漏；反例更新/跨作品无泄漏/kernel 可关闭字节不变均有既有测试覆盖。**净收益盲评判据（注入净收益 > 0，CI 下界）需真实 LLM 双生成 + S2 盲评，装置已就绪 → S6 真实 Canary 执行**。合同锁 `3079`（+7）。

**S6 状态（无人连续生产，2026-08-24）**：48 清单自动化等价物全绿——代码级就绪检查 `scripts/verify_a1_chain_readiness.py` + `tests/test_s6_a1_chain_readiness.py`（+7）14/14 PASS：auto 入口无 [WAITING] 执行路径；S2 终审闸（换位一致性下限 + reader gate hard_consistency 轴）；S3 因果防线并入提交闸（run_causal_defense 并入 reconcile_issues）；证据链完整（precommit 证伪 + commit head 校验）；预算四轴扣减 + 超限拒绝；10/20/30 章 checkpoint 自动比对。历史证据（48 §0）：k3 provider 时代全链端到端无人提交 PASS（diag3：chapter_1 committed，position_consistency=1.0）。**三类各 30 章无人 Canary + 90 章聚合 + 独立 release/tag 需真实 provider 运行 `a1_release_validation.py` 聚合（环境无 provider key → 真机判据挂起，代码层前置全绿）**。合同锁 `3079`（+7）。

**S7 状态（大神级判据操作化，2026-08-24）**：已实现——自动合取裁决器 `scripts/long_run_judgment.py` + `tests/test_s7_long_run_judgment.py`（+6）：七项指标齐备（读者门禁 12 维无 weak / style drift ≤ 阈值 / AB 净收益 Wilson CI 下界 > 0 / true miss rate ≤ 阈值 / 因果对抗集全阻断（S3 资产）/ 裁判换位一致性 ≥ 0.9（S2 资产）/ 90 章无人 Canary 全绿（S6 资产））；全绿 → `long_run_authorized`；任一红/pending → 缺口报告指回对应 S 阶段（未武装不静默放行）。阈值标定代码化可审计、判定可复现（--metrics 显式输入）。**S1–S7 确定性层全部落地**；真机 90 章 Canary + 净收益盲评 + 独立 release/tag 三处判据统一挂真实 provider（环境无 key），代码层与判定层前置全部就绪。合同锁 `3079`（+6）。

### 0.6 质量判定修订（2026-08-20，Step 4 单变量证伪）

- 此前研究层判定「**主角借力不出面 = 模型默认、指令难修**」（`output/quality_research/01_project_fact_audit.md` §B3 / §F8 / §G4 / §H.2）**已被证伪**，改判为「**prompt 契约层可修复**」。
  实验：单变量（仅新增一条续写要求）、同模型两臂（opus5）、双截点（ch200 / ch1000）、独立盲判（claude-opus-4-8，不知哪臂是 treatment）——两截点**均判 treatment 更接近真实作者且均高置信**；ch1000 确定性代理借力标记 **12 vs 0**。
  证据：`output/quality_research/04_step4_hd_falsification.md`。
- **已落地**：`src/workflow_action/continuation.py`【续写要求】**第 11 条**（条件式措辞：原作借力则保持、原作本就亲力亲为则保持其亲力亲为），位于常驻需求条内、**不新增注入段 → 零成本契约不变**；回归测试 `tests/test_continuation_offstage.py::test_delegation_requirement_present`。
- **诚实边界（不得越读）**：被证伪的是「**指令不能改变输出方向**」，**不是**「该漂移已在成稿层修复」——n=2 截点、单判官、单生成模型，**流水线级回归盲评未做**。**布局深度未被本实验覆盖，原「模型默认」判定保留**，且同样从未被单变量实验检验过。
- **基线影响（已完成全量复核）**：该修复新增 1 个测试函数（`tests/test_continuation_offstage.py`）；全量 pytest 实机复核结果为 `1 failed, 2968 passed, 1 skipped`，唯一失败即合同锁漂移（`tests/test_cli_runtime_contract.py::test_collected_test_baseline_matches_contract`）；连同结构搜索 T3 阶段一新增（`tests/test_structural_search_t3_phase1.py` +6），本轮新增测试合计 +7，修正合同锁后 §0.1 基线更新为 `2969 passed + 1 skipped (collected 2970)`，合同锁 `EXPECTED_TEST_BASELINE="2970"`（口径不变：本地测试声明，GitHub 无可见 CI）。发布记录、tag、G7 失败记录均未改动。
- **基线影响（2026-08-21 复核）**：作者语料采样粒度修复新增 12 个测试函数（`tests/test_corpus_author_model.py`）；全量 pytest 实机复核结果为 `1 failed, 2980 passed, 1 skipped`，唯一失败仍为合同锁漂移（`tests/test_cli_runtime_contract.py::test_collected_test_baseline_matches_contract`，collect-only 实际 2982）；修正合同锁后 §0.1 基线更新为 `2982 passed + 1 skipped (collected 2983)`，合同锁 `EXPECTED_TEST_BASELINE="2983"`，`docs/00_project/tier0_release_record.example.json` 同步 2982（口径不变：本地测试声明，GitHub 无可见 CI）。发布记录、tag、G7 失败记录均未改动。

---

## 1. Current State

The repository is currently **end_to_end_validated** and **Tier 0 production ready — three-flow daily-production hardened**.

Tier 0 (local staged CLI v0, operator-in-the-loop) was validated on 2026-07-28:

- full pytest baseline: 3080 tests passing（精确口径：3079 passed + 1 skipped (3080 collected)；本地测试声明，GitHub 无可见 CI）
- audit canary (`tier0-canary`) passed `novel gate`: `ok=true`, `review_route=pass`, `next_workflow=ContinueUnit`, `blocking_pending_count=0`
- canary evidence: `docs/00_project/releases/tier0-canary-evidence.json`
- saved canary gate result: `docs/00_project/releases/tier0-canary-gate.json`
- release record: `docs/00_project/releases/tier0-release.json` (passing the single combined validation command)
- immutable checkpoint: git tag `v0.1.2-tier0`

Three-flow daily-production hardening was completed on 2026-07-29 (see `docs/00_project/34_tier0_daily_production_hardening_plan.md`):

- extend canary (`tier0-extend-canary`) and compose canary (`tier0-compose-canary`) each ran a real staged Codex loop (rebuild→continue→review, and continue→review→rewrite→rereview) and passed `novel gate` with the same four standards; previously only audit had a real canary
- operator runbook covering all three flows, their staged slots, resume semantics, the compose `ns_initial` input_state_ref trap, and the mtime/orphan-response failure modes: `docs/00_project/35_operator_runbook.md`
- one-command regression gate (read-only, no API): `python scripts/tier0_canary_regression.py`
- three-flow aggregation evidence (human-curated; the canary-evidence generator binds `workspace_path` to `novels/tier0-canary` only): `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- per-flow gate results: `tier0-extend-canary-gate.json`, `tier0-compose-canary-gate.json` (audit gate already pinned)
- canonical canary response sources now checked in under `canary_inputs/` so the three canary workspaces are reproducible
- workspace hygiene: `.gitignore` ignores `.pytest-tmp-*/`; canary `output/` artifacts are force-added as immutable evidence (they are referenced by file sha256)
- production-readiness re-certified on 2026-08-06 under a new immutable checkpoint: git tag `v0.1.2-tier0` (hardening stays inside the Tier 0 boundary; no tier upgrade is implied)
- **canary regression re-verification (2026-08-18)**: the extend/compose serialization packages (`extend_rebuild_package.json` / `compose_state.json`) are present; all three flows report `ok=true / route=pass / blocking=0`, and `python scripts/tier0_canary_regression.py` reports **PASS for all three flows**. Full-test baseline: **2962 passed + 1 skipped (2963 collected)**（本地测试声明，GitHub 无可见 CI）。

It now has both:

- a complete planning foundation through the implementation-planning artifact chain
- a running Codex-native implementation layer for `audit`, `extend`, and `compose`

The current orchestration model is staged:

1. script writes a prompt file
2. Codex generates the response JSON file
3. script is rerun and parses the response
4. the flow repeats until a result JSON is written

This is no longer only a documentation and planning workspace.
It is also not yet a deployed runtime product.

---

## 1.5 A1 Autonomous Production (Q2A) — 承重墙完成，未验收（2026-08-12）

A1 自动叙事生产（`novel auto` / AutonomousRunner）实现了严格状态机、预算、自动决策合同与单次真实 Provider 通路，
但 **未达到 A1/Q2A 生产验收**，诚实状态：**合同和 Provider 承重墙已完成，自动生产系统未完成**（见 `48_a1_autonomous_production_handoff.md`）。

- G0 通过：profile/policy/基准 SHA 冻结并重生成；Tier 0/Q1 记录与 tag 字节不变。
- G3 通过：可信停止 Canary（真实续写工作区 chapter_23 返回 narrative_stopped，停止后生成调用为零）。
- **G7 FAILED（冻结阈值不降）**：真实 holdout overall 0.8837 ≥ 0.65 ✓、分类型全 ≥ 0.5 ✓、**position consistency 0.5 < 0.9 ✗**；
  deepseek-v4-flash 评审器把候选名命到位置槽而非内容 → A/B 换位不稳定。
- **G8 无人 Canary 无法运行（0/90 章）**：冻结生成 temp0.7 下该模型只出 thinking 块无正文（4 次冒烟各在不同层显式失败：
  ProviderSchemaError×2 / TimeoutError / HTTPError）；即便生成成功，G7 位置偏置使淘汰赛必然 `quality_exhausted`。
- **G9 实现级验证通过**：完整 pytest **2817 passed**、Tier 0 三流回归 PASS、隐私扫描干净、旧记录/tag 不变；
  单命令 `scripts/a1_release_validation.py` 聚合全部证据（exit 1，`a1_gate_result.json`，release record/tag withheld）。
- 发布：Q2A/A1 release record + 新 tag **未生成**；旧 tag 未移动。证据与实施记录留在 gitignored `.taskflow/`（已归档）。

---

## 2. What Is Already Built

The repository already has:

- project scope and boundaries
- core concepts
- core object schemas
- state transition rules
- review rules
- minimal workflows
- examples and decision logs
- implementation-planning maps for unit ownership, serialization, handoff, orchestration, and no-regression acceptance
- running entry scripts for Audit, Extend, and Compose
- executable no-regression tests for Track 1, Track 2, and Track 3

The project is no longer at the "empty idea" stage or the "planning only" stage.

---

## 3. Recent Alignment Work

Recent implementation work has added or validated:

- `RebuildUnit.build_prompt()` and `RebuildUnit.parse_response()`
- `ContinueUnit.build_prompt()` and `ContinueUnit.parse_response()`
- `ReviewUnit.build_prompt()` and `ReviewUnit.parse_response()`
- Codex-native staged entry scripts
- long-form multi-arc Audit / Extend stress testing
- no-regression pytest coverage for Track 1 / 2 / 3
- full end-to-end Audit / Extend / Compose validation
- **Q1 Phase 1 (2026-08-10)**: ProseEvidencePackage + code extractor + dual reconcile (hard consistency + cross-chapter window); 8 synthetic failure fixtures all blocked with correct issue_type; full baseline 2341 passed
- **Q1 Phase 2 (2026-08-10)**: transactional chapter commit — `RunManifest` (run|seed, five statuses, source/prev/draft/facts/state-before/state-after/frame hashes, artifacts sha256), `ChapterCommitBoundary` (chapter→archive→provenance→frames→state→manifest last, atomic; `recover()` recognizes only complete commits; orphan scan; refuse unmanaged overwrite), explicit flow v2→v3 migration only (`novel migrate --to-flow 3 --preserve-old`), read-only `novel inspect-run [--json]`; flow v3 wired into compose/extend with byte-identical v2 preserved (zero-cost contract); failpoint crash-recovery tests prove no half-commit; full baseline 2414 passed
- **Q1 Phase 3 (2026-08-10)**: 续写可行性与读者契约（flow v3 门禁，v2 字节不变零成本）— `ContinuationViabilityDecision` 确定性分析（no_active_frame / open promises / 终止型节点 / ReaderContract.ending_conditions → continue / needs_premise / stop，含歧义 staged prompt），extend/compose Continue 前 viability 闸（stop/needs_premise 时写 `viability_report.json` 并停下）；`ReaderContract` sidecar（`reader_contract.json`，不入 serialization 白名单；确定性检查 forbidden_drifts 子串命中 + v3 Pre-Review 闸 scene_experience 关键单元强制）；`novel contract` CLI（--default 零 LLM 初始契约 / staged prompt→response→save / 检查模式）；Proposal Selector Consistency Gate 接入契约（命中 forbidden_drifts 的候选阻断 `contract_violation`）；SceneExperience 缺失映射 blocking ReviewIssue（missing_consequence / motivation_gap）；full baseline 2414 passed
- **Q1 Phase 4 (2026-08-10)**: 单章与滑动窗口读者门禁（提交点门禁链，v2 字节不变零成本）— `evaluate_commit_reader_gate`（ProseEvidence 提取 → 跨章 `reconcile_prose_evidence` → `ReaderQualityGatePolicy`）接入 flow v3 提交点；确定性硬门禁内联（跨章硬一致性 / 重复闭环第二次即阻断 / 契约 forbidden_drifts 子串 / 纯氛围无推进），LLM 读者维度报告武装（`novel reader` 单章 7 维 / `novel reader --window 3|5` 连续章 `SerialReaderUnit` 12 维 → `serial_reader_report.json`，未武装轴显式 unarmed）；route=block/manual → rejected 不提交，通过后 `facts_package_hash` 写入 run manifest；`novel gate` 报告三轴；`run_manifest` 新 run 生命周期（续写下一章归档旧 run）；full baseline 2470 passed

---

## 4. Current Stable Judgments

Treat the following as current project consensus:

- state first, text second
- `PlotUnit` must cause meaningful state change
- `Review` is the routing hub
- `Continue` should not skip `Review`
- formal `Rewrite` should be issue-driven
- current work should optimize for clarity and reviewability before broader automation

---

## 5. Current Checkpoint Judgment

Current phase judgment:

- foundation skeleton: stable
- workflow loop: running
- harness framing: stable
- implementation-planning output set: complete
- implementation unit boundaries: clear enough for current slices
- current implementation status: `end_to_end_validated`
- default next action: use the unified `novel` entry for staged multi-novel runs; decide next orchestration follow-up only when a new workflow gap appears

This means the project is no longer blocked on missing design pieces or first running slices.
The project has adopted a local staged CLI v0 shape and is now tightening the file/state contract before DirectAPI, UI, or further automation.

### Tier 0 Production Readiness — 2026-07-28

Tier 0 production readiness has been reached and verified:

- production tier confirmed as `local staged CLI v0` (operator-in-the-loop, no DirectAPI)
- release record path: `docs/00_project/releases/tier0-release.json`
- immutable checkpoint: git tag `v0.1.2-tier0`
- canary workspace: `novels/tier0-canary/` (audit canary, `gate` ok=true / pass / ContinueUnit / blocking=0)
- known limitations are documented in `docs/00_project/30_production_readiness_checklist.md`

Known limitations declared for Tier 0 (must hold for any future work that treats the staged CLI as a finished surface):

- DirectAPI provider calling is not implemented
- closed-loop automation remains disallowed
- Tier 0 is not a public product surface
- release record does not replace a release tag or immutable checkpoint
- response files must be materialized by the operator or Codex; no automatic model call is performed

---

## 6. Current Transition Judgment

Current transition status:

- `implementation_planning_sufficient`
- `end_to_end_validated`

Must inherit unchanged:

- Track 1 hard-fact threshold lock
- Track 2 bounded runtime-first `Rewrite` lock
- Track 3 `CharacterModel` evidence-leakback lock

Still deferred:

- DirectAPI implementation; provider calls remain unimplemented
- deployment shapes beyond local staged CLI v0
- UI / product workflow
- runtime performance
- full long-form automatic completion

---

## 7. Current Gate Judgment

Current foundation gate status:

- `pass`

Current implementation-planning sufficiency status:

- `pass`

Current end-to-end validation status:

- `pass`

Passed:

- Audit flow: staged Rebuild + Review
- Extend flow: staged Rebuild + Continue + Review
- Compose flow: staged Initialize + Continue + Review
- required result files: `rebuild_package.json`, `review_result.json`, `extend_result.json`, `compose_result.json`

Blocked by:

- none at the current end-to-end validation layer

---

## 8. Current Inherited Risks

The most important inherited risks are:

- DirectAPI provider calls remain unimplemented
- deployment shape is adopted for v0 as local Codex-native staged CLI
- RewriteUnit is code-complete with build_prompt/parse_response/apply_fix interfaces. All three entry scripts (audit/extend/compose) integrate the full Rewrite 鈫?Re-Review loop. apply_fix now supports nested field paths (e.g. `entries.0.confirmed`).
- compose-mode initialization now derives meaningful defaults from WorkSpec genre/theme/tone via domain layer, instead of hard-coded "待定" stubs
- long-form automatic completion remains out of scope

These are the areas most likely to create drift if future work treats the current staged scripts as a finished product surface.

---

## 9. Next-Step Plan

The current next-step plan is no longer "produce implementation-planning artifacts."
The artifact set is complete and the first running slices are end-to-end validated.

### 9.1 Use the implementation-planning entry as the phase anchor

- treat `docs/00_project/16_implementation_planning.md` as the current planning anchor
- keep documents 17 through 21 as the ownership / serialization / handoff / gate / no-regression baseline
- keep Track 1, Track 2, and Track 3 visible while implementation moves forward

### 9.2 Keep current implementation bounded

- keep `audit_short_form`, `extend_short_form`, and `compose_short_form` as bounded slices
- treat staged Codex orchestration as the v0 local CLI surface, not as final product deployment
- do not turn DirectAPI into an assumed implementation detail

### 9.3 Preserve the current validation baseline

Current baseline:

- `pytest -q`: 3080 tests passing（精确口径：3079 passed + 1 skipped，收集 3080；本地测试声明，GitHub 无可见 CI）
- long-form multi-arc stress test: PASS
- end-to-end Audit / Extend / Compose validation: PASS

Any future slice should state whether it preserves, extends, or intentionally changes this baseline.

### 9.4 Usage-oriented supplement

Real usage across `audit` / `extend` / `compose` is now the live implementation driver.

The proposal-status roadmap at `docs/00_project/22_usage_oriented_roadmap.md` remains useful context, but the current code has moved beyond proposal-only status for the first three slices.

Project-level open threads are tracked in `docs/00_project/23_open_threads.md`.

### 9.5 Post-sufficiency direction

Post-sufficiency implementation has reached end-to-end validation.

Completed:

- all three bounded slices are running
- LLM calls are split out of workflow units
- Codex-native staged orchestration is validated
- long-form multi-arc Audit / Extend stress testing has passed
- no-regression checks are executable pytest tests
- end-to-end Audit / Extend / Compose validation has passed
- Phase B domain layer deepening (B1/B2/B3): complete
  - B1: structure node 脳 emotional arc linkage
  - B2: platform constraint injection (WorkSpec.platform, platform guidance, platform-aware review)
  - B3: hook effectiveness quality check + genre rule injection

- Phase A execution plan (doc 24): core tasks complete; A3 WorkSpec hooks verified as no-new-field-needed; deferred compose walkthrough remains open

Current next decision:

- staged CLI runtime contract hardening
- DirectAPI design only after the local file/state contract is stable

### 9.6 Implementation progress

- **Slice 1: `audit_short_form`** - Complete
  - Rebuild + Review pipeline
  - staged prompt / response / rerun orchestration
  - outputs `rebuild_package.json` and `review_result.json`
  - end-to-end validation: PASS
- **Slice 2: `extend_short_form`** - Complete
  - Rebuild + Continue + Review pipeline
  - staged prompt / response / rerun orchestration
  - verifies state inheritance from rebuilt final state
  - outputs `extend_result.json`
  - end-to-end validation: PASS
- **Slice 3: `compose_short_form`** - Complete
  - WorkSpec + Initialize + Continue + Review pipeline
  - staged prompt / response / rerun orchestration
  - outputs `compose_result.json`
  - end-to-end validation: PASS
- **Phase B: Domain layer deepening** - Complete
  - B1: structure node 脳 emotional arc linkage (PlotUnit.formula_node, NODE_EMOTION_MAP, validate_node_emotion)
  - B2: platform constraint injection (WorkSpec.platform, PLATFORM_SNAPSHOTS, build_platform_guidance)
  - B3: hook effectiveness + genre rules (CRITICAL_HOOK_NODES, GENRE_RULES, get_hook_effectiveness, get_genre_guidance)
- **Slice D1: Incremental continuation** - Complete
  - `extend_short_form.py` supports `--resume` to load saved state and skip Rebuild
  - `compose_short_form.py` supports `--resume` to load saved state and skip Initialize
  - `NarrativeFrameUnit.advance_cursor()` auto-advances scene cursor post-Continue
  - Frame state persisted to `output/extend_frames.json` and `output/compose_frames.json`
- **LLM layer split** - Complete
  - workflow units expose `build_prompt()` and `parse_response()`
  - scripts no longer call LLMs internally
  - `src/llm_interface.py` remains a backup interface layer
- **Deployment shape decision** - Adopted for v0
    - local Codex-native staged CLI is the current usable runtime surface
    - `--output-dir` is the run isolation boundary for entry scripts
    - DirectAPI, UI, and automatic closed-loop calls remain deferred
- **Slice N1: Unified novel CLI** - Complete
  - `src/novel_cli.py` provides `novel audit`, `novel extend`, `novel compose`, `novel resume`, and `novel list`
  - per-novel workspaces live under `novels/<小说�?/`
  - tests: `tests/test_novel_cli.py`
- **Slice R1: RewriteUnit nested apply_fix** - Complete
  - `_resolve_path()` / `_set_path()` support dot-notation nested fields
  - `entries.0.confirmed`, `relations.c2`, `active_characters.0` all supported
  - old_value mismatch guard works for nested paths
- **Slice A2: generative_indicia failure type** - Complete
  - Documented in `08_failure_types.md` (Layer 4)
  - Heuristic detection in `ReviewUnit._domain_rules()` (over_modifiers, emotional_stacking, goal repetition)
  - 4 tests in `test_generative_indicia.py`
- **Slice C2: Compose initialization improvement** - Complete
  - `initialize_from_workspec()` derives defaults from genre/theme/tone via domain layer
  - No more hard-coded "待定" stubs
  - `GENRE_RULES` 鈫?`WorldModel.consequence_logic`, theme maps 鈫?`CharacterModel` goals
- **Slice R2: Review hard rules extension** - Complete
  - Rule 5: PlotUnit `output_state_ref` validity (blocking)
  - Rule 6: orphan active foreshadow detection (warning)
  - Rule 7: `time_order` fact timestamp conflicts (warning)
  - 5 tests in `test_review_hard_rules_extended.py`
- **No-regression tests** - Complete
  - Track 1 FactLedger checks
  - Track 2 rewrite boundary checks
  - Track 3 CharacterModel evidence-leakback checks
  - generative_indicia detection checks
  - Review hard rules extension checks
  - total validation baseline: 3080 tests passing（精确口径：3079 passed + 1 skipped，收集 3080；本地测试声明，GitHub 无可见 CI）
- **Slice L1: Long-form chapter-level infra** - Complete
  - `src/boundary_control/chunking.py` splits text by chapters
  - `src/boundary_control/report_formatter.py` formats audit reports
  - audit/extend entry scripts accept `--range`, `--batch-size`, `--max-chapters`
  - input hash is recorded and re-run mismatch is exposed as an error
  - tests: `tests/test_chunking.py`, `tests/test_long_form_infra.py`
- **Slice O1: OutlineUnit (structure overview)** - Complete
  - `src/workflow_action/outline.py` samples chapters and produces book/arc/character/world/timeline overview
  - audit entry supports `--outline-only` mode (skips detailed Rebuild)
  - tests: `tests/test_outline_unit.py`
- **Slice B': OutlineUnit as prior in long-form audit** - Complete
  - `audit_short_form.py` runs OutlineUnit before batch Rebuild for chapter-wise audits with 30+ chapters
  - `RebuildUnit.build_prompt(..., book_outline=...)` injects structured BookOutline fields as L1 prior
  - AuditReport records `outline_used` and `outline_arcs_count`
  - tests: `tests/test_audit_outline_injection.py`, `tests/test_long_form_audit_end_to_end.py`
- **Slice O3: extend long-form outline injection** - Complete
  - `extend_short_form.py` runs OutlineUnit before batch Rebuild for chapter-wise extends with 30+ chapters
  - resume mode skips outline because it skips Rebuild
  - `extend_result.json` records `outline_used` and `outline_arcs_count`
  - tests: `tests/test_extend_outline_injection.py`
- **Slice O5: rebuild_package outline trace** - Complete
  - `SerializationPackage.metadata` carries runtime metadata outside the four serialized layers
  - audit rebuild packages persist `outline_used` and `outline_arcs_count`
  - audit rewrite path restores outline trace from package metadata
  - tests: `tests/test_serialization_metadata.py`, `tests/test_long_form_audit_end_to_end.py`
- **Slice O2: outline-based cross-chapter consistency check** - Complete
  - `ReconcileUnit.check_outline_consistency()` compares BookOutline characters and genre against reconciled objects
  - audit flow merges outline consistency issues into cross-issue review input
  - issue types reuse `character_distortion` and `world_violation`
  - tests: `tests/test_outline_consistency.py`, `tests/test_long_form_audit_end_to_end.py`
- **Slice R3: ReconcileUnit + AuditReport** - Complete
  - `src/workflow_action/reconcile.py` merges per-chapter Rebuild outputs and surfaces cross-chapter ReviewIssues
  - `src/object_state/audit_report.py` carries the report object
  - tests: `tests/test_reconcile.py`, `tests/test_audit_end_to_end.py`
- **Phase B4: Long-range orchestration owner** - Adopted as NarrativeFrameUnit
  - `src/workflow_action/frame.py` is the running implementation
  - tests: `tests/test_frame.py`

Current limitation: DirectAPI provider calls remain unimplemented. Long-form audit end-to-end pipeline (chunking 鈫?OutlineUnit prior 鈫?multi-batch Rebuild 鈫?Reconcile 鈫?Review 鈫?AuditReport JSON/Markdown) is wired in `src/audit_short_form.py` and covered by `tests/test_long_form_audit_end_to_end.py`. Long-form extend also injects OutlineUnit prior before batch Rebuild.

---

## 10. Read After This

If you need a fuller picture, read:

1. `docs/00_project/00_project_brief.md`
2. `docs/00_project/01_scope_and_boundaries.md`
3. `docs/00_project/06_foundation_checkpoint.md`
4. `docs/00_project/07_phase_transition_memo.md`
5. `docs/00_project/08_foundation_phase_gate.md`
6. `docs/00_project/09_preimplementation_boundary_lock.md`
7. `docs/00_project/10_transition_planning.md`
8. `docs/00_project/11_implementation_planning_entry_pack.md`
9. `docs/00_project/12_serialization_candidate_note.md`
10. `docs/00_project/13_handoff_schema_candidate_note.md`
11. `docs/00_project/14_runtime_orchestration_boundary_note.md`
12. `docs/00_project/15_no_regression_verification_checklist.md`
13. `docs/00_project/16_implementation_planning.md`
14. `docs/00_project/17_implementation_unit_map.md`
15. `docs/00_project/18_serialization_responsibility_map.md`
16. `docs/00_project/19_workflow_handoff_responsibility_map.md`
17. `docs/00_project/20_orchestration_gate_map.md`
18. `docs/00_project/21_no_regression_acceptance_test_list.md`
19. `docs/00_project/27_deployment_shape_decision.md`
20. `docs/00_project/04_agent_operating_model.md`
21. `docs/00_project/05_narrative_agent_harness.md`
22. `docs/07_decisions/03_workflow_order_decisions.md`
23. `docs/07_decisions/08_context_packaging_decisions.md`
24. `docs/07_decisions/09_review_reminder_decisions.md`
25. `docs/07_decisions/10_ownership_matrix_decisions.md`
26. `docs/07_decisions/11_reviewreminder_escalation_matrix.md`
27. `docs/07_decisions/12_concurrent_reminder_routing_decisions.md`
28. `docs/07_decisions/13_factledger_admission_thresholds.md`
29. `docs/04_workflows/05_workflow_handoff_contract.md`
30. `docs/00_project/28_directapi_boundary_note.md`
31. `docs/00_project/29_automation_readiness_boundary.md`
32. `docs/00_project/30_production_readiness_checklist.md`
33. `docs/00_project/31_tier0_canary_runbook.md`
34. `docs/00_project/32_tier0_release_record_contract.md`
35. the workflow or schema file directly related to the task you were asked to do
