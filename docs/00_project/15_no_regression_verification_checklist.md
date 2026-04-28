# No-Regression Verification Checklist

## Purpose

This file is the shared no-regression checklist for transition planning.

It turns the current boundary locks and planning artifacts into a small verification layer that future implementation planning must not violate.

It is not:

- a test framework
- an implementation test suite
- a final QA protocol

It is:

- a planning-stage guardrail checklist

---

## 1. What This Checklist Protects

This checklist protects four things at once:

1. Track 1 lock
2. Track 2 lock
3. Track 3 lock
4. the first planning artifact chain:
   - serialization candidate
   - handoff schema candidate
   - runtime orchestration boundary note

If a future implementation-planning proposal fails this checklist, it should be treated as a regression risk, not just a style difference.

---

## 2. Track 1 Checks: `FactLedger` Hard-Fact Integrity

Reject a proposal if any answer below is "yes".

### 2.1 Hard Fact Downgrade

- Does the proposal allow established hard facts to live mainly in prose, summary, or working-state commentary?

### 2.2 Working-State Substitution

- Does the proposal let `working_set` act as the practical replacement for `FactLedger` truth?

### 2.3 Handoff Substitution

- Does the proposal rely on handoff payload richness to compensate for missing `FactLedger` writeback?

### 2.4 Mixed-Layer Compression

- Does the proposal collapse hard facts, temporary pressure, and unresolved inference into one summary layer?

Pass condition:

- hard fact remains object-layer truth and is not substituted by prose, working state, or handoff density

---

## 3. Track 2 Checks: bounded runtime-first `Rewrite`

Reject a proposal if any answer below is "yes".

### 3.1 Packet Escape

- Does the proposal allow bounded runtime-first `Rewrite` to leave the current packet before formal synchronization is complete?

### 3.2 Review-Late Sync

- Does the proposal let a packet move forward first and update hard facts only after later review?

### 3.3 Handoff Compensation

- Does the proposal treat richer handoff as a valid substitute for same-packet writeback?

### 3.4 Root-Cause Drift

- Does the proposal let runtime-first repair become a practical alternate default order rather than a narrow local exception?

Pass condition:

- runtime-first repair stays bounded, same-packet, root-cause-local, and never escapes formal synchronization requirements

---

## 4. Track 3 Checks: `CharacterModel` Evidence Leakback

Reject a proposal if any answer below is "yes".

### 4.1 Evidence Backfill

- Does the proposal push supporting evidence, recent sequence logic, or rollback explanation into `CharacterModel` field bodies?

### 4.2 Handoff Insurance Bloat

- Does the proposal expand `CharacterModel` mainly to reduce handoff risk?

### 4.3 Role-Side Summary Collapse

- Does the proposal treat `CharacterModel` as a convenience archive for current operational pressure?

### 4.4 Cross-Field Compression

- Does the proposal blur long-term conclusions and their supporting evidence across `knowledge_state`, `relations`, `misinformation`, `self_image`, or `arc_stage`?

Pass condition:

- `CharacterModel` keeps compressed long-term conclusions only, while evidence stays outside field bodies

---

## 5. Serialization Candidate Checks

Reject a proposal if any answer below is "yes".

### 5.1 Memory-Tier Collapse

- Does the proposal merge stable memory, working state, repair state, and confidence into one opaque storage object?

### 5.2 Confidence-As-Truth

- Does the proposal blur completeness/confidence metadata into object truth?

### 5.3 Repair-In-Stable-Memory

- Does the proposal store issue/reminder commentary inside stable memory objects?

Pass condition:

- the four-layer serialization split remains recognizable and operational

---

## 6. Handoff Schema Checks

Reject a proposal if any answer below is "yes".

### 6.1 Missing Delta Structure

- Does the proposal lose explicit `change_set`, `open_items`, or `confidence_and_gaps` structure in favor of broader summaries?

### 6.2 Hidden Gaps

- Does the proposal hide uncertainty, conflict markers, or incomplete reconstruction inside generic prose?

### 6.3 Stable Constraint Smuggling

- Does the proposal make handoff commentary the de facto home of stable constraints?

Pass condition:

- handoff remains explicit, delta-oriented, and separate from object truth

---

## 7. Runtime Orchestration Checks

Reject a proposal if any answer below is "yes".

### 7.1 Orchestration As Truth Layer

- Does the proposal let orchestration decide what counts as fact, role summary, or current state?

### 7.2 Orchestration As Rule Override

- Does the proposal let orchestration silently override review, rewrite, or fact-admission judgments?

### 7.3 Orchestration As Prose Shortcut

- Does the proposal allow orchestration to carry stale object state forward because the packet summary looks rich enough?

### 7.4 Rebuild Normalization

- Does the proposal treat `Rebuild` as a routine path instead of an escalation path when bounded packages fail?

Pass condition:

- orchestration coordinates workflow movement and packet gating without becoming a hidden truth or shortcut layer

---

## 8. Cross-Artifact Consistency Checks

Reject a proposal if any answer below is "yes".

### 8.1 Serialization-Handoff Mismatch

- Does the proposed handoff shape assume data that the serialization candidate no longer keeps separated?

### 8.2 Handoff-Orchestration Mismatch

- Does the orchestration proposal depend on route or sync shortcuts that the handoff candidate explicitly forbids?

### 8.3 Lock-Artifact Mismatch

- Does any planning artifact quietly weaken Track 1, Track 2, or Track 3 while still claiming compatibility?

Pass condition:

- serialization, handoff, orchestration, and inherited locks still point in the same direction

---

## 9. Minimum Use Rule

Before accepting any new implementation-planning note, check:

1. Track 1 section
2. Track 2 section
3. Track 3 section
4. the relevant artifact section
5. cross-artifact consistency

If any section fails, the planning note should be revised before being treated as the next stable planning artifact.

---

## 10. One-Sentence Summary

This checklist exists to make sure future implementation planning inherits current boundary locks through serialization, handoff, and orchestration choices instead of quietly regressing through convenience.
