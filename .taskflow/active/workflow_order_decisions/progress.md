# workflow_order_decisions

## Goal

Tighten workflow-order decisions for the foundation phase, with emphasis on:

- workflow routing order
- object writeback order
- conflict-precedence rules

## Progress

- Reviewed existing `07_decisions/03_workflow_order_decisions.md`
- Rewrote the document around fixed routing and synchronization order
- Added explicit decisions for:
  - `Continue` writeback order
  - `Rewrite` synchronization order
  - object conflict precedence
- Cross-checked `04_workflows/02_review_workflow.md` against the new routing rules
- Aligned `08_reviewissue_schema.md` with rule/workflow enums that had drifted
- Added onboarding entry files for new agents:
  - `README.md`
  - `docs/00_project/02_agent_quickstart.md`
  - `docs/00_project/03_current_status.md`
- Added `docs/00_project/04_agent_operating_model.md` to define how agents should onboard, update context, and avoid drift
- Added `docs/00_project/05_narrative_agent_harness.md` to translate the agent-harness perspective into current design guidance
- Updated `AGENTS.md` so current phase does not get misread as a permanent no-implementation stance
- Added explicit context-package guidance to:
  - `docs/04_workflows/01_rebuild_workflow.md`
  - `docs/04_workflows/03_continue_workflow.md`
  - `docs/04_workflows/02_review_workflow.md`
  - `docs/04_workflows/04_rewrite_workflow.md`
  - `docs/02_data_models/09_field_rules.md`
- Added `docs/07_decisions/08_context_packaging_decisions.md` to promote context packaging from workflow-local guidance into project-level decision consensus
- Added `ReviewReminder` as a lightweight review-layer object:
  - `docs/01_concepts/09_reviewreminder.md`
  - `docs/02_data_models/10_reviewreminder_schema.md`
  - `docs/07_decisions/09_review_reminder_decisions.md`
- Wired `ReviewReminder` into review, continue, rewrite, example, and onboarding/status docs
- Added `docs/05_examples/08_reviewreminder_chain.md` to pressure-test the chain:
  - `Review -> Continue -> Review -> escalation`
  - reminder active-window tracking
  - reminder-to-issue upgrade path
- Added `docs/05_examples/09_mixed_review_routing.md` to pressure-test mixed routing:
  - active reminder + new formal issue
  - `Rewrite` routing without premature `Replan`
  - reminder retention across local repair decisions
- Added `docs/05_examples/10_structural_replan_routing.md` to pressure-test structural routing:
  - multiple formal issues with shared structural weakness
  - `Replan` routing instead of repeated local rewrite
  - distinction between issue count and structural failure
- Added `docs/05_examples/11_cross_arc_rebuild_recovery.md` to pressure-test long-context recovery:
  - bounded package insufficiency
  - `Rebuild` as recovery/compiler step
  - recovery into runnable state plus uncertainty package

## Next

- Verify `02_review_workflow.md` and `08_reviewissue_schema.md` stay consistent
- Pressure-test `ReviewReminder` thresholds and escalation windows with multi-round examples
- Extend from single-reminder chains to concurrent reminder chains and mixed reminder/issue chains
- Extend from multi-issue structural `Replan` cases to longer cross-arc degradation and rebuild-recovery cases
- Extend from single recovery cases to repeated degradation / rebuild / continue loops
- Revisit broader enum cleanup only if more drift appears in later rule files
- Add harness-oriented pressure-test examples for context loss and rebuild recovery
