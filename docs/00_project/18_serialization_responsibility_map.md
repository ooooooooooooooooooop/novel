# Serialization Responsibility Map

## Purpose

This file assigns serialization responsibilities to the implementation units defined in `docs/00_project/17_implementation_unit_map.md`.

It converts the candidate serialization shape in `docs/00_project/12_serialization_candidate_note.md` into responsibility boundaries.

It does not define a storage backend, file format, database schema, or code module layout.

---

## 1. Core Goal

The core goal is to decide who is responsible for placing each kind of narrative data into the serialization layers.

The simplest valid path is to keep the four-layer split from the serialization candidate:

1. `stable_memory`
2. `working_set`
3. `repair_control`
4. `confidence`

The responsibility map must preserve object ownership while making transfer boundaries explicit.

---

## 2. Responsibility Principle

Serialization is a boundary responsibility, not a truth-making responsibility.

This means:

- object-state units own what their fields mean
- workflow-action units produce candidate deltas and repair/control signals
- `SerializationBoundaryUnit` maps accepted material into serialization layers
- `SerializationBoundaryUnit` does not decide whether a fact, character conclusion, or review issue is valid

---

## 3. Layer Responsibility Summary

| Serialization Layer | Primary Boundary Owner | Source Owners | Main Responsibility | Must Not Do |
|---|---|---|---|---|
| `stable_memory` | `SerializationBoundaryUnit` | `WorkSpecUnit`, `WorldModelUnit`, `CharacterModelUnit`, `FactLedgerUnit`, `ForeshadowGraphUnit` | persist slow-changing object truth and long-range constraints | absorb working pressure, repair commentary, or confidence gaps |
| `working_set` | `SerializationBoundaryUnit` | `NarrativeStateUnit`, `PlotUnitUnit`, active runtime slices from object-state units | persist current runnable state and active operation context | silently replace stable memory or hard-fact admission |
| `repair_control` | `SerializationBoundaryUnit` | `ReviewIssueUnit`, `ReviewUnit`, `RewriteUnit`, review-reminder source rules | persist formal issue routing and bounded repair state | store permanent truth or become a generic note archive |
| `confidence` | `SerializationBoundaryUnit` | `RebuildUnit`, `ReviewUnit`, `HandoffBoundaryUnit`, object-state units reporting gaps | persist completeness, certainty, conflict, and reconstruction gaps | become fact, state, or repair object |

---

## 4. Object-State Serialization Responsibilities

Object-state units are responsible for defining admissible content.

They are not responsible for choosing storage technology.

| Source Unit | Default Layer | Serialized Responsibility | Excluded From This Layer |
|---|---|---|---|
| `WorkSpecUnit` | `stable_memory` | project-level narrative constraints, scope, goals, and durable exclusions | runtime route, current repair pressure, model choice |
| `WorldModelUnit` | `stable_memory` | stable world legality, constraints, and accepted world facts | character belief, temporary tactical pressure |
| `CharacterModelUnit` | `stable_memory` | compressed long-term knowledge, relations, misinformation, self-image, and arc-stage conclusions | supporting evidence, recent sequence logic, handoff insurance |
| `FactLedgerUnit` | `stable_memory` | hard facts that already count in the world | suspicion, unresolved inference, confidence commentary |
| `ForeshadowGraphUnit` | `stable_memory` | open promises, setup/payoff links, and resolved promise status | review route, current repair action |
| `NarrativeStateUnit` | `working_set` | current runnable state, active pressures, current scene/arc operating context | stable hard facts, long-term character summary |
| `PlotUnitUnit` | `working_set` | latest event record, input/output state delta, effective progression evidence | long-term memory compression by default |
| `ReviewIssueUnit` | `repair_control` | issue type, severity, route, target object, fix status, and escalation state | stable fact, character conclusion, or world legality rule |

---

## 5. Workflow-Action Serialization Responsibilities

Workflow-action units produce material that may be serialized.

They do not own the target serialization layer.

| Workflow Unit | Produces | Target Layer | Serialization Responsibility Boundary |
|---|---|---|---|
| `RebuildUnit` | reconstructed object packet, unresolved gaps, confidence notes | `stable_memory`, `working_set`, `confidence` | may propose reconstructed object state, but gaps stay in `confidence` until admitted |
| `ContinueUnit` | candidate `PlotUnit`, proposed state deltas, active context | `working_set` | may update runnable state only after review/writeback rules accept the progression |
| `ReviewUnit` | review classification, warnings, issues, route recommendation | `repair_control`, `confidence` | may create issue/control records but must not patch object truth directly |
| `RewriteUnit` | repaired packet, synchronized object deltas, repair completion state | `working_set`, `repair_control`, possibly `stable_memory` through object owners | may serialize repair results only when same-packet writeback is complete |

---

## 6. Boundary-Control Responsibilities

### 6.1 `SerializationBoundaryUnit`

Owns:

- layer placement
- layer separation checks
- cross-layer references
- serialization package completeness

Does not own:

- fact admission
- character conclusion admission
- review issue validity
- workflow route choice

### 6.2 `HandoffBoundaryUnit`

Provides:

- source workflow outputs
- `change_set`
- `open_items`
- `confidence_and_gaps`

Serialization uses this material only as transfer context.
It must not treat handoff prose as a substitute for object-layer writeback.

### 6.3 `OrchestrationGateUnit`

Uses serialization status to decide whether a packet can move forward.

It may block movement when required layers are incomplete.
It must not decide the truth of serialized content.

### 6.4 `NoRegressionValidationUnit`

Checks whether serialized outputs preserve the inherited locks.

It should test layer separation rather than general prose quality.

---

## 7. Cross-Layer Reference Rules

Serialization layers may reference each other, but references must not collapse ownership.

Allowed references:

- `working_set` may reference stable object IDs or stable entries
- `repair_control` may reference affected object units and current packet IDs
- `confidence` may reference any layer to mark gaps or uncertainty
- `stable_memory` may reference source `PlotUnit` or review evidence only as external support, not as embedded field body

Forbidden references:

- `stable_memory` embedding repair commentary as durable object truth
- `working_set` overriding `FactLedgerUnit` hard facts
- `repair_control` becoming permanent character or world state
- `confidence` changing object truth by being present or absent

---

## 8. Write Responsibility Rules

### 8.1 Stable Memory Writes

Stable memory writes must pass through the relevant object-state owner.

Examples:

- hard fact write: `FactLedgerUnit`
- long-term character conclusion write: `CharacterModelUnit`
- world legality write: `WorldModelUnit`
- promise graph write: `ForeshadowGraphUnit`

`SerializationBoundaryUnit` may package these writes, but it cannot admit them.

### 8.2 Working Set Writes

Working set writes are owned by current-state and event units.

Examples:

- current state write: `NarrativeStateUnit`
- event progression write: `PlotUnitUnit`
- active runtime character slice: `NarrativeStateUnit` carrying a bounded projection from `CharacterModelUnit`

Working set writes must not become stable memory without admission by the relevant stable owner.

### 8.3 Repair Control Writes

Repair control writes are owned by issue and workflow units.

Examples:

- issue creation: `ReviewIssueUnit` from `ReviewUnit`
- warning/reminder handoff: review reminder rules through `ReviewUnit`
- repair completion marker: `RewriteUnit`

Repair control writes must not become a permanent archive of everything that was discussed.

### 8.4 Confidence Writes

Confidence writes are owned by the unit that exposes the gap.

Examples:

- reconstruction uncertainty: `RebuildUnit`
- review ambiguity: `ReviewUnit`
- handoff incompleteness: `HandoffBoundaryUnit`
- object-level missing field: relevant object-state unit

Confidence writes must remain metadata, not object truth.

---

## 9. Serialization Dependency Order

The minimum serialization order is:

1. collect object-state owner outputs
2. separate material into `stable_memory`, `working_set`, `repair_control`, and `confidence`
3. check that no layer is compensating for another layer's missing write
4. attach cross-layer references without copying field bodies into the wrong layer
5. expose serialization status to handoff and orchestration planning

This order keeps ownership before packaging.

---

## 10. Lock Inheritance

### 10.1 Track 1: `FactLedger` Hard-Fact Integrity

Only `FactLedgerUnit` may admit hard facts into `stable_memory`.

`working_set`, `repair_control`, `confidence`, and handoff prose may carry candidate pressure or uncertainty, but they cannot count as hard fact storage.

Reject any serialization design where a fact is considered synchronized because it appears in current state, repair notes, or dense handoff prose.

### 10.2 Track 2: Bounded Runtime-First `Rewrite`

`RewriteUnit` may produce repair deltas, but serialization must show whether same-packet writeback has completed.

`repair_control` cannot mark a packet safe to continue if affected `stable_memory` or `working_set` writes remain unsynchronized.

Reject any serialization design where repair notes compensate for missing object-layer writeback.

### 10.3 Track 3: `CharacterModel` Evidence Leakback

`CharacterModelUnit` serializes compressed long-term conclusions only.

Supporting evidence may be referenced externally through `PlotUnitUnit`, `NarrativeStateUnit`, handoff context, review context, or confidence metadata.

Reject any serialization design that embeds supporting evidence into `CharacterModel` fields to reduce handoff risk.

---

## 11. Minimal Acceptance Checks

The serialization responsibility map is acceptable if all answers below are "yes".

1. Does every serialized item have a source owner and a target layer?
2. Does `SerializationBoundaryUnit` package material without admitting truth?
3. Does `stable_memory` exclude working pressure, repair notes, and confidence gaps?
4. Does `working_set` remain current runnable state rather than hard-fact truth?
5. Does `repair_control` remain route and repair state rather than durable object memory?
6. Does `confidence` remain metadata rather than fact, state, or repair object?
7. Can handoff and orchestration maps consume this split without inventing a new core object?

---

## 12. What This Enables Next

This map enables the next planning documents to define transfer and movement rules without reassigning object ownership.

Recommended next outputs:

1. workflow handoff responsibility map: `docs/00_project/19_workflow_handoff_responsibility_map.md`
2. orchestration gate map: `docs/00_project/20_orchestration_gate_map.md`
3. no-regression acceptance test list: `docs/00_project/21_no_regression_acceptance_test_list.md`

Each should preserve this serialization split unless a real responsibility contradiction is found.

---

## 13. One-Sentence Summary

The serialization responsibility map assigns stable, working, repair, and confidence layers to named implementation units while keeping serialization as packaging, not truth-making.
