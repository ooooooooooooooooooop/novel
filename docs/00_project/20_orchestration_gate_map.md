# Orchestration Gate Map

## Purpose

This file assigns orchestration gate responsibilities to the implementation units defined in `docs/00_project/17_implementation_unit_map.md`.

It converts the orchestration boundary in `docs/00_project/14_runtime_orchestration_boundary_note.md` into gate responsibilities.

It consumes the serialization responsibilities in `docs/00_project/18_serialization_responsibility_map.md` and the workflow handoff responsibilities in `docs/00_project/19_workflow_handoff_responsibility_map.md`.

It does not define a scheduler, runtime engine, queue, framework, or execution protocol.

---

## 1. Core Goal

The core goal is to decide when workflow movement is allowed, blocked, or escalated.

The simplest valid path is to preserve the four orchestration layers:

1. entry gating
2. execution coordination
3. writeback verification
4. escalation

Orchestration is movement control, not object truth, review judgment, or prose repair.

---

## 2. Responsibility Principle

Orchestration is owned by `OrchestrationGateUnit` as a boundary-control unit.

This means:

- workflow-action units own workflow-specific action and judgment
- object-state units own object truth and admissible updates
- `SerializationBoundaryUnit` exposes layer completeness and synchronization status
- `HandoffBoundaryUnit` exposes transfer sections and next-route proposals
- `OrchestrationGateUnit` accepts, blocks, or escalates movement between workflows

`OrchestrationGateUnit` must not decide hard facts, broaden `CharacterModel`, classify review issues, or treat dense prose as synchronization.

---

## 3. Gate Layer Summary

| Gate Layer | Primary Owner | Inputs | Outputs | Main Responsibility | Must Not Do |
|---|---|---|---|---|---|
| Entry Gating | `OrchestrationGateUnit` | requested workflow, serialized packet status, handoff header, input anchor | allow/block workflow entry with reason | enter a workflow when required object state is missing or only summarized in prose |
| Execution Coordination | `OrchestrationGateUnit` | active workflow, declared target, route constraints, open items | execution envelope and required next checkpoint | replace workflow-specific logic or review classification |
| Writeback Verification | `OrchestrationGateUnit` | output anchor, change set, serialization layer status, repair status | pass/block synchronization completion | treat handoff density as object-layer writeback |
| Escalation | `OrchestrationGateUnit` | blocked gate reason, repeated failure, unresolved issue, confidence gaps | route to Review, Rewrite, Rebuild, Replan, or stop condition | normalize Rebuild or bypass formal review/rewrite routing |

---

## 4. Gate Rules

### 4.1 Entry Gating

Entry gating answers:

- is the requested workflow allowed to start?
- does the packet contain the required serialized layers?
- does the handoff packet expose input state and route reason?
- are open issues compatible with the requested workflow?

Primary inputs:

- `handoff_header`
- `input_anchor`
- `open_items`
- `confidence_and_gaps`
- serialization layer completeness

Allowed outputs:

- `allow_entry`
- `block_entry`
- `require_review`
- `require_rebuild`
- `require_missing_context`

Must not:

- infer missing object state from summary prose
- allow `ContinueUnit` to run when current `NarrativeStateUnit` is not runnable
- allow `RewriteUnit` to start without a formal issue or bounded target packet

### 4.2 Execution Coordination

Execution coordination answers:

- which workflow unit is active?
- what packet is it allowed to touch?
- which object-state units may receive proposed deltas?
- what checkpoint must occur after execution?

Primary inputs:

- active workflow route
- handoff `next_route`
- target object-state units from `change_set`
- open review or repair items

Allowed outputs:

- execution envelope
- target unit list
- required post-execution handoff sections
- required review or writeback checkpoint

Must not:

- classify review issues on behalf of `ReviewUnit`
- choose rewrite root cause on behalf of `RewriteUnit`
- decide whether an object delta is true or admissible

### 4.3 Writeback Verification

Writeback verification answers:

- did the workflow produce explicit output state?
- are object deltas named and owned?
- are required serialization layers synchronized?
- does any repair remain open?
- is re-review mandatory before movement continues?

Primary inputs:

- `output_anchor`
- `change_set`
- `open_items`
- serialization layer status
- repair completion markers

Allowed outputs:

- `writeback_complete`
- `writeback_incomplete`
- `requires_same_packet_sync`
- `requires_re_review`
- `requires_escalation`

Must not:

- count a prose summary as stable writeback
- count `repair_control` as synchronized object state
- move a packet forward when target layers remain incomplete

### 4.4 Escalation

Escalation answers:

- is local movement blocked?
- can the block be resolved by `ReviewUnit`?
- can it be resolved by bounded `RewriteUnit`?
- does it require `RebuildUnit`?
- does it expose a foundation-level contradiction?

Primary inputs:

- failed entry gate
- failed writeback verification
- unresolved `ReviewIssueUnit` records
- repeated local repair failure
- confidence and reconstruction gaps

Allowed outputs:

- route to `ReviewUnit`
- route to `RewriteUnit`
- route to `RebuildUnit`
- route to replan / structural escalation
- stop and surface boundary contradiction

Must not:

- treat `RebuildUnit` as normal continuation
- escalate to rewrite without a formal issue
- hide boundary contradiction inside retry behavior

---

## 5. Workflow Gate Responsibilities

### 5.1 `RebuildUnit` Gates

Entry allowed when:

- current runnable state cannot be trusted
- serialized state is incomplete or degraded
- handoff exposes reconstruction gaps that local review/rewrite cannot resolve

Exit allowed when:

- reconstructed object packet is explicitly separated into stable, working, repair, and confidence layers
- unresolved gaps remain in `confidence_and_gaps`
- object-state admissions are marked as admitted, proposed, rejected, or deferred

Must block when:

- reconstruction confidence is being treated as hard fact
- rebuild is used as routine continuation convenience

### 5.2 `ContinueUnit` Gates

Entry allowed when:

- `NarrativeStateUnit` is runnable
- required stable constraints are available
- no blocking review or repair item prevents progression
- open promises and pressures are visible enough for candidate progression

Exit allowed when:

- candidate `PlotUnitUnit` causes meaningful state change
- proposed `NarrativeStateUnit` delta is explicit
- output is routed to `ReviewUnit` before being treated as accepted progression

Must block when:

- progression is only prose without state change
- candidate fact changes bypass `FactLedgerUnit`

### 5.3 `ReviewUnit` Gates

Entry allowed when:

- a candidate packet, repaired packet, or degraded packet needs judgment
- input and output anchors are explicit enough to evaluate
- review target is named

Exit allowed when:

- route recommendation is explicit
- `ReviewIssueUnit` records or warning/reminder items are created when needed
- unresolved uncertainty is visible in `confidence_and_gaps`

Must block when:

- review would silently patch object state
- route recommendation hides missing object writeback

### 5.4 `RewriteUnit` Gates

Entry allowed when:

- a formal `ReviewIssueUnit` requires repair
- target packet is bounded
- affected object-state units are named

Exit allowed when:

- same-packet writeback status is explicit
- affected stable or working layers are synchronized as required
- repaired packet is routed to re-review or onward only after gate checks pass

Must block when:

- runtime-first repair tries to leave the current packet before formal synchronization
- handoff prose is used to compensate for missing writeback

---

## 6. Gate Dependency Order

The minimum orchestration order is:

1. read `handoff_header` and requested `next_route`
2. check `input_anchor` and serialized layer availability
3. allow or block workflow entry
4. coordinate active workflow envelope
5. check `output_anchor` and `change_set`
6. verify writeback and synchronization status
7. require re-review, allow movement, or escalate

This order keeps packet state before route movement.

---

## 7. Relationship To Serialization And Handoff

### 7.1 Relationship To Serialization

Orchestration consumes serialization status.

It asks:

- is required `stable_memory` available?
- is required `working_set` runnable?
- does `repair_control` contain blocking items?
- does `confidence` expose gaps that require review or rebuild?

It does not decide whether serialized content is true.

### 7.2 Relationship To Handoff

Orchestration consumes handoff sections.

It asks:

- does `handoff_header` identify movement?
- do `input_anchor` and `output_anchor` identify packet state?
- does `change_set` name object owners and target layers?
- do `open_items` block the route?
- does `confidence_and_gaps` require escalation?
- is `next_route` allowed by current gates?

It does not replace the handoff packet or hide route reason in runtime behavior.

---

## 8. Lock Inheritance

### 8.1 Track 1: `FactLedger` Hard-Fact Integrity

`OrchestrationGateUnit` must not advance a packet as if a hard fact were synchronized unless `FactLedgerUnit` admission and required serialization writeback are explicit.

Working-state pressure, handoff prose, and confidence notes are not hard facts.

Reject any orchestration design that treats route movement as fact admission.

### 8.2 Track 2: Bounded Runtime-First `Rewrite`

`OrchestrationGateUnit` must block `RewriteUnit` output from moving forward until same-packet synchronization is complete.

`open_items`, dense handoff prose, or repair notes cannot substitute for formal writeback.

Reject any orchestration design that lets runtime-first repair become an alternate default order.

### 8.3 Track 3: `CharacterModel` Evidence Leakback

`OrchestrationGateUnit` must not reduce handoff or routing risk by expanding `CharacterModelUnit` field bodies.

Supporting evidence stays in event, state, handoff, review, or confidence context.

Reject any orchestration design that broadens role-side summaries as a gating shortcut.

---

## 9. Minimal Acceptance Checks

The orchestration gate map is acceptable if all answers below are "yes".

1. Does every gate layer have a named owner and bounded output?
2. Does entry gating depend on serialized state and handoff anchors rather than prose summary?
3. Does execution coordination avoid replacing workflow-specific judgment?
4. Does writeback verification block movement when object-layer sync is incomplete?
5. Does escalation keep `RebuildUnit` as an escalation path, not routine continuation?
6. Does orchestration consume `next_route` without turning it into a rule override?
7. Can no-regression acceptance tests be written from these gates without inventing another core object?

---

## 10. What This Enables Next

This map enables the final implementation-planning output to define no-regression acceptance tests across units, serialization, handoff, and orchestration.

Recommended next output:

1. no-regression acceptance test list: `docs/00_project/21_no_regression_acceptance_test_list.md`

The test list should use the gate outputs in this file unless a real responsibility contradiction is found.

---

## 11. One-Sentence Summary

The orchestration gate map assigns entry, execution, writeback, and escalation gates to `OrchestrationGateUnit` while preventing orchestration from becoming truth ownership, review logic, or prose compensation.
