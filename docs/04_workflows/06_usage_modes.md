# Usage Modes

## Purpose

This file is a terminology index for the three usage entry modes of the narrative system.

It does not define new workflows. It does not modify existing workflow semantics. It names and points.

## Three Modes

| Mode | Input | Entry Workflow | Dominant Workflow Chain | Exit |
|---|---|---|---|---|
| **audit** | Full existing text | `Rebuild` | `Rebuild` → `Review` → optional `Rewrite` | Reconstructed object packet + issue list with severity routing |
| **extend** | Partial state + partial text | `Rebuild` (partial reconstruction) | `Rebuild` → `Continue` → `Review` (loop) | Continued text with synchronized state and updated reconstruction packet |
| **compose** | `WorkSpec` only | `Rebuild` (initialization-style) | `Continue` → `Review` (loop), state grows from empty | Complete narrative satisfying `WorkSpec` |

## Mode-to-Document Mapping

### audit
- `01_rebuild_workflow.md` section 2.1: "从已完结小说重建"
- `01_rebuild_workflow.md` section 3.2 input level A (完整文本型)
- `01_rebuild_workflow.md` section 7: 完整重建 / 结构性重建

### extend
- `01_rebuild_workflow.md` section 2.2: "从断更小说重建"
- `01_rebuild_workflow.md` section 3.2 input level B (半完整资料型)
- `01_rebuild_workflow.md` section 7: 结构性重建 / 初始化式重建

### compose
- `01_rebuild_workflow.md` section 2.5: 从 WorkSpec 初始化（compose 模式）
- `01_rebuild_workflow.md` section 3.2 input level C (零散碎片型) 的极端形式
- `03_continue_workflow.md`: state generation loop starting from empty
- No existing text to reconstruct; `Rebuild` produces stub objects from constraints

## Shared Constraints

Across all three modes:

- Track 1 lock: `FactLedger` hard-fact threshold unchanged
- Track 2 lock: bounded runtime-first `Rewrite` unchanged
- Track 3 lock: `CharacterModel` evidence-leakback prevention unchanged
- Eight core objects unchanged
- Four core workflows unchanged

## Compose-Mode Stub Definition

When input is `WorkSpec`-only, `Rebuild` does not process source material. Instead it:

1. Reads `WorkSpec` constraints
2. Produces stub `NarrativeState` (empty but runnable)
3. Produces stub `WorldModel` from `WorkSpec` genre/constraints
4. Produces stub `CharacterModel` placeholders from `WorkSpec` character requirements
5. Marks all objects as `proposed` in `confidence_and_gaps`
6. Produces no reconstructed history

This is initialization, not reconstruction. It is represented in `Rebuild` for consistency.

## One-Sentence Summary

The three usage modes are entry paths, not new workflows: audit for existing text review, extend for partial continuation, compose for `WorkSpec`-driven creation from zero.
