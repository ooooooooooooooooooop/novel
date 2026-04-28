# Handoff Schema Candidate Note

## Purpose

This file is an implementation-planning note for workflow handoff schema shape.

It does not define the final transport contract.
It defines a first candidate structure that preserves:

- current handoff contract semantics
- memory-tier separation
- workflow routing clarity
- same-packet synchronization requirements

---

## 1. Handoff Schema Goal

The goal is not to make handoff payloads look formal.

The goal is to ensure that a later implementation-facing handoff:

- exposes what changed
- exposes what remains open
- does not hide stale object state behind prose density
- stays aligned with serialization boundaries

One sentence:

handoff schema must make re-inference smaller, not just make prose longer.

---

## 2. Candidate Relationship To Serialization Shape

The current serialization candidate uses four top-level layers:

- `stable_memory`
- `working_set`
- `repair_control`
- `confidence`

The first handoff schema candidate should not duplicate those entire layers.
It should reference them selectively and expose delta-oriented information.

Recommended relationship:

- handoff payload references stable serialized state
- handoff payload highlights changed working-state and repair-control items
- handoff payload carries confidence and gap markers explicitly

This keeps handoff light enough to be operational while still preserving object-layer truth.

---

## 3. Candidate Top-Level Handoff Shape

Current first candidate shape:

1. `handoff_header`
2. `input_anchor`
3. `output_anchor`
4. `change_set`
5. `open_items`
6. `confidence_and_gaps`
7. `next_route`

This follows the current shared handoff contract and should remain the default planning direction.

---

## 4. Candidate Section Rules

### 4.1 `handoff_header`

Should identify:

- workflow name
- handoff id
- round / packet identity
- generation stage

It should answer:

- what handoff is this
- from which workflow stage did it come

### 4.2 `input_anchor`

Should identify:

- the primary input object or state
- required supporting refs
- input completeness level

It should answer:

- what this workflow started from
- how trustworthy the starting package was

### 4.3 `output_anchor`

Should identify:

- the primary output object or state
- whether a runnable next state exists
- whether new repair objects were created

It should answer:

- what later workflow should treat as the current output anchor

### 4.4 `change_set`

Should identify:

- changed objects
- change summaries
- which changes are already formalized
- which changes remain only inferred or local

Recommended internal split:

- `formalized_updates`
- `working_state_updates`
- `not_promoted`

This section is the main defense against layer flattening.

### 4.5 `open_items`

Should identify:

- active issues
- active reminders
- unresolved inferences
- residual risks

It should answer:

- what the next workflow still cannot assume is done

### 4.6 `confidence_and_gaps`

Should identify:

- confidence level
- known missing inputs
- conflict markers
- inference-only conclusions

It should answer:

- what the next workflow should distrust or verify

### 4.7 `next_route`

Should identify:

- recommended next workflow
- must-read refs
- do-not-skip checks

It should answer:

- what to do next
- what to read first

---

## 5. What Must Not Happen In Handoff Schema

The first handoff schema candidate must explicitly block these failure shapes.

### 5.1 Handoff As Replacement For Object Sync

Do not allow handoff payload richness to stand in for:

- missing `FactLedger` writeback
- missing `NarrativeState` sync
- missing repair-object updates

### 5.2 Stable Constraint Smuggling

Do not let handoff prose or handoff summary fields become the de facto home of:

- hard facts
- stable relation state
- stable character conclusions

### 5.3 `CharacterModel` Expansion For Handoff Safety

Do not use handoff-risk reduction as a reason to:

- expand `CharacterModel`
- push supporting evidence into field bodies
- treat compressed role summaries as evidence archives

### 5.4 Confidence Hidden Inside Narrative Summary

Do not bury:

- uncertainty
- conflict markers
- incomplete reconstruction

inside generic summary prose.

They need explicit schema space.

---

## 6. Candidate Workflow Specialization

The same top-level handoff shape should be used across workflows, but each workflow should emphasize different sections.

### 6.1 `Rebuild`

Emphasis:

- `input_anchor`
- `output_anchor`
- `confidence_and_gaps`

Because `Rebuild` mainly needs to state:

- what was reconstructed
- what is still missing
- whether a runnable state exists

### 6.2 `Continue`

Emphasis:

- `output_anchor`
- `change_set`
- `open_items`

Because `Continue` mainly needs to state:

- what changed this round
- what is now current state
- what warnings or issues remain active

### 6.3 `Review`

Emphasis:

- `change_set`
- `open_items`
- `next_route`

Because `Review` mainly needs to state:

- what judgment was made
- what repair or reminder objects were created
- which workflow should take over

### 6.4 `Rewrite`

Emphasis:

- `change_set`
- `open_items`
- `confidence_and_gaps`

Because `Rewrite` mainly needs to state:

- which issue was repaired
- which dependencies were synchronized
- what still requires re-review

---

## 7. Candidate Relationship To No-Regression Checks

Any future handoff schema proposal should be rejected if it makes these regressions easier:

1. richer summaries replacing same-packet formal sync
2. hidden confidence gaps
3. repair/control state leaking into stable memory
4. stable constraints expressed mainly as handoff commentary
5. `CharacterModel` expansion used as handoff insurance

---

## 8. What This Note Still Does Not Decide

This note still does not decide:

- final field names
- transport encoding
- payload versioning format
- whether payloads are stored whole or derived on demand

Those belong to later implementation planning.

---

## 9. Recommended Next Note

After this handoff schema note, the most natural next planning artifact is:

- `runtime orchestration boundary note`

because orchestration is the next layer that has to consume both serialization and handoff boundaries together.

---

## 10. One-Sentence Summary

The first handoff schema candidate should expose bounded, explicit delta-oriented workflow handoff, not a denser narrative summary that hides stale object state.
