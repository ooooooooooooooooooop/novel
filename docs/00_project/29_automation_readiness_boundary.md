# Automation Readiness Boundary

## Status

The project is not ready for closed-loop automation.

FileExchangeInterface remains the default v0 runtime. The staged CLI is the
current executable orchestration surface, and DirectAPI provider calling is not
implemented.

This note defines the boundary that UI, DirectAPI, and future automation must
respect before any provider call or closed-loop runner is allowed to move a
workflow forward.

## Required Stable Contracts

### 1. Handoff route contract

`HandoffPacket.next_route` is a structured `NextRoute` object, not a string
next_route shortcut.

Automation must treat these as gate inputs:

- `recommended_workflow`
- `route_reason`
- optional `review_route`
- `must_read_first`
- `do_not_skip`

String `next_route` values must fail. `handoff_header.source` and
`handoff_header.target` must both be supported workflow strings.
handoff source and target must be different workflows.
handoff transition must be supported: `RebuildUnit`, `ContinueUnit`, and
`RewriteUnit` handoffs route to `ReviewUnit`; `ReviewUnit` handoffs route only
to `ContinueUnit`, `RewriteUnit`, `Stop`, `RebuildUnit`, or `Replan`.
`handoff_header.target` must match `next_route.recommended_workflow`, and
Review route values must only map to the allowed workflow target:

- `pass` -> `ContinueUnit`
- `rewrite` -> `RewriteUnit`
- `block` -> `Stop`, `RebuildUnit`, or `Replan`

`handoff_header.reason` must be a non-empty string when present and must match `next_route.route_reason`.
standard handoff must include handoff_header.reason: RebuildUnit -> ReviewUnit
and ReviewUnit handoffs must carry the same route reason in both
`handoff_header.reason` and `next_route.route_reason`.

Outer handoff container fields must keep their JSON container shape:
`handoff_header`, `input_anchor`, `output_anchor`, and `confidence_and_gaps`
must be objects; `change_set` and `open_items` must be lists; `next_route`
must remain a structured `NextRoute` object. Malformed outer container fields
must become handoff gate violations instead of parser or attribute errors.
`confidence_and_gaps.gaps` must be a list of non-empty strings when present.
confidence_gap open items content must be a non-empty string.
confidence_gap open items must match confidence_and_gaps.gaps.
standard handoff anchor fields must keep executable reference shape:
`input_anchor.source_text`, `input_anchor.review_target_ref`, and
`output_anchor.state_ref` must be non-empty strings when present, and
`output_anchor.reconstructed_objects` must be a non-empty object when present.
workflow standard anchors are required before route execution:
RebuildUnit -> ReviewUnit handoffs must include `input_anchor.source_text` and
`output_anchor.reconstructed_objects`; ReviewUnit handoffs must include
`input_anchor.review_target_ref` and `output_anchor.state_ref`.
`next_route.must_read_first must include standard input anchors`: when
`input_anchor.source_text` or `input_anchor.review_target_ref` is present, the
same reference must appear in `next_route.must_read_first` before the packet can
enter a downstream workflow.
standard workflow handoffs must include next_route.do_not_skip: RebuildUnit ->
ReviewUnit and ReviewUnit handoffs must carry at least one non-skippable route
guard before the packet can be routed.
RebuildUnit handoff do_not_skip must include review reconstructed object layers.
ReviewUnit handoff do_not_skip must include ReviewIssue and ReviewReminder state.
Normal `HandoffPacket` assignment must reject these malformed outer container
shapes before a packet reaches orchestration.
Outer handoff object keys and `change_set` / `open_items` entry keys must be
strings, matching JSON object semantics. Python-only dict shapes with
non-string handoff keys must fail at the handoff gate.
Normal `HandoffPacket` construction and assignment must also reject
non-string handoff keys before a packet reaches orchestration.
`change_set` and `open_items` remain list-valued in dumped handoff JSON, but
the runtime `HandoffPacket` object must keep them immutable so in-place list
mutation cannot bypass assignment validation.
Every change_set entry must include non-empty action before the packet can be
routed, so actionless adapter metadata cannot be treated as workflow change
evidence. change_set entries must include non-empty action.
ReviewUnit handoffs must include review change_set evidence: a review
`change_set` entry must carry `route`, `issue_count`, and `reminder_count`.
ReviewUnit handoffs must include exactly one review change_set entry.
The review change_set route must match `next_route.review_route`, and review change_set issue_count and reminder_count must match open_items before a packet can be routed.
RebuildUnit handoffs must include create change_set evidence: a create
`change_set` entry must carry `objects`, and rebuild change_set objects must match output_anchor.reconstructed_objects before the packet can enter ReviewUnit.
RebuildUnit handoffs must include exactly one create change_set entry, and rebuild change_set objects entries must be unique.
Top-level handoff object fields and direct `change_set` / `open_items` entries
must also be shallow read-only mappings at runtime, while still dumping as
plain JSON objects.
`NextRoute.model_copy(update=...)` and `HandoffPacket.model_copy(update=...)`
must re-run model validation; adapter code must not use copy-update as a way to
bypass construction or assignment gates.
`HandoffPacket.model_copy(deep=True)` must also rebuild through the same
validated JSON-shaped payload so shallow read-only runtime mappings do not make
deep copy unusable.
`NextRoute` fields must also keep their runtime JSON shape after object
construction: `recommended_workflow` and `review_route` must remain allowed
route values, `route_reason` must remain a non-empty string, and
`must_read_first` / `do_not_skip` must remain lists of non-empty strings.
must_read_first and do_not_skip entries must be unique.
Normal `NextRoute` assignment must reject shape drift immediately; the handoff
verifier remains a second boundary for already-corrupted route objects.
`must_read_first` and `do_not_skip` remain list-valued in dumped handoff JSON,
but the runtime `NextRoute` object must keep them immutable so in-place list
mutation cannot bypass assignment validation.

### 2. Reminder escalation contract

Handoff and package `ReviewIssue` items are validated through the same runtime
model used by workflow outputs. The handoff-only `status` alias may be used only
when it matches `resolution_status`; unknown review issue fields must fail
instead of being accepted as adapter metadata. Only open `critical` or
`blocking` issues can block Continue or satisfy Rewrite evidence.
The orchestration gate must not keep a duplicated ReviewIssue or ReviewReminder
field matrix; the runtime model remains the contract owner.
Handoff `ReviewIssue` open items must be model-valid before any route target is
entered, including `Stop`, `RebuildUnit`, and `Replan` block routes.
Handoff `ReviewReminder` open items must also be model-valid at the handoff
boundary, so missing `window`, missing `escalation_issue_type`, illegal family
values, or illegal escalation targets cannot survive until a later gate.
`HandoffBoundaryUnit.build_review_route()` must validate `ReviewIssue` and
`ReviewReminder` inputs through the same runtime models before creating a
packet, so invalid review objects fail before `route_handoff.json` can be
written.
The handoff builder and orchestration gate must share
`src/boundary_control/review_object_contracts.py` for ReviewIssue and
ReviewReminder payload normalization, including the handoff-only `status`
alias.
Review object payloads must be JSON objects; non-object ReviewIssue or
ReviewReminder payloads must fail before model parsing or packet construction.
Review object payload keys must be strings, matching JSON object semantics;
Python-only dict shapes with non-string keys must fail at the shared contract
boundary.
Every handoff `open_items` entry must itself be a JSON object; non-object open
items must become `open item must be an object` orchestration gate violations
before route-specific entry checks run.
If a ReviewIssue or ReviewReminder payload includes handoff `type` metadata, it
must match the parser target; conflicting `type` values must fail instead of
being ignored.
When such malformed payloads reach `OrchestrationGateUnit.verify_entry()`, they
must be reported as gate violations rather than leaking parser exceptions.
When a `SerializationPackage` is supplied to the gate, `repair_control`
`ReviewIssue` and `ReviewReminder` items must also be model-valid before any
route target is entered, including block routes.
Package outer container fields must keep their JSON object shape:
`stable_memory`, `working_set`, `repair_control`, `confidence`, and `metadata`
must be objects. Malformed package container fields must become package gate
violations before route-specific package scans run.
Package `confidence` and `metadata` keys must be strings, matching JSON object
semantics, even though their values remain free-form metadata.
Normal `SerializationPackage` assignment must reject malformed package
container shapes before a package reaches orchestration, and
`SerializationPackage.model_copy(update=...)` must re-run model validation
instead of letting adapter code create invalid package snapshots through
copy-update.
Runtime `SerializationPackage` layer buckets and free-form metadata objects
must be shallow read-only while `model_dump()` continues to emit ordinary JSON
objects and arrays. `SerializationPackage.model_copy(deep=True)` must rebuild
from the same validated JSON-shaped payload so read-only runtime mappings do
not break deep-copy paths.
Serialized package layer buckets must map string type names to lists of object
payloads. Non-string type keys, non-list buckets, or non-object bucket entries
must become package gate violations before `ContinueUnit` can treat package
truthiness as runnable state evidence.
Package layer separation is owned by `SerializationBoundaryUnit.check_separation()`.
Unknown serialized types and types placed in the wrong package layer must become
package gate violations before route-specific entry checks run.
Serialized `stable_memory` and `working_set` objects must deserialize through
`SerializationBoundaryUnit.deserialize_package()` before route-specific entry
checks run. `repair_control` review objects continue to use the shared
ReviewIssue / ReviewReminder runtime contracts instead of the stable-state deserialization gate.

`ReviewReminder` is a structured near-term warning object. It is not prose
metadata.

Every runtime reminder must carry:

- a valid first-pass matrix `family`
- `window`
- `escalation_issue_type`
- `early_escalation_condition`
- `closure_condition`

The accepted family and escalation issue types are owned by the runtime schema.
Missing `window`, missing `escalation_issue_type`, illegal family values, or
illegal escalation targets must fail instead of being inferred.
Handoff `ReviewReminder` open items are validated through the same runtime model,
so unknown reminder fields must fail instead of being accepted as adapter
metadata.

### 3. Staged response contract

Staged response automation may only materialize one verified raw response into
one verified pending prompt slot.
FileExchangeAction action payload generation validates before returning, so the
printed `[AGENT_ACTION]` metadata cannot be emitted from a corrupted in-memory
action object.
Its `prompt_bytes` field must remain a canonical decimal positive prompt_bytes
value, so zero-byte prompt evidence cannot be treated as an automation-ready
action.

The allowed automation path is:

1. discover or select a pending prompt slot
2. bind to the exact prompt hash and byte snapshot
3. obtain raw response text
4. write through `ResponseFileBoundaryUnit`
5. return audit metadata

Response slot paths must be absolute. The response slot paths must be absolute
rule fails before provider calls or response writes, preventing a relative
staged path from creating a response file before audit result validation fails.

`StagedResponseResult` is audit metadata, not response content. Its payload
must include prompt / response paths, slot metadata, hashes, positive byte
counts, positive response character count, plus the staged materialization
contract fields, but not response text.
`interface_name` must not contain whitespace. The interface_name must not contain whitespace rule prevents future UI/provider adapters from grouping padded or space-separated interface labels as distinct evidence.
Staged response result paths must be absolute. The result paths must be absolute rule prevents future UI/provider adapters from resolving staged evidence relative to their own working directories.
Payload parsing must reject old result payloads missing that materialization
contract, and must reject any result payload that claims a provider call or
closed-loop workflow advance occurred.
Staged response result payload generation validates before returning, so a
corrupted in-memory `StagedResponseResult` cannot emit adapter audit metadata.
Staged response result payload keys must be strings, matching JSON object
semantics, and non-string keys must fail before result field-whitelist checks.
Staged response result payloads must not include credential fields.
Staged response result payloads must not include execution claim fields.
Staged response result payloads must not include pending automation metadata fields.
Staged response result payloads must not include prompt or response content fields.
`StagedResponseRunner` must bind the interface name snapshot before provider
execution and recheck it before response materialization; provider-side
interface audit-name mutation must fail without writing a staged response file.
The shared contract constants, exact field-order declarations, metadata builders,
metadata fragment extractors, in-payload metadata validators, pending metadata exact-field validation,
and materialization metadata exact-field validation for pending readiness and
staged response materialization live in
`src/boundary_control/automation_contracts.py`; CLI JSON, boundary result
payloads, and future UI/provider adapters must consume that module instead of
duplicating contract strings, boolean flags, or payload fragments.
Pending automation metadata and response materialization metadata payload keys
must also be strings before fragment extraction or exact-field validation.
Pending automation contract, action, and readiness-reason labels must be
non-empty strings before exact readiness matching runs.
`automation_blockers` must be a list of non-empty strings before exact readiness
matching runs.
Staged materialization audit flags `provider_call_performed` and
`closed_loop_advanced` must be exact JSON `false`; numeric stand-ins such as `0`
are not accepted as no-provider/no-closed-loop evidence.
Pending readiness boolean fields must be exact JSON booleans; numeric stand-ins
such as `0` or `1` are not accepted as automation evidence.
Pending automation metadata source payloads and response materialization metadata source payloads must not include credential fields such as `api_key`, `credential`, `credentials`, `secret`, or `token`.
Pending automation metadata payloads and response materialization metadata payloads must reject credential fields before unknown-field handling.
Pending automation metadata source payloads, response materialization metadata source payloads, pending automation metadata payloads, and response materialization metadata payloads must not include execution claim fields such as `provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or `closed_loop_result`.
Pending automation metadata source payloads must not include response materialization metadata fields, and response materialization metadata source payloads must not include pending automation metadata fields; metadata source payloads must not include cross-contract metadata fields.
CLI JSON must self-validate those pending and materialization fragments before
emit, so contract drift fails inside the runtime path instead of only in adapter
tests. The CLI pending JSON payload also has an outer exact-field contract:
CLI mode whitelist is enforced before emit or adapter consumption:
pending/respond/gate payloads only accept `audit`, `extend`, or `compose`,
while list rows may use `unknown` only for initialized rows without route or
pending evidence.
payload keys must be strings, pending slot entries must keep the declared slot
fields, pending slot entries must not include credential fields, pending slot
entries must not include execution claim fields, pending slot entries must not
include prompt or response content fields, pending slot entries must not include
cross-contract metadata fields, staged prompt/response/slot identity must be internally consistent, and
workspace novel names must remain single workspace segments, output_dir must be absolute, output_dir must be output/<mode>, pending slot paths must be under output_dir, and staged prompt/response paths must be absolute.
pending slot entries must not include execution claim fields.
pending slot entries must not include prompt or response content fields.
pending slot entries must not include cross-contract metadata fields.
pending discovery output_dir must be absolute, pending slot paths must be absolute, and pending response paths must not already exist before boundary-level pending-slot metadata can be exposed.
pending slot prompt hashes and caller-provided expected prompt hashes must be
valid content hashes. positive pending prompt bytes are required. pending slot prompt hashes and byte counts must match current prompt files. pending slot prompt mtime must match current prompt files. pending/list JSON prompt evidence must match current prompt files, pending response paths must not already exist, pending slot prompt mtime must be a finite non-negative number, and freshness timestamps must be finite non-negative numbers or null.
expected prompt hash binding must match the caller-provided `expected_prompt_hash`
to the current staged `prompt_hash`.
The effective freshness cutoff must match the maximum of caller `newer_than` and
`route_artifact_mtime` before emit.
route_artifact_mtime must match current route artifacts before emit.
prompt_mtime must be newer than effective freshness cutoff before emit.
The selection method contract only accepts `all_pending` or `slot_id`; `slot_id`
selection must bind the top-level `slot_id` to the selected pending entry, and
`all_pending` must not claim a top-level selected slot.
pending preflight requires slot_id selection before `expected_prompt_hash` can
appear.
`pending_count` must match the number of pending entries before emit.
all_pending entries must match current pending discovery.
The CLI list JSON row payload has an outer exact-field contract before emit:
row keys must be strings, exact list row fields must be enforced,
finite non-negative latest_mtime is required, pending metadata must match
`pending_count`, staged prompt/response/slot identity must be internally consistent
for pending rows, list row status/pending consistency is enforced,
list route/status/workflow consistency is enforced,
list route artifact consistency is enforced,
list gate artifact consistency is enforced,
list gate metadata completeness is enforced,
final result file must match mode,
list JSON final result route content must match current result file,
route handoff file must be route_handoff.json,
staged prompt/response paths must be absolute, and
list artifact paths must be absolute. list JSON artifact existence must match current files. list JSON route handoff content must match current handoff file. list JSON gate verdict fields must match current gate verdict. artifact paths must be under output/<mode>. artifact paths must share output directory. artifact file fields must match path names.
list JSON detail must match status and route evidence.
pending response paths must not already exist.
latest_date must match latest_mtime.
latest_mtime must match current workspace files.
list row pending prompt mtime must be a finite non-negative number.
pending_prompt_mtime must not exceed latest_mtime.
pending_prompt_mtime must be newer than current route artifacts.
list row pending prompt bytes must be positive.
list waiting rows must match current pending discovery.
Gate blocking counts must match gate blocking prompt files. blocking prompt files must be staged prompt filenames. gate package file must match mode. gate JSON artifact existence must match current files. gate JSON route handoff content must match current handoff file. gate JSON verdict fields must match current gate verdict. list JSON gate verdict fields must match current gate verdict. ContinueUnit pass requires package_present. The top-level list
output remains an array for compatibility.
`automation_contracts.py` is metadata-only and must not import filesystem,
provider, route, handoff, or runner dependencies.

`novel respond --json` is the CLI materialization audit surface. A successful
payload must identify the staged response materialization contract, the
performed action, and the fact that no provider call or closed-loop workflow
advance happened.
The CLI respond JSON payload has an outer exact-field contract before emit:
payload keys must be strings, content hashes and caller-provided expected prompt
hashes must be valid content hashes, byte and character counts remain explicit
metadata, prompt byte count must be a positive integer, response source
bytes, staged response bytes, and response characters must be positive response materialization counts, and staged
prompt/response/slot identity must be internally consistent.
response_bytes must be at least response_chars.
response_source_bytes must not be less than response_bytes.
staged prompt/response paths must be absolute.
respond staged paths must be under output/<mode>.
response_source must be an absolute path, matching the resolved source identity
used for source-byte evidence.
response_source must not match staged prompt_path or response_path.
respond JSON file evidence must match current files before machine-readable
respond payloads can be trusted.
respond JSON source text must match staged response file.
respond JSON response text must be non-empty.
respond JSON response_source mtime must not be older than prompt_path.
respond JSON response_path mtime must not be older than prompt_path.
expected prompt hash binding must match the caller-provided `expected_prompt_hash`
to the current staged `prompt_hash`.
The effective freshness cutoff must match the route-artifact input before emit.
route_artifact_mtime must match current route artifacts before emit.
prompt_mtime must be newer than effective freshness cutoff before emit.
The selection method contract only accepts `single_pending`, `slot_id`, or
`prompt_file`.
`prompt_hash_verified` must match whether `expected_prompt_hash` is present.

The CLI gate JSON payload has an outer exact-field contract before emit:
payload keys must be strings, exact gate fields must be enforced, gate review route matrix must match the Handoff route contract,
gate verdict consistency is enforced,
gate artifact paths must be absolute,
blocking prompt files must be staged prompt filenames,
gate package file must match mode,
ContinueUnit pass requires package_present,
and gate blocking counts must match gate blocking prompt files.

### 4. DirectAPI contract

DirectAPI may later replace only the human action of writing a staged response
file.

DirectAPI must not replace workflow ordering, route selection, handoff parsing,
Review reminder escalation, or final artifact writing.

`DirectAPIRequest` and `DirectAPIResponse` have strict versioned payload
schemas for serialization and audit. `DirectAPIInterface.call()` remains an
object-level call path and must not use request / response payload dictionaries
as control flow.
FileExchange action blocks must not include credential fields or execution
claim fields; the staged action block remains a prompt/response file-exchange
contract and not a provider, retry, fallback, or credential carrier.
FileExchange action blocks must not include automation or materialization
metadata fields; those fields belong to pending/readiness and staged response
materialization payloads, not the action block.
DirectAPI request / response to_payload() validates before returning, so
provider/UI audit payload generation and audit payload parsing share the same
schema gate.
Provider request objects are checked against their prompt/model snapshots after
provider return, so corrupted in-memory `DirectAPIRequest` instances cannot
rewrite call evidence.
Provider response objects are revalidated before returning text from
`DirectAPIInterface.call()`, so corrupted in-memory `DirectAPIResponse`
instances cannot bypass response text or model checks.
DirectAPI interface private snapshots (`model`, `api_key`, and `provider_call`)
must be revalidated again after provider return, so provider-side private-state
corruption fails as invalid configuration before any response text is trusted.
Future UI/provider adapters that consume DirectAPI audit payloads must use the
shared `parse_direct_api_payload()` entrypoint instead of branching on raw
payload fields themselves.
parse_direct_api_payload() enforces the DirectAPI credential-field ban before type dispatch, then the request / response payload parsers enforce it again.
DirectAPI request / response payload parsing must require both identity fields:
`schema_version` and `type`.
DirectAPI request / response payload keys must be strings, matching JSON object
semantics, and non-string keys must fail before the shared parser dispatches to
request or response parsing.
DirectAPI audit payloads must not include credential fields such as `api_key`,
`credential`, `credentials`, `secret`, or `token`; these fields fail as
credential-field violations before generic unknown-field handling.
DirectAPI audit payloads must not include execution claim fields such as
`provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
`closed_loop_result`; these fields fail as execution-claim violations before
generic unknown-field handling.
DirectAPI audit payloads must not include automation or materialization metadata
fields such as `automation_ready`, `automation_blockers`,
`provider_calls_implemented`, `materialized_action`,
`provider_call_performed`, or `closed_loop_advanced`; DirectAPI audit payload
cross-contract metadata violations before generic unknown-field handling.

DirectAPI provider calling is not implemented. There is no retry, no fallback
provider, no silent default response, and no exception translation into a
passable workflow result.

### 5. Runtime JSON contract

Machine-readable CLI output is for orchestration evidence:

- `novel list --json`
- `novel pending --json`
- `novel respond --json`
- `novel gate --json`

The CLI gate JSON payload has an outer exact-field contract before emit:
payload keys must be strings, exact gate fields must be enforced, violation
lists must contain strings, blocking pending prompt file lists must contain
strings, and `blocking_pending_count` must match the number of blocking prompt
files. blocking prompt files must be staged prompt filenames. gate package file must match mode. gate JSON route handoff content must match current handoff file. gate JSON verdict fields must match current gate verdict. ContinueUnit pass requires package_present. These blocking prompt files are evidence that the route handoff is stale.

`novel list --json` rows expose the same automation-readiness metadata as
`novel pending --json`, but only as batch discovery evidence. A caller must use
the specific pending gate before preparing or materializing a response.
Rows with multiple pending slots must remain not-ready and expose blocker codes;
batch discovery must not guess one slot by filename or timestamp.
Each row must pass the CLI list JSON row payload contract before emit, including
exact list row fields, string row keys, finite non-negative latest_mtime,
latest_mtime must match current workspace files,
pending metadata consistency, list JSON gate verdict fields must match current gate verdict, and gate blocking counts that match gate blocking
prompt files. The top-level list output remains an array for compatibility.

`novel pending --json` is the current model-call preflight surface. It reports
`automation_contract_version`, `automation_contract`, `automation_ready`,
`automation_ready_reason`, `automation_blockers`, `allowed_automation_action`,
`provider_calls_implemented`, and `closed_loop_allowed`.
`automation_ready=true` only means there is exactly one verified pending staged
response slot, `automation_blockers` is an empty list, and the allowed action
`materialize_staged_response_only`; it does not authorize DirectAPI provider
calls or closed-loop workflow
advancement.
`novel pending --require-automation-ready --json` is the read-only gate form of
that preflight. Not-ready states must return `ok=false`, keep the same pending
evidence and readiness fields, and expose blocker codes instead of guessing a
slot or calling a provider.

Object-shaped success payloads must include `schema_version=1`, `ok=true`, and
`command`. The CLI JSON error payload contract governs runtime and argument
failures. The error payload keys must be strings, `ok` must be `false`,
`schema_version` must be `1`, and exact error fields are enforced before emit.
Argument failures expose only `ok`, `schema_version`, `error_stage`,
`error_type`, and `error`; `error_type` must be an exception class identifier.
Runtime failures additionally expose a parsed `command`, which must be a
non-empty supported CLI command. Commands with a novel argument require runtime
`novel` as a non-empty string; `list` runtime errors require `novel=null`.
Base error payloads without runtime context are argument-stage only.
CLI JSON error payloads must be built through _json_error_payload(), and direct
`{"ok": false}` error payload literals outside that helper are rejected by the
runtime contract tests.
CLI JSON error payload call sites must be guarded by JSON mode:
`NovelArgumentParser.error` requires `self.emit_json_errors`, and runtime
errors require `getattr(args, "json", False)`.
runtime CLI JSON error payload call sites must include runtime context:
`command`, `novel`, and `include_runtime_context=True`; only argument parser
errors may use the base argument payload.
Only NovelArgumentParser.error may emit the base argument JSON error payload;
all other CLI JSON error payload call sites are runtime-context payloads.
CLI JSON error payload call sites must declare literal error_stage by context:
argument parser errors use `error_stage="argument"`, and runtime errors use
`error_stage="runtime"`.
CLI JSON error payload call sites must declare error_type by context:
`NovelArgumentParser.error` uses `ArgumentError`, and runtime errors derive
`error_type` from the caught exception class name.
CLI JSON error payload call sites must declare error message source by context:
`NovelArgumentParser.error` uses the parser `message`, and runtime errors use
`str(exc)` from the caught exception.
CLI JSON error payloads must not include credential fields such as `api_key`,
`credential`, `credentials`, `secret`, or `token`; error payloads must not
include credential fields before generic unknown-field handling.
CLI JSON error payloads must not include execution claim fields such as
`provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
`closed_loop_result`; error payloads must not include execution claim fields
before generic unknown-field handling.
CLI JSON error payloads must not include cross-contract metadata fields such as
`automation_ready`, `automation_blockers`, `provider_calls_implemented`,
`materialized_action`, `provider_call_performed`, or `closed_loop_advanced`;
error payloads must not include cross-contract metadata fields before generic
unknown-field handling.
CLI JSON error payloads must not include prompt or response content fields such
as `prompt`, `response_text`, `text`, or `model`; error payloads must not
include prompt or response content fields before generic unknown-field handling.

The JSON layer can expose evidence and failure stages. It must not repair stale
routes, guess pending slots, ignore handoff errors, or bypass staged prompt /
response files.
exact-field CLI JSON payloads must not include credential fields such as
`api_key`, `credential`, `credentials`, `secret`, or `token`.
exact-field CLI JSON payloads must not include execution claim fields such as
`provider_call_result`, `provider_response`, `retry`, `fallback_provider`, or
`closed_loop_result`.
exact-field CLI JSON payloads must not include prompt or response content fields
such as `prompt`, `response_text`, `text`, or `model`.
exact-field CLI JSON payloads must not include cross-contract metadata fields
from another runtime contract; pending/list payloads reject response
materialization metadata, respond payloads reject pending automation metadata,
and gate payloads reject both metadata families.
exact-field validator call sites must declare cross-contract metadata policy
when they use the shared exact-field gate, so new CLI JSON payload families do
not silently inherit a generic unknown-field-only posture.
object-shaped CLI JSON payload literals with ok must declare schema_version and command
before they can be consumed by UI/provider automation.
ok=true CLI JSON payload literals must not declare error fields; success and
status evidence must stay separate from error payload evidence.
ok=false CLI JSON payload literals outside _json_error_payload() must declare error fields;
failure evidence must include stage, type, and message.
CLI stdout JSON dumps must emit only payload or rows contract variables.
CLI JSON object payload emits must validate payload before print; error payloads
do this through `_json_error_payload()`, while success/status payloads use their
explicit `_validate_*_json_payload()` gate.
CLI JSON object payload emits must validate after last payload assignment before print.
CLI JSON object payload emits must validate after last payload mutation before print.
CLI list JSON rows emits must validate rows before print.
CLI list JSON rows emits must validate after last rows mutation before print.
CLI list JSON rows emits must validate after last rows in-place mutation before print.
CLI empty list JSON emits must validate empty list before print.

## Still Not Allowed

These remain out of bounds:

- closed-loop automation that advances multiple workflow stages without a
  verified handoff gate between stages
- DirectAPI provider calls
- skipping staged prompt / response files
- string `next_route`
- route mutation by UI, provider adapters, or runner code
- automatic retry
- fallback provider selection
- swallowing provider, schema, route, or file-evidence exceptions

## Readiness Rule

Future automation is allowed to call a model only after it can prove it is using
the same staged prompt, response, handoff route, reminder escalation, and JSON
error contracts as the current CLI runtime.
