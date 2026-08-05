# Production Readiness Checklist

## Status

Current production tier: local staged CLI v0.

Tier 0 was declared production-ready on 2026-07-28.

- release record: `docs/00_project/releases/tier0-release.json`
- immutable checkpoint: git tag `v0.1.1-tier0`
- canary evidence: `docs/00_project/releases/tier0-canary-evidence.json`
- saved canary gate result: `docs/00_project/releases/tier0-canary-gate.json`
- the single combined validation command passes with expected baseline 1625

Three-flow daily-production hardening completed on 2026-07-29 (planning: `docs/00_project/34_tier0_daily_production_hardening_plan.md`), extending the audit-only Tier 0 verdict to all three flows (`audit` / `extend` / `compose`):

- extend canary and compose canary each ran a real staged Codex loop and passed `novel gate` (ok / pass / ContinueUnit / blocking=0); per-flow gate results saved at `tier0-extend-canary-gate.json` and `tier0-compose-canary-gate.json`
- three-flow aggregation evidence (human-curated): `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- operator runbook for all three flows: `docs/00_project/35_operator_runbook.md`
- one-command regression gate: `python scripts/tier0_canary_regression.py` (exit 0 ⇒ three-flow baseline not regressed)
- production-readiness re-certified on 2026-08-04 under a new immutable checkpoint `v0.1.1-tier0` (hardening stays inside the Tier 0 boundary; no tier upgrade)

The current acceptable production use is internal operator-in-the-loop production:

- an operator runs `novel audit`, `novel extend`, `novel compose`, `novel list`, `novel pending`, `novel respond`, and `novel gate` locally
- `FileExchangeInterface remains the default v0 runtime`
- response text is materialized through staged prompt/response files
- `DirectAPI provider calling is not implemented`
- UI automation and `closed-loop automation remains disallowed`

This checklist defines when the project can be treated as production-ready for a tier. It does not declare DirectAPI, UI, or automatic closed-loop execution ready.

## Tier 0: Local Operator Production

Tier 0 is ready only when all of these are true:

- the runtime is still `local staged CLI v0`
- one operator controls response materialization
- the release candidate has a clean full pytest run
- the release candidate records `1625 tests passing`
- `novel gate --require-approval` is an opt-in human-approval gate; the default `novel gate` contract is unchanged
- a release tag or equivalent immutable checkpoint exists
- known limitations are documented in this file and the current status page
- no provider call is made by the staged CLI entrypoints
- no automatic route advancement occurs after model text is produced
- no final artifact is written except by the existing staged workflow commands

Allowed Tier 0 production use:

- internal operator-in-the-loop production
- local workspace runs under `novels/<name>/`
- response-file materialization through `novel respond`
- read-only readiness checks through `novel pending`, `novel list`, and `novel gate`

Tier 0 is not a public product surface.

### Known Limitations (Tier 0)

The following must be documented alongside this checklist and `03_current_status.md`:

- DirectAPI provider calling is not implemented
- closed-loop automation remains disallowed
- Tier 0 is not a public product surface
- release record does not replace a release tag or immutable checkpoint
- response files must be materialized by the operator or Codex; no automatic model call is performed

## Tier 1: DirectAPI Single-Provider Beta

Tier 1 is not ready now.

Tier 1 becomes eligible only after a provider adapter exists and all of these are true:

- DirectAPI fills response text only
- DirectAPI consumes exactly one `single pending slot`
- DirectAPI uses the `same staged response materialization path` as `novel respond`
- DirectAPI must not parse workflow JSON
- DirectAPI must not select routes
- DirectAPI must not write final artifacts
- DirectAPI must not bypass `build_prompt()` / `parse_response()` boundaries
- DirectAPI must not mutate handoff, route, reminder, or package schemas
- provider errors must surface unchanged to the caller
- schema errors must surface unchanged to the caller
- no retry
- no `fallback provider`
- provider `secrets` are supplied outside payloads and audit records
- provider `timeout` behavior is configured explicitly
- an `audit log` records prompt path, response path, slot id, prompt hash, provider name, and failure type without storing credentials

Tier 1 may replace only the manual act of writing a response file. It may not replace orchestration order, route selection, gate validation, or final artifact writes.

## Tier 2: UI Or Automation Production

Tier 2 is not ready now.

Tier 2 requires a separate gate after Tier 1:

- explicit UI or automation ownership model
- route gate enforcement before every state transition
- concurrency and workspace locking
- rollback plan for partially materialized responses
- audit-visible operator or service identity
- multi-novel isolation
- failure dashboards or equivalent monitoring
- documented incident recovery steps

Until those exist, closed-loop automation remains disallowed.

## Non-Goals

- Do not use DirectAPI to select routes.
- Do not use DirectAPI to parse workflow JSON.
- Do not let provider output write final artifacts directly.
- Do not add automatic retry.
- Do not add a fallback provider.
- Do not store secrets in JSON payloads, action blocks, response metadata, handoff packets, or audit logs.

## Release Check Sequence

Before calling any tier production-ready:

1. Run a clean full pytest.
2. Confirm the current baseline is documented.
3. Run a canary through `novel pending`, `novel respond`, and `novel gate`.
   Use `docs/00_project/31_tier0_canary_runbook.md` for the Tier 0 canary sequence.
4. Generate canary evidence from the final staged workspace artifacts with `--generate-canary-evidence`.
5. Confirm no provider calls are performed in Tier 0.
6. Confirm provider errors surface unchanged before Tier 1.
7. Confirm no retry or fallback provider behavior exists before Tier 1.
8. Create a release tag or equivalent immutable checkpoint.
9. Record the tested command set and known limitations with `docs/00_project/32_tier0_release_record_contract.md`.
10. Validate the release record with `validate_tier0_release_record()`.
11. Validate release record evidence files with `--require-evidence-files`.
12. Validate the release tag or immutable checkpoint with `--require-git-checkpoint`.
13. Validate the canary evidence binding with `--canary-evidence`.
14. Validate canary final artifact files, sha256 content hashes, runtime shapes, and cross-artifact semantics with `--require-canary-artifacts`.
15. Run the single combined validation command from `docs/00_project/32_tier0_release_record_contract.md` over the same release record and canary evidence.
