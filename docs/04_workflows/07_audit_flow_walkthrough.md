# Walkthrough: Audit Flow

## Purpose

End-to-end walkthrough of the `audit` usage mode.

It shows what happens when a user gives the system an existing novel and asks for reconstruction + review.

## Scenario

**Input**: Chapters 1-14 of `示例小说甲` (the mock project case), plus scattered character notes and worldbuilding documents.

**User goal**: Understand the narrative structure, check for consistency issues, and identify where the story may have weakened.

**Entry mode**: `audit`

---

## Step 1: Rebuild

### Input
- Full text of chapters 1-14
- Author notes on three main characters
- Partial worldbuilding document

### Rebuild actions
1. Extract `WorkSpec` from genre signals, pacing patterns, and thematic markers
2. Build `WorldModel` from explicit rules (spirit root damage, forbidden arts traces, trial token system) and implicit constraints (faction balance, city prohibitions)
3. Reconstruct three `CharacterModel`s from behavior patterns, dialogue choices, and decision pressure
4. Establish `FactLedger` from confirmed events, deaths, transfers of ownership, and rule activations
5. Build `ForeshadowGraph` from promises made to the reader:身世之谜, 旧案真凶, c002 立场, 令牌来源
6. Derive current `NarrativeState` at scene_014 breakpoint

### Output anchor
- Reconstructed object packet separated into `stable_memory`, `working_set`, `confidence_and_gaps`
- Unresolved gaps marked explicitly (e.g., "c002's true faction allegiance inferred but not confirmed")
- No hard facts claimed from inference

---

## Step 2: Review

### Input
- Reconstructed object packet
- Original text for spot-checking
- `ReviewIssue` schema and rule set

### Review actions
1. **Fact consistency check**: Does `FactLedger` contradict the text?
2. **Character consistency check**: Do reconstructed `CharacterModel`s explain key decisions?
3. **World legality check**: Do events respect `WorldModel` rules?
4. **Promise tracking check**: Are foreshadow items accounted for?
5. **Progression check**: Does `PlotUnit` chain show meaningful state change?

### Review result

| Check | Result | Notes |
|---|---|---|
| Fact consistency | pass | No contradictions found |
| Character consistency | pass with warning | c001's "refuse to ask for help" flaw is consistent but may become repetitive |
| World legality | pass | Token rules, trace rules, and prohibition respected |
| Promise tracking | pass with warning | `fg_002` (c002 stance) needs payoff within 2-3 units |
| Progression | pass | Scene_014 is effective state change |

### Output
- `ReviewIssue` count: 0 blocking, 2 warnings
- `ReviewReminder` created for: character flaw repetition risk, promise payoff timing
- Route recommendation: `Rebuild` output is structurally sound; no `Rewrite` required
- Exit package: reconstructed objects + issue list with severity routing

---

## Step 3: Exit

### What the user receives
1. **Reconstruction report**: object layer summary (not prose summary)
2. **Issue list**: 0 blocking, 2 warnings with explicit routing
3. **Confidence map**: which reconstructions are solid, which are inferred, which are guessed

### What the user does not receive
- Polished prose rewrite
- Continuation of the story
- Editorial judgment on "quality" beyond legality and consistency

---

## What This Walkthrough Validates

1. `audit` entry mode works end-to-end without requiring continuation
2. `Rebuild` → `Review` chain is sufficient for analysis tasks
3. The mock case can carry a full workflow loop
4. Output package shape is reviewable and transferable

## What It Does Not Validate

- `extend` (requires continuation)
- `compose` (requires zero-text initialization)
- Long-chain drift (only 14 chapters)
- Multi-novel migration (only one case)

## One-Sentence Summary

This walkthrough shows `audit` as a self-contained flow: input text, reconstruct objects, review for consistency, output structured findings.
