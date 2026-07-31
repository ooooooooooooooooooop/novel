# No-Regression Acceptance Test List

## Purpose

This file defines the first implementation-planning no-regression acceptance test list.

It turns the planning guardrails in `docs/00_project/15_no_regression_verification_checklist.md` and the acceptance checks in `docs/00_project/17_implementation_unit_map.md` through `docs/00_project/20_orchestration_gate_map.md` into future implementation acceptance tests.

It does not define a test framework, test runner, fixture format, or automation strategy.

---

## 1. Core Goal

The core goal is to define what a future implementation must prove before it can be treated as non-regressing against the current planning foundation.

The simplest valid path is to test five areas:

1. inherited locks
2. implementation unit ownership
3. serialization responsibility
4. workflow handoff responsibility
5. orchestration gate responsibility

Each test is written as an acceptance condition, not executable code.

---

## 2. Test Result Vocabulary

Use these result labels for future implementation review.

| Result | Meaning |
|---|---|
| `pass` | implementation preserves the required boundary |
| `fail` | implementation violates or bypasses the boundary |
| `blocked` | implementation cannot be evaluated because required evidence is missing |
| `defer` | implementation does not touch this boundary yet |

`defer` is allowed only when the implementation slice truly does not touch the tested responsibility.

It must not hide missing evidence for an affected boundary.

---

## 3. Required Evidence Types

Future implementation review should look for these evidence types.

| Evidence Type | Purpose |
|---|---|
| owner mapping | proves a responsibility has a named unit owner |
| input/output trace | proves data enters and leaves the unit through explicit boundaries |
| state delta record | proves state movement is explicit and reviewable |
| layer placement record | proves serialized material belongs to the correct layer |
| handoff packet record | proves workflow transfer is explicit and not hidden in prose |
| gate decision record | proves orchestration allowed, blocked, or escalated movement for a stated reason |
| rejection example | proves the implementation refuses known regression shapes |

These are evidence categories, not required file formats.

---

## 4. Track 1 Tests: `FactLedger` Hard-Fact Integrity

### T1.1 Hard Fact Owner Test

Acceptance condition:

- every hard fact write is admitted by `FactLedgerUnit`

Fail if:

- a hard fact enters stable memory through `NarrativeStateUnit`, `HandoffBoundaryUnit`, `SerializationBoundaryUnit`, or `OrchestrationGateUnit`

Required evidence:

- owner mapping
- layer placement record
- state delta record when the fact came from workflow output

### T1.2 Working-State Substitution Test

Acceptance condition:

- `working_set` may carry current pressure or candidate fact changes, but it does not count as hard-fact storage

Fail if:

- future logic treats a fact as synchronized because it appears in current runnable state

Required evidence:

- layer placement record
- gate decision record when movement depends on the fact

### T1.3 Handoff Substitution Test

Acceptance condition:

- handoff may carry candidate fact deltas, but only admitted `FactLedgerUnit` writes count as hard facts

Fail if:

- dense handoff prose or `change_set` text compensates for missing `FactLedgerUnit` writeback

Required evidence:

- handoff packet record
- owner mapping for each fact delta

### T1.4 Mixed-Layer Compression Test

Acceptance condition:

- stable facts, working pressure, repair state, and confidence gaps remain separate

Fail if:

- a summary field compresses fact truth, current pressure, repair notes, and uncertainty into one untyped payload

Required evidence:

- layer placement record
- rejection example

---

## 5. Track 2 Tests: Bounded Runtime-First `Rewrite`

### T2.1 Formal Issue Entry Test

Acceptance condition:

- `RewriteUnit` starts only from a formal `ReviewIssueUnit` or equivalent issue-driven repair record

Fail if:

- rewrite starts from vague dissatisfaction, prose preference, or unclassified runtime discomfort

Required evidence:

- owner mapping
- input/output trace

### T2.2 Same-Packet Sync Test

Acceptance condition:

- `RewriteUnit` output cannot move forward until same-packet writeback is complete or explicitly blocked

Fail if:

- repaired prose moves forward while affected `stable_memory` or `working_set` writes remain unsynchronized

Required evidence:

- state delta record
- layer placement record
- gate decision record

### T2.3 Handoff Compensation Test

Acceptance condition:

- `open_items`, repair notes, or dense handoff prose cannot substitute for object-layer writeback

Fail if:

- handoff richness makes an incomplete rewrite packet eligible for continuation

Required evidence:

- handoff packet record
- gate decision record
- rejection example

### T2.4 Runtime-First Default Drift Test

Acceptance condition:

- runtime-first repair remains a bounded local exception, not a normal workflow order

Fail if:

- implementation paths routinely patch runtime state before object owners and review/writeback rules are applied

Required evidence:

- input/output trace
- gate decision record
- rejection example

---

## 6. Track 3 Tests: `CharacterModel` Evidence Leakback

### T3.1 Long-Term Conclusion Test

Acceptance condition:

- `CharacterModelUnit` stores compressed long-term conclusions only

Fail if:

- field bodies store scene evidence, recent sequence logic, or rollback explanation as part of the conclusion

Required evidence:

- owner mapping
- layer placement record

### T3.2 Handoff Insurance Bloat Test

Acceptance condition:

- handoff risk is handled by handoff context, not by expanding `CharacterModelUnit`

Fail if:

- character fields grow mainly to make future handoff safer

Required evidence:

- handoff packet record
- rejection example

### T3.3 Evidence Placement Test

Acceptance condition:

- supporting evidence remains in `PlotUnitUnit`, `NarrativeStateUnit`, handoff context, review context, or confidence metadata

Fail if:

- evidence is copied into `CharacterModelUnit` field bodies to reduce lookup burden

Required evidence:

- layer placement record
- input/output trace

### T3.4 Cross-Field Compression Test

Acceptance condition:

- `knowledge_state`, `relations`, `misinformation`, `self_image`, and `arc_stage` remain distinct when represented

Fail if:

- implementation collapses long-term conclusions and supporting evidence across those fields into one convenience summary

Required evidence:

- owner mapping
- rejection example

---

## 7. Implementation Unit Ownership Tests

### U1 Primary Owner Test

Acceptance condition:

- every core object has exactly one primary object-state unit owner

Fail if:

- object truth is co-owned ambiguously by a workflow or boundary unit

### U2 Workflow Route Owner Test

Acceptance condition:

- every workflow has exactly one workflow-action unit route owner

Fail if:

- routing is hidden inside object storage, serialization, or orchestration convenience code

### U3 Boundary Owner Test

Acceptance condition:

- serialization, handoff, orchestration, and validation each attach to named boundary-control units

Fail if:

- boundary responsibilities are spread across unrelated units with no single reviewable owner

### U4 No-New-Core-Object Test

Acceptance condition:

- implementation can express responsibilities using the current unit map without inventing another core narrative object

Fail if:

- a new core object appears only to avoid assigning responsibility to existing units

---

## 8. Serialization Responsibility Tests

### S1 Layer Placement Test

Acceptance condition:

- every serialized item has a source owner and target layer

Fail if:

- data is serialized into an opaque payload without owner or layer

### S2 Packaging-Not-Truth Test

Acceptance condition:

- `SerializationBoundaryUnit` packages accepted material without admitting truth

Fail if:

- serialization decides whether a fact, character conclusion, review issue, or world rule is valid

### S3 Stable Memory Purity Test

Acceptance condition:

- `stable_memory` excludes working pressure, repair notes, and confidence gaps

Fail if:

- stable memory stores issue commentary, unresolved suspicion, or reconstruction uncertainty as durable truth

### S4 Working Set Boundary Test

Acceptance condition:

- `working_set` remains current runnable state

Fail if:

- `working_set` replaces `FactLedgerUnit` or long-term `CharacterModelUnit` storage

### S5 Repair Control Boundary Test

Acceptance condition:

- `repair_control` remains route and repair state

Fail if:

- `repair_control` becomes durable object memory or a generic discussion archive

### S6 Confidence Metadata Test

Acceptance condition:

- `confidence` remains metadata

Fail if:

- confidence level, gap status, or completeness marker changes object truth by itself

---

## 9. Workflow Handoff Responsibility Tests

### H1 Section Owner Test

Acceptance condition:

- every handoff section has a primary owner

Fail if:

- handoff is a freeform summary with no section responsibility

### H2 Change Set Owner Test

Acceptance condition:

- every object delta in `change_set` names a target object-state unit and target serialization layer

Fail if:

- object changes are implied by prose without target owner or layer

### H3 Anchor Reference Test

Acceptance condition:

- `input_anchor` and `output_anchor` reference serialized state rather than replacing it

Fail if:

- anchor prose becomes the only record of input or output state

### H4 Explicit Gap Test

Acceptance condition:

- `confidence_and_gaps` keeps uncertainty explicit

Fail if:

- uncertainty is hidden inside narrative summary, route note, or handoff header

### H5 Route-As-Gate-Input Test

Acceptance condition:

- `next_route` remains a gate input

Fail if:

- `next_route` overrides review rules, object admission, or writeback verification

### H6 Serialization Preservation Test

Acceptance condition:

- handoff preserves the four serialization layers

Fail if:

- handoff packet shape assumes data that serialization no longer keeps separated

---

## 10. Orchestration Gate Tests

### O1 Entry Gate Evidence Test

Acceptance condition:

- entry gating depends on serialized state and handoff anchors

Fail if:

- entry is allowed because prose summary looks sufficient

### O2 Execution Coordination Boundary Test

Acceptance condition:

- execution coordination avoids replacing workflow-specific judgment

Fail if:

- orchestration classifies review issues, chooses rewrite root cause, or admits object deltas

### O3 Writeback Verification Test

Acceptance condition:

- writeback verification blocks movement when object-layer sync is incomplete

Fail if:

- prose summary, repair notes, or `repair_control` are treated as synchronized object state

### O4 Escalation Boundary Test

Acceptance condition:

- escalation keeps `RebuildUnit` as an escalation path

Fail if:

- rebuild becomes routine continuation or a shortcut around review/rewrite gates

### O5 Route Override Test

Acceptance condition:

- orchestration consumes `next_route` without turning it into a rule override

Fail if:

- orchestration follows route recommendation despite failed gate, open blocking issue, or incomplete writeback

---

## 11. Cross-Artifact Consistency Tests

### C1 Unit-To-Serialization Consistency Test

Acceptance condition:

- serialization responsibilities match the unit owners in `17_implementation_unit_map.md`

Fail if:

- serialization introduces a new owner for object truth without updating unit responsibility

### C2 Serialization-To-Handoff Consistency Test

Acceptance condition:

- handoff references the serialization layers from `18_serialization_responsibility_map.md`

Fail if:

- handoff assumes merged state that serialization intentionally separates

### C3 Handoff-To-Orchestration Consistency Test

Acceptance condition:

- orchestration gates consume the handoff sections from `19_workflow_handoff_responsibility_map.md`

Fail if:

- orchestration moves workflow state without using handoff anchors, change sets, open items, or confidence gaps

### C4 Lock-To-Gate Consistency Test

Acceptance condition:

- Track 1, Track 2, and Track 3 are enforceable through unit ownership, serialization layer checks, handoff checks, and orchestration gates

Fail if:

- any lock exists only as prose guidance with no implementation acceptance point

---

## 12. Minimum Review Set

Every future implementation slice that touches narrative state movement must evaluate at least these tests:

1. T1.1 Hard Fact Owner Test
2. T2.2 Same-Packet Sync Test
3. T3.1 Long-Term Conclusion Test
4. S1 Layer Placement Test
5. H2 Change Set Owner Test
6. O3 Writeback Verification Test
7. C4 Lock-To-Gate Consistency Test

If a slice does not touch one of these areas, mark it `defer` with a reason.

---

## 13. Completion Rule

The first implementation-planning output set is complete when:

- `docs/00_project/17_implementation_unit_map.md` exists
- `docs/00_project/18_serialization_responsibility_map.md` exists
- `docs/00_project/19_workflow_handoff_responsibility_map.md` exists
- `docs/00_project/20_orchestration_gate_map.md` exists
- this no-regression acceptance test list exists

Future implementation may begin only as bounded slices that can identify which tests they must pass, fail, block, or defer.

---

## 14. One-Sentence Summary

The no-regression acceptance test list defines implementation-review checks that preserve the inherited locks across unit ownership, serialization, handoff, and orchestration without prescribing a test framework.
