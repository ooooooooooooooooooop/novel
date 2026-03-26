# Current Status

## Purpose

This file gives a newly opened agent a fast snapshot of what is already done, what is still unstable, and what work is most reasonable next.

Update this file after each meaningful round of project-shaping work.

---

## 1. Current State

The repository is currently a foundation-design workspace.

At this stage it is mainly documentation and design decisions.
This is a phase description, not a permanent restriction on future implementation.

---

## 2. What Is Already Built

The repository already has a coherent first-pass foundation for:

- project scope and boundaries
- core concepts
- core object schemas
- state transition rules
- review rules
- minimal workflows
- examples and decision logs

The project is no longer at the "empty idea" stage.

---

## 3. Recent Alignment Work

Recent work has tightened consistency in these areas:

- workflow-order decisions were consolidated
- `Continue` writeback order was made explicit
- `Rewrite` synchronization order was made explicit
- `Review` routing thresholds for `warning`, `Rewrite`, and `Replan` were tightened
- `ReviewIssue` schema was aligned with issue and fix types used by the rule layer

---

## 4. Current Stable Judgments

Treat the following as current project consensus:

- state first, text second
- `PlotUnit` must cause meaningful state change
- `Review` is the routing hub
- `Continue` should not skip `Review`
- formal `Rewrite` should be issue-driven
- current work should optimize for clarity and reviewability before implementation

---

## 5. Current Unresolved Boundaries

The most important unresolved boundaries are:

- knowledge ownership across `CharacterModel`, `NarrativeState`, and `FactLedger`
- relation ownership across long-term model, runtime state, and fact ledger
- whether `warning / reminder` should be formalized as a lightweight object
- what situation changes qualify for `FactLedger` entry

These are the areas most likely to create drift if future edits are made casually.

---

## 6. Recommended Next Work

The most reasonable next steps are:

1. decide whether `warning / reminder` needs a dedicated lightweight object
2. keep workflow, rules, and schema enums synchronized
3. pressure-test the current boundaries with more counterexamples and mock cases
4. avoid expanding object count unless a real responsibility gap is proven

---

## 7. Read After This

If you need a fuller picture, read:

1. `docs/00_project/00_project_brief.md`
2. `docs/00_project/01_scope_and_boundaries.md`
3. `docs/07_decisions/03_workflow_order_decisions.md`
4. the workflow or schema file directly related to the task you were asked to do
