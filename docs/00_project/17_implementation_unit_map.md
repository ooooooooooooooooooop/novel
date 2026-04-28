# Implementation Unit Map

## Purpose

This file defines the first bounded implementation unit map.

It answers which implementation units should exist before the project assigns serialization, handoff, orchestration, or no-regression responsibilities.

It does not define code modules, package names, storage technology, or runtime framework.

---

## 1. Core Goal

The core goal is to make future implementation responsibilities explicit without reopening foundation boundaries.

The simplest useful split is not pure object split, pure workflow split, or pure technical-layer split.

The first implementation map should use a hybrid split:

- object units own narrative truth and state shape
- workflow units own allowed state movement
- boundary units own transfer, gating, and verification responsibilities

This keeps state first and text second.

---

## 2. Split Decision

### 2.1 Why Not Object-Only

An object-only split is too static.

It can define `WorkSpec`, `CharacterModel`, or `FactLedger`, but it does not explain how `Rebuild`, `Review`, `Continue`, or `Rewrite` move state.

If used alone, it would hide workflow responsibility inside object methods or storage routines.

Rejected because workflow route and writeback order are central design rules.

### 2.2 Why Not Workflow-Only

A workflow-only split is too procedural.

It can define `Review` or `Rewrite`, but it risks letting workflows become the owner of facts, character summaries, or current state.

If used alone, it would weaken object ownership and make Track 1 / Track 3 easier to violate.

Rejected because object truth must remain separate from workflow movement.

### 2.3 Why Not Technical-Layer-Only

A technical-layer split is premature.

Storage, state management, generation, review, and orchestration are useful implementation concerns, but they do not by themselves preserve narrative ownership.

If used too early, they encourage choosing abstractions before responsibility boundaries are stable.

Rejected because stack and runtime structure are still deferred.

### 2.4 Chosen Split

Use three implementation-unit families:

1. object-state units
2. workflow-action units
3. boundary-control units

These are implementation units, not new core narrative objects.

---

## 3. Unit Family A: Object-State Units

Object-state units own schemas, admissible fields, and object-level update boundaries.

They do not own workflow routing.

They do not decide whether prose is good.


| Unit | Owns | Inputs | Outputs | Must Not Do |
|---|---|---|---|---|
| `WorkSpecUnit` | project-level narrative constraints and goals | user/project intent, accepted scope decisions | bounded work constraints | decide runtime route or store transient repair pressure |
| `WorldModelUnit` | world legality and stable world constraints | accepted world facts, rule updates | world constraints available to state transition | absorb character belief or current tactical pressure |
| `CharacterModelUnit` | compressed long-term character conclusions | admitted long-term knowledge, relations, self-image, arc-stage changes | stable character summary fields | store supporting evidence, recent sequence logic, or handoff insurance |
| `NarrativeStateUnit` | current working narrative state | prior state, valid state deltas, current pressures | updated current state | become stable fact ledger or long-term character archive |
| `PlotUnitUnit` | event-level progression unit | input state, character decision, world constraint, conflict pressure | event record and output-state delta | count as valid without meaningful state change |
| `FactLedgerUnit` | hard facts that already count in the world | admitted fact changes | stable fact entries | store suspicion, unresolved inference, or confidence commentary as fact |
| `ForeshadowGraphUnit` | promises, setup/payoff links, unresolved narrative obligations | accepted foreshadow entries and payoff updates | open and resolved promise graph | replace review routing or fact admission |
| `ReviewIssueUnit` | formal review issues and fix routing metadata | review findings, issue classification | issue records for warning, rewrite, or replan routing | become a generic comment bucket or hidden repair state |

### 3.1 Object-State Unit Dependency Order

The minimum dependency order is:

1. `WorkSpecUnit`
2. `WorldModelUnit`, `CharacterModelUnit`, `FactLedgerUnit`, `ForeshadowGraphUnit`
3. `NarrativeStateUnit`
4. `PlotUnitUnit`
5. `ReviewIssueUnit`

Reason:

- `WorkSpecUnit` frames the project constraints
- stable world, character, fact, and promise objects constrain current state
- `NarrativeStateUnit` needs those constraints before representing current state
- `PlotUnitUnit` needs input state before validating progression
- `ReviewIssueUnit` evaluates outputs after candidate progression exists

---

## 4. Unit Family B: Workflow-Action Units

Workflow-action units own the allowed movement between states.

They consume and update object-state units through explicit deltas.

They do not become the source of object truth.

| Unit | Owns | Inputs | Outputs | Depends On | Must Not Do |
|---|---|---|---|---|---|
| `RebuildUnit` | reconstructing runnable object state from existing material | source text, prior objects if available, confidence gaps | reconstructed object packet, unresolved gaps | object-state units, handoff boundary | normalize rebuild as routine continuation |
| `ReviewUnit` | classifying validity and routing next action | candidate packet, object states, review rules | `ReviewIssue` records, reminders or route recommendation | object-state units, no-regression checks | silently patch state or facts |
| `ContinueUnit` | proposing next effective progression | current state, character decision pressure, world constraints, open promises | candidate `PlotUnit`, proposed state deltas | `NarrativeStateUnit`, `PlotUnitUnit`, `WorldModelUnit`, `CharacterModelUnit` | create non-effective progression or bypass review |
| `RewriteUnit` | applying minimal issue-driven repair | formal issue, bounded packet, target object deltas | repaired packet and synchronized writeback | `ReviewIssueUnit`, affected object-state units | let runtime-first repair escape same-packet sync |

### 4.1 Workflow Dependency Order

The normal loop order is:

1. `ContinueUnit`
2. `ReviewUnit`
3. `RewriteUnit` if formal issue-driven repair is required
4. `RebuildUnit` only when runnable state cannot be trusted or recovered locally

Reason:

- `Continue` creates candidate progression
- `Review` decides whether it is valid, warning-worthy, repairable, or structurally broken
- `Rewrite` repairs bounded issue-driven failures
- `Rebuild` is an escalation path, not a default continuation step

---

## 5. Unit Family C: Boundary-Control Units

Boundary-control units coordinate transfer and verification.

They do not own narrative truth.

They are included now only so later responsibility maps have a place to attach decisions.

| Unit | Owns | Inputs | Outputs | Must Not Do |
|---|---|---|---|---|
| `SerializationBoundaryUnit` | mapping object-state units into stable, working, repair, and confidence tiers | object packet, repair state, confidence gaps | serialization responsibility map | flatten all state into one opaque payload |
| `HandoffBoundaryUnit` | explicit cross-workflow packet structure | source workflow outputs, change sets, open items, confidence gaps | handoff responsibility map | use dense prose as substitute for object writeback |
| `OrchestrationGateUnit` | workflow entry, exit, escalation, and packet-gating checks | workflow route proposal, packet state, issue status | orchestration gate map | decide object truth or override review rules |
| `NoRegressionValidationUnit` | acceptance checks for lock-sensitive behavior | candidate plan or implementation output | no-regression acceptance test list | become a general quality checklist detached from locks |

### 5.1 Boundary Dependency Order

The minimum dependency order is:

1. `SerializationBoundaryUnit`
2. `HandoffBoundaryUnit`
3. `OrchestrationGateUnit`
4. `NoRegressionValidationUnit`

Reason:

- serialization defines what can be persisted or reconstructed
- handoff defines what moves between workflows
- orchestration gates movement using serialized and handoff-visible state
- no-regression checks verify that none of those choices weaken the locks

---

## 6. Cross-Unit Dependency Map

The first full dependency path should be:

1. define object-state unit responsibilities
2. define serialization responsibility from object-state units
3. define workflow-action unit inputs and outputs
4. define handoff responsibility between workflow-action units
5. define orchestration gates around workflow movement
6. define no-regression acceptance checks across all units

This order keeps object ownership before transfer mechanics.

---

## 7. Lock Inheritance

### 7.1 Track 1: `FactLedger` Hard-Fact Integrity

The unit map preserves Track 1 by assigning hard-fact ownership only to `FactLedgerUnit`.

Other units may propose, route, or carry candidate fact changes, but they do not make unresolved inference into fact.

Reject any later implementation plan where serialization, handoff, orchestration, or workflow code treats prose density as fact synchronization.

### 7.2 Track 2: Bounded Runtime-First `Rewrite`

The unit map preserves Track 2 by assigning repair execution to `RewriteUnit` and movement gating to `OrchestrationGateUnit`.

`RewriteUnit` may start with a bounded local packet repair only when a formal issue requires it.

`OrchestrationGateUnit` must block forward movement until same-packet writeback is synchronized.

### 7.3 Track 3: `CharacterModel` Evidence Leakback

The unit map preserves Track 3 by assigning long-term character conclusions only to `CharacterModelUnit`.

Supporting evidence belongs in `PlotUnitUnit`, `NarrativeStateUnit`, handoff supporting context, or review context.

Reject any later plan that expands `CharacterModelUnit` mainly to reduce handoff risk.

---

## 8. Minimal Acceptance Checks

The implementation unit map is acceptable if all answers below are "yes".

1. Can each core object point to exactly one object-state unit as its primary owner?
2. Can each workflow point to exactly one workflow-action unit as its route owner?
3. Can serialization, handoff, orchestration, and validation attach to named boundary-control units?
4. Does `FactLedgerUnit` remain the only hard-fact owner?
5. Does `RewriteUnit` remain bounded by same-packet synchronization?
6. Does `CharacterModelUnit` remain limited to compressed long-term conclusions?
7. Can the next four planning outputs be written without inventing another core object?

---

## 9. What This Enables Next

This map enables the next planning documents to assign responsibility without redefining the system.

Recommended next outputs:

1. serialization responsibility map: `docs/00_project/18_serialization_responsibility_map.md`
2. workflow handoff responsibility map: `docs/00_project/19_workflow_handoff_responsibility_map.md`
3. orchestration gate map: `docs/00_project/20_orchestration_gate_map.md`
4. no-regression acceptance test list: `docs/00_project/21_no_regression_acceptance_test_list.md`

Each should use the unit names in this file unless a real responsibility gap is proven.

---

## 10. One-Sentence Summary

The first implementation unit map uses object-state units for truth ownership, workflow-action units for state movement, and boundary-control units for transfer and gating, without weakening the three inherited locks.
