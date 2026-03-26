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
- Updated `AGENTS.md` so current phase does not get misread as a permanent no-implementation stance

## Next

- Verify `02_review_workflow.md` and `08_reviewissue_schema.md` stay consistent
- Decide whether `warning / reminder` needs its own lightweight object or only workflow rules
- Revisit broader enum cleanup only if more drift appears in later rule files
