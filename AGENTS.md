# AGENTS.md

## Project

Automatic Novel Narrative System

## 跨对话恢复入口（2026-09-09）

- 新对话、接续旧任务或上下文压缩后，先读 `docs/00_project/55_evidence_first_novel_design.md` §0，再按需读取 `.workspace_local/task_control/CURRENT_TASK.md`。前者保存目标与有效授权，后者保存本机私有产物和实际断点；文件不存在时先从现有记录恢复，不伪造完成状态，也不重复索取已有答案。
- 最新用户输入决定本次是在执行、分析还是暂停。历史未完成任务不会自动覆盖新的分析或停止要求；恢复旧任务时沿用仍有效的授权。
- 多步骤执行任务保留目标、完成条件、授权来源、剩余事项和完成证据。助手划分的章节、调用批次、测试或文件变更不能自行替代用户的完成条件；目标变更须记录对应用户指令。
- 用户级结束检查的项目接续说明见 `.codex/CONTINUITY.md`。收到 hook 提供的当前 session/turn 后，在其指定文件登记本次意图；多步骤执行另填完成条件、证据和剩余事项。新用户请求须重新核对意图，普通问答仅登记 `answer`。不得为结束任务清空剩余事项、虚填证据或把执行改标为分析。
- 跨对话持续的是文件与有效授权，不是聊天缓存；已启动的其他会话须重新读取这些文件。其他机器或未同步的 worktree 不能假定已获得本机私有断点或 hook 信任。

## 用户设计工作准则（2026-09-07）

以下三条适用于本项目后续所有设计与规划：

1. **设计前优先澄清已知的不懂之处**：对已明确存在的用户意图、目标、约束或验收标准疑问，优先向用户询问，不以未经确认的假设替代用户意图。可通过现有上下文、仓库或官方资料核实的技术问题，先自行核查。仅暂停依赖缺失答案的部分，继续不受影响且已获授权的工作；不重复询问已有明确答案的问题。
2. **设计后必须联网检索与自检**：每项实质设计形成后，先上网检查是否已有可复用的方案、工具或研究，是否在重复造轮子；即使没有现成方案，也要依据检索结果检查设计的假设、边界和失败模式，并据此修订。技术检索优先使用官方文档、原始论文和项目源码。同一设计已核实且仍适用的来源可以复用；出现实质变化或新的关键证据时再补查。能够说明可复用方案、主要差异、关键风险及剩余未知后即可完成本项自检。联网失败时明确保留自检缺口，继续不依赖该结果的已授权工作，不将草案冒充已完成外部自检的最终方案。
3. **设计完成后检查重要遗漏**：主动追问“有没有一个目前没有意识到、但一旦意识到就可能明显改变目标、判断、方案、优先级或下一步行动的重要遗漏？”完成一轮针对关键假设、依赖和失败模式的检查，说明发现的关键遗漏及其影响，并相应调整设计；新证据可能实质改变结论时再追加检查。尚不能确定的事项明确保留为待验证问题，不把未发现遗漏当作没有遗漏的证明，也不以穷尽全部未知作为交付条件。

## 任务完成与批准

- 用户已明确要求优先实际运行与可用产物，避免测试成本超过直接运行：保留必要解析、状态保护和一次常规审查。追加测试必须回答一个会改变当前行动的具体问题；必要检查通过后，没有新变更、失败或未解决疑点就回到主任务，不追加模型对照、重复复判或为统一标签反复调用。实际出现问题时只做所需的定向诊断。此要求不取消明确的生产、发布或数据范围限制。
- 分片是实施方式，不是完成条件。执行任务结束前，对照用户要求的完成条件检查剩余工作；只要仍有同一请求内、已授权且可以执行的必要工作，就继续执行。阶段进展使用中途消息汇报，不以最终答复代替下一步操作。
- 结束执行的有效原因：交付条件已有证据满足；用户要求暂停、取消或转为分析；或者确有权限、资源、依赖阻塞且已无不受影响的必要工作可做。阻塞时写明具体对象、证据和恢复条件。完成一次调用、一个场景、一组测试、上下文压缩或准备好了下一步，均不单独构成结束理由。
- 用户仅请求分析、建议或先审阅时，以该阶段交付为完成，不擅自实施。假设性的“完全接手”讨论不构成真实运行、支出或发布授权。
- 需要批准的动作，先完成其已授权准备工作，在该动作之前等待；继续不受该批准影响的已授权工作。批准不扩大到未请求的范围，也不以重复确认替代已经有效的授权。
- 授权按对象及最新有效指令解释：历史单批额度和“待批准”记录须结合后续授权读取，不自动作为当前阻塞。被取代的限制注明取代来源，仍有效的生产、发布、模型、数据和资源边界保留；不能将持续授权解释为无限支出。
- 已有明确的操作前再次确认、生产运行、发布、push、tag、预算和模型/数据范围限制继续生效。工具可用、代码存在、测试通过或任务要求持续完成，均不自动解除这些限制。
- 验证资格与工作许可分开：`CURRENT_HEAD_UNVERIFIED` 约束资格声明，不禁止已授权的审阅、诊断和修复。

## Current Status Pointer (2026-08-30)

- 当前验证资格唯一机器真源：仓库根 `current_state.json`（第四轮 attestation 协议）。
- 历史 tier 判定与验收叙事已移出本文（见 `docs/00_project/releases/`、
  `30_production_readiness_checklist.md`、`40_session_handoff.md` 的带日期记录）。
- 测试基线：`current_state.json` 的 `collected_tests` 与
  `tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS` 唯一锁定。

<!-- state:current -->
**当前状态（唯一机器真源：`current_state.json`）**：默认标记 `CURRENT_HEAD_UNVERIFIED`——
carrier 提交不可自证；subject 资格以 json 的 `subject_overall_status` 为准。
<!-- /state:current -->

## Current Phase
历史阶段记录（2026-08-30）：S7 缺口闭环，prospective5 当时记录为死锁定格、待用户决策（见 runtime 侧战役日志）。该待决记录仅涉及对应实验，不构成全项目暂停；处理时核对具体待决问题、最新证据和恢复条件，不推定已获恢复授权。Tier 0 判定是历史 checkpoint（2026-07-28 首判、2026-08-06 重认证，tag `v0.1.2-tier0`），不自动延续到当前 HEAD；当前验证资格以 `current_state.json` 为唯一真源。三个实现切片（audit/extend/compose）代码完成，各自曾有真实 staged Codex canary 通过 `novel gate`（历史证据）。
Foundation gate, transition-planning sufficiency, and implementation-planning sufficiency have passed (2026-07-28 historical judgment).
v0 deployment shape decision (Codex-native staged CLI) is adopted.
This is a phase boundary, not a permanent repository boundary.

Tier 0 production evidence:

- production tier: `local staged CLI v0` (operator-in-the-loop, no DirectAPI)
- release record: `docs/00_project/releases/tier0-release.json` (passes the single combined validation command against the repository collected contract, 唯一真源 `tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS`)
- canary evidence: `docs/00_project/releases/tier0-canary-evidence.json`
- saved canary gate result: `docs/00_project/releases/tier0-canary-gate.json`
- immutable checkpoint: git tag `v0.1.2-tier0`

Three-flow hardening evidence (2026-07-29, re-certified under `v0.1.2-tier0` on 2026-08-06):

- extend and compose canaries each passed `novel gate`; per-flow gate results: `tier0-extend-canary-gate.json`, `tier0-compose-canary-gate.json`
- three-flow aggregation evidence: `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- operator runbook: `docs/00_project/35_operator_runbook.md`; hardening plan: `docs/00_project/34_tier0_daily_production_hardening_plan.md`
- regression gate: `python scripts/tier0_canary_regression.py` (exit 0 ⇒ three-flow baseline not regressed)

Tier 0 staged CLI boundaries that remain in force:

- Tier 0 staged entry scripts do not perform DirectAPI provider calls
- closed-loop automation remains disallowed
- Tier 0 is not a public product surface
- release record does not replace a release tag or immutable checkpoint
- response files must be materialized by the operator or Codex; no automatic model call is performed

其他运行模式的边界：

- A1 自动通路与 provider adapter 的实现状态须与 Tier 0 staged 行为区分；代码存在不代表运行已获授权。
- `docs/00_project/54_master_goal_execution_plan.md` §5 记录了自动闭环的路线变更，但研究目标、运行授权与验证资格分别核对。实际自动调用仍须满足适用的明确授权、模式策略、预算与证据条件；授权来源冲突或不明时不启动相关调用，继续不受影响的已授权工作。本次措辞修订不新增自动运行授权。
- 记录待决事项时注明具体对象、待决问题和恢复条件；仅阻塞相关动作。当前授权尚未被明确取代的限制继续有效。

## Primary Goal
Build the conceptual foundation of a novel system that can:
- parse narrative structure
- maintain narrative state
- plan story progression
- review generated results
- support future rebuilding, continuation, and rewriting workflows

## Current Scope
Completed at this stage:
1. bounded implementation slices - complete and validated
2. slice refinement and long-form stress testing - complete
3. preserving Track 1/2/3 locks in running code - complete
4. no-regression acceptance tests as code, not just documents - complete
5. Codex-native prompt / response / rerun orchestration - complete
6. Phase B domain layer deepening (B1/B2/B3): complete
   - structure node 脳 emotion arc linkage
   - platform constraint injection
   - hook effectiveness quality check + genre rule injection
7. Slice D1 incremental continuation: complete
   - `--resume` mode for extend and compose streams
   - frame cursor auto-advance
   - state persistence across runs
8. Phase B4 long-range orchestration owner: adopted as NarrativeFrameUnit (`src/workflow_action/frame.py`)
9. Long-form chapter-level infra: complete
   - `src/boundary_control/chunking.py`, `src/boundary_control/report_formatter.py`
   - audit/extend entry scripts accept `--range`, `--batch-size`, `--max-chapters`, input hash guard
10. OutlineUnit (structure overview): complete
   - `src/workflow_action/outline.py`
   - audit entry supports `--outline-only` mode
   - audit + extend chapter-wise paths inject OutlineUnit as a Rebuild prior for 30+ chapters
11. ReconcileUnit + AuditReport: complete
   - `src/workflow_action/reconcile.py` merges cross-chapter Rebuild outputs and reports cross-chapter ReviewIssues
   - `src/object_state/audit_report.py` carries the report object
12. Unified novel CLI: complete
   - `src/novel_cli.py` wraps audit / extend / compose into `novel`
   - audit / extend / compose write `route_handoff.json`
   - `novel list` reads and validates `route_handoff.json` when present
   - `novel gate <name>` runs a read-only `OrchestrationGateUnit` check over `route_handoff.json`
   - Review `pass` / `rewrite` / `block` routes are packaged as structured `NextRoute` handoffs
- per-novel workspaces live under `novels/<小说名>/`
- `novel corpus-author-model` supports reusable neutral `Author` instances: deterministic method-layer metrics plus staged selection-pattern evidence; `author_models/` is local and gitignored, and this research artifact is not production authorization
- 隐私纪律：所有具体小说信息（标题/正文/角色/工作区/作者笔名）一律不入 GitHub（见 CLAUDE.md）；写作风格综合积累统一放仓库根 `style_library/<name>.json`

Next focus:
- integrate OutlineUnit as a prior into the long-form audit pipeline (B' slice) - complete
- close residual Phase A items (A3 WorkSpec external hooks, schema-stage validation) - complete
- O3/O5: extend outline injection + rebuild_package outline trace - complete
- O2: audit Reconcile uses outline for structural consistency checks - complete

## Out of Scope for Now
Do not optimize for:
- unsolicited full-system expansion (implement authorized work slice by slice; complete all slices needed for the user's request)
- deployment before deployment shape is decided
- long-form automatic completion
- copying original expression, identity marketing, or publishing corpus-derived private identifiers
- seamless continuation of arbitrary existing novels
- publication-grade prose quality

## Working Principles
- State first, text second.
- Facts must be separated from inference.
- Narrative units must be evaluated by state change.
- Reviewability is more important than polish.
- Prefer clear structure over premature complexity.
- Every generated narrative unit should update state and memory.
- Avoid vague abstractions that cannot be tested with examples.

## Implementation Status

- Slice 1 (`audit_short_form`): code complete, staged Codex flow validated, end-to-end PASS (2026-07-28)
- Slice 2 (`extend_short_form`): code complete, long-form inheritance validated, end-to-end PASS (2026-07-28)
- Slice 3 (`compose_short_form`): code complete, default WorkSpec validated, end-to-end PASS (2026-07-29)
- LLM layer split: workflow units expose `build_prompt()` and `parse_response()`; staged scripts do not call LLMs internally (separate from the A1 automatic path)
- Long-form multi-arc stress test: PASS (2026-07-29 historical evidence)
- No-regression tests: 以 `current_state.json` 为唯一真源（collected / passing / skipped 分离，公开 checkout 的私有资产门控跳过单独计数）。
- End-to-end Audit / Extend / Compose validation: PASS (2026-07-29 historical evidence)

If you are asked to write code, the existing infrastructure is:
- `src/object_state/` - 8 core Pydantic models + `audit_report.py`
- `src/workflow_action/` - RebuildUnit, ContinueUnit, ReviewUnit, RewriteUnit, NarrativeFrameUnit, OutlineUnit, ReconcileUnit
- `src/boundary_control/` - Serialization, Handoff, Validation, `chunking.py`, `report_formatter.py`
- `src/llm_interface.py` - backup interface layer and provider-agnostic DirectAPI contract; distinguish this interface from the A1 adapter in `src/provider_adapter.py` and from permission to run it
- `src/audit_short_form.py` - staged Codex entry script for slice 1 (supports `--range`, `--batch-size`, `--max-chapters`, `--outline-only`)
- `src/extend_short_form.py` - staged Codex entry script for slice 2 (supports `--range`, `--batch-size`, `--max-chapters`)
- `src/compose_short_form.py` - staged Codex entry script for slice 3

Default next action:
- use `novel` as the default runtime entry for staged multi-novel work
- add unsolicited orchestration work only after a new workflow gap appears; continue orchestration work already required by the user's authorized task

## Core Objects
The system is built around these objects:
- WorkSpec
- WorldModel
- CharacterModel
- NarrativeState
- PlotUnit
- FactLedger
- ForeshadowGraph
- ReviewIssue

## Required Design Direction
When drafting new files or refining existing ones:
- define what each object is
- define what it is not
- define what problem it solves
- define how it relates to other objects
- define which fields are hard facts, inferred values, or runtime state

## Review Priorities
When evaluating any narrative design, prioritize:
1. fact consistency
2. character consistency
3. world legality
4. effective progression
5. promise / foreshadow tracking

## PlotUnit Rule
A PlotUnit is only valid if it causes meaningful state change.
If a unit does not change state, it should be treated as non-effective progression.

## State Transition Formula
Input State + Character Decision + World Constraint + Conflict Pressure = Event = Output State

## Expected Output Style
When writing docs for this repo:
- be concise
- be explicit
- prefer bullet structure when it reduces ambiguity
- define terms before using them
- separate concepts, schemas, rules, and workflows
- include small examples when needed

## File Priorities
If new work begins, prioritize these files first:
- README.md
- 00_project/02_agent_quickstart.md
- 00_project/03_current_status.md
- 00_project/04_agent_operating_model.md
- 00_project/05_narrative_agent_harness.md
- 00_project/00_project_brief.md
- 00_project/01_scope_and_boundaries.md
- 07_decisions/08_context_packaging_decisions.md
- 07_decisions/09_review_reminder_decisions.md
- 01_concepts/00_glossary.md
- 01_concepts/05_plotunit.md
- 02_data_models/09_field_rules.md
- 03_rules/01_state_transition_rules.md
- 03_rules/07_review_rules.md
- 05_examples/07_mock_project_case.md

## Decision Policy
If uncertain between elegance and clarity, choose clarity.
If uncertain between more features and tighter boundaries, choose tighter boundaries.
If uncertain between prose discussion and structured definition, choose structured definition.
