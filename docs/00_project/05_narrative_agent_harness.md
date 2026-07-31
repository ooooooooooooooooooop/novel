# Narrative Agent Harness

## Purpose

This file explains why the current project should be treated not only as a narrative design system, but also as a harness layer for long-context narrative work.

Its purpose is not only conceptual.
It defines concrete design guidance for the current foundation phase.

---

## 1. Core Claim

Long-form fiction is a long-context task.

That means the central problem is not only:

- how to generate the next paragraph

It is also:

- how to keep the model working coherently across many rounds
- how to preserve important state without carrying the whole text
- how to recover structure from text when context is partial
- how to prevent drift in facts, character logic, promises, and world legality

So this repository is not only designing a narrative system.
It is also designing a work harness for narrative agents.

---

## 2. Why This Matters Now

This perspective changes current design priorities.

Without it, the project can drift toward:

- concept collections
- isolated schemas
- workflow descriptions that look correct but do not support sustained use

With it, the project is forced to ask:

- can this object act as a stable external state interface
- can this workflow support repeated multi-round use
- can this rule survive context compression
- can this example prove the design works under long-context pressure

---

## 3. Immediate Design Implications

The current project should treat key objects as working interfaces, not only concept definitions.

### 3.1 `NarrativeState`

It is not only a story-state object.
It is the current working set for the model.

So its design should help answer:

- what the model must know now
- what the model can ignore for this round
- what changed since the previous step

### 3.2 `FactLedger`

It is not only a record of facts.
It is the stable long-term memory layer for hard facts.

So its design should help answer:

- what must survive context compression
- what later rounds can trust without rereading full text
- what should not be mixed with temporary situation state

### 3.3 `CharacterModel`

It is not only a character sheet.
It is the long-term behavioral baseline for future decisions.

So its design should help answer:

- what persists across scenes
- what is a stable trait versus temporary condition
- what later review passes can use to detect drift

### 3.4 `ForeshadowGraph`

It is not only a narrative-thread tracker.
It is the cross-round promise-management layer.

So its design should help answer:

- which open threads must stay visible across long spans
- which threads are active, latent, or already resolved
- which promises are at risk of being forgotten

### 3.5 `ReviewIssue`

It is not only an issue record.
It is the formal repair interface between review and future action.

So its design should help answer:

- what exactly failed
- what kind of repair is needed
- whether the problem belongs to `Rewrite` or `Replan`

---

## 4. Workflow Implications

The current workflows should be treated as context-management loops, not only task names.

### 4.1 `Rebuild`

`Rebuild` should be understood as a compiler step.

Its job is:

- reconstruct a usable object layer from text
- recover the minimum state required for future work
- turn raw narrative history into a structured working set

### 4.2 `Review`

`Review` should be understood as a control loop.

Its job is:

- detect drift
- classify failure
- decide whether the current result can continue
- create the formal repair entry if it cannot

### 4.3 `Continue`

`Continue` should be understood as controlled state extension.

Its job is not just to add text.
Its job is to add the next valid state change while keeping all relevant interfaces coherent.

### 4.4 `Rewrite`

`Rewrite` should be understood as targeted repair.

Its job is:

- repair a localized failure
- synchronize dependent state layers
- avoid unnecessary re-generation of unaffected parts

---

## 5. Guidance For Current Foundation Work

This perspective implies the current phase should prioritize the following work more explicitly.

### 5.1 Context Packaging Rules

The project should define, for each workflow:

- what must be loaded
- what may be omitted
- what is derived on demand
- what must be written back

Without this, workflows remain descriptive but not operationally stable.

### 5.2 Memory Tiering

The project should explicitly distinguish:

- stable long-term memory
- current working set
- temporary inference state
- formal repair state

At minimum, current design should keep clarifying the roles of:

- `FactLedger`
- `CharacterModel`
- `NarrativeState`
- `ForeshadowGraph`
- `ReviewIssue`

### 5.3 Compression-Safe Boundaries

A field or rule is stronger if it survives context compression.

Current design should prefer representations that remain usable when full prior text is not loaded.

### 5.4 Recovery From Partial Context

The system should assume that later work may start with:

- incomplete text context
- incomplete memory load
- partial rebuild results

So object and workflow design should support graceful recovery instead of assuming perfect continuity.

### 5.5 Drift Detection

The project should value designs that make drift easier to detect:

- fact drift
- character drift
- world drift
- promise drift
- knowledge-boundary drift

If drift cannot be detected clearly, the system will not remain usable over long runs.

---

## 6. What This Changes In Document Design

This perspective suggests adding or strengthening specific documentation questions.

### 6.1 For object files

Ask not only:

- what is this object

Also ask:

- what role does this object play in long-term agent work
- is it long-term memory, current working state, or repair/control state
- what should survive compression into this object

### 6.2 For workflow files

Ask not only:

- what are the steps

Also ask:

- what context package does this workflow require
- what state package does it output
- what drift does it guard against

### 6.3 For field rules

Ask not only:

- what kind of field is this

Also ask:

- is this field stable across rounds
- should it survive compression
- does it belong to memory, working state, or derived review state

### 6.4 For examples

Ask not only:

- does this example illustrate the concept

Also ask:

- would this design still work after many rounds
- would it survive context loss and rebuild
- would review still catch the failure clearly

---

## 7. Current Priority Shifts

If this harness perspective is taken seriously, current priorities should shift slightly.

More important now:

- context packaging
- memory-tier clarity
- rebuild quality
- review as drift control
- examples as pressure tests

Less important now:

- adding many new concepts
- broadening feature scope
- optimizing for future implementation details too early

---

## 8. Near-Term Questions It Creates

This perspective makes several current open questions more important:

- what exactly belongs in `FactLedger` versus `NarrativeState`
- how should knowledge state be distributed across objects
- how `ReviewReminder` should be pressure-tested and when it should escalate
- what the minimum workflow input package is for stable continuation
- how examples should simulate long-context degradation and recovery

These are not side questions.
They are harness questions.

---

## 9. Current Applicability Assessment

The current project is highly suitable for a harness-coding direction.

This is not only because the repository now uses the word `harness`.
It is because the actual problem shape already matches harness work:

- long-form fiction here is treated as sustained multi-round state work
- continuity depends on bounded context loading, not full-history rereading
- later work must survive context loss, rebuild, review, and repair
- the main failure mode is drift in objects, rules, and handoff, not only weak prose

At the current phase, the project is already harness-oriented in several concrete ways.

### 9.1 Where the fit is already strong

- key objects are increasingly defined as external working interfaces, not only concept labels
- the main workflows are increasingly defined as context-management loops
- context packages are already treated as formal operating contracts
- field rules already use memory-tier thinking
- examples have started pressure-testing degradation, reminder handoff, and rebuild recovery

In this sense, the project is not merely compatible with harness coding.
It already needs harness thinking to avoid future drift.

### 9.2 Where the current design is still incomplete

However, the repository is not yet a fully operational harness specification.

The main gaps are:

- workflow context packages are defined in strong prose, but not yet as one tighter cross-workflow handoff schema
- knowledge ownership is still unstable across `CharacterModel`, `NarrativeState`, and `FactLedger`
- relation ownership is still unstable across long-term model, runtime state, and ledger
- `ReviewReminder` escalation windows are still only partially fixed
- long-chain pressure tests are still thinner than the intended long-context use case

So the current state is best described as:

- a strong harness-oriented foundation
- not yet a fully hardened harness contract

### 9.3 What this means for current work

If the project takes harness coding seriously, current foundation work should prioritize:

- tightening workflow input and output packages
- clarifying object ownership at drift-prone boundaries
- making uncertainty and confidence first-class handoff content
- expanding repeated degradation / rebuild / continue pressure tests

It should deprioritize:

- adding many new objects
- broadening feature scope early
- discussing implementation architecture before the handoff model is stable

---

## 10. One-Sentence Summary

The current project is not only designing how a story is represented.
It is designing how a model can keep working on a story coherently over time.
