"""Tests for the unified novel CLI wrapper."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest

from src.boundary_control.automation_contracts import (
    PENDING_AUTOMATION_ACTION,
    PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING,
    PENDING_AUTOMATION_BLOCKER_NO_PENDING,
    PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED,
    PENDING_AUTOMATION_CONTRACT,
    PENDING_AUTOMATION_CONTRACT_VERSION,
    PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED,
    PENDING_AUTOMATION_REASON_READY,
    pending_automation_metadata,
    validate_pending_automation_metadata_in_payload,
    response_materialization_metadata,
)
from src.novel_cli import (
    APPROVAL_GATE_JSON_FIELDS,
    GATE_JSON_FIELDS,
    LIST_JSON_ROW_FIELDS,
    PENDING_JSON_ERROR_FIELDS,
    PENDING_JSON_FIELDS,
    PENDING_SLOT_FIELDS,
    RESPOND_JSON_FIELDS,
    _validate_approval_gate_json_payload,
    _validate_gate_json_payload,
    _validate_json_error_payload,
    _validate_list_json_row_payload,
    _validate_pending_json_payload,
    _validate_respond_json_payload,
    _latest_mtime,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _contract_output_dir(mode: str = "audit") -> Path:
    output_dir = Path(tempfile.mkdtemp(prefix="novel-cli-contract-")) / "output" / mode
    output_dir.mkdir(parents=True)
    return output_dir


def _write_contract_prompt(output_dir: Path, slot_id: str = "rebuild") -> tuple[Path, str, int, float]:
    prompt_path = output_dir / f"{slot_id}_prompt.txt"
    prompt_bytes = b"contract prompt"
    prompt_path.write_bytes(prompt_bytes)
    return (
        prompt_path,
        hashlib.md5(prompt_bytes).hexdigest(),
        len(prompt_bytes),
        prompt_path.stat().st_mtime,
    )


def _run(args: list[str], novels_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["NOVELS_ROOT"] = str(novels_root)
    return subprocess.run(
        [sys.executable, "src/novel_cli.py", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _chapter_text(count: int = 2) -> str:
    return "\n\n".join(
        f"第{i}章 标题{i}\n" + ("正文" * 100) for i in range(1, count + 1)
    )


def test_cli_json_error_payload_contract_rejects_non_string_keys():
    payload = {
        "ok": False,
        "schema_version": 1,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
        1: "adapter-only",
    }

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_unknown_fields():
    payload = {
        "ok": False,
        "schema_version": 1,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
        "adapter_note": "not allowed",
    }

    with pytest.raises(ValueError, match="unknown CLI JSON error field"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_credential_fields():
    payload = {
        "ok": False,
        "schema_version": 1,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
        "api_key": "not allowed",
    }

    with pytest.raises(ValueError, match="must not include credential field"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_execution_claim_fields():
    payload = {
        "ok": False,
        "schema_version": 1,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
        "retry": True,
    }

    with pytest.raises(ValueError, match="must not include execution claim field"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_cross_contract_metadata_fields():
    for field, value in (
        ("automation_ready", True),
        ("provider_call_performed", False),
    ):
        payload = {
            "ok": False,
            "schema_version": 1,
            "error_stage": "runtime",
            "error_type": "ValueError",
            "error": "failed",
            field: value,
        }

        with pytest.raises(ValueError, match="cross-contract metadata"):
            _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_content_fields():
    for field, value in (
        ("prompt", "not allowed"),
        ("response_text", "not allowed"),
        ("text", "not allowed"),
        ("model", "not allowed"),
    ):
        payload = {
            "ok": False,
            "schema_version": 1,
            "error_stage": "runtime",
            "error_type": "ValueError",
            "error": "failed",
            field: value,
        }

        with pytest.raises(ValueError, match="prompt or response content"):
            _validate_json_error_payload(payload)


@pytest.mark.parametrize("field", ["command", "novel"])
def test_cli_json_error_payload_contract_rejects_blank_runtime_context(field):
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "pending",
        "novel": "contract",
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }
    payload[field] = " "

    with pytest.raises(ValueError, match=rf"{field} must be a non-empty string"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_unknown_runtime_command():
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "delete",
        "novel": "contract",
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="unsupported CLI JSON error command"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_null_runtime_command():
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": None,
        "novel": "contract",
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="command must be a non-empty string"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_missing_required_novel_context():
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "pending",
        "novel": None,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="novel must be a non-empty string"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_list_novel_context():
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "list",
        "novel": "contract",
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="novel must be null for list"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_runtime_stage_without_context():
    payload = {
        "ok": False,
        "schema_version": 1,
        "error_stage": "runtime",
        "error_type": "ValueError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="base error payload requires argument"):
        _validate_json_error_payload(payload)


def test_cli_json_error_payload_contract_rejects_argument_stage_with_runtime_context():
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "pending",
        "novel": "contract",
        "error_stage": "argument",
        "error_type": "ArgumentError",
        "error": "failed",
    }

    with pytest.raises(ValueError, match="runtime context requires runtime"):
        _validate_json_error_payload(payload)


@pytest.mark.parametrize("error_type", ["Value Error", "ValueError.", " ValueError"])
def test_cli_json_error_payload_contract_rejects_malformed_error_type(error_type):
    payload = {
        "ok": False,
        "schema_version": 1,
        "command": "pending",
        "novel": "contract",
        "error_stage": "runtime",
        "error_type": error_type,
        "error": "failed",
    }

    with pytest.raises(ValueError, match="exception class identifier"):
        _validate_json_error_payload(payload)


def _valid_pending_json_payload() -> dict:
    output_dir = _contract_output_dir("audit")
    prompt_path, prompt_hash, prompt_bytes, prompt_mtime = _write_contract_prompt(
        output_dir,
    )
    response_path = output_dir / "rebuild_response.txt"
    return {
        "ok": True,
        "schema_version": 1,
        "command": "pending",
        "novel": "contract",
        "mode": "audit",
        "output_dir": str(output_dir),
        "slot_id": None,
        "selection_method": "all_pending",
        "newer_than": None,
        "effective_newer_than": None,
        "route_artifact_mtime": None,
        "expected_prompt_hash": None,
        "prompt_hash_verified": False,
        "pending_count": 1,
        **pending_automation_metadata(pending_count=1),
        "pending": [
            {
                "prompt_file": "rebuild_prompt.txt",
                "response_file": "rebuild_response.txt",
                "prompt_path": str(prompt_path),
                "response_path": str(response_path),
                "prompt_mtime": prompt_mtime,
                "prompt_hash": prompt_hash,
                "prompt_bytes": prompt_bytes,
                "slot_id": "rebuild",
            }
        ],
    }


def test_cli_pending_json_payload_contract_rejects_non_string_keys():
    payload = _valid_pending_json_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_unknown_fields():
    payload = _valid_pending_json_payload()
    payload["adapter_note"] = "not allowed"

    with pytest.raises(ValueError, match="unknown CLI pending JSON field"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_pending_slot_pollution_fields():
    for field, value, message in (
        ("api_key", "not allowed", "credential field"),
        ("retry", True, "execution claim field"),
        ("text", "not allowed", "prompt or response content"),
        ("provider_call_performed", False, "cross-contract metadata"),
    ):
        payload = _valid_pending_json_payload()
        payload["pending"][0][field] = value

        with pytest.raises(ValueError, match=message):
            _validate_pending_json_payload(payload)


def test_cli_pending_json_error_payload_contract_rejects_malformed_error_type():
    payload = _valid_pending_json_payload()
    payload.update(
        {
            "ok": False,
            "error_stage": "runtime",
            "error_type": "Value Error",
            "error": "failed",
        }
    )

    with pytest.raises(ValueError, match="exception class identifier"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_relative_output_dir():
    payload = _valid_pending_json_payload()
    payload["output_dir"] = "output/audit"

    with pytest.raises(ValueError, match="output_dir must be an absolute path"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_output_dir_mode_mismatch():
    payload = _valid_pending_json_payload()
    payload["mode"] = "extend"

    with pytest.raises(ValueError, match="output_dir must be output/extend"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_slot_paths_outside_output_dir():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_path"] = str(
        PROJECT_ROOT / "other-run/output/audit/rebuild_prompt.txt"
    )
    payload["pending"][0]["response_path"] = str(
        PROJECT_ROOT / "other-run/output/audit/rebuild_response.txt"
    )

    with pytest.raises(ValueError, match="pending slot paths must be under output_dir"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_unknown_selection_method():
    payload = _valid_pending_json_payload()
    payload["selection_method"] = "timestamp_guess"

    with pytest.raises(ValueError, match="unsupported CLI pending JSON selection_method"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_unknown_mode():
    payload = _valid_pending_json_payload()
    payload["mode"] = "draft"

    with pytest.raises(ValueError, match="mode must be a supported mode"):
        _validate_pending_json_payload(payload)


def test_cli_json_payload_contract_rejects_workspace_path_novel_names():
    cases = (
        (_validate_pending_json_payload, _valid_pending_json_payload(), "novel"),
        (_validate_respond_json_payload, _valid_respond_json_payload(), "novel"),
        (_validate_gate_json_payload, _valid_gate_json_payload(), "novel"),
        (_validate_list_json_row_payload, _valid_list_json_row_payload(), "name"),
    )

    for validator, payload, field in cases:
        payload[field] = "../other"
        with pytest.raises(ValueError, match="invalid novel name"):
            validator(payload)


def test_cli_pending_json_payload_contract_rejects_zero_prompt_bytes():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_bytes"] = 0

    with pytest.raises(ValueError, match="prompt_bytes must be a positive integer"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_relative_prompt_path():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_path"] = "output/audit/rebuild_prompt.txt"

    with pytest.raises(ValueError, match="prompt_path must be an absolute path"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_slot_id_selection_mismatch():
    payload = _valid_pending_json_payload()
    payload["selection_method"] = "slot_id"
    payload["slot_id"] = "review"

    with pytest.raises(ValueError, match="slot_id must match selected pending entry"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_count_mismatch():
    payload = _valid_pending_json_payload()
    payload["pending_count"] = 0

    with pytest.raises(ValueError, match="pending_count must match pending entries"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_omitted_all_pending_entry():
    payload = _valid_pending_json_payload()
    output_dir = Path(payload["output_dir"])
    omitted_prompt = output_dir / "review_prompt.txt"
    omitted_prompt.write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="all_pending entries must match current pending discovery"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_invalid_prompt_hash():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_hash"] = "abc"

    with pytest.raises(ValueError, match="invalid CLI pending slot prompt_hash"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_prompt_hash_mismatch():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_hash"] = hashlib.md5(b"other").hexdigest()

    with pytest.raises(ValueError, match="prompt_hash must match current prompt file"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_prompt_bytes_mismatch():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_bytes"] += 1

    with pytest.raises(ValueError, match="prompt_bytes must match current prompt file"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_invalid_expected_prompt_hash():
    payload = _valid_pending_json_payload()
    payload["expected_prompt_hash"] = "abc"
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="invalid CLI pending JSON expected_prompt_hash"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_expected_hash_mismatch():
    payload = _valid_pending_json_payload()
    payload["selection_method"] = "slot_id"
    payload["slot_id"] = payload["pending"][0]["slot_id"]
    payload["expected_prompt_hash"] = "1" * 32
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="expected_prompt_hash must match prompt_hash"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_expected_hash_without_slot_id_selection():
    payload = _valid_pending_json_payload()
    payload["expected_prompt_hash"] = payload["pending"][0]["prompt_hash"]
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="expected_prompt_hash requires slot_id"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_invalid_freshness_times():
    for field in ("newer_than", "effective_newer_than", "route_artifact_mtime"):
        for value in (-1, float("nan"), True):
            payload = _valid_pending_json_payload()
            payload[field] = value

            with pytest.raises(ValueError, match=field):
                _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_inconsistent_effective_cutoff():
    payload = _valid_pending_json_payload()
    payload["newer_than"] = 10.0
    payload["route_artifact_mtime"] = 20.0
    payload["effective_newer_than"] = 10.0

    with pytest.raises(ValueError, match="effective freshness cutoff"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_current_route_artifact_mtime_mismatch():
    payload = _valid_pending_json_payload()
    output_dir = Path(payload["output_dir"])
    final_path = output_dir / "audit_report.json"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    payload["route_artifact_mtime"] = 1_700_000_000
    payload["effective_newer_than"] = 1_700_000_000

    with pytest.raises(ValueError, match="route_artifact_mtime must match current route artifacts"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_prompt_not_newer_than_effective_cutoff():
    payload = _valid_pending_json_payload()
    output_dir = Path(payload["output_dir"])
    prompt_path = Path(payload["pending"][0]["prompt_path"])
    final_path = output_dir / "audit_report.json"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    payload["pending"][0]["prompt_mtime"] = 1_700_000_000
    payload["route_artifact_mtime"] = 1_700_000_100
    payload["effective_newer_than"] = 1_700_000_100

    with pytest.raises(ValueError, match="prompt_mtime must be newer than effective freshness cutoff"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_invalid_prompt_mtime():
    for prompt_mtime in (None, -1, float("nan"), True):
        payload = _valid_pending_json_payload()
        payload["pending"][0]["prompt_mtime"] = prompt_mtime

        with pytest.raises(ValueError, match="prompt_mtime"):
            _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_prompt_mtime_mismatch():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["prompt_mtime"] += 1

    with pytest.raises(ValueError, match="prompt_mtime must match current prompt file"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_slot_identity_mismatch():
    payload = _valid_pending_json_payload()
    payload["pending"][0]["response_path"] = str(
        PROJECT_ROOT / "output/audit/other_response.txt"
    )
    payload["pending"][0]["response_file"] = "other_response.txt"

    with pytest.raises(ValueError, match="response_path must match prompt_path"):
        _validate_pending_json_payload(payload)


def test_cli_pending_json_payload_contract_rejects_existing_response_path():
    payload = _valid_pending_json_payload()
    Path(payload["pending"][0]["response_path"]).write_text(
        "completed response",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="response_path must not exist"):
        _validate_pending_json_payload(payload)


def _valid_respond_json_payload() -> dict:
    output_dir = _contract_output_dir("audit")
    prompt_path, prompt_hash, prompt_bytes, _prompt_mtime = _write_contract_prompt(
        output_dir,
    )
    response_source = output_dir.parent.parent / "response.json"
    response_source.write_text("raw response", encoding="utf-8")
    response_source_data = response_source.read_bytes()
    response_path = output_dir / "rebuild_response.txt"
    response_path.write_bytes(response_source_data)
    return {
        "ok": True,
        "schema_version": 1,
        "command": "respond",
        "novel": "contract",
        "mode": "audit",
        "prompt_file": "rebuild_prompt.txt",
        "response_file": "rebuild_response.txt",
        "prompt_path": str(prompt_path),
        "response_path": str(response_path),
        "response_source": str(response_source),
        **response_materialization_metadata(),
        "selection_method": "single_pending",
        "route_artifact_mtime": None,
        "effective_newer_than": None,
        "expected_prompt_hash": None,
        "prompt_hash_verified": False,
        "prompt_hash": prompt_hash,
        "prompt_bytes": prompt_bytes,
        "slot_id": "rebuild",
        "response_source_hash": hashlib.md5(response_source_data).hexdigest(),
        "response_source_bytes": len(response_source_data),
        "response_hash": hashlib.md5(response_source_data).hexdigest(),
        "response_bytes": len(response_source_data),
        "response_chars": len("raw response"),
    }


def test_cli_respond_json_payload_contract_rejects_non_string_keys():
    payload = _valid_respond_json_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_unknown_fields():
    payload = _valid_respond_json_payload()
    payload["adapter_note"] = "not allowed"

    with pytest.raises(ValueError, match="unknown CLI respond JSON field"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_unknown_selection_method():
    payload = _valid_respond_json_payload()
    payload["selection_method"] = "timestamp_guess"

    with pytest.raises(ValueError, match="unsupported CLI respond JSON selection_method"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_unknown_mode():
    payload = _valid_respond_json_payload()
    payload["mode"] = "draft"

    with pytest.raises(ValueError, match="mode must be a supported mode"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_staged_path_mode_mismatch():
    payload = _valid_respond_json_payload()
    payload["mode"] = "extend"

    with pytest.raises(ValueError, match="prompt_path must be under output/extend"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_relative_response_source():
    payload = _valid_respond_json_payload()
    payload["response_source"] = "response.json"

    with pytest.raises(ValueError, match="response_source must be an absolute path"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_relative_response_path():
    payload = _valid_respond_json_payload()
    payload["response_path"] = "output/audit/rebuild_response.txt"

    with pytest.raises(ValueError, match="response_path must be an absolute path"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_prompt_hash_flag_mismatch():
    payload = _valid_respond_json_payload()
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="prompt_hash_verified"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_invalid_expected_prompt_hash():
    payload = _valid_respond_json_payload()
    payload["expected_prompt_hash"] = "abc"
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="invalid CLI respond JSON expected_prompt_hash"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_expected_hash_mismatch():
    payload = _valid_respond_json_payload()
    payload["expected_prompt_hash"] = "1" * 32
    payload["prompt_hash_verified"] = True

    with pytest.raises(ValueError, match="expected_prompt_hash must match prompt_hash"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_prompt_hash_mismatch():
    payload = _valid_respond_json_payload()
    payload["prompt_hash"] = hashlib.md5(b"other").hexdigest()

    with pytest.raises(ValueError, match="prompt_hash must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_prompt_bytes_mismatch():
    payload = _valid_respond_json_payload()
    payload["prompt_bytes"] += 1

    with pytest.raises(ValueError, match="prompt_bytes must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_invalid_freshness_times():
    for field in ("route_artifact_mtime", "effective_newer_than"):
        for value in (-1, float("nan"), True):
            payload = _valid_respond_json_payload()
            payload[field] = value

            with pytest.raises(ValueError, match=field):
                _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_inconsistent_effective_cutoff():
    payload = _valid_respond_json_payload()
    payload["route_artifact_mtime"] = 20.0
    payload["effective_newer_than"] = 10.0

    with pytest.raises(ValueError, match="effective freshness cutoff"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_current_route_artifact_mtime_mismatch():
    payload = _valid_respond_json_payload()
    output_dir = Path(payload["prompt_path"]).parent
    final_path = output_dir / "audit_report.json"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    payload["route_artifact_mtime"] = 1_700_000_000
    payload["effective_newer_than"] = 1_700_000_000

    with pytest.raises(ValueError, match="route_artifact_mtime must match current route artifacts"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_prompt_not_newer_than_effective_cutoff():
    payload = _valid_respond_json_payload()
    output_dir = Path(payload["prompt_path"]).parent
    prompt_path = Path(payload["prompt_path"])
    final_path = output_dir / "audit_report.json"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    payload["route_artifact_mtime"] = 1_700_000_100
    payload["effective_newer_than"] = 1_700_000_100

    with pytest.raises(ValueError, match="prompt_mtime must be newer than effective freshness cutoff"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_empty_response_evidence():
    for field in ("response_source_bytes", "response_bytes", "response_chars"):
        payload = _valid_respond_json_payload()
        payload[field] = 0

        with pytest.raises(ValueError, match=rf"{field}.*positive integer"):
            _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_impossible_response_counts():
    cases = (
        (
            {"response_bytes": 2, "response_chars": 3},
            "response_bytes must be at least response_chars",
        ),
        (
            {"response_source_bytes": 2, "response_bytes": 3, "response_chars": 1},
            "response_source_bytes must not be less than response_bytes",
        ),
    )
    for updates, message in cases:
        payload = _valid_respond_json_payload()
        payload.update(updates)

        with pytest.raises(ValueError, match=message):
            _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_staged_response_source_paths():
    cases = (
        ("prompt_path", "response_source must not match staged prompt_path"),
        ("response_path", "response_source must not match staged response_path"),
    )
    for field, message in cases:
        payload = _valid_respond_json_payload()
        payload["response_source"] = payload[field]

        with pytest.raises(ValueError, match=message):
            _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_source_hash_mismatch():
    payload = _valid_respond_json_payload()
    payload["response_source_hash"] = hashlib.md5(b"other").hexdigest()

    with pytest.raises(ValueError, match="response_source_hash must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_source_bytes_mismatch():
    payload = _valid_respond_json_payload()
    payload["response_source_bytes"] += 1

    with pytest.raises(ValueError, match="response_source_bytes must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_hash_mismatch():
    payload = _valid_respond_json_payload()
    payload["response_hash"] = hashlib.md5(b"other").hexdigest()

    with pytest.raises(ValueError, match="response_hash must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_bytes_mismatch():
    payload = _valid_respond_json_payload()
    payload["response_bytes"] -= 1
    payload["response_chars"] = payload["response_bytes"]

    with pytest.raises(ValueError, match="response_bytes must match current file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_chars_mismatch():
    payload = _valid_respond_json_payload()
    payload["response_chars"] -= 1

    with pytest.raises(ValueError, match="response_chars must match current response file"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_older_than_prompt():
    payload = _valid_respond_json_payload()
    prompt_path = Path(payload["prompt_path"])
    response_path = Path(payload["response_path"])
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))
    os.utime(response_path, (1_700_000_000, 1_700_000_000))

    with pytest.raises(ValueError, match="response_path mtime must not be older"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_response_source_older_than_prompt():
    payload = _valid_respond_json_payload()
    prompt_path = Path(payload["prompt_path"])
    response_source = Path(payload["response_source"])
    response_path = Path(payload["response_path"])
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))
    os.utime(response_source, (1_700_000_000, 1_700_000_000))
    os.utime(response_path, (1_700_000_200, 1_700_000_200))

    with pytest.raises(ValueError, match="response_source mtime must not be older"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_source_response_text_mismatch():
    payload = _valid_respond_json_payload()
    response_path = Path(payload["response_path"])
    response_path.write_text("different", encoding="utf-8")
    response_data = response_path.read_bytes()
    payload["response_hash"] = hashlib.md5(response_data).hexdigest()
    payload["response_bytes"] = len(response_data)
    payload["response_chars"] = len("different")

    with pytest.raises(ValueError, match="response_source text must match"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_blank_response_text():
    payload = _valid_respond_json_payload()
    response_source = Path(payload["response_source"])
    response_path = Path(payload["response_path"])
    response_source.write_text("   ", encoding="utf-8")
    response_path.write_text("   ", encoding="utf-8")
    response_data = response_path.read_bytes()
    payload["response_source_hash"] = hashlib.md5(response_source.read_bytes()).hexdigest()
    payload["response_source_bytes"] = len(response_source.read_bytes())
    payload["response_hash"] = hashlib.md5(response_data).hexdigest()
    payload["response_bytes"] = len(response_data)
    payload["response_chars"] = len("   ")

    with pytest.raises(ValueError, match="response text must be non-empty"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_zero_prompt_bytes():
    payload = _valid_respond_json_payload()
    payload["prompt_bytes"] = 0

    with pytest.raises(ValueError, match="prompt_bytes.*positive integer"):
        _validate_respond_json_payload(payload)


def test_cli_respond_json_payload_contract_rejects_slot_id_mismatch():
    payload = _valid_respond_json_payload()
    payload["slot_id"] = "review"

    with pytest.raises(ValueError, match="slot_id must match prompt_path"):
        _validate_respond_json_payload(payload)


def _valid_gate_json_payload() -> dict:
    output_dir = _contract_output_dir("extend")
    handoff_path = output_dir / "route_handoff.json"
    package_path = output_dir / "extend_rebuild_package.json"
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    package_path.write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "command": "gate",
        "novel": "contract",
        "mode": "extend",
        "ok": True,
        "schema_version": 1,
        "review_route": "pass",
        "next_workflow": "ContinueUnit",
        "violations": [],
        "handoff_path": str(handoff_path),
        "package_path": str(package_path),
        "package_present": True,
        "blocking_pending_count": 0,
        "blocking_pending_prompt_files": [],
    }


def test_cli_gate_json_payload_contract_rejects_non_string_keys():
    payload = _valid_gate_json_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_unknown_fields():
    payload = _valid_gate_json_payload()
    payload["auto_advance"] = True

    with pytest.raises(ValueError, match="unknown CLI gate JSON field"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_blocking_count_mismatch():
    payload = _valid_gate_json_payload()
    payload["blocking_pending_count"] = 1

    with pytest.raises(ValueError, match="blocking_pending_count"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_passed_verdict_with_violations():
    payload = _valid_gate_json_payload()
    payload["violations"] = ["route gate: blocked"]

    with pytest.raises(ValueError, match="passed verdict must not include violations"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_passed_verdict_with_blocking_pending():
    payload = _valid_gate_json_payload()
    payload["blocking_pending_count"] = 1
    payload["blocking_pending_prompt_files"] = ["review_prompt.txt"]

    with pytest.raises(ValueError, match="passed verdict must not include blocking pending"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_continue_pass_without_package():
    payload = _valid_gate_json_payload()
    payload["package_present"] = False

    with pytest.raises(ValueError, match="package_present must match"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_continue_pass_missing_package_file():
    payload = _valid_gate_json_payload()
    Path(payload["package_path"]).unlink()
    payload["package_present"] = False

    with pytest.raises(ValueError, match="ContinueUnit pass requires package_present"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_missing_handoff_file():
    payload = _valid_gate_json_payload()
    Path(payload["handoff_path"]).unlink()

    with pytest.raises(ValueError, match="handoff_path must exist"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_package_present_without_file():
    payload = _valid_gate_json_payload()
    Path(payload["package_path"]).unlink()
    payload["review_route"] = "block"
    payload["next_workflow"] = "Stop"
    payload["ok"] = False
    payload["violations"] = ["route gate: blocked"]
    Path(payload["handoff_path"]).write_text(
        json.dumps(_route_handoff("block", "Stop"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="package_present must match"):
        _validate_gate_json_payload(payload)


def test_cli_json_gate_blocking_prompt_files_must_be_staged_prompt_filenames():
    gate_payload = _valid_gate_json_payload()
    gate_payload["ok"] = False
    gate_payload["violations"] = ["route gate: blocked"]
    gate_payload["blocking_pending_count"] = 1
    gate_payload["blocking_pending_prompt_files"] = ["../review_prompt.txt"]

    with pytest.raises(ValueError, match="invalid prompt filename"):
        _validate_gate_json_payload(gate_payload)

    list_payload = _valid_list_json_row_payload()
    list_payload["gate_ok"] = False
    _set_list_gate_package_fields(list_payload)
    list_payload["gate_violations"] = ["route gate: blocked"]
    list_payload["gate_blocking_pending_count"] = 1
    list_payload["gate_blocking_pending_prompt_files"] = ["../review_prompt.txt"]

    with pytest.raises(ValueError, match="invalid prompt filename"):
        _validate_list_json_row_payload(list_payload)


def test_cli_gate_json_payload_contract_rejects_failed_verdict_without_violations():
    payload = _valid_gate_json_payload()
    payload["ok"] = False

    with pytest.raises(ValueError, match="failed verdict must include violations"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_allows_rebuild_to_review_route_marker():
    payload = _valid_gate_json_payload()
    payload["review_route"] = "-"
    payload["next_workflow"] = "ReviewUnit"
    Path(payload["handoff_path"]).write_text(
        json.dumps(_route_handoff(None, "ReviewUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_unknown_review_route():
    payload = _valid_gate_json_payload()
    payload["review_route"] = "skip"

    with pytest.raises(ValueError, match="review_route must be pass, rewrite, block"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_unknown_next_workflow():
    payload = _valid_gate_json_payload()
    payload["next_workflow"] = "AutoAdvanceUnit"

    with pytest.raises(ValueError, match="next_workflow must be a supported workflow"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_unknown_mode():
    payload = _valid_gate_json_payload()
    payload["mode"] = "draft"

    with pytest.raises(ValueError, match="mode must be a supported mode"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_pass_workflow_mismatch():
    payload = _valid_gate_json_payload()
    payload["next_workflow"] = "RewriteUnit"

    with pytest.raises(ValueError, match="review_route=pass must route to ContinueUnit"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_rewrite_workflow_mismatch():
    payload = _valid_gate_json_payload()
    payload["review_route"] = "rewrite"
    payload["next_workflow"] = "ContinueUnit"

    with pytest.raises(
        ValueError,
        match="review_route=rewrite must route to RewriteUnit",
    ):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_block_workflow_mismatch():
    payload = _valid_gate_json_payload()
    payload["review_route"] = "block"
    payload["next_workflow"] = "ContinueUnit"

    with pytest.raises(
        ValueError,
        match="review_route=block must route to Stop, RebuildUnit, or Replan",
    ):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_relative_handoff_path():
    payload = _valid_gate_json_payload()
    payload["handoff_path"] = "output/extend/route_handoff.json"

    with pytest.raises(ValueError, match="handoff_path must be an absolute path"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_noncanonical_handoff_filename():
    payload = _valid_gate_json_payload()
    payload["handoff_path"] = str(Path(payload["handoff_path"]).with_name("other_handoff.json"))

    with pytest.raises(ValueError, match="route handoff file must be route_handoff.json"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_artifact_path_mode_mismatch():
    cases = (
        ("handoff_path", PROJECT_ROOT / "output/audit/route_handoff.json"),
        ("package_path", PROJECT_ROOT / "output/audit/extend_rebuild_package.json"),
    )
    for field, artifact_path in cases:
        payload = _valid_gate_json_payload()
        payload[field] = str(artifact_path)

        with pytest.raises(ValueError, match=f"{field} must be under output/extend"):
            _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_split_artifact_directories():
    payload = _valid_gate_json_payload()
    payload["package_path"] = str(
        PROJECT_ROOT / "other-run/output/extend/extend_rebuild_package.json"
    )

    with pytest.raises(ValueError, match="artifact paths must share output directory"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_relative_package_path():
    payload = _valid_gate_json_payload()
    payload["package_path"] = "output/extend/extend_rebuild_package.json"

    with pytest.raises(ValueError, match="package_path must be an absolute path"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_package_file_mode_mismatch():
    payload = _valid_gate_json_payload()
    payload["package_path"] = str(Path(payload["package_path"]).with_name("rebuild_package.json"))

    with pytest.raises(ValueError, match="package file must match mode"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_handoff_review_route_mismatch():
    payload = _valid_gate_json_payload()
    Path(payload["handoff_path"]).write_text(
        json.dumps(_route_handoff("rewrite", "RewriteUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="review_route must match route_handoff"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_handoff_workflow_mismatch():
    payload = _valid_gate_json_payload()
    payload["ok"] = False
    payload["review_route"] = "block"
    payload["next_workflow"] = "Stop"
    payload["violations"] = ["route gate: blocked"]
    Path(payload["handoff_path"]).write_text(
        json.dumps(_route_handoff("block", "Replan"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="next_workflow must match route_handoff"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_current_verdict_ok_mismatch():
    payload = _valid_gate_json_payload()
    payload["ok"] = False
    payload["violations"] = ["route gate: forged failure"]

    with pytest.raises(ValueError, match="ok must match current gate verdict"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_current_verdict_violations_mismatch():
    payload = _valid_gate_json_payload()
    Path(payload["package_path"]).write_text(
        json.dumps(_serialization_package(runnable_state=False), ensure_ascii=False),
        encoding="utf-8",
    )
    payload["ok"] = False
    payload["violations"] = ["route gate: forged failure"]

    with pytest.raises(ValueError, match="violations must match current gate verdict"):
        _validate_gate_json_payload(payload)


def test_cli_gate_json_payload_contract_rejects_current_verdict_blocking_mismatch():
    payload = _valid_gate_json_payload()
    prompt_path = Path(payload["handoff_path"]).with_name("review_prompt.txt")
    prompt_path.write_text("new prompt", encoding="utf-8")
    os.utime(Path(payload["handoff_path"]), (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))
    payload["ok"] = False
    payload["violations"] = [
        "route gate: pending prompt newer than route handoff: review_prompt.txt"
    ]
    payload["blocking_pending_count"] = 0
    payload["blocking_pending_prompt_files"] = []

    with pytest.raises(
        ValueError,
        match="blocking_pending_count must match current gate verdict",
    ):
        _validate_gate_json_payload(payload)


def _review_issue_open_item(**overrides) -> dict:
    """A ReviewIssue handoff open item with sensible defaults."""
    item = {
        "type": "ReviewIssue",
        "issue_id": "iss_critical_1",
        "issue_type": "weak_progression",
        "severity": "critical",
        "location": "pu_scene_001",
        "scope_of_impact": "next unit",
        "violated_rule": "progression",
        "description": "critical issue for approval gate",
        "resolution_status": "open",
        "status": "open",
        "suggested_fix": None,
        "plotunit_ref": None,
        "affected_threads": [],
        "supporting_facts": [],
        "contradictory_facts": [],
    }
    for key, value in overrides.items():
        if value is None:
            item.pop(key, None)
        else:
            item[key] = value
    return item


def _approval_decision_file(
    output_dir: Path,
    *,
    decision: str = "approve",
    critical_issue_ids: list[str] | None = None,
) -> Path:
    path = output_dir / "approval_decision.json"
    path.write_text(
        json.dumps(
            {
                "decision": decision,
                "critical_issue_ids": (
                    critical_issue_ids
                    if critical_issue_ids is not None
                    else ["iss_critical_1"]
                ),
                "operator_note": "operator accepted",
                "decided_at_utc": "2026-08-01T12:34:56Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _valid_approval_gate_json_payload(*, override: bool = False) -> dict:
    """Mirror of _valid_gate_json_payload for the approval gate contract.

    Writes a rewrite handoff with an open critical ReviewIssue, then hard-codes
    the verdict the gate would produce. With override=True the payload reflects
    the approve override (review_route=rewrite, next_workflow=ContinueUnit,
    ok=true, approval_ok=true). Without it, the payload reflects a reject
    decision (ok=false, decision=reject) — the on-disk state that actually
    produces a non-override verdict, so the recomputed verdict matches.
    """
    output_dir = _contract_output_dir("extend")
    handoff_path = output_dir / "route_handoff.json"
    package_path = output_dir / "extend_rebuild_package.json"
    handoff_payload = _route_handoff("rewrite", "RewriteUnit")
    handoff_payload["open_items"] = [_review_issue_open_item()]
    handoff_payload["change_set"][0]["issue_count"] = 1
    handoff_path.write_text(
        json.dumps(handoff_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    package_path.write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    if override:
        _approval_decision_file(output_dir)
        return {
            "command": "gate",
            "novel": "contract",
            "mode": "extend",
            "ok": True,
            "schema_version": 1,
            "review_route": "rewrite",
            "next_workflow": "ContinueUnit",
            "violations": [],
            "handoff_path": str(handoff_path),
            "package_path": str(package_path),
            "package_present": True,
            "blocking_pending_count": 0,
            "blocking_pending_prompt_files": [],
            "approval_required": True,
            "critical_issue_ids": ["iss_critical_1"],
            "approval_decision": "approve",
            "approval_ok": True,
        }
    _approval_decision_file(output_dir, decision="reject")
    return {
        "command": "gate",
        "novel": "contract",
        "mode": "extend",
        "ok": False,
        "schema_version": 1,
        "review_route": "rewrite",
        "next_workflow": "RewriteUnit",
        "violations": [
            "approval gate: critical issue(s) rejected by operator: "
            "iss_critical_1"
        ],
        "handoff_path": str(handoff_path),
        "package_path": str(package_path),
        "package_present": True,
        "blocking_pending_count": 0,
        "blocking_pending_prompt_files": [],
        "approval_required": True,
        "critical_issue_ids": ["iss_critical_1"],
        "approval_decision": "reject",
        "approval_ok": False,
    }


def test_cli_approval_gate_json_fields_extends_gate_json_fields_as_prefix():
    assert APPROVAL_GATE_JSON_FIELDS[:13] == GATE_JSON_FIELDS
    assert APPROVAL_GATE_JSON_FIELDS[13:] == (
        "approval_required",
        "critical_issue_ids",
        "approval_decision",
        "approval_ok",
    )


def test_cli_gate_json_payload_contract_rejects_approval_field_as_unknown():
    payload = _valid_gate_json_payload()
    payload["approval_required"] = True

    with pytest.raises(ValueError, match="unknown CLI gate JSON field"):
        _validate_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_non_string_keys():
    payload = _valid_approval_gate_json_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_unknown_fields():
    payload = _valid_approval_gate_json_payload()
    payload["auto_advance"] = True

    with pytest.raises(ValueError, match="unknown CLI approval gate JSON field"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_credential_fields():
    payload = _valid_approval_gate_json_payload()
    payload["api_key"] = "not allowed"

    with pytest.raises(ValueError, match="must not include credential field"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_execution_claim_fields():
    payload = _valid_approval_gate_json_payload()
    payload["retry"] = True

    with pytest.raises(ValueError, match="must not include execution claim field"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_cross_contract_metadata():
    payload = _valid_approval_gate_json_payload()
    payload["provider_call_performed"] = False

    with pytest.raises(ValueError, match="cross-contract metadata"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_bad_approval_required():
    payload = _valid_approval_gate_json_payload()
    payload["approval_required"] = False

    with pytest.raises(ValueError, match="approval_required must match"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_bad_approval_decision():
    payload = _valid_approval_gate_json_payload()
    payload["approval_decision"] = "maybe"

    with pytest.raises(ValueError, match="approval_decision must be approve, reject, or -"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_override_without_approval():
    payload = _valid_approval_gate_json_payload(override=True)
    payload["approval_ok"] = False

    with pytest.raises(ValueError, match="ContinueUnit override requires approved"):
        _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_accepts_override_with_approval():
    payload = _valid_approval_gate_json_payload(override=True)
    _validate_approval_gate_json_payload(payload)


def test_cli_approval_gate_json_payload_contract_rejects_approval_ok_true_when_gate_fails():
    payload = _valid_approval_gate_json_payload(override=True)
    payload["ok"] = False
    payload["violations"] = ["route gate: pending prompt newer than handoff"]
    payload["next_workflow"] = "RewriteUnit"

    with pytest.raises(ValueError, match="must match current approval gate verdict"):
        _validate_approval_gate_json_payload(payload)


def _valid_list_json_row_payload() -> dict:
    output_dir = _contract_output_dir("audit")
    prompt_path, prompt_hash, prompt_bytes, prompt_mtime = _write_contract_prompt(
        output_dir,
    )
    response_path = output_dir / "rebuild_response.txt"
    return {
        "schema_version": 1,
        "command": "list",
        "name": "contract",
        "mode": "audit",
        "status": "waiting",
        "detail": "[WAITING: rebuild_response.txt]",
        "latest_date": datetime.fromtimestamp(prompt_mtime).strftime("%Y-%m-%d"),
        "latest_mtime": prompt_mtime,
        "route": None,
        "next_workflow": None,
        "gate_ok": None,
        "gate_violations": [],
        "gate_package_file": None,
        "gate_package_path": None,
        "gate_package_present": None,
        "gate_blocking_pending_count": None,
        "gate_blocking_pending_prompt_files": [],
        "pending_count": 1,
        "pending_prompt_file": "rebuild_prompt.txt",
        "pending_response_file": "rebuild_response.txt",
        "pending_prompt_path": str(prompt_path),
        "pending_response_path": str(response_path),
        "pending_prompt_hash": prompt_hash,
        "pending_prompt_bytes": prompt_bytes,
        "pending_prompt_mtime": prompt_mtime,
        "pending_slot_id": "rebuild",
        **pending_automation_metadata(pending_count=1),
        "final_result_file": None,
        "final_result_path": None,
        "route_handoff_file": None,
        "route_handoff_path": None,
        "time_status": "未设定",
    }


def _clear_list_pending_fields(payload: dict) -> None:
    payload["pending_count"] = 0
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
        payload[field] = None
    payload.update(pending_automation_metadata(pending_count=0))


def _refresh_list_detail(payload: dict) -> None:
    if payload["status"] == "initialized":
        payload["detail"] = "-"
        return
    if payload["pending_count"] > 0:
        payload["detail"] = f"[WAITING: {payload['pending_response_file']}]"
        return
    if payload.get("route") is not None:
        payload["detail"] = f"route={payload['route']}"
        if payload.get("next_workflow") is not None:
            payload["detail"] += f" next={payload['next_workflow']}"


def _list_artifact_output_dir(payload: dict) -> Path:
    for field in (
        "gate_package_path",
        "final_result_path",
        "route_handoff_path",
    ):
        if payload.get(field) is not None:
            return Path(payload[field]).parent
    return _contract_output_dir("extend")


def _refresh_list_latest_fields(payload: dict) -> None:
    output_dir = _list_artifact_output_dir(payload)
    latest_mtime = _latest_mtime(output_dir.parent.parent)
    payload["latest_mtime"] = latest_mtime
    payload["latest_date"] = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d")


def _set_list_gate_package_fields(payload: dict) -> None:
    payload["mode"] = "extend"
    output_dir = _list_artifact_output_dir(payload)
    package_path = output_dir / "extend_rebuild_package.json"
    package_path.write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    payload["gate_package_file"] = "extend_rebuild_package.json"
    payload["gate_package_path"] = str(package_path)
    payload["gate_package_present"] = True
    _refresh_list_latest_fields(payload)


def _set_list_final_result_fields(payload: dict) -> None:
    payload["mode"] = "extend"
    output_dir = _list_artifact_output_dir(payload)
    final_result_path = output_dir / "extend_result.json"
    route = payload.get("route") or "pass"
    final_result_path.write_text(
        json.dumps({"route": route}, ensure_ascii=False),
        encoding="utf-8",
    )
    payload["final_result_file"] = "extend_result.json"
    payload["final_result_path"] = str(final_result_path)
    _refresh_list_latest_fields(payload)
    _refresh_list_detail(payload)


def _set_list_route_handoff_fields(payload: dict) -> None:
    output_dir = _list_artifact_output_dir(payload)
    route_handoff_path = output_dir / "route_handoff.json"
    route = payload.get("route")
    target = payload.get("next_workflow")
    if route is None:
        route = "pass"
    if target is None:
        target = "ContinueUnit"
    route_handoff_path.write_text(
        json.dumps(_route_handoff(route, target), ensure_ascii=False),
        encoding="utf-8",
    )
    payload["route_handoff_file"] = "route_handoff.json"
    payload["route_handoff_path"] = str(route_handoff_path)
    _refresh_list_latest_fields(payload)
    _refresh_list_detail(payload)


def _set_list_passing_gate_fields(payload: dict) -> None:
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)
    payload["gate_blocking_pending_count"] = 0


def test_cli_list_json_row_contract_rejects_non_string_keys():
    payload = _valid_list_json_row_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="payload keys must be strings"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_unknown_fields():
    payload = _valid_list_json_row_payload()
    payload["selected_by_timestamp"] = True

    with pytest.raises(ValueError, match="unknown CLI list JSON row field"):
        _validate_list_json_row_payload(payload)


def test_cli_exact_json_payload_contract_rejects_pollution_fields_before_unknown():
    cases = (
        (
            _validate_pending_json_payload,
            _valid_pending_json_payload(),
            "api_key",
            "not allowed",
            "credential field",
        ),
        (
            _validate_respond_json_payload,
            _valid_respond_json_payload(),
            "retry",
            True,
            "execution claim field",
        ),
        (
            _validate_gate_json_payload,
            _valid_gate_json_payload(),
            "text",
            "not allowed",
            "prompt or response content",
        ),
        (
            _validate_list_json_row_payload,
            _valid_list_json_row_payload(),
            "model",
            "not allowed",
            "prompt or response content",
        ),
    )

    for validator, payload, field, value, message in cases:
        payload[field] = value
        with pytest.raises(ValueError, match=message):
            validator(payload)


def test_cli_exact_json_payload_contract_rejects_cross_contract_metadata_before_unknown():
    cases = (
        (
            _validate_pending_json_payload,
            _valid_pending_json_payload(),
            "provider_call_performed",
            False,
        ),
        (
            _validate_respond_json_payload,
            _valid_respond_json_payload(),
            "automation_ready",
            True,
        ),
        (
            _validate_gate_json_payload,
            _valid_gate_json_payload(),
            "closed_loop_advanced",
            False,
        ),
        (
            _validate_list_json_row_payload,
            _valid_list_json_row_payload(),
            "materialized_action",
            "materialize_staged_response_only",
        ),
    )

    for validator, payload, field, value in cases:
        payload[field] = value
        with pytest.raises(ValueError, match="cross-contract metadata"):
            validator(payload)


def test_cli_list_json_row_contract_rejects_unknown_status():
    payload = _valid_list_json_row_payload()
    payload["status"] = "ready"

    with pytest.raises(ValueError, match="status must be a supported status"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_unknown_mode():
    payload = _valid_list_json_row_payload()
    payload["mode"] = "draft"

    with pytest.raises(ValueError, match="mode must be a supported mode"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_unknown_mode_for_waiting_row():
    payload = _valid_list_json_row_payload()
    payload["mode"] = "unknown"

    with pytest.raises(ValueError, match="unknown mode requires initialized status"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_allows_unknown_initialized_mode():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "unknown"
    payload["status"] = "initialized"
    payload["detail"] = "-"

    _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_initialized_detail_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "unknown"
    payload["status"] = "initialized"
    payload["detail"] = "route=pass"

    with pytest.raises(ValueError, match="detail must match status and route evidence"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_waiting_detail_mismatch():
    payload = _valid_list_json_row_payload()
    payload["detail"] = "[WAITING: other_response.txt]"

    with pytest.raises(ValueError, match="detail must match status and route evidence"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_existing_pending_response_path():
    payload = _valid_list_json_row_payload()
    Path(payload["pending_response_path"]).write_text(
        "completed response",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pending_response_path must not exist"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_omitted_current_pending_slot():
    payload = _valid_list_json_row_payload()
    output_dir = Path(payload["pending_prompt_path"]).parent
    omitted_prompt = output_dir / "review_prompt.txt"
    omitted_prompt.write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="current pending discovery"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_nonfirst_current_pending_slot():
    payload = _valid_list_json_row_payload()
    output_dir = Path(payload["pending_prompt_path"]).parent
    earlier_prompt = output_dir / "continue_prompt.txt"
    earlier_prompt.write_text("continue", encoding="utf-8")
    earlier_time = payload["pending_prompt_mtime"] - 1
    os.utime(earlier_prompt, (earlier_time, earlier_time))
    payload["pending_count"] = 2
    payload.update(pending_automation_metadata(pending_count=2))

    with pytest.raises(ValueError, match="current pending discovery"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_waiting_without_pending_count():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)

    with pytest.raises(ValueError, match="waiting status requires pending_count"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_non_waiting_with_pending_count():
    payload = _valid_list_json_row_payload()
    payload["status"] = "completed"
    payload["route"] = "pass"
    _set_list_final_result_fields(payload)

    with pytest.raises(ValueError, match="pending_count must be zero unless status is waiting"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_next_workflow_without_route():
    payload = _valid_list_json_row_payload()
    payload["next_workflow"] = "ContinueUnit"

    with pytest.raises(ValueError, match="next_workflow requires route"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_unknown_route():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "skip"

    with pytest.raises(ValueError, match="route must be pass, rewrite, or block"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_status_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "rewrite"

    with pytest.raises(ValueError, match="status must match route"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_unknown_next_workflow():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "AutoAdvanceUnit"

    with pytest.raises(ValueError, match="next_workflow must be a supported workflow"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_next_workflow_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "RewriteUnit"

    with pytest.raises(ValueError, match="route=pass must route to ContinueUnit"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_allows_block_route_workflow_matrix():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "blocked"
    payload["route"] = "block"
    payload["next_workflow"] = "Replan"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)

    _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_without_final_result_artifact():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"

    with pytest.raises(ValueError, match="route requires final result artifact"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_final_result_artifact_without_route():
    payload = _valid_list_json_row_payload()
    _set_list_final_result_fields(payload)

    with pytest.raises(ValueError, match="final result artifact requires route"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_next_workflow_without_route_handoff_artifact():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)

    with pytest.raises(ValueError, match="next_workflow requires route handoff artifact"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_handoff_artifact_without_next_workflow():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)

    with pytest.raises(ValueError, match="route handoff artifact requires next_workflow"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_verdict_without_route_handoff_artifact():
    payload = _valid_list_json_row_payload()
    _set_list_passing_gate_fields(payload)

    with pytest.raises(ValueError, match="gate verdict requires route handoff artifact"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_handoff_artifact_without_gate_verdict():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)

    with pytest.raises(ValueError, match="route handoff artifact requires gate verdict"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_allows_passed_gate_verdict():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)

    _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_detail_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    _set_list_final_result_fields(payload)
    payload["detail"] = "route=block"

    with pytest.raises(ValueError, match="detail must match status and route evidence"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_handoff_detail_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    payload["detail"] = "route=pass"

    with pytest.raises(ValueError, match="detail must match status and route evidence"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_current_gate_ok_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    payload["gate_ok"] = False
    payload["gate_violations"] = ["route gate: forged failure"]

    with pytest.raises(ValueError, match="gate_ok must match current gate verdict"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_current_gate_violations_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    Path(payload["gate_package_path"]).write_text(
        json.dumps(_serialization_package(runnable_state=False), ensure_ascii=False),
        encoding="utf-8",
    )
    payload["gate_ok"] = False
    payload["gate_violations"] = ["route gate: forged failure"]

    with pytest.raises(
        ValueError,
        match="gate_violations must match current gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_current_gate_blocking_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    prompt_path = Path(payload["route_handoff_path"]).with_name("review_prompt.txt")
    prompt_path.write_text("new prompt", encoding="utf-8")
    os.utime(Path(payload["route_handoff_path"]), (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))
    payload["gate_ok"] = False
    payload["gate_violations"] = [
        "route gate: pending prompt newer than route handoff: review_prompt.txt"
    ]

    with pytest.raises(
        ValueError,
        match="gate_blocking_pending_count must match current gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_violations_without_verdict():
    payload = _valid_list_json_row_payload()
    payload["gate_violations"] = ["route gate: blocked"]

    with pytest.raises(ValueError, match="gate_violations must be empty without gate verdict"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_count_without_verdict():
    payload = _valid_list_json_row_payload()
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(
        ValueError,
        match="gate_blocking_pending_count must be null without gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_package_without_verdict():
    payload = _valid_list_json_row_payload()
    _set_list_gate_package_fields(payload)

    with pytest.raises(
        ValueError,
        match="gate_package_file must be null without gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_verdict_without_blocking_count():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)

    with pytest.raises(
        ValueError,
        match="gate_blocking_pending_count must be present with gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_verdict_without_package_path():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)
    payload["gate_package_path"] = None
    payload["gate_package_present"] = True
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(
        ValueError,
        match="gate_package_path must be present with gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_verdict_without_package_presence():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)
    payload["gate_package_present"] = None
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(
        ValueError,
        match="gate_package_present must be present with gate verdict",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_passed_gate_with_violations():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)
    payload["gate_violations"] = ["route gate: blocked"]
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(ValueError, match="passed verdict must not include violations"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_passed_gate_with_blocking_pending():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = True
    _set_list_gate_package_fields(payload)
    payload["gate_blocking_pending_count"] = 1
    payload["gate_blocking_pending_prompt_files"] = ["review_prompt.txt"]

    with pytest.raises(ValueError, match="passed verdict must not include blocking pending"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_continue_gate_pass_without_package():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_passing_gate_fields(payload)
    payload["gate_package_present"] = False

    with pytest.raises(ValueError, match="ContinueUnit pass requires package_present"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_failed_gate_without_violations():
    payload = _valid_list_json_row_payload()
    payload["gate_ok"] = False
    _set_list_gate_package_fields(payload)
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(ValueError, match="failed verdict must include violations"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_invalid_latest_mtime():
    for latest_mtime in (None, -1, float("nan"), True):
        payload = _valid_list_json_row_payload()
        payload["latest_mtime"] = latest_mtime

        with pytest.raises(ValueError, match="latest_mtime"):
            _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_latest_date_mismatch():
    payload = _valid_list_json_row_payload()
    payload["latest_date"] = "2999-01-01"

    with pytest.raises(ValueError, match="latest_date must match latest_mtime"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_current_latest_mtime_mismatch():
    payload = _valid_list_json_row_payload()
    payload["latest_mtime"] = payload["latest_mtime"] + 86_400
    payload["latest_date"] = datetime.fromtimestamp(
        payload["latest_mtime"]
    ).strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="latest_mtime must match current workspace files"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_prompt_older_than_route_artifacts():
    payload = _valid_list_json_row_payload()
    output_dir = Path(payload["pending_prompt_path"]).parent
    prompt_path = Path(payload["pending_prompt_path"])
    final_path = output_dir / "audit_report.json"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    payload["pending_prompt_mtime"] = 1_700_000_000
    payload["latest_mtime"] = 1_700_000_100
    payload["latest_date"] = datetime.fromtimestamp(1_700_000_100).strftime("%Y-%m-%d")

    with pytest.raises(ValueError, match="pending_prompt_mtime must be newer than current route artifacts"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_metadata_mismatch():
    payload = _valid_list_json_row_payload()
    payload["status"] = "completed"
    payload["route"] = "pass"
    _set_list_final_result_fields(payload)
    payload["pending_count"] = 0

    with pytest.raises(ValueError, match="pending_prompt_file"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_invalid_pending_prompt_mtime():
    for pending_prompt_mtime in (None, -1, float("nan"), True):
        payload = _valid_list_json_row_payload()
        payload["pending_prompt_mtime"] = pending_prompt_mtime

        with pytest.raises(ValueError, match="pending_prompt_mtime"):
            _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_prompt_hash_mismatch():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_hash"] = hashlib.md5(b"other").hexdigest()

    with pytest.raises(ValueError, match="prompt_hash must match current prompt file"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_prompt_bytes_mismatch():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_bytes"] += 1

    with pytest.raises(ValueError, match="prompt_bytes must match current prompt file"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_prompt_mtime_mismatch():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_mtime"] -= 1

    with pytest.raises(ValueError, match="prompt_mtime must match current prompt file"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_prompt_mtime_after_latest_mtime():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_mtime"] = payload["latest_mtime"] + 1

    with pytest.raises(ValueError, match="pending_prompt_mtime must not exceed"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_zero_pending_prompt_bytes():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_bytes"] = 0

    with pytest.raises(ValueError, match="pending_prompt_bytes.*positive integer"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_pending_slot_identity_mismatch():
    payload = _valid_list_json_row_payload()
    payload["pending_prompt_file"] = "other_prompt.txt"

    with pytest.raises(ValueError, match="pending_prompt_file must match"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_relative_pending_response_path():
    payload = _valid_list_json_row_payload()
    payload["pending_response_path"] = "output/audit/rebuild_response.txt"

    with pytest.raises(
        ValueError,
        match="pending_response_path must be an absolute path",
    ):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_relative_gate_package_path():
    payload = _valid_list_json_row_payload()
    payload["gate_package_file"] = "extend_rebuild_package.json"
    payload["gate_package_path"] = "output/extend/extend_rebuild_package.json"
    payload["gate_package_present"] = True
    payload["gate_ok"] = True
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(ValueError, match="gate_package_path must be an absolute path"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_package_present_without_file():
    payload = _valid_list_json_row_payload()
    _set_list_passing_gate_fields(payload)
    Path(payload["gate_package_path"]).unlink()

    with pytest.raises(ValueError, match="gate_package_present must match"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_package_absent_with_file():
    payload = _valid_list_json_row_payload()
    _set_list_gate_package_fields(payload)
    payload["gate_ok"] = False
    payload["gate_violations"] = ["route gate: blocked"]
    payload["gate_blocking_pending_count"] = 0
    payload["gate_package_present"] = False

    with pytest.raises(ValueError, match="gate_package_present must match"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_package_file_path_mismatch():
    payload = _valid_list_json_row_payload()
    payload["gate_package_file"] = "other_package.json"
    payload["gate_package_path"] = str(
        PROJECT_ROOT / "output/extend/extend_rebuild_package.json"
    )
    payload["gate_package_present"] = True
    payload["gate_ok"] = True
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(ValueError, match="gate_package_file must match"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_gate_package_file_mode_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    payload["gate_package_file"] = "rebuild_package.json"
    payload["gate_package_path"] = str(PROJECT_ROOT / "output/extend/rebuild_package.json")
    payload["gate_package_present"] = True
    payload["gate_ok"] = True
    payload["gate_blocking_pending_count"] = 0

    with pytest.raises(ValueError, match="package file must match mode"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_relative_final_result_path():
    payload = _valid_list_json_row_payload()
    payload["final_result_file"] = "extend_result.json"
    payload["final_result_path"] = "output/extend/extend_result.json"

    with pytest.raises(ValueError, match="final_result_path must be an absolute path"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_missing_final_result_file():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    _set_list_final_result_fields(payload)
    Path(payload["final_result_path"]).unlink()

    with pytest.raises(ValueError, match="final_result_path must exist"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_final_result_route_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    Path(payload["final_result_path"]).write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="route must match final_result_path route"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_final_result_file_mode_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["final_result_file"] = "audit_report.json"
    payload["final_result_path"] = str(PROJECT_ROOT / "output/extend/audit_report.json")

    with pytest.raises(ValueError, match="final result file must match mode"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_handoff_file_path_mismatch():
    payload = _valid_list_json_row_payload()
    payload["route_handoff_file"] = "other_handoff.json"
    payload["route_handoff_path"] = str(PROJECT_ROOT / "output/extend/route_handoff.json")

    with pytest.raises(ValueError, match="route_handoff_file must match"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_noncanonical_route_handoff_filename():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    payload["route_handoff_file"] = "other_handoff.json"
    payload["route_handoff_path"] = str(PROJECT_ROOT / "output/extend/other_handoff.json")

    with pytest.raises(ValueError, match="route handoff file must be route_handoff.json"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_missing_route_handoff_file():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    Path(payload["route_handoff_path"]).unlink()

    with pytest.raises(ValueError, match="route_handoff_path must exist"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_handoff_route_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    Path(payload["route_handoff_path"]).write_text(
        json.dumps(_route_handoff("rewrite", "RewriteUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="route must match route_handoff"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_route_handoff_workflow_mismatch():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "blocked"
    payload["route"] = "block"
    payload["next_workflow"] = "Stop"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    Path(payload["route_handoff_path"]).write_text(
        json.dumps(_route_handoff("block", "Replan"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="next_workflow must match route_handoff"):
        _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_artifact_path_mode_mismatch():
    cases = (
        ("gate_package_path", PROJECT_ROOT / "output/audit/extend_rebuild_package.json"),
        ("final_result_path", PROJECT_ROOT / "output/audit/extend_result.json"),
        ("route_handoff_path", PROJECT_ROOT / "output/audit/route_handoff.json"),
    )
    for field, artifact_path in cases:
        payload = _valid_list_json_row_payload()
        _clear_list_pending_fields(payload)
        payload["mode"] = "extend"
        payload["status"] = "completed"
        payload["route"] = "pass"
        payload["next_workflow"] = "ContinueUnit"
        _set_list_final_result_fields(payload)
        _set_list_route_handoff_fields(payload)
        _set_list_passing_gate_fields(payload)
        payload[field] = str(artifact_path)

        with pytest.raises(ValueError, match=f"{field} must be under output/extend"):
            _validate_list_json_row_payload(payload)


def test_cli_list_json_row_contract_rejects_split_artifact_directories():
    payload = _valid_list_json_row_payload()
    _clear_list_pending_fields(payload)
    payload["mode"] = "extend"
    payload["status"] = "completed"
    payload["route"] = "pass"
    payload["next_workflow"] = "ContinueUnit"
    _set_list_final_result_fields(payload)
    _set_list_route_handoff_fields(payload)
    _set_list_passing_gate_fields(payload)
    other_handoff_path = (
        Path(payload["route_handoff_path"]).parents[2]
        / "other-run"
        / "output"
        / "extend"
        / "route_handoff.json"
    )
    other_handoff_path.parent.mkdir(parents=True)
    other_handoff_path.write_text("{}", encoding="utf-8")
    payload["route_handoff_path"] = str(other_handoff_path)

    with pytest.raises(ValueError, match="artifact paths must share output directory"):
        _validate_list_json_row_payload(payload)


def _route_handoff(route: str | None, target: str) -> dict:
    source = "ReviewUnit" if route is not None else "RebuildUnit"
    reason = "review_completed" if route is not None else "reconstruction_complete"
    if route is None:
        input_anchor = {"source_text": "input.txt"}
        output_anchor = {"reconstructed_objects": {"WorkSpec": {}}}
        must_read_first = ["input.txt"]
        do_not_skip = ["review reconstructed object layers"]
    else:
        input_anchor = {"review_target_ref": "result.json"}
        output_anchor = {"state_ref": "ns_001"}
        must_read_first = ["result.json"]
        do_not_skip = ["honor ReviewIssue and ReviewReminder state"]
    change_set = []
    if route is None:
        change_set = [{"action": "create", "objects": ["WorkSpec"]}]
    else:
        change_set = [
            {
                "action": "review",
                "route": route,
                "issue_count": 0,
                "reminder_count": 0,
            }
        ]
    return {
        "handoff_header": {
            "source": source,
            "target": target,
            "reason": reason,
        },
        "input_anchor": input_anchor,
        "output_anchor": output_anchor,
        "change_set": change_set,
        "open_items": [],
        "confidence_and_gaps": {},
        "next_route": {
            "recommended_workflow": target,
            "route_reason": reason,
            "review_route": route,
            "must_read_first": must_read_first,
            "do_not_skip": do_not_skip,
        },
    }


def _review_reminder_open_item(**overrides) -> dict:
    item = {
        "type": "ReviewReminder",
        "reminder_id": "rem_handoff",
        "family": "missing_cost",
        "trigger_condition": "next unit still has no cost",
        "window": "plotunit_count=1_or_2",
        "escalation_issue_type": "missing_cost",
        "early_escalation_condition": "continued zero-cost operation",
        "closure_condition": "cost or accountability becomes explicit",
        "priority": "medium",
        "status": "active",
    }
    for key, value in overrides.items():
        if value is None:
            item.pop(key, None)
        else:
            item[key] = value
    return item


def _serialization_package(*, runnable_state: bool = True) -> dict:
    working_set = {}
    if runnable_state:
        working_set["NarrativeState"] = [
            {
                "state_id": "ns_001",
                "current_time": "now",
                "current_location": "room",
                "current_situation": "ready",
                "active_characters": [],
                "primary_goal": None,
                "active_conflicts": [],
                "emotional_temperature": None,
                "public_information": [],
                "hidden_information": [],
                "active_suspense_items": [],
                "current_goals": [],
                "linked_open_threads": [],
                "current_facts_in_scope": [],
            }
        ]
    return {
        "stable_memory": {},
        "working_set": working_set,
        "repair_control": {},
        "confidence": {},
        "metadata": {},
    }


def test_novel_audit_copies_input_and_uses_project_output(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")

    result = _run(["audit", "示例小说甲", "--input", str(source)], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    novel_dir = novels_root / "示例小说甲"
    assert (novel_dir / "input.txt").read_text(encoding="utf-8") == "短篇测试文本"
    assert (novel_dir / "mode.txt").read_text(encoding="utf-8") == "audit"
    config = json.loads((novel_dir / "run_config.json").read_text(encoding="utf-8"))
    assert config["mode"] == "audit"
    assert (novel_dir / "output" / "audit" / "rebuild_prompt.txt").exists()
    assert "[WAITING]" in result.stdout


def test_novel_extend_passes_long_form_options(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(_chapter_text(5), encoding="utf-8")

    result = _run(
        [
            "extend",
            "示例小说乙",
            "--input",
            str(source),
            "--chapter-wise",
            "--range",
            "1-3",
            "--batch-size",
            "2",
            "--max-chapters",
            "200",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output_dir = novels_root / "示例小说乙" / "output" / "extend"
    config = json.loads(
        (novels_root / "示例小说乙" / "run_config.json").read_text(encoding="utf-8")
    )
    assert config["chapter_range"] == "1-3"
    assert config["batch_size"] == 2
    assert config["max_chapters"] == 200
    assert not (output_dir / "outline_prompt.txt").exists()
    assert (output_dir / "extend_batch_001_002_rebuild_prompt.txt").exists()
    assert (output_dir / "extend_batch_003_003_rebuild_prompt.txt").exists()


def test_novel_flows_use_separate_output_dirs(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("short shared input", encoding="utf-8")

    audit = _run(["audit", "shared-name", "--input", str(source)], novels_root)
    extend = _run(["extend", "shared-name", "--input", str(source)], novels_root)

    assert audit.returncode == 0, audit.stdout + audit.stderr
    assert extend.returncode == 0, extend.stdout + extend.stderr
    novel_dir = novels_root / "shared-name"
    assert (novel_dir / "output" / "audit" / "rebuild_prompt.txt").exists()
    assert (novel_dir / "output" / "extend" / "rebuild_prompt.txt").exists()
    assert not (novel_dir / "output" / "rebuild_prompt.txt").exists()


def test_novel_audit_hash_mismatch_preserves_workspace_input(tmp_path):
    from src.boundary_control.runtime_identity import file_content_hash

    novels_root = tmp_path / "novels"
    source_a = tmp_path / "source_a.txt"
    source_b = tmp_path / "source_b.txt"
    source_a.write_text("original input", encoding="utf-8")
    source_b.write_text("changed input", encoding="utf-8")

    first = _run(["audit", "hash-guard", "--input", str(source_a)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    novel_dir = novels_root / "hash-guard"
    output_dir = novel_dir / "output" / "audit"
    (output_dir / "rebuild_response.txt").write_text('{"preserve": true}', encoding="utf-8")
    assert (output_dir / ".input_hash").read_text(encoding="utf-8") == file_content_hash(
        source_a
    )

    second = _run(["audit", "hash-guard", "--input", str(source_b)], novels_root)

    assert second.returncode == 1
    assert "hash mismatch" in second.stdout
    assert (novel_dir / "input.txt").read_text(encoding="utf-8") == "original input"
    assert (output_dir / "rebuild_response.txt").read_text(encoding="utf-8") == (
        '{"preserve": true}'
    )


def test_novel_compose_hash_mismatch_preserves_workspace_workspec(tmp_path):
    novels_root = tmp_path / "novels"
    workspec_a = tmp_path / "workspec_a.json"
    workspec_b = tmp_path / "workspec_b.json"
    workspec_a.write_text(
        json.dumps(
            {
                "genre": "fantasy",
                "audience": "young adult",
                "theme": "growth",
                "tone": "restrained",
                "pacing": "steady",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    workspec_b.write_text(
        json.dumps(
            {
                "genre": "mystery",
                "audience": "adult",
                "theme": "truth",
                "tone": "tense",
                "pacing": "fast",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = _run(["compose", "hash-guard-compose", "--workspec", str(workspec_a)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    novel_dir = novels_root / "hash-guard-compose"
    output_dir = novel_dir / "output" / "compose"
    (output_dir / "compose_continue_response.txt").write_text(
        '{"preserve": true}', encoding="utf-8"
    )

    second = _run(["compose", "hash-guard-compose", "--workspec", str(workspec_b)], novels_root)

    assert second.returncode == 1
    assert "WorkSpec hash mismatch" in second.stdout
    saved = json.loads((novel_dir / "workspec.json").read_text(encoding="utf-8"))
    assert saved["genre"] == "fantasy"
    assert (output_dir / "compose_continue_response.txt").read_text(encoding="utf-8") == (
        '{"preserve": true}'
    )


def test_novel_cli_rejects_invalid_long_form_options_before_config(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(_chapter_text(2), encoding="utf-8")

    result = _run(
        ["extend", "bad-options", "--input", str(source), "--batch-size", "0"],
        novels_root,
    )

    assert result.returncode == 1
    assert "invalid --batch-size" in result.stdout
    assert not (novels_root / "bad-options" / "run_config.json").exists()


def test_novel_compose_accepts_workspec_and_writes_mode(tmp_path):
    novels_root = tmp_path / "novels"
    workspec = tmp_path / "workspec.json"
    workspec.write_text(
        json.dumps(
            {
                "genre": "仙侠",
                "audience": "青年",
                "theme": "成长",
                "tone": "克制",
                "pacing": "前快中稳后爆",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run(["compose", "仙侠新作", "--workspec", str(workspec)], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    novel_dir = novels_root / "仙侠新作"
    assert (novel_dir / "workspec.json").exists()
    assert (novel_dir / "mode.txt").read_text(encoding="utf-8") == "compose"
    assert (novel_dir / "output" / "compose" / "compose_continue_prompt.txt").exists()


def test_novel_style_accepts_input_and_writes_mode(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(_chapter_text(2), encoding="utf-8")

    result = _run(["style", "风格样书", "--input", str(source)], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    novel_dir = novels_root / "风格样书"
    assert (novel_dir / "mode.txt").read_text(encoding="utf-8") == "style"
    style_output = novel_dir / "output" / "style"
    assert (style_output / "style_extract_prompt.txt").exists()
    assert (style_output / ".input_hash").exists()


def test_novel_style_resume_uses_saved_style_mode(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(_chapter_text(2), encoding="utf-8")
    first = _run(["style", "风格样书", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    novel_dir = novels_root / "风格样书"
    style_output = novel_dir / "output" / "style"
    style_output.joinpath("style_extract_response.txt").write_text(
        json.dumps(
            {
                "tone_labels": ["克制"],
                "genre_guess": "古典仙侠",
                "narrative_pov": "第三人称有限",
                "pacing_description": "叙述默认长句，情绪爆点短句独立成段",
                "sentence_habits": ["情绪靠身体反应"],
                "rhetorical_preferences": ["具象物比喻"],
                "show_dont_tell_notes": ["恐惧→冷汗/攥拳"],
                "closed_loop_objects": ["那本书"],
                "chapter_end_hook_notes": ["章末留疑问钩"],
                "taboo_words": ["轻轻", "淡淡"],
                "style_references": ["tone_kz_01"],
                "confidence_gaps": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run(["resume", "风格样书"], novels_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (style_output / "style_profile.json").exists()


def test_novel_list_reports_style_waiting_tasks(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(_chapter_text(2), encoding="utf-8")
    first = _run(["style", "风格样书", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "风格样书" in result.stdout
    assert "style" in result.stdout
    assert "[WAITING: style_extract_response.txt]" in result.stdout


def test_cli_style_mode_contract_maps():
    from src.novel_cli import (
        VALID_MODES,
        _expected_final_result_name,
        _expected_gate_package_name,
    )

    assert "style" in VALID_MODES
    assert _expected_gate_package_name("style") == "style_profile.json"
    assert _expected_final_result_name("style") == "style_profile.json"


def test_cli_rubric_mode_contract_maps():
    from src.novel_cli import (
        JSON_ERROR_COMMANDS,
        VALID_MODES,
        _expected_final_result_name,
        _expected_gate_package_name,
    )

    assert "rubric" in VALID_MODES
    assert "rubric" in JSON_ERROR_COMMANDS
    # rubric 永不 gate，防御性映射为 rubric.json
    assert _expected_gate_package_name("rubric") == "rubric.json"
    assert _expected_final_result_name("rubric") == "rubric.json"


def test_cli_rubric_writes_eight_dimension_report(tmp_path):
    import json as json_mod

    novels_root = tmp_path / "novels"
    result = _run(["rubric", "评测样书"], novels_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rubric" in result.stdout
    assert "Saved" in result.stdout

    report_path = (
        novels_root / "评测样书" / "output" / "rubric" / "rubric.json"
    )
    assert report_path.exists()
    report = json_mod.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["benchmark"] == "WebNovelBench"
    assert report["offline"] is True
    assert len(report["dimensions"]) == 8


def test_novel_list_reports_waiting_tasks(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "示例小说甲", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "示例小说甲" in result.stdout
    assert "audit" in result.stdout
    assert "waiting" in result.stdout
    assert "[WAITING: rebuild_response.txt]" in result.stdout


def test_novel_list_json_reports_tasks(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    waiting = _run(["audit", "waiting-json", "--input", str(source)], novels_root)
    assert waiting.returncode == 0, waiting.stdout + waiting.stderr

    done_dir = novels_root / "done-json"
    done_output = done_dir / "output" / "extend"
    done_output.mkdir(parents=True)
    (done_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (done_output / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )

    multi_dir = novels_root / "multi-json"
    multi_output = multi_dir / "output" / "extend"
    multi_output.mkdir(parents=True)
    (multi_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (multi_output / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (multi_output / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    by_name = {row["name"]: row for row in payload}
    assert tuple(by_name["waiting-json"]) == LIST_JSON_ROW_FIELDS
    assert by_name["waiting-json"]["schema_version"] == 1
    assert by_name["waiting-json"]["command"] == "list"
    assert isinstance(by_name["waiting-json"]["latest_mtime"], int | float)
    assert by_name["waiting-json"]["mode"] == "audit"
    assert by_name["waiting-json"]["status"] == "waiting"
    assert by_name["waiting-json"]["detail"] == "[WAITING: rebuild_response.txt]"
    assert by_name["waiting-json"]["pending_count"] == 1
    assert by_name["waiting-json"]["pending_prompt_file"] == "rebuild_prompt.txt"
    assert by_name["waiting-json"]["pending_response_file"] == "rebuild_response.txt"
    assert by_name["waiting-json"]["pending_prompt_path"].endswith(
        "rebuild_prompt.txt"
    )
    assert by_name["waiting-json"]["pending_response_path"].endswith(
        "rebuild_response.txt"
    )
    expected_prompt_hash = hashlib.md5(
        (
            novels_root
            / "waiting-json"
            / "output"
            / "audit"
            / "rebuild_prompt.txt"
        ).read_bytes()
    ).hexdigest()
    assert by_name["waiting-json"]["pending_prompt_hash"] == expected_prompt_hash
    assert by_name["waiting-json"]["pending_prompt_bytes"] == len(
        (
            novels_root
            / "waiting-json"
            / "output"
            / "audit"
            / "rebuild_prompt.txt"
        ).read_bytes()
    )
    assert isinstance(by_name["waiting-json"]["pending_prompt_mtime"], int | float)
    assert by_name["waiting-json"]["pending_slot_id"] == "rebuild"
    for key, value in pending_automation_metadata(pending_count=1).items():
        assert by_name["waiting-json"][key] == value
    validate_pending_automation_metadata_in_payload(
        by_name["waiting-json"],
        pending_count=1,
    )
    with pytest.raises(ValueError, match="pending_count"):
        pending_automation_metadata(pending_count=-1)
    with pytest.raises(ValueError, match="automation_ready"):
        validate_pending_automation_metadata_in_payload(
            by_name["waiting-json"],
            pending_count=0,
        )
    assert by_name["waiting-json"]["route"] is None
    assert by_name["waiting-json"]["next_workflow"] is None
    assert by_name["waiting-json"]["final_result_file"] is None
    assert by_name["waiting-json"]["final_result_path"] is None
    assert by_name["waiting-json"]["route_handoff_file"] is None
    assert by_name["waiting-json"]["route_handoff_path"] is None
    assert by_name["multi-json"]["mode"] == "extend"
    assert by_name["multi-json"]["schema_version"] == 1
    assert by_name["multi-json"]["command"] == "list"
    assert by_name["multi-json"]["status"] == "waiting"
    assert by_name["multi-json"]["pending_count"] == 2
    assert by_name["multi-json"]["pending_slot_id"] in {"continue", "review"}
    assert (
        by_name["multi-json"]["automation_contract_version"]
        == PENDING_AUTOMATION_CONTRACT_VERSION
    )
    assert by_name["multi-json"]["automation_contract"] == PENDING_AUTOMATION_CONTRACT
    assert by_name["multi-json"]["automation_ready"] is False
    assert (
        by_name["multi-json"]["automation_ready_reason"]
        == PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    )
    assert by_name["multi-json"]["automation_blockers"] == [
        PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    ]
    assert (
        by_name["multi-json"]["allowed_automation_action"]
        == PENDING_AUTOMATION_ACTION
    )
    assert (
        by_name["multi-json"]["provider_calls_implemented"]
        is PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED
    )
    assert (
        by_name["multi-json"]["closed_loop_allowed"]
        is PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED
    )
    validate_pending_automation_metadata_in_payload(
        by_name["multi-json"],
        pending_count=2,
    )
    assert by_name["done-json"]["mode"] == "extend"
    assert by_name["done-json"]["schema_version"] == 1
    assert by_name["done-json"]["command"] == "list"
    assert by_name["done-json"]["status"] == "completed"
    assert by_name["done-json"]["detail"] == "route=pass"
    assert by_name["done-json"]["route"] == "pass"
    assert by_name["done-json"]["next_workflow"] is None
    assert by_name["done-json"]["final_result_file"] == "extend_result.json"
    assert by_name["done-json"]["final_result_path"].endswith("extend_result.json")
    assert by_name["done-json"]["route_handoff_file"] is None
    assert by_name["done-json"]["route_handoff_path"] is None
    assert by_name["done-json"]["pending_count"] == 0
    assert by_name["done-json"]["pending_prompt_file"] is None
    assert by_name["done-json"]["pending_response_file"] is None
    assert by_name["done-json"]["pending_prompt_hash"] is None
    assert by_name["done-json"]["pending_prompt_bytes"] is None
    assert by_name["done-json"]["pending_prompt_mtime"] is None
    assert by_name["done-json"]["pending_slot_id"] is None
    assert (
        by_name["done-json"]["automation_contract_version"]
        == PENDING_AUTOMATION_CONTRACT_VERSION
    )
    assert by_name["done-json"]["automation_contract"] == PENDING_AUTOMATION_CONTRACT
    assert by_name["done-json"]["automation_ready"] is False
    assert (
        by_name["done-json"]["automation_ready_reason"]
        == PENDING_AUTOMATION_BLOCKER_NO_PENDING
    )
    assert by_name["done-json"]["automation_blockers"] == [
        PENDING_AUTOMATION_BLOCKER_NO_PENDING
    ]
    assert (
        by_name["done-json"]["allowed_automation_action"]
        == PENDING_AUTOMATION_ACTION
    )
    assert (
        by_name["done-json"]["provider_calls_implemented"]
        is PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED
    )
    assert (
        by_name["done-json"]["closed_loop_allowed"]
        is PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED
    )
    validate_pending_automation_metadata_in_payload(
        by_name["done-json"],
        pending_count=0,
    )
    assert isinstance(by_name["done-json"]["latest_date"], str)
    assert isinstance(by_name["done-json"]["latest_mtime"], int | float)


def test_novel_list_json_reports_empty_root(tmp_path):
    novels_root = tmp_path / "missing-root"

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == []


def test_novel_pending_lists_waiting_response_slots(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "pending-audit", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(["pending", "pending-audit"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "audit\trebuild_prompt.txt\trebuild_response.txt" in result.stdout


def test_novel_pending_json_lists_waiting_response_slots(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "pending-json", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(["pending", "pending-json", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert tuple(payload) == PENDING_JSON_FIELDS
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["command"] == "pending"
    assert payload["novel"] == "pending-json"
    assert payload["mode"] == "audit"
    assert payload["selection_method"] == "all_pending"
    assert payload["pending_count"] == 1
    assert tuple(payload["pending"][0]) == PENDING_SLOT_FIELDS
    assert payload["pending"][0]["prompt_file"] == "rebuild_prompt.txt"
    assert payload["pending"][0]["response_file"] == "rebuild_response.txt"
    assert payload["pending"][0]["prompt_path"].endswith("rebuild_prompt.txt")
    assert payload["pending"][0]["response_path"].endswith("rebuild_response.txt")
    assert isinstance(payload["pending"][0]["prompt_mtime"], float)
    assert payload["pending"][0]["slot_id"] == "rebuild"
    prompt_path = Path(payload["pending"][0]["prompt_path"])
    assert payload["pending"][0]["prompt_hash"] == hashlib.md5(
        prompt_path.read_bytes()
    ).hexdigest()
    assert payload["pending"][0]["prompt_bytes"] == len(prompt_path.read_bytes())


def test_novel_pending_json_honors_newer_than_filter(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-newer-than"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    old_prompt = output_dir / "continue_prompt.txt"
    new_prompt = output_dir / "review_prompt.txt"
    old_prompt.write_text("continue", encoding="utf-8")
    new_prompt.write_text("review", encoding="utf-8")
    os.utime(old_prompt, (1_700_000_000, 1_700_000_000))
    os.utime(new_prompt, (1_700_000_100, 1_700_000_100))

    result = _run(
        [
            "pending",
            "pending-newer-than",
            "--newer-than",
            "1700000050",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["newer_than"] == 1_700_000_050
    assert payload["pending_count"] == 1
    assert payload["pending"][0]["slot_id"] == "review"
    assert payload["pending"][0]["prompt_file"] == "review_prompt.txt"


def test_novel_pending_slot_id_honors_newer_than_filter(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-newer-than"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path = output_dir / "review_prompt.txt"
    prompt_path.write_text("review", encoding="utf-8")
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))

    result = _run(
        [
            "pending",
            "pending-slot-newer-than",
            "--slot-id",
            "review",
            "--newer-than",
            "1700000100",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "pending response slot not found" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_json_filters_prompts_older_than_route_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-route-cutoff"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path = output_dir / "review_prompt.txt"
    final_path = output_dir / "extend_result.json"
    handoff_path = output_dir / "route_handoff.json"
    prompt_path.write_text("stale review prompt", encoding="utf-8")
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    os.utime(handoff_path, (1_700_000_200, 1_700_000_200))

    result = _run(["pending", "pending-route-cutoff", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["newer_than"] is None
    assert payload["route_artifact_mtime"] == 1_700_000_200
    assert payload["effective_newer_than"] == 1_700_000_200
    assert payload["pending_count"] == 0
    assert payload["pending"] == []
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_slot_id_rejects_prompt_older_than_route_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-route-cutoff"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path = output_dir / "review_prompt.txt"
    final_path = output_dir / "extend_result.json"
    handoff_path = output_dir / "route_handoff.json"
    prompt_path.write_text("stale review prompt", encoding="utf-8")
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))
    os.utime(handoff_path, (1_700_000_200, 1_700_000_200))

    result = _run(
        ["pending", "pending-slot-route-cutoff", "--slot-id", "review", "--json"],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "pending response slot not found" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_json_rejects_invalid_final_route_artifact(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-invalid-final-route"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "unknown"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["pending", "pending-invalid-final-route", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "invalid result route" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_json_rejects_route_handoff_mismatch_before_filtering(
    tmp_path,
):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-route-mismatch"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["pending", "pending-route-mismatch", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "route handoff mismatch" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


@pytest.mark.parametrize("newer_than", ["-1", "nan", "inf"])
def test_novel_pending_rejects_invalid_newer_than_as_json_error(
    tmp_path,
    newer_than,
):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / f"pending-invalid-newer-than-{newer_than}"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(
        [
            "pending",
            f"pending-invalid-newer-than-{newer_than}",
            "--newer-than",
            newer_than,
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "newer_than must be a finite non-negative number" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_reports_no_pending_slots(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "done"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    (output_dir / "review_response.txt").write_text("response", encoding="utf-8")

    result = _run(["pending", "done"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No pending response slots: mode=audit" in result.stdout


def test_novel_pending_json_reports_empty_pending_slots(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "done-json"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    (output_dir / "review_response.txt").write_text("response", encoding="utf-8")

    result = _run(["pending", "done-json", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["novel"] == "done-json"
    assert payload["mode"] == "audit"
    assert payload["pending_count"] == 0
    assert (
        payload["automation_contract_version"]
        == PENDING_AUTOMATION_CONTRACT_VERSION
    )
    assert payload["automation_contract"] == PENDING_AUTOMATION_CONTRACT
    assert payload["automation_ready"] is False
    assert payload["automation_ready_reason"] == PENDING_AUTOMATION_BLOCKER_NO_PENDING
    assert payload["automation_blockers"] == [PENDING_AUTOMATION_BLOCKER_NO_PENDING]
    assert payload["allowed_automation_action"] == PENDING_AUTOMATION_ACTION
    assert (
        payload["provider_calls_implemented"]
        is PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED
    )
    assert payload["closed_loop_allowed"] is PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED
    validate_pending_automation_metadata_in_payload(
        payload,
        pending_count=0,
    )
    assert payload["pending"] == []


def test_novel_pending_json_validates_metadata_before_emit(tmp_path, monkeypatch):
    import src.novel_cli as novel_cli

    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-validate-before-emit"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )

    def reject_metadata(payload, *, pending_count):
        raise ValueError("pending metadata validation called")

    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    monkeypatch.setattr(
        novel_cli,
        "validate_pending_automation_metadata_in_payload",
        reject_metadata,
    )

    with pytest.raises(ValueError, match="pending metadata validation called"):
        novel_cli._run_pending(
            Namespace(
                novel="pending-validate-before-emit",
                slot_id=None,
                prompt_hash=None,
                newer_than=None,
                require_automation_ready=False,
                json=True,
            )
        )


def test_novel_pending_json_require_automation_ready_rejects_empty_slots(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "done-json-require-ready"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    (output_dir / "review_response.txt").write_text("response", encoding="utf-8")

    result = _run(
        [
            "pending",
            "done-json-require-ready",
            "--require-automation-ready",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert tuple(payload) == PENDING_JSON_ERROR_FIELDS
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["command"] == "pending"
    assert payload["pending_count"] == 0
    assert payload["automation_ready"] is False
    assert payload["automation_ready_reason"] == PENDING_AUTOMATION_BLOCKER_NO_PENDING
    assert payload["automation_blockers"] == [PENDING_AUTOMATION_BLOCKER_NO_PENDING]
    assert payload["error_stage"] == "runtime"
    assert payload["error_type"] == "ValueError"
    assert PENDING_AUTOMATION_BLOCKER_NO_PENDING in payload["error"]
    assert payload["pending"] == []


def test_novel_pending_ignores_completed_invalid_prompt_bytes(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-skip-done"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_bytes(b"\xff")
    (output_dir / "review_response.txt").write_text("done", encoding="utf-8")
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")

    result = _run(["pending", "pending-skip-done", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["pending_count"] == 1
    assert payload["pending"][0]["slot_id"] == "continue"
    assert payload["pending"][0]["prompt_file"] == "continue_prompt.txt"


def test_novel_pending_requires_saved_mode(tmp_path):
    novels_root = tmp_path / "novels"
    (novels_root / "no-mode").mkdir(parents=True)

    result = _run(["pending", "no-mode"], novels_root)

    assert result.returncode == 1
    assert "missing saved mode" in result.stdout


def test_novel_pending_json_reports_runtime_errors_as_json(tmp_path):
    novels_root = tmp_path / "novels"
    (novels_root / "no-mode-json").mkdir(parents=True)

    result = _run(["pending", "no-mode-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert tuple(payload) == (
        "ok",
        "schema_version",
        "command",
        "novel",
        "error_stage",
        "error_type",
        "error",
    )
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["command"] == "pending"
    assert payload["novel"] == "no-mode-json"
    assert payload["error_stage"] == "runtime"
    assert payload["error_type"] == "ValueError"
    assert "missing saved mode" in payload["error"]
    assert "Error:" not in result.stdout


def test_novel_pending_json_rejects_empty_prompt_as_contract_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "empty-prompt-json"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("  ", encoding="utf-8")

    result = _run(["pending", "empty-prompt-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "prompt file must be non-empty" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_lists_multiple_slots_without_guessing(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "multi"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(["pending", "multi"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "extend\tcontinue_prompt.txt\tcontinue_response.txt" in result.stdout
    assert "extend\treview_prompt.txt\treview_response.txt" in result.stdout


def test_novel_pending_can_select_slot_id(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(["pending", "pending-slot", "--slot-id", "review", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["slot_id"] == "review"
    assert payload["selection_method"] == "slot_id"
    assert payload["pending_count"] == 1
    assert payload["pending"][0]["slot_id"] == "review"
    assert payload["pending"][0]["prompt_file"] == "review_prompt.txt"
    assert payload["pending"][0]["prompt_bytes"] == len(b"review")
    assert not (output_dir / "continue_response.txt").exists()
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_slot_id_accepts_matching_prompt_hash(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-hash"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path = output_dir / "review_prompt.txt"
    prompt_path.write_text("review", encoding="utf-8")
    prompt_hash = hashlib.md5(prompt_path.read_bytes()).hexdigest()

    result = _run(
        [
            "pending",
            "pending-slot-hash",
            "--slot-id",
            "review",
            "--prompt-hash",
            prompt_hash,
            "--require-automation-ready",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["slot_id"] == "review"
    assert payload["selection_method"] == "slot_id"
    assert payload["expected_prompt_hash"] == prompt_hash
    assert payload["prompt_hash_verified"] is True
    assert (
        payload["automation_contract_version"]
        == PENDING_AUTOMATION_CONTRACT_VERSION
    )
    assert payload["automation_contract"] == PENDING_AUTOMATION_CONTRACT
    assert payload["automation_ready"] is True
    assert payload["automation_ready_reason"] == PENDING_AUTOMATION_REASON_READY
    assert payload["automation_blockers"] == []
    assert payload["allowed_automation_action"] == PENDING_AUTOMATION_ACTION
    assert (
        payload["provider_calls_implemented"]
        is PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED
    )
    assert payload["closed_loop_allowed"] is PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED
    assert payload["pending"][0]["prompt_hash"] == prompt_hash
    assert payload["pending"][0]["prompt_bytes"] == len(b"review")
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_json_marks_multiple_slots_not_automation_ready(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-multi-readiness"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(
        [
            "pending",
            "pending-multi-readiness",
            "--require-automation-ready",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["pending_count"] == 2
    assert (
        payload["automation_contract_version"]
        == PENDING_AUTOMATION_CONTRACT_VERSION
    )
    assert payload["automation_contract"] == PENDING_AUTOMATION_CONTRACT
    assert payload["automation_ready"] is False
    assert (
        payload["automation_ready_reason"]
        == PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    )
    assert payload["automation_blockers"] == [
        PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    ]
    assert payload["allowed_automation_action"] == PENDING_AUTOMATION_ACTION
    assert (
        payload["provider_calls_implemented"]
        is PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED
    )
    assert payload["closed_loop_allowed"] is PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED
    validate_pending_automation_metadata_in_payload(
        payload,
        pending_count=2,
    )
    assert payload["error_stage"] == "runtime"
    assert payload["error_type"] == "ValueError"
    assert PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING in payload["error"]
    assert not (output_dir / "continue_response.txt").exists()
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_slot_id_rejects_prompt_hash_mismatch(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-hash-mismatch"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    wrong_hash = hashlib.md5(b"other").hexdigest()

    result = _run(
        [
            "pending",
            "pending-slot-hash-mismatch",
            "--slot-id",
            "review",
            "--prompt-hash",
            wrong_hash,
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "prompt hash mismatch" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_rejects_prompt_hash_without_slot_id(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-hash-without-slot"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(
        [
            "pending",
            "pending-hash-without-slot",
            "--prompt-hash",
            hashlib.md5(b"review").hexdigest(),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "--prompt-hash requires --slot-id" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_slot_id_rejects_invalid_prompt_hash(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-invalid-hash"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(
        [
            "pending",
            "pending-slot-invalid-hash",
            "--slot-id",
            "review",
            "--prompt-hash",
            "wrong-hash",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "invalid expected_prompt_hash" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_rejects_missing_slot_id_as_json_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-missing-slot"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")

    result = _run(
        ["pending", "pending-missing-slot", "--slot-id", "continue", "--json"],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "pending response slot not found" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_pending_slot_id_ignores_completed_invalid_prompt_bytes(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "pending-slot-done-invalid"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_bytes(b"\xff")
    (output_dir / "review_response.txt").write_text("done", encoding="utf-8")

    result = _run(
        [
            "pending",
            "pending-slot-done-invalid",
            "--slot-id",
            "review",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "pending response slot not found" in payload["error"]
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == "done"


def test_novel_respond_materializes_single_pending_slot(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    response_source.write_text('{"objects": [], "confidence_gaps": []}', encoding="utf-8")
    first = _run(["audit", "respond-audit", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(
        ["respond", "respond-audit", "--response-file", str(response_source)],
        novels_root,
    )

    output_dir = novels_root / "respond-audit" / "output" / "audit"
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Response saved: mode=audit prompt=rebuild_prompt.txt" in result.stdout
    assert (output_dir / "rebuild_response.txt").read_text(encoding="utf-8") == (
        '{"objects": [], "confidence_gaps": []}'
    )


def test_novel_respond_ignores_completed_invalid_prompt_bytes(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-skip-done"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_bytes(b"\xff")
    (output_dir / "review_response.txt").write_text("done", encoding="utf-8")
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    response_source.write_text("continue response", encoding="utf-8")

    result = _run(
        ["respond", "respond-skip-done", "--response-file", str(response_source)],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Response saved: mode=extend prompt=continue_prompt.txt" in result.stdout
    assert (output_dir / "continue_response.txt").read_text(encoding="utf-8") == (
        "continue response"
    )
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == "done"


def test_novel_respond_slot_id_ignores_completed_invalid_prompt_bytes(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-slot-done-invalid"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_bytes(b"\xff")
    (output_dir / "review_response.txt").write_text("done", encoding="utf-8")
    response_source.write_text("new response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-slot-done-invalid",
            "--response-file",
            str(response_source),
            "--slot-id",
            "review",
            "--json",
        ],
        novels_root,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "pending response slot not found" in payload["error"]
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == "done"


def test_novel_respond_default_rejects_prompt_older_than_route_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-route-cutoff"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("stale continue", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    response_source.write_text("continue response", encoding="utf-8")
    os.utime(output_dir / "continue_prompt.txt", (1_700_000_000, 1_700_000_000))
    os.utime(output_dir / "extend_result.json", (1_700_000_100, 1_700_000_100))
    os.utime(output_dir / "route_handoff.json", (1_700_000_200, 1_700_000_200))

    result = _run(
        [
            "respond",
            "respond-route-cutoff",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "no pending response slot found" in payload["error"]
    assert not (output_dir / "continue_response.txt").exists()


def test_novel_respond_slot_id_rejects_prompt_older_than_route_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-slot-route-cutoff"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("stale review", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    response_source.write_text("review response", encoding="utf-8")
    os.utime(output_dir / "review_prompt.txt", (1_700_000_000, 1_700_000_000))
    os.utime(output_dir / "extend_result.json", (1_700_000_100, 1_700_000_100))
    os.utime(output_dir / "route_handoff.json", (1_700_000_200, 1_700_000_200))

    result = _run(
        [
            "respond",
            "respond-slot-route-cutoff",
            "--response-file",
            str(response_source),
            "--slot-id",
            "review",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "pending response slot not found" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_prompt_rejects_prompt_older_than_route_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-prompt-route-cutoff"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("stale review", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    response_source.write_text("review response", encoding="utf-8")
    os.utime(output_dir / "review_prompt.txt", (1_700_000_000, 1_700_000_000))
    os.utime(output_dir / "extend_result.json", (1_700_000_100, 1_700_000_100))
    os.utime(output_dir / "route_handoff.json", (1_700_000_200, 1_700_000_200))

    result = _run(
        [
            "respond",
            "respond-prompt-route-cutoff",
            "--response-file",
            str(response_source),
            "--prompt",
            "review_prompt.txt",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "pending prompt is older than current route artifact" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_invalid_final_route_artifact_before_write(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-invalid-final-route"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "unknown"}, ensure_ascii=False),
        encoding="utf-8",
    )
    response_source.write_text("review response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-invalid-final-route",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "invalid result route" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_json_reports_materialized_response_without_content(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.json"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "respond-json", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    response_source.write_text('{"objects": [], "confidence_gaps": []}', encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-json",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert tuple(payload) == RESPOND_JSON_FIELDS
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["command"] == "respond"
    assert payload["novel"] == "respond-json"
    assert payload["mode"] == "audit"
    assert payload["prompt_file"] == "rebuild_prompt.txt"
    assert payload["response_file"] == "rebuild_response.txt"
    assert payload["prompt_path"].endswith("rebuild_prompt.txt")
    assert payload["response_path"].endswith("rebuild_response.txt")
    assert payload["response_source"] == str(response_source.resolve())
    for key, value in response_materialization_metadata().items():
        assert payload[key] == value
    assert payload["selection_method"] == "single_pending"
    assert payload["expected_prompt_hash"] is None
    assert payload["prompt_hash_verified"] is False
    prompt_path = Path(payload["prompt_path"])
    response_path = Path(payload["response_path"])
    assert payload["prompt_hash"] == hashlib.md5(prompt_path.read_bytes()).hexdigest()
    assert payload["prompt_bytes"] == len(prompt_path.read_bytes())
    assert payload["slot_id"] == "rebuild"
    assert payload["response_source_hash"] == hashlib.md5(
        response_source.read_bytes()
    ).hexdigest()
    assert payload["response_source_bytes"] == len(response_source.read_bytes())
    assert payload["response_hash"] == hashlib.md5(response_path.read_bytes()).hexdigest()
    assert payload["response_bytes"] == len(response_path.read_bytes())
    assert payload["response_chars"] == len(
        '{"objects": [], "confidence_gaps": []}'
    )
    assert "objects" not in payload
    assert "confidence_gaps" not in payload


def test_novel_respond_json_validates_materialization_metadata_before_emit(
    tmp_path,
    monkeypatch,
):
    import src.novel_cli as novel_cli

    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-validate-before-emit"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.json"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "rebuild_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_text('{"objects": []}', encoding="utf-8")

    def reject_metadata(payload):
        raise ValueError("materialization metadata validation called")

    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    monkeypatch.setattr(
        novel_cli,
        "validate_response_materialization_metadata_in_payload",
        reject_metadata,
    )

    with pytest.raises(
        ValueError,
        match="materialization metadata validation called",
    ):
        novel_cli._run_respond(
            Namespace(
                novel="respond-validate-before-emit",
                response_file=str(response_source),
                prompt=None,
                slot_id=None,
                prompt_hash=None,
                json=True,
            )
        )


def test_novel_respond_json_preserves_lf_response_source_bytes(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "respond-lf-json", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    response_source.write_bytes(b"line1\nline2")

    result = _run(
        [
            "respond",
            "respond-lf-json",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    response_path = Path(payload["response_path"])
    assert response_path.read_bytes() == b"line1\nline2"
    assert payload["response_source_hash"] == hashlib.md5(b"line1\nline2").hexdigest()
    assert payload["response_source_bytes"] == len(b"line1\nline2")
    assert payload["response_hash"] == hashlib.md5(b"line1\nline2").hexdigest()
    assert payload["response_bytes"] == len(b"line1\nline2")
    assert payload["response_chars"] == len("line1\nline2")


def test_read_text_with_hash_binds_hash_to_consumed_response_bytes(
    tmp_path,
    monkeypatch,
):
    import src.novel_cli as novel_cli

    response_source = tmp_path / "response.txt"
    response_source.write_text("old response", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_then_mutate(path):
        data = original_read_bytes(path)
        if path == response_source:
            response_source.write_text("changed response", encoding="utf-8")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_mutate)

    response_text, response_hash, response_bytes = novel_cli._read_text_with_hash(
        response_source
    )

    assert response_text == "old response"
    assert response_hash == hashlib.md5(b"old response").hexdigest()
    assert response_bytes == len(b"old response")
    assert response_source.read_text(encoding="utf-8") == "changed response"


def test_novel_respond_accepts_matching_prompt_hash(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "respond-hash", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    response_source.write_text("response", encoding="utf-8")
    prompt_path = (
        novels_root
        / "respond-hash"
        / "output"
        / "audit"
        / "rebuild_prompt.txt"
    )
    prompt_hash = hashlib.md5(prompt_path.read_bytes()).hexdigest()

    result = _run(
        [
            "respond",
            "respond-hash",
            "--response-file",
            str(response_source),
            "--prompt-hash",
            prompt_hash,
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["selection_method"] == "single_pending"
    assert payload["expected_prompt_hash"] == prompt_hash
    assert payload["prompt_hash_verified"] is True
    assert payload["prompt_hash"] == prompt_hash
    assert payload["prompt_bytes"] == len(prompt_path.read_bytes())
    assert (
        novels_root
        / "respond-hash"
        / "output"
        / "audit"
        / "rebuild_response.txt"
    ).read_text(encoding="utf-8") == "response"


def test_novel_respond_rejects_prompt_file_as_response_source(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["audit", "respond-prompt-source", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    prompt_path = (
        novels_root
        / "respond-prompt-source"
        / "output"
        / "audit"
        / "rebuild_prompt.txt"
    )
    response_path = (
        novels_root
        / "respond-prompt-source"
        / "output"
        / "audit"
        / "rebuild_response.txt"
    )

    result = _run(
        [
            "respond",
            "respond-prompt-source",
            "--response-file",
            str(prompt_path),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "response source file must not be the staged prompt file" in payload["error"]
    assert not response_path.exists()


def test_novel_respond_rejects_prompt_hardlink_as_response_source(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(
        ["audit", "respond-prompt-hardlink-source", "--input", str(source)],
        novels_root,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    prompt_path = (
        novels_root
        / "respond-prompt-hardlink-source"
        / "output"
        / "audit"
        / "rebuild_prompt.txt"
    )
    response_path = (
        novels_root
        / "respond-prompt-hardlink-source"
        / "output"
        / "audit"
        / "rebuild_response.txt"
    )
    response_source = tmp_path / "prompt_alias.txt"
    os.link(prompt_path, response_source)

    result = _run(
        [
            "respond",
            "respond-prompt-hardlink-source",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "response source file must not be the staged prompt file" in payload["error"]
    assert not response_path.exists()


def test_novel_respond_binds_write_to_verified_prompt_hash(tmp_path, monkeypatch):
    import src.novel_cli as novel_cli

    class MutatingBoundary:
        def require_single_pending_slot(self, output_dir):
            prompt_path = output_dir / "review_prompt.txt"
            response_path = output_dir / "review_response.txt"
            return type(
                "Slot",
                (),
                {"prompt_path": prompt_path, "response_path": response_path},
            )()

        def verify_prompt_hash(self, prompt_path, expected_prompt_hash=None):
            prompt_hash = hashlib.md5(Path(prompt_path).read_bytes()).hexdigest()
            Path(prompt_path).write_text("changed prompt", encoding="utf-8")
            return prompt_hash

        def materialize_response(
            self,
            *,
            prompt_path,
            response_path,
            response_text,
            expected_prompt_hash=None,
        ):
            actual_hash = hashlib.md5(Path(prompt_path).read_bytes()).hexdigest()
            if expected_prompt_hash != actual_hash:
                raise ValueError(
                    f"prompt hash mismatch for {prompt_path}: "
                    f"expected {expected_prompt_hash}, actual {actual_hash}"
                )
            Path(response_path).write_text(response_text, encoding="utf-8")
            return response_path

    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "bind-respond"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("original prompt", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    monkeypatch.setattr(novel_cli, "ResponseFileBoundaryUnit", MutatingBoundary)

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        novel_cli._run_respond(
            Namespace(
                novel="bind-respond",
                response_file=str(response_source),
                prompt=None,
                prompt_hash=None,
                json=True,
            )
        )

    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_staged_response_mutation_before_json(
    tmp_path,
    monkeypatch,
):
    import src.novel_cli as novel_cli

    class MutatingResponseBoundary:
        def require_single_pending_slot(self, output_dir):
            prompt_path = output_dir / "review_prompt.txt"
            response_path = output_dir / "review_response.txt"
            return type(
                "Slot",
                (),
                {"prompt_path": prompt_path, "response_path": response_path},
            )()

        def verify_prompt_hash(self, prompt_path, expected_prompt_hash=None):
            return hashlib.md5(Path(prompt_path).read_bytes()).hexdigest()

        def materialize_response(
            self,
            *,
            prompt_path,
            response_path,
            response_text,
            expected_prompt_hash=None,
        ):
            Path(response_path).write_text(response_text, encoding="utf-8")
            Path(response_path).write_text("changed response", encoding="utf-8")
            return response_path

    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "mutated-response"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_text("original response", encoding="utf-8")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    monkeypatch.setattr(novel_cli, "ResponseFileBoundaryUnit", MutatingResponseBoundary)

    with pytest.raises(ValueError, match="staged response hash mismatch"):
        novel_cli._run_respond(
            Namespace(
                novel="mutated-response",
                response_file=str(response_source),
                prompt=None,
                slot_id=None,
                prompt_hash=None,
                json=True,
            )
        )

    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == (
        "changed response"
    )


def test_novel_respond_rejects_prompt_mutation_after_response_write(
    tmp_path,
    monkeypatch,
):
    import src.novel_cli as novel_cli

    class MutatingPromptAfterWriteBoundary:
        def require_single_pending_slot(self, output_dir):
            prompt_path = output_dir / "review_prompt.txt"
            response_path = output_dir / "review_response.txt"
            return type(
                "Slot",
                (),
                {"prompt_path": prompt_path, "response_path": response_path},
            )()

        def verify_prompt_hash(self, prompt_path, expected_prompt_hash=None):
            actual_hash = hashlib.md5(Path(prompt_path).read_bytes()).hexdigest()
            if expected_prompt_hash is not None and expected_prompt_hash != actual_hash:
                raise ValueError(
                    f"prompt hash mismatch for {prompt_path}: "
                    f"expected {expected_prompt_hash}, actual {actual_hash}"
                )
            return actual_hash

        def materialize_response(
            self,
            *,
            prompt_path,
            response_path,
            response_text,
            expected_prompt_hash=None,
        ):
            Path(response_path).write_text(response_text, encoding="utf-8")
            Path(prompt_path).write_text("changed prompt", encoding="utf-8")
            return response_path

    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "mutated-prompt-after-write"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("original prompt", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    monkeypatch.setattr(
        novel_cli,
        "ResponseFileBoundaryUnit",
        MutatingPromptAfterWriteBoundary,
    )

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        novel_cli._run_respond(
            Namespace(
                novel="mutated-prompt-after-write",
                response_file=str(response_source),
                prompt=None,
                slot_id=None,
                prompt_hash=None,
                json=True,
            )
        )

    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == "response"


def test_novel_respond_rejects_prompt_hash_mismatch(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")
    first = _run(["audit", "respond-hash-mismatch", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    response_path = (
        novels_root
        / "respond-hash-mismatch"
        / "output"
        / "audit"
        / "rebuild_response.txt"
    )

    result = _run(
        [
            "respond",
            "respond-hash-mismatch",
            "--response-file",
            str(response_source),
            "--prompt-hash",
            hashlib.md5(b"other prompt").hexdigest(),
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "prompt hash mismatch" in payload["error"]
    assert not response_path.exists()


def test_novel_respond_rejects_invalid_prompt_hash(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    response_source = tmp_path / "response.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")
    first = _run(["audit", "respond-invalid-hash", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr
    response_path = (
        novels_root
        / "respond-invalid-hash"
        / "output"
        / "audit"
        / "rebuild_response.txt"
    )

    result = _run(
        [
            "respond",
            "respond-invalid-hash",
            "--response-file",
            str(response_source),
            "--prompt-hash",
            "wrong-hash",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["command"] == "respond"
    assert payload["novel"] == "respond-invalid-hash"
    assert payload["error_stage"] == "runtime"
    assert payload["error_type"] == "ValueError"
    assert "invalid expected_prompt_hash" in payload["error"]
    assert not response_path.exists()


def test_novel_respond_json_reports_argument_errors_as_json(tmp_path):
    novels_root = tmp_path / "novels"

    result = _run(["respond", "parse-json", "--json"], novels_root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert tuple(payload) == (
        "ok",
        "schema_version",
        "error_stage",
        "error_type",
        "error",
    )
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_stage"] == "argument"
    assert payload["error_type"] == "ArgumentError"
    assert "--response-file" in payload["error"]
    assert result.stderr == ""


def test_novel_respond_can_target_prompt_when_multiple_slots_exist(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-multi"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    response_source.write_text("review response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-multi",
            "--response-file",
            str(response_source),
            "--prompt",
            "review_prompt.txt",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["selection_method"] == "prompt_file"
    assert payload["slot_id"] == "review"
    assert payload["prompt_file"] == "review_prompt.txt"
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == (
        "review response"
    )
    assert not (output_dir / "continue_response.txt").exists()


def test_novel_respond_can_target_slot_id_when_multiple_slots_exist(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-slot"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    response_source.write_text("review response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-slot",
            "--response-file",
            str(response_source),
            "--slot-id",
            "review",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["selection_method"] == "slot_id"
    assert payload["slot_id"] == "review"
    assert payload["prompt_file"] == "review_prompt.txt"
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == (
        "review response"
    )
    assert not (output_dir / "continue_response.txt").exists()


def test_novel_respond_rejects_missing_slot_id_without_writing(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-missing-slot"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-missing-slot",
            "--response-file",
            str(response_source),
            "--slot-id",
            "continue",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "pending response slot not found" in payload["error"]
    assert not (output_dir / "continue_response.txt").exists()
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_prompt_and_slot_id_together(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-double-target"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-double-target",
            "--response-file",
            str(response_source),
            "--prompt",
            "review_prompt.txt",
            "--slot-id",
            "review",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "--prompt and --slot-id cannot be used together" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_fails_on_multiple_slots_without_prompt(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-ambiguous"
    output_dir = novel_dir / "output" / "extend"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (output_dir / "review_prompt.txt").write_text("review", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        ["respond", "respond-ambiguous", "--response-file", str(response_source)],
        novels_root,
    )

    assert result.returncode == 1
    assert "multiple pending response slots" in result.stdout
    assert not (output_dir / "continue_response.txt").exists()
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_prompt_path_escape(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-path"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-path",
            "--response-file",
            str(response_source),
            "--prompt",
            "../review_prompt.txt",
        ],
        novels_root,
    )

    assert result.returncode == 1
    assert "invalid prompt filename" in result.stdout
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_empty_slot_prompt_filename_as_json_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-empty-slot"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source = tmp_path / "response.json"
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-empty-slot",
            "--response-file",
            str(response_source),
            "--prompt",
            "_prompt.txt",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "invalid prompt slot id" in payload["error"]
    assert not (output_dir / "_response.txt").exists()


def test_novel_respond_rejects_whitespace_slot_prompt_filename_as_json_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-whitespace-slot"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / " review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source = tmp_path / "response.json"
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-whitespace-slot",
            "--response-file",
            str(response_source),
            "--prompt",
            " review_prompt.txt",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "invalid prompt slot id" in payload["error"]
    assert not (output_dir / " review_response.txt").exists()


def test_novel_respond_rejects_non_slug_slot_prompt_filename_as_json_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-non-slug-slot"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review.v1_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source = tmp_path / "response.json"
    response_source.write_text("response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-non-slug-slot",
            "--response-file",
            str(response_source),
            "--prompt",
            "review.v1_prompt.txt",
            "--json",
        ],
        novels_root,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "invalid prompt slot id" in payload["error"]
    assert not (output_dir / "review.v1_response.txt").exists()


def test_novel_respond_refuses_existing_response(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-existing"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    (output_dir / "review_response.txt").write_text("old response", encoding="utf-8")
    response_source.write_text("new response", encoding="utf-8")

    result = _run(
        [
            "respond",
            "respond-existing",
            "--response-file",
            str(response_source),
            "--prompt",
            "review_prompt.txt",
        ],
        novels_root,
    )

    assert result.returncode == 1
    assert "response file already exists" in result.stdout
    assert (output_dir / "review_response.txt").read_text(encoding="utf-8") == (
        "old response"
    )


def test_novel_respond_rejects_empty_response_source(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-empty"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_text("  ", encoding="utf-8")

    result = _run(
        ["respond", "respond-empty", "--response-file", str(response_source)],
        novels_root,
    )

    assert result.returncode == 1
    assert "response text must be a non-empty string" in result.stdout
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_bom_only_response_source(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-bom-only"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_bytes(b"\xef\xbb\xbf")

    result = _run(
        ["respond", "respond-bom-only", "--response-file", str(response_source)],
        novels_root,
    )

    assert result.returncode == 1
    assert "response text must be a non-empty string" in result.stdout
    assert not (output_dir / "review_response.txt").exists()


def test_novel_respond_rejects_non_utf8_response_source_as_json_error(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "respond-non-utf8-source"
    output_dir = novel_dir / "output" / "audit"
    response_source = tmp_path / "response.txt"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "review_prompt.txt").write_text("prompt", encoding="utf-8")
    response_source.write_bytes(b"\xb6\xcc")

    result = _run(
        [
            "respond",
            "respond-non-utf8-source",
            "--response-file",
            str(response_source),
            "--json",
        ],
        novels_root,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "UnicodeDecodeError"
    assert "can't decode byte" in payload["error"]
    assert not (output_dir / "review_response.txt").exists()


def test_tier0_audit_canary_pending_respond_gate_sequence(tmp_path):
    from tests.test_audit_short_form import _complete_rebuild_response

    novels_root = tmp_path / "novels"
    input_path = tmp_path / "canary_input.txt"
    input_path.write_text("A short canary narrative with one concrete event.", encoding="utf-8")

    first = _run(["audit", "tier0-canary", "--input", str(input_path)], novels_root)

    assert first.returncode == 0, first.stdout + first.stderr
    assert "[WAITING]" in first.stdout

    rebuild_pending = _run(
        ["pending", "tier0-canary", "--require-automation-ready", "--json"],
        novels_root,
    )
    assert rebuild_pending.returncode == 0, rebuild_pending.stdout + rebuild_pending.stderr
    rebuild_pending_payload = json.loads(rebuild_pending.stdout)
    assert tuple(rebuild_pending_payload) == PENDING_JSON_FIELDS
    assert rebuild_pending_payload["automation_ready"] is True
    assert rebuild_pending_payload["provider_calls_implemented"] is False
    assert rebuild_pending_payload["closed_loop_allowed"] is False
    assert rebuild_pending_payload["pending_count"] == 1
    rebuild_slot = rebuild_pending_payload["pending"][0]
    assert rebuild_slot["slot_id"] == "rebuild"
    assert rebuild_slot["prompt_file"] == "rebuild_prompt.txt"
    assert rebuild_slot["response_file"] == "rebuild_response.txt"

    rebuild_response_source = tmp_path / "canary_rebuild_response.json"
    rebuild_response_source.write_text(_complete_rebuild_response(), encoding="utf-8")
    rebuild_respond = _run(
        [
            "respond",
            "tier0-canary",
            "--slot-id",
            rebuild_slot["slot_id"],
            "--prompt-hash",
            rebuild_slot["prompt_hash"],
            "--response-file",
            str(rebuild_response_source),
            "--json",
        ],
        novels_root,
    )
    assert rebuild_respond.returncode == 0, rebuild_respond.stdout + rebuild_respond.stderr
    rebuild_respond_payload = json.loads(rebuild_respond.stdout)
    assert tuple(rebuild_respond_payload) == RESPOND_JSON_FIELDS
    assert response_materialization_metadata().items() <= rebuild_respond_payload.items()
    assert rebuild_respond_payload["selection_method"] == "slot_id"
    assert rebuild_respond_payload["slot_id"] == "rebuild"

    second = _run(["resume", "tier0-canary"], novels_root)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "[WAITING]" in second.stdout
    assert "review_response.txt" in second.stdout

    review_pending = _run(
        ["pending", "tier0-canary", "--require-automation-ready", "--json"],
        novels_root,
    )
    assert review_pending.returncode == 0, review_pending.stdout + review_pending.stderr
    review_pending_payload = json.loads(review_pending.stdout)
    assert tuple(review_pending_payload) == PENDING_JSON_FIELDS
    assert review_pending_payload["automation_ready"] is True
    assert review_pending_payload["provider_calls_implemented"] is False
    assert review_pending_payload["closed_loop_allowed"] is False
    assert review_pending_payload["pending_count"] == 1
    review_slot = review_pending_payload["pending"][0]
    assert review_slot["slot_id"] == "review"
    assert review_slot["prompt_file"] == "review_prompt.txt"
    assert review_slot["response_file"] == "review_response.txt"

    review_response_source = tmp_path / "canary_review_response.json"
    review_response_source.write_text(
        json.dumps({"issues": [], "reminders": [], "route": "pass"}),
        encoding="utf-8",
    )
    review_respond = _run(
        [
            "respond",
            "tier0-canary",
            "--slot-id",
            review_slot["slot_id"],
            "--prompt-hash",
            review_slot["prompt_hash"],
            "--response-file",
            str(review_response_source),
            "--json",
        ],
        novels_root,
    )
    assert review_respond.returncode == 0, review_respond.stdout + review_respond.stderr
    review_respond_payload = json.loads(review_respond.stdout)
    assert tuple(review_respond_payload) == RESPOND_JSON_FIELDS
    assert response_materialization_metadata().items() <= review_respond_payload.items()
    assert review_respond_payload["selection_method"] == "slot_id"
    assert review_respond_payload["slot_id"] == "review"

    third = _run(["resume", "tier0-canary"], novels_root)

    assert third.returncode == 0, third.stdout + third.stderr
    assert "Audit complete: PASS" in third.stdout

    gate = _run(["gate", "tier0-canary", "--json"], novels_root)

    assert gate.returncode == 0, gate.stdout + gate.stderr
    gate_payload = json.loads(gate.stdout)
    assert tuple(gate_payload) == GATE_JSON_FIELDS
    assert gate_payload["ok"] is True
    assert gate_payload["review_route"] == "pass"
    assert gate_payload["next_workflow"] == "ContinueUnit"
    assert gate_payload["blocking_pending_count"] == 0
    assert gate_payload["blocking_pending_prompt_files"] == []


def test_novel_list_fails_on_invalid_final_result(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "broken"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "audit_report.json").write_text("{bad json", encoding="utf-8")

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid result JSON" in result.stdout
    assert "completed" not in result.stdout


def test_novel_list_fails_on_invalid_run_config(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "bad-config"
    novel_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text("{bad json", encoding="utf-8")

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid run config JSON" in result.stdout
    assert "bad-config" in result.stdout


def test_novel_list_fails_on_non_object_run_config(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "bad-config"
    novel_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text("[]", encoding="utf-8")

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid run config object" in result.stdout
    assert "bad-config" in result.stdout


def test_novel_list_fails_on_unknown_run_config_field(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "bad-config-field"
    novel_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit", "chapter_rang": "1-2"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid run config field" in result.stdout
    assert "chapter_rang" in result.stdout


def test_novel_list_fails_on_invalid_saved_mode(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "bad-mode"
    novel_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "unknown-flow"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid saved mode" in result.stdout
    assert "bad-mode" in result.stdout


def test_novel_list_fails_on_blank_saved_mode(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "blank-mode"
    novel_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": ""}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "invalid saved mode" in result.stdout
    assert "blank-mode" in result.stdout


def test_novel_list_does_not_mark_blocked_extend_as_completed(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "blocked"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "blocked" in result.stdout
    assert "route=block" in result.stdout
    assert "completed" not in result.stdout


def test_novel_list_reports_newer_waiting_prompt_before_stale_final(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "stale-final"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    final_path = output_dir / "audit_report.json"
    prompt_path = output_dir / "rebuild_prompt.txt"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text("new prompt", encoding="utf-8")
    os.utime(final_path, (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "waiting" in result.stdout
    assert "[WAITING: rebuild_response.txt]" in result.stdout
    assert "completed" not in result.stdout


def test_novel_list_json_filters_prompt_older_than_route_artifact(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "stale-prompt-current-final"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit"}, ensure_ascii=False),
        encoding="utf-8",
    )
    final_path = output_dir / "audit_report.json"
    prompt_path = output_dir / "rebuild_prompt.txt"
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text("stale prompt", encoding="utf-8")
    os.utime(prompt_path, (1_700_000_000, 1_700_000_000))
    os.utime(final_path, (1_700_000_100, 1_700_000_100))

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    row = json.loads(result.stdout)[0]
    assert row["status"] == "completed"
    assert row["route"] == "pass"
    assert row["pending_count"] == 0
    assert row["pending_prompt_file"] is None
    assert row["final_result_file"] == "audit_report.json"


def test_novel_list_rejects_invalid_final_even_with_newer_prompt(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "invalid-final-new-prompt"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    final_path = output_dir / "extend_result.json"
    prompt_path = output_dir / "review_prompt.txt"
    final_path.write_text(json.dumps({"route": "unknown"}, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text("new prompt", encoding="utf-8")
    os.utime(final_path, (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "invalid result route" in payload["error"]


def test_novel_list_rejects_handoff_mismatch_even_with_newer_prompt(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "handoff-mismatch-new-prompt"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    final_path = output_dir / "extend_result.json"
    handoff_path = output_dir / "route_handoff.json"
    prompt_path = output_dir / "review_prompt.txt"
    final_path.write_text(json.dumps({"route": "block"}, ensure_ascii=False), encoding="utf-8")
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path.write_text("new prompt", encoding="utf-8")
    os.utime(final_path, (1_700_000_000, 1_700_000_000))
    os.utime(handoff_path, (1_700_000_050, 1_700_000_050))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert "route handoff mismatch" in payload["error"]


def test_novel_list_reports_markdown_audit_as_completed(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "markdown-audit"
    output_dir = novel_dir / "output" / "audit"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "audit", "format": "markdown"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "audit_report.md").write_text("# report", encoding="utf-8")
    (output_dir / "review_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "completed" in result.stdout
    assert "route=pass" in result.stdout


def test_novel_list_reads_route_handoff_detail(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "handoff-detail"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "completed" in result.stdout
    assert "route=pass next=ContinueUnit" in result.stdout

    json_result = _run(["list", "--json"], novels_root)

    assert json_result.returncode == 0, json_result.stdout + json_result.stderr
    payload = json.loads(json_result.stdout)
    row = payload[0]
    assert row["schema_version"] == 1
    assert isinstance(row["latest_mtime"], int | float)
    assert row["route"] == "pass"
    assert row["next_workflow"] == "ContinueUnit"
    assert row["final_result_file"] == "extend_result.json"
    assert row["final_result_path"].endswith("extend_result.json")
    assert row["route_handoff_file"] == "route_handoff.json"
    assert row["route_handoff_path"].endswith("route_handoff.json")
    assert row["gate_ok"] is False
    assert row["gate_package_file"] == "extend_rebuild_package.json"
    assert row["gate_package_path"].endswith("extend_rebuild_package.json")
    assert row["gate_package_present"] is False
    assert "route gate: ContinueUnit requires a serialization package" in row[
        "gate_violations"
    ]


def test_novel_list_json_reports_gate_pass_with_package(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "list-gate-pass"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    row = json.loads(result.stdout)[0]
    assert row["status"] == "completed"
    assert row["route"] == "pass"
    assert row["next_workflow"] == "ContinueUnit"
    assert row["gate_ok"] is True
    assert row["gate_violations"] == []
    assert row["gate_package_present"] is True
    assert row["gate_package_file"] == "extend_rebuild_package.json"
    assert row["gate_blocking_pending_count"] == 0
    assert row["gate_blocking_pending_prompt_files"] == []


def test_novel_list_json_gate_metadata_blocks_stale_handoff_prompt(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "list-gate-stale-handoff"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    handoff_path = output_dir / "route_handoff.json"
    prompt_path = output_dir / "review_prompt.txt"
    final_path = output_dir / "extend_result.json"
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path.write_text("new review prompt", encoding="utf-8")
    final_path.write_text(json.dumps({"route": "pass"}, ensure_ascii=False), encoding="utf-8")
    os.utime(handoff_path, (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))
    os.utime(final_path, (1_700_000_200, 1_700_000_200))

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    row = json.loads(result.stdout)[0]
    assert row["status"] == "completed"
    assert row["pending_count"] == 0
    assert row["gate_ok"] is False
    assert row["gate_blocking_pending_count"] == 1
    assert row["gate_blocking_pending_prompt_files"] == ["review_prompt.txt"]
    assert "route gate: pending prompt newer than route handoff: review_prompt.txt" in row[
        "gate_violations"
    ]


def test_novel_list_json_reports_gate_failure_for_incomplete_review_reminder(
    tmp_path,
):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "list-gate-reminder-fail"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    handoff = _route_handoff("pass", "ContinueUnit")
    handoff["open_items"] = [_review_reminder_open_item(window=None)]
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "pass"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(handoff, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["command"] == "list"
    assert payload["error_type"] == "ValueError"
    assert "invalid route handoff packet" in payload["error"]
    assert "open_items ReviewReminder must match runtime model" in payload["error"]


def test_novel_list_rejects_result_handoff_route_mismatch(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "handoff-mismatch"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["list"], novels_root)

    assert result.returncode == 1
    assert "route handoff mismatch" in result.stdout


def test_novel_gate_passes_with_route_handoff_and_package(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-pass"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-pass"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gate PASS" in result.stdout
    assert "next=ContinueUnit" in result.stdout


def test_novel_gate_json_reports_pass_verdict(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-pass-json"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-pass-json", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert tuple(payload) == GATE_JSON_FIELDS
    assert payload["command"] == "gate"
    assert payload["novel"] == "gate-pass-json"
    assert payload["mode"] == "extend"
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["review_route"] == "pass"
    assert payload["next_workflow"] == "ContinueUnit"
    assert payload["violations"] == []
    assert payload["handoff_path"].endswith("route_handoff.json")
    assert payload["package_path"].endswith("extend_rebuild_package.json")
    assert payload["package_present"] is True
    assert payload["blocking_pending_count"] == 0
    assert payload["blocking_pending_prompt_files"] == []


def test_novel_gate_fails_when_pending_prompt_is_newer_than_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-newer-prompt"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    handoff_path = output_dir / "route_handoff.json"
    prompt_path = output_dir / "review_prompt.txt"
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path.write_text("new review prompt", encoding="utf-8")
    os.utime(handoff_path, (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))

    result = _run(["gate", "gate-newer-prompt"], novels_root)

    assert result.returncode == 1
    assert "pending prompt newer than route handoff" in result.stdout
    assert "review_prompt.txt" in result.stdout


def test_novel_gate_json_reports_pending_prompt_newer_than_handoff(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-newer-prompt-json"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    handoff_path = output_dir / "route_handoff.json"
    prompt_path = output_dir / "review_prompt.txt"
    handoff_path.write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_path.write_text("new review prompt", encoding="utf-8")
    os.utime(handoff_path, (1_700_000_000, 1_700_000_000))
    os.utime(prompt_path, (1_700_000_100, 1_700_000_100))

    result = _run(["gate", "gate-newer-prompt-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["blocking_pending_count"] == 1
    assert payload["blocking_pending_prompt_files"] == ["review_prompt.txt"]
    assert "route gate: pending prompt newer than route handoff: review_prompt.txt" in payload[
        "violations"
    ]


def test_novel_gate_rejects_result_handoff_route_mismatch(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-route-mismatch"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-route-mismatch"], novels_root)

    assert result.returncode == 1
    assert "route handoff mismatch" in result.stdout


def test_novel_gate_json_rejects_result_handoff_route_mismatch(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-route-mismatch-json"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_result.json").write_text(
        json.dumps({"route": "block"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-route-mismatch-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "route handoff mismatch" in payload["error"]


def test_novel_gate_fails_when_continue_package_missing(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-missing-package"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-missing-package"], novels_root)

    assert result.returncode == 1
    assert "ContinueUnit requires a serialization package" in result.stdout


def test_novel_gate_json_reports_failure_verdict(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-fail-json"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-fail-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["review_route"] == "pass"
    assert payload["next_workflow"] == "ContinueUnit"
    assert payload["package_present"] is False
    assert payload["violations"] == [
        "route gate: ContinueUnit requires a serialization package"
    ]


def test_novel_gate_fails_on_incomplete_review_reminder(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-reminder-fail"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    packet = _route_handoff("pass", "ContinueUnit")
    packet["open_items"] = [_review_reminder_open_item(window=None)]
    (output_dir / "route_handoff.json").write_text(
        json.dumps(packet, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-reminder-fail"], novels_root)

    assert result.returncode == 1
    assert "invalid route handoff packet" in result.stdout
    assert "open_items ReviewReminder must match runtime model" in result.stdout


def test_novel_gate_json_reports_incomplete_review_reminder(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-reminder-fail-json"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    packet = _route_handoff("pass", "ContinueUnit")
    packet["open_items"] = [
        _review_reminder_open_item(escalation_issue_type="information_leak")
    ]
    (output_dir / "route_handoff.json").write_text(
        json.dumps(packet, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-reminder-fail-json", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error_type"] == "ValueError"
    assert "invalid route handoff packet" in payload["error"]
    assert "open_items ReviewReminder must match runtime model" in payload["error"]


def test_novel_gate_accepts_rewrite_handoff_issue_without_package(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "gate-rewrite"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    packet = _route_handoff("rewrite", "RewriteUnit")
    packet["open_items"] = [
        {
            "type": "ReviewIssue",
            "issue_id": "iss_rewrite",
            "issue_type": "fact_conflict",
            "severity": "blocking",
            "location": "FactLedger",
            "scope_of_impact": "current packet",
            "violated_rule": "rewrite gate",
            "description": "blocking issue requires rewrite",
            "status": "open",
        }
    ]
    packet["change_set"][0]["issue_count"] = 1
    (output_dir / "route_handoff.json").write_text(
        json.dumps(packet, ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "gate-rewrite"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gate PASS" in result.stdout
    assert "route=rewrite" in result.stdout


def _approval_gate_workspace(
    novels_root: Path,
    name: str,
    *,
    decision: str | None = "approve",
    review_issues: list[dict] | None = None,
) -> Path:
    """Build an extend workspace whose rewrite handoff carries open critical
    ReviewIssues, plus an optional approval_decision.json."""
    novel_dir = novels_root / name
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    packet = _route_handoff("rewrite", "RewriteUnit")
    packet["open_items"] = review_issues or [_review_issue_open_item()]
    packet["change_set"][0]["issue_count"] = len(packet["open_items"])
    (output_dir / "route_handoff.json").write_text(
        json.dumps(packet, ensure_ascii=False),
        encoding="utf-8",
    )
    if decision is not None:
        _approval_decision_file(output_dir, decision=decision)
    return output_dir


def test_novel_gate_require_approval_matches_standard_when_no_critical(tmp_path):
    novels_root = tmp_path / "novels"
    novel_dir = novels_root / "approval-no-critical"
    output_dir = novel_dir / "output" / "extend"
    output_dir.mkdir(parents=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps({"mode": "extend"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "route_handoff.json").write_text(
        json.dumps(_route_handoff("pass", "ContinueUnit"), ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "extend_rebuild_package.json").write_text(
        json.dumps(_serialization_package(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run(["gate", "approval-no-critical", "--require-approval", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert tuple(payload) == APPROVAL_GATE_JSON_FIELDS
    assert payload["ok"] is True
    assert payload["approval_required"] is False
    assert payload["critical_issue_ids"] == []
    assert payload["approval_decision"] == "-"
    assert payload["approval_ok"] is True


def test_novel_gate_require_approval_blocks_without_decision_artifact(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-missing", decision=None)

    result = _run(["gate", "approval-missing", "--require-approval", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["approval_required"] is True
    assert payload["approval_decision"] == "-"
    assert payload["approval_ok"] is False
    assert "require operator approval" in payload["violations"][0]
    assert "iss_critical_1" in payload["violations"][0]


def test_novel_gate_require_approval_blocks_without_decision_human(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-missing-human", decision=None)

    result = _run(["gate", "approval-missing-human", "--require-approval"], novels_root)

    assert result.returncode == 1
    assert "approval required" in result.stdout or "require operator approval" in result.stdout
    assert "iss_critical_1" in result.stdout


def test_novel_gate_require_approval_passes_with_full_approve(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-ok")

    result = _run(["gate", "approval-ok", "--require-approval", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["review_route"] == "rewrite"
    assert payload["next_workflow"] == "ContinueUnit"
    assert payload["approval_required"] is True
    assert payload["critical_issue_ids"] == ["iss_critical_1"]
    assert payload["approval_decision"] == "approve"
    assert payload["approval_ok"] is True


def test_novel_gate_require_approval_reject_blocks(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-reject", decision="reject")

    result = _run(["gate", "approval-reject", "--require-approval", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["approval_decision"] == "reject"
    assert payload["approval_ok"] is False
    assert "rejected by operator" in payload["violations"][0]


def test_novel_gate_require_approval_partial_approve_blocks(tmp_path):
    novels_root = tmp_path / "novels"
    output_dir = _approval_gate_workspace(novels_root, "approval-partial")
    _approval_decision_file(
        output_dir,
        critical_issue_ids=["iss_critical_1"],
    )
    # add a second open critical issue not covered by the artifact
    packet_path = output_dir / "route_handoff.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["open_items"].append(_review_issue_open_item(issue_id="iss_critical_2"))
    packet["change_set"][0]["issue_count"] = len(packet["open_items"])
    packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

    result = _run(["gate", "approval-partial", "--require-approval", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["approval_ok"] is False
    assert "does not cover" in payload["violations"][0]
    assert "iss_critical_2" in payload["violations"][0]


def test_novel_gate_require_approval_invalid_artifact_blocks(tmp_path):
    novels_root = tmp_path / "novels"
    output_dir = _approval_gate_workspace(novels_root, "approval-invalid", decision=None)
    (output_dir / "approval_decision.json").write_text(
        '{"decision": "nope"}',
        encoding="utf-8",
    )

    result = _run(["gate", "approval-invalid", "--require-approval", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["approval_ok"] is False
    assert "invalid approval decision" in payload["violations"][0]


def test_novel_gate_require_approval_blocking_issue_not_approvable(tmp_path):
    novels_root = tmp_path / "novels"
    blocking = _review_issue_open_item(
        issue_id="iss_blocking_1",
        severity="blocking",
    )
    critical = _review_issue_open_item(issue_id="iss_critical_1")
    _approval_gate_workspace(
        novels_root,
        "approval-blocking",
        review_issues=[blocking, critical],
    )

    result = _run(["gate", "approval-blocking", "--require-approval", "--json"], novels_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["approval_ok"] is True  # critical covered
    assert payload["ok"] is False  # blocking remains, override suppressed
    assert payload["next_workflow"] == "RewriteUnit"


def test_novel_gate_require_approval_override_human_path(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-human")

    result = _run(["gate", "approval-human", "--require-approval"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gate PASS" in result.stdout
    assert "approval=approve" in result.stdout


def test_novel_gate_default_json_stays_thirteen_fields(tmp_path):
    novels_root = tmp_path / "novels"
    _approval_gate_workspace(novels_root, "approval-default", decision=None)

    result = _run(["gate", "approval-default", "--json"], novels_root)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert tuple(payload) == GATE_JSON_FIELDS
    assert payload["ok"] is True
    assert payload["next_workflow"] == "RewriteUnit"


def test_novel_resume_uses_saved_extend_mode(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("短篇测试文本", encoding="utf-8")
    first = _run(["extend", "示例小说乙", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run(["resume", "示例小说乙"], novels_root)

    assert result.returncode == 1
    assert "--resume requires saved state file" in result.stdout
