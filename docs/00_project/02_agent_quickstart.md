# Agent Quickstart

<!-- state:current -->
**当前状态（唯一机器真源：`current_state.json`）**：默认标记 `CURRENT_HEAD_UNVERIFIED`——
任何提交的验证资格不自动延续；attestation 记录（subject_commit / results / canary /
last_validated_commit）以 json 为准。本区块禁止出现数字声明与历史资格。
<!-- /state:current -->

## Purpose

This file is the fastest onboarding entry for a newly opened agent.

It should answer:

- what this repository is
- what phase it is in now
- what is already stable
- what should not be assumed
- where to read next

---

## 1. One-Sentence Definition

This repository is building the conceptual foundation and first running slices of a narrative operating system for novels.

---

## 2. Current Phase

The historical phase (2026-07-28 validation) was **end-to-end validated, Codex-native orchestration**; current qualification lives only in `current_state.json`.

All three running slices are code-complete and validated:

- `audit_short_form`: Rebuild + Review
- `extend_short_form`: Rebuild + Continue + Review
- `compose_short_form`: WorkSpec + Initialize + Continue + Review

The LLM layer has been split out of workflow units:

- workflow units expose `build_prompt()` and `parse_response()`
- entry scripts write prompt files, wait for Codex-authored response files, and continue on rerun
- `src/llm_interface.py` remains a backup interface layer
- DirectAPI has a provider-agnostic interface contract, pending response-slot discovery, and staged response runner; provider calls remain unimplemented

Validation status:

- foundation gate: `pass`
- transition-planning sufficiency: `pass`
- implementation-planning sufficiency: `pass`
- long-form multi-arc stress test: PASS
- no-regression tests as code: 以 `current_state.json` 为唯一真源（机器生成）
- end-to-end Audit / Extend / Compose validation: PASS (2026-07-28)

That means:

- the repo has a running implementation layer
- Codex is the current orchestration surface
- usage is staged prompt / response / rerun, not single-run automatic completion

That does not mean:

- DirectAPI provider calls or closed-loop automation are implemented
- any deployment shape beyond local staged CLI v0 is decided
- long-form automatic completion is in scope

---

## 3. Core Objects

The system is built around:

- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

If a task introduces new concepts, check first whether one of these objects should already own that responsibility.

---

## 4. Core Judgments

- `NarrativeState` is the first-class runtime object, not raw text.
- `PlotUnit` is valid only when it causes meaningful state change.
- Facts must be kept separate from inference and commentary.
- Reviewability is more important than polish.
- Workflow order matters more than local elegance.

---

## 5. Workflow Judgments

- `Rebuild` comes before `Continue` when current state is unclear.
- `Review` is the workflow hub.
- `Continue` should not skip `Review`.
- `Rewrite` should be driven by formal issue objects.
- `warning` can remain in the progression chain for a while, but must upgrade when threshold conditions are met.

---

## 6. What Is Stable Enough To Reuse

The following direction is already stable enough to treat as current project consensus:

- the eight core objects
- state-first framing
- `PlotUnit` as state-change unit
- `Review` as routing hub
- fixed writeback order decisions for `Continue` and `Rewrite`
- staged Codex orchestration for the three current entry scripts
- Track 1 / 2 / 3 no-regression locks as executable pytest checks

---

## 7. Current Fragile Boundaries

The following boundaries still need care:

- DirectAPI has a provider-agnostic interface contract, but provider calls and closed-loop automation remain unimplemented
- deployment shape is decided for v0 as Codex-native staged CLI
- OrchestrationGateUnit exists as a minimal route gate. It is exposed through
  read-only `novel gate <name>`, but it is not an automatic closed-loop runner
- DirectAPI, UI, and fully automatic closed-loop calls remain deferred
- Phase B domain layer deepening (B1/B2/B3): complete
- Phase B4 long-range orchestration: adopted as NarrativeFrameUnit; implementation in `src/workflow_action/frame.py`
- `RewriteUnit` is code-complete for build_prompt / parse_response / apply_fix and integrated into all three entry scripts
- compose-mode initialization is domain-derived, but full long-form automatic completion remains out of scope
- long-form audit sub-modules (chunking, reconcile, audit_report) are wired into `audit_short_form.py` chapter-wise path and covered by end-to-end integration tests; OutlineUnit is integrated as a prior in long-form audit and extend paths, with `--outline-only` still available as an isolated structure-overview mode

Default next action:

1. harden the Codex-native staged CLI v0 runtime contract.
2. Keep run outputs isolated with `--output-dir`.
3. DirectAPI design only after the staged CLI file/state contract is stable.

---

## 8. Read Next

Read these files next:

1. `docs/00_project/03_current_status.md`
2. `docs/00_project/06_foundation_checkpoint.md`
3. `docs/00_project/07_phase_transition_memo.md`
4. `docs/00_project/08_foundation_phase_gate.md`
5. `docs/00_project/09_preimplementation_boundary_lock.md`
6. `docs/00_project/10_transition_planning.md`
7. `docs/00_project/11_implementation_planning_entry_pack.md`
8. `docs/00_project/12_serialization_candidate_note.md`
9. `docs/00_project/13_handoff_schema_candidate_note.md`
10. `docs/00_project/14_runtime_orchestration_boundary_note.md`
11. `docs/00_project/15_no_regression_verification_checklist.md`
12. `docs/00_project/16_implementation_planning.md`
13. `docs/00_project/17_implementation_unit_map.md`
14. `docs/00_project/18_serialization_responsibility_map.md`
15. `docs/00_project/19_workflow_handoff_responsibility_map.md`
16. `docs/00_project/20_orchestration_gate_map.md`
17. `docs/00_project/21_no_regression_acceptance_test_list.md`
18. `docs/00_project/22_usage_oriented_roadmap.md`
19. `docs/00_project/23_open_threads.md`
20. `docs/00_project/27_deployment_shape_decision.md`
21. `src/audit_short_form.py`
22. `src/extend_short_form.py`
23. `src/compose_short_form.py`
24. `tests/test_no_regression.py`
25. `docs/04_workflows/10_style_modeling_workflow.md`（写作风格建模 SOP：compose/extend 前建风格档案，12 必填 + 4 可选 v2 质性字段）

Then go to the specific workflow or schema file relevant to the task.

---

## 9. Default Working Rule

If you are unsure between:

- adding a new abstraction or tightening an existing boundary

choose tighter boundaries first.
