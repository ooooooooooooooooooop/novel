#!/usr/bin/env python3
"""Unified CLI wrapper for staged novel workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.approval_gate import (
    APPROVAL_DECISION_FILE,
    APPROVAL_GATE_EXTRA_FIELDS,
    blocking_review_issue_ids,
    critical_review_issue_ids,
    load_approval_decision,
    resolve_approval_gate_verdict,
)
from src.boundary_control.automation_contracts import (
    AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS,
    AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS,
    PENDING_AUTOMATION_METADATA_FIELDS,
    RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    pending_automation_metadata,
    response_materialization_metadata,
    validate_pending_automation_metadata_in_payload,
    validate_response_materialization_metadata_in_payload,
)
from src.boundary_control.handoff import (
    HandoffBoundaryUnit,
    HandoffPacket,
    VALID_REVIEW_ROUTES,
    VALID_WORKFLOW_ROUTES,
)
from src.boundary_control.orchestration import OrchestrationGateUnit
from src.boundary_control.runtime_args import validate_long_runtime_args
from src.boundary_control.runtime_identity import (
    content_evidence_from_bytes,
    expected_staged_response_path,
    file_content_hash,
    file_content_evidence,
    model_content_hash,
    staged_slot_id,
    validate_content_hash,
    validate_run_hash,
)
from src.boundary_control.response_file import (
    PendingResponseSlot,
    ResponseFileBoundaryUnit,
    STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS,
)
from src.object_state import WorkSpec
from src.boundary_control.serialization import SerializationBoundaryUnit

DEFAULT_NOVELS_ROOT = PROJECT_ROOT / "novels"
MODE_FILE = "mode.txt"
CONFIG_FILE = "run_config.json"
JSON_SCHEMA_VERSION = 1
VALID_MODES = {"audit", "extend", "compose", "style", "compliance", "rubric", "time"}
JSON_ERROR_COMMANDS = {"audit", "extend", "compose", "style", "compliance", "rubric", "time", "list", "gate", "pending", "respond"}
JSON_ERROR_COMMANDS_WITH_NOVEL = JSON_ERROR_COMMANDS - {"list"}
ROUTE_HANDOFF_FILE = "route_handoff.json"
PENDING_SELECTION_METHODS = {"all_pending", "slot_id"}
RESPOND_SELECTION_METHODS = {"single_pending", "slot_id", "prompt_file"}
BLOCK_REVIEW_WORKFLOWS = {"Stop", "RebuildUnit", "Replan"}
LIST_ROW_STATUSES = {"waiting", "completed", "blocked", "rewrite", "initialized"}
LIST_ROW_MODES = {*VALID_MODES, "unknown"}
LIST_ROW_STATUS_BY_ROUTE = {
    "pass": "completed",
    "rewrite": "rewrite",
    "block": "blocked",
}
VALID_CONFIG_FIELDS = {
    "mode",
    "format",
    "outline_only",
    "chapter_wise",
    "chapter_range",
    "batch_size",
    "max_chapters",
    "workspec",
    "style",
    "name",
    "platform",
    "sensitive",
    "lexicon",
    "retrieval",
    "rebuild",
    "check",
}
BASE_JSON_ERROR_FIELDS = (
    "ok",
    "schema_version",
    "error_stage",
    "error_type",
    "error",
)
RUNTIME_JSON_ERROR_FIELDS = (
    "ok",
    "schema_version",
    "command",
    "novel",
    "error_stage",
    "error_type",
    "error",
)
PENDING_SLOT_FIELDS = (
    "prompt_file",
    "response_file",
    "prompt_path",
    "response_path",
    "prompt_mtime",
    "prompt_hash",
    "prompt_bytes",
    "slot_id",
)
PENDING_JSON_FIELDS = (
    "ok",
    "schema_version",
    "command",
    "novel",
    "mode",
    "output_dir",
    "slot_id",
    "selection_method",
    "newer_than",
    "effective_newer_than",
    "route_artifact_mtime",
    "expected_prompt_hash",
    "prompt_hash_verified",
    "pending_count",
    *PENDING_AUTOMATION_METADATA_FIELDS,
    "pending",
)
PENDING_JSON_ERROR_FIELDS = (
    *PENDING_JSON_FIELDS,
    "error_stage",
    "error_type",
    "error",
)
RESPOND_JSON_FIELDS = (
    "ok",
    "schema_version",
    "command",
    "novel",
    "mode",
    "prompt_file",
    "response_file",
    "prompt_path",
    "response_path",
    "response_source",
    *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    "selection_method",
    "route_artifact_mtime",
    "effective_newer_than",
    "expected_prompt_hash",
    "prompt_hash_verified",
    "prompt_hash",
    "prompt_bytes",
    "slot_id",
    "response_source_hash",
    "response_source_bytes",
    "response_hash",
    "response_bytes",
    "response_chars",
)
GATE_JSON_FIELDS = (
    "command",
    "novel",
    "mode",
    "ok",
    "schema_version",
    "review_route",
    "next_workflow",
    "violations",
    "handoff_path",
    "package_path",
    "package_present",
    "blocking_pending_count",
    "blocking_pending_prompt_files",
)
# Approval gate JSON = the 13 standard fields as an identical prefix, then the
# approval fields. This new shape has no existing locks, so the default gate
# contract (GATE_JSON_FIELDS) and its sha256-pinned canary fixtures stay
# byte-identical.
APPROVAL_GATE_JSON_FIELDS = (*GATE_JSON_FIELDS, *APPROVAL_GATE_EXTRA_FIELDS)
LIST_JSON_ROW_FIELDS = (
    "schema_version",
    "command",
    "name",
    "mode",
    "status",
    "detail",
    "latest_date",
    "latest_mtime",
    "route",
    "next_workflow",
    "gate_ok",
    "gate_violations",
    "gate_package_file",
    "gate_package_path",
    "gate_package_present",
    "gate_blocking_pending_count",
    "gate_blocking_pending_prompt_files",
    "pending_count",
    "pending_prompt_file",
    "pending_response_file",
    "pending_prompt_path",
    "pending_response_path",
    "pending_prompt_hash",
    "pending_prompt_bytes",
    "pending_prompt_mtime",
    "pending_slot_id",
    *PENDING_AUTOMATION_METADATA_FIELDS,
    "final_result_file",
    "final_result_path",
    "route_handoff_file",
    "route_handoff_path",
    "time_status",
)


def _validate_json_error_payload(payload: dict[object, object]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("CLI JSON error payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("CLI JSON error payload keys must be strings")
    credential_fields = [
        field for field in AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS if field in payload
    ]
    if credential_fields:
        raise ValueError(
            "CLI JSON error payload must not include credential field(s): "
            f"{', '.join(credential_fields)}"
        )
    execution_claim_fields = [
        field for field in AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS if field in payload
    ]
    if execution_claim_fields:
        raise ValueError(
            "CLI JSON error payload must not include execution claim field(s): "
            f"{', '.join(execution_claim_fields)}"
        )
    cross_contract_metadata_fields = [
        field
        for field in (
            *PENDING_AUTOMATION_METADATA_FIELDS,
            *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
        )
        if field in payload
    ]
    if cross_contract_metadata_fields:
        raise ValueError(
            "CLI JSON error payload must not include cross-contract metadata "
            f"field(s): {', '.join(cross_contract_metadata_fields)}"
        )
    content_fields = [
        field
        for field in STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS
        if field in payload
    ]
    if content_fields:
        raise ValueError(
            "CLI JSON error payload must not include prompt or response content "
            f"field(s): {', '.join(content_fields)}"
        )
    fields = (
        RUNTIME_JSON_ERROR_FIELDS
        if "command" in payload or "novel" in payload
        else BASE_JSON_ERROR_FIELDS
    )
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"missing CLI JSON error field(s): {', '.join(missing)}")
    unknown = [field for field in payload if field not in fields]
    if unknown:
        raise ValueError(f"unknown CLI JSON error field(s): {', '.join(unknown)}")
    if payload["ok"] is not False:
        raise ValueError("CLI JSON error ok must be false")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI JSON error schema_version: {schema_version}"
        )
    if payload["error_stage"] not in {"argument", "runtime"}:
        raise ValueError(f"unsupported CLI JSON error_stage: {payload['error_stage']}")
    has_runtime_context = fields == RUNTIME_JSON_ERROR_FIELDS
    if has_runtime_context and payload["error_stage"] != "runtime":
        raise ValueError("CLI JSON error runtime context requires runtime error_stage")
    if not has_runtime_context and payload["error_stage"] != "argument":
        raise ValueError("CLI JSON base error payload requires argument error_stage")
    _validate_error_type(payload["error_type"], label="CLI JSON error")
    value = payload["error"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CLI JSON error error must be a non-empty string")
    command = payload["command"] if "command" in payload else None
    if has_runtime_context and (
        not isinstance(command, str) or not command.strip()
    ):
        raise ValueError("CLI JSON error command must be a non-empty string")
    for field in ("command", "novel"):
        if field not in payload:
            continue
        value = payload[field]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(
                f"CLI JSON error {field} must be a non-empty string or null"
            )
    if command is not None and command not in JSON_ERROR_COMMANDS:
        raise ValueError(f"unsupported CLI JSON error command: {command}")
    novel = payload["novel"] if "novel" in payload else None
    if command in JSON_ERROR_COMMANDS_WITH_NOVEL and (
        not isinstance(novel, str) or not novel.strip()
    ):
        raise ValueError(
            f"CLI JSON error novel must be a non-empty string for {command}"
        )
    if command == "list" and novel is not None:
        raise ValueError("CLI JSON error novel must be null for list")


def _validate_error_type(value: object, *, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} error_type must be a non-empty string")
    if value != value.strip() or not value.isidentifier():
        raise ValueError(f"{label} error_type must be an exception class identifier")


def _json_error_payload(
    *,
    error_stage: str,
    error_type: str,
    error: str,
    command: str | None = None,
    novel: str | None = None,
    include_runtime_context: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "schema_version": JSON_SCHEMA_VERSION,
        "error_stage": error_stage,
        "error_type": error_type,
        "error": error,
    }
    if include_runtime_context:
        payload = {
            "ok": False,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": command,
            "novel": novel,
            "error_stage": error_stage,
            "error_type": error_type,
            "error": error,
        }
    _validate_json_error_payload(payload)
    return payload


def _validate_exact_fields(
    payload: dict[object, object],
    *,
    fields: tuple[str, ...],
    label: str,
    forbidden_cross_contract_metadata_fields: tuple[str, ...] = (),
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{label} payload keys must be strings")
    credential_fields = [
        field for field in AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS if field in payload
    ]
    if credential_fields:
        raise ValueError(
            f"{label} payload must not include credential field(s): "
            f"{', '.join(credential_fields)}"
        )
    execution_claim_fields = [
        field for field in AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS if field in payload
    ]
    if execution_claim_fields:
        raise ValueError(
            f"{label} payload must not include execution claim field(s): "
            f"{', '.join(execution_claim_fields)}"
        )
    content_fields = [
        field
        for field in STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS
        if field in payload
    ]
    if content_fields:
        raise ValueError(
            f"{label} payload must not include prompt or response content "
            f"field(s): {', '.join(content_fields)}"
        )
    cross_contract_metadata_fields = [
        field for field in forbidden_cross_contract_metadata_fields if field in payload
    ]
    if cross_contract_metadata_fields:
        raise ValueError(
            f"{label} payload must not include cross-contract metadata "
            f"field(s): {', '.join(cross_contract_metadata_fields)}"
        )
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"missing {label} field(s): {', '.join(missing)}")
    unknown = [field for field in payload if field not in fields]
    if unknown:
        raise ValueError(f"unknown {label} field(s): {', '.join(unknown)}")


def _validate_optional_string(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    value = payload[field]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{label} {field} must be a non-empty string or null")


def _validate_cli_mode(
    payload: dict[object, object],
    *,
    label: str,
    allow_unknown: bool = False,
) -> None:
    mode = payload["mode"]
    allowed_modes = LIST_ROW_MODES if allow_unknown else VALID_MODES
    if mode not in allowed_modes:
        raise ValueError(f"{label} mode must be a supported mode")


def _validate_finite_non_negative_number(
    value: object,
    *,
    label: str,
) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite non-negative number")


def _validate_optional_finite_non_negative_number(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    if payload[field] is None:
        return
    _validate_finite_non_negative_number(
        payload[field],
        label=f"{label} {field}",
    )


def _expected_effective_newer_than(
    *,
    newer_than: object,
    route_artifact_mtime: object,
) -> int | float | None:
    values = [
        value for value in (newer_than, route_artifact_mtime) if value is not None
    ]
    if not values:
        return None
    return max(values)


def _validate_effective_newer_than(
    payload: dict[object, object],
    *,
    newer_than_field: str | None,
    route_artifact_mtime_field: str,
    effective_newer_than_field: str,
    label: str,
) -> None:
    newer_than = None if newer_than_field is None else payload[newer_than_field]
    expected = _expected_effective_newer_than(
        newer_than=newer_than,
        route_artifact_mtime=payload[route_artifact_mtime_field],
    )
    if payload[effective_newer_than_field] != expected:
        raise ValueError(
            f"{label} {effective_newer_than_field} must match "
            "the effective freshness cutoff"
        )


def _validate_route_artifact_mtime_current(
    *,
    mode: str,
    output_dir: Path,
    route_artifact_mtime: object,
    label: str,
) -> None:
    current_route_artifact_mtime = _latest_route_artifact_mtime(mode, output_dir)
    if route_artifact_mtime != current_route_artifact_mtime:
        raise ValueError(f"{label} route_artifact_mtime must match current route artifacts")


def _validate_prompt_mtime_after_effective_cutoff(
    *,
    prompt_mtime: float,
    effective_newer_than: object,
    label: str,
) -> None:
    if effective_newer_than is None:
        return
    if prompt_mtime <= effective_newer_than:
        raise ValueError(
            f"{label} prompt_mtime must be newer than effective freshness cutoff"
        )


def _validate_staged_slot_identity(
    payload: dict[object, object],
    *,
    prompt_file_field: str,
    response_file_field: str,
    prompt_path_field: str,
    response_path_field: str,
    slot_id_field: str,
    label: str,
) -> None:
    prompt_path = Path(payload[prompt_path_field])
    response_path = Path(payload[response_path_field])
    if not prompt_path.is_absolute():
        raise ValueError(f"{label} {prompt_path_field} must be an absolute path")
    if not response_path.is_absolute():
        raise ValueError(f"{label} {response_path_field} must be an absolute path")
    expected_response_path = expected_staged_response_path(prompt_path)
    if payload[prompt_file_field] != prompt_path.name:
        raise ValueError(
            f"{label} {prompt_file_field} must match {prompt_path_field}"
        )
    if payload[response_file_field] != response_path.name:
        raise ValueError(
            f"{label} {response_file_field} must match {response_path_field}"
        )
    if response_path != expected_response_path:
        raise ValueError(
            f"{label} {response_path_field} must match {prompt_path_field}"
        )
    expected_slot_id = staged_slot_id(prompt_path)
    if payload[slot_id_field] != expected_slot_id:
        raise ValueError(f"{label} {slot_id_field} must match {prompt_path_field}")


def _validate_absolute_path_field(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> Path:
    path = Path(payload[field])
    if not path.is_absolute():
        raise ValueError(f"{label} {field} must be an absolute path")
    return path


def _validate_optional_artifact_path_identity(
    payload: dict[object, object],
    *,
    file_field: str,
    path_field: str,
    label: str,
) -> None:
    file_value = payload[file_field]
    path_value = payload[path_field]
    if file_value is None and path_value is None:
        return
    if not isinstance(file_value, str) or not file_value.strip():
        raise ValueError(f"{label} {file_field} must be a non-empty string")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} {path_field} must be a non-empty string")
    path = _validate_absolute_path_field(payload, path_field, label=label)
    if file_value != path.name:
        raise ValueError(f"{label} {file_field} must match {path_field}")


def _validate_artifact_path_exists(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    if not Path(payload[field]).is_file():
        raise ValueError(f"{label} {field} must exist")


def _validate_output_dir_for_mode(
    *,
    mode: str,
    output_dir: Path,
    label: str,
) -> None:
    if output_dir.name != mode or output_dir.parent.name != "output":
        raise ValueError(f"{label} output_dir must be output/{mode}")


def _validate_pending_slot_output_dir(
    *,
    entry: dict[object, object],
    output_dir: Path,
) -> None:
    prompt_parent = Path(entry["prompt_path"]).parent
    response_parent = Path(entry["response_path"]).parent
    if prompt_parent != output_dir or response_parent != output_dir:
        raise ValueError("CLI pending slot paths must be under output_dir")


def _validate_pending_slot_payload(entry: dict[object, object]) -> None:
    _validate_exact_fields(
        entry,
        fields=PENDING_SLOT_FIELDS,
        label="CLI pending slot",
        forbidden_cross_contract_metadata_fields=(
            *PENDING_AUTOMATION_METADATA_FIELDS,
            *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
        ),
    )
    for field in (
        "prompt_file",
        "response_file",
        "prompt_path",
        "response_path",
        "slot_id",
    ):
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"CLI pending slot {field} must be a non-empty string")
    validate_content_hash(entry["prompt_hash"], "CLI pending slot prompt_hash")
    _validate_finite_non_negative_number(
        entry["prompt_mtime"],
        label="CLI pending slot prompt_mtime",
    )
    prompt_bytes = entry["prompt_bytes"]
    if (
        not isinstance(prompt_bytes, int)
        or isinstance(prompt_bytes, bool)
        or prompt_bytes <= 0
    ):
        raise ValueError("CLI pending slot prompt_bytes must be a positive integer")
    _validate_staged_slot_identity(
        entry,
        prompt_file_field="prompt_file",
        response_file_field="response_file",
        prompt_path_field="prompt_path",
        response_path_field="response_path",
        slot_id_field="slot_id",
        label="CLI pending slot",
    )
    if Path(entry["response_path"]).exists():
        raise ValueError("CLI pending slot response_path must not exist")


def _validate_pending_prompt_file_evidence(
    *,
    prompt_path: Path,
    prompt_hash: object,
    prompt_bytes: object,
    prompt_mtime: object,
    label: str,
) -> None:
    prompt_data = prompt_path.read_bytes()
    prompt_text = prompt_data.decode("utf-8-sig")
    if not prompt_text.strip():
        raise ValueError(f"{label} prompt file must be non-empty")
    prompt_evidence = content_evidence_from_bytes(prompt_data)
    if prompt_evidence.content_hash != prompt_hash:
        raise ValueError(f"{label} prompt_hash must match current prompt file")
    if prompt_evidence.byte_count != prompt_bytes:
        raise ValueError(f"{label} prompt_bytes must match current prompt file")
    current_prompt_mtime = prompt_path.stat().st_mtime
    if current_prompt_mtime != prompt_mtime:
        raise ValueError(f"{label} prompt_mtime must match current prompt file")


def _pending_slot_identity_from_entry(entry: dict[object, object]) -> tuple[object, ...]:
    return (
        entry["slot_id"],
        entry["prompt_file"],
        entry["response_file"],
        entry["prompt_path"],
        entry["response_path"],
        entry["prompt_mtime"],
        entry["prompt_hash"],
        entry["prompt_bytes"],
    )


def _pending_slot_identity_from_slot(slot: PendingResponseSlot) -> tuple[object, ...]:
    return (
        slot.slot_id,
        slot.prompt_path.name,
        slot.response_path.name,
        str(slot.prompt_path),
        str(slot.response_path),
        slot.prompt_mtime,
        slot.prompt_hash,
        slot.prompt_bytes,
    )


def _validate_pending_json_current_discovery(
    *,
    payload: dict[object, object],
    pending: list[object],
    output_dir: Path,
) -> None:
    if payload["selection_method"] != "all_pending":
        return
    current_slots = ResponseFileBoundaryUnit().discover_pending_slots(
        output_dir,
        newer_than=payload["effective_newer_than"],
    )
    current_identities = [
        _pending_slot_identity_from_slot(slot) for slot in current_slots
    ]
    payload_identities = [
        _pending_slot_identity_from_entry(entry) for entry in pending
    ]
    if payload_identities != current_identities:
        raise ValueError(
            "CLI pending JSON all_pending entries must match current pending discovery"
        )


def _validate_current_file_hash_and_bytes(
    *,
    file_path: Path,
    expected_hash: object,
    expected_bytes: object,
    hash_label: str,
    bytes_label: str,
    label: str,
) -> bytes:
    file_data = file_path.read_bytes()
    evidence = content_evidence_from_bytes(file_data)
    if evidence.content_hash != expected_hash:
        raise ValueError(f"{label} {hash_label} must match current file")
    if evidence.byte_count != expected_bytes:
        raise ValueError(f"{label} {bytes_label} must match current file")
    return file_data


def _validate_pending_json_payload(payload: dict[object, object]) -> None:
    fields = (
        PENDING_JSON_ERROR_FIELDS
        if any(field in payload for field in ("error_stage", "error_type", "error"))
        else PENDING_JSON_FIELDS
    )
    _validate_exact_fields(
        payload,
        fields=fields,
        label="CLI pending JSON",
        forbidden_cross_contract_metadata_fields=RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    )
    is_error_payload = fields == PENDING_JSON_ERROR_FIELDS
    if payload["ok"] is not (not is_error_payload):
        raise ValueError("CLI pending JSON ok does not match payload kind")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI pending JSON schema_version: {schema_version}"
        )
    if payload["command"] != "pending":
        raise ValueError(f"unsupported CLI pending JSON command: {payload['command']}")
    for field in ("novel", "mode", "output_dir", "selection_method"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"CLI pending JSON {field} must be a non-empty string")
    _validate_novel_name(payload["novel"])
    _validate_cli_mode(payload, label="CLI pending JSON")
    _validate_absolute_path_field(
        payload,
        "output_dir",
        label="CLI pending JSON",
    )
    output_dir = Path(payload["output_dir"])
    _validate_output_dir_for_mode(
        mode=payload["mode"],
        output_dir=output_dir,
        label="CLI pending JSON",
    )
    for field in ("slot_id", "expected_prompt_hash"):
        _validate_optional_string(payload, field, label="CLI pending JSON")
    if payload["expected_prompt_hash"] is not None:
        validate_content_hash(
            payload["expected_prompt_hash"],
            "CLI pending JSON expected_prompt_hash",
        )
    for field in ("newer_than", "effective_newer_than", "route_artifact_mtime"):
        _validate_optional_finite_non_negative_number(
            payload,
            field,
            label="CLI pending JSON",
        )
    _validate_effective_newer_than(
        payload,
        newer_than_field="newer_than",
        route_artifact_mtime_field="route_artifact_mtime",
        effective_newer_than_field="effective_newer_than",
        label="CLI pending JSON",
    )
    _validate_route_artifact_mtime_current(
        mode=payload["mode"],
        output_dir=output_dir,
        route_artifact_mtime=payload["route_artifact_mtime"],
        label="CLI pending JSON",
    )
    if payload["prompt_hash_verified"] is not isinstance(
        payload["expected_prompt_hash"],
        str,
    ):
        raise ValueError(
            "CLI pending JSON prompt_hash_verified must match expected_prompt_hash"
        )
    pending = payload["pending"]
    if not isinstance(pending, list):
        raise ValueError("CLI pending JSON pending must be a list")
    pending_count = payload["pending_count"]
    if (
        not isinstance(pending_count, int)
        or isinstance(pending_count, bool)
        or pending_count < 0
    ):
        raise ValueError("CLI pending JSON pending_count must be a non-negative integer")
    if pending_count != len(pending):
        raise ValueError("CLI pending JSON pending_count must match pending entries")
    for entry in pending:
        _validate_pending_slot_payload(entry)
        _validate_pending_slot_output_dir(entry=entry, output_dir=output_dir)
        _validate_pending_prompt_file_evidence(
            prompt_path=Path(entry["prompt_path"]),
            prompt_hash=entry["prompt_hash"],
            prompt_bytes=entry["prompt_bytes"],
            prompt_mtime=entry["prompt_mtime"],
            label="CLI pending slot",
        )
        _validate_prompt_mtime_after_effective_cutoff(
            prompt_mtime=entry["prompt_mtime"],
            effective_newer_than=payload["effective_newer_than"],
            label="CLI pending slot",
        )
    selection_method = payload["selection_method"]
    if selection_method not in PENDING_SELECTION_METHODS:
        raise ValueError(
            f"unsupported CLI pending JSON selection_method: {selection_method}"
        )
    if selection_method == "all_pending":
        if payload["slot_id"] is not None:
            raise ValueError(
                "CLI pending JSON slot_id must be null for all_pending selection"
            )
    if selection_method == "slot_id":
        if pending_count != 1:
            raise ValueError(
                "CLI pending JSON slot_id selection requires one pending entry"
            )
        if payload["slot_id"] != pending[0]["slot_id"]:
            raise ValueError(
                "CLI pending JSON slot_id must match selected pending entry"
            )
    if payload["expected_prompt_hash"] is not None:
        if selection_method != "slot_id":
            raise ValueError(
                "CLI pending JSON expected_prompt_hash requires slot_id selection"
            )
        if pending_count != 1:
            raise ValueError(
                "CLI pending JSON expected_prompt_hash requires one pending entry"
            )
        if payload["expected_prompt_hash"] != pending[0]["prompt_hash"]:
            raise ValueError(
                "CLI pending JSON expected_prompt_hash must match prompt_hash"
            )
    _validate_pending_json_current_discovery(
        payload=payload,
        pending=pending,
        output_dir=output_dir,
    )
    validate_pending_automation_metadata_in_payload(
        payload,
        pending_count=pending_count,
    )
    if is_error_payload:
        if payload["error_stage"] != "runtime":
            raise ValueError("CLI pending JSON error_stage must be runtime")
        _validate_error_type(payload["error_type"], label="CLI pending JSON")
        value = payload["error"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("CLI pending JSON error must be a non-empty string")


def _validate_non_negative_integer(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    value = payload[field]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} {field} must be a non-negative integer")


def _validate_positive_integer(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    value = payload[field]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} {field} must be a positive integer")


def _validate_respond_json_payload(payload: dict[object, object]) -> None:
    _validate_exact_fields(
        payload,
        fields=RESPOND_JSON_FIELDS,
        label="CLI respond JSON",
        forbidden_cross_contract_metadata_fields=PENDING_AUTOMATION_METADATA_FIELDS,
    )
    if payload["ok"] is not True:
        raise ValueError("CLI respond JSON ok must be true")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI respond JSON schema_version: {schema_version}"
        )
    if payload["command"] != "respond":
        raise ValueError(f"unsupported CLI respond JSON command: {payload['command']}")
    for field in (
        "novel",
        "mode",
        "prompt_file",
        "response_file",
        "prompt_path",
        "response_path",
        "response_source",
        "selection_method",
        "slot_id",
    ):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"CLI respond JSON {field} must be a non-empty string")
    _validate_novel_name(payload["novel"])
    _validate_cli_mode(payload, label="CLI respond JSON")
    _validate_absolute_path_field(payload, "response_source", label="CLI respond JSON")
    if payload["selection_method"] not in RESPOND_SELECTION_METHODS:
        raise ValueError(
            "unsupported CLI respond JSON selection_method: "
            f"{payload['selection_method']}"
        )
    _validate_optional_finite_non_negative_number(
        payload,
        "route_artifact_mtime",
        label="CLI respond JSON",
    )
    _validate_optional_finite_non_negative_number(
        payload,
        "effective_newer_than",
        label="CLI respond JSON",
    )
    _validate_effective_newer_than(
        payload,
        newer_than_field=None,
        route_artifact_mtime_field="route_artifact_mtime",
        effective_newer_than_field="effective_newer_than",
        label="CLI respond JSON",
    )
    _validate_optional_string(
        payload,
        "expected_prompt_hash",
        label="CLI respond JSON",
    )
    if payload["expected_prompt_hash"] is not None:
        validate_content_hash(
            payload["expected_prompt_hash"],
            "CLI respond JSON expected_prompt_hash",
        )
    if payload["prompt_hash_verified"] is not isinstance(
        payload["expected_prompt_hash"],
        str,
    ):
        raise ValueError(
            "CLI respond JSON prompt_hash_verified must match expected_prompt_hash"
        )
    for field in ("prompt_hash", "response_source_hash", "response_hash"):
        validate_content_hash(payload[field], f"CLI respond JSON {field}")
    if (
        payload["expected_prompt_hash"] is not None
        and payload["expected_prompt_hash"] != payload["prompt_hash"]
    ):
        raise ValueError("CLI respond JSON expected_prompt_hash must match prompt_hash")
    _validate_positive_integer(payload, "prompt_bytes", label="CLI respond JSON")
    for field in ("response_source_bytes", "response_bytes", "response_chars"):
        _validate_positive_integer(payload, field, label="CLI respond JSON")
    if payload["response_bytes"] < payload["response_chars"]:
        raise ValueError(
            "CLI respond JSON response_bytes must be at least response_chars"
        )
    if payload["response_source_bytes"] < payload["response_bytes"]:
        raise ValueError(
            "CLI respond JSON response_source_bytes must not be less than "
            "response_bytes"
        )
    validate_response_materialization_metadata_in_payload(payload)
    _validate_staged_slot_identity(
        payload,
        prompt_file_field="prompt_file",
        response_file_field="response_file",
        prompt_path_field="prompt_path",
        response_path_field="response_path",
        slot_id_field="slot_id",
        label="CLI respond JSON",
    )
    _validate_current_file_hash_and_bytes(
        file_path=Path(payload["prompt_path"]),
        expected_hash=payload["prompt_hash"],
        expected_bytes=payload["prompt_bytes"],
        hash_label="prompt_hash",
        bytes_label="prompt_bytes",
        label="CLI respond JSON",
    )
    for field in ("prompt_path", "response_path"):
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload[field],
            field=field,
            label="CLI respond JSON",
        )
    _validate_route_artifact_mtime_current(
        mode=payload["mode"],
        output_dir=Path(payload["prompt_path"]).parent,
        route_artifact_mtime=payload["route_artifact_mtime"],
        label="CLI respond JSON",
    )
    _validate_prompt_mtime_after_effective_cutoff(
        prompt_mtime=Path(payload["prompt_path"]).stat().st_mtime,
        effective_newer_than=payload["effective_newer_than"],
        label="CLI respond JSON",
    )
    response_source_path = Path(payload["response_source"]).resolve()
    for field in ("prompt_path", "response_path"):
        if response_source_path == Path(payload[field]).resolve():
            raise ValueError(
                f"CLI respond JSON response_source must not match staged {field}"
            )
    response_source_data = _validate_current_file_hash_and_bytes(
        file_path=response_source_path,
        expected_hash=payload["response_source_hash"],
        expected_bytes=payload["response_source_bytes"],
        hash_label="response_source_hash",
        bytes_label="response_source_bytes",
        label="CLI respond JSON",
    )
    if response_source_path.stat().st_mtime < Path(
        payload["prompt_path"]
    ).stat().st_mtime:
        raise ValueError(
            "CLI respond JSON response_source mtime must not be older than prompt_path"
        )
    response_data = _validate_current_file_hash_and_bytes(
        file_path=Path(payload["response_path"]),
        expected_hash=payload["response_hash"],
        expected_bytes=payload["response_bytes"],
        hash_label="response_hash",
        bytes_label="response_bytes",
        label="CLI respond JSON",
    )
    response_text = response_data.decode("utf-8")
    if len(response_text) != payload["response_chars"]:
        raise ValueError(
            "CLI respond JSON response_chars must match current response file"
        )
    if not response_text.strip():
        raise ValueError("CLI respond JSON response text must be non-empty")
    if Path(payload["response_path"]).stat().st_mtime < Path(
        payload["prompt_path"]
    ).stat().st_mtime:
        raise ValueError(
            "CLI respond JSON response_path mtime must not be older than prompt_path"
        )
    response_source_text = response_source_data.decode("utf-8-sig")
    if response_source_text != response_text:
        raise ValueError(
            "CLI respond JSON response_source text must match staged response file"
        )


def _validate_string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} entries must be non-empty strings")
    return value


def _validate_prompt_filename_list(value: object, *, label: str) -> list[str]:
    items = _validate_string_list(value, label=label)
    for item in items:
        _prompt_filename(item)
    return items


def _validate_gate_verdict_consistency(
    *,
    ok: bool,
    violations: list[str],
    blocking_count: int,
    label: str,
) -> None:
    if ok and violations:
        raise ValueError(f"{label} passed verdict must not include violations")
    if ok and blocking_count != 0:
        raise ValueError(f"{label} passed verdict must not include blocking pending")
    if not ok and not violations:
        raise ValueError(f"{label} failed verdict must include violations")


def _validate_continue_package_presence(
    *,
    ok: bool,
    next_workflow: object,
    package_present: object,
    label: str,
) -> None:
    if ok and next_workflow == "ContinueUnit" and package_present is not True:
        raise ValueError(f"{label} ContinueUnit pass requires package_present")


def _json_route_handoff_values(path: Path) -> tuple[str, str]:
    packet = _load_route_handoff_packet(path)
    return (
        packet.next_route.review_route or "-",
        packet.next_route.recommended_workflow,
    )


def _validate_gate_json_current_verdict(
    payload: dict[object, object],
    *,
    handoff_path: Path,
) -> None:
    verdict = _route_gate_verdict(
        mode=payload["mode"],
        output_dir=handoff_path.parent,
        handoff_path=handoff_path,
    )
    comparisons = (
        ("ok", "ok"),
        ("review_route", "review_route"),
        ("next_workflow", "next_workflow"),
        ("violations", "violations"),
        ("package_present", "package_present"),
        ("blocking_pending_count", "blocking_pending_count"),
        ("blocking_pending_prompt_files", "blocking_pending_prompt_files"),
    )
    for payload_field, verdict_field in comparisons:
        if payload[payload_field] != verdict[verdict_field]:
            raise ValueError(
                f"CLI gate JSON {payload_field} must match current gate verdict"
            )


def _validate_list_json_current_gate_verdict(payload: dict[object, object]) -> None:
    if payload["gate_ok"] is None:
        return
    handoff_path = Path(payload["route_handoff_path"])
    verdict = _route_gate_verdict(
        mode=payload["mode"],
        output_dir=handoff_path.parent,
        handoff_path=handoff_path,
    )
    comparisons: tuple[tuple[str, object], ...] = (
        ("gate_ok", verdict["ok"]),
        ("gate_violations", verdict["violations"]),
        ("gate_package_file", verdict["package_path"].name),
        ("gate_package_path", str(verdict["package_path"])),
        ("gate_package_present", verdict["package_present"]),
        ("gate_blocking_pending_count", verdict["blocking_pending_count"]),
        (
            "gate_blocking_pending_prompt_files",
            verdict["blocking_pending_prompt_files"],
        ),
    )
    for field, expected in comparisons:
        if payload[field] != expected:
            raise ValueError(
                f"CLI list JSON row {field} must match current gate verdict"
            )


def _validate_list_pending_prompt_after_route_artifacts(
    payload: dict[object, object],
) -> None:
    if payload["pending_count"] == 0:
        return
    route_artifact_mtime = _latest_route_artifact_mtime(
        payload["mode"],
        Path(payload["pending_prompt_path"]).parent,
    )
    if route_artifact_mtime is None:
        return
    if payload["pending_prompt_mtime"] <= route_artifact_mtime:
        raise ValueError(
            "CLI list JSON row pending_prompt_mtime must be newer than "
            "current route artifacts"
        )


def _expected_gate_package_name(mode: str) -> str:
    package_name_by_mode = {
        "audit": "rebuild_package.json",
        "extend": "extend_rebuild_package.json",
        "compose": "compose_state.json",
        "style": "style_profile.json",
        "compliance": "compliance_report.json",
        "rubric": "rubric.json",
        "time": "time_book.json",
    }
    return package_name_by_mode[mode]


def _validate_gate_package_name(
    *,
    mode: str,
    package_name: str,
    label: str,
) -> None:
    if package_name != _expected_gate_package_name(mode):
        raise ValueError(f"{label} package file must match mode")


def _expected_final_result_name(mode: str) -> str:
    result_name_by_mode = {
        "audit": "audit_report.json",
        "extend": "extend_result.json",
        "compose": "compose_result.json",
        "style": "style_profile.json",
        "compliance": "compliance_report.json",
        "rubric": "rubric.json",
        "time": "timeline_report.json",
    }
    return result_name_by_mode[mode]


def _validate_final_result_name(
    *,
    mode: str,
    result_name: str,
    label: str,
) -> None:
    if result_name != _expected_final_result_name(mode):
        raise ValueError(f"{label} final result file must match mode")


def _validate_route_handoff_name(*, handoff_name: str, label: str) -> None:
    if handoff_name != ROUTE_HANDOFF_FILE:
        raise ValueError(f"{label} route handoff file must be route_handoff.json")


def _validate_mode_output_path(
    *,
    mode: str,
    artifact_path: str,
    field: str,
    label: str,
) -> None:
    path = Path(artifact_path)
    if path.parent.name != mode or path.parent.parent.name != "output":
        raise ValueError(f"{label} {field} must be under output/{mode}")


def _validate_shared_artifact_directory(
    *,
    artifact_paths: list[str],
    label: str,
) -> None:
    if not artifact_paths:
        return
    expected_parent = Path(artifact_paths[0]).parent
    if any(Path(path).parent != expected_parent for path in artifact_paths[1:]):
        raise ValueError(f"{label} artifact paths must share output directory")


def _date_from_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def _validate_latest_date_binding(payload: dict[object, object], *, label: str) -> None:
    expected_date = _date_from_mtime(payload["latest_mtime"])
    if payload["latest_date"] != expected_date:
        raise ValueError(f"{label} latest_date must match latest_mtime")


def _list_row_novel_dir(payload: dict[object, object]) -> Path | None:
    for field in (
        "gate_package_path",
        "final_result_path",
        "route_handoff_path",
        "pending_prompt_path",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value)
        if path.parent.name == payload["mode"] and path.parent.parent.name == "output":
            return path.parent.parent.parent
    return None


def _validate_list_latest_mtime_current(payload: dict[object, object]) -> None:
    novel_dir = _list_row_novel_dir(payload)
    if novel_dir is None:
        return
    current_latest_mtime = _latest_mtime(novel_dir)
    if payload["latest_mtime"] != current_latest_mtime:
        raise ValueError(
            "CLI list JSON row latest_mtime must match current workspace files"
        )


def _validate_gate_json_payload(payload: dict[object, object]) -> None:
    _validate_exact_fields(
        payload,
        fields=GATE_JSON_FIELDS,
        label="CLI gate JSON",
        forbidden_cross_contract_metadata_fields=(
            *PENDING_AUTOMATION_METADATA_FIELDS,
            *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
        ),
    )
    if payload["command"] != "gate":
        raise ValueError(f"unsupported CLI gate JSON command: {payload['command']}")
    for field in (
        "novel",
        "mode",
        "review_route",
        "next_workflow",
        "handoff_path",
        "package_path",
    ):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"CLI gate JSON {field} must be a non-empty string")
    _validate_novel_name(payload["novel"])
    _validate_cli_mode(payload, label="CLI gate JSON")
    for field in ("handoff_path", "package_path"):
        _validate_absolute_path_field(payload, field, label="CLI gate JSON")
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload[field],
            field=field,
            label="CLI gate JSON",
        )
    _validate_shared_artifact_directory(
        artifact_paths=[payload["handoff_path"], payload["package_path"]],
        label="CLI gate JSON",
    )
    _validate_route_handoff_name(
        handoff_name=Path(payload["handoff_path"]).name,
        label="CLI gate JSON",
    )
    _validate_gate_package_name(
        mode=payload["mode"],
        package_name=Path(payload["package_path"]).name,
        label="CLI gate JSON",
    )
    handoff_path = Path(payload["handoff_path"])
    package_path = Path(payload["package_path"])
    if not handoff_path.is_file():
        raise ValueError("CLI gate JSON handoff_path must exist")
    review_route = payload["review_route"]
    next_workflow = payload["next_workflow"]
    if next_workflow not in VALID_WORKFLOW_ROUTES:
        raise ValueError("CLI gate JSON next_workflow must be a supported workflow")
    if review_route != "-" and review_route not in VALID_REVIEW_ROUTES:
        raise ValueError("CLI gate JSON review_route must be pass, rewrite, block, or -")
    if review_route == "-" and next_workflow != "ReviewUnit":
        raise ValueError("CLI gate JSON review_route=- must route to ReviewUnit")
    if review_route == "pass" and next_workflow != "ContinueUnit":
        raise ValueError("CLI gate JSON review_route=pass must route to ContinueUnit")
    if review_route == "rewrite" and next_workflow != "RewriteUnit":
        raise ValueError("CLI gate JSON review_route=rewrite must route to RewriteUnit")
    if review_route == "block" and next_workflow not in BLOCK_REVIEW_WORKFLOWS:
        raise ValueError(
            "CLI gate JSON review_route=block must route to Stop, RebuildUnit, or Replan"
        )
    handoff_review_route, handoff_workflow = _json_route_handoff_values(handoff_path)
    if review_route != handoff_review_route:
        raise ValueError("CLI gate JSON review_route must match route_handoff.json")
    if next_workflow != handoff_workflow:
        raise ValueError("CLI gate JSON next_workflow must match route_handoff.json")
    if not isinstance(payload["ok"], bool):
        raise ValueError("CLI gate JSON ok must be a boolean")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI gate JSON schema_version: {schema_version}"
        )
    if not isinstance(payload["package_present"], bool):
        raise ValueError("CLI gate JSON package_present must be a boolean")
    if payload["package_present"] is not package_path.is_file():
        raise ValueError(
            "CLI gate JSON package_present must match package_path existence"
        )
    violations = _validate_string_list(
        payload["violations"],
        label="CLI gate JSON violations",
    )
    blocking_prompt_files = _validate_prompt_filename_list(
        payload["blocking_pending_prompt_files"],
        label="CLI gate JSON blocking_pending_prompt_files",
    )
    _validate_non_negative_integer(
        payload,
        "blocking_pending_count",
        label="CLI gate JSON",
    )
    if payload["blocking_pending_count"] != len(blocking_prompt_files):
        raise ValueError(
            "CLI gate JSON blocking_pending_count must match "
            "blocking_pending_prompt_files"
        )
    _validate_gate_verdict_consistency(
        ok=payload["ok"],
        violations=violations,
        blocking_count=payload["blocking_pending_count"],
        label="CLI gate JSON",
    )
    _validate_continue_package_presence(
        ok=payload["ok"],
        next_workflow=next_workflow,
        package_present=payload["package_present"],
        label="CLI gate JSON",
    )
    _validate_gate_json_current_verdict(payload, handoff_path=handoff_path)


def _validate_approval_gate_json_payload(payload: dict[object, object]) -> None:
    """Validate the opt-in approval gate JSON contract.

    The first 13 fields mirror the standard gate contract exactly. The one
    deliberate relaxation: under an approve override, review_route may be
    rewrite/block while next_workflow is ContinueUnit (and
    _validate_continue_package_presence is skipped), which the standard
    contract rejects. That override is confined to this new contract and gated
    on approval_ok and approval_decision == "approve".
    """
    _validate_exact_fields(
        payload,
        fields=APPROVAL_GATE_JSON_FIELDS,
        label="CLI approval gate JSON",
        forbidden_cross_contract_metadata_fields=(
            *PENDING_AUTOMATION_METADATA_FIELDS,
            *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
        ),
    )
    if payload["command"] != "gate":
        raise ValueError(
            f"unsupported CLI approval gate JSON command: {payload['command']}"
        )
    for field in (
        "novel",
        "mode",
        "review_route",
        "next_workflow",
        "handoff_path",
        "package_path",
    ):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"CLI approval gate JSON {field} must be a non-empty string"
            )
    _validate_novel_name(payload["novel"])
    _validate_cli_mode(payload, label="CLI approval gate JSON")
    for field in ("handoff_path", "package_path"):
        _validate_absolute_path_field(payload, field, label="CLI approval gate JSON")
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload[field],
            field=field,
            label="CLI approval gate JSON",
        )
    _validate_shared_artifact_directory(
        artifact_paths=[payload["handoff_path"], payload["package_path"]],
        label="CLI approval gate JSON",
    )
    _validate_route_handoff_name(
        handoff_name=Path(payload["handoff_path"]).name,
        label="CLI approval gate JSON",
    )
    _validate_gate_package_name(
        mode=payload["mode"],
        package_name=Path(payload["package_path"]).name,
        label="CLI approval gate JSON",
    )
    handoff_path = Path(payload["handoff_path"])
    package_path = Path(payload["package_path"])
    if not handoff_path.is_file():
        raise ValueError("CLI approval gate JSON handoff_path must exist")
    review_route = payload["review_route"]
    next_workflow = payload["next_workflow"]
    if next_workflow not in VALID_WORKFLOW_ROUTES:
        raise ValueError(
            "CLI approval gate JSON next_workflow must be a supported workflow"
        )
    if review_route != "-" and review_route not in VALID_REVIEW_ROUTES:
        raise ValueError(
            "CLI approval gate JSON review_route must be pass, rewrite, block, or -"
        )
    override_combo = (
        payload["ok"] is True
        and next_workflow == "ContinueUnit"
        and review_route != "pass"
    )
    if override_combo:
        if payload["approval_ok"] is not True:
            raise ValueError(
                "CLI approval gate JSON ContinueUnit override requires "
                "approved critical issues"
            )
        if payload["approval_decision"] != "approve":
            raise ValueError(
                "CLI approval gate JSON ContinueUnit override requires "
                "approval_decision=approve"
            )
    else:
        if review_route == "-" and next_workflow != "ReviewUnit":
            raise ValueError(
                "CLI approval gate JSON review_route=- must route to ReviewUnit"
            )
        if review_route == "pass" and next_workflow != "ContinueUnit":
            raise ValueError(
                "CLI approval gate JSON review_route=pass must route to ContinueUnit"
            )
        if review_route == "rewrite" and next_workflow != "RewriteUnit":
            raise ValueError(
                "CLI approval gate JSON review_route=rewrite must route to RewriteUnit"
            )
        if review_route == "block" and next_workflow not in BLOCK_REVIEW_WORKFLOWS:
            raise ValueError(
                "CLI approval gate JSON review_route=block must route to "
                "Stop, RebuildUnit, or Replan"
            )
    handoff_review_route, handoff_workflow = _json_route_handoff_values(handoff_path)
    if review_route != handoff_review_route:
        raise ValueError(
            "CLI approval gate JSON review_route must match route_handoff.json"
        )
    if not override_combo and next_workflow != handoff_workflow:
        raise ValueError(
            "CLI approval gate JSON next_workflow must match route_handoff.json"
        )
    if not isinstance(payload["ok"], bool):
        raise ValueError("CLI approval gate JSON ok must be a boolean")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI approval gate JSON schema_version: {schema_version}"
        )
    if not isinstance(payload["package_present"], bool):
        raise ValueError("CLI approval gate JSON package_present must be a boolean")
    if payload["package_present"] is not package_path.is_file():
        raise ValueError(
            "CLI approval gate JSON package_present must match package_path existence"
        )
    violations = _validate_string_list(
        payload["violations"],
        label="CLI approval gate JSON violations",
    )
    blocking_prompt_files = _validate_prompt_filename_list(
        payload["blocking_pending_prompt_files"],
        label="CLI approval gate JSON blocking_pending_prompt_files",
    )
    _validate_non_negative_integer(
        payload,
        "blocking_pending_count",
        label="CLI approval gate JSON",
    )
    if payload["blocking_pending_count"] != len(blocking_prompt_files):
        raise ValueError(
            "CLI approval gate JSON blocking_pending_count must match "
            "blocking_pending_prompt_files"
        )
    _validate_gate_verdict_consistency(
        ok=payload["ok"],
        violations=violations,
        blocking_count=payload["blocking_pending_count"],
        label="CLI approval gate JSON",
    )
    if not override_combo:
        _validate_continue_package_presence(
            ok=payload["ok"],
            next_workflow=next_workflow,
            package_present=payload["package_present"],
            label="CLI approval gate JSON",
        )
    _validate_approval_gate_fields(payload)
    _validate_approval_gate_json_current_verdict(
        payload,
        handoff_path=handoff_path,
    )


def _validate_approval_gate_fields(payload: dict[object, object]) -> None:
    if not isinstance(payload["approval_required"], bool):
        raise ValueError("CLI approval gate JSON approval_required must be a boolean")
    critical_ids = _validate_string_list(
        payload["critical_issue_ids"],
        label="CLI approval gate JSON critical_issue_ids",
    )
    if payload["approval_required"] is not (len(critical_ids) > 0):
        raise ValueError(
            "CLI approval gate JSON approval_required must match critical_issue_ids"
        )
    approval_decision = payload["approval_decision"]
    if approval_decision not in {"approve", "reject", "-"}:
        raise ValueError(
            "CLI approval gate JSON approval_decision must be approve, reject, or -"
        )
    if not isinstance(payload["approval_ok"], bool):
        raise ValueError("CLI approval gate JSON approval_ok must be a boolean")
    if payload["approval_ok"] is False and payload["ok"] is True:
        raise ValueError(
            "CLI approval gate JSON failed approval must not pass the gate"
        )
    if approval_decision == "reject" and payload["approval_ok"] is True:
        raise ValueError(
            "CLI approval gate JSON rejected approval cannot be approval_ok"
        )
    if not critical_ids:
        if payload["approval_ok"] is not True:
            raise ValueError(
                "CLI approval gate JSON no critical issues requires approval_ok"
            )
        if approval_decision != "-":
            raise ValueError(
                "CLI approval gate JSON no critical issues requires "
                "approval_decision=-"
            )


def _validate_approval_gate_json_current_verdict(
    payload: dict[object, object],
    *,
    handoff_path: Path,
) -> None:
    verdict = _approval_gate_verdict(
        mode=payload["mode"],
        output_dir=handoff_path.parent,
        handoff_path=handoff_path,
    )
    comparisons = (
        ("ok", "ok"),
        ("review_route", "review_route"),
        ("next_workflow", "next_workflow"),
        ("violations", "violations"),
        ("package_present", "package_present"),
        ("blocking_pending_count", "blocking_pending_count"),
        ("blocking_pending_prompt_files", "blocking_pending_prompt_files"),
        ("approval_required", "approval_required"),
        ("critical_issue_ids", "critical_issue_ids"),
        ("approval_decision", "approval_decision"),
        ("approval_ok", "approval_ok"),
    )
    for payload_field, verdict_field in comparisons:
        if payload[payload_field] != verdict[verdict_field]:
            raise ValueError(
                f"CLI approval gate JSON {payload_field} must match current "
                f"approval gate verdict"
            )


def _validate_optional_non_negative_integer(
    payload: dict[object, object],
    field: str,
    *,
    label: str,
) -> None:
    value = payload[field]
    if value is None:
        return
    _validate_non_negative_integer(payload, field, label=label)


def _validate_list_route_status_consistency(payload: dict[object, object]) -> None:
    route = payload["route"]
    next_workflow = payload["next_workflow"]
    status = payload["status"]
    if route is None:
        if next_workflow is not None:
            raise ValueError("CLI list JSON row next_workflow requires route")
        if status in {"completed", "rewrite", "blocked"}:
            raise ValueError("CLI list JSON row completed status requires route")
        return
    if route not in VALID_REVIEW_ROUTES:
        raise ValueError("CLI list JSON row route must be pass, rewrite, or block")
    expected_status = LIST_ROW_STATUS_BY_ROUTE[route]
    if status != expected_status:
        raise ValueError("CLI list JSON row status must match route")
    if next_workflow is None:
        return
    if next_workflow not in VALID_WORKFLOW_ROUTES:
        raise ValueError("CLI list JSON row next_workflow must be a supported workflow")
    if route == "pass" and next_workflow != "ContinueUnit":
        raise ValueError("CLI list JSON row route=pass must route to ContinueUnit")
    if route == "rewrite" and next_workflow != "RewriteUnit":
        raise ValueError("CLI list JSON row route=rewrite must route to RewriteUnit")
    if route == "block" and next_workflow not in BLOCK_REVIEW_WORKFLOWS:
        raise ValueError(
            "CLI list JSON row route=block must route to Stop, RebuildUnit, or Replan"
        )


def _validate_list_route_artifact_consistency(payload: dict[object, object]) -> None:
    has_route = payload["route"] is not None
    has_next_workflow = payload["next_workflow"] is not None
    has_final_result = payload["final_result_file"] is not None
    has_route_handoff = payload["route_handoff_file"] is not None
    if has_route and not has_final_result:
        raise ValueError("CLI list JSON row route requires final result artifact")
    if not has_route and has_final_result:
        raise ValueError("CLI list JSON row final result artifact requires route")
    if has_next_workflow and not has_route_handoff:
        raise ValueError("CLI list JSON row next_workflow requires route handoff artifact")
    if not has_next_workflow and has_route_handoff:
        raise ValueError("CLI list JSON row route handoff artifact requires next_workflow")


def _validate_list_gate_artifact_consistency(payload: dict[object, object]) -> None:
    has_gate_verdict = payload["gate_ok"] is not None
    has_route_handoff = payload["route_handoff_file"] is not None
    if has_gate_verdict and not has_route_handoff:
        raise ValueError("CLI list JSON row gate verdict requires route handoff artifact")
    if not has_gate_verdict and has_route_handoff:
        raise ValueError("CLI list JSON row route handoff artifact requires gate verdict")


def _expected_list_detail(payload: dict[object, object]) -> str | None:
    if payload["status"] == "initialized":
        return "-"
    if payload["pending_count"] > 0:
        return f"[WAITING: {payload['pending_response_file']}]"
    if payload["route"] is None:
        return None
    if payload["next_workflow"] is None:
        return f"route={payload['route']}"
    return f"route={payload['route']} next={payload['next_workflow']}"


def _validate_list_detail_consistency(payload: dict[object, object]) -> None:
    expected_detail = _expected_list_detail(payload)
    if expected_detail is None:
        return
    if payload["detail"] != expected_detail:
        raise ValueError(
            "CLI list JSON row detail must match status and route evidence"
        )


def _list_pending_slot_identity_from_payload(
    payload: dict[object, object],
) -> tuple[object, ...]:
    return (
        payload["pending_slot_id"],
        payload["pending_prompt_file"],
        payload["pending_response_file"],
        payload["pending_prompt_path"],
        payload["pending_response_path"],
        payload["pending_prompt_mtime"],
        payload["pending_prompt_hash"],
        payload["pending_prompt_bytes"],
    )


def _validate_list_waiting_current_discovery(
    payload: dict[object, object],
) -> None:
    if payload["pending_count"] == 0:
        return
    output_dir = Path(payload["pending_prompt_path"]).parent
    artifact_cutoff = _latest_route_artifact_mtime(payload["mode"], output_dir)
    current_slots = _waiting_slots(output_dir, newer_than=artifact_cutoff)
    if payload["pending_count"] != len(current_slots):
        raise ValueError(
            "CLI list JSON row pending_count and first pending slot must match "
            "current pending discovery"
        )
    if not current_slots:
        raise ValueError(
            "CLI list JSON row pending_count and first pending slot must match "
            "current pending discovery"
        )
    if _list_pending_slot_identity_from_payload(payload) != (
        _pending_slot_identity_from_slot(current_slots[0])
    ):
        raise ValueError(
            "CLI list JSON row pending_count and first pending slot must match "
            "current pending discovery"
        )


def _validate_list_json_row_payload(payload: dict[object, object]) -> None:
    _validate_exact_fields(
        payload,
        fields=LIST_JSON_ROW_FIELDS,
        label="CLI list JSON row",
        forbidden_cross_contract_metadata_fields=RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    )
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != JSON_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported CLI list JSON row schema_version: {schema_version}"
        )
    if payload["command"] != "list":
        raise ValueError(
            f"unsupported CLI list JSON row command: {payload['command']}"
        )
    for field in ("name", "mode", "status", "detail", "latest_date"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"CLI list JSON row {field} must be a non-empty string")
    _validate_novel_name(payload["name"])
    status = payload["status"]
    if status not in LIST_ROW_STATUSES:
        raise ValueError("CLI list JSON row status must be a supported status")
    _validate_cli_mode(payload, label="CLI list JSON row", allow_unknown=True)
    if payload["mode"] == "unknown" and status != "initialized":
        raise ValueError("CLI list JSON row unknown mode requires initialized status")
    _validate_finite_non_negative_number(
        payload["latest_mtime"],
        label="CLI list JSON row latest_mtime",
    )
    _validate_latest_date_binding(payload, label="CLI list JSON row")
    for field in (
        "route",
        "next_workflow",
        "gate_package_file",
        "gate_package_path",
        "pending_prompt_file",
        "pending_response_file",
        "pending_prompt_path",
        "pending_response_path",
        "pending_slot_id",
        "final_result_file",
        "final_result_path",
        "route_handoff_file",
        "route_handoff_path",
    ):
        _validate_optional_string(payload, field, label="CLI list JSON row")
    _validate_list_route_status_consistency(payload)
    gate_ok = payload["gate_ok"]
    if gate_ok is not None and not isinstance(gate_ok, bool):
        raise ValueError("CLI list JSON row gate_ok must be a boolean or null")
    gate_package_present = payload["gate_package_present"]
    if gate_package_present is not None and not isinstance(gate_package_present, bool):
        raise ValueError(
            "CLI list JSON row gate_package_present must be a boolean or null"
        )
    gate_violations = _validate_string_list(
        payload["gate_violations"],
        label="CLI list JSON row gate_violations",
    )
    gate_blocking_prompt_files = _validate_prompt_filename_list(
        payload["gate_blocking_pending_prompt_files"],
        label="CLI list JSON row gate_blocking_pending_prompt_files",
    )
    _validate_optional_non_negative_integer(
        payload,
        "gate_blocking_pending_count",
        label="CLI list JSON row",
    )
    if payload["gate_blocking_pending_count"] is not None and (
        payload["gate_blocking_pending_count"] != len(gate_blocking_prompt_files)
    ):
        raise ValueError(
            "CLI list JSON row gate_blocking_pending_count must match "
            "gate_blocking_pending_prompt_files"
        )
    if gate_ok is None:
        if gate_violations:
            raise ValueError("CLI list JSON row gate_violations must be empty without gate verdict")
        for field in ("gate_package_file", "gate_package_path", "gate_package_present"):
            if payload[field] is not None:
                raise ValueError(
                    f"CLI list JSON row {field} must be null without gate verdict"
                )
        if payload["gate_blocking_pending_count"] is not None:
            raise ValueError(
                "CLI list JSON row gate_blocking_pending_count must be null without gate verdict"
            )
    else:
        for field in ("gate_package_file", "gate_package_path"):
            if payload[field] is None:
                raise ValueError(
                    f"CLI list JSON row {field} must be present with gate verdict"
                )
        if payload["gate_package_present"] is None:
            raise ValueError(
                "CLI list JSON row gate_package_present must be present with gate verdict"
            )
        if payload["gate_blocking_pending_count"] is None:
            raise ValueError(
                "CLI list JSON row gate_blocking_pending_count must be present with gate verdict"
            )
        _validate_gate_verdict_consistency(
            ok=gate_ok,
            violations=gate_violations,
            blocking_count=payload["gate_blocking_pending_count"],
            label="CLI list JSON row gate",
        )
        _validate_continue_package_presence(
            ok=gate_ok,
            next_workflow=payload["next_workflow"],
            package_present=payload["gate_package_present"],
            label="CLI list JSON row gate",
        )
    _validate_optional_artifact_path_identity(
        payload,
        file_field="gate_package_file",
        path_field="gate_package_path",
        label="CLI list JSON row",
    )
    if payload["gate_package_file"] is not None:
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload["gate_package_path"],
            field="gate_package_path",
            label="CLI list JSON row",
        )
        _validate_gate_package_name(
            mode=payload["mode"],
            package_name=payload["gate_package_file"],
            label="CLI list JSON row",
        )
        package_exists = Path(payload["gate_package_path"]).is_file()
        if payload["gate_package_present"] is not package_exists:
            raise ValueError(
                "CLI list JSON row gate_package_present must match "
                "gate_package_path existence"
            )
    _validate_optional_artifact_path_identity(
        payload,
        file_field="final_result_file",
        path_field="final_result_path",
        label="CLI list JSON row",
    )
    if payload["final_result_file"] is not None:
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload["final_result_path"],
            field="final_result_path",
            label="CLI list JSON row",
        )
        _validate_final_result_name(
            mode=payload["mode"],
            result_name=payload["final_result_file"],
            label="CLI list JSON row",
        )
        _validate_artifact_path_exists(
            payload,
            "final_result_path",
            label="CLI list JSON row",
        )
    _validate_optional_artifact_path_identity(
        payload,
        file_field="route_handoff_file",
        path_field="route_handoff_path",
        label="CLI list JSON row",
    )
    if payload["route_handoff_file"] is not None:
        _validate_mode_output_path(
            mode=payload["mode"],
            artifact_path=payload["route_handoff_path"],
            field="route_handoff_path",
            label="CLI list JSON row",
        )
        _validate_route_handoff_name(
            handoff_name=payload["route_handoff_file"],
            label="CLI list JSON row",
        )
        _validate_artifact_path_exists(
            payload,
            "route_handoff_path",
            label="CLI list JSON row",
        )
    _validate_shared_artifact_directory(
        artifact_paths=[
            payload[field]
            for field in (
                "gate_package_path",
                "final_result_path",
                "route_handoff_path",
            )
            if payload[field] is not None
        ],
        label="CLI list JSON row",
    )
    _validate_list_route_artifact_consistency(payload)
    _validate_list_gate_artifact_consistency(payload)
    if payload["final_result_file"] is not None:
        result_route = _read_route_value(Path(payload["final_result_path"]))
        if payload["route"] != result_route:
            raise ValueError(
                "CLI list JSON row route must match final_result_path route"
            )
    if payload["route_handoff_file"] is not None:
        handoff_route, handoff_workflow = _json_route_handoff_values(
            Path(payload["route_handoff_path"])
        )
        if payload["route"] != handoff_route:
            raise ValueError("CLI list JSON row route must match route_handoff.json")
        if payload["next_workflow"] != handoff_workflow:
            raise ValueError(
                "CLI list JSON row next_workflow must match route_handoff.json"
            )
    _validate_list_json_current_gate_verdict(payload)
    _validate_non_negative_integer(payload, "pending_count", label="CLI list JSON row")
    pending_count = payload["pending_count"]
    if status == "waiting" and pending_count == 0:
        raise ValueError("CLI list JSON row waiting status requires pending_count")
    if status != "waiting" and pending_count != 0:
        raise ValueError(
            "CLI list JSON row pending_count must be zero unless status is waiting"
        )
    if pending_count == 0:
        for field in (
            "pending_prompt_file",
            "pending_response_file",
            "pending_prompt_path",
            "pending_response_path",
            "pending_prompt_hash",
            "pending_prompt_bytes",
            "pending_prompt_mtime",
            "pending_slot_id",
        ):
            if payload[field] is not None:
                raise ValueError(
                    f"CLI list JSON row {field} must be null when pending_count is 0"
                )
    else:
        for field in (
            "pending_prompt_file",
            "pending_response_file",
            "pending_prompt_path",
            "pending_response_path",
            "pending_slot_id",
        ):
            value = payload[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"CLI list JSON row {field} must be a non-empty string"
                )
        validate_content_hash(
            payload["pending_prompt_hash"],
            "CLI list JSON row pending_prompt_hash",
        )
        _validate_positive_integer(
            payload,
            "pending_prompt_bytes",
            label="CLI list JSON row",
        )
        _validate_finite_non_negative_number(
            payload["pending_prompt_mtime"],
            label="CLI list JSON row pending_prompt_mtime",
        )
        if payload["pending_prompt_mtime"] > payload["latest_mtime"]:
            raise ValueError(
                "CLI list JSON row pending_prompt_mtime must not exceed latest_mtime"
            )
        _validate_staged_slot_identity(
            payload,
            prompt_file_field="pending_prompt_file",
            response_file_field="pending_response_file",
            prompt_path_field="pending_prompt_path",
            response_path_field="pending_response_path",
            slot_id_field="pending_slot_id",
            label="CLI list JSON row",
        )
        if Path(payload["pending_response_path"]).exists():
            raise ValueError(
                "CLI list JSON row pending_response_path must not exist"
            )
        _validate_pending_prompt_file_evidence(
            prompt_path=Path(payload["pending_prompt_path"]),
            prompt_hash=payload["pending_prompt_hash"],
            prompt_bytes=payload["pending_prompt_bytes"],
            prompt_mtime=payload["pending_prompt_mtime"],
            label="CLI list JSON row",
        )
        _validate_list_pending_prompt_after_route_artifacts(payload)
        _validate_list_waiting_current_discovery(payload)
    _validate_list_detail_consistency(payload)
    _validate_list_latest_mtime_current(payload)
    validate_pending_automation_metadata_in_payload(
        payload,
        pending_count=pending_count,
    )


def _validate_list_json_payload(payload: object) -> None:
    if not isinstance(payload, list):
        raise ValueError("CLI list JSON payload must be a list")
    for row in payload:
        _validate_list_json_row_payload(row)


class NovelArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, emit_json_errors: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.emit_json_errors = emit_json_errors

    def error(self, message: str) -> None:
        if self.emit_json_errors:
            payload = _json_error_payload(
                error_stage="argument",
                error_type="ArgumentError",
                error=message,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            self.exit(2)
        super().error(message)


def _novels_root() -> Path:
    root = os.environ.get("NOVELS_ROOT")
    return Path(root).resolve() if root else DEFAULT_NOVELS_ROOT


def _validate_novel_name(name: str) -> None:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
        raise ValueError(f"invalid novel name: {name}")


def _novel_dir(name: str) -> Path:
    _validate_novel_name(name)
    return _novels_root() / name


def _output_dir(novel_dir: Path, mode: str) -> Path:
    return novel_dir / "output" / mode


def _copy_to_workspace(source: str, target: Path) -> Path:
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"input file not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path != target.resolve():
        shutil.copy2(source_path, target)
    return target


def _ensure_input(args: argparse.Namespace, novel_dir: Path) -> Path:
    input_path = novel_dir / "input.txt"
    if args.input:
        return _copy_to_workspace(args.input, input_path)
    if input_path.exists():
        return input_path
    raise FileNotFoundError("missing --input and no existing novels/<name>/input.txt")


def _input_source(args: argparse.Namespace, novel_dir: Path) -> Path:
    if args.input:
        source_path = Path(args.input).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"input file not found: {args.input}")
        return source_path
    input_path = novel_dir / "input.txt"
    if input_path.exists():
        return input_path
    raise FileNotFoundError("missing --input and no existing novels/<name>/input.txt")


def _preflight_run_hash(
    *,
    output_dir: Path,
    hash_filename: str,
    current_hash: str,
    label: str,
) -> bool:
    errors = validate_run_hash(
        hash_path=output_dir / hash_filename,
        current_hash=current_hash,
        output_dir=output_dir,
        label=label,
        write_hash=False,
    )
    if not errors:
        return True
    for error in errors:
        print(error)
    return False


def _decode_text(data: bytes, path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode file: {path}")


def _read_text(path: Path) -> str:
    return _decode_text(Path(path).read_bytes(), Path(path))


def _read_text_with_hash(path: Path) -> tuple[str, str, int]:
    data = Path(path).read_bytes()
    evidence = content_evidence_from_bytes(data)
    return data.decode("utf-8-sig"), evidence.content_hash, evidence.byte_count


def _is_same_existing_file(left: Path, right: Path) -> bool:
    left = Path(left)
    right = Path(right)
    if not left.exists() or not right.exists():
        return False
    return left.samefile(right)


def _default_compose_workspec() -> WorkSpec:
    return WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )


def _write_mode(novel_dir: Path, mode: str) -> None:
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / MODE_FILE).write_text(mode, encoding="utf-8")


def _write_config(novel_dir: Path, data: dict) -> None:
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / CONFIG_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_config(novel_dir: Path) -> dict:
    config_path = novel_dir / CONFIG_FILE
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read run config: {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid run config JSON: {config_path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid run config object: {config_path}")
    unknown = sorted(set(data) - VALID_CONFIG_FIELDS)
    if unknown:
        raise ValueError(
            f"invalid run config field(s): {config_path}: {', '.join(unknown)}"
        )
    return data


def _read_mode(novel_dir: Path) -> str | None:
    config = _read_config(novel_dir)
    if "mode" in config:
        mode = config["mode"]
        if mode not in VALID_MODES:
            raise ValueError(f"invalid saved mode in {novel_dir / CONFIG_FILE}: {mode}")
        return mode
    mode_path = novel_dir / MODE_FILE
    if mode_path.exists():
        mode = mode_path.read_text(encoding="utf-8").strip() or None
        if mode is not None and mode not in VALID_MODES:
            raise ValueError(f"invalid saved mode in {mode_path}: {mode}")
        return mode
    return None


def _append_long_options(command: list[str], args: argparse.Namespace) -> None:
    if getattr(args, "chapter_wise", False):
        command.append("--chapter-wise")
    if getattr(args, "chapter_range", None):
        command.extend(["--range", args.chapter_range])
    if getattr(args, "batch_size", None) is not None:
        command.extend(["--batch-size", str(args.batch_size)])
    if getattr(args, "max_chapters", None) is not None:
        command.extend(["--max-chapters", str(args.max_chapters)])


def _validate_long_options(args: argparse.Namespace) -> None:
    validate_long_runtime_args(
        chapter_range=getattr(args, "chapter_range", None),
        batch_size=(
            getattr(args, "batch_size", None)
            if getattr(args, "batch_size", None) is not None
            else 50
        ),
        max_chapters=(
            getattr(args, "max_chapters", None)
            if getattr(args, "max_chapters", None) is not None
            else 100
        ),
    )


def _validate_configured_long_options(config: dict) -> None:
    validate_long_runtime_args(
        chapter_range=config.get("chapter_range"),
        batch_size=config.get("batch_size") if config.get("batch_size") is not None else 50,
        max_chapters=(
            config.get("max_chapters") if config.get("max_chapters") is not None else 100
        ),
    )


def _append_configured_long_options(command: list[str], config: dict) -> None:
    if config.get("chapter_wise"):
        command.append("--chapter-wise")
    if config.get("chapter_range"):
        command.extend(["--range", config["chapter_range"]])
    if config.get("batch_size") is not None:
        command.extend(["--batch-size", str(config["batch_size"])])
    if config.get("max_chapters") is not None:
        command.extend(["--max-chapters", str(config["max_chapters"])])


def _capture_long_config(args: argparse.Namespace) -> dict:
    return {
        "chapter_wise": getattr(args, "chapter_wise", False),
        "chapter_range": getattr(args, "chapter_range", None),
        "batch_size": getattr(args, "batch_size", None),
        "max_chapters": getattr(args, "max_chapters", None),
    }


def _run_child(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return completed.returncode


def _script_path(name: str) -> str:
    return str(PROJECT_ROOT / "src" / name)


def _run_audit(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "audit")
    _validate_long_options(args)
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "audit")
    _write_config(
        novel_dir,
        {
            "mode": "audit",
            "format": args.format,
            "outline_only": args.outline_only,
            **_capture_long_config(args),
        },
    )

    command = [
        sys.executable,
        _script_path("audit_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.format:
        command.extend(["--format", args.format])
    if args.outline_only:
        command.append("--outline-only")
    _append_long_options(command, args)
    return _run_child(command)


def _run_extend(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "extend")
    _validate_long_options(args)
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "extend")
    _write_config(
        novel_dir,
        {"mode": "extend", **_capture_long_config(args)}
        | ({"style": args.style} if getattr(args, "style", None) else {})
        | {"retrieval": getattr(args, "retrieval", "on")},
    )

    command = [
        sys.executable,
        _script_path("extend_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    _append_long_options(command, args)
    if getattr(args, "style", None):
        command.extend(["--style", args.style])
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    command.extend(["--retrieval", getattr(args, "retrieval", "on")])
    if getattr(args, "no_prose", False):
        command.append("--no-prose")
    return _run_child(command)


def _run_compose(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "compose")
    if args.workspec:
        source_workspec_path = Path(args.workspec).resolve()
        if not source_workspec_path.exists():
            raise FileNotFoundError(f"input file not found: {args.workspec}")
        source_workspec = WorkSpec.model_validate_json(_read_text(source_workspec_path))
    elif (novel_dir / "workspec.json").exists():
        source_workspec_path = novel_dir / "workspec.json"
        source_workspec = WorkSpec.model_validate_json(_read_text(source_workspec_path))
    else:
        source_workspec_path = None
        source_workspec = _default_compose_workspec()
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".workspec_hash",
        current_hash=model_content_hash(source_workspec),
        label="WorkSpec",
    ):
        return 1
    _write_mode(novel_dir, "compose")

    command = [sys.executable, _script_path("compose_short_form.py")]
    if source_workspec_path is not None and args.workspec:
        workspec_path = _copy_to_workspace(args.workspec, novel_dir / "workspec.json")
        command.append(str(workspec_path))
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": "workspec.json"}
            | ({"style": args.style} if getattr(args, "style", None) else {}),
        )
    elif source_workspec_path is not None:
        command.append(str(novel_dir / "workspec.json"))
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": "workspec.json"}
            | ({"style": args.style} if getattr(args, "style", None) else {})
            | {"retrieval": getattr(args, "retrieval", "on")},
        )
    else:
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": None}
            | ({"style": args.style} if getattr(args, "style", None) else {})
            | {"retrieval": getattr(args, "retrieval", "on")},
        )
    command.extend(["--output-dir", str(output_dir)])
    if getattr(args, "style", None):
        command.extend(["--style", args.style])
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    command.extend(["--retrieval", getattr(args, "retrieval", "on")])
    if getattr(args, "no_prose", False):
        command.append("--no-prose")
    return _run_child(command)


def _run_style(args: argparse.Namespace) -> int:
    """从已有小说文本提炼写作风格档案（或引用风格库档案做 lint）."""
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "style")
    # --style-search：纯库检索（全局 manifest），无需输入文本 / hash / config
    if getattr(args, "style_search", None):
        command = [
            sys.executable,
            _script_path("style_short_form.py"),
            "--output-dir",
            str(output_dir),
            "--style-search",
            args.style_search,
        ]
        return _run_child(command)
    source_input = _input_source(args, novel_dir)
    # --style 引用模式不做提炼，跳过 hash 校验（输入仅供 lint 用）
    if not args.style and not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "style")
    _write_config(
        novel_dir,
        {
            "mode": "style",
            **({"name": args.name} if args.name else {}),
            **({"style": args.style} if args.style else {}),
        },
    )

    command = [
        sys.executable,
        _script_path("style_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.tone:
        command.extend(["--tone", args.tone])
    if args.genre:
        command.extend(["--genre", args.genre])
    if args.lint:
        command.append("--lint")
    if args.name:
        command.extend(["--name", args.name])
    if args.style:
        command.extend(["--style", args.style])
    if getattr(args, "force", False):
        command.append("--force")
    if getattr(args, "no_library", False):
        command.append("--no-library")
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    return _run_child(command)


def _run_compliance(args: argparse.Namespace) -> int:
    """内容合规模块：扫敏感词 + 平台政策（纯代码，无 LLM 阶段）."""
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "compliance")
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "compliance")
    _write_config(
        novel_dir,
        {
            "mode": "compliance",
            **({"platform": args.platform} if getattr(args, "platform", None) else {}),
            **({"sensitive": args.sensitive} if getattr(args, "sensitive", None) else {}),
            **({"lexicon": args.lexicon} if getattr(args, "lexicon", None) else {}),
        },
    )

    command = [
        sys.executable,
        _script_path("compliance_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.platform:
        command.extend(["--platform", args.platform])
    if args.sensitive:
        command.extend(["--sensitive", args.sensitive])
    if args.lexicon:
        command.extend(["--lexicon", args.lexicon])
    return _run_child(command)


def _run_rubric(args: argparse.Namespace) -> int:
    """导出 WebNovelBench 8 维本地评测 rubric（纯代码，无输入文件）.

    rubric 是静态领域知识导出（无 input 文件、无 .input_hash），
    输出到 novels/<name>/output/rubric/rubric.json。
    """
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "rubric")
    _write_mode(novel_dir, "rubric")
    _write_config(novel_dir, {"mode": "rubric"})

    command = [
        sys.executable,
        _script_path("rubric_short_form.py"),
        "--output-dir",
        str(output_dir),
    ]
    return _run_child(command)


def _run_time(args: argparse.Namespace) -> int:
    """时间域模块：TimeBook 管理 + 时间审计（纯代码，无 LLM 阶段）.

    横向域：output/time 同时被 audit/extend/compose 消费；
    时间域产出 time_book.json / timeline_report.json。
    """
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "time")
    _write_mode(novel_dir, "time")
    _write_config(novel_dir, {"mode": "time"})

    command = [
        sys.executable,
        _script_path("time_short_form.py"),
        "--output-dir",
        str(output_dir),
    ]
    if args.input:
        command.extend(["--input", str(_ensure_input(args, novel_dir))])
    if args.rebuild:
        command.append("--rebuild")
    if args.check:
        command.append("--check")
    return _run_child(command)


def _run_resume(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    config = _read_config(novel_dir)
    if mode is None:
        print(f"Error: no saved mode for novel: {args.novel}")
        return 1

    if mode == "audit":
        output_dir = _output_dir(novel_dir, "audit")
        _validate_configured_long_options(config)
        input_path = novel_dir / "input.txt"
        if not input_path.exists():
            print(f"Error: missing input file: {input_path}")
            return 1
        command = [
            sys.executable,
            _script_path("audit_short_form.py"),
            str(input_path),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("format"):
            command.extend(["--format", config["format"]])
        if config.get("outline_only"):
            command.append("--outline-only")
        _append_configured_long_options(command, config)
        return _run_child(command)
    if mode == "extend":
        output_dir = _output_dir(novel_dir, "extend")
        _validate_configured_long_options(config)
        input_path = novel_dir / "input.txt"
        if not input_path.exists():
            print(f"Error: missing input file: {input_path}")
            return 1
        command = [
            sys.executable,
            _script_path("extend_short_form.py"),
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--resume",
        ]
        _append_configured_long_options(command, config)
        if config.get("style"):
            command.extend(["--style", config["style"]])
        command.extend(["--retrieval", config.get("retrieval", "on")])
        return _run_child(command)
    if mode == "compose":
        output_dir = _output_dir(novel_dir, "compose")
        command = [
            sys.executable,
            _script_path("compose_short_form.py"),
            "--output-dir",
            str(output_dir),
            "--resume",
        ]
        if config.get("style"):
            command.extend(["--style", config["style"]])
        command.extend(["--retrieval", config.get("retrieval", "on")])
        return _run_child(command)
    if mode == "style":
        output_dir = _output_dir(novel_dir, "style")
        command = [
            sys.executable,
            _script_path("style_short_form.py"),
            str(novel_dir / "input.txt"),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("style"):
            command.extend(["--style", config["style"]])
        if config.get("name"):
            command.extend(["--name", config["name"]])
        return _run_child(command)
    if mode == "compliance":
        output_dir = _output_dir(novel_dir, "compliance")
        command = [
            sys.executable,
            _script_path("compliance_short_form.py"),
            str(novel_dir / "input.txt"),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("platform"):
            command.extend(["--platform", config["platform"]])
        if config.get("sensitive"):
            command.extend(["--sensitive", config["sensitive"]])
        if config.get("lexicon"):
            command.extend(["--lexicon", config["lexicon"]])
        return _run_child(command)
    if mode == "rubric":
        output_dir = _output_dir(novel_dir, "rubric")
        command = [
            sys.executable,
            _script_path("rubric_short_form.py"),
            "--output-dir",
            str(output_dir),
        ]
        return _run_child(command)
    if mode == "time":
        output_dir = _output_dir(novel_dir, "time")
        command = [
            sys.executable,
            _script_path("time_short_form.py"),
            "--output-dir",
            str(output_dir),
        ]
        input_path = novel_dir / "input.txt"
        if input_path.exists():
            command.extend(["--input", str(input_path)])
        if _read_config(novel_dir).get("rebuild"):
            command.append("--rebuild")
        command.append("--check")
        return _run_child(command)

    print(f"Error: unknown saved mode for {args.novel}: {mode}")
    return 1


def _latest_mtime(novel_dir: Path) -> float:
    paths = [novel_dir]
    output_dir = novel_dir / "output"
    if output_dir.exists():
        paths.extend(p for p in output_dir.rglob("*") if p.is_file())
    return max((p.stat().st_mtime for p in paths), default=novel_dir.stat().st_mtime)


def _latest_date(novel_dir: Path) -> str:
    return _date_from_mtime(_latest_mtime(novel_dir))


def _read_route(path: Path) -> str:
    return f"route={_read_route_value(path)}"


def _read_route_value(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read result JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid result JSON: {path}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"invalid result JSON object: {path}")
    route = data.get("route")
    if route not in {"pass", "rewrite", "block"}:
        raise ValueError(f"invalid result route in {path}: {route}")
    return route


def _load_route_handoff_packet(path: Path) -> HandoffPacket:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read route handoff JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid route handoff JSON: {path}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"invalid route handoff JSON object: {path}")
    try:
        packet = HandoffPacket(**data)
    except Exception as exc:
        raise ValueError(f"invalid route handoff packet: {path}: {exc}") from exc

    ok, violations = HandoffBoundaryUnit().verify(packet)
    if not ok:
        raise ValueError(
            f"invalid route handoff packet: {path}: {', '.join(violations)}"
        )
    return packet


def _read_route_handoff(path: Path) -> tuple[str, str]:
    packet = _load_route_handoff_packet(path)
    route = packet.next_route.review_route
    if route not in {"pass", "rewrite", "block"}:
        raise ValueError(f"route handoff missing review_route in {path}")
    return route, packet.next_route.recommended_workflow


def _waiting_slots(
    output_dir: Path,
    *,
    newer_than: float | None = None,
):
    return ResponseFileBoundaryUnit().discover_pending_slots(
        output_dir,
        newer_than=newer_than,
    )


def _final_route_path(mode: str, output_dir: Path) -> tuple[Path, float] | None:
    if mode == "audit":
        candidates: list[tuple[Path, float]] = []
        json_report = output_dir / "audit_report.json"
        if json_report.exists():
            candidates.append((json_report, json_report.stat().st_mtime))

        markdown_report = output_dir / "audit_report.md"
        review_result = output_dir / "review_result.json"
        if markdown_report.exists():
            if not review_result.exists():
                raise ValueError(
                    f"missing route JSON for markdown audit report: {review_result}"
                )
            candidates.append(
                (
                    review_result,
                    max(markdown_report.stat().st_mtime, review_result.stat().st_mtime),
                )
            )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[1])

    final_by_mode = {
        "extend": output_dir / "extend_result.json",
        "compose": output_dir / "compose_result.json",
        "compliance": output_dir / "compliance_report.json",
        "time": output_dir / "timeline_report.json",
    }
    final_path = final_by_mode.get(mode)
    if final_path and final_path.exists():
        return final_path, final_path.stat().st_mtime
    return None


def _route_handoff_path(output_dir: Path) -> tuple[Path, float] | None:
    path = output_dir / ROUTE_HANDOFF_FILE
    if path.exists():
        return path, path.stat().st_mtime
    return None


def _route_detail(
    final_path: Path,
    handoff: tuple[Path, float] | None,
) -> tuple[str, str, str | None]:
    route = _read_route_value(final_path)
    if handoff is None:
        return route, f"route={route}", None

    handoff_path, _mtime = handoff
    handoff_route, next_workflow = _read_route_handoff(handoff_path)
    if handoff_route != route:
        raise ValueError(
            f"route handoff mismatch: {handoff_path} has {handoff_route}, "
            f"but {final_path} has {route}"
        )
    return route, f"route={route} next={next_workflow}", next_workflow


def _gate_package_path(mode: str, output_dir: Path) -> Path:
    package_by_mode = {
        "audit": output_dir / "rebuild_package.json",
        "extend": output_dir / "extend_rebuild_package.json",
        "compose": output_dir / "compose_state.json",
    }
    package_path = package_by_mode.get(mode)
    if package_path is None:
        raise ValueError(f"invalid saved mode for gate: {mode}")
    return package_path


def _route_gate_verdict(
    *,
    mode: str,
    output_dir: Path,
    handoff_path: Path,
) -> dict[str, object]:
    packet = _load_route_handoff_packet(handoff_path)
    final = _final_route_path(mode, output_dir)
    if final:
        final_path, _mtime = final
        _route_detail(final_path, (handoff_path, handoff_path.stat().st_mtime))
    package_path = _gate_package_path(mode, output_dir)
    package = (
        SerializationBoundaryUnit().load(package_path)
        if package_path.exists()
        else None
    )
    ok, violations = OrchestrationGateUnit().verify_entry(packet, package)
    blocking_slots = _waiting_slots(
        output_dir,
        newer_than=handoff_path.stat().st_mtime,
    )
    if blocking_slots:
        names = ", ".join(slot.prompt_path.name for slot in blocking_slots)
        violations = [
            *violations,
            f"route gate: pending prompt newer than route handoff: {names}",
        ]
        ok = False
    return {
        "ok": ok,
        "review_route": packet.next_route.review_route or "-",
        "next_workflow": packet.next_route.recommended_workflow,
        "violations": violations,
        "handoff_path": handoff_path,
        "package_path": package_path,
        "package_present": package_path.exists(),
        "blocking_pending_count": len(blocking_slots),
        "blocking_pending_prompt_files": [
            slot.prompt_path.name for slot in blocking_slots
        ],
    }


def _approval_gate_verdict(
    *,
    mode: str,
    output_dir: Path,
    handoff_path: Path,
) -> dict[str, object]:
    """Resolve the opt-in approval gate verdict (critical issues require a
    human approve/reject decision artifact before the workflow may advance).

    Reuses ``_route_gate_verdict`` unchanged as the base verdict, then applies
    the approval decision table. A missing or invalid decision artifact
    produces a blocked verdict (never a hard raise) so ``--json`` always emits
    the uniform approval-gate contract.
    """
    base = _route_gate_verdict(
        mode=mode,
        output_dir=output_dir,
        handoff_path=handoff_path,
    )
    packet = _load_route_handoff_packet(handoff_path)
    package = (
        SerializationBoundaryUnit().load(base["package_path"])
        if base["package_present"]
        else None
    )
    critical_ids = critical_review_issue_ids(packet, package)
    blocking_ids = blocking_review_issue_ids(packet, package)

    decision_path = output_dir / APPROVAL_DECISION_FILE
    decision = None
    decision_error: str | None = None
    # A missing artifact is the ordinary "require operator approval" case
    # (decision-table row B), so only attempt to load when the file exists.
    # A present-but-invalid artifact routes to the decision_error branch.
    if critical_ids and decision_path.is_file():
        try:
            decision = load_approval_decision(decision_path)
        except ValueError as exc:
            decision_error = str(exc)

    if decision_error is not None:
        return {
            **base,
            "approval_required": True,
            "critical_issue_ids": critical_ids,
            "approval_decision": "-",
            "approval_ok": False,
            "ok": False,
            "next_workflow": base["next_workflow"],
            "violations": [f"approval gate: {decision_error}"],
            "approval_decision_path": str(decision_path),
            "approval_decision_present": False,
        }

    resolved = resolve_approval_gate_verdict(
        critical_issue_ids=critical_ids,
        blocking_issue_ids=blocking_ids,
        decision=decision,
        base_ok=base["ok"],
        base_violations=base["violations"],
        review_route=base["review_route"],
        next_workflow=base["next_workflow"],
    )
    return {
        **base,
        **resolved,
        "approval_decision_path": str(decision_path),
        "approval_decision_present": decision is not None,
    }


def _gate_json_payload(
    verdict: dict[str, object],
    args: argparse.Namespace,
    mode: str,
) -> dict[str, object]:
    """Build the 13-field standard gate JSON payload."""
    return {
        "command": "gate",
        "novel": args.novel,
        "mode": mode,
        "ok": verdict["ok"],
        "schema_version": JSON_SCHEMA_VERSION,
        "review_route": verdict["review_route"],
        "next_workflow": verdict["next_workflow"],
        "violations": verdict["violations"],
        "handoff_path": str(verdict["handoff_path"]),
        "package_path": str(verdict["package_path"]),
        "package_present": verdict["package_present"],
        "blocking_pending_count": verdict["blocking_pending_count"],
        "blocking_pending_prompt_files": verdict["blocking_pending_prompt_files"],
    }


def _approval_gate_json_payload(
    verdict: dict[str, object],
    args: argparse.Namespace,
    mode: str,
) -> dict[str, object]:
    """Build the 17-field approval gate JSON payload.

    The 13 standard fields are a verbatim prefix (``_gate_json_payload``);
    the four approval fields are appended. Approve-override verdicts already
    carry approval_required/critical_issue_ids/approval_decision/approval_ok.
    """
    payload = _gate_json_payload(verdict, args, mode)
    payload["approval_required"] = verdict["approval_required"]
    payload["critical_issue_ids"] = verdict["critical_issue_ids"]
    payload["approval_decision"] = verdict["approval_decision"]
    payload["approval_ok"] = verdict["approval_ok"]
    return payload


def _run_gate(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")
    output_dir = _output_dir(novel_dir, mode)
    handoff_path = output_dir / ROUTE_HANDOFF_FILE
    if not handoff_path.exists():
        raise ValueError(f"missing route handoff: {handoff_path}")

    require_approval = bool(getattr(args, "require_approval", False))
    if require_approval:
        verdict = _approval_gate_verdict(
            mode=mode,
            output_dir=output_dir,
            handoff_path=handoff_path,
        )
    else:
        verdict = _route_gate_verdict(
            mode=mode,
            output_dir=output_dir,
            handoff_path=handoff_path,
        )

    if args.json:
        if require_approval:
            payload = _approval_gate_json_payload(verdict, args, mode)
            _validate_approval_gate_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if verdict["ok"] else 1
        else:
            payload = _gate_json_payload(verdict, args, mode)
            _validate_gate_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if verdict["ok"] else 1

    if not verdict["ok"]:
        print("Gate failed:")
        for violation in verdict["violations"]:
            print(f"  - {violation}")
        return 1

    approval_suffix = ""
    if require_approval:
        approval_suffix = f" approval={verdict['approval_decision']}"
    print(
        f"Gate PASS: mode={mode} route={verdict['review_route']} "
        f"next={verdict['next_workflow']}{approval_suffix}"
    )
    return 0


def _gate_metadata(mode: str, output_dir: Path, handoff_path: Path) -> dict[str, object]:
    verdict = _route_gate_verdict(
        mode=mode,
        output_dir=output_dir,
        handoff_path=handoff_path,
    )
    return {
        "gate_ok": verdict["ok"],
        "gate_violations": verdict["violations"],
        "gate_package_file": Path(verdict["package_path"]).name,
        "gate_package_path": str(verdict["package_path"]),
        "gate_package_present": verdict["package_present"],
        "gate_blocking_pending_count": verdict["blocking_pending_count"],
        "gate_blocking_pending_prompt_files": verdict[
            "blocking_pending_prompt_files"
        ],
    }


def _empty_status_metadata() -> dict[str, object]:
    metadata = {
        "route": None,
        "next_workflow": None,
        "gate_ok": None,
        "gate_violations": [],
        "gate_package_file": None,
        "gate_package_path": None,
        "gate_package_present": None,
        "gate_blocking_pending_count": None,
        "gate_blocking_pending_prompt_files": [],
        "pending_count": 0,
        "pending_prompt_file": None,
        "pending_response_file": None,
        "pending_prompt_path": None,
        "pending_response_path": None,
        "pending_prompt_hash": None,
        "pending_prompt_bytes": None,
        "pending_prompt_mtime": None,
        "pending_slot_id": None,
        **pending_automation_metadata(pending_count=0),
        "final_result_file": None,
        "final_result_path": None,
        "route_handoff_file": None,
        "route_handoff_path": None,
    }
    validate_pending_automation_metadata_in_payload(
        metadata,
        pending_count=0,
    )
    return metadata


def _status_for(novel_dir: Path) -> tuple[str, str, str, dict[str, object]]:
    mode = _read_mode(novel_dir) or "unknown"
    output_dir = _output_dir(novel_dir, mode)
    final = _final_route_path(mode, output_dir)
    handoff = _route_handoff_path(output_dir)
    metadata = _empty_status_metadata()
    if output_dir.exists():
        latest_final = _latest_route_artifact_mtime(mode, output_dir)
        slots = _waiting_slots(
            output_dir,
            newer_than=latest_final,
        )
        if slots:
            first_slot = slots[0]
            metadata.update(
                {
                    "pending_count": len(slots),
                    "pending_prompt_file": first_slot.prompt_path.name,
                    "pending_response_file": first_slot.response_path.name,
                    "pending_prompt_path": str(first_slot.prompt_path),
                    "pending_response_path": str(first_slot.response_path),
                    "pending_prompt_hash": first_slot.prompt_hash,
                    "pending_prompt_bytes": first_slot.prompt_bytes,
                    "pending_prompt_mtime": first_slot.prompt_mtime,
                    "pending_slot_id": first_slot.slot_id,
                    **pending_automation_metadata(pending_count=len(slots)),
                }
            )
            validate_pending_automation_metadata_in_payload(
                metadata,
                pending_count=len(slots),
            )
            return (
                mode,
                "waiting",
                f"[WAITING: {first_slot.response_path.name}]",
                metadata,
            )
    if handoff and not final:
        raise ValueError(
            f"route handoff exists without final result: {handoff[0]}"
        )
    if final:
        final_path, _ = final
        route, detail, next_workflow = _route_detail(final_path, handoff)
        metadata["route"] = route
        metadata["next_workflow"] = next_workflow
        metadata["final_result_file"] = final_path.name
        metadata["final_result_path"] = str(final_path)
        if handoff:
            handoff_path, _ = handoff
            metadata["route_handoff_file"] = handoff_path.name
            metadata["route_handoff_path"] = str(handoff_path)
            metadata.update(_gate_metadata(mode, output_dir, handoff_path))
        if mode in {"extend", "compose"} and route != "pass":
            status = "blocked" if route == "block" else "rewrite"
            return mode, status, detail, metadata
        return mode, "completed", detail, metadata
    return mode, "initialized", "-", metadata


def _time_status_detail(novel_dir: Path) -> str:
    """每部小说当前叙事时间状态（无 TimeBook → 未设定）.

    时间域为横向域，独立于 mode.txt；list 行用它展示时间线准星。
    """
    from src.workflow_action.timebook import load_time_book

    tb = load_time_book(_output_dir(novel_dir, "time"))
    if tb is None:
        return "未设定"
    latest = tb.latest_anchor()
    if latest is not None:
        bits = [b for b in (latest.chapter, latest.date, latest.lunar, latest.tod, latest.loc) if b]
        return " ".join(bits)
    if tb.initial is not None and not tb.initial.is_empty():
        bits = [b for b in (tb.initial.date, tb.initial.lunar, tb.initial.loc) if b]
        return "起点 " + " ".join(bits)
    return "存在"


def _run_list(args: argparse.Namespace) -> int:
    root = _novels_root()
    if not root.exists():
        if args.json:
            _validate_list_json_payload([])
            print("[]")
        return 0
    rows = []
    for novel_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        mode, status, detail, metadata = _status_for(novel_dir)
        latest_mtime = _latest_mtime(novel_dir)
        latest_date = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d")
        rows.append(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "command": "list",
                "name": novel_dir.name,
                "mode": mode,
                "status": status,
                "detail": detail,
                "latest_date": latest_date,
                "latest_mtime": latest_mtime,
                **metadata,
                "time_status": _time_status_detail(novel_dir),
            }
        )
    if args.json:
        _validate_list_json_payload(rows)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        print(
            f"{row['name']}\t{row['mode']}\t{row['status']}\t"
            f"{row['detail']}\t{row['latest_date']}"
        )
    return 0


def _latest_route_artifact_mtime(mode: str, output_dir: Path) -> float | None:
    final = _final_route_path(mode, output_dir)
    handoff = _route_handoff_path(output_dir)
    mtimes = []
    if handoff and not final:
        raise ValueError(
            f"route handoff exists without final result: {handoff[0]}"
        )
    if final:
        final_path, _mtime = final
        _route_detail(final_path, handoff)
        mtimes.append(final[1])
    if handoff:
        mtimes.append(handoff[1])
    if not mtimes:
        return None
    return max(mtimes)


def _effective_pending_newer_than(
    *,
    requested_newer_than: float | None,
    artifact_cutoff: float | None,
) -> float | None:
    if artifact_cutoff is None:
        return requested_newer_than
    if requested_newer_than is None:
        return artifact_cutoff
    return max(requested_newer_than, artifact_cutoff)


def _run_pending(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")

    output_dir = _output_dir(novel_dir, mode)
    boundary = ResponseFileBoundaryUnit()
    artifact_cutoff = _latest_route_artifact_mtime(mode, output_dir)
    effective_newer_than = _effective_pending_newer_than(
        requested_newer_than=args.newer_than,
        artifact_cutoff=artifact_cutoff,
    )
    if args.prompt_hash and not args.slot_id:
        raise ValueError("--prompt-hash requires --slot-id for pending verification")
    if args.slot_id:
        selection_method = "slot_id"
        slots = [
            boundary.require_pending_slot(
                output_dir,
                slot_id=args.slot_id,
                newer_than=effective_newer_than,
                expected_prompt_hash=args.prompt_hash,
            )
        ]
    else:
        selection_method = "all_pending"
        slots = boundary.discover_pending_slots(
            output_dir,
            newer_than=effective_newer_than,
        )
    automation_metadata = pending_automation_metadata(pending_count=len(slots))
    validate_pending_automation_metadata_in_payload(
        automation_metadata,
        pending_count=len(slots),
    )
    pending_entries = [
        {
            "prompt_file": slot.prompt_path.name,
            "response_file": slot.response_path.name,
            "prompt_path": str(slot.prompt_path),
            "response_path": str(slot.response_path),
            "prompt_mtime": slot.prompt_mtime,
            "prompt_hash": slot.prompt_hash,
            "prompt_bytes": slot.prompt_bytes,
            "slot_id": slot.slot_id,
        }
        for slot in slots
    ]
    if args.require_automation_ready and not automation_metadata["automation_ready"]:
        error = (
            "pending slot is not automation ready: "
            f"{automation_metadata['automation_ready_reason']}"
        )
        if args.json:
            payload = {
                "ok": False,
                "schema_version": JSON_SCHEMA_VERSION,
                "command": "pending",
                "novel": args.novel,
                "mode": mode,
                "output_dir": str(output_dir),
                "slot_id": args.slot_id,
                "selection_method": selection_method,
                "newer_than": args.newer_than,
                "effective_newer_than": effective_newer_than,
                "route_artifact_mtime": artifact_cutoff,
                "expected_prompt_hash": args.prompt_hash,
                "prompt_hash_verified": args.prompt_hash is not None,
                "pending_count": len(slots),
                **automation_metadata,
                "pending": pending_entries,
                "error_stage": "runtime",
                "error_type": "ValueError",
                "error": error,
            }
            _validate_pending_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        raise ValueError(error)
    if args.json:
        payload = {
            "ok": True,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": "pending",
            "novel": args.novel,
            "mode": mode,
            "output_dir": str(output_dir),
            "slot_id": args.slot_id,
            "selection_method": selection_method,
            "newer_than": args.newer_than,
            "effective_newer_than": effective_newer_than,
            "route_artifact_mtime": artifact_cutoff,
            "expected_prompt_hash": args.prompt_hash,
            "prompt_hash_verified": args.prompt_hash is not None,
            "pending_count": len(slots),
            **automation_metadata,
            "pending": pending_entries,
        }
        _validate_pending_json_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not slots:
        print(f"No pending response slots: mode={mode}")
        return 0

    for slot in slots:
        print(f"{mode}\t{slot.prompt_path.name}\t{slot.response_path.name}")
    return 0


def _prompt_filename(name: str) -> str:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
        raise ValueError(f"invalid prompt filename: {name}")
    if not name.endswith("_prompt.txt"):
        raise ValueError(f"prompt filename must end with _prompt.txt: {name}")
    return name


def _pending_slot_for_prompt(output_dir: Path, prompt_name: str):
    boundary = ResponseFileBoundaryUnit()
    prompt_path = output_dir / _prompt_filename(prompt_name)
    response_path = boundary.expected_response_path(prompt_path)
    boundary.verify_response_slot(prompt_path=prompt_path, response_path=response_path)
    return prompt_path, response_path


def _verify_prompt_after_cutoff(
    prompt_path: Path,
    cutoff: float | None,
) -> None:
    if cutoff is None:
        return
    prompt_mtime = Path(prompt_path).stat().st_mtime
    if prompt_mtime <= cutoff:
        raise ValueError(
            f"pending prompt is older than current route artifact: {prompt_path}"
        )


def _pending_slot_for_slot_id(
    output_dir: Path,
    slot_id: str,
    *,
    newer_than: float | None = None,
):
    boundary = ResponseFileBoundaryUnit()
    if newer_than is None:
        slot = boundary.require_pending_slot(output_dir, slot_id=slot_id)
    else:
        slot = boundary.require_pending_slot(
            output_dir,
            slot_id=slot_id,
            newer_than=newer_than,
        )
    return slot.prompt_path, slot.response_path


def _run_respond(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")

    response_source = Path(args.response_file).resolve()
    if not response_source.exists() or not response_source.is_file():
        raise FileNotFoundError(f"response source file not found: {args.response_file}")

    output_dir = _output_dir(novel_dir, mode)
    boundary = ResponseFileBoundaryUnit()
    artifact_cutoff = _latest_route_artifact_mtime(mode, output_dir)
    effective_newer_than = _effective_pending_newer_than(
        requested_newer_than=None,
        artifact_cutoff=artifact_cutoff,
    )
    slot_id = getattr(args, "slot_id", None)
    if args.prompt and slot_id:
        raise ValueError("--prompt and --slot-id cannot be used together")
    if slot_id:
        selection_method = "slot_id"
        prompt_path, response_path = _pending_slot_for_slot_id(
            output_dir,
            slot_id,
            newer_than=effective_newer_than,
        )
    elif args.prompt:
        selection_method = "prompt_file"
        prompt_path, response_path = _pending_slot_for_prompt(output_dir, args.prompt)
        _verify_prompt_after_cutoff(prompt_path, effective_newer_than)
    else:
        selection_method = "single_pending"
        if effective_newer_than is None:
            slot = boundary.require_single_pending_slot(output_dir)
        else:
            slot = boundary.require_single_pending_slot(
                output_dir,
                newer_than=effective_newer_than,
            )
        prompt_path = slot.prompt_path
        response_path = slot.response_path

    if _is_same_existing_file(response_source, prompt_path):
        raise ValueError("response source file must not be the staged prompt file")
    if _is_same_existing_file(response_source, response_path):
        raise ValueError("response source file must not be the staged response file")

    prompt_hash = boundary.verify_prompt_hash(prompt_path, args.prompt_hash)
    response_text, response_source_hash, response_source_bytes = _read_text_with_hash(
        response_source
    )
    boundary.materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text=response_text,
        expected_prompt_hash=prompt_hash,
    )
    prompt_evidence = file_content_evidence(prompt_path)
    if prompt_evidence.content_hash != prompt_hash:
        raise ValueError(
            f"prompt hash mismatch for {prompt_path}: "
            f"expected {prompt_hash}, actual {prompt_evidence.content_hash}"
        )
    response_bytes = response_text.encode("utf-8")
    expected_response_hash = hashlib.md5(response_bytes).hexdigest()
    response_hash = file_content_hash(response_path)
    if response_hash != expected_response_hash:
        raise ValueError(
            f"staged response hash mismatch for {response_path}: "
            f"expected {expected_response_hash}, actual {response_hash}"
        )
    if args.json:
        payload = {
            "ok": True,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": "respond",
            "novel": args.novel,
            "mode": mode,
            "prompt_file": prompt_path.name,
            "response_file": response_path.name,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "response_source": str(response_source),
            **response_materialization_metadata(),
            "selection_method": selection_method,
            "route_artifact_mtime": artifact_cutoff,
            "effective_newer_than": effective_newer_than,
            "expected_prompt_hash": args.prompt_hash,
            "prompt_hash_verified": args.prompt_hash is not None,
            "prompt_hash": prompt_hash,
            "prompt_bytes": prompt_evidence.byte_count,
            "slot_id": staged_slot_id(prompt_path),
            "response_source_hash": response_source_hash,
            "response_source_bytes": response_source_bytes,
            "response_hash": response_hash,
            "response_bytes": len(response_bytes),
            "response_chars": len(response_text),
        }
        _validate_respond_json_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Response saved: mode={mode} prompt={prompt_path.name} response={response_path.name}")
    return 0


def _add_input_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", help="原始文本路径；会复制到 novels/<小说名>/input.txt")


def _add_long_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chapter-wise", action="store_true", help="强制启用章节级处理")
    parser.add_argument("--range", dest="chapter_range", metavar="START-END", help="处理指定章节范围")
    parser.add_argument("--batch-size", type=int, help="每批处理章节数")
    parser.add_argument("--max-chapters", type=int, help="无 --range 时的最大允许章节数")


def build_parser(*, emit_json_errors: bool = False) -> argparse.ArgumentParser:
    parser = NovelArgumentParser(
        description="统一小说工作流入口",
        emit_json_errors=emit_json_errors,
    )
    parser_factory = lambda *args, **kwargs: NovelArgumentParser(
        *args,
        emit_json_errors=emit_json_errors,
        **kwargs,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=parser_factory,
    )

    audit = subparsers.add_parser("audit", help="审核已有小说")
    audit.add_argument("novel", help="小说名")
    _add_input_argument(audit)
    _add_long_arguments(audit)
    audit.add_argument("--format", choices=["json", "markdown"], default="json", help="审核报告格式")
    audit.add_argument("--outline-only", action="store_true", help="只生成结构概览")
    audit.set_defaults(func=_run_audit)

    extend = subparsers.add_parser("extend", help="续写已有小说")
    extend.add_argument("novel", help="小说名")
    _add_input_argument(extend)
    _add_long_arguments(extend)
    extend.add_argument("--style", help="引用风格库中的已有档案 <name>，注入续写 prompt")
    extend.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；无风格档案时注入气质桶指导",
    )
    extend.add_argument(
        "--retrieval",
        choices=["on", "off"],
        default="on",
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
    )
    extend.add_argument(
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构）",
    )
    extend.set_defaults(func=_run_extend)

    compose = subparsers.add_parser("compose", help="从 WorkSpec 创作")
    compose.add_argument("novel", help="小说名")
    compose.add_argument("--workspec", help="WorkSpec JSON 文件路径")
    compose.add_argument("--style", help="引用风格库中的已有档案 <name>，注入续写 prompt")
    compose.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；CLI 优先，缺省回落到 workspec.temperament",
    )
    compose.add_argument(
        "--retrieval",
        choices=["on", "off"],
        default="on",
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
    )
    compose.add_argument(
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构）",
    )
    compose.set_defaults(func=_run_compose)

    style = subparsers.add_parser("style", help="从已有小说文本提炼写作风格档案")
    style.add_argument("novel", help="小说名")
    _add_input_argument(style)
    style.add_argument("--tone", help="调性提示词（如 克制）")
    style.add_argument("--genre", help="类型提示词（如 仙侠）")
    style.add_argument("--lint", action="store_true", help="对全文做 AI 味 lint")
    style.add_argument("--name", help="另存到风格库 style_library/<name>.json（可跨小说复用）")
    style.add_argument("--style", help="引用风格库中的已有档案 <name>，跳过提炼")
    style.add_argument(
        "--force",
        action="store_true",
        help="入库时忽略相似度去重提示，强制新建档案",
    )
    style.add_argument(
        "--no-library",
        action="store_true",
        help="提炼结果不写入风格库（跳过自动入库）",
    )
    style.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型），透传给风格提炼作为先验",
    )
    style.add_argument(
        "--style-search",
        metavar="QUERY",
        help="在风格库 manifest 上检索候选 id（支持 '要素:手法' 如 人物:衬托），列出后退出",
    )
    style.set_defaults(func=_run_style)

    compliance = subparsers.add_parser("compliance", help="内容合规模块：扫敏感词 + 平台政策")
    compliance.add_argument("novel", help="小说名")
    _add_input_argument(compliance)
    compliance.add_argument("--platform", default="通用", help="目标平台（默认 通用）")
    compliance.add_argument(
        "--sensitive",
        default="on",
        choices=["on", "off"],
        help="敏感词扫描开关（默认 on；off 时跳过词库扫描，平台政策检查仍跑）",
    )
    compliance.add_argument("--lexicon", help="自定义词库 JSON 文件路径（与内置词库合并）")
    compliance.set_defaults(func=_run_compliance)

    rubric = subparsers.add_parser("rubric", help="导出 WebNovelBench 8 维本地评测 rubric (离线)")
    rubric.add_argument("novel", help="小说名（rubric 为全局知识，novel 仅作容器）")
    rubric.set_defaults(func=_run_rubric)

    time_cmd = subparsers.add_parser("time", help="时间域模块：TimeBook 管理 + 时间审计")
    time_cmd.add_argument("novel", help="小说名")
    _add_input_argument(time_cmd)
    time_cmd.add_argument("--rebuild", action="store_true", help="从正文提取锚点并校准 TimeBook")
    time_cmd.add_argument("--check", action="store_true", help="运行时间审计，产出 timeline_report.json")
    time_cmd.add_argument("--status", action="store_true", help="打印 TimeBook 状态（默认动作）")
    time_cmd.set_defaults(func=_run_time)

    resume = subparsers.add_parser("resume", help="按上次模式断点续跑")
    resume.add_argument("novel", help="小说名")
    resume.set_defaults(func=_run_resume)

    list_cmd = subparsers.add_parser("list", help="查看所有小说任务")
    list_cmd.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    list_cmd.set_defaults(func=_run_list)

    pending = subparsers.add_parser("pending", help="list pending response slots")
    pending.add_argument("novel", help="novel name")
    pending.add_argument("--slot-id", help="select one pending staged slot id")
    pending.add_argument("--newer-than", type=float, help="only list prompts newer than this timestamp")
    pending.add_argument("--prompt-hash", help="expected pending prompt content hash")
    pending.add_argument("--require-automation-ready", action="store_true", help="fail unless exactly one staged slot is ready for automation preflight")
    pending.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    pending.set_defaults(func=_run_pending)

    respond = subparsers.add_parser("respond", help="materialize a staged response file")
    respond.add_argument("novel", help="novel name")
    respond.add_argument("--response-file", required=True, help="raw response text file")
    respond.add_argument("--prompt", help="pending prompt filename when multiple slots exist")
    respond.add_argument("--slot-id", help="pending staged slot id when multiple slots exist")
    respond.add_argument("--prompt-hash", help="expected pending prompt content hash")
    respond.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    respond.set_defaults(func=_run_respond)

    gate = subparsers.add_parser("gate", help="verify route handoff gate")
    gate.add_argument("novel", help="novel name")
    gate.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    gate.add_argument(
        "--require-approval",
        action="store_true",
        help="fail unless all open critical review issues are operator-approved "
        "(approval_decision.json)",
    )
    gate.set_defaults(func=_run_gate)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(emit_json_errors="--json" in raw_argv)
    args = parser.parse_args(raw_argv)
    try:
        return args.func(args)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        if getattr(args, "json", False):
            payload = _json_error_payload(
                error_stage="runtime",
                error_type=type(exc).__name__,
                error=str(exc),
                command=getattr(args, "command", None),
                novel=getattr(args, "novel", None),
                include_runtime_context=True,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
