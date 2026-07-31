# Deployment Shape Decision

## Status

- Decision: `adopted`
- Deployment shape: `Codex-native staged CLI v0`
- Date: 2026-05-27

## Purpose

Fix the next runnable shape of the project after the Audit / Extend / Compose
slices became end-to-end validated.

This decision does not add a new core object, does not change the four core
workflows, and does not implement DirectAPI.

## Decision

The v0 deployment shape is a local **Codex-native staged CLI**.

The entry scripts are treated as the current usable runtime surface:

- `src/audit_short_form.py`
- `src/extend_short_form.py`
- `src/compose_short_form.py`

They remain staged workflows:

1. script writes a prompt file
2. Codex or the user writes the matching response file
3. script is rerun
4. result/state files are written only after required responses exist

## Runtime Contract

- Every flow must support an explicit `--output-dir`.
- Prompt, response, package/state, frame, and result files must stay inside the selected output directory.
- Missing response files are normal staged waiting points and return success.
- Missing resume state is an error, not a reason to restart from scratch.
- Input hash mismatch is an error, and existing response files must be preserved.

## Deferred

The following remain out of v0:

- DirectAPI implementation
- UI or product workflow
- fully automatic closed-loop model calls
- long-form automatic completion
- storage backend selection beyond local files

DirectAPI design may start only after this CLI surface is stable enough that
its file/state contract can be reused rather than guessed.

## Reasoning

The project has enough running capability that the next risk is not lack of a
new feature. The next risk is treating staged scripts, output directories,
response files, resume state, and future API calls as informal details.

Choosing Codex-native staged CLI v0 keeps the current successful orchestration
model, while making failure behavior explicit before DirectAPI or UI work can
pull the architecture in different directions.

## Acceptance

This decision is accepted when:

- all three entry scripts support `--output-dir`
- resume state failure is exposed instead of bypassed
- input hash mismatch preserves existing response files
- docs describe DirectAPI provider calls remain unimplemented, and closed-loop automation remains deferred
- full regression tests pass
