# AGENTS.md

## Project

<!-- state:current -->
**当前状态（唯一机器真源：`current_state.json`）**：默认标记 `CURRENT_HEAD_UNVERIFIED`——
任何提交的验证资格不自动延续；attestation 记录（subject_commit / results / canary /
last_validated_commit）以 json 为准。本区块禁止出现数字声明与历史资格。
<!-- /state:current -->
Automatic Novel Narrative System

## Current Status Pointer (2026-08-29)

- 当前状态唯一权威入口：`docs/00_project/03_current_status.md` §0（§0.7 为 S6/S7 真机终态）。
- 大神级升级计划：`docs/00_project/52_mastery_upgrade_plan.md`（P0–P7）；总目标执行计划：`docs/00_project/54_master_goal_execution_plan.md`（S1–S7，确定性层已全部落地）。
- **S6 90 章无人 Canary certified（90/90，2026-08-28）**；S7 七指标合取 **3 绿 / 4 红 → `long_run_not_authorized`**——A1 仍未获生产资格；缺口闭环 prospective5 因上游 `gemini-3.7-flash-high` 503 停摆（外部故障，非代码）。
- G7 自动审美资格失败、已退役为研究性子能力（失败记录不可变）。
- 测试基线：状态真源：以仓库根 `current_state.json`（机器生成，`scripts/generate_current_state.py`）为唯一权威——记录 collected / passing / skipped / canary / 验证资格与 validation_timestamp。公开 checkout 缺运营侧私有资产时，依赖资产的测试显式跳过（原因机器可读），不宣称无条件全绿。

## Current Phase
Current Phase: S7 缺口闭环（prospective5 死锁定格，待用户决策，见 runtime 侧战役日志）。Tier 0 判定是历史 checkpoint（2026-07-28 首判、2026-08-06 重认证，tag `v0.1.2-tier0`），不自动延续到当前 HEAD；当前验证资格以 `current_state.json` 为唯一真源。三个实现切片（audit/extend/compose）代码完成，各自曾有真实 staged Codex canary 通过 `novel gate`（历史证据）。
Foundation gate, transition-planning sufficiency, and implementation-planning sufficiency have passed.
v0 deployment shape decision (Codex-native staged CLI) is adopted.
This is a phase boundary, not a permanent repository boundary.

Tier 0 production evidence:

- production tier: `local staged CLI v0` (operator-in-the-loop, no DirectAPI)
- release record: `docs/00_project/releases/tier0-release.json` (passes the single combined validation command at the current full-pytest baseline 2940)
- canary evidence: `docs/00_project/releases/tier0-canary-evidence.json`
- saved canary gate result: `docs/00_project/releases/tier0-canary-gate.json`
- immutable checkpoint: git tag `v0.1.2-tier0`

Three-flow hardening evidence (2026-07-29, re-certified under `v0.1.2-tier0` on 2026-08-06):

- extend and compose canaries each passed `novel gate`; per-flow gate results: `tier0-extend-canary-gate.json`, `tier0-compose-canary-gate.json`
- three-flow aggregation evidence: `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- operator runbook: `docs/00_project/35_operator_runbook.md`; hardening plan: `docs/00_project/34_tier0_daily_production_hardening_plan.md`
- regression gate: `python scripts/tier0_canary_regression.py` (exit 0 ⇒ three-flow baseline not regressed)

Tier 0 boundaries that remain in force:

- DirectAPI provider calling is not implemented
- closed-loop automation remains disallowed
- Tier 0 is not a public product surface
- release record does not replace a release tag or immutable checkpoint
- response files must be materialized by the operator or Codex; no automatic model call is performed

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
- full implementation (proceed slice by slice)
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

- Slice 1 (`audit_short_form`): code complete, staged Codex flow validated, end-to-end PASS
- Slice 2 (`extend_short_form`): code complete, long-form inheritance validated, end-to-end PASS
- Slice 3 (`compose_short_form`): code complete, default WorkSpec validated, end-to-end PASS
- LLM layer split: workflow units expose `build_prompt()` and `parse_response()`; scripts do not call LLMs internally
- Long-form multi-arc stress test: PASS
- No-regression tests: 以 `current_state.json` 为唯一真源（collected / passing / skipped 分离，公开 checkout 的私有资产门控跳过单独计数）。
- End-to-end Audit / Extend / Compose validation: PASS

If you are asked to write code, the existing infrastructure is:
- `src/object_state/` - 8 core Pydantic models + `audit_report.py`
- `src/workflow_action/` - RebuildUnit, ContinueUnit, ReviewUnit, RewriteUnit, NarrativeFrameUnit, OutlineUnit, ReconcileUnit
- `src/boundary_control/` - Serialization, Handoff, Validation, `chunking.py`, `report_formatter.py`
- `src/llm_interface.py` - backup interface layer; DirectAPI has a provider-agnostic interface contract, but provider calls remain unimplemented
- `src/audit_short_form.py` - staged Codex entry script for slice 1 (supports `--range`, `--batch-size`, `--max-chapters`, `--outline-only`)
- `src/extend_short_form.py` - staged Codex entry script for slice 2 (supports `--range`, `--batch-size`, `--max-chapters`)
- `src/compose_short_form.py` - staged Codex entry script for slice 3

Default next action:
- use `novel` as the default runtime entry for staged multi-novel work
- decide the next orchestration follow-up only after a new workflow gap appears

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
