"""Tier 0 release record validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.boundary_control.handoff import HandoffBoundaryUnit, HandoffPacket
from src.boundary_control.review_object_contracts import (
    review_issue_from_payload,
    review_reminder_from_payload,
)
from src.boundary_control.serialization import (
    SerializationBoundaryUnit,
    SerializationPackage,
)
from src.object_state.audit_report import AuditReport

TIER0_RELEASE_RECORD_SCHEMA_VERSION = 1
TIER0_RELEASE_RECORD_TYPE = "tier0_release_record"
TIER0_CANARY_EVIDENCE_TYPE = "tier0_canary_evidence"
TIER0_PRODUCTION_TIER = "local_staged_cli_v0"
TIER0_CANARY_RUNBOOK = "docs/00_project/31_tier0_canary_runbook.md"
TIER0_CANARY_WORKSPACE = "novels/tier0-canary"
TIER0_STAGED_RUNTIME = "FileExchangeInterface"
TIER0_RELEASE_RECORD_FIELDS = (
    "schema_version",
    "type",
    "production_tier",
    "release_id",
    "created_at_utc",
    "release_tag_or_checkpoint",
    "git_commit",
    "baseline_tests_passing",
    "full_pytest_command",
    "full_pytest_result",
    "canary_runbook",
    "canary_result",
    "canary_commands",
    "staged_runtime",
    "directapi_provider_calling",
    "provider_calls_implemented",
    "closed_loop_allowed",
    "provider_call_performed",
    "closed_loop_advanced",
    "known_limitations",
    "evidence_paths",
)
TIER0_CANARY_EVIDENCE_FIELDS = (
    "schema_version",
    "type",
    "release_id",
    "canary_result",
    "canary_commands",
    "workspace_path",
    "final_artifact_paths",
    "final_artifact_sha256",
    "gate_result_path",
    "gate_result_sha256",
    "final_gate_ok",
    "final_review_route",
    "final_next_workflow",
    "blocking_pending_count",
    "directapi_provider_calling",
    "provider_calls_implemented",
    "closed_loop_allowed",
    "provider_call_performed",
    "closed_loop_advanced",
    "materialized_actions",
)
TIER0_REQUIRED_CANARY_COMMANDS = (
    "novel audit tier0-canary --input canary_input.txt",
    "novel pending tier0-canary --require-automation-ready --json",
    "novel respond tier0-canary --slot-id rebuild --prompt-hash <rebuild_prompt_hash> --response-file canary_rebuild_response.json --json",
    "novel resume tier0-canary",
    "novel pending tier0-canary --require-automation-ready --json",
    "novel respond tier0-canary --slot-id review --prompt-hash <review_prompt_hash> --response-file canary_review_response.json --json",
    "novel resume tier0-canary",
    "novel gate tier0-canary --json",
)
TIER0_REQUIRED_LIMITATIONS = (
    "DirectAPI provider calling is not implemented",
    "closed-loop automation remains disallowed",
    "Tier 0 is not a public product surface",
    "release record does not replace a release tag or immutable checkpoint",
)
TIER0_REQUIRED_EVIDENCE_PATHS = (
    "docs/00_project/30_production_readiness_checklist.md",
    "docs/00_project/31_tier0_canary_runbook.md",
)
TIER0_REQUIRED_CANARY_ARTIFACT_NAMES = (
    "audit_report.json",
    "review_result.json",
    "route_handoff.json",
    "rebuild_package.json",
)
TIER0_REQUIRED_MATERIALIZED_ACTIONS = (
    "materialize_staged_response_only",
    "materialize_staged_response_only",
)
TIER0_FALSE_CLAIM_FIELDS = (
    "directapi_provider_calling",
    "provider_calls_implemented",
    "closed_loop_allowed",
    "provider_call_performed",
    "closed_loop_advanced",
)
TIER0_GENERATE_REQUIRED_FIELDS = (
    "release_id",
    "created_at_utc",
    "release_tag_or_checkpoint",
    "git_commit",
    "full_pytest_command",
)
TIER0_CANARY_GENERATE_REQUIRED_FIELDS = (
    "release_id",
    "canary_workspace",
    "canary_gate_result",
)
TIER0_CREATED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIER0_GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TIER0_RELEASE_ID_PATTERN = re.compile(r"^tier0-canary-(\d{8})$")
TIER0_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIER0_FULL_PYTEST_COMMAND_PREFIX = ("python", "-m", "pytest", "-q")
TIER0_FULL_PYTEST_BASETEMP_PREFIX = ".pytest-tmp-current-tier0-release-"
TIER0_FULL_PYTEST_BASETEMP_PATTERN = re.compile(
    r"^\.pytest-tmp-current-tier0-release-[A-Za-z0-9][A-Za-z0-9._-]*$"
)
TIER0_FULL_PYTEST_COMMAND_SUFFIX = ("-p", "no:cacheprovider")


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} entries must be non-empty strings")
    return value


def _require_unique_string_list(value: object, label: str) -> list[str]:
    items = _require_string_list(value, label)
    if len(set(items)) != len(items):
        raise ValueError(f"{label} entries must be unique")
    return items


def _require_subsequence_order(
    items: list[str],
    ordered_items: list[str],
    label: str,
) -> None:
    positions = [items.index(item) for item in ordered_items]
    if positions != sorted(positions):
        raise ValueError(f"{label} must keep required evidence path order")


def _require_sha256_map(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{label} keys must be non-empty strings")
    for key, item in value.items():
        if not isinstance(item, str) or TIER0_SHA256_PATTERN.fullmatch(item) is None:
            raise ValueError(
                f"{label} entries must be lowercase 64-character sha256 hex strings"
            )
    return value


def _require_utc_timestamp(value: object, label: str) -> str:
    text = _require_non_empty_string(value, label)
    try:
        datetime.strptime(text, TIER0_CREATED_AT_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be a UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format"
        ) from exc
    return text


def _require_release_id(value: object, label: str) -> str:
    text = _require_non_empty_string(value, label)
    match = TIER0_RELEASE_ID_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"{label} must use tier0-canary-YYYYMMDD format")
    try:
        datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{label} must contain a valid YYYYMMDD date") from exc
    return text


def _require_release_id_matches_created_at(release_id: str, created_at_utc: str) -> None:
    release_date = release_id.removeprefix("tier0-canary-")
    created_date = datetime.strptime(created_at_utc, TIER0_CREATED_AT_FORMAT).strftime(
        "%Y%m%d"
    )
    if release_date != created_date:
        raise ValueError(
            "Tier 0 release record release_id date must match created_at_utc date"
        )


def _require_git_commit_hash(value: object, label: str) -> str:
    text = _require_non_empty_string(value, label)
    if TIER0_GIT_COMMIT_PATTERN.fullmatch(text) is None:
        raise ValueError(
            f"{label} must be a 40-character lowercase hexadecimal git commit hash"
        )
    return text


def _require_full_pytest_command(value: object, label: str) -> str:
    text = _require_non_empty_string(value, label)
    tokens = shlex.split(text)
    if (
        len(tokens) != 8
        or tuple(tokens[:4]) != TIER0_FULL_PYTEST_COMMAND_PREFIX
        or tokens[4] != "--basetemp"
        or TIER0_FULL_PYTEST_BASETEMP_PATTERN.fullmatch(tokens[5]) is None
        or tuple(tokens[6:]) != TIER0_FULL_PYTEST_COMMAND_SUFFIX
    ):
        raise ValueError(
            f"{label} must be a full pytest command: "
            "python -m pytest -q --basetemp "
            f"{TIER0_FULL_PYTEST_BASETEMP_PREFIX}<name> -p no:cacheprovider"
        )
    return text


def _git_commit_exists(commit_hash: str, repo_root: str | Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{commit_hash}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _git_tag_commit(tag_name: str, repo_root: str | Path) -> str | None:
    tag_ref = tag_name if tag_name.startswith("refs/tags/") else f"refs/tags/{tag_name}"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", f"{tag_ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    if TIER0_GIT_COMMIT_PATTERN.fullmatch(resolved) is None:
        return None
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{label} JSON object keys must be strings")
    return payload


def _validate_review_result_artifact(payload: dict[str, Any], label: str) -> None:
    expected_fields = {"issues", "reminders", "route"}
    keys = set(payload)
    missing = sorted(expected_fields - keys)
    if missing:
        raise ValueError(f"{label} missing review result field(s): {', '.join(missing)}")
    unknown = sorted(keys - expected_fields)
    if unknown:
        raise ValueError(f"{label} unknown review result field(s): {', '.join(unknown)}")
    if not isinstance(payload["issues"], list):
        raise ValueError(f"{label} issues must be a list")
    if not isinstance(payload["reminders"], list):
        raise ValueError(f"{label} reminders must be a list")
    for issue in payload["issues"]:
        review_issue_from_payload(issue)
    for reminder in payload["reminders"]:
        review_reminder_from_payload(reminder)
    if payload["route"] not in {"pass", "rewrite", "block"}:
        raise ValueError(f"{label} route must be pass, rewrite, or block")


def _resolve_artifact_ref(ref: str, root: Path) -> Path:
    ref_path = Path(ref)
    return (ref_path if ref_path.is_absolute() else root / ref_path).resolve()


def _normalize_json_path(path: str) -> str:
    return path.strip().replace("\\", "/").rstrip("/")


def _canary_artifact_ref(workspace_path: str, artifact_name: str) -> str:
    normalized_workspace = _normalize_json_path(workspace_path)
    return f"{normalized_workspace}/output/audit/{artifact_name}"


def _require_tier0_canary_workspace(value: object) -> str:
    normalized_workspace = _normalize_json_path(
        _require_non_empty_string(
            value,
            "Tier 0 canary evidence workspace_path",
        )
    )
    if normalized_workspace != TIER0_CANARY_WORKSPACE:
        raise ValueError(
            "Tier 0 canary evidence workspace_path must be "
            f"{TIER0_CANARY_WORKSPACE}"
        )
    return normalized_workspace


def _validate_final_artifact_shape(path: Path, artifact_name: str) -> dict[str, Any]:
    label = f"Tier 0 canary evidence {artifact_name}"
    payload = _read_json_object(path, label)
    try:
        if artifact_name == "audit_report.json":
            AuditReport.model_validate(payload)
            return payload
        if artifact_name == "review_result.json":
            _validate_review_result_artifact(payload, label)
            return payload
        if artifact_name == "route_handoff.json":
            packet = HandoffPacket.model_validate(payload)
            ok, violations = HandoffBoundaryUnit().verify(packet)
            if not ok:
                raise ValueError(
                    f"{label} handoff violations: {', '.join(violations)}"
                )
            return payload
        if artifact_name == "rebuild_package.json":
            package = SerializationPackage.model_validate(payload)
            violations = SerializationBoundaryUnit().check_separation(package)
            if violations:
                raise ValueError(
                    f"{label} serialization violations: {', '.join(violations)}"
                )
            SerializationBoundaryUnit().deserialize_package(package)
            return payload
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"{label} shape validation failed: {exc}") from exc
    raise ValueError(f"unsupported Tier 0 canary final artifact: {artifact_name}")


def _validate_canary_artifact_semantics(
    *,
    evidence: dict[str, object],
    artifact_payloads: dict[str, dict[str, Any]],
    artifact_paths: dict[str, Path],
    root: Path,
) -> None:
    required_names = set(TIER0_REQUIRED_CANARY_ARTIFACT_NAMES)
    missing_payloads = sorted(required_names - set(artifact_payloads))
    if missing_payloads:
        raise ValueError(
            "Tier 0 canary evidence missing final artifact payload(s): "
            f"{', '.join(missing_payloads)}"
        )

    audit_report = artifact_payloads["audit_report.json"]
    review_result = artifact_payloads["review_result.json"]
    route_handoff = artifact_payloads["route_handoff.json"]
    rebuild_package = artifact_payloads["rebuild_package.json"]

    route = review_result["route"]
    if audit_report["route"] != route:
        raise ValueError(
            "Tier 0 canary evidence audit_report.route must match review_result.route"
        )
    if evidence["final_review_route"] != route:
        raise ValueError(
            "Tier 0 canary evidence final_review_route must match review_result.route"
        )

    next_route = route_handoff["next_route"]
    if next_route["review_route"] != route:
        raise ValueError(
            "Tier 0 canary evidence route_handoff review_route must match "
            "review_result.route"
        )
    if next_route["recommended_workflow"] != evidence["final_next_workflow"]:
        raise ValueError(
            "Tier 0 canary evidence route_handoff recommended_workflow must match "
            "final_next_workflow"
        )

    input_anchor = route_handoff["input_anchor"]
    review_target_ref = input_anchor["review_target_ref"]
    if _resolve_artifact_ref(review_target_ref, root) != artifact_paths[
        "review_result.json"
    ]:
        raise ValueError(
            "Tier 0 canary evidence route_handoff input_anchor.review_target_ref "
            "must reference review_result.json"
        )

    output_anchor = route_handoff["output_anchor"]
    state_ref = output_anchor["state_ref"]
    narrative_state = audit_report.get("narrative_state")
    if narrative_state is None:
        raise ValueError(
            "Tier 0 canary evidence audit_report.narrative_state must be "
            "present for route_handoff state_ref validation"
        )
    if state_ref != narrative_state["state_id"]:
        raise ValueError(
            "Tier 0 canary evidence route_handoff output_anchor.state_ref must "
            "match audit_report.narrative_state.state_id"
        )

    if not rebuild_package.get("working_set"):
        raise ValueError(
            "Tier 0 canary evidence rebuild_package.json must include working_set "
            "state for the audited result"
        )


def _validate_canary_gate_result(
    payload: object,
    *,
    workspace_path: str,
    route_handoff_path: Path,
    package_path: Path,
    artifact_root: Path,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Tier 0 canary gate result must be a JSON object")
    expected_fields = (
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
    missing = [field for field in expected_fields if field not in payload]
    if missing:
        raise ValueError(
            "Tier 0 canary gate result missing field(s): "
            f"{', '.join(missing)}"
        )
    unknown = sorted(set(payload) - set(expected_fields))
    if unknown:
        raise ValueError(
            "Tier 0 canary gate result unknown field(s): "
            f"{', '.join(unknown)}"
        )
    if payload["command"] != "gate":
        raise ValueError("Tier 0 canary gate result command must be gate")
    expected_novel = _normalize_json_path(workspace_path).rsplit("/", 1)[-1]
    if payload["novel"] != expected_novel:
        raise ValueError(
            "Tier 0 canary gate result novel must match canary workspace name"
        )
    if payload["mode"] != "audit":
        raise ValueError("Tier 0 canary gate result mode must be audit")
    if payload["schema_version"] != 1:
        raise ValueError("Tier 0 canary gate result schema_version must be 1")
    if payload["ok"] is not True:
        raise ValueError("Tier 0 canary gate result ok must be true")
    if payload["review_route"] not in {"pass", "rewrite", "block"}:
        raise ValueError(
            "Tier 0 canary gate result review_route must be pass, rewrite, or block"
        )
    if not isinstance(payload["next_workflow"], str) or not payload[
        "next_workflow"
    ].strip():
        raise ValueError(
            "Tier 0 canary gate result next_workflow must be a non-empty string"
        )
    if payload["violations"] != []:
        raise ValueError("Tier 0 canary gate result violations must be empty")
    if payload["package_present"] is not True:
        raise ValueError("Tier 0 canary gate result package_present must be true")
    blocking_count = _require_non_negative_int(
        payload["blocking_pending_count"],
        "Tier 0 canary gate result blocking_pending_count",
    )
    prompt_files = _require_string_list(
        payload["blocking_pending_prompt_files"],
        "Tier 0 canary gate result blocking_pending_prompt_files",
    )
    if blocking_count != len(prompt_files):
        raise ValueError(
            "Tier 0 canary gate result blocking_pending_count must match "
            "blocking_pending_prompt_files"
        )
    if blocking_count != 0:
        raise ValueError("Tier 0 canary gate result blocking_pending_count must be 0")
    handoff_ref = _require_non_empty_string(
        payload["handoff_path"],
        "Tier 0 canary gate result handoff_path",
    )
    package_ref = _require_non_empty_string(
        payload["package_path"],
        "Tier 0 canary gate result package_path",
    )
    if _resolve_artifact_ref(handoff_ref, artifact_root) != route_handoff_path.resolve():
        raise ValueError(
            "Tier 0 canary gate result handoff_path must reference route_handoff.json"
        )
    if _resolve_artifact_ref(package_ref, artifact_root) != package_path.resolve():
        raise ValueError(
            "Tier 0 canary gate result package_path must reference rebuild_package.json"
        )
    return payload


def _validate_exact_fields(payload: dict[str, object]) -> None:
    keys = set(payload)
    expected = set(TIER0_RELEASE_RECORD_FIELDS)
    missing = [field for field in TIER0_RELEASE_RECORD_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"missing Tier 0 release record field(s): {', '.join(missing)}")
    unknown = sorted(keys - expected)
    if unknown:
        raise ValueError(f"unknown Tier 0 release record field(s): {', '.join(unknown)}")


def _validate_exact_canary_evidence_fields(payload: dict[str, object]) -> None:
    keys = set(payload)
    expected = set(TIER0_CANARY_EVIDENCE_FIELDS)
    missing = [field for field in TIER0_CANARY_EVIDENCE_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"missing Tier 0 canary evidence field(s): {', '.join(missing)}")
    unknown = sorted(keys - expected)
    if unknown:
        raise ValueError(f"unknown Tier 0 canary evidence field(s): {', '.join(unknown)}")


def _require_exact_bool(value: object, label: str, expected: bool) -> None:
    if value is not expected:
        literal = "true" if expected else "false"
        raise ValueError(f"{label} must be {literal}")


def _require_non_negative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def validate_tier0_release_record(
    payload: object,
    *,
    expected_baseline: int,
    record_path: str | None = None,
) -> dict[str, object]:
    """Validate a Tier 0 release record payload and return it unchanged."""

    if not isinstance(payload, dict):
        raise ValueError("Tier 0 release record payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("Tier 0 release record payload keys must be strings")
    _validate_exact_fields(payload)
    if (
        not isinstance(expected_baseline, int)
        or isinstance(expected_baseline, bool)
        or expected_baseline <= 0
    ):
        raise ValueError("expected_baseline must be a positive integer")
    if payload["schema_version"] != TIER0_RELEASE_RECORD_SCHEMA_VERSION:
        raise ValueError(
            "unsupported Tier 0 release record schema_version: "
            f"{payload['schema_version']}"
        )
    if payload["type"] != TIER0_RELEASE_RECORD_TYPE:
        raise ValueError(f"unsupported Tier 0 release record type: {payload['type']}")
    if payload["production_tier"] != TIER0_PRODUCTION_TIER:
        raise ValueError(
            "unsupported Tier 0 release record production_tier: "
            f"{payload['production_tier']}"
        )
    for field in (
        "release_id",
        "created_at_utc",
        "release_tag_or_checkpoint",
        "git_commit",
        "full_pytest_command",
    ):
        _require_non_empty_string(payload[field], f"Tier 0 release record {field}")
    release_id = _require_release_id(
        payload["release_id"],
        "Tier 0 release record release_id",
    )
    created_at_utc = _require_utc_timestamp(
        payload["created_at_utc"],
        "Tier 0 release record created_at_utc",
    )
    _require_release_id_matches_created_at(release_id, created_at_utc)
    _require_git_commit_hash(
        payload["git_commit"],
        "Tier 0 release record git_commit",
    )
    _require_full_pytest_command(
        payload["full_pytest_command"],
        "Tier 0 release record full_pytest_command",
    )
    if payload["baseline_tests_passing"] != expected_baseline:
        raise ValueError(
            "Tier 0 release record baseline_tests_passing must match expected "
            f"baseline {expected_baseline}"
        )
    expected_pytest_result = f"{expected_baseline} passed"
    if payload["full_pytest_result"] != expected_pytest_result:
        raise ValueError(
            "Tier 0 release record full_pytest_result must be "
            f"{expected_pytest_result}"
        )
    if payload["canary_runbook"] != TIER0_CANARY_RUNBOOK:
        raise ValueError(
            "Tier 0 release record canary_runbook must be "
            f"{TIER0_CANARY_RUNBOOK}"
        )
    if payload["canary_result"] != "pass":
        raise ValueError("Tier 0 release record canary_result must be pass")
    if tuple(payload["canary_commands"]) != TIER0_REQUIRED_CANARY_COMMANDS:
        raise ValueError("Tier 0 release record canary_commands must match runbook")
    if payload["staged_runtime"] != TIER0_STAGED_RUNTIME:
        raise ValueError(
            "Tier 0 release record staged_runtime must be "
            f"{TIER0_STAGED_RUNTIME}"
        )
    for field in TIER0_FALSE_CLAIM_FIELDS:
        if payload[field] is not False:
            raise ValueError(f"Tier 0 release record {field} must be false")
    limitations = set(
        _require_unique_string_list(
            payload["known_limitations"],
            "Tier 0 release record known_limitations",
        )
    )
    missing_limitations = [
        item for item in TIER0_REQUIRED_LIMITATIONS if item not in limitations
    ]
    if missing_limitations:
        raise ValueError(
            "Tier 0 release record missing required known limitation(s): "
            f"{', '.join(missing_limitations)}"
        )
    evidence_path_items = _require_unique_string_list(
        payload["evidence_paths"],
        "Tier 0 release record evidence_paths",
    )
    evidence_paths = set(evidence_path_items)
    record_path_text = None
    if record_path is not None:
        record_path_text = _require_non_empty_string(
            record_path,
            "Tier 0 release record path",
        )
    required_evidence_paths = list(TIER0_REQUIRED_EVIDENCE_PATHS)
    if record_path_text is not None:
        required_evidence_paths.append(record_path_text)
    missing_evidence_paths = [
        item for item in required_evidence_paths if item not in evidence_paths
    ]
    if missing_evidence_paths:
        raise ValueError(
            "Tier 0 release record missing required evidence path(s): "
            f"{', '.join(missing_evidence_paths)}"
        )
    _require_subsequence_order(
        evidence_path_items,
        list(TIER0_REQUIRED_EVIDENCE_PATHS),
        "Tier 0 release record evidence_paths",
    )
    if record_path_text is not None and evidence_path_items[-1] != record_path_text:
        raise ValueError(
            "Tier 0 release record evidence_paths record path must be final "
            "evidence path"
        )
    return payload


def validate_tier0_canary_evidence(payload: object) -> dict[str, object]:
    """Validate a Tier 0 canary evidence payload and return it unchanged."""

    if not isinstance(payload, dict):
        raise ValueError("Tier 0 canary evidence payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("Tier 0 canary evidence payload keys must be strings")
    _validate_exact_canary_evidence_fields(payload)
    if payload["schema_version"] != TIER0_RELEASE_RECORD_SCHEMA_VERSION:
        raise ValueError(
            "unsupported Tier 0 canary evidence schema_version: "
            f"{payload['schema_version']}"
        )
    if payload["type"] != TIER0_CANARY_EVIDENCE_TYPE:
        raise ValueError(f"unsupported Tier 0 canary evidence type: {payload['type']}")
    _require_release_id(payload["release_id"], "Tier 0 canary evidence release_id")
    if payload["canary_result"] != "pass":
        raise ValueError("Tier 0 canary evidence canary_result must be pass")
    if tuple(payload["canary_commands"]) != TIER0_REQUIRED_CANARY_COMMANDS:
        raise ValueError("Tier 0 canary evidence canary_commands must match runbook")
    normalized_workspace = _require_tier0_canary_workspace(
        payload["workspace_path"],
    )
    final_artifact_paths = _require_unique_string_list(
        payload["final_artifact_paths"],
        "Tier 0 canary evidence final_artifact_paths",
    )
    artifact_name_list = [Path(item).name for item in final_artifact_paths]
    if len(set(artifact_name_list)) != len(artifact_name_list):
        raise ValueError(
            "Tier 0 canary evidence final_artifact_paths artifact names "
            "must be unique"
        )
    artifact_names = set(artifact_name_list)
    missing_artifacts = [
        name for name in TIER0_REQUIRED_CANARY_ARTIFACT_NAMES if name not in artifact_names
    ]
    if missing_artifacts:
        raise ValueError(
            "Tier 0 canary evidence missing required artifact path(s): "
            f"{', '.join(missing_artifacts)}"
        )
    expected_artifact_paths = [
        _canary_artifact_ref(normalized_workspace, name)
        for name in TIER0_REQUIRED_CANARY_ARTIFACT_NAMES
    ]
    if final_artifact_paths != expected_artifact_paths:
        raise ValueError(
            "Tier 0 canary evidence final_artifact_paths must match "
            "ordered workspace output/audit final artifacts"
        )
    final_artifact_sha256 = _require_sha256_map(
        payload["final_artifact_sha256"],
        "Tier 0 canary evidence final_artifact_sha256",
    )
    artifact_path_set = set(final_artifact_paths)
    hash_path_set = set(final_artifact_sha256)
    missing_hashes = [
        item for item in final_artifact_paths if item not in final_artifact_sha256
    ]
    extra_hashes = sorted(hash_path_set - artifact_path_set)
    if missing_hashes:
        raise ValueError(
            "Tier 0 canary evidence final_artifact_sha256 missing path(s): "
            f"{', '.join(missing_hashes)}"
        )
    if extra_hashes:
        raise ValueError(
            "Tier 0 canary evidence final_artifact_sha256 unknown path(s): "
            f"{', '.join(extra_hashes)}"
        )
    _require_non_empty_string(
        payload["gate_result_path"],
        "Tier 0 canary evidence gate_result_path",
    )
    _require_sha256_map(
        {"gate_result_path": payload["gate_result_sha256"]},
        "Tier 0 canary evidence gate_result_sha256",
    )
    _require_exact_bool(
        payload["final_gate_ok"],
        "Tier 0 canary evidence final_gate_ok",
        True,
    )
    if payload["final_review_route"] != "pass":
        raise ValueError("Tier 0 canary evidence final_review_route must be pass")
    if payload["final_next_workflow"] != "ContinueUnit":
        raise ValueError(
            "Tier 0 canary evidence final_next_workflow must be ContinueUnit"
        )
    if (
        _require_non_negative_int(
            payload["blocking_pending_count"],
            "Tier 0 canary evidence blocking_pending_count",
        )
        != 0
    ):
        raise ValueError("Tier 0 canary evidence blocking_pending_count must be 0")
    for field in TIER0_FALSE_CLAIM_FIELDS:
        _require_exact_bool(payload[field], f"Tier 0 canary evidence {field}", False)
    if (
        tuple(
            _require_string_list(
                payload["materialized_actions"],
                "Tier 0 canary evidence materialized_actions",
            )
        )
        != TIER0_REQUIRED_MATERIALIZED_ACTIONS
    ):
        raise ValueError(
            "Tier 0 canary evidence materialized_actions must record staged-only "
            "materialization for both response writes"
        )
    return payload


def validate_tier0_release_record_canary_evidence(
    release_record: object,
    canary_evidence: object,
    *,
    canary_evidence_path: str | None = None,
) -> dict[str, object]:
    """Validate that a release record is bound to matching canary evidence."""

    if not isinstance(release_record, dict):
        raise ValueError("Tier 0 release record payload must be an object")
    evidence = validate_tier0_canary_evidence(canary_evidence)
    if release_record.get("release_id") != evidence["release_id"]:
        raise ValueError(
            "Tier 0 release record release_id must match canary evidence release_id"
        )
    if release_record.get("canary_result") != evidence["canary_result"]:
        raise ValueError(
            "Tier 0 release record canary_result must match canary evidence"
        )
    if tuple(release_record.get("canary_commands", ())) != tuple(
        evidence["canary_commands"]
    ):
        raise ValueError(
            "Tier 0 release record canary_commands must match canary evidence"
        )
    evidence_path_items = _require_unique_string_list(
        release_record.get("evidence_paths"),
        "Tier 0 release record evidence_paths",
    )
    evidence_paths = set(evidence_path_items)
    canary_evidence_path_text = None
    if canary_evidence_path is not None:
        canary_evidence_path_text = _require_non_empty_string(
            canary_evidence_path,
            "Tier 0 canary evidence path",
        )
        if canary_evidence_path_text not in evidence_paths:
            raise ValueError(
                "Tier 0 release record evidence_paths must include canary evidence "
                f"path: {canary_evidence_path_text}"
            )
    gate_result_path = _require_non_empty_string(
        evidence["gate_result_path"],
        "Tier 0 canary evidence gate_result_path",
    )
    if gate_result_path not in evidence_paths:
        raise ValueError(
            "Tier 0 release record evidence_paths must include canary gate result "
            f"path: {gate_result_path}"
        )
    if (
        canary_evidence_path_text is not None
        and evidence_path_items.index(canary_evidence_path_text)
        > evidence_path_items.index(gate_result_path)
    ):
        raise ValueError(
            "Tier 0 release record evidence_paths must list canary evidence path "
            "before canary gate result path"
        )
    return evidence


def validate_tier0_canary_evidence_artifacts(
    payload: object,
    *,
    artifact_root: str | Path = ".",
) -> None:
    """Validate that listed Tier 0 canary final artifacts exist as files."""

    evidence = validate_tier0_canary_evidence(payload)
    artifact_paths = _require_unique_string_list(
        evidence["final_artifact_paths"],
        "Tier 0 canary evidence final_artifact_paths",
    )
    root = Path(artifact_root)
    workspace_path = Path(
        _require_non_empty_string(
            evidence["workspace_path"],
            "Tier 0 canary evidence workspace_path",
        )
    )
    resolved_workspace = (
        workspace_path if workspace_path.is_absolute() else root / workspace_path
    ).resolve()
    missing = []
    hash_mismatches = []
    outside_workspace = []
    artifact_payloads = {}
    artifact_resolved_paths = {}
    for item in artifact_paths:
        artifact_path = Path(item)
        resolved = artifact_path if artifact_path.is_absolute() else root / artifact_path
        resolved = resolved.resolve()
        artifact_name = resolved.name
        if not resolved.is_relative_to(resolved_workspace):
            outside_workspace.append(item)
        if not resolved.is_file():
            missing.append(item)
            continue
        actual_hash = _sha256_file(resolved)
        if actual_hash != evidence["final_artifact_sha256"][item]:
            hash_mismatches.append(item)
            continue
        artifact_payloads[artifact_name] = _validate_final_artifact_shape(
            resolved,
            artifact_name,
        )
        artifact_resolved_paths[artifact_name] = resolved
    if outside_workspace:
        raise ValueError(
            "Tier 0 canary evidence final artifact path(s) must be under "
            f"workspace_path: {', '.join(outside_workspace)}"
        )
    if missing:
        raise ValueError(
            "Tier 0 canary evidence missing final artifact file(s): "
            f"{', '.join(missing)}"
        )
    if hash_mismatches:
        raise ValueError(
            "Tier 0 canary evidence final artifact sha256 mismatch for path(s): "
            f"{', '.join(hash_mismatches)}"
        )
    gate_result_ref = _require_non_empty_string(
        evidence["gate_result_path"],
        "Tier 0 canary evidence gate_result_path",
    )
    gate_result_path = _resolve_artifact_ref(gate_result_ref, root)
    if not gate_result_path.is_file():
        raise ValueError(
            "Tier 0 canary evidence missing gate result file: "
            f"{gate_result_ref}"
        )
    gate_result_hash = _sha256_file(gate_result_path)
    if gate_result_hash != evidence["gate_result_sha256"]:
        raise ValueError(
            "Tier 0 canary evidence gate result sha256 mismatch: "
            f"{gate_result_ref}"
        )
    gate_result = _read_json_object(
        gate_result_path,
        "Tier 0 canary evidence gate result",
    )
    _validate_canary_gate_result(
        gate_result,
        workspace_path=str(evidence["workspace_path"]),
        route_handoff_path=artifact_resolved_paths["route_handoff.json"],
        package_path=artifact_resolved_paths["rebuild_package.json"],
        artifact_root=root,
    )
    if gate_result["ok"] != evidence["final_gate_ok"]:
        raise ValueError(
            "Tier 0 canary evidence final_gate_ok must match gate result"
        )
    if gate_result["review_route"] != evidence["final_review_route"]:
        raise ValueError(
            "Tier 0 canary evidence final_review_route must match gate result"
        )
    if gate_result["next_workflow"] != evidence["final_next_workflow"]:
        raise ValueError(
            "Tier 0 canary evidence final_next_workflow must match gate result"
        )
    if gate_result["blocking_pending_count"] != evidence["blocking_pending_count"]:
        raise ValueError(
            "Tier 0 canary evidence blocking_pending_count must match gate result"
        )
    _validate_canary_artifact_semantics(
        evidence=evidence,
        artifact_payloads=artifact_payloads,
        artifact_paths=artifact_resolved_paths,
        root=root,
    )


def build_tier0_canary_evidence(
    *,
    release_id: str,
    workspace_path: str,
    gate_result_path: str,
    artifact_root: str | Path = ".",
) -> dict[str, object]:
    """Build canary evidence from existing staged workspace final artifacts."""

    normalized_workspace = _require_tier0_canary_workspace(workspace_path)
    artifact_paths = [
        _canary_artifact_ref(normalized_workspace, artifact_name)
        for artifact_name in TIER0_REQUIRED_CANARY_ARTIFACT_NAMES
    ]
    root = Path(artifact_root)
    gate_result_ref = _normalize_json_path(
        _require_non_empty_string(gate_result_path, "gate_result_path")
    )
    resolved_gate_result_path = _resolve_artifact_ref(gate_result_ref, root)
    if not resolved_gate_result_path.is_file():
        raise ValueError(
            f"missing Tier 0 canary gate result file: {gate_result_ref}"
        )
    gate_result_sha256 = _sha256_file(resolved_gate_result_path)
    gate_result = _read_json_object(
        resolved_gate_result_path,
        "Tier 0 canary gate result",
    )
    final_artifact_sha256 = {}
    for item in artifact_paths:
        resolved = _resolve_artifact_ref(item, root)
        if not resolved.is_file():
            raise ValueError(f"missing Tier 0 canary final artifact file: {item}")
        final_artifact_sha256[item] = _sha256_file(resolved)

    route_handoff_path = _resolve_artifact_ref(
        _canary_artifact_ref(normalized_workspace, "route_handoff.json"),
        root,
    )
    package_path = _resolve_artifact_ref(
        _canary_artifact_ref(normalized_workspace, "rebuild_package.json"),
        root,
    )
    route_handoff_payload = _read_json_object(
        route_handoff_path,
        "Tier 0 canary evidence route_handoff.json",
    )
    route_handoff = HandoffPacket.model_validate(route_handoff_payload)
    ok, violations = HandoffBoundaryUnit().verify(route_handoff)
    if not ok:
        raise ValueError(
            "Tier 0 canary evidence route_handoff.json handoff violations: "
            f"{', '.join(violations)}"
        )
    review_route = route_handoff.next_route.review_route
    if review_route is None:
        raise ValueError(
            "Tier 0 canary evidence route_handoff.json must include review_route"
        )
    validated_gate = _validate_canary_gate_result(
        gate_result,
        workspace_path=normalized_workspace,
        route_handoff_path=route_handoff_path,
        package_path=package_path,
        artifact_root=root,
    )
    if validated_gate["review_route"] != review_route:
        raise ValueError(
            "Tier 0 canary gate result review_route must match route_handoff.json"
        )
    if (
        validated_gate["next_workflow"]
        != route_handoff.next_route.recommended_workflow
    ):
        raise ValueError(
            "Tier 0 canary gate result next_workflow must match route_handoff.json"
        )

    payload: dict[str, object] = {
        "schema_version": TIER0_RELEASE_RECORD_SCHEMA_VERSION,
        "type": TIER0_CANARY_EVIDENCE_TYPE,
        "release_id": _require_release_id(release_id, "release_id"),
        "canary_result": "pass",
        "canary_commands": list(TIER0_REQUIRED_CANARY_COMMANDS),
        "workspace_path": normalized_workspace,
        "final_artifact_paths": artifact_paths,
        "final_artifact_sha256": final_artifact_sha256,
        "gate_result_path": gate_result_ref,
        "gate_result_sha256": gate_result_sha256,
        "final_gate_ok": validated_gate["ok"],
        "final_review_route": review_route,
        "final_next_workflow": route_handoff.next_route.recommended_workflow,
        "blocking_pending_count": validated_gate["blocking_pending_count"],
        "directapi_provider_calling": False,
        "provider_calls_implemented": False,
        "closed_loop_allowed": False,
        "provider_call_performed": False,
        "closed_loop_advanced": False,
        "materialized_actions": list(TIER0_REQUIRED_MATERIALIZED_ACTIONS),
    }
    validate_tier0_canary_evidence(payload)
    validate_tier0_canary_evidence_artifacts(payload, artifact_root=root)
    return payload


def validate_tier0_release_record_evidence_files(
    payload: object,
    *,
    evidence_root: str | Path = ".",
) -> None:
    """Validate that listed Tier 0 evidence paths point to existing files."""

    if not isinstance(payload, dict):
        raise ValueError("Tier 0 release record payload must be an object")
    evidence_paths = _require_unique_string_list(
        payload.get("evidence_paths"),
        "Tier 0 release record evidence_paths",
    )
    root = Path(evidence_root)
    missing = []
    for item in evidence_paths:
        evidence_path = Path(item)
        resolved = evidence_path if evidence_path.is_absolute() else root / evidence_path
        if not resolved.is_file():
            missing.append(item)
    if missing:
        raise ValueError(
            "Tier 0 release record missing evidence file(s): "
            f"{', '.join(missing)}"
        )


def validate_tier0_release_record_git_checkpoint(
    payload: object,
    *,
    repo_root: str | Path = ".",
) -> None:
    """Validate that the release checkpoint exists and binds to git_commit."""

    if not isinstance(payload, dict):
        raise ValueError("Tier 0 release record payload must be an object")
    git_commit = _require_git_commit_hash(
        payload.get("git_commit"),
        "Tier 0 release record git_commit",
    )
    checkpoint = _require_non_empty_string(
        payload.get("release_tag_or_checkpoint"),
        "Tier 0 release record release_tag_or_checkpoint",
    )
    if not _git_commit_exists(git_commit, repo_root):
        raise ValueError(
            "Tier 0 release record git_commit must exist in the repository"
        )
    if TIER0_GIT_COMMIT_PATTERN.fullmatch(checkpoint):
        if checkpoint != git_commit:
            raise ValueError(
                "Tier 0 release record release_tag_or_checkpoint commit hash "
                "must match git_commit"
            )
        return
    resolved_tag_commit = _git_tag_commit(checkpoint, repo_root)
    if resolved_tag_commit is None:
        raise ValueError(
            "Tier 0 release record release_tag_or_checkpoint must be a git tag "
            "or the git_commit hash"
        )
    if resolved_tag_commit != git_commit:
        raise ValueError(
            "Tier 0 release record release_tag_or_checkpoint tag must resolve "
            "to git_commit"
        )


def build_tier0_release_record(
    *,
    release_id: str,
    created_at_utc: str,
    release_tag_or_checkpoint: str,
    git_commit: str,
    expected_baseline: int,
    full_pytest_command: str,
    record_path: str,
    canary_evidence_path: str | None = None,
    canary_gate_result_path: str | None = None,
) -> dict[str, object]:
    """Build and validate a Tier 0 release record payload."""

    evidence_paths = [
        *TIER0_REQUIRED_EVIDENCE_PATHS,
    ]
    if canary_evidence_path is not None:
        evidence_paths.append(
            _require_non_empty_string(canary_evidence_path, "canary_evidence_path")
        )
    if canary_gate_result_path is not None:
        evidence_paths.append(
            _require_non_empty_string(
                canary_gate_result_path,
                "canary_gate_result_path",
            )
        )
    evidence_paths.append(_require_non_empty_string(record_path, "record_path"))

    payload: dict[str, object] = {
        "schema_version": TIER0_RELEASE_RECORD_SCHEMA_VERSION,
        "type": TIER0_RELEASE_RECORD_TYPE,
        "production_tier": TIER0_PRODUCTION_TIER,
        "release_id": _require_non_empty_string(release_id, "release_id"),
        "created_at_utc": _require_non_empty_string(
            created_at_utc,
            "created_at_utc",
        ),
        "release_tag_or_checkpoint": _require_non_empty_string(
            release_tag_or_checkpoint,
            "release_tag_or_checkpoint",
        ),
        "git_commit": _require_non_empty_string(git_commit, "git_commit"),
        "baseline_tests_passing": expected_baseline,
        "full_pytest_command": _require_non_empty_string(
            full_pytest_command,
            "full_pytest_command",
        ),
        "full_pytest_result": f"{expected_baseline} passed",
        "canary_runbook": TIER0_CANARY_RUNBOOK,
        "canary_result": "pass",
        "canary_commands": list(TIER0_REQUIRED_CANARY_COMMANDS),
        "staged_runtime": TIER0_STAGED_RUNTIME,
        "directapi_provider_calling": False,
        "provider_calls_implemented": False,
        "closed_loop_allowed": False,
        "provider_call_performed": False,
        "closed_loop_advanced": False,
        "known_limitations": list(TIER0_REQUIRED_LIMITATIONS),
        "evidence_paths": evidence_paths,
    }
    validate_tier0_release_record(
        payload,
        expected_baseline=expected_baseline,
        record_path=record_path,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Tier 0 release record JSON file.",
    )
    parser.add_argument("record", help="Tier 0 release record JSON path")
    parser.add_argument(
        "--expected-baseline",
        required=True,
        type=int,
        help="expected full pytest passing count",
    )
    parser.add_argument(
        "--record-path",
        help="record path string that must appear in evidence_paths; defaults to record",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="build and write a Tier 0 release record instead of validating an existing file",
    )
    parser.add_argument(
        "--generate-canary-evidence",
        action="store_true",
        help=(
            "build and write Tier 0 canary evidence from existing staged "
            "workspace final artifacts"
        ),
    )
    parser.add_argument("--release-id", help="release record id for --generate")
    parser.add_argument(
        "--canary-workspace",
        help="workspace path containing output/audit final artifacts for canary evidence generation",
    )
    parser.add_argument(
        "--canary-gate-result",
        help=(
            "saved novel gate --json result for deriving final_gate_ok and "
            "blocking_pending_count"
        ),
    )
    parser.add_argument("--created-at-utc", help="UTC creation timestamp for --generate")
    parser.add_argument(
        "--release-tag-or-checkpoint",
        help="release tag or immutable checkpoint id for --generate",
    )
    parser.add_argument("--git-commit", help="git commit or checkpoint id for --generate")
    parser.add_argument(
        "--full-pytest-command",
        help="full pytest command that produced the baseline for --generate",
    )
    parser.add_argument(
        "--require-evidence-files",
        action="store_true",
        help="require all evidence_paths to point to existing files when validating",
    )
    parser.add_argument(
        "--evidence-root",
        default=".",
        help="root for resolving relative evidence_paths with --require-evidence-files",
    )
    parser.add_argument(
        "--require-git-checkpoint",
        action="store_true",
        help="require release_tag_or_checkpoint to exist and resolve to git_commit",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="git repository root for --require-git-checkpoint",
    )
    parser.add_argument(
        "--canary-evidence",
        help="Tier 0 canary evidence JSON path to validate and bind to the record",
    )
    parser.add_argument(
        "--require-canary-artifacts",
        action="store_true",
        help=(
            "require canary final_artifact_paths to point to existing files and "
            "match final_artifact_sha256, expected JSON artifact shape, and "
            "cross-artifact semantics"
        ),
    )
    parser.add_argument(
        "--canary-artifact-root",
        default=".",
        help="root for resolving relative canary final_artifact_paths",
    )
    args = parser.parse_args(argv)
    failure_subject = (
        "Tier 0 canary evidence"
        if args.generate_canary_evidence
        else "Tier 0 release record"
    )
    try:
        if args.generate_canary_evidence:
            if args.generate:
                raise ValueError(
                    "--generate-canary-evidence cannot be used with --generate"
                )
            incompatible = []
            for flag, value in (
                ("--record-path", args.record_path),
                ("--created-at-utc", args.created_at_utc),
                ("--release-tag-or-checkpoint", args.release_tag_or_checkpoint),
                ("--git-commit", args.git_commit),
                ("--full-pytest-command", args.full_pytest_command),
                ("--require-evidence-files", args.require_evidence_files),
                ("--require-git-checkpoint", args.require_git_checkpoint),
                ("--canary-evidence", args.canary_evidence),
                ("--require-canary-artifacts", args.require_canary_artifacts),
            ):
                if value:
                    incompatible.append(flag)
            if incompatible:
                raise ValueError(
                    "--generate-canary-evidence cannot be used with: "
                    f"{', '.join(incompatible)}"
                )
            missing = [
                field
                for field in TIER0_CANARY_GENERATE_REQUIRED_FIELDS
                if getattr(args, field) is None
            ]
            if missing:
                raise ValueError(
                    "missing Tier 0 canary evidence generation field(s): "
                    f"{', '.join(missing)}"
                )
            output_path = Path(args.record)
            if output_path.exists():
                raise FileExistsError(
                    f"canary evidence already exists: {output_path}"
                )
            payload = build_tier0_canary_evidence(
                release_id=args.release_id,
                workspace_path=args.canary_workspace,
                gate_result_path=args.canary_gate_result,
                artifact_root=args.canary_artifact_root,
            )
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Tier 0 canary evidence GENERATED: {args.record}")
            return 0
        if args.require_canary_artifacts and not args.canary_evidence:
            raise ValueError(
                "--require-canary-artifacts requires --canary-evidence"
            )
        if args.generate:
            if args.require_evidence_files:
                raise ValueError(
                    "--require-evidence-files validates existing records and cannot "
                    "be used with --generate"
                )
            missing = [
                field
                for field in TIER0_GENERATE_REQUIRED_FIELDS
                if not getattr(args, field)
            ]
            if missing:
                raise ValueError(
                    "missing Tier 0 release record generation field(s): "
                    f"{', '.join(missing)}"
                )
            record_path = args.record_path or args.record
            canary_evidence = None
            canary_gate_result_path = None
            if args.canary_evidence:
                canary_evidence = json.loads(
                    Path(args.canary_evidence).read_text(encoding="utf-8")
                )
                canary_gate_result_path = validate_tier0_canary_evidence(
                    canary_evidence
                )["gate_result_path"]
            payload = build_tier0_release_record(
                release_id=args.release_id,
                created_at_utc=args.created_at_utc,
                release_tag_or_checkpoint=args.release_tag_or_checkpoint,
                git_commit=args.git_commit,
                expected_baseline=args.expected_baseline,
                full_pytest_command=args.full_pytest_command,
                record_path=record_path,
                canary_evidence_path=args.canary_evidence,
                canary_gate_result_path=canary_gate_result_path,
            )
            if args.require_git_checkpoint:
                validate_tier0_release_record_git_checkpoint(
                    payload,
                    repo_root=args.repo_root,
                )
            if args.canary_evidence:
                validate_tier0_release_record_canary_evidence(
                    payload,
                    canary_evidence,
                    canary_evidence_path=args.canary_evidence,
                )
                if args.require_canary_artifacts:
                    validate_tier0_canary_evidence_artifacts(
                        canary_evidence,
                        artifact_root=args.canary_artifact_root,
                    )
            output_path = Path(args.record)
            if output_path.exists():
                raise FileExistsError(f"release record already exists: {output_path}")
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Tier 0 release record GENERATED: {args.record}")
            return 0
        extra_generation_fields = [
            field for field in TIER0_GENERATE_REQUIRED_FIELDS if getattr(args, field)
        ]
        if extra_generation_fields:
            raise ValueError(
                "Tier 0 release record generation fields require --generate: "
                f"{', '.join(extra_generation_fields)}"
            )
        extra_canary_generation_fields = [
            field
            for field in TIER0_CANARY_GENERATE_REQUIRED_FIELDS
            if getattr(args, field) is not None
        ]
        if extra_canary_generation_fields:
            raise ValueError(
                "Tier 0 canary evidence generation fields require "
                "--generate-canary-evidence: "
                f"{', '.join(extra_canary_generation_fields)}"
            )
        payload = json.loads(Path(args.record).read_text(encoding="utf-8"))
        validate_tier0_release_record(
            payload,
            expected_baseline=args.expected_baseline,
            record_path=args.record_path or args.record,
        )
        if args.require_evidence_files:
            validate_tier0_release_record_evidence_files(
                payload,
                evidence_root=args.evidence_root,
            )
        if args.require_git_checkpoint:
            validate_tier0_release_record_git_checkpoint(
                payload,
                repo_root=args.repo_root,
            )
        if args.canary_evidence:
            canary_evidence = json.loads(
                Path(args.canary_evidence).read_text(encoding="utf-8")
            )
            validate_tier0_release_record_canary_evidence(
                payload,
                canary_evidence,
                canary_evidence_path=args.canary_evidence,
            )
            if args.require_canary_artifacts:
                validate_tier0_canary_evidence_artifacts(
                    canary_evidence,
                    artifact_root=args.canary_artifact_root,
                )
    except Exception as exc:
        print(f"{failure_subject} FAIL: {exc}")
        return 1
    print(f"Tier 0 release record PASS: {args.record}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
