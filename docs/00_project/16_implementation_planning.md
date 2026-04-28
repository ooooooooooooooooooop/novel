# Implementation Planning

## Purpose

This file opens the implementation-planning phase.

It uses the completed transition-planning set as bounded input.
It does not start implementation.

It defines:

- what implementation planning is allowed to decide
- what it must inherit unchanged
- what it must still defer
- what outputs should exist before code-level implementation begins

---

## 1. Current Position

The repository is currently:

- foundation gate: `pass`
- transition-planning sufficiency: `pass`
- implementation-planning status: `in_progress`

This means:

- the foundation layer is stable enough to stop default local counterexample expansion
- the transition-planning set is sufficient as a bounded input package
- the next task is to convert planning boundaries into implementation-facing plans
- code implementation should still wait for a bounded implementation plan

---

## 2. Input Package

Implementation planning starts from these documents.

### 2.1 Phase And Boundary Inputs

- `docs/00_project/10_transition_planning.md`
- `docs/00_project/11_implementation_planning_entry_pack.md`
- `docs/00_project/15_no_regression_verification_checklist.md`

### 2.2 Candidate Artifact Inputs

- `docs/00_project/12_serialization_candidate_note.md`
- `docs/00_project/13_handoff_schema_candidate_note.md`
- `docs/00_project/14_runtime_orchestration_boundary_note.md`

### 2.3 Foundation Lock Inputs

- `docs/00_project/09_preimplementation_boundary_lock.md`
- `docs/07_decisions/08_context_packaging_decisions.md`
- `docs/07_decisions/09_review_reminder_decisions.md`
- `docs/07_decisions/10_ownership_matrix_decisions.md`
- `docs/07_decisions/13_factledger_admission_thresholds.md`

---

## 3. What Implementation Planning Is

Implementation planning is the phase that converts current design boundaries into:

- candidate implementation units
- object serialization responsibilities
- workflow handoff responsibilities
- orchestration responsibilities
- validation targets for no-regression behavior

It should make future implementation smaller and safer.

It should not make implementation decisions by hiding unresolved boundary questions inside code structure.

---

## 4. What Implementation Planning Is Not

Implementation planning is not:

- full implementation
- product workflow design
- model or vendor selection
- deployment planning
- runtime performance optimization
- publication-quality prose planning
- a new foundation-reopening phase

If one of these topics appears, it should be accepted only when needed to define an implementation boundary.

---

## 5. Required Inheritance

Implementation planning must inherit these locks unchanged.

### 5.1 Track 1 Lock

- `FactLedger` records only hard facts that already count in the world
- working pressure, suspicion, and unresolved inference stay out of hard-fact storage
- richer handoff prose cannot substitute for object-layer truth

### 5.2 Track 2 Lock

- bounded runtime-first `Rewrite` remains a same-packet local start exception
- formal writeback is required before the packet can move forward
- handoff density cannot compensate for incomplete same-packet synchronization

### 5.3 Track 3 Lock

- `CharacterModel` fields keep compressed long-term conclusions only
- supporting evidence stays outside field bodies
- handoff risk cannot be solved by broadening role-side summaries

---

## 6. Allowed Planning Topics

Implementation planning may now discuss:

- serialization shape for the existing object set
- handoff packet structure between existing workflows
- orchestration boundaries for `Rebuild`, `Continue`, `Review`, and `Rewrite`
- validation targets for lock-sensitive behavior
- minimal implementation units that preserve object ownership
- example-backed acceptance checks for future code

All discussion must stay anchored to existing objects, workflows, and locks.

---

## 7. Deferred Topics

Implementation planning should still defer:

- final storage backend choice
- programming language or framework choice
- model routing or prompt infrastructure
- UI and product workflow
- performance tuning
- long-form generation automation

These topics can be named as future constraints, but they should not drive current structure.

---

## 8. First Planning Outputs

The first implementation-planning outputs should be small and bounded.

Recommended outputs:

1. implementation unit map: `docs/00_project/17_implementation_unit_map.md`
2. serialization responsibility map: `docs/00_project/18_serialization_responsibility_map.md`
3. workflow handoff responsibility map: `docs/00_project/19_workflow_handoff_responsibility_map.md`
4. orchestration gate map: `docs/00_project/20_orchestration_gate_map.md`
5. no-regression acceptance test list: `docs/00_project/21_no_regression_acceptance_test_list.md`

These outputs should describe what future implementation must preserve before describing how code should be written.

---

## 9. Reopen Trigger

Do not reopen foundation work by default.

Reopen foundation only if implementation planning exposes:

- a new mixed failure shape current anchors cannot explain
- an ownership contradiction between core objects
- a candidate plan that cannot preserve Track 1, Track 2, or Track 3
- a workflow route that cannot be represented without weakening existing rules

If none of these appear, continue planning forward.

---

## 10. Exit Conditions

Implementation planning is sufficient when the repo has:

- a bounded map of implementation units
- a clear serialization responsibility split
- a clear handoff responsibility split
- a clear orchestration gate split
- no-regression checks tied to the three inherited locks
- no unresolved foundation-level contradiction

Passing this phase means implementation may begin in a bounded way.
It does not mean every future implementation detail has been decided.

---

## 11. One-Sentence Summary


Implementation planning converts the completed transition-planning package into bounded implementation responsibilities while preserving the foundation locks unchanged.
