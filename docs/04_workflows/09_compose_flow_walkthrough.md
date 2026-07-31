# Walkthrough: Compose Flow

## Purpose

End-to-end walkthrough of the `compose` usage mode.

It shows what happens when a user gives the system only a `WorkSpec` and asks it to build a narrative from zero.

## Scenario

**Input**: `WorkSpec` for `示例小说甲` (same genre, theme, and constraints as audit/extend cases).

**User goal**: Generate a short narrative from scratch that satisfies the `WorkSpec`.

**Entry mode**: `compose`

---

## Step 1: Rebuild (Initialization)

### Input
- `WorkSpec` only (no existing text, no prior state)

### Rebuild actions
1. Read `WorkSpec` constraints:
   - Genre: 仙侠 / 宗门成长 / 身世之谜 / 女性成长
   - Theme: 成长、代价、命运、身份认同
   - Tone: 克制
   - Viewpoint: 限制第三人称
   - Pacing: 前快中稳后爆
2. Derive stub `WorldModel` from genre-implied rules:
   - Spirit root system exists
   - Faction hierarchy exists
   - Forbidden arts have traceable consequences
   - Trial tokens are controlled resources
   - (Minimal rules only; no over-building)
3. Create stub `CharacterModel` placeholders from `WorkSpec` character requirements:
   - Protagonist: female, expelled, time-limited survival constraint
   - Ally candidate: ambiguous stance, risk-averse
   - Antagonist pressure: faction-based or rival-based
   - (Names and details not filled; only structural roles)
4. Generate empty `NarrativeState`:
   - Time: pre-trial, day zero
   - Location: undefined (to be established by first `PlotUnit`)
   - Active characters: protagonist only
   - Goals: survive and return (abstract)
5. Empty `FactLedger` (no confirmed events)
6. Empty `ForeshadowGraph` (no promises yet)
7. Mark all objects as `proposed` in `confidence_and_gaps`

### Output anchor
- Initialization packet: all objects are stubs with high uncertainty
- No reconstructed history (there is none)
- Next route: `Continue`

---

## Step 2: Continue (First PlotUnit)

### Input
- Stub `NarrativeState` (mostly empty)
- Stub `CharacterModel`s (structural only)
- Stub `WorldModel` (genre-implied rules)
- `WorkSpec` constraints (tone, pacing, viewpoint)

### Continue actions
1. Establish opening situation that satisfies `WorkSpec`:
   - Must introduce protagonist's constraint (expelled, time limit, survival pressure)
   - Must establish world rule presence (spirit root damage, faction control)
   - Must create immediate actionable goal (obtain trial token, find shelter, etc.)
   - Must fit "前快" pacing (opening moves quickly)
2. Select first `PlotUnit`: `pu_scene_001 / 逐令初现`
   - Level: scene
   - Goal: establish protagonist's desperate situation and first concrete objective
   - Participants: protagonist + one faction representative
   - Conflict: time pressure vs bureaucratic indifference
   - Input state: empty/pre-trial
   - Output state: protagonist has a named objective and a deadline
3. Generate candidate progression text

### Output
- Candidate `PlotUnit` with explicit state change
- Proposed `NarrativeState` (now has location, time, goal, active conflict)
- No new hard facts yet (first scene; facts accumulate in subsequent units)

---

## Step 3: Review

### Input
- Candidate `PlotUnit`
- `WorkSpec` constraints
- Stub object states

### Review actions
1. Does `pu_scene_001` change state meaningfully? Yes (from undefined to defined situation).
2. Is it consistent with `WorkSpec` tone? Yes (克制, not melodramatic).
3. Is it consistent with `WorldModel` stub rules? Yes (faction control present, spirit root damage acknowledged).
4. Does it establish narrative promise? Yes (will she make it back? what is the true reason for expulsion?).
5. Does it serve `WorkSpec` pacing? Yes (opening is fast, stakes are clear).

### Review result

| Check | Result | Notes |
|---|---|---|
| State change | pass | First definition of situation counts as meaningful change |
| Spec consistency | pass | Tone and genre respected |
| World legality | pass | Stub rules not violated |
| Promise tracking | pass | Two promise threads seeded |
| Pacing | pass | Opening satisfies "前快" |

### Output
- Route recommendation: allow continuation
- `ReviewIssue`: 0
- `ReviewReminder`: none yet (too early)
- `ForeshadowGraph` updated with seeded promises

---

## Step 4: Writeback and Loop

### Writeback
1. Update `NarrativeState` to post-scene_001 state
2. Add first `FactLedger` entries (only if scene confirms hard facts):
   - Protagonist is expelled
   - Protagonist has a time limit
   - (Soft facts: her spirit root is damaged — may be inferred, not yet confirmed)
3. Update `ForeshadowGraph` with two promise threads
4. Update `CharacterModel` with first behavioral observation (if any)

### Handoff to next iteration
- `handoff_header`: Continue → Continue
- `open_items`: none
- `next_route`: Continue

### Loop
- Step 2-4 repeats, generating `scene_002`, `scene_003`, etc.
- State accumulates from empty to populated
- Facts accumulate from none to established
- Promises accumulate and must eventually pay off or escalate

---

## What This Walkthrough Validates

1. `compose` entry mode works from zero input
2. `Rebuild` initialization produces runnable stubs from `WorkSpec` alone
3. `Continue` can generate meaningful first progression from mostly empty state
4. State grows incrementally, not all at once

## What It Does Not Validate

- `audit` (already covered)
- `extend` (already covered)
- Long-form consistency (only first scene shown)
- Multi-novel generalization (only one `WorkSpec` tested)

## Key Difference from Audit and Extend

| | Audit | Extend | Compose |
|---|---|---|---|
| Input | Full text | Partial text + partial state | `WorkSpec` only |
| Rebuild type | Reconstruction | Partial reconstruction | Initialization |
| Initial state | Derived from text | Recovered from input + text | Empty stubs |
| Fact source | Text | Text + prior state | Generated by `PlotUnit`s |
| Output | Object packet + issues | Continued text + state | Narrative built from zero |

## One-Sentence Summary

This walkthrough shows `compose` as a creation flow: initialize stubs from `WorkSpec`, generate first progression, review it, write back, and loop until narrative satisfies the spec.
