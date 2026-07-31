# DirectAPI Boundary Note

## Status

DirectAPI provider calling is not implemented.

The default v0 runtime remains staged file exchange through
`FileExchangeInterface` and the `novel` CLI.

`FileExchangeInterface` treats existing prompt and response files as staged
evidence and fails rather than overwriting them.
Existing prompt or response evidence is rejected before new prompt text is
validated, so evidence conflicts are not masked by bad new input. It validates
that prompt text is non-empty and UTF-8 encodable before creating the prompt
directory or staged prompt file.
It also requires prompt files to use the `<valid-slot>_prompt.txt` naming
contract and point to the matching same-directory `<slot>_response.txt` before
writing a prompt. Valid slot ids are ASCII slugs: letters, digits, `_`, and
`-`.
Those path and timeout settings are validated when the interface is
constructed; invalid staged configuration should not survive until call time.
Its `[AGENT_ACTION]` block includes `schema_version`, `slot_id`, prompt content
hash, and prompt byte count so response materialization can identify the action
contract and slot while binding back to the exact prompt. The hash remains the
write-binding identity; the byte count is positive prompt_bytes audit metadata.
The block is generated from one `FileExchangeAction` metadata object, so the
printed fields are covered as a single contract. FileExchangeAction action payload generation validates before returning, so corrupted in-memory action metadata cannot print a machine-readable block.
`FileExchangeAction` validates its own schema version, action type, interface,
required metadata, staged prompt / response / slot-id relationship, and
prompt-hash shape before it can print a machine-readable block; filesystem
state remains the parser and response-boundary responsibility.
FileExchange action blocks must not include credential fields such as `api_key`,
`credential`, `credentials`, `secret`, or `token`.
FileExchange action blocks must not include execution claim fields such as
`provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
`closed_loop_result`.
FileExchange action blocks must not include automation or materialization metadata
fields such as `automation_ready`, `automation_blockers`,
`provider_call_performed`, or `closed_loop_advanced`.
action blocks must not include automation or materialization metadata fields.
When parsing a printed block, `prompt_bytes` must use the same canonical decimal
string that `FileExchangeAction` emits and must be positive prompt_bytes;
padded, signed, or zero numeric variants are not accepted as equivalent evidence.
Automation clients may use `parse_file_exchange_action_block()` to parse the
block. The parser requires non-empty text output with exactly one block, rejects
unknown, duplicate, or missing fields, rejects unsupported action types, and
only accepts the current schema version. It only accepts the default
`FileExchangeInterface` action contract, not provider-specific or DirectAPI
action blocks. It reuses
`FileExchangeAction` structure checks, so blank prompt / response path metadata
fails before filesystem checks. It also verifies that `response_file` and
`slot_id` match the staged naming contract implied by `prompt_file`. The parser
requires `prompt_hash` to be a valid content hash
and, when parsing against the current workspace, verifies it against the
referenced prompt file instead of trusting the printed value alone. It also
requires `prompt_bytes` to match that same prompt file. It rejects empty
referenced prompt files, including BOM-only prompt files where the BOM is only
an encoding marker, and pending action blocks whose referenced prompt file
cannot be decoded as UTF-8 / UTF-8-sig fail as prompt-evidence errors. Action
blocks whose response file already exists are rejected because those are not
pending LLM actions. Existing response files are rejected before prompt content
is decoded, so a completed/non-pending slot is not masked by missing or damaged
prompt files.
Before returning a staged response, it rechecks that the prompt file still
matches that hash. The response file is read as one UTF-8 byte snapshot, not
through platform newline translation, so the returned raw response text
preserves staged response newline bytes. UTF-8 BOM bytes in the response file
are treated as an encoding marker before parser handoff, while the response
file bytes remain unchanged on disk.

`ResponseFileBoundaryUnit` owns the future DirectAPI / UI write boundary for
staged responses.
Response slot paths must be absolute. The response slot paths must be absolute
rule fails before provider calls or response writes, so relative staged paths
cannot produce a response file and then fail during audit result construction.

It can discover pending response slots from an output directory. Automation
must either require exactly one pending slot or name an explicit `slot_id`
before materializing a response. Multiple pending prompts are an ambiguity, not
a reason to guess by filename or timestamp.
When a caller supplies a `newer_than` freshness filter, it must be a finite
non-negative numeric timestamp. Invalid freshness filters fail before provider
calls or response writes.
The unified CLI exposes that read-side freshness filter as
`novel pending <name> --newer-than <timestamp> --json`. It is sorting and
staleness metadata, not a replacement for prompt-hash verification.
Even without a caller-provided freshness filter, `novel pending` applies the
latest final-result or `route_handoff.json` mtime as an automatic cutoff. A
prompt older than the current route artifact is stale and is not exposed to
automation, including explicit `--slot-id` selection. JSON output reports both
the caller's `newer_than` value and the resulting `effective_newer_than`.
The `effective_newer_than` value is the effective freshness cutoff: for pending
JSON it must equal the maximum of caller `newer_than` and `route_artifact_mtime`,
and for respond JSON it must match `route_artifact_mtime`.
The cutoff source is validated before it can hide a pending slot: malformed
final-result route JSON, invalid route handoff packets, handoff/final route
mismatches, or route handoffs without final results fail as route-artifact
errors instead of being treated as trusted timestamps.
`novel list` uses the same validated route-artifact cutoff before reporting
waiting rows, so list output and pending/respond automation cannot disagree
about whether damaged route artifacts are blocking evidence.
Its `gate_ok` / `gate_violations` metadata also includes the same stale-handoff
pending prompt blocker as `novel gate`, even when a newer final result means the
row itself is no longer reported as waiting.
`novel gate` also refuses a route handoff when a pending staged prompt is newer
than that handoff, because the workspace has advanced to a newer manual/model
response step and the old route packet is no longer the current automation
entry.
When a final result file exists, `novel gate` also requires its route to match
the saved route handoff before running the package gate, so gate, list,
pending, and respond do not disagree about the current route state.
`novel gate --json` validates its complete CLI gate JSON payload before emit:
payload keys must be strings, exact gate fields are enforced, violation lists
must contain strings, and `blocking_pending_count` must match the number of
blocking pending prompt files.
Pending discovery validates that a waiting prompt is non-empty and decodable as
UTF-8 / UTF-8-sig. An empty or damaged staged prompt is a boundary error, not a
pending slot.
Completed slots whose response file already exists are skipped before prompt
decoding, so damaged historical prompt bytes do not block discovery of other
pending slots or get reported as selected pending slots. The `novel pending`
and `novel respond` commands use that same discovery behavior for default and
explicit `slot_id` selection.
`PendingResponseSlot` validates its own prompt / response naming, `slot_id`,
prompt mtime, prompt-hash metadata, positive prompt_bytes, and unfinished
response state before it can be exposed to CLI, UI, or automation callers.
pending discovery output_dir must be absolute, pending slot paths must be absolute,
and pending response paths must not already exist before `PendingResponseSlot`
evidence can be exposed to adapters.

`StagedResponseRunner` is the thin connector that may read one existing prompt,
call an `LLMInterface`, and materialize the returned raw text through
`ResponseFileBoundaryUnit`.
It requires a real `ResponseFileBoundaryUnit` boundary and a real
`LLMInterface`; invalid runner wiring fails before provider calls or file
writes.
Its `call_single_pending()` entry requires exactly one pending prompt.
Its `call_pending_slot()` entry accepts an explicit `slot_id` for callers that
already selected a pending slot from machine-readable metadata. Both paths bind
the write to the prompt hash discovered from that slot. Pending-slot discovery
and selected-slot verification run before provider-interface type checks, so a
completed, missing, ambiguous, stale, or damaged slot is reported as staged
evidence instead of being masked by bad provider wiring. After slot verification
and before calling the provider, the runner rereads the prompt as one non-empty
UTF-8 / UTF-8-sig byte snapshot; if the prompt became empty or cannot be
decoded, the provider is not called.
The runner also binds the interface name snapshot before provider execution and
checks it again before materializing the response; if the provider call mutates
the interface audit name, the response file is not written.
For automation that needs audit metadata, the runner also exposes
`call_and_materialize_result()`, `call_single_pending_result()`, and
`call_pending_slot_result()`. These return `StagedResponseResult` with the
verified prompt path, response path, slot id, interface name, prompt hash /
bytes, and materialized response hash / bytes / character count.
`interface_name` must not contain whitespace. The interface_name must not contain whitespace rule prevents adapter audit payloads from representing the same provider under padded or space-separated names.
Staged response result paths must be absolute. The result paths must be absolute rule prevents adapter audit payloads from resolving staged evidence relative to whichever process consumes the payload.
`StagedResponseResult` validates that those hashes, positive byte counts, and
positive response character count match the current prompt and response files
before the object is accepted. The existing path-returning methods remain thin
compatibility wrappers over those result methods.
`StagedResponseResult.to_payload()` returns a versioned machine-readable audit
payload for UI/provider adapters; it includes only paths, slot/interface
metadata, hashes, positive counts, and staged materialization audit fields, not
response text. The materialization fields state that the
action was `materialize_staged_response_only`, `provider_call_performed=false`,
and `closed_loop_advanced=false`.
Those two audit flags must be exact JSON `false`; numeric stand-ins such as `0`
are not accepted as no-provider/no-closed-loop evidence.
Staged response result payload generation validates before returning, so
corrupted in-memory result objects cannot rewrite adapter audit evidence.
`StagedResponseResult.from_payload()` rejects missing or unknown fields,
including accidental `response_text`, verifies schema version, result type, and
the materialization contract, rejects payloads that claim provider calls or
closed-loop advancement, rejects non-string or blank prompt/response path and
filename metadata, checks prompt/response filenames against their paths, and
then reuses the same file-evidence validation as direct result construction.
Staged response result payloads must not include credential fields.
Staged response result payloads must not include execution claim fields.
Staged response result payloads must not include pending automation metadata fields.
Staged response result payloads must not include prompt or response content fields.
Staged response result payload keys and shared pending/materialization metadata
payload keys must be strings, matching JSON object semantics; Python-only
non-string keys must fail before field-whitelist or metadata-fragment checks.

`DirectAPIInterface` defines only the provider-agnostic request / response
contract used by future adapters:

- input: `DirectAPIRequest(prompt, model)`
- output: `DirectAPIResponse(text, model)`
- request / response objects expose strict `to_payload()` / `from_payload()`
  round-trips with `schema_version=1`, distinct request/response `type`
  values, exact field whitelists, and the same prompt/text/model validation as
  direct object construction; to_payload() validates before returning so
  audit payload generation and audit payload parsing share the same gate
- shared DirectAPI audit payload consumption must go through
  `parse_direct_api_payload()`, which validates `schema_version` and `type`
  before dispatching to the request or response parser
- parse_direct_api_payload() enforces the DirectAPI credential-field ban before type dispatch, then the request / response payload parsers enforce it again
- request / response payload parsing requires both identity fields,
  `schema_version` and `type`, before accepting provider-audit data
- DirectAPI request / response payload keys must be strings, matching JSON
  object semantics; Python-only non-string keys must fail before payload
  dispatch or field-whitelist checks
- DirectAPI audit payloads must not include credential fields such as
  `api_key`, `credential`, `credentials`, `secret`, or `token`; these fail as
  credential-field violations before generic unknown-field handling
- DirectAPI audit payloads must not include execution claim fields such as
  `provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
  `closed_loop_result`; these fail as execution-claim violations before generic
  unknown-field handling
DirectAPI audit payload execution-claim violations before generic unknown-field handling.
- DirectAPI audit payloads must not include automation or materialization metadata
  fields such as `automation_ready`, `automation_blockers`,
  `provider_calls_implemented`, `materialized_action`,
  `provider_call_performed`, or `closed_loop_advanced`
DirectAPI audit payloads must not include automation or materialization metadata fields.
DirectAPI audit payload cross-contract metadata violations before generic unknown-field handling.
- those payload round-trips are serialization/audit boundaries; the
  `DirectAPIInterface.call()` path remains object-level and does not convert
  provider requests or responses through payload dictionaries
- staged automation contract constants, exact field-order declarations, metadata
  builders, metadata fragment extractors, in-payload metadata validators,
  pending metadata exact-field validation, and materialization metadata exact-field validation live in
  `src/boundary_control/automation_contracts.py`; future DirectAPI or UI
  adapters must consume those constants for pending readiness and staged
  response materialization payloads instead of duplicating contract strings,
  boolean flags, or payload fragments; CLI JSON self-validates those fragments
  before emit
- CLI JSON error payload construction is also local-contract validated: error
  payload keys must be strings, exact error fields are enforced for argument and
  runtime failures, `error_type` must be an exception class identifier, runtime
  context must include a supported non-empty `command`, commands with a novel
  argument require runtime `novel` as a non-empty string, `list` runtime errors
  require `novel=null`, and runtime errors carry only parsed `command` /
  `novel` context in addition to the base error fields; base error payloads are
  argument-stage only
- CLI JSON error payloads must be built through _json_error_payload(), and
  direct `{"ok": false}` error payload literals outside that helper are rejected
  by the runtime contract tests.
- CLI JSON error payload call sites must be guarded by JSON mode:
  `NovelArgumentParser.error` requires `self.emit_json_errors`, and runtime
  errors require `getattr(args, "json", False)`.
- runtime CLI JSON error payload call sites must include runtime context:
  `command`, `novel`, and `include_runtime_context=True`; only argument parser
  errors may use the base argument payload.
- Only NovelArgumentParser.error may emit the base argument JSON error payload;
  all other CLI JSON error payload call sites are runtime-context payloads.
- CLI JSON error payload call sites must declare literal error_stage by context:
  argument parser errors use `error_stage="argument"`, and runtime errors use
  `error_stage="runtime"`.
- CLI JSON error payload call sites must declare error_type by context:
  `NovelArgumentParser.error` uses `ArgumentError`, and runtime errors derive
  `error_type` from the caught exception class name.
- CLI JSON error payload call sites must declare error message source by context:
  `NovelArgumentParser.error` uses the parser `message`, and runtime errors use
  `str(exc)` from the caught exception.
- CLI JSON error payloads must not include credential fields such as `api_key`,
  `credential`, `credentials`, `secret`, or `token`; error payloads must not
  include credential fields before generic unknown-field handling
- CLI JSON error payloads must not include execution claim fields such as
  `provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
  `closed_loop_result`; error payloads must not include execution claim fields
  before generic unknown-field handling
- CLI JSON error payloads must not include cross-contract metadata fields such
  as `automation_ready`, `automation_blockers`, `provider_calls_implemented`,
  `materialized_action`, `provider_call_performed`, or `closed_loop_advanced`;
  error payloads must not include cross-contract metadata fields before generic
  unknown-field handling
- CLI JSON error payloads must not include prompt or response content fields
  such as `prompt`, `response_text`, `text`, or `model`; error payloads must
  not include prompt or response content fields before generic unknown-field
  handling
- CLI mode whitelist is enforced before CLI JSON payloads can be emitted or
  consumed: pending/respond/gate payloads only accept `audit`, `extend`, or
  `compose`, while list payload rows may use `unknown` only for initialized
  rows without route or pending evidence.
- exact-field CLI JSON payloads must not include credential fields such as
  `api_key`, `credential`, `credentials`, `secret`, or `token`.
- exact-field CLI JSON payloads must not include execution claim fields such as
  `provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
  `closed_loop_result`.
- exact-field CLI JSON payloads must not include prompt or response content
  fields such as `prompt`, `response_text`, `text`, or `model`.
- exact-field CLI JSON payloads must not include cross-contract metadata fields
  from another runtime contract; pending/list payloads reject response
  materialization metadata, respond payloads reject pending automation metadata,
  and gate payloads reject both metadata families.
- exact-field validator call sites must declare cross-contract metadata policy
  when they use the shared exact-field gate, so new CLI JSON payload families do
  not silently inherit a generic unknown-field-only posture.
- object-shaped CLI JSON payload literals with ok must declare schema_version and command
  before they can be consumed by UI/provider automation.
- ok=true CLI JSON payload literals must not declare error fields; success and
  status evidence must stay separate from error payload evidence.
- ok=false CLI JSON payload literals outside _json_error_payload() must declare error fields;
  failure evidence must include stage, type, and message.
- CLI stdout JSON dumps must emit only payload or rows contract variables.
- CLI JSON object payload emits must validate payload before print; error
  payloads do this through `_json_error_payload()`, while success/status payloads
  use their explicit `_validate_*_json_payload()` gate.
- CLI JSON object payload emits must validate after last payload assignment before print.
- CLI JSON object payload emits must validate after last payload mutation before print.
- CLI pending JSON payload construction is local-contract validated before
  emit: payload keys must be strings, exact pending fields are enforced,
  workspace novel names must remain single workspace segments,
  output_dir must be absolute, output_dir must be output/<mode>,
  pending slot paths must be under output_dir, pending
  slot entries must keep the declared slot fields, pending slot entries must
  not include credential fields, pending slot entries must not include execution
  claim fields, pending slot entries must not include prompt or response content
  fields, pending slot entries must not include cross-contract metadata fields,
  staged prompt/response/slot
  identity must be internally consistent, pending slot prompt hashes must be
  valid content hashes, positive pending prompt bytes are required,
  pending slot prompt hashes and byte counts must match current prompt files,
  pending slot prompt mtime must match current prompt files,
  pending/list JSON prompt evidence must match current prompt files,
  pending response paths must not already exist,
  caller-provided expected prompt hashes must be valid content hashes, expected
  prompt hash binding must match the current prompt hash, pending slot prompt mtime
  must be a finite non-negative number, freshness timestamps must be
  finite non-negative numbers or null, route_artifact_mtime must match current route artifacts,
  prompt_mtime must be newer than effective freshness cutoff, the effective
  freshness cutoff must match caller and route-artifact inputs, and `pending_count` must match the number
  of pending entries. all_pending entries must match current pending discovery.
  The selection method contract only accepts
  `all_pending` or `slot_id`; `slot_id` selection must bind the top-level
  `slot_id` to the selected pending entry, and `all_pending` must not claim a
  top-level selected slot. pending preflight requires slot_id selection before
  `expected_prompt_hash` can appear.
- CLI respond JSON payload construction is local-contract validated before
  emit: payload keys must be strings, exact respond fields are enforced,
  content hashes and caller-provided expected prompt hashes must be valid content
  hashes, expected prompt hash binding must match the current prompt hash,
  prompt byte count must be a positive integer, response source bytes,
  staged response bytes, and response characters must be positive response
  materialization counts, staged prompt/response/slot identity must be internally
  consistent, staged prompt/response paths must be absolute,
  respond staged paths must be under output/<mode>,
  response_source must be an absolute path, freshness timestamps must be finite
  non-negative numbers or null, route_artifact_mtime must match current route artifacts,
  prompt_mtime must be newer than effective freshness cutoff, the effective freshness cutoff must match route-artifact input, and
  `prompt_hash_verified` must match `expected_prompt_hash`.
  The selection method contract only accepts `single_pending`, `slot_id`, or
  `prompt_file`.
- CLI gate JSON payload construction is local-contract validated before emit:
  payload keys must be strings, exact gate fields are enforced, violation lists
  must contain strings, gate review route matrix must match the Handoff route
  contract, gate verdict consistency is enforced, gate artifact paths must be absolute,
  artifact paths must be under output/<mode>,
  artifact paths must share output directory,
  gate package file must match mode,
  gate JSON route handoff content must match current handoff file,
  gate JSON verdict fields must match current gate verdict,
  route handoff file must be route_handoff.json,
  blocking prompt files must be staged prompt filenames, and
  ContinueUnit pass requires package_present before
  `blocking_pending_count` can be trusted against blocking prompt files
- CLI list JSON row payload construction is local-contract validated before
  emit: row keys must be strings, exact list row fields are enforced,
  finite non-negative latest_mtime is required, latest_date must match latest_mtime, latest_mtime must match current workspace files, `pending_count` must match readiness
  metadata, list row status/pending consistency is enforced, list route/status/workflow consistency is enforced, list route artifact consistency is enforced, list gate artifact consistency is enforced, list gate metadata completeness is enforced, staged prompt/response/slot identity must be internally consistent
  for pending rows, staged prompt/response paths must be absolute,
  final result file must match mode, list JSON final result route content must match current result file, route handoff file must be route_handoff.json, list artifact paths must be absolute, list JSON artifact existence must match current files, list JSON route handoff content must match current handoff file, list JSON gate verdict fields must match current gate verdict, artifact paths must be under output/<mode>, artifact paths must share output directory, artifact file fields must match path names,
  list JSON detail must match status and route evidence,
  pending response paths must not already exist,
  gate verdict consistency is enforced when a gate verdict is present,
  list row pending prompt mtime must be a finite non-negative number,
  pending_prompt_mtime must not exceed latest_mtime,
  pending_prompt_mtime must be newer than current route artifacts,
  list row pending prompt bytes must be positive, list waiting rows must match current pending discovery, gate blocking
  prompt files must be staged prompt filenames, gate package file must match mode, gate JSON artifact existence must match current files, gate JSON route handoff content must match current handoff file, gate JSON verdict fields must match current gate verdict, list JSON gate verdict fields must match current gate verdict, ContinueUnit pass requires package_present, and gate blocking counts must match blocking prompt files; the
  top-level list output remains an array for compatibility
- pending readiness boolean fields must be exact JSON booleans; numeric
  stand-ins such as `0` or `1` are not accepted as automation evidence
- pending automation metadata source payloads and response materialization
  metadata source payloads must not include credential fields such as
  `api_key`, `credential`, `credentials`, `secret`, or `token`
- pending automation metadata payloads and response materialization metadata
  payloads must reject credential fields before unknown-field handling
- pending automation metadata source payloads, response materialization metadata
  source payloads, pending automation metadata payloads, and response
  materialization metadata payloads must not include execution claim fields such
  as `provider_call_result`, `provider_response`, `retry`, `fallback_provider`,
  or `closed_loop_result`
- pending automation metadata source payloads must not include response
  materialization metadata fields, and response materialization metadata source
  payloads must not include pending automation metadata fields; metadata source
  payloads must not include cross-contract metadata fields
- `automation_contracts.py` is metadata-only and must not import filesystem,
  provider, route, handoff, or runner dependencies
- `call(prompt)` returns raw response text only; non-empty response text is
  returned unchanged, without stripping or newline normalization
- provider request objects are checked against their prompt/model snapshots
  after provider return, so corrupted in-memory `DirectAPIRequest` instances
  cannot rewrite call evidence
- provider response objects are revalidated before returning text, so corrupted
  in-memory `DirectAPIResponse` instances cannot bypass response text or model
  checks
- prompt must be non-empty and UTF-8 encodable before any provider call or
  missing-provider error; after that validation, the prompt text is sent to the
  provider unchanged when a provider adapter exists
- model identifiers must be non-empty, UTF-8 encodable, and must not contain
  whitespace
- each call validates and binds the current model identifier snapshot before
  missing-provider checks or request construction; changing the interface model,
  API key, or provider adapter during a call is a contract failure
- each call validates the current optional API key and provider adapter snapshot
  before request construction; a polluted API key or non-callable provider
  adapter is a configuration error, not a provider result
- normal assignment to `model`, `api_key`, and `provider_call` uses the same
  validation rules, while `call()` still revalidates the private snapshots
  before request construction and again after provider return
- `name()` also validates the current model identifier before returning an
  audit label, so corrupted interface state is not exposed as trusted metadata
- `DirectAPIRequest` and `DirectAPIResponse` reject empty or non-UTF-8-encodable text fields at construction time and during payload parsing
- optional `api_key` must be omitted or a non-empty UTF-8-encodable identifier
  without whitespace
- configured provider adapters must be callable at `DirectAPIInterface` construction time

Without a provider adapter, `DirectAPIInterface.call()` raises
`NotImplementedError`.

## Allowed Replacement

DirectAPI may replace only one human/manual action:

- write the raw response text that would otherwise be saved into the staged
  response file

That write must go through `ResponseFileBoundaryUnit`, which requires:

- an existing non-empty UTF-8 / UTF-8-sig decodable `*_prompt.txt`
- the matching same-directory `*_response.txt`
- no overwrite of an existing response file
- exclusive response-file creation at write time, so a response that appears
  after slot verification still blocks the write
- optional expected prompt-hash verification against a staged, non-empty prompt
  byte snapshot at the response boundary
- non-empty raw response text

The response-file boundary validates staged prompt / response slot evidence
before validating candidate response text, so an existing response file or
damaged prompt is not masked by empty or non-UTF-8-encodable response text.
For a matching staged response path, an existing response file is reported before
missing or damaged prompt content, because that slot is already completed and
must not be overwritten.
It also preempts caller-supplied prompt-hash errors for the same reason.

Automated response materialization may use `StagedResponseRunner`, but the
runner must use the same expected prompt-hash verification when a caller
provides one. It must not parse workflow JSON, choose routes, retry providers,
or write result artifacts. This thin-runner boundary is covered by a static
contract test over `StagedResponseRunner`.
When using `call_single_pending()`, multiple pending prompts fail before any
provider call; they are not resolved by timestamp or filename guesses. When
multiple prompts are pending, automation must pass an explicit `slot_id` through
`call_pending_slot()` or stop for caller selection.

Even without a caller-provided expected hash, `StagedResponseRunner` binds the
final write to the prompt hash it actually sent to the interface, so a prompt
that changes during provider execution blocks response materialization.
The shared response-file boundary treats UTF-8 BOM bytes in staged prompts as
encoding markers, so a BOM-only prompt is still an empty prompt and fails before
pending discovery, prompt-hash verification, provider calls, or response writes.

Machine-readable pending-slot metadata includes a prompt content hash and byte
count. Future UI or provider adapters should bind generated response text to
the prompt hash they consumed instead of relying only on filenames or
modification times; the byte count is audit metadata for prompt-size checks,
not the write-binding identity.
For selected slots, the returned prompt hash is refreshed through the response
boundary's prompt-hash verification step before it is exposed to callers.
`novel pending <name> --slot-id <slot_id> --json` exposes a read-only way to
verify that a selected slot is still pending before the caller prepares or
materializes response text.
`novel pending <name> --slot-id <slot_id> --prompt-hash <hash> --json` also
preflights the caller's expected prompt content hash without writing a response
or calling a provider.
That pending preflight requires slot_id selection; batch `all_pending` discovery
must not carry caller-provided `expected_prompt_hash` evidence.
Successful pending JSON reports `selection_method` as `all_pending` or
`slot_id`, so callers can distinguish bulk pending discovery from explicit slot
verification without inferring it from a nullable `slot_id` field.
It also reports `automation_contract_version`, `automation_contract`,
`automation_ready`, `automation_ready_reason`, `automation_blockers`,
`allowed_automation_action`, `provider_calls_implemented`, and
`closed_loop_allowed`. Provider or UI adapters may treat pending JSON as a
model-call preflight only when exactly one staged slot is verified and
pending automation contract/action/reason labels are non-empty strings,
`automation_blockers` follows the list-of-non-empty-strings contract and is
empty when ready; the allowed action remains
`materialize_staged_response_only`, provider calls remain unimplemented, and
closed-loop workflow advancement remains disallowed.
`novel pending <name> --require-automation-ready --json` is the read-only
automation gate form of the same preflight. When no staged slot or multiple
staged slots are present, it returns `ok=false` with `error_stage=runtime`
while preserving the same pending evidence, readiness contract fields, and
`automation_blockers`.
Prompt hashes use the shared content-hash validator; caller-provided expected
hash values must be valid content hashes before they can participate in write
binding. Expected prompt hash binding means that any caller-provided
`expected_prompt_hash` must equal the current staged `prompt_hash` before a
pending or respond JSON payload can be trusted.
It also includes `slot_id`, derived from the staged prompt filename without the
`_prompt.txt` suffix. `slot_id` is for display, filtering, and command routing;
it may select a pending slot, but prompt hash remains the write-binding
identity.
The derived `slot_id` must be non-empty, so `_prompt.txt` is not a valid staged
prompt name. Slot ids also cannot be path-like, whitespace-padded, or end with
the staged prompt/response suffixes, because those names are ambiguous when
serialized into CLI/UI/automation metadata.

The `novel respond <name> --response-file <path>` CLI command exposes the same
response-file boundary for existing raw response files. It does not call a
model provider. When multiple slots are pending, callers may select one with
`--slot-id <slot_id>` or the existing `--prompt <prompt_file>` option; passing
both is an error. Default selection, explicit `--slot-id`, and direct
`--prompt` selection all apply the same route-artifact freshness cutoff as
`novel pending`, so a prompt older than the latest final result or
`route_handoff.json` cannot be materialized. It always binds the write to the
prompt hash verified during the command; `--prompt-hash <hash>` additionally
requires a caller-provided expected hash. The response source file must be a
different filesystem file from the staged prompt and staged response files, so
callers cannot accidentally materialize prompt text as a response through
aliases such as hard links or reuse the target response path as its own source.
Its JSON output includes prompt, response source, and staged response hashes /
byte counts for audit without including response content. `response_source_hash`
and `response_source_bytes` are computed from the same response-source bytes
that were decoded into the staged response text as UTF-8 / UTF-8-sig, not from
a later second read of the source file. Successful JSON requires
`response_source` to be an absolute path, matching the resolved source identity
used for same-file checks and source-byte evidence. Response sources are not
decoded through input-text compatibility encodings such as GBK or GB18030. UTF-8
BOM bytes are treated as an encoding marker during decode, so a BOM-only
response source is still an empty response and fails before materialization. The
staged entry scripts also treat UTF-8 BOM bytes as
an input encoding marker before building prompts, so prompt text does not carry
the BOM as narrative content; their staged `*_response.txt` reads use the same
BOM-as-encoding-marker rule before workflow parser handoff. `prompt_hash` and
`prompt_bytes` are likewise emitted from one final prompt-file read before
success JSON. Before success JSON is emitted, the prompt file must still match
the verified prompt hash and staged `response_hash` must still match the
response text that was just written; otherwise the command fails with a hash
mismatch instead of returning mixed evidence.
Successful JSON also requires positive response materialization counts for
response source bytes, staged response bytes, and response characters, so
adapters cannot accept an empty response evidence set as a completed staged
write.
Successful JSON requires response_bytes must be at least response_chars and
response_source_bytes must not be less than response_bytes, so adapters cannot
emit impossible UTF-8 byte / character count evidence for a completed staged
write.
Successful JSON requires response_source must not match staged prompt_path or response_path, so adapters cannot claim a staged prompt or target staged response file as the external source that produced the materialized response.
Successful JSON requires respond JSON response_source mtime must not be older than prompt_path, so adapters cannot claim a stale external response source for a newer staged prompt.
Successful JSON requires respond JSON response_path mtime must not be older than prompt_path, so adapters cannot pair a newer staged prompt with an older response artifact.
respond JSON file evidence must match current files before machine-readable respond payloads can be trusted by UI/provider adapters.
respond JSON source text must match staged response file.
respond JSON response text must be non-empty.
Successful `respond --json` also reports `materialization_contract_version`,
`materialization_contract`, `materialized_action`,
`provider_call_performed=false`, and `closed_loop_advanced=false`, so callers
can audit that the command only materialized a staged response and did not call
a provider or advance workflow state.
Those two audit flags must be exact JSON `false`; numeric stand-ins such as `0`
are not accepted as no-provider/no-closed-loop evidence.
The same JSON payload reports `expected_prompt_hash` and
`prompt_hash_verified`, so UI or provider adapters can distinguish automatic
prompt binding from a caller-provided expected-hash preflight.
That payload is validated as a complete CLI respond JSON payload before emit,
not only as a materialization metadata fragment.
It also reports `selection_method` as `single_pending`, `slot_id`, or
`prompt_file`, so successful response materialization records how the pending
slot was selected instead of requiring callers to infer that from command
history.
Staged response writes preserve the decoded UTF-8 bytes without platform newline
translation or surrounding-whitespace normalization, so raw response newline
shape, including LF-only or CRLF text, remains unchanged in the staged response
file. Response text must be encodable as UTF-8 before the staged response file
is created; encoding failures surface without occupying the pending response
slot.
Successful object-shaped JSON payloads include `ok=true` and `command`;
runtime or argument failures include `ok=false` with `error_stage`, `error_type`,
and `error`. `error_stage` is `argument` before argparse succeeds and `runtime`
after parsed execution begins. `error_type` must be an exception class
identifier. Runtime failures include a parsed `command` field; it must be a
non-empty supported CLI command so automation can group errors without relying
only on external call context. Commands with a novel argument require runtime
`novel` as a non-empty string, while `list` runtime errors require
`novel=null`. Base error payloads are reserved for argument-stage failures
before parsed runtime context exists.
Object-shaped JSON payloads include `schema_version=1`; `list --json` remains
a top-level array for compatibility, and each row carries `schema_version=1`
and `command=list`. Each row is still a fully validated CLI list JSON row
payload before emit, so the array shape does not weaken row-level contract
checks.
CLI list JSON rows emits must validate rows before print.
CLI list JSON rows emits must validate after last rows mutation before print.
CLI list JSON rows emits must validate after last rows in-place mutation before print.
CLI empty list JSON emits must validate empty list before print.
List rows also carry `latest_mtime`; waiting rows carry `pending_prompt_mtime`
and positive `pending_prompt_bytes`; all list rows carry the same automation-readiness
metadata used by `pending --json`, so batch callers can identify candidate
workspaces before running the stricter pending gate; `pending --json` and
`respond --json` report `route_artifact_mtime` and `effective_newer_than` for
stale-slot audits.
These timestamps are sorting and freshness metadata, not a substitute for prompt
hash binding or route validation; route_artifact_mtime must match current route artifacts,
prompt_mtime must be newer than effective freshness cutoff, non-null freshness
timestamps and list finite non-negative latest_mtime values are required, and
list latest_mtime must match current workspace files before DirectAPI can
consume the row.

It must still consume the same prompt text and return the same response text
shape expected by the workflow unit parser.

The future provider adapter is allowed to fill `DirectAPIResponse.text`, but it
is not allowed to parse workflow JSON, change routes, or write final artifacts.
`DirectAPIInterface.call()` is statically tested to stay out of workflow JSON
parsing, route selection, response-boundary materialization, and file writes.
Its call-path control flow is also statically tested against retry loops,
fallback hooks, exception translation blocks, and request/response payload
dictionary conversion.

## Fixed Boundaries

DirectAPI must not change:

- workflow order
- staged prompt / response contract
- `build_prompt()` / `parse_response()` boundaries
- `HandoffPacket` / `NextRoute` validation
- `ReviewIssue` / `ReviewReminder` validation
- serialization and no-regression checks

## Error Rules

DirectAPI must expose provider and schema errors to its caller.

The current contract tests require provider exceptions to surface unchanged and
without automatic retry.

It must not add:

- automatic retry
- fallback provider selection
- silent default responses
- try/except paths that convert provider failure into a passable workflow result

The interface also rejects non-`DirectAPIResponse` returns, model mismatches,
interface model / API-key / provider-adapter mutation during provider calls,
non-callable provider adapters, empty or non-UTF-8-encodable response text,
empty or non-UTF-8-encodable prompts, empty or non-UTF-8-encodable model names,
and non-UTF-8-encodable API keys.
Its `name()` method uses the same model identifier validation rather than
formatting a raw internal value.

## Next Implementation Gate

DirectAPI can be implemented only after the same handoff, route, reminder, and
serialization contracts are already stable in staged mode.
