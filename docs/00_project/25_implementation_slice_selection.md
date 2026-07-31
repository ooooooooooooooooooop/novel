# Implementation Slice Selection

## Status

- Phase A core tasks: complete (A1 terminology, compose stub, audit walkthrough, extend walkthrough, compose walkthrough)
- Phase A formerly deferred items have since been closed or absorbed by later implementation work: A2 generative_indicia, A3 WorkSpec external hooks, and A4 compose walkthrough
- This document opens the bounded implementation slice selection track

## Purpose

Choose the first minimal end-to-end implementation slice that can be built and validated.

## Selection Criteria

1. Must stress-test at least one complex workflow
2. Must avoid unresolved long-range orchestration questions
3. Must align with current-phase priority (audit > extend > compose)
4. Must preserve Track 1, Track 2, Track 3
5. Must have a clear pass/fail validation target

## Candidate Analysis

### Candidate 1: Short-form audit (recommended)

**What it is**: Rebuild + Review loop for a short existing text (e.g., one arc of `示例小说甲`)

**Why recommended**:
- Input is existing complete text — no generation pressure, no compose-gap
- Short form avoids long-range orchestration stress
- Simultaneously stress-tests the two most complex workflows: `Rebuild` and `Review`
- Aligns with current-phase priority (audit > extend > compose)
- Per DEC-22: "先验证 Rebuild / Continue / Review / Rewrite，再考虑表达层"
- Explicitly defers text-generation pressure

**In scope**:
- `RebuildUnit`: reconstruct object state from short text
- `ReviewUnit`: classify validity and route
- `SerializationBoundaryUnit`: persist reconstructed layers
- `HandoffBoundaryUnit`: transfer between Rebuild and Review
- `OrchestrationGateUnit`: entry and writeback verification
- No-regression tests T1.1, T2.2, O3 (minimum set)

**Out of scope**:
- `ContinueUnit` (text generation deferred)
- `RewriteUnit` (repair deferred until review finds issues)
- Long-form orchestration (book → arc → chapter hierarchy)
- UI / product layer
- Model routing
- Deployment

### Candidate 2: Short-form extend

**What it is**: Rebuild + Continue + Review loop for a short continuation task

**Why not first**:
- Adds `ContinueUnit`, which introduces generation pressure
- Requires partial state input, which adds reconstruction complexity on top of candidate 1
- DEC-22 priority says audit before extend

**When to use**: Second slice, after audit slice validates Rebuild and Review

### Candidate 3: Short-form compose

**What it is**: WorkSpec-driven Continue + Review loop from zero text

**Why not first**:
- Lowest current-phase priority per DEC-22
- Exposes WorkSpec expressiveness gaps simultaneously with long-range orchestration
- Conflicts with DEC-22 explicit deferral

**When to use**: Third slice, after audit and extend close the basic loop

## Recommendation

**First slice: short-form audit**

| Property | Value |
|---|---|
| Slice name | `audit_short_form` |
| Workflows | `Rebuild` + `Review` |
| Input | Existing short text (one arc) |
| Output | Reconstructed object packet + issue list |
| Validation | No-regression tests + mock case replay |
| Deferred to later slices | `Continue`, `Rewrite`, long-form orchestration, UI |

## Exit Condition for This Slice

The slice is validated when:
1. A short text can be processed end-to-end through Rebuild + Review
2. Output object packet passes no-regression checks for Track 1/2/3
3. The process does not require human intervention at each step
4. The result is reviewable (not just runnable)

## What This Enables

Once this slice is validated:
- Second slice (short-form extend) can add `ContinueUnit`
- Third slice (short-form compose) can test `WorkSpec`-driven initialization
- Long-range orchestration and deployment can be decided with running evidence

## One-Sentence Summary

The recommended first implementation slice is short-form audit: a bounded Rebuild + Review loop on existing short text, deferring Continue, Rewrite, and long-range concerns to later slices.
