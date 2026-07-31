# Phase A Execution Plan

## Status

- Decision: `adopted-as-supplement`
- Relation to official planning chain: supplement, not replacement
- Path: C (parallel Phase A + bounded implementation slice selection)

## Purpose

Execute a trimmed Phase A from the usage-oriented roadmap (doc 22) in parallel with bounded implementation slice selection.

## Scope Boundary

### In Scope

- A1: Make three flow entry modes explicit (audit / extend / compose terminology index)
- A4: Add end-to-end usage walkthroughs (audit first, extend second, compose deferred)
- Parallel track: bounded implementation slice selection analysis

### Out of Scope

- A2: `generative_indicia` failure type (deferred to Phase A late or Phase B)
- A3: `WorkSpec` external input hooks (deferred to schema-stage validation trigger)
- Code implementation (still deferred until slice selection completes)
- Modifying core objects, workflows, or Track 1/2/3 locks (explicitly forbidden)

## Task Priority

1. **P0**: A1 terminology index — `04_workflows/06_usage_modes.md` (new file, terminology only)
2. **P0**: Compose-mode stub in `01_rebuild_workflow.md` (new section)
3. **P1**: A4 audit walkthrough — reuse `示例小说甲` mock case
4. **P1**: A4 extend walkthrough — reuse `示例小说甲` mock case
5. **P1**: Bounded implementation slice selection analysis
6. **P2**: A4 compose walkthrough (deferrable per DEC-22)
7. **P3**: A2 `generative_indicia` (deferred)
8. **P3**: A3 `WorkSpec` external hooks (deferred)

## Parallel Track Rules

- Phase A tasks must not block slice selection
- Slice selection must not require Phase A completion
- Both tracks feed into the same decision: what is the first bounded implementation slice

## Exit Conditions

Phase A is complete when:
- audit and extend entry modes are documented in unified terminology
- compose entry mode has a documented stub form
- at least audit and extend walkthroughs exist
- bounded implementation slice selection has a recommended candidate
- Track 1, Track 2, Track 3 unchanged
- no new core object added

## Relation to Existing Documents

- docs 11-21 remain authoritative for implementation-planning artifacts
- doc 22 remains the source roadmap, this file is the execution plan derived from it
- doc 23 tracks any new open threads surfaced during execution
