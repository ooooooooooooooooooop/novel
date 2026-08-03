# Automatic Novel Narrative System

## Project

This repository is building the foundation of an automatic novel narrative system.

The long-term goal is a system that can:

- parse narrative structure
- maintain narrative state
- plan story progression
- review generated results
- support rebuilding, continuation, rewriting, and later implementation work

## Current Phase

The repository is now **Tier 0 production ready — three-flow daily-production hardened** — end-to-end validated, Codex-native orchestration.

All three implementation slices are code-complete and validated:
`audit_short_form`, `extend_short_form`, and `compose_short_form`.

Tier 0 (local staged CLI v0, operator-in-the-loop) was declared production-ready on 2026-07-28:

- production tier: `local staged CLI v0`
- full pytest baseline: 1540 tests passing
- release record: `docs/00_project/releases/tier0-release.json` — passing the single combined validation command
- canary evidence: `docs/00_project/releases/tier0-canary-evidence.json`
- saved canary gate result: `docs/00_project/releases/tier0-canary-gate.json`
- immutable checkpoint: git tag `v0.1.0-tier0` → commit `b8738060689af137f544303cf64d5fd37f225a8c`
- audit canary `novel gate tier0-canary --json`: `ok=true`, `review_route=pass`, `next_workflow=ContinueUnit`, `blocking_pending_count=0`

Three-flow daily-production hardening (2026-07-29) extended the Tier 0 verdict from audit-only to all three flows:

- extend and compose canaries each ran a real staged Codex loop and passed `novel gate` with the same four standards; per-flow gate results at `tier0-extend-canary-gate.json` / `tier0-compose-canary-gate.json`; aggregation evidence at `tier0-three-flow-canary-aggregation.json`
- operator runbook: `docs/00_project/35_operator_runbook.md`
- one-command regression gate: `python scripts/tier0_canary_regression.py`
- hardening planning: `docs/00_project/34_tier0_daily_production_hardening_plan.md`

Tier 0 boundaries that remain in force:

- DirectAPI provider calling is not implemented
- closed-loop automation remains disallowed
- Tier 0 is not a public product surface
- release record does not replace a release tag or immutable checkpoint
- response files must be materialized by the operator or Codex; no automatic model call is performed

Current checkpoint judgment:

- foundation gate status: `pass`
- transition-planning sufficiency: `pass`
- implementation-planning sufficiency: `pass`
- implementation status: `end_to_end_validated`
- orchestration mode: staged prompt, Codex response, rerun
- current next step: use the unified `novel` entry for multi-novel staged runs

Current work has completed:

- bounded implementation slices: all three complete and validated
- LLM layer split: workflow units expose `build_prompt()` and `parse_response()`
- long-form multi-arc stress test: PASS
- executable no-regression tests: 1540 tests passing
- end-to-end Audit / Extend / Compose validation: PASS
## Implementation Status

- **Slice 1: `audit_short_form`** - Complete
  - Rebuild + Review pipeline
  - 8 core object models (Pydantic v2)
  - 4-layer JSON serialization
  - Handoff packet structure
  - Entry script: `src/audit_short_form.py`
  - End-to-end validation: PASS
- **Slice 2: `extend_short_form`** - Complete
  - Rebuild + Continue + Review pipeline
  - Entry script: `src/extend_short_form.py`
  - Long-form state inheritance validation: PASS
  - End-to-end validation: PASS
- **Slice 3: `compose_short_form`** - Complete
  - WorkSpec + Initialize + Continue + Review pipeline
  - Entry script: `src/compose_short_form.py`
  - Default WorkSpec validation: PASS
  - End-to-end validation: PASS
- **Domain layer** - Complete (Phase B)
  - Genre formulas, hook taxonomy, emotional arc templates
  - Structure node -> emotion mapping (B1)
  - Platform constraints (B2)
  - Hook effectiveness + genre rules (B3)
- **Incremental continuation** - Complete (Slice D1)
  - `extend_short_form.py` supports `--resume` to skip Rebuild and continue from saved state
  - `compose_short_form.py` supports `--resume` to skip Initialize and continue from saved state
  - Frame cursor auto-advances to next scene after each successful Continue
  - Frame state persisted to `output/extend_frames.json` and `output/compose_frames.json`
- **LLM layer split** - Complete
  - `RebuildUnit`, `ContinueUnit`, and `ReviewUnit` no longer receive an `llm` parameter
  - each unit exposes `build_prompt()` and `parse_response()`
  - scripts no longer call an LLM internally
  - `src/llm_interface.py` remains as a backup interface layer
  - DirectAPI has a provider-agnostic interface contract, pending response-slot discovery, and staged response runner; provider calls remain unimplemented
  - OrchestrationGateUnit exists as a minimal executable route gate, not an
    automatic closed-loop runner
- **Deployment shape** - Adopted for v0
  - local Codex-native staged CLI is the current usable runtime surface
  - all flow outputs should be isolated with `--output-dir`
  - DirectAPI, UI, and fully automatic closed-loop model calls remain deferred
- **Validation status**
  - `pytest tests/ -q`: 1540 tests passing
  - long-form multi-arc Audit / Extend stress test: PASS
  - end-to-end Audit / Extend / Compose workflow validation: PASS

## Usage

The preferred entry point is `novel`, a thin wrapper around the existing Codex-native staged workflows. It creates `novels/<name>/`, copies the input into that workspace, writes intermediate files under `novels/<name>/output/<mode>/`, and then calls the underlying short-form script.

Install locally if needed:

```bash
pip install -e .
```

Audit existing text:

```bash
novel audit 示例小说甲 --input 示例小说甲.txt
```

Extend existing text:

```bash
novel extend 示例小说乙 --input 示例小说乙.txt
```

Compose from WorkSpec or the default WorkSpec:

```bash
novel compose 仙侠新作
novel compose 仙侠新作 --workspec workspec.json
```

List and resume:

```bash
novel list
novel list --json
novel pending <name>
novel pending <name> --json
novel pending <name> --newer-than <timestamp> --json
novel pending <name> --slot-id <slot_id> --json
novel pending <name> --slot-id <slot_id> --prompt-hash <hash> --json
novel pending <name> --require-automation-ready --json
novel respond <name> --response-file response.json
novel respond <name> --response-file response.json --slot-id <slot_id>
novel respond <name> --response-file response.json --prompt-hash <hash>
novel respond <name> --response-file response.json --json
novel gate <name>
novel gate <name> --json
novel resume 示例小说甲
```

Long-form options (audit / extend):

```bash
novel audit 示例小说甲 --input 示例小说甲.txt --range 1-50 --batch-size 5 --max-chapters 200
novel audit 示例小说甲 --outline-only      # structure-overview only
```

- `--range A-B`: restrict to chapter range [A, B]
- `--batch-size N`: process N chapters per Rebuild batch
- `--max-chapters N`: hard cap on chapters per run
- `--outline-only`: produce OutlineUnit overview, skip detailed Rebuild
- chapter-wise audit / extend automatically run an outline stage when processing 30+ chapters; staged files are `outline_prompt.txt`, `outline_response.txt`, and `outline_result.json`
- input / WorkSpec hash is recorded in the mode output directory; mismatch on rerun is an error

Codex staged loop:

1. Run `novel <mode> <name> [parameters]`.
2. If the script prints `[WAITING]`, read the prompt file it names.
3. Generate the required JSON response and save it to the matching response file.
4. Re-run the same `novel` command until it exits with a final result.
5. Use `route_handoff.json` when a downstream orchestrator needs the structured Review route handoff.
6. `novel list` validates `route_handoff.json` against the final result when it is present; add `--json` for machine-readable task status rows with `schema_version=1`, `command=list`, structured route fields, pending-slot fields, `latest_mtime`, `pending_slot_id`, pending prompt hash / byte / mtime metadata, and the same automation-readiness metadata used by `novel pending --json`.
7. Run `novel pending <name>` when you need a read-only list of pending prompt/response slots; add `--json` for machine-readable output with `selection_method`, `slot_id`, pending prompt hash, positive pending prompt bytes, and automation-readiness metadata; pending slot prompt hashes and byte counts must match current prompt files, pending slot prompt mtime must match current prompt files, pending/list JSON prompt evidence must match current prompt files, pending response paths must not already exist, and all_pending entries must match current pending discovery; pass `--newer-than <finite-timestamp>` to filter stale prompts, pass `--slot-id <slot_id>` to verify one pending slot without writing a response, add `--prompt-hash <hash>` to preflight the expected prompt content hash before a provider call, and add `--require-automation-ready` when automation needs a non-zero exit unless exactly one verified staged slot is ready.
8. Run `novel respond <name> --response-file <path>` to materialize an existing raw response file into a pending staged slot; use `--slot-id <slot_id>` or `--prompt <prompt_file>` when multiple slots are pending, the write is bound to the verified prompt hash, `--prompt-hash <hash>` additionally requires a caller-provided expected hash, and `--json` emits machine-readable write metadata including `selection_method`, `slot_id`, prompt / response hashes, prompt / response byte counts, and the staged response materialization contract. `response_source_hash` / `response_source_bytes` are computed from the same source bytes that were decoded for the staged write; staged response writes preserve decoded UTF-8 bytes without platform newline translation; before JSON success is emitted, the prompt must still match the verified prompt hash, the staged `response_hash` must match the text just written, `response_source` must not match staged `prompt_path` or `response_path`, respond JSON file evidence must match current files, respond JSON source text must match staged response file, respond JSON response text must be non-empty, respond JSON response_source mtime must not be older than prompt_path, respond JSON response_path mtime must not be older than prompt_path, response bytes must be at least response characters, response source bytes must not be less than staged response bytes, and response source bytes / staged response bytes / response characters must be positive response materialization counts.
9. Run `novel gate <name>` when you need a read-only orchestration gate verdict for the saved workspace; add `--json` for machine-readable output.
10. For subcommands that accept `--json`, argument and runtime failures are emitted as JSON with `ok=false`, `error_stage`, `error_type`, and `error`; `error_stage` is `argument` before argparse succeeds and `runtime` after parsed execution begins; `error_type` must be an exception class identifier; runtime failures include a supported parsed `command`; commands with a novel argument require parsed `novel`, while `list` errors require `novel=null`; object-shaped payloads include `schema_version=1`, object-shaped success payloads include `ok=true` and `command`, and `list --json` remains a top-level array of versioned rows with `command=list`.
10. Report the final artifact path and route summary.

Helpful commands:

```bash
novel --help
novel audit --help
novel extend --help
novel compose --help
novel pending --help
novel respond --help
novel gate --help
pytest tests/ -q
```

Response files are the resume points. If a response file is missing, the script prints `[WAITING]` and exits normally; re-run the same script after saving the response.
Existing prompt and response files are preserved as staged evidence; the file-exchange interface fails instead of overwriting them.
Prompt files must use the `<valid-slot>_prompt.txt` naming contract and point to the matching same-directory `<slot>_response.txt`; slot ids are ASCII slugs using letters, digits, `_`, and `-`, and cannot be blank, path-like, whitespace-padded, or end with staged prompt/response suffixes.
Pending-slot discovery rejects empty prompt files instead of listing them as work for automation.
The `[AGENT_ACTION]` block includes `schema_version`, `slot_id`, `prompt_hash`, and positive `prompt_bytes`; action payload generation validates before returning; pass the hash back through `novel respond --prompt-hash` when you need an explicit write guard.
Automation clients can parse this block with `parse_file_exchange_action_block()`, which requires non-empty text output and rejects unknown fields, unsupported schema versions, and blank prompt/response path metadata through the same `FileExchangeAction` structure checks used when printing the block.
Before accepting a response file, the file-exchange interface rechecks that the prompt still matches that hash.
Automation adapters may use `StagedResponseRunner.call_single_pending()` only when there is exactly one pending slot, or `call_pending_slot()` when the caller supplies an explicit `slot_id`; pending discovery output_dir must be absolute, pending slot paths must be absolute, pending response paths must not already exist, and both runner paths bind the write to the discovered prompt hash and require response slot paths to be absolute before provider calls or response writes. They also require the interface name snapshot to stay stable during the provider call. Use the corresponding result-returning methods when an adapter needs `StagedResponseResult` audit metadata for the prompt hash, response hash, byte counts, slot id, and interface name; `interface_name` must not contain whitespace, and result paths must be absolute; the result object validates that metadata against the current staged files, `to_payload()` emits versioned metadata without response text and records that only staged response materialization occurred, and `from_payload()` rejects unknown fields, old payloads missing that materialization contract, non-string or blank path/file metadata, relative result paths, and any payload claiming a provider call or closed-loop advance before revalidating file evidence.
Shared automation contract constants, exact field-order declarations, metadata builders, metadata fragment extractors, in-payload metadata validators, pending metadata exact-field validation, and materialization metadata exact-field validation live in `src/boundary_control/automation_contracts.py`; CLI JSON self-validates those fragments before emit, staged response result payloads reuse the same helpers, and future UI/provider adapters must use those helpers instead of duplicating contract strings, slicing fragments ad hoc, composing validation steps, or assembling those payload fragments by hand.
That module is metadata-only: it must not import filesystem, provider, route, handoff, or runner dependencies.
The CLI pending JSON payload also self-validates its exact pending fields, string keys, workspace novel names, `output_dir` must be absolute, pending slot entry fields, expected prompt hashes, positive pending prompt bytes, pending slot prompt hashes and byte counts must match current prompt files, pending slot prompt mtime must match current prompt files, pending/list JSON prompt evidence must match current prompt files, pending response paths must not already exist, all_pending entries must match current pending discovery, expected prompt hash binding, selection method contract, pending preflight requires slot_id selection, freshness timestamps, route_artifact_mtime must match current route artifacts, prompt_mtime must be newer than effective freshness cutoff, effective freshness cutoff, and `pending_count` versus pending entries before emit.
The CLI respond JSON payload also self-validates its exact respond fields, string keys, content hashes, expected prompt hashes, expected prompt hash binding, selection method contract, freshness timestamps, route_artifact_mtime must match current route artifacts, prompt_mtime must be newer than effective freshness cutoff, effective freshness cutoff, byte/character counts, response_bytes must be at least response_chars, response_source_bytes must not be less than response_bytes, prompt-hash verification flag, `response_source` must not match staged `prompt_path` or `response_path`, respond JSON file evidence must match current files, respond JSON source text must match staged response file, respond JSON response text must be non-empty, respond JSON response_source mtime must not be older than prompt_path, respond JSON response_path mtime must not be older than prompt_path, and materialization metadata before emit. Response materialization audit flags `provider_call_performed` and `closed_loop_advanced` must be exact `false`; numeric stand-ins such as `0` are not accepted.
The CLI gate JSON payload also self-validates exact gate fields, string keys, violation lists, blocking pending prompt file lists, blocking prompt files must be staged prompt filenames, gate package file must match mode, gate JSON artifact existence must match current files, gate JSON route handoff content must match current handoff file, gate JSON verdict fields must match current gate verdict, ContinueUnit pass requires package_present, and `blocking_pending_count` before emit. With `novel gate --require-approval`, the CLI emits an independent self-validating approval gate JSON contract — the same 13 standard gate fields as a verbatim prefix plus four approval fields (`approval_required`, `critical_issue_ids`, `approval_decision`, `approval_ok`); the default `novel gate` output is unchanged.
The CLI list JSON row payload also self-validates exact list row fields, string keys, finite non-negative `latest_mtime`, latest_mtime must match current workspace files, list JSON detail must match status and route evidence, list row pending prompt mtime, pending_prompt_mtime must be newer than current route artifacts, list row pending prompt bytes, pending/list JSON prompt evidence must match current prompt files, pending response paths must not already exist, list waiting rows must match current pending discovery, list JSON artifact existence must match current files, list JSON final result route content must match current result file, list JSON route handoff content must match current handoff file, list JSON gate verdict fields must match current gate verdict, pending metadata / count consistency, and gate blocking metadata before emit while keeping the top-level list output as an array.
`novel pending --json` exposes `automation_contract_version`, `automation_contract`, `automation_ready`, `automation_ready_reason`, `automation_blockers`, `allowed_automation_action`, `provider_calls_implemented`, and `closed_loop_allowed`. Pending automation contract/action/reason labels must be non-empty strings, and `automation_blockers` must be a list of non-empty strings. `automation_ready=true` only authorizes the caller to prepare the same staged response materialization path; provider calls remain unimplemented and closed-loop workflow advancement remains disallowed. `--require-automation-ready --json` turns not-ready metadata into an `ok=false` runtime result while preserving the same evidence and blockers.

## Core Objects

- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

## Core Judgments

- State first, text second.
- Facts must be separated from inference.
- A `PlotUnit` is only valid if it causes meaningful state change.
- `Review` is the routing hub of the operational workflows.
- Formal `Rewrite` should be issue-driven, not feeling-driven.

## Workflow Map

- `Rebuild`: reconstruct object state from existing text
- `Review`: judge validity, classify failures, and route next action
- `Continue`: generate the next valid progression from current state
- `Rewrite`: apply minimal repair based on formal issues

## Read First

If you are a newly opened agent, read in this order:

1. `AGENTS.md`
2. `docs/00_project/02_agent_quickstart.md`
3. `docs/00_project/03_current_status.md`
4. `docs/00_project/06_foundation_checkpoint.md`
5. `docs/00_project/07_phase_transition_memo.md`
6. `docs/00_project/08_foundation_phase_gate.md`
7. `docs/00_project/09_preimplementation_boundary_lock.md`
8. `docs/00_project/10_transition_planning.md`
9. `docs/00_project/11_implementation_planning_entry_pack.md`
10. `docs/00_project/12_serialization_candidate_note.md`
11. `docs/00_project/13_handoff_schema_candidate_note.md`
12. `docs/00_project/14_runtime_orchestration_boundary_note.md`
13. `docs/00_project/15_no_regression_verification_checklist.md`
14. `docs/00_project/16_implementation_planning.md`
15. `docs/00_project/17_implementation_unit_map.md`
16. `docs/00_project/18_serialization_responsibility_map.md`
17. `docs/00_project/19_workflow_handoff_responsibility_map.md`
18. `docs/00_project/20_orchestration_gate_map.md`
19. `docs/00_project/21_no_regression_acceptance_test_list.md`
20. `docs/00_project/27_deployment_shape_decision.md`
21. `docs/00_project/04_agent_operating_model.md`
22. `docs/00_project/05_narrative_agent_harness.md`
23. `docs/00_project/00_project_brief.md`
24. `docs/00_project/01_scope_and_boundaries.md`
25. `docs/07_decisions/03_workflow_order_decisions.md`
26. `docs/07_decisions/08_context_packaging_decisions.md`
27. `docs/07_decisions/09_review_reminder_decisions.md`
28. `docs/07_decisions/10_ownership_matrix_decisions.md`
29. `docs/07_decisions/11_reviewreminder_escalation_matrix.md`
30. `docs/07_decisions/12_concurrent_reminder_routing_decisions.md`
31. `docs/07_decisions/13_factledger_admission_thresholds.md`
32. `docs/00_project/28_directapi_boundary_note.md`
33. `docs/00_project/29_automation_readiness_boundary.md`
34. `docs/00_project/30_production_readiness_checklist.md`
35. `docs/00_project/31_tier0_canary_runbook.md`
36. `docs/00_project/32_tier0_release_record_contract.md`

## Current Repository Shape

The repository now contains both a complete design layer and a running implementation layer.
That is a current-state description, not a permanent restriction on later phases.
