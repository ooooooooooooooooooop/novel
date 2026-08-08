# Current Status

## Purpose

This file gives a newly opened agent a fast snapshot of what is already done, what is still unstable, and what work is most reasonable next.

Update this file after each meaningful round of project-shaping work.

---

## 1. Current State

The repository is currently **end_to_end_validated** and **Tier 0 production ready — three-flow daily-production hardened**.

Tier 0 (local staged CLI v0, operator-in-the-loop) was validated on 2026-07-28:

- full pytest baseline: 2203 tests passing
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
- **evidence caveat**: the extend/compose canary workspaces were generated under a gate contract that predates the Phase 5 serialization-package requirement (`31fc12a`); as committed they contain no `extend_rebuild_package.json` / `compose_state.json`, so `novel gate` now reports `ContinueUnit requires a serialization package` for those two workspaces and `python scripts/tier0_canary_regression.py` reports FAIL for extend/compose (audit passes). The committed per-flow gate JSONs and the aggregation `final_gate_ok` for extend/compose predate this and no longer reflect the current gate contract. Regeneration under the current contract is a pending operator task (see Known limitations below).

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
- extend/compose canary evidence predates the Phase 5 gate package requirement (`31fc12a`) and lacks `extend_rebuild_package.json` / `compose_state.json`; `novel gate` on those workspaces reports a serialization-package violation and `python scripts/tier0_canary_regression.py` reports FAIL for extend/compose (audit canary still passes). Regenerating that evidence under the current gate contract is a pending operator task and does not affect the Tier 0 release record (whose canary evidence is the audit canary).

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

- `pytest -q`: 2203 tests passing
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
  - total validation baseline: 2203 tests passing
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
