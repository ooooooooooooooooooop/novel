# Walkthrough: Extend Flow

## Purpose

End-to-end walkthrough of the `extend` usage mode.

It shows what happens when a user gives the system partial state + partial text of an unfinished novel and asks it to continue.

## Scenario

**Input**:
- Chapters 1-14 of `示例小说甲` (same as audit case)
- Partial object layer from a previous session (some `CharacterModel` fields, partial `FactLedger`, outdated `NarrativeState` at scene_013)
- Author note: "stopped writing after the rain scene, want to continue from there"

**User goal**: Continue the story from where it stopped, keeping state synchronized.

**Entry mode**: `extend`

---

## Step 1: Rebuild (Partial Recovery)

### Input
- Existing chapters 1-14
- Partial object layer (stale, incomplete, or degraded)
- Confidence gaps from prior session

### Rebuild actions
1. Reconcile existing text with partial object layer
2. Update `CharacterModel` where text shows new behavior
3. Extend `FactLedger` with events from chapters 12-14
4. Resolve confidence gaps: mark which old inferences are now confirmed, which remain open
5. Reconstruct `NarrativeState` at scene_014 (the actual breakpoint, not scene_013)
6. Carry forward `ReviewReminder` from prior session (if any)

### Output anchor
- Reconstructed object packet with explicit confidence layers
- Hard-fact constraints separated from current working pressures
- Unresolved inferences kept in `confidence_and_gaps`, not merged into `FactLedger`

---

## Step 2: Continue

### Input
- Current `NarrativeState` at scene_014
- Active `CharacterModel`s
- Current `FactLedger`
- Open `ForeshadowGraph` items
- `ReviewReminder` (promise payoff timing warning)

### Continue actions
1. Identify driving pressures: patrol approaching, old injury, secrecy risk
2. Select next `PlotUnit`: `pu_scene_015 / 夜雨撤离`
3. Ensure `PlotUnit` causes meaningful state change:
   - `c001` gains partial ally (`c002`) but not full trust
   - `c003` is neutralized but not eliminated
   - Old injury is acknowledged, not ignored
   - Token ownership is secured but exit route is uncertain
4. Generate candidate progression

### Output
- Candidate `PlotUnit` with explicit `input_state` and `output_state`
- Proposed `NarrativeState` delta
- Proposed `FactLedger` additions (if any new hard facts)
- Proposed `ForeshadowGraph` updates

---

## Step 3: Review

### Input
- Candidate `PlotUnit`
- Current object states
- Review rules

### Review actions
1. Does `pu_scene_015` change state meaningfully? Yes.
2. Is it consistent with `FactLedger`? Yes.
3. Is it consistent with `CharacterModel`? Yes, but check `c002` stance does not jump.
4. Does it respect narrative promises? Yes, `fg_002` advanced but not resolved.
5. Does it serve current level goal? Yes, moves toward withdrawal and封口.

### Review result

| Check | Result | Notes |
|---|---|---|
| State change | pass | Meaningful progression |
| Fact consistency | pass | No contradictions |
| Character consistency | pass | Relationship bridge, not jump |
| Promise tracking | pass | Promise advanced, not abandoned |
| Level goal | pass | Serves scene-level goal |

### Output
- Route recommendation: allow continuation
- `ReviewIssue`: 0
- `ReviewReminder`: updated (promise payoff now within 1-2 units)

---

## Step 4: Writeback and Loop

### Writeback
1. Update `NarrativeState` to post-scene_015 state
2. Add new facts to `FactLedger` (if any confirmed)
3. Update `ForeshadowGraph` status
4. Update `CharacterModel` relations (if long-term change)

### Handoff to next iteration
- `handoff_header`: Continue → Continue (or Continue → Review if threshold met)
- `open_items`: `ReviewReminder` for promise payoff
- `next_route`: Continue

### Loop
- Step 2-4 repeats until:
  - User stops
  - Review fails and requires Rewrite
  - Structural issue requires Replan

---

## What This Walkthrough Validates

1. `extend` entry mode works with partial + degraded input
2. `Rebuild` can recover from incomplete state
3. `Continue` → `Review` loop is the core progression mechanism
4. State synchronization across iterations is explicit

## What It Does Not Validate

- `audit` (already covered)
- `compose` (zero-text initialization)
- Multi-arc long-range consistency
- Rewrite / Replan recovery paths

## Key Difference from Audit

| | Audit | Extend |
|---|---|---|
| Entry | Full text | Partial text + partial state |
| Dominant chain | Rebuild → Review | Rebuild → Continue → Review (loop) |
| Output | Object packet + issue list | Continued text + synchronized state |
| `Continue` usage | None | Core |
| Exit condition | Review complete | User stops or structural issue |

## One-Sentence Summary

This walkthrough shows `extend` as a continuation flow: recover partial state, generate next progression, review it, write back, and loop.
