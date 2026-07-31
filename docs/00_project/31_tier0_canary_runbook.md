# Tier 0 Canary Runbook

## Purpose

This runbook verifies the current production tier: local staged CLI v0 with an internal operator-in-the-loop.

It proves that the operator can move one audit workspace through staged response materialization and route gate validation without DirectAPI provider calls, UI automation, retry, fallback provider behavior, or closed-loop workflow advancement.

## Preconditions

- Use a temporary canary novel name.
- Use a temporary `NOVELS_ROOT` or an isolated canary workspace.
- Keep `FileExchangeInterface` as the default v0 runtime.
- Prepare response files outside the staged output directory.
- Do not write directly to `*_response.txt`.
- Do not parse workflow JSON outside the existing workflow commands.
- Do not select routes outside `ReviewUnit.parse_response()`.
- Do not write final artifacts outside the staged workflow commands.

## Audit Canary Sequence

Run these commands in order:

```bash
novel audit tier0-canary --input canary_input.txt
novel pending tier0-canary --require-automation-ready --json
novel respond tier0-canary --slot-id rebuild --prompt-hash <rebuild_prompt_hash> --response-file canary_rebuild_response.json --json
novel resume tier0-canary
novel pending tier0-canary --require-automation-ready --json
novel respond tier0-canary --slot-id review --prompt-hash <review_prompt_hash> --response-file canary_review_response.json --json
novel resume tier0-canary
novel gate tier0-canary --json
```

The expected staged slots are:

- `rebuild_prompt.txt` -> `rebuild_response.txt`
- `review_prompt.txt` -> `review_response.txt`

The expected final artifacts are:

- `audit_report.json`
- `review_result.json`
- `route_handoff.json`
- `rebuild_package.json`

## Pass Criteria

The canary passes only when all of these are true:

- both `novel pending --require-automation-ready --json` calls return `automation_ready=true`
- both pending payloads return `provider_calls_implemented=false`
- both pending payloads return `closed_loop_allowed=false`
- both `novel respond --json` calls return `provider_call_performed=false`
- both `novel respond --json` calls return `closed_loop_advanced=false`
- both `novel respond --json` calls return `materialized_action=materialize_staged_response_only`
- final `novel gate --json` returns `ok=true`
- final `novel gate --json` returns `review_route=pass`
- final `novel gate --json` returns `next_workflow=ContinueUnit`
- final gate payload has `blocking_pending_count=0`

## Failure Handling

Stop the canary on the first failure.

Do not retry with a different provider, fallback provider, alternate route, or hand-written final artifact.

Record the failing command, exit code, stdout/stderr, current prompt hash, response source hash, and workspace path before rerunning.

## Release Evidence

After a passing canary, record the result with `docs/00_project/32_tier0_release_record_contract.md`.

The release record must keep provider and closed-loop fields false. It is evidence for the release tag or equivalent immutable checkpoint, not a replacement for that checkpoint.

## Current Scope

This runbook is Tier 0 only.

It does not validate DirectAPI provider calling, UI automation, public deployment, multi-user isolation, or closed-loop automation.
