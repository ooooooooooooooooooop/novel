# Runtime Orchestration Boundary Note

## Purpose

This file is an implementation-planning note for runtime orchestration boundaries.

It does not define an implementation architecture.
It defines what orchestration is allowed to coordinate and what it must not absorb.

Its purpose is to keep future runtime planning aligned with:

- workflow order
- memory-tier separation
- handoff discipline
- boundary-lock inheritance

---

## 1. Orchestration Goal

The goal of orchestration is not to replace workflow logic.

The goal is to coordinate:

- which workflow runs when
- what package must be loaded
- what package must be written back
- when escalation is required
- when re-review is required

One sentence:

orchestration should schedule and gate workflow movement, not redefine narrative truth.

---

## 2. What Orchestration May Coordinate

The first orchestration boundary candidate may coordinate the following things.

### 2.1 Workflow Routing

It may coordinate:

- `Rebuild -> Review -> Continue / Rewrite / Replan`
- entry conditions for each workflow
- return paths after `Review` or `Rewrite`

### 2.2 Package Loading

It may coordinate:

- which serialized package layers must be loaded
- whether bounded context is sufficient
- whether escalation to `Rebuild` is needed

### 2.3 Writeback Gating

It may coordinate:

- whether required same-packet sync has completed
- whether a packet may move forward to next workflow
- whether re-review is mandatory

### 2.4 Retry And Escalation

It may coordinate:

- when bounded operation has failed
- when warning/reminder state has upgraded to repair state
- when repeated local fixes should stop and stronger review or replanning should begin

---

## 3. What Orchestration Must Not Absorb

The first orchestration boundary candidate must not absorb these responsibilities.

### 3.1 Object Truth Ownership

Orchestration must not decide:

- what counts as hard fact
- what belongs in `CharacterModel`
- what counts as current `NarrativeState`

Those remain object-layer and rule-layer decisions.

### 3.2 Workflow-Specific Judgment Logic

Orchestration must not silently replace:

- review classification logic
- rewrite root-cause logic
- fact admission thresholds

It may route based on those judgments, but it does not author them.

### 3.3 Prose Compensation

Orchestration must not let:

- denser summaries
- broader package carry
- longer chat memory

act as substitutes for missing formal writeback.

### 3.4 Convenience-Layer Memory Collapse

Orchestration must not create a hidden convenience layer that mixes:

- stable memory
- working state
- repair state
- confidence metadata

into one opaque runtime blob.

---

## 4. Candidate Orchestration Layers

The first orchestration boundary candidate should keep a small four-layer view.

### 4.1 Entry Gating Layer

Answers:

- can the requested workflow start
- is the required input package present
- is bounded operation still valid

### 4.2 Execution Coordination Layer

Answers:

- which workflow is active
- which package slices were loaded
- which outputs are expected

### 4.3 Writeback Verification Layer

Answers:

- did required object sync complete
- did same-packet locks hold
- is the next route allowed

### 4.4 Escalation Layer

Answers:

- should the packet go to `Review`
- should it go to `Rewrite`
- should it go back to `Rebuild`
- should local repair stop and stronger replanning begin

---

## 5. Candidate Workflow Coordination Rules

### 5.1 `Rebuild`

Orchestration should treat `Rebuild` as:

- the recovery path when bounded packages are insufficient
- the workflow that can re-establish runnable state and stable memory alignment

Orchestration should not treat `Rebuild` as:

- a routine substitute for disciplined bounded operation

### 5.2 `Continue`

Orchestration should treat `Continue` as:

- controlled state extension from a valid current state

It should require:

- current runnable `working_set`
- relevant `stable_memory`
- relevant `repair_control`

### 5.3 `Review`

Orchestration should treat `Review` as:

- the main control loop and route authority

It should require:

- explicit review target
- judgment-relevant context
- output route selection before leaving the packet

### 5.4 `Rewrite`

Orchestration should treat `Rewrite` as:

- targeted repair under issue control

It should require:

- clear issue anchor
- root-cause object scope
- same-packet synchronization before re-review

---

## 6. Lock-Sensitive Orchestration Rules

Any orchestration candidate should explicitly preserve these locks.

### 6.1 Track 1 Rule

Orchestration must not advance a packet as if a hard fact were synchronized when it exists only in prose or working-state form.

### 6.2 Track 2 Rule

Orchestration must not allow bounded runtime-first `Rewrite` to escape same-packet formal sync and continue forward on handoff density alone.

### 6.3 Track 3 Rule

Orchestration must not solve handoff risk by broadening `CharacterModel` payloads with supporting evidence.

---

## 7. Candidate Orchestration Rejection Tests

Reject an orchestration proposal if it makes any of these easier:

1. skipping `Review` because runtime state "looks fine"
2. carrying forward stale object state with richer summaries
3. treating `Rebuild` as the normal path instead of escalation
4. merging stable memory, working state, and repair state into one convenience runtime object
5. using orchestration as a backdoor to reopen locked boundary decisions

---

## 8. What This Note Still Does Not Decide

This note still does not decide:

- process model
- queue design
- concurrency model
- service boundaries
- deployment topology

Those belong to later implementation planning.

---

## 9. Recommended Next Note

After this orchestration note, the most natural next planning artifact is:

- `no-regression verification checklist`

because the repo now has serialization, handoff, and orchestration candidates that need one shared regression guard.

---

## 10. One-Sentence Summary

The first orchestration boundary candidate should coordinate workflow movement and packet gating while leaving object truth, rule judgment, and memory ownership where they already belong.
