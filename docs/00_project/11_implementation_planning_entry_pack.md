# Implementation-Planning Entry Pack

## Purpose

This file is the first bounded output of transition planning.

It packages four things for future implementation planning:

- boundary inheritance summary
- implementation-planning input list
- deferred-topic list
- phase-entry conditions

It does not start implementation.
It prepares a bounded entry into implementation planning.

---

## 1. Boundary Inheritance Summary

Implementation planning may proceed only if the following conclusions are inherited unchanged.

### 1.1 Track 1 Inheritance

- `FactLedger` records only changes that already count in the world
- hard fact may not be downgraded into prose pressure
- handoff prose may not replace `FactLedger` writeback
- current minimum anchor set: `23`, `24`, `29`

### 1.2 Track 2 Inheritance

- bounded runtime-first `Rewrite` is only a same-packet local start exception
- it may not become an alternate default writeback order
- denser handoff may not compensate for missing same-packet formal sync
- current minimum anchor set: `17`, `25`, `29`

### 1.3 Track 3 Inheritance

- `CharacterModel` fields keep long-term compressed conclusions only
- supporting evidence stays outside `CharacterModel` field bodies
- evidence leakback is a no-regression item
- current minimum anchor set: `26`, `27`, `28`, `29`

### 1.4 Accepted-For-Now Residual Risk

Implementation planning may inherit these as accepted-for-now conditions, not as solved problems:

- no second independent convergence family yet
- no final machine-executable serialization format yet
- no implementation-level harness orchestration design yet

---

## 2. Implementation-Planning Input List

The following topics are now valid inputs to implementation planning.

### 2.1 Serialization Candidates

Plan candidate shapes for:

- object-level storage boundaries
- workflow handoff payloads
- stable-memory vs working-set serialization splits

### 2.2 Storage Layout Boundaries

Plan how implementation should separate:

- long-term stable memory
- current working state
- repair / issue state
- confidence / completeness state

### 2.3 Runtime Orchestration Boundaries

Plan implementation-facing boundaries for:

- `Rebuild`
- `Review`
- `Continue`
- `Rewrite`

The goal is to preserve current workflow contracts, not redesign them from scratch.

### 2.4 No-Regression Verification Targets

Plan implementation checks that can detect regression on:

- `FactLedger` substitution by prose or working-state pressure
- `Rewrite` packet incompleteness hidden by handoff density
- `CharacterModel` evidence leakback

---

## 3. Deferred-Topic List

The following topics remain deferred and should not shape implementation planning too early.

### 3.1 Technology Choice As Premature Driver

Do not let:

- model hype
- vendor preference
- framework familiarity

reshape current object and workflow boundaries.

### 3.2 UI And Product Workflow

Do not let:

- product screens
- interaction flows
- user-facing convenience

become the main driver of memory-tier collapse or workflow shortcutting.

### 3.3 Performance And Automation Detail

Do not optimize early for:

- throughput
- latency
- scheduling detail
- automation breadth

before the implementation-facing contract layer is stable.

### 3.4 Prose-Quality And Publication Concerns

Do not let:

- stylistic polish
- market positioning
- publication-grade output goals

pull planning away from state, memory, review, and repair interfaces.

---

## 4. Phase-Entry Conditions

The repository is ready to enter implementation planning when the following conditions hold.

### 4.1 Planning Scope Is Bounded

The repo can state clearly:

- what implementation planning may discuss
- what it may not reopen

### 4.2 Inherited Locks Are Visible

Track 1, Track 2, and Track 3 locks are visible in the planning entry path and not only buried in older documents.

### 4.3 First Implementation-Facing Artifact Targets Are Named

At minimum, the repo has named targets for:

- serialization candidates
- handoff schema candidates
- runtime orchestration boundaries
- no-regression verification targets

### 4.4 Reopen Trigger Remains Narrow

The repo still treats new foundation work as exception-only.

Reopen foundation only if:

- a new mixed failure shape appears
- an ownership contradiction is exposed by planning
- a planning candidate cannot preserve one of the three locks

---

## 5. Recommended Immediate Next Outputs

After this entry pack, the most reasonable next outputs are:

1. an implementation-facing serialization candidate note
2. an implementation-facing handoff schema note
3. a runtime orchestration boundary note
4. a no-regression verification checklist

These should remain planning artifacts, not implementation artifacts.

Current first follow-up output:

- `docs/00_project/12_serialization_candidate_note.md`
- `docs/00_project/13_handoff_schema_candidate_note.md`
- `docs/00_project/14_runtime_orchestration_boundary_note.md`
- `docs/00_project/15_no_regression_verification_checklist.md`

---

## 6. One-Sentence Summary

This entry pack defines the minimum bounded input that future implementation planning should start from, without reopening foundation consensus.
