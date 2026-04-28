# Context Packaging Decisions

## Purpose

This file consolidates the project-level decisions about context packaging for the foundation phase.

It is not repeating the detailed steps of each workflow.
It fixes the higher-level questions:

- why workflow context packages must be treated as formal interfaces
- what kinds of context packages the system should distinguish
- what each main workflow must minimally read
- what each main workflow must minimally hand off
- why full-history loading should not be the default operating mode

This file mainly affects:

- `docs/04_workflows/01_rebuild_workflow.md`
- `docs/04_workflows/02_review_workflow.md`
- `docs/04_workflows/03_continue_workflow.md`
- `docs/04_workflows/04_rewrite_workflow.md`
- `docs/02_data_models/09_field_rules.md`
- `docs/00_project/05_narrative_agent_harness.md`

---

## 1. What This File Is Fixing

The project has already introduced context-package guidance into the main workflows.

However, without a decision-layer consolidation, those additions still risk being interpreted as:

- local wording choices
- workflow-specific style preferences
- non-binding explanations

This file makes the opposite choice:

workflow context packages are now treated as part of the system's operating contract.

---

## 2. Current Decisions That Need To Be Fixed

The current phase most needs stable decisions on these questions:

1. Should workflow context packages be treated as formal interfaces or just local descriptions
2. Should a workflow load full history by default
3. What package layers should the system distinguish
4. What is the minimum handoff package between workflows
5. How should context packages relate to memory tiers

---

## 3. DEC-20260326-56

### Decision Title

Workflow context packages are treated as formal operating interfaces, not optional explanatory prose

### Decision Type

`workflow`

### Decision Status

`adopted`

### Background Problem

The project has reached a point where workflow stability depends on how context is loaded, bounded, and handed off.

If context packaging remains informal, different agents or future implementations may:

- load too much history
- load the wrong layers
- skip required context
- hand off ambiguous results

### Options Considered

- Option A: keep context-package wording as workflow-local explanation only
- Option B: treat context packages as part of workflow operating contracts

### Final Choice

Adopt Option B.

### Reasoning

1. Long-form narrative work is a long-context task
2. Long-context tasks fail less often because of missing words and more often because of unstable state loading and handoff
3. The project is already moving toward an agent-harness model, so informal context rules are no longer sufficient
4. Formalizing context packages now reduces future drift in schemas, workflows, and examples

### Impact Scope

- all main workflows
- field rules
- future example and experiment design

### Risk / To Verify

- later implementation phases may need stricter serialization formats than the current conceptual layer

### Follow-up Action

`keep`

---

## 4. DEC-20260326-57

### Decision Title

The system distinguishes four package layers: working set, stable constraints, repair/history, and confidence

### Decision Type

`workflow`

### Decision Status

`adopted`

### Background Problem

Before this decision, the project had memory-layer thinking but not one fixed package-layer vocabulary for workflow operation.

Without a shared vocabulary, the same information can be loaded differently by different workflows, producing drift.

### Options Considered

- Option A: let each workflow invent its own package taxonomy
- Option B: define one cross-workflow package-layer vocabulary

### Final Choice

Adopt Option B.

### Package Layers

#### 4.1 Working Set Package

Carries what is directly needed for the current operation.

Typical examples:

- current `NarrativeState`
- active characters
- current goal
- current conflict

#### 4.2 Stable Constraint Package

Carries long-term constraints that must survive compression.

Typical examples:

- `WorldModel`
- stable `CharacterModel` baselines
- relevant `FactLedger`
- relevant `ForeshadowGraph`

#### 4.3 Repair / History Package

Carries near-history and unresolved repair signals.

Typical examples:

- previous `PlotUnit` chain
- open `ReviewIssue`
- unresolved warning
- local plan summary

#### 4.4 Confidence Package

Carries what the current workflow knows about completeness and certainty.

Typical examples:

- input completeness
- confidence level
- known gaps
- conflict markers

### Reasoning

1. This vocabulary is broad enough to cover all four main workflows
2. It matches the project's memory-tier direction without collapsing memory and operation into one thing
3. It supports future compression, rebuild, and handoff design

### Impact Scope

- `Rebuild`
- `Continue`
- `Review`
- `Rewrite`
- `Field Rules`

### Risk / To Verify

- some workflows may later need sub-packages, but the top-level four-way split should remain stable

### Follow-up Action

`keep`

---

## 5. DEC-20260326-58

### Decision Title

Full-history loading is not the default mode; bounded packages plus stable memory layers are the default mode

### Decision Type

`workflow`

### Decision Status

`adopted`

### Background Problem

A tempting operating mode is to keep loading more prior text whenever uncertainty appears.

That feels safe, but in long-form work it quickly becomes unstable:

- context balloons
- important constraints become harder to track
- workflows stop having meaningful boundaries

### Options Considered

- Option A: default to full-history loading whenever possible
- Option B: default to bounded packages and use stable memory layers for continuity

### Final Choice

Adopt Option B.

### Reasoning

1. The project is explicitly trying to avoid impression-based continuation
2. Stable continuity should come from state objects and controlled packages, not unlimited rereading
3. Full-history loading should remain an escalation path, not the normal path
4. This decision aligns with `Rebuild` as recovery/compilation and `Review` as drift control

### Practical Meaning

- `Continue` should prefer working set + relevant constraints + near history
- `Review` should prefer judgment-relevant context, not unlimited story recall
- `Rewrite` should prefer root-cause packages and dependency-relevant history
- `Rebuild` is the correct response when bounded packages are no longer enough

### Impact Scope

- all main workflows
- examples
- future experiments

### Risk / To Verify

- the escalation threshold from bounded operation to `Rebuild` still needs more pressure testing

### Follow-up Action

`watch`

---

## 6. DEC-20260326-59

### Decision Title

Workflow handoff requires a minimal explicit output package; "implicit understanding" is not sufficient

### Decision Type

`workflow`

### Decision Status

`adopted`

### Background Problem

Even when a workflow reaches a sound local conclusion, the next workflow can still fail if the handoff is vague.

Typical failure modes:

- `Review` cannot tell what exactly changed
- `Rewrite` cannot tell which issue it is supposed to fix
- `Continue` cannot tell what warning is still pending

### Options Considered

- Option A: rely on prose summary and local inference
- Option B: require a minimum explicit handoff package

### Final Choice

Adopt Option B.

### Minimum Handoff Expectations

Every workflow handoff should make it easy to answer:

1. what object or state the workflow started from
2. what object or state it produced
3. what was updated
4. what remains unresolved
5. what the next workflow is expected to do

### Workflow-Specific Minimums

#### Rebuild Handoff

Should expose:

- reconstruction level
- current confidence
- static memory produced
- whether a runnable `NarrativeState` exists

#### Continue Handoff

Should expose:

- input state
- output state
- changed objects
- unresolved warning / issue

#### Review Handoff

Should expose:

- review conclusion
- failure or warning classification
- generated `ReviewIssue` if any
- route to `Continue` / `Rewrite` / `Replan`

#### Rewrite Handoff

Should expose:

- issue repaired
- objects modified
- synchronized dependencies
- residual risk before re-review

### Reasoning

1. Handoff quality is part of workflow quality
2. Without explicit handoff, later workflows re-infer too much
3. Re-inference is one of the main sources of long-context drift

### Additional Constraint From Later Pressure Tests

An explicit handoff package is necessary, but it is not allowed to compensate for an incomplete object sync.

In particular:

- if `Rewrite` has already made a new hard fact explicit, handoff detail cannot stand in for same-packet `FactLedger` writeback
- handoff prose cannot be used to smuggle stable constraints into the next workflow when the formal object layer is still stale
- `CharacterModel` detail cannot be expanded just to reduce handoff risk

This means:

- better handoff density is not a substitute for repair completeness

### Impact Scope

- all main workflows
- examples
- future implementation interfaces

### Risk / To Verify

- later implementation phases may require a stricter field-level handoff schema

### Follow-up Action

`patch`

---

## 7. DEC-20260326-60

### Decision Title

Context packages must stay aligned with memory tiers; package design and field design are not independent

### Decision Type

`workflow`

### Decision Status

`adopted`

### Background Problem

The project already distinguishes objects by responsibility, and `Field Rules` now includes a memory-tier perspective.

Without an explicit decision, workflows may still package fields in ways that blur:

- long-term memory
- current working state
- temporary inference
- formal repair state

### Options Considered

- Option A: treat package design and field design as separate concerns
- Option B: require package design to respect memory tiers

### Final Choice

Adopt Option B.

### Practical Meaning

- stable memory should not be overwritten by repair notes or temporary inferences
- current working state should not pretend to be long-term fact storage
- warning and issue layers should not silently replace object-layer memory
- field placement and workflow packaging should be checked together

### Reasoning

1. Memory tiers are only useful if workflows actually respect them
2. Package drift will eventually create object drift
3. This decision reinforces why `Field Rules` and workflow docs must evolve together

### Impact Scope

- `docs/02_data_models/09_field_rules.md`
- all workflow docs
- future schema refinements

### Risk / To Verify

- `ReviewReminder` 已被确立为轻量正式层，但不同 reminder 类型的 handoff 窗口仍需实验压实

### Follow-up Action

`re-evaluate`

---

## 8. Recommended Immediate Follow-up

Now that context packaging has been promoted to the decision layer, the most natural next steps are:

- pressure-test repeated `degradation -> rebuild -> review -> continue` chains so handoff packages keep hard constraints separate from current pressures
- add mixed-family handoff-compression examples that prove `FactLedger` facts survive second-recovery packaging without being flattened into vague prose
- keep extending context-loss, rebuild-recovery, and handoff-stability experiments before implementation pressure starts shaping the package layer

---

## 9. One-Sentence Summary

`08_context_packaging_decisions.md` fixes the current project consensus that workflow context is not an informal convenience layer, but a formal operating interface for sustained narrative work.
