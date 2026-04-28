# Automatic Novel Narrative System

## Project

This repository is building the foundation of an automatic novel narrative system.

The long-term goal is a system that can:

- parse narrative structure
- maintain narrative state
- plan story progression
- review generated results
- support rebuilding, continuation, rewriting, and later implementation work

## Current Phase

The repository is currently in the implementation-planning phase.

Current checkpoint judgment:

- the foundation skeleton is now stable enough for consolidation
- boundary clusters are first-pass stable, not yet implementation-exit stable
- foundation gate status is currently `pass`
- transition-planning sufficiency is currently `pass`
- current planning status is now `implementation_planning_in_progress`
- current next step is now `implementation_planning`

Current work is focused on:

- implementation unit boundaries
- serialization responsibility boundaries
- workflow handoff responsibility boundaries
- orchestration gate boundaries
- no-regression acceptance targets

This does not mean code implementation has started.
It means code implementation is intentionally deferred until implementation responsibilities are bounded enough to support it.

## Core Objects

- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

## Core Judgments

- State first, text second.
- Facts must be separated from inference.
- A `PlotUnit` is only valid if it causes meaningful state change.
- `Review` is the routing hub of the operational workflows.
- Formal `Rewrite` should be issue-driven, not feeling-driven.

## Workflow Map

- `Rebuild`: reconstruct object state from existing text
- `Review`: judge validity, classify failures, and route next action
- `Continue`: generate the next valid progression from current state
- `Rewrite`: apply minimal repair based on formal issues

## Read First

If you are a newly opened agent, read in this order:

1. `AGENTS.md`
2. `docs/00_project/02_agent_quickstart.md`
3. `docs/00_project/03_current_status.md`
4. `docs/00_project/06_foundation_checkpoint.md`
5. `docs/00_project/07_phase_transition_memo.md`
6. `docs/00_project/08_foundation_phase_gate.md`
7. `docs/00_project/09_preimplementation_boundary_lock.md`
8. `docs/00_project/10_transition_planning.md`
9. `docs/00_project/11_implementation_planning_entry_pack.md`
10. `docs/00_project/12_serialization_candidate_note.md`
11. `docs/00_project/13_handoff_schema_candidate_note.md`
12. `docs/00_project/14_runtime_orchestration_boundary_note.md`
13. `docs/00_project/15_no_regression_verification_checklist.md`
14. `docs/00_project/16_implementation_planning.md`
15. `docs/00_project/17_implementation_unit_map.md`
16. `docs/00_project/18_serialization_responsibility_map.md`
17. `docs/00_project/19_workflow_handoff_responsibility_map.md`
18. `docs/00_project/20_orchestration_gate_map.md`
19. `docs/00_project/21_no_regression_acceptance_test_list.md`
20. `docs/00_project/04_agent_operating_model.md`
21. `docs/00_project/05_narrative_agent_harness.md`
22. `docs/00_project/00_project_brief.md`
23. `docs/00_project/01_scope_and_boundaries.md`
24. `docs/07_decisions/03_workflow_order_decisions.md`
25. `docs/07_decisions/08_context_packaging_decisions.md`
26. `docs/07_decisions/09_review_reminder_decisions.md`
27. `docs/07_decisions/10_ownership_matrix_decisions.md`
28. `docs/07_decisions/11_reviewreminder_escalation_matrix.md`
29. `docs/07_decisions/12_concurrent_reminder_routing_decisions.md`
30. `docs/07_decisions/13_factledger_admission_thresholds.md`

## Current Repository Shape

At the moment, the repository is mainly a design and documentation workspace.
That is a current-state description, not a permanent restriction on later phases.
