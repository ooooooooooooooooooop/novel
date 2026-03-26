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

- knowledge ownership across `CharacterModel`, `NarrativeState`, and `FactLedger`
- relation ownership across long-term model, current state, and ledger
- whether `warning / reminder` should become its own lightweight object
- what situation changes are important enough to enter `FactLedger`

Do not casually hard-code new assumptions in these areas without checking recent decisions.

---

## 8. Read Next

Read these files next:

1. `docs/00_project/03_current_status.md`
2. `docs/00_project/00_project_brief.md`
3. `docs/00_project/01_scope_and_boundaries.md`
4. `docs/07_decisions/03_workflow_order_decisions.md`

Then go to the specific workflow or schema file relevant to the task.

---

## 9. Default Working Rule

If you are unsure between:

- adding a new abstraction or tightening an existing boundary

choose tighter boundaries first.
