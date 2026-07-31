# Audit Short-Form Slice Design

## Purpose

First bounded implementation slice: Rebuild + Review on short existing text.

This document defines what the slice must do, what it must not do, and what remains deferred.

## Slice Boundary

### In Scope

| Component | Responsibility |
|---|---|
| `WorkSpecUnit` | Parse and store project-level constraints |
| `WorldModelUnit` | Extract and validate world rules from text |
| `CharacterModelUnit` | Extract character logic from behavior patterns |
| `FactLedgerUnit` | Admit hard facts from confirmed events |
| `ForeshadowGraphUnit` | Track promises from setup/payoff signals |
| `NarrativeStateUnit` | Derive current runnable state |
| `RebuildUnit` | Orchestrate reconstruction from input text |
| `ReviewUnit` | Classify validity and route |
| `SerializationBoundaryUnit` | Persist four layers (stable/working/repair/confidence) |
| `HandoffBoundaryUnit` | Transfer Rebuild output to Review |
| `OrchestrationGateUnit` | Entry gating and writeback verification |
| `NoRegressionValidationUnit` | Verify Track 1/2/3 preservation |

### Out of Scope

- `ContinueUnit` (generation deferred)
- `RewriteUnit` (repair deferred until Review finds issues)
- Long-range orchestration (book/arc/chapter hierarchy)
- UI / product layer
- Model provider selection
- Deployment shape
- Performance optimization

## Input Contract

- One short narrative text (one arc, 3-10 chapters, or equivalent)
- Optional: scattered notes (character cards, worldbuilding fragments)
- No prior object layer required

## Output Contract

- Reconstructed object packet with four serialization layers
- `ReviewIssue` list with severity routing
- `ReviewReminder` items if warranted
- Confidence map showing what is solid vs inferred vs guessed

## No-Regression Checklist

This slice must pass:

| Test | Source |
|---|---|
| T1.1 Hard Fact Owner | `21_no_regression_acceptance_test_list.md` |
| T2.2 Same-Packet Sync | `21_no_regression_acceptance_test_list.md` |
| T3.1 Long-Term Conclusion | `21_no_regression_acceptance_test_list.md` |
| S1 Layer Placement | `21_no_regression_acceptance_test_list.md` |
| H2 Change Set Owner | `21_no_regression_acceptance_test_list.md` |
| O3 Writeback Verification | `21_no_regression_acceptance_test_list.md` |
| C4 Lock-To-Gate Consistency | `21_no_regression_acceptance_test_list.md` |

## Deferred Decisions

The following remain deferred and must not block this slice:

| Decision | Why Deferred |
|---|---|
| Storage backend | Serialization shape is defined; storage choice is implementation detail |
| Programming language | Object schemas are language-agnostic |
| Model routing | Review logic is rule-based, not model-dependent |
| Prompt structure | Rebuild strategy is conceptual, not prompt-engineered |

## Validation Target

The slice is validated when:

1. `示例小说甲` arc-level text can be processed through the slice end-to-end
2. Output object packet passes the no-regression checklist
3. Manual inspection confirms `FactLedger` facts match text
4. Manual inspection confirms `Review` routing matches rule definitions

## One-Sentence Summary

This slice is a bounded Rebuild + Review pipeline on short text, preserving all planning locks while deferring Continue, Rewrite, UI, and deployment.
