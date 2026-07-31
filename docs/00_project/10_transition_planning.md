# Transition Planning

## Purpose

This file turns the current phase conclusion into an explicit planning entry.

It does not reopen foundation boundary debates.
It defines:

- what transition planning is for
- what it should inherit unchanged
- what it may now plan
- what it must still avoid
- what outputs should exist before implementation work begins

---

## 1. Current Position

The repository is currently:

- foundation gate: `pass`
- transition status: `ready_for_transition_planning`

This means:

- the foundation layer is stable enough to stop default local counterexample expansion
- implementation should still not start directly
- the next task is to plan the handoff from conceptual foundation to implementation planning

---

## 2. What Transition Planning Is

Transition planning is the phase that converts current foundation consensus into:

- inherited constraints
- implementation-planning scope
- deferred topics
- first implementation-planning inputs

It is not:

- implementation
- stack selection
- runtime building
- product design
- a return to local boundary exploration unless a new failure shape appears

---

## 3. What Must Be Inherited Unchanged

Transition planning must inherit these boundary locks unchanged.

### 3.1 Track 1 Lock

- `FactLedger` only records changes that already count in the world
- hard fact cannot be downgraded into prose pressure
- handoff prose cannot replace `FactLedger`

### 3.2 Track 2 Lock

- bounded runtime-first `Rewrite` is only a same-packet local start exception
- it is not an alternate default writeback order
- denser handoff cannot compensate for missing same-packet formal writeback

### 3.3 Track 3 Lock

- `CharacterModel` fields keep long-term compressed conclusions only
- supporting evidence stays in `PlotUnit`, `NarrativeState`, handoff supporting context, and review context
- evidence leakback is a no-regression item

---

## 4. What Transition Planning Should Produce

Transition planning should produce a minimal planning package for the next phase.

### 4.1 Boundary Inheritance Summary

A short file or section that states:

- what implementation planning may not reopen
- which anchor sets must remain in scope
- which residual risks are accepted for now

Current first output:

- `docs/00_project/11_implementation_planning_entry_pack.md`

### 4.2 Implementation-Planning Input List

A clear list of topics that are now allowed to be planned, such as:

- serialization shape
- object storage layout
- runtime orchestration boundaries
- implementation-facing handoff schema

### 4.3 Deferred Topic List

A stable list of topics that still should not shape the design early, such as:

- model selection by hype
- UI-first product decisions
- premature optimization
- publication-grade prose concerns

### 4.4 Phase-Entry Conditions

A small checklist that says when the repo can move from transition planning into implementation planning.

Current first output:

- `docs/00_project/11_implementation_planning_entry_pack.md`

---

## 5. What Transition Planning May Now Discuss

The following topics are now in scope for planning discussion:

- implementation-facing serialization candidates
- storage boundaries between long-term memory, working set, repair state, and confidence state
- runtime orchestration boundaries between `Rebuild`, `Review`, `Continue`, and `Rewrite`
- implementation-facing handoff schema candidates
- testing targets for no-regression locks

These topics must still be discussed through current object and boundary definitions, not by bypassing them.

---

## 6. What Transition Planning Must Still Avoid

Transition planning should still avoid:

- direct code implementation
- choosing concrete models or vendors as if the conceptual layer were already executable
- reopening the eight-core-object set without a new ownership failure
- weakening `FactLedger`, `Rewrite`, or `CharacterModel` boundary locks for convenience
- treating implementation convenience as a reason to collapse memory tiers

---

## 7. Planning Order

The default order for transition planning should be:

1. restate inherited locks
2. define implementation-planning scope
3. define implementation-planning non-goals
4. identify required planning artifacts
5. define phase-entry conditions for implementation planning

This keeps planning attached to current foundation consensus instead of drifting into freeform architecture discussion.

---

## 8. Trigger To Reopen Foundation Work

Transition planning should not reopen foundation work by default.

Only reopen foundation boundary work if:

- a new mixed failure shape appears that current anchor sets cannot explain
- a planning topic directly exposes an unresolved ownership contradiction
- a proposed implementation-facing schema cannot preserve one of the three locks

If none of those conditions applies, planning should continue without adding new local counterexamples.

---

## 9. Done Condition

Transition planning is in good shape when the repository can answer these questions briefly:

1. what implementation planning is allowed to discuss
2. what implementation planning is not allowed to reopen
3. which foundation locks must be inherited unchanged
4. which planning artifacts should be written before implementation starts

---

## 10. One-Sentence Summary

Transition planning is the bridge between stable foundation consensus and future implementation planning, and its job is to carry the current boundary locks forward without reopening them.
