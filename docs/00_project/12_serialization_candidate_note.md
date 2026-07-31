# Serialization Candidate Note

## Purpose

This file is an implementation-planning note for serialization shape.

It does not define a final machine schema.
It defines a first candidate direction that preserves current foundation locks.

Its main job is to answer:

- what should be serialized as stable memory
- what should be serialized as current working state
- what should be serialized as repair/control state
- what should remain confidence metadata
- what should never be flattened together for convenience

---

## 1. Serialization Goal

The goal is not "serialize every object the same way".

The goal is:

- preserve memory-tier separation
- preserve ownership boundaries
- preserve workflow handoff clarity
- prevent prose fallback from silently replacing object-layer state

One sentence:

serialization must protect the conceptual boundaries that foundation has already locked.

---

## 2. Candidate Top-Level Shape

Current first candidate is a four-part package shape:

1. `stable_memory`
2. `working_set`
3. `repair_control`
4. `confidence`

This mirrors current context-package and memory-tier decisions.

### 2.1 `stable_memory`

Carries long-term state that should survive compression.

Typical contents:

- relevant `WorkSpec`
- relevant `WorldModel`
- stable `CharacterModel` baselines
- relevant `FactLedger`
- relevant `ForeshadowGraph`

### 2.2 `working_set`

Carries the minimum current runnable state.

Typical contents:

- current `NarrativeState`
- active character subset
- current operational context needed by the next workflow

### 2.3 `repair_control`

Carries issue-routing and repair-state information.

Typical contents:

- active `ReviewIssue`
- active `ReviewReminder`
- previous handoff summaries that are still operationally relevant

### 2.4 `confidence`

Carries completeness and reliability metadata.

Typical contents:

- input completeness
- confidence level
- known gaps
- conflict markers

---

## 3. Candidate Object Placement

The first serialization candidate should keep these default placements.

| object / content | default serialized home | reason |
|---|---|---|
| `WorkSpec` | `stable_memory` | top-level direction, slow-changing |
| `WorldModel` | `stable_memory` | stable legality constraints |
| stable `CharacterModel` baseline | `stable_memory` | long-term role baseline |
| `FactLedger` | `stable_memory` | hard facts that already count |
| `ForeshadowGraph` | `stable_memory` | long-range promise tracking |
| current `NarrativeState` | `working_set` | current runnable state |
| local active character runtime slice | `working_set` | current operation only |
| `ReviewIssue` | `repair_control` | formal repair routing |
| `ReviewReminder` | `repair_control` | near-term warning handoff |
| completeness / certainty markers | `confidence` | not fact, not state, not repair object |

---

## 4. What Must Not Be Flattened

The serialization candidate must explicitly forbid these convenience collapses.

### 4.1 Hard Fact Into Working Pressure

Do not serialize:

- established `FactLedger` constraints

as if they were only:

- current situation prose
- temporary pressure
- handoff commentary

### 4.2 Repair Detail Into Stable Memory

Do not serialize:

- issue notes
- warning logic
- residual repair commentary

into:

- `FactLedger`
- `CharacterModel`
- `ForeshadowGraph`

### 4.3 Supporting Evidence Into `CharacterModel`

Do not serialize:

- recent sequence explanations
- rollback explanations
- temporary tactical evidence

back into `CharacterModel` field bodies.

### 4.4 Handoff Prose As State Substitute

Do not let a rich handoff summary act as a substitute for missing:

- `FactLedger` writeback
- `NarrativeState` sync
- formal repair/control objects

---

## 5. Candidate Subdivision Rules

The first serialization candidate should prefer these subdivisions.

### 5.1 `stable_memory` Subdivision

Recommended internal split:

- `direction`
- `world_constraints`
- `character_baselines`
- `fact_constraints`
- `promise_threads`

### 5.2 `working_set` Subdivision

Recommended internal split:

- `current_state`
- `active_scope`
- `current_operational_projections`

### 5.3 `repair_control` Subdivision

Recommended internal split:

- `active_issues`
- `active_reminders`
- `pending_recheck_targets`

### 5.4 `confidence` Subdivision

Recommended internal split:

- `completeness`
- `certainty`
- `known_gaps`
- `conflict_flags`

---

## 6. Workflow Serialization Implications

The same top-level shape should support all four workflows, but with different load emphasis.

### 6.1 `Rebuild`

Load focus:

- partial source material
- confidence gaps

Output emphasis:

- reconstructed `stable_memory`
- a runnable `working_set` when possible

### 6.2 `Continue`

Load focus:

- current `working_set`
- relevant `stable_memory`
- active `repair_control`

Output emphasis:

- updated `working_set`
- synchronized object updates where promotion thresholds are crossed

### 6.3 `Review`

Load focus:

- target `working_set`
- judgment-relevant `stable_memory`
- current `repair_control`

Output emphasis:

- updated `repair_control`
- review-facing state judgments

### 6.4 `Rewrite`

Load focus:

- issue-targeted `repair_control`
- root-cause objects from `working_set` and `stable_memory`

Output emphasis:

- same-packet synchronized object repair
- updated `repair_control`

---

## 7. No-Regression Checks For This Candidate

Any future implementation-facing serialization proposal should be rejected if it makes any of these regressions easier:

1. storing hard facts mainly in prose or commentary form
2. letting `working_set` silently replace `FactLedger`
3. letting `CharacterModel` absorb supporting evidence
4. letting handoff density substitute for missing formal synchronization
5. mixing confidence metadata into object truth

---

## 8. What This Note Still Does Not Decide

This note still does not decide:

- final JSON field names
- persistence technology
- database shape
- transport format
- versioning format

Those belong to later implementation planning.

---

## 9. Recommended Next Note

After this serialization note, the most natural next planning artifact is:

- `implementation-facing handoff schema note`

because handoff payload shape is the nearest companion to serialization boundaries.

---

## 10. One-Sentence Summary

The first serialization candidate should serialize by memory tier and workflow responsibility, not by flattening all narrative state into one convenience payload.
