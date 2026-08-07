# Tier 0 Release Record Contract

## Purpose

This contract defines the evidence record required before a local staged CLI v0 build can be treated as Tier 0 production-ready.

It records the tested command set, immutable checkpoint, canary result, full pytest result, and known limitations without claiming DirectAPI provider calling, retry, fallback provider behavior, UI automation, or closed-loop workflow advancement.

## Record File

Use JSON.

Example: `docs/00_project/tier0_release_record.example.json`

The release record must be stored outside transient pytest directories and attached to the release tag or equivalent immutable checkpoint.

The release record must pass `validate_tier0_release_record()` from `src/boundary_control/release_record.py`.

Command:

```bash
python -m src.boundary_control.release_record docs/00_project/tier0_release_record.example.json --expected-baseline 2112
novel-release-record docs/00_project/tier0_release_record.example.json --expected-baseline 2112
novel-release-record docs/00_project/tier0_release_record.example.json --expected-baseline 2112 --require-evidence-files --evidence-root .
novel-release-record docs/00_project/tier0_release_record.example.json --expected-baseline 2112 --canary-evidence docs/00_project/tier0_canary_evidence.example.json
```

Generation command:

```bash
novel-release-record docs/00_project/releases/tier0-release.json --expected-baseline 2112 --record-path docs/00_project/releases/tier0-release.json --generate --release-id tier0-canary-YYYYMMDD --created-at-utc YYYY-MM-DDTHH:MM:SSZ --release-tag-or-checkpoint <tag-or-40-character-lowercase-hex-commit> --git-commit <40-character-lowercase-hex-commit> --full-pytest-command "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-evidence-full -p no:cacheprovider" --canary-evidence docs/00_project/releases/tier0-canary-evidence.json
```

Generation refuses to overwrite an existing release record file. The generated payload is validated with `validate_tier0_release_record()` before it is written.

When `--generate` is combined with `--canary-evidence`, the generated release record includes that canary evidence path in `evidence_paths` before binding validation runs.

`--require-evidence-files` validates that every `evidence_paths` entry points to an existing file. It is for existing records only and cannot be combined with `--generate`.

Canary evidence generation command:

```bash
novel-release-record docs/00_project/releases/tier0-canary-evidence.json --expected-baseline 2112 --generate-canary-evidence --release-id tier0-canary-YYYYMMDD --canary-workspace novels/tier0-canary --canary-gate-result docs/00_project/releases/tier0-canary-gate.json --canary-artifact-root .
```

`--generate-canary-evidence` reads existing staged final artifacts from `<workspace_path>/output/audit/`, computes `final_artifact_sha256`, records `gate_result_path` and `gate_result_sha256` for the saved `novel gate --json` result, derives `final_review_route` / `final_next_workflow` from `route_handoff.json`, derives `final_gate_ok` / `blocking_pending_count` from the saved gate result passed with `--canary-gate-result`, validates the generated object with `validate_tier0_canary_evidence()`, and then validates the listed files with `validate_tier0_canary_evidence_artifacts()` before writing. It refuses to overwrite an existing canary evidence file.

Canary evidence generation does not run the canary, call a provider, retry a failed step, create missing final artifacts, or advance the workflow. The `--canary-gate-result` file must be the actual final `novel gate --json` output for the same canary workspace.

For an actual release record, validate the immutable checkpoint binding:

```bash
novel-release-record docs/00_project/releases/tier0-release.json --expected-baseline 2112 --record-path docs/00_project/releases/tier0-release.json --require-git-checkpoint --repo-root .
```

`--require-git-checkpoint` validates that `git_commit` exists in the repository and that `release_tag_or_checkpoint` is either the same commit hash or a local `refs/tags/...` tag that resolves to `git_commit`. Branch names and moving refs such as `HEAD` are not accepted as immutable checkpoints.

For an actual release record, validate canary evidence binding:

```bash
novel-release-record docs/00_project/releases/tier0-release.json --expected-baseline 2112 --record-path docs/00_project/releases/tier0-release.json --canary-evidence docs/00_project/releases/tier0-canary-evidence.json
novel-release-record docs/00_project/releases/tier0-release.json --expected-baseline 2112 --record-path docs/00_project/releases/tier0-release.json --canary-evidence docs/00_project/releases/tier0-canary-evidence.json --require-canary-artifacts --canary-artifact-root .
```

`--canary-evidence` validates a `tier0_canary_evidence` JSON file and requires its `release_id`, `canary_result`, and `canary_commands` to match the release record. The canary evidence path and its `gate_result_path` must also appear in release record `evidence_paths`.

`--require-canary-artifacts` validates that every canary evidence `final_artifact_paths` entry resolves to an existing file from `--canary-artifact-root`, is under `workspace_path`, matches the corresponding `final_artifact_sha256` value, passes the expected JSON artifact shape for its filename, and is semantically consistent with the other final artifacts. It also validates that `gate_result_path` resolves to an existing saved gate JSON file, matches `gate_result_sha256`, and agrees with `final_gate_ok`, `final_review_route`, `final_next_workflow`, and `blocking_pending_count`. It requires `--canary-evidence`.

For final Tier 0 release validation, run a single combined validation command over the same release record and canary evidence:

```bash
novel-release-record docs/00_project/releases/tier0-release.json --expected-baseline 2112 --record-path docs/00_project/releases/tier0-release.json --require-evidence-files --evidence-root . --require-git-checkpoint --repo-root . --canary-evidence docs/00_project/releases/tier0-canary-evidence.json --require-canary-artifacts --canary-artifact-root .
```

The single combined validation command must pass before the release record is treated as production evidence.

## Required Fields

The JSON object must contain exactly these fields:

- `schema_version`: `1`
- `type`: `tier0_release_record`
- `production_tier`: `local_staged_cli_v0`
- `release_id`: `tier0-canary-YYYYMMDD`; date must be valid and must match `created_at_utc`
- `created_at_utc`: UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` format
- `release_tag_or_checkpoint`: immutable tag or the same 40-character commit hash as `git_commit`
- `git_commit`: 40-character lowercase hexadecimal git commit hash
- `baseline_tests_passing`: current full pytest baseline, currently `2112`
- `full_pytest_command`: full repo pytest command in the form `python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-<name> -p no:cacheprovider`
  - `<name>` must be a non-empty single directory-name suffix using only letters, digits, `.`, `_`, and `-`
  - path separators, parent directory references, and an empty suffix are not accepted
- `full_pytest_result`: `<baseline> passed`
- `canary_runbook`: `docs/00_project/31_tier0_canary_runbook.md`
- `canary_result`: `pass`
- `canary_commands`: ordered command list from the Tier 0 canary runbook
- `staged_runtime`: `FileExchangeInterface`
- `directapi_provider_calling`: `false`
- `provider_calls_implemented`: `false`
- `closed_loop_allowed`: `false`
- `provider_call_performed`: `false`
- `closed_loop_advanced`: `false`
- `known_limitations`: non-empty string list; `known_limitations` entries must be unique
- `evidence_paths`: non-empty string list; `evidence_paths` entries must be unique; `evidence_paths` must preserve the required evidence order; the release record path must be the final evidence path

## Required Limitations

`known_limitations` must include:

- `DirectAPI provider calling is not implemented`
- `closed-loop automation remains disallowed`
- `Tier 0 is not a public product surface`
- `release record does not replace a release tag or immutable checkpoint`

## Required Evidence

`evidence_paths` must include these entries in this order:

- `docs/00_project/30_production_readiness_checklist.md`
- `docs/00_project/31_tier0_canary_runbook.md`
- the canary evidence record file
- the saved canary gate JSON result file listed by canary evidence `gate_result_path`
- the release record file itself

When `--require-evidence-files` is used, every listed path must resolve to an existing file from `--evidence-root`.

When canary evidence is bound, the canary evidence record path must appear before its saved canary gate JSON result path.

## Canary Evidence

Example: `docs/00_project/tier0_canary_evidence.example.json`

The canary evidence object must contain exactly these fields:

- `schema_version`: `1`
- `type`: `tier0_canary_evidence`
- `release_id`: same value as the release record
- `canary_result`: `pass`
- `canary_commands`: ordered command list from the Tier 0 canary runbook
- `workspace_path`: `novels/tier0-canary`
- `final_artifact_paths`: paths including `audit_report.json`, `review_result.json`, `route_handoff.json`, and `rebuild_package.json`; `final_artifact_paths` entries must be unique; `final_artifact_paths` artifact names must be unique; `final_artifact_paths` must match ordered workspace `output/audit` final artifacts
- `final_artifact_sha256`: object mapping every `final_artifact_paths` entry to a lowercase 64-character sha256 hex string; missing, unknown, or invalid hash entries are rejected
- `gate_result_path`: saved `novel gate --json` result path
- `gate_result_sha256`: lowercase 64-character sha256 hex string for `gate_result_path`
  - with `--require-canary-artifacts`, every listed final artifact path must resolve to an existing file under `workspace_path`; its computed sha256 must match `final_artifact_sha256`; `audit_report.json`, `review_result.json`, `route_handoff.json`, and `rebuild_package.json` must each validate against their runtime JSON shape; `gate_result_path` must resolve, match `gate_result_sha256`, and validate as the final gate JSON result; `route_handoff.output_anchor.state_ref` must equal `audit_report.narrative_state.state_id`; and route / handoff / package / gate semantics must remain cross-artifact consistent
- `final_gate_ok`: `true`
- `final_review_route`: `pass`
- `final_next_workflow`: `ContinueUnit`
- `blocking_pending_count`: `0`
- `directapi_provider_calling`: `false`
- `provider_calls_implemented`: `false`
- `closed_loop_allowed`: `false`
- `provider_call_performed`: `false`
- `closed_loop_advanced`: `false`
- `materialized_actions`: two `materialize_staged_response_only` entries

## Boundaries

The release record is evidence only.

It must not:

- store secrets
- contain raw prompt text
- contain raw response text
- claim provider execution
- claim retry
- claim a fallback provider
- claim closed-loop automation
- replace `novel gate --json`
