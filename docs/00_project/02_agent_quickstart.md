# Agent Quickstart

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

This repository is building the conceptual foundation of a narrative operating system for novels.

---

## 2. Current Phase

The current phase is foundation design.

That means:

- define concepts
- define schemas
- define rules
- define minimal workflows
- validate them with examples and decisions

That does not mean:

- the repository will never include implementation
- implementation is rejected as a future direction

The actual boundary is:

- do not optimize for implementation now
- do not let implementation pressure distort the foundation

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

---

## 7. Current Fragile Boundaries

The following boundaries still need extra care:

- long-chain validation of `FactLedger` admission thresholds
- bounded runtime-first `Rewrite` exception still needs more counterexample coverage so it cannot drift into a cross-handoff shortcut
- `CharacterModel` field-level keep-vs-drop direction is now first-pass visible across knowledge, relation, misinformation, self-image, and arc-stage cases, but still needs cross-field long-chain coverage so these boundaries do not collapse when they interact

Do not casually hard-code new assumptions in these areas without checking recent decisions.

Default near-term plan:

1. extend repeated `degradation -> rebuild -> review -> continue` pressure tests so `FactLedger` thresholds are checked across longer mixed knowledge / relation / situation chains instead of one-off recoveries
   Current anchors: `docs/05_examples/23_mixed_threshold_recovery_chain.md`, `docs/05_examples/24_second_recovery_handoff_split.md`, and `docs/05_examples/29_three_track_convergence_pressure_test.md`
2. add explicit negative `Rewrite` counterexamples so the bounded runtime-first exception stays limited to local root-cause repair and cannot be misread as an alternate default writeback order
   Current anchors: `docs/05_examples/17_local_rewrite_writeback_exception.md`, `docs/05_examples/25_rewrite_exception_misuse_chain.md`, and `docs/05_examples/29_three_track_convergence_pressure_test.md`
3. add a cross-field `CharacterModel` recovery case that forces keep-vs-drop judgments across `knowledge_state`, `relations`, `misinformation`, `self_image`, and `arc_stage` in one loop
   Current anchors: `docs/05_examples/26_charactermodel_cross_field_recovery.md`, `docs/05_examples/27_charactermodel_rollback_misinformation.md`, `docs/05_examples/28_charactermodel_supporting_evidence_leakback.md`, and `docs/05_examples/29_three_track_convergence_pressure_test.md`
   Near-term focus: prefer a foundation checkpoint / exit-criteria review unless a new mixed-loop failure appears that `29` still cannot explain

Current checkpoint judgment:

- foundation skeleton: stable
- boundary clusters: first-pass stable
- phase exit: not yet
- default next action: checkpoint / transition judgment, not reflexive local-example expansion

Current transition judgment:

- transition status: `ready_for_transition_planning`
- accepted for now: no second convergence family yet, no final machine format yet
- must inherit unchanged in implementation planning: Track 1 lock, Track 2 lock, Track 3 lock
- default next action: transition planning, not implementation start

Current gate judgment:

- gate status: `pass`
- passed: skeleton, object set, workflow loop, example/rule/decision alignment, and pre-implementation boundary lock
- default next action: transition planning, not reflexive local-example expansion

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
12. `docs/00_project/04_agent_operating_model.md`
13. `docs/00_project/05_narrative_agent_harness.md`
14. `docs/00_project/00_project_brief.md`
15. `docs/00_project/01_scope_and_boundaries.md`
16. `docs/07_decisions/03_workflow_order_decisions.md`
17. `docs/07_decisions/08_context_packaging_decisions.md`
18. `docs/07_decisions/10_ownership_matrix_decisions.md`
19. `docs/07_decisions/11_reviewreminder_escalation_matrix.md`
20. `docs/07_decisions/12_concurrent_reminder_routing_decisions.md`
21. `docs/07_decisions/13_factledger_admission_thresholds.md`

Then go to the specific workflow or schema file relevant to the task.

---

## 9. Default Working Rule

If you are unsure between:

- adding a new abstraction or tightening an existing boundary

choose tighter boundaries first.
