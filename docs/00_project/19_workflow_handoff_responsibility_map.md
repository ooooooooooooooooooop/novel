# Workflow Handoff Responsibility Map

## Purpose

This file assigns workflow handoff responsibilities to the implementation units defined in `docs/00_project/17_implementation_unit_map.md`.

It converts the seven-part handoff shape in `docs/00_project/13_handoff_schema_candidate_note.md` into responsibility boundaries.

It uses the serialization split from `docs/00_project/18_serialization_responsibility_map.md`.

It does not define a message format, transport protocol, queue, API, or runtime framework.

---

## 1. Core Goal

The core goal is to decide who creates, verifies, carries, and consumes each handoff section between workflows.

The simplest valid path is to preserve the candidate seven-section shape:

1. `handoff_header`
2. `input_anchor`
3. `output_anchor`
4. `change_set`
5. `open_items`
6. `confidence_and_gaps`
7. `next_route`

Handoff is transfer structure, not object truth.

---

## 2. Responsibility Principle

Workflow handoff is owned by `HandoffBoundaryUnit` as a boundary-control unit.

This means:

- workflow-action units produce handoff source material
- object-state units own the meaning and admission of object deltas
- `SerializationBoundaryUnit` confirms which layer each referenced item belongs to
- `HandoffBoundaryUnit` assembles and verifies the handoff packet
- `OrchestrationGateUnit` uses the handoff packet to decide whether movement is allowed

`HandoffBoundaryUnit` must not admit hard facts, expand `CharacterModel`, or bypass same-packet writeback.

---

## 3. Section Responsibility Summary

| Handoff Section | Primary Owner | Source Owners | Consumer Units | Main Responsibility | Must Not Do |
|---|---|---|---|---|---|
| `handoff_header` | `HandoffBoundaryUnit` | source workflow unit, `OrchestrationGateUnit` | target workflow unit, `OrchestrationGateUnit` | identify source, target, route, packet id, and workflow reason | hide route ambiguity in prose |
| `input_anchor` | `HandoffBoundaryUnit` | source workflow unit, relevant object-state units | target workflow unit | state what packet/object state the source workflow started from | replace serialized object state |
| `output_anchor` | `HandoffBoundaryUnit` | source workflow unit, `SerializationBoundaryUnit` | target workflow unit, `OrchestrationGateUnit` | state what object packet or state the source workflow produced | claim writeback completed when layers are unsynchronized |
| `change_set` | `HandoffBoundaryUnit` | object-state units, workflow-action unit | target workflow unit, `SerializationBoundaryUnit` | list explicit object deltas and their admission/write status | turn dense summary into implicit object update |
| `open_items` | `HandoffBoundaryUnit` | `ReviewUnit`, `ReviewIssueUnit`, source workflow unit | target workflow unit, `ReviewUnit`, `RewriteUnit` | carry unresolved issues, warnings, reminders, and pending decisions | store permanent truth or broad context archive |
| `confidence_and_gaps` | `HandoffBoundaryUnit` | `RebuildUnit`, `ReviewUnit`, object-state units, `SerializationBoundaryUnit` | target workflow unit, `OrchestrationGateUnit` | expose uncertainty, incompleteness, and reconstruction gaps | hide uncertainty inside narrative summary |
| `next_route` | `HandoffBoundaryUnit` | `ReviewUnit`, `OrchestrationGateUnit`, source workflow unit | `OrchestrationGateUnit`, target workflow unit | state recommended next workflow and gating reason | override review rules or object admission |

---

## 4. Section Rules

### 4.1 `handoff_header`

Owns:

- source workflow
- target workflow
- packet identifier
- route reason
- handoff status

Primary producer:

- source workflow-action unit

Primary verifier:

- `HandoffBoundaryUnit`

Required check:

- the header must make workflow movement explicit enough for `OrchestrationGateUnit` to accept, block, or escalate it

### 4.2 `input_anchor`

Owns:

- starting object packet reference
- starting `NarrativeState` reference
- relevant stable-memory references
- known input gaps

Primary producer:

- source workflow-action unit

Primary source owners:

- relevant object-state units
- `SerializationBoundaryUnit`

Required check:

- input anchor must reference serialized object state; it must not recreate object truth as handoff prose

### 4.3 `output_anchor`

Owns:

- output object packet reference
- output `NarrativeState` reference
- output `PlotUnit` reference when applicable
- writeback completion status

Primary producer:

- source workflow-action unit

Primary verifier:

- `SerializationBoundaryUnit`
- `HandoffBoundaryUnit`

Required check:

- output anchor must distinguish proposed output, reviewed output, repaired output, and synchronized output

### 4.4 `change_set`

Owns:

- explicit object deltas
- target object-state unit for each delta
- admission status
- write status
- reason for change

Primary producer:

- source workflow-action unit

Primary admission owner:

- relevant object-state unit

Required check:

- every change must name its target owner, target layer, and whether it is proposed, admitted, rejected, or deferred

### 4.5 `open_items`

Owns:

- unresolved `ReviewIssue` items
- active warning/reminder items
- pending admissions
- blocked routes
- deferred decisions

Primary producer:

- `ReviewUnit`
- source workflow-action unit

Primary consumer:

- target workflow-action unit
- `ReviewUnit` when re-review is required

Required check:

- open items must remain repair/control or confidence material unless admitted by the proper object-state owner

### 4.6 `confidence_and_gaps`

Owns:

- confidence level
- missing source material
- reconstruction uncertainty
- unresolved conflict markers
- incomplete synchronization markers

Primary producer:

- unit that exposes the gap

Primary verifier:

- `HandoffBoundaryUnit`
- `SerializationBoundaryUnit`

Required check:

- confidence must stay explicit and must not be hidden inside summary prose

### 4.7 `next_route`

Owns:

- recommended next workflow
- reason for route
- required preconditions
- blocking issue if route cannot proceed
- escalation target if needed

Primary producer:

- `ReviewUnit` when review has occurred
- source workflow-action unit when a non-review transfer is being proposed

Primary gatekeeper:

- `OrchestrationGateUnit`

Required check:

- next route is a recommendation or gate input, not a silent override of review and writeback rules

---

## 5. Workflow-Specific Responsibilities

### 5.1 `RebuildUnit` Handoff

Most important sections:

- `input_anchor`
- `output_anchor`
- `confidence_and_gaps`
- `open_items`

Responsibilities:

- expose source material and reconstruction scope
- separate reconstructed object state from unresolved gaps
- mark which recovered entries are admitted and which remain uncertain
- route incomplete recovery to `ReviewUnit`, `RewriteUnit`, or another bounded `RebuildUnit` pass only when justified

Must not:

- normalize `Rebuild` as routine continuation
- turn reconstruction confidence into hard fact

### 5.2 `ContinueUnit` Handoff

Most important sections:

- `input_anchor`
- `output_anchor`
- `change_set`
- `open_items`
- `next_route`

Responsibilities:

- expose candidate `PlotUnit` and proposed `NarrativeState` delta
- identify meaningful state change
- carry open promise, pressure, or review concerns forward explicitly
- route candidate output to `ReviewUnit` before treating it as accepted progression

Must not:

- treat non-effective progression as valid because prose exists
- write stable facts directly from candidate continuation

### 5.3 `ReviewUnit` Handoff

Most important sections:

- `change_set`
- `open_items`
- `confidence_and_gaps`
- `next_route`

Responsibilities:

- classify validity and issue severity
- create or update `ReviewIssueUnit` records
- route to warning, `RewriteUnit`, `Replan`, `ContinueUnit`, or escalation according to rules
- mark uncertainty and unresolved review gaps explicitly

Must not:

- silently patch object truth
- hide review uncertainty inside narrative summary

### 5.4 `RewriteUnit` Handoff

Most important sections:

- `input_anchor`
- `output_anchor`
- `change_set`
- `open_items`
- `confidence_and_gaps`
- `next_route`

Responsibilities:

- name the formal issue being repaired
- identify each affected object-state unit
- mark writeback completion for same-packet synchronization
- leave unresolved or out-of-scope issues in `open_items`
- route repaired packet back to `ReviewUnit` or onward only when synchronization is complete

Must not:

- let runtime-first repair escape same-packet synchronization
- use handoff density as compensation for missing writeback

---

## 6. Relationship To Serialization

Handoff sections reference serialized layers; they do not replace them.

| Handoff Section | Serialization Relationship |
|---|---|
| `handoff_header` | references route and packet identity; not a serialization layer |
| `input_anchor` | references prior `stable_memory`, `working_set`, `repair_control`, and `confidence` as needed |
| `output_anchor` | references produced or updated serialized packet state |
| `change_set` | names target object owner and target serialization layer for each delta |
| `open_items` | usually references `repair_control` and `confidence` |
| `confidence_and_gaps` | corresponds to `confidence` metadata |
| `next_route` | uses serialization completeness as route precondition |

Serialization remains the package/layer boundary.
Handoff remains the workflow transfer boundary.

---

## 7. Handoff Dependency Order

The minimum handoff construction order is:

1. identify source workflow and target workflow in `handoff_header`
2. reference the source packet in `input_anchor`
3. reference produced packet state in `output_anchor`
4. list explicit object deltas in `change_set`
5. list unresolved issues and pending work in `open_items`
6. expose uncertainty in `confidence_and_gaps`
7. recommend or block movement in `next_route`
8. let `OrchestrationGateUnit` accept, block, or escalate the route

This order keeps state references before routing decisions.

---

## 8. Lock Inheritance

### 8.1 Track 1: `FactLedger` Hard-Fact Integrity

Handoff may carry candidate facts, fact deltas, or unresolved fact pressure.

Only `FactLedgerUnit` may admit hard facts.

`change_set`, `open_items`, and `confidence_and_gaps` must clearly mark whether a fact change is proposed, admitted, rejected, or deferred.

Reject any handoff design where a hard fact is considered synchronized because it appears in summary prose.

### 8.2 Track 2: Bounded Runtime-First `Rewrite`

`RewriteUnit` handoff must include synchronization status in `output_anchor` and affected-object deltas in `change_set`.

`next_route` must not move the packet forward while required same-packet writeback is incomplete.

Reject any handoff design where `open_items` or dense handoff prose compensates for incomplete writeback.

### 8.3 Track 3: `CharacterModel` Evidence Leakback

Handoff may carry supporting evidence as transfer context.

`CharacterModelUnit` may admit only compressed long-term conclusions.

Supporting evidence should stay in `change_set`, `open_items`, `confidence_and_gaps`, review context, or referenced `PlotUnit` / `NarrativeState` context.

Reject any handoff design that expands `CharacterModel` fields to make future handoff safer.

---

## 9. Minimal Acceptance Checks

The workflow handoff responsibility map is acceptable if all answers below are "yes".

1. Does every handoff section have a primary owner?
2. Does every object delta in `change_set` name a target object-state unit?
3. Does `input_anchor` / `output_anchor` reference serialized state rather than replacing it?
4. Does `confidence_and_gaps` keep uncertainty explicit?
5. Does `next_route` remain a gate input rather than a rule override?
6. Does handoff preserve the four serialization layers from `18_serialization_responsibility_map.md`?
7. Can orchestration gates consume this handoff without inventing another core object?

---

## 10. What This Enables Next

This map enables orchestration planning to decide when workflow movement is allowed, blocked, or escalated.

Recommended next outputs:

1. orchestration gate map: `docs/00_project/20_orchestration_gate_map.md`
2. no-regression acceptance test list: `docs/00_project/21_no_regression_acceptance_test_list.md`

Each should use the handoff sections in this file unless a real responsibility contradiction is found.

---

## 11. One-Sentence Summary

The workflow handoff responsibility map assigns each handoff section to named units while keeping handoff as explicit transfer structure, not object truth or rule override.
