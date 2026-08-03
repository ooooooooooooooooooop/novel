"""Tests for Tier 0 release record validation."""

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.boundary_control.release_record import (
    TIER0_RELEASE_RECORD_FIELDS,
    build_tier0_canary_evidence,
    build_tier0_release_record,
    validate_tier0_canary_evidence,
    validate_tier0_canary_evidence_artifacts,
    validate_tier0_release_record,
    validate_tier0_release_record_canary_evidence,
    validate_tier0_release_record_evidence_files,
    validate_tier0_release_record_git_checkpoint,
)
from src.boundary_control.handoff import HandoffBoundaryUnit
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state import NarrativeState, WorkSpec
from src.object_state.audit_report import AuditReport


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BASELINE = 1571
EXAMPLE_PATH = "docs/00_project/tier0_release_record.example.json"
CANARY_EVIDENCE_EXAMPLE_PATH = "docs/00_project/tier0_canary_evidence.example.json"
FULL_PYTEST_COMMAND = (
    "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-evidence-full "
    "-p no:cacheprovider"
)


def _example_payload() -> dict:
    return json.loads((PROJECT_ROOT / EXAMPLE_PATH).read_text(encoding="utf-8"))


def _canary_evidence_payload() -> dict:
    return json.loads(
        (PROJECT_ROOT / CANARY_EVIDENCE_EXAMPLE_PATH).read_text(encoding="utf-8")
    )


def _current_git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _write_canary_artifact_files(root: Path, payload: dict) -> None:
    for item in payload["final_artifact_paths"]:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _artifact_json_for_path(path.name),
            encoding="utf-8",
        )
        payload["final_artifact_sha256"][item] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    gate_result_path = _write_gate_result_file(root)
    payload["gate_result_path"] = str(gate_result_path)
    payload["gate_result_sha256"] = hashlib.sha256(
        gate_result_path.read_bytes()
    ).hexdigest()


def _attach_canary_evidence_paths(
    record: dict,
    canary_evidence_path: Path,
    canary_evidence: dict,
) -> None:
    release_record_path = record["evidence_paths"][-1]
    record["evidence_paths"] = [
        *record["evidence_paths"][:-1],
        str(canary_evidence_path),
        canary_evidence["gate_result_path"],
        release_record_path,
    ]


def _gate_result_payload(root: Path) -> dict:
    return {
        "command": "gate",
        "novel": "tier0-canary",
        "mode": "audit",
        "ok": True,
        "schema_version": 1,
        "review_route": "pass",
        "next_workflow": "ContinueUnit",
        "violations": [],
        "handoff_path": str(
            root / "novels/tier0-canary/output/audit/route_handoff.json"
        ),
        "package_path": str(
            root / "novels/tier0-canary/output/audit/rebuild_package.json"
        ),
        "package_present": True,
        "blocking_pending_count": 0,
        "blocking_pending_prompt_files": [],
    }


def _write_gate_result_file(root: Path, payload: dict | None = None) -> Path:
    gate_result_path = root / "gate-result.json"
    gate_result_path.write_text(
        json.dumps(payload or _gate_result_payload(root), ensure_ascii=False),
        encoding="utf-8",
    )
    return gate_result_path


def _rewrite_canary_artifact(
    root: Path,
    payload: dict,
    artifact_name: str,
    content: str,
) -> None:
    artifact = next(
        item for item in payload["final_artifact_paths"] if Path(item).name == artifact_name
    )
    target = root / artifact
    target.write_text(content, encoding="utf-8")
    payload["final_artifact_sha256"][artifact] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()


def _artifact_json_for_path(name: str) -> str:
    if name == "audit_report.json":
        return (
            AuditReport(
                source_text_ref="canary_input.txt",
                route="pass",
                narrative_state=NarrativeState(
                    state_id="ns_canary",
                    current_time="test",
                    current_location="test",
                    current_situation="test",
                ),
            )
            .model_dump_json(indent=2)
            + "\n"
        )
    if name == "review_result.json":
        return json.dumps(
            {"issues": [], "reminders": [], "route": "pass"},
            indent=2,
        ) + "\n"
    if name == "route_handoff.json":
        return (
            HandoffBoundaryUnit()
            .build_review_route(
                review_target_ref="novels/tier0-canary/output/audit/review_result.json",
                route="pass",
                issues=[],
                reminders=[],
                output_state_ref="ns_canary",
            )
            .model_dump_json(indent=2)
            + "\n"
        )
    if name == "rebuild_package.json":
        package = SerializationBoundaryUnit().build_package(
            WorkSpec(
                genre="test",
                audience="test",
                theme="test",
                tone="test",
                pacing="test",
            ),
            NarrativeState(
                state_id="ns_canary",
                current_time="test",
                current_location="test",
                current_situation="test",
            ),
        )
        return package.model_dump_json(indent=2) + "\n"
    raise AssertionError(f"unsupported test artifact: {name}")


def test_tier0_release_record_console_script_declared():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["novel-release-record"] == (
        "src.boundary_control.release_record:main"
    )


def test_tier0_release_record_example_validates():
    payload = _example_payload()

    validated = validate_tier0_release_record(
        payload,
        expected_baseline=EXPECTED_BASELINE,
        record_path=EXAMPLE_PATH,
    )

    assert validated is payload
    assert tuple(payload) == TIER0_RELEASE_RECORD_FIELDS


def test_tier0_canary_evidence_example_validates():
    payload = _canary_evidence_payload()

    validated = validate_tier0_canary_evidence(payload)

    assert validated is payload
    assert payload["type"] == "tier0_canary_evidence"
    assert set(payload["final_artifact_sha256"]) == set(payload["final_artifact_paths"])
    assert payload["gate_result_path"]
    assert len(payload["gate_result_sha256"]) == 64


def test_tier0_release_record_canary_evidence_accepts_matching_example():
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()

    validated = validate_tier0_release_record_canary_evidence(
        record,
        canary_evidence,
        canary_evidence_path=CANARY_EVIDENCE_EXAMPLE_PATH,
    )

    assert validated is canary_evidence


def test_tier0_release_record_canary_evidence_rejects_release_id_mismatch():
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    canary_evidence["release_id"] = "tier0-canary-20260705"

    with pytest.raises(ValueError, match="release_id must match"):
        validate_tier0_release_record_canary_evidence(record, canary_evidence)


def test_tier0_release_record_canary_evidence_requires_gate_result_path():
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    record["evidence_paths"].remove(canary_evidence["gate_result_path"])

    with pytest.raises(ValueError, match="must include canary gate result path"):
        validate_tier0_release_record_canary_evidence(record, canary_evidence)


def test_tier0_release_record_canary_evidence_requires_ordered_canary_paths():
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    canary_evidence_index = record["evidence_paths"].index(CANARY_EVIDENCE_EXAMPLE_PATH)
    gate_result_index = record["evidence_paths"].index(
        canary_evidence["gate_result_path"]
    )
    record["evidence_paths"][canary_evidence_index] = canary_evidence[
        "gate_result_path"
    ]
    record["evidence_paths"][gate_result_index] = CANARY_EVIDENCE_EXAMPLE_PATH

    with pytest.raises(ValueError, match="canary evidence path before"):
        validate_tier0_release_record_canary_evidence(
            record,
            canary_evidence,
            canary_evidence_path=CANARY_EVIDENCE_EXAMPLE_PATH,
        )


def test_tier0_canary_evidence_rejects_failed_gate():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_gate_ok"] = False

    with pytest.raises(ValueError, match="final_gate_ok must be true"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_missing_artifact_hash():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_sha256"].pop(
        canary_evidence["final_artifact_paths"][0]
    )

    with pytest.raises(ValueError, match="final_artifact_sha256 missing path"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_invalid_artifact_hash():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_sha256"][
        canary_evidence["final_artifact_paths"][0]
    ] = "not-a-sha"

    with pytest.raises(ValueError, match="64-character sha256"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_duplicate_final_artifact_paths():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_paths"].append(
        canary_evidence["final_artifact_paths"][0]
    )

    with pytest.raises(
        ValueError,
        match="final_artifact_paths entries must be unique",
    ):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_duplicate_final_artifact_names():
    canary_evidence = _canary_evidence_payload()
    duplicate_name_path = "novels/tier0-canary/output/audit_copy/audit_report.json"
    canary_evidence["final_artifact_paths"].append(duplicate_name_path)
    canary_evidence["final_artifact_sha256"][duplicate_name_path] = (
        canary_evidence["final_artifact_sha256"][
            canary_evidence["final_artifact_paths"][0]
        ]
    )

    with pytest.raises(ValueError, match="artifact names must be unique"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_noncanonical_final_artifact_path():
    canary_evidence = _canary_evidence_payload()
    original = "novels/tier0-canary/output/audit/audit_report.json"
    noncanonical = "novels/tier0-canary/output/archive/audit_report.json"
    canary_evidence["final_artifact_paths"][0] = noncanonical
    canary_evidence["final_artifact_sha256"][noncanonical] = (
        canary_evidence["final_artifact_sha256"].pop(original)
    )

    with pytest.raises(ValueError, match="ordered workspace output/audit final artifacts"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_wrong_final_artifact_order():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_paths"] = [
        canary_evidence["final_artifact_paths"][1],
        canary_evidence["final_artifact_paths"][0],
        *canary_evidence["final_artifact_paths"][2:],
    ]

    with pytest.raises(ValueError, match="ordered workspace output/audit final artifacts"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_wrong_workspace_path():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["workspace_path"] = "novels/other-canary"

    with pytest.raises(ValueError, match="workspace_path must be novels/tier0-canary"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_rejects_missing_gate_result_hash():
    canary_evidence = _canary_evidence_payload()
    canary_evidence.pop("gate_result_sha256")

    with pytest.raises(ValueError, match="missing Tier 0 canary evidence field"):
        validate_tier0_canary_evidence(canary_evidence)


def test_tier0_canary_evidence_artifacts_accepts_existing_files(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result_path = _write_gate_result_file(tmp_path)
    canary_evidence["gate_result_path"] = str(gate_result_path)
    canary_evidence["gate_result_sha256"] = hashlib.sha256(
        gate_result_path.read_bytes()
    ).hexdigest()

    validate_tier0_canary_evidence_artifacts(
        canary_evidence,
        artifact_root=tmp_path,
    )


def test_build_tier0_canary_evidence_derives_workspace_artifacts(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result_path = _write_gate_result_file(tmp_path)

    payload = build_tier0_canary_evidence(
        release_id="tier0-canary-20260706",
        workspace_path="novels/tier0-canary",
        gate_result_path=str(gate_result_path),
        artifact_root=tmp_path,
    )

    assert payload["workspace_path"] == "novels/tier0-canary"
    assert payload["final_review_route"] == "pass"
    assert payload["final_next_workflow"] == "ContinueUnit"
    assert set(payload["final_artifact_sha256"]) == set(
        payload["final_artifact_paths"]
    )
    assert payload["gate_result_path"] == str(gate_result_path).replace("\\", "/")
    assert payload["gate_result_sha256"] == hashlib.sha256(
        gate_result_path.read_bytes()
    ).hexdigest()
    validate_tier0_canary_evidence_artifacts(payload, artifact_root=tmp_path)


def test_build_tier0_canary_evidence_rejects_missing_artifact(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result_path = _write_gate_result_file(tmp_path)
    missing_artifact = tmp_path / "novels/tier0-canary/output/audit/route_handoff.json"
    missing_artifact.unlink()

    with pytest.raises(ValueError, match="missing Tier 0 canary final artifact file"):
        build_tier0_canary_evidence(
            release_id="tier0-canary-20260706",
            workspace_path="novels/tier0-canary",
            gate_result_path=str(gate_result_path),
            artifact_root=tmp_path,
        )


def test_build_tier0_canary_evidence_rejects_nonzero_pending(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result = _gate_result_payload(tmp_path)
    gate_result["blocking_pending_count"] = 1
    gate_result["blocking_pending_prompt_files"] = ["review_prompt.txt"]
    gate_result_path = _write_gate_result_file(tmp_path, gate_result)

    with pytest.raises(ValueError, match="gate result blocking_pending_count must be 0"):
        build_tier0_canary_evidence(
            release_id="tier0-canary-20260706",
            workspace_path="novels/tier0-canary",
            gate_result_path=str(gate_result_path),
            artifact_root=tmp_path,
        )


def test_build_tier0_canary_evidence_rejects_failed_gate_result(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result = _gate_result_payload(tmp_path)
    gate_result["ok"] = False
    gate_result["violations"] = ["route gate failed"]
    gate_result_path = _write_gate_result_file(tmp_path, gate_result)

    with pytest.raises(ValueError, match="gate result ok must be true"):
        build_tier0_canary_evidence(
            release_id="tier0-canary-20260706",
            workspace_path="novels/tier0-canary",
            gate_result_path=str(gate_result_path),
            artifact_root=tmp_path,
        )


def test_build_tier0_canary_evidence_rejects_gate_route_mismatch(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result = _gate_result_payload(tmp_path)
    gate_result["review_route"] = "rewrite"
    gate_result["next_workflow"] = "RewriteUnit"
    gate_result_path = _write_gate_result_file(tmp_path, gate_result)

    with pytest.raises(ValueError, match="review_route must match"):
        build_tier0_canary_evidence(
            release_id="tier0-canary-20260706",
            workspace_path="novels/tier0-canary",
            gate_result_path=str(gate_result_path),
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_missing_file(tmp_path):
    canary_evidence = _canary_evidence_payload()

    with pytest.raises(ValueError, match="missing final artifact file"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_file_outside_workspace(tmp_path):
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_paths"][0] = "outside/audit_report.json"
    canary_evidence["final_artifact_sha256"]["outside/audit_report.json"] = (
        canary_evidence["final_artifact_sha256"].pop(
            "novels/tier0-canary/output/audit/audit_report.json"
        )
    )
    _write_canary_artifact_files(tmp_path, canary_evidence)

    with pytest.raises(ValueError, match="workspace output/audit final artifacts"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_hash_mismatch(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    target = tmp_path / canary_evidence["final_artifact_paths"][0]
    target.write_text('{"changed": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_gate_result_hash_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result = Path(canary_evidence["gate_result_path"])
    gate_result.write_text(
        json.dumps({**_gate_result_payload(tmp_path), "package_present": False}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gate result sha256 mismatch"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_gate_result_route_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    gate_result_path = Path(canary_evidence["gate_result_path"])
    gate_result = _gate_result_payload(tmp_path)
    gate_result["review_route"] = "rewrite"
    gate_result["next_workflow"] = "RewriteUnit"
    gate_result_path.write_text(
        json.dumps(gate_result, ensure_ascii=False),
        encoding="utf-8",
    )
    canary_evidence["gate_result_sha256"] = hashlib.sha256(
        gate_result_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="final_review_route must match gate result"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_invalid_json_shape(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    artifact = canary_evidence["final_artifact_paths"][2]
    target = tmp_path / artifact
    target.write_text("{bad json", encoding="utf-8")
    canary_evidence["final_artifact_sha256"][artifact] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="must be valid JSON"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_wrong_artifact_shape(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    artifact = canary_evidence["final_artifact_paths"][0]
    target = tmp_path / artifact
    target.write_text(
        json.dumps({"issues": [], "reminders": [], "route": "pass"}),
        encoding="utf-8",
    )
    canary_evidence["final_artifact_sha256"][artifact] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="audit_report.json shape validation failed"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_review_result_extra_field(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    artifact = canary_evidence["final_artifact_paths"][1]
    target = tmp_path / artifact
    target.write_text(
        json.dumps(
            {
                "issues": [],
                "reminders": [],
                "route": "pass",
                "provider_response": "not allowed",
            }
        ),
        encoding="utf-8",
    )
    canary_evidence["final_artifact_sha256"][artifact] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="unknown review result field"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_audit_review_route_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "audit_report.json",
        AuditReport(source_text_ref="canary_input.txt", route="rewrite")
        .model_dump_json(indent=2)
        + "\n",
    )

    with pytest.raises(ValueError, match="audit_report.route must match"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_handoff_review_route_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    route_handoff = json.loads(_artifact_json_for_path("route_handoff.json"))
    route_handoff["next_route"]["review_route"] = "rewrite"
    route_handoff["next_route"]["recommended_workflow"] = "RewriteUnit"
    route_handoff["handoff_header"]["target"] = "RewriteUnit"
    route_handoff["change_set"][0]["route"] = "rewrite"
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "route_handoff.json",
        json.dumps(route_handoff, ensure_ascii=False, indent=2) + "\n",
    )

    with pytest.raises(ValueError, match="review_route must match"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_handoff_review_target_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    route_handoff = json.loads(_artifact_json_for_path("route_handoff.json"))
    route_handoff["input_anchor"][
        "review_target_ref"
    ] = "novels/tier0-canary/output/audit/other_review_result.json"
    route_handoff["next_route"]["must_read_first"] = [
        "novels/tier0-canary/output/audit/other_review_result.json"
    ]
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "route_handoff.json",
        json.dumps(route_handoff, ensure_ascii=False, indent=2) + "\n",
    )

    with pytest.raises(ValueError, match="must reference review_result.json"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_handoff_state_ref_mismatch(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    route_handoff = json.loads(_artifact_json_for_path("route_handoff.json"))
    route_handoff["output_anchor"]["state_ref"] = "ns_other"
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "route_handoff.json",
        json.dumps(route_handoff, ensure_ascii=False, indent=2) + "\n",
    )

    with pytest.raises(
        ValueError,
        match="must match audit_report.narrative_state.state_id",
    ):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_canary_evidence_artifacts_rejects_package_without_working_state(
    tmp_path,
):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    package = json.loads(_artifact_json_for_path("rebuild_package.json"))
    package["working_set"] = {}
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "rebuild_package.json",
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
    )

    with pytest.raises(ValueError, match="must include working_set"):
        validate_tier0_canary_evidence_artifacts(
            canary_evidence,
            artifact_root=tmp_path,
        )


def test_tier0_release_record_canary_evidence_requires_listed_path():
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()

    with pytest.raises(ValueError, match="must include canary evidence path"):
        validate_tier0_release_record_canary_evidence(
            record,
            canary_evidence,
            canary_evidence_path="docs/00_project/releases/tier0-canary-evidence.json",
        )


def test_build_tier0_release_record_returns_valid_exact_payload():
    payload = build_tier0_release_record(
        release_id="tier0-canary-20260706",
        created_at_utc="2026-07-06T00:00:00Z",
        release_tag_or_checkpoint="tier0-v0.1.0",
        git_commit="0123456789abcdef0123456789abcdef01234567",
        expected_baseline=EXPECTED_BASELINE,
        full_pytest_command=FULL_PYTEST_COMMAND,
        record_path="docs/00_project/releases/tier0-canary-20260706.json",
    )

    assert tuple(payload) == TIER0_RELEASE_RECORD_FIELDS
    assert payload["baseline_tests_passing"] == EXPECTED_BASELINE
    assert payload["full_pytest_result"] == f"{EXPECTED_BASELINE} passed"
    assert "docs/00_project/releases/tier0-canary-20260706.json" in payload[
        "evidence_paths"
    ]


def test_build_tier0_release_record_includes_canary_evidence_path():
    canary_evidence = _canary_evidence_payload()
    canary_evidence["gate_result_path"] = (
        "docs/00_project/releases/tier0-canary-gate.json"
    )
    payload = build_tier0_release_record(
        release_id="tier0-canary-20260706",
        created_at_utc="2026-07-06T00:00:00Z",
        release_tag_or_checkpoint="tier0-v0.1.0",
        git_commit="0123456789abcdef0123456789abcdef01234567",
        expected_baseline=EXPECTED_BASELINE,
        full_pytest_command=FULL_PYTEST_COMMAND,
        record_path="docs/00_project/releases/tier0-canary-20260706.json",
        canary_evidence_path="docs/00_project/releases/tier0-canary-evidence.json",
        canary_gate_result_path="docs/00_project/releases/tier0-canary-gate.json",
    )

    assert "docs/00_project/releases/tier0-canary-evidence.json" in payload[
        "evidence_paths"
    ]
    assert "docs/00_project/releases/tier0-canary-gate.json" in payload[
        "evidence_paths"
    ]
    validate_tier0_release_record_canary_evidence(
        payload,
        canary_evidence,
        canary_evidence_path="docs/00_project/releases/tier0-canary-evidence.json",
    )


def test_build_tier0_release_record_rejects_blank_required_inputs():
    with pytest.raises(ValueError, match="release_id must be a non-empty string"):
        build_tier0_release_record(
            release_id=" ",
            created_at_utc="2026-07-06T00:00:00Z",
            release_tag_or_checkpoint="tier0-v0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
            expected_baseline=EXPECTED_BASELINE,
            full_pytest_command=FULL_PYTEST_COMMAND,
            record_path="docs/00_project/releases/tier0-canary-20260706.json",
        )


def test_tier0_release_record_rejects_non_object():
    with pytest.raises(ValueError, match="payload must be an object"):
        validate_tier0_release_record([], expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_unknown_fields():
    payload = _example_payload()
    payload["provider_response"] = "not allowed"

    with pytest.raises(ValueError, match="unknown Tier 0 release record field"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_baseline_mismatch():
    payload = _example_payload()
    payload["baseline_tests_passing"] = EXPECTED_BASELINE - 1

    with pytest.raises(ValueError, match="baseline_tests_passing must match"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_full_pytest_result_mismatch():
    payload = _example_payload()
    payload["full_pytest_result"] = f"{EXPECTED_BASELINE - 1} passed"

    with pytest.raises(ValueError, match="full_pytest_result must be"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_invalid_release_id_format():
    payload = _example_payload()
    payload["release_id"] = "release-20260706"

    with pytest.raises(ValueError, match="tier0-canary-YYYYMMDD"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_invalid_release_id_date():
    payload = _example_payload()
    payload["release_id"] = "tier0-canary-20260230"

    with pytest.raises(ValueError, match="valid YYYYMMDD date"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_release_id_created_at_date_mismatch():
    payload = _example_payload()
    payload["release_id"] = "tier0-canary-20260705"

    with pytest.raises(ValueError, match="release_id date must match"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_non_pytest_full_command():
    payload = _example_payload()
    payload["full_pytest_command"] = f"echo {EXPECTED_BASELINE} passed"

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_narrow_pytest_command():
    payload = _example_payload()
    payload["full_pytest_command"] = (
        "python -m pytest tests/test_release_record.py -q "
        "--basetemp .pytest-tmp-current-tier0-release-full -p no:cacheprovider"
    )

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_pytest_command_without_cache_isolation():
    payload = _example_payload()
    payload["full_pytest_command"] = (
        "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-full"
    )

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_pytest_basetemp_empty_suffix():
    payload = _example_payload()
    payload["full_pytest_command"] = (
        "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release- "
        "-p no:cacheprovider"
    )

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_pytest_basetemp_path_separator():
    payload = _example_payload()
    payload["full_pytest_command"] = (
        "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-full/out "
        "-p no:cacheprovider"
    )

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_pytest_basetemp_parent_reference():
    payload = _example_payload()
    payload["full_pytest_command"] = (
        "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-.. "
        "-p no:cacheprovider"
    )

    with pytest.raises(ValueError, match="full pytest command"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_invalid_created_at_utc():
    payload = _example_payload()
    payload["created_at_utc"] = "2026-07-06 00:00:00"

    with pytest.raises(ValueError, match="UTC timestamp"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_invalid_git_commit_hash():
    payload = _example_payload()
    payload["git_commit"] = "not-a-git-commit"

    with pytest.raises(ValueError, match="40-character lowercase hexadecimal"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_canary_command_drift():
    payload = _example_payload()
    payload["canary_commands"][0] = "novel audit other --input canary_input.txt"

    with pytest.raises(ValueError, match="canary_commands must match runbook"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_provider_claims():
    for field in (
        "directapi_provider_calling",
        "provider_calls_implemented",
        "closed_loop_allowed",
        "provider_call_performed",
        "closed_loop_advanced",
    ):
        payload = _example_payload()
        payload[field] = True

        with pytest.raises(ValueError, match=f"{field} must be false"):
            validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_missing_required_limitations():
    payload = _example_payload()
    payload["known_limitations"] = payload["known_limitations"][:-1]

    with pytest.raises(ValueError, match="missing required known limitation"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_duplicate_known_limitations():
    payload = _example_payload()
    payload["known_limitations"] = [
        *payload["known_limitations"],
        payload["known_limitations"][0],
    ]

    with pytest.raises(ValueError, match="known_limitations entries must be unique"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_missing_evidence_paths():
    payload = _example_payload()
    payload["evidence_paths"] = [
        "docs/00_project/tier0_release_record.example.json",
    ]

    with pytest.raises(ValueError, match="missing required evidence path"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_duplicate_evidence_paths():
    payload = _example_payload()
    payload["evidence_paths"] = [
        *payload["evidence_paths"],
        payload["evidence_paths"][0],
    ]

    with pytest.raises(ValueError, match="evidence_paths entries must be unique"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_required_evidence_path_order_drift():
    payload = _example_payload()
    payload["evidence_paths"] = [
        "docs/00_project/31_tier0_canary_runbook.md",
        "docs/00_project/30_production_readiness_checklist.md",
        *payload["evidence_paths"][2:],
    ]

    with pytest.raises(ValueError, match="required evidence path order"):
        validate_tier0_release_record(payload, expected_baseline=EXPECTED_BASELINE)


def test_tier0_release_record_rejects_record_path_not_last():
    payload = _example_payload()
    payload["evidence_paths"] = [
        *payload["evidence_paths"][:-2],
        EXAMPLE_PATH,
        payload["evidence_paths"][-2],
    ]

    with pytest.raises(ValueError, match="record path must be final"):
        validate_tier0_release_record(
            payload,
            expected_baseline=EXPECTED_BASELINE,
            record_path=EXAMPLE_PATH,
        )


def test_tier0_release_record_requires_record_path_when_given():
    payload = _example_payload()

    with pytest.raises(ValueError, match="missing required evidence path"):
        validate_tier0_release_record(
            payload,
            expected_baseline=EXPECTED_BASELINE,
            record_path="docs/00_project/releases/tier0-release.json",
        )


def test_tier0_release_record_evidence_files_accepts_example():
    payload = _example_payload()
    validate_tier0_release_record(
        payload,
        expected_baseline=EXPECTED_BASELINE,
        record_path=EXAMPLE_PATH,
    )

    validate_tier0_release_record_evidence_files(
        payload,
        evidence_root=PROJECT_ROOT,
    )


def test_tier0_release_record_evidence_files_rejects_missing_path():
    payload = _example_payload()
    payload["evidence_paths"] = [
        *payload["evidence_paths"],
        "docs/00_project/missing-release-evidence.json",
    ]

    with pytest.raises(ValueError, match="missing evidence file"):
        validate_tier0_release_record_evidence_files(
            payload,
            evidence_root=PROJECT_ROOT,
        )


def test_tier0_release_record_git_checkpoint_accepts_commit_checkpoint():
    head = _current_git_head()
    payload = build_tier0_release_record(
        release_id="tier0-canary-20260706",
        created_at_utc="2026-07-06T00:00:00Z",
        release_tag_or_checkpoint=head,
        git_commit=head,
        expected_baseline=EXPECTED_BASELINE,
        full_pytest_command=FULL_PYTEST_COMMAND,
        record_path="docs/00_project/releases/tier0-canary-20260706.json",
    )

    validate_tier0_release_record_git_checkpoint(
        payload,
        repo_root=PROJECT_ROOT,
    )


def test_tier0_release_record_git_checkpoint_rejects_missing_commit():
    missing_commit = "0" * 40
    payload = _example_payload()
    payload["release_tag_or_checkpoint"] = missing_commit
    payload["git_commit"] = missing_commit

    with pytest.raises(ValueError, match="git_commit must exist"):
        validate_tier0_release_record_git_checkpoint(
            payload,
            repo_root=PROJECT_ROOT,
        )


def test_tier0_release_record_git_checkpoint_rejects_mismatched_checkpoint_hash():
    payload = _example_payload()
    payload["release_tag_or_checkpoint"] = "0" * 40
    payload["git_commit"] = _current_git_head()

    with pytest.raises(ValueError, match="must match git_commit"):
        validate_tier0_release_record_git_checkpoint(
            payload,
            repo_root=PROJECT_ROOT,
        )


def test_tier0_release_record_cli_accepts_example():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            EXAMPLE_PATH,
            "--expected-baseline",
            str(EXPECTED_BASELINE),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {EXAMPLE_PATH}" in result.stdout


def test_tier0_release_record_cli_requires_existing_evidence_files():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            EXAMPLE_PATH,
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--require-evidence-files",
            "--evidence-root",
            ".",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {EXAMPLE_PATH}" in result.stdout


def test_tier0_release_record_cli_accepts_canary_evidence():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            EXAMPLE_PATH,
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--canary-evidence",
            CANARY_EVIDENCE_EXAMPLE_PATH,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {EXAMPLE_PATH}" in result.stdout


def test_tier0_release_record_cli_accepts_canary_artifact_files(tmp_path):
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    record_path = tmp_path / "release-record.json"
    canary_path = tmp_path / "canary-evidence.json"
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _attach_canary_evidence_paths(record, canary_path, canary_evidence)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {record_path}" in result.stdout


def test_tier0_release_record_cli_accepts_combined_production_validation(tmp_path):
    head = _current_git_head()
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    canary_path = tmp_path / "canary-evidence.json"
    record_path = tmp_path / "release-record.json"
    payload = build_tier0_release_record(
        release_id="tier0-canary-20260706",
        created_at_utc="2026-07-06T00:00:00Z",
        release_tag_or_checkpoint=head,
        git_commit=head,
        expected_baseline=EXPECTED_BASELINE,
        full_pytest_command=FULL_PYTEST_COMMAND,
        record_path=str(record_path),
        canary_evidence_path=str(canary_path),
        canary_gate_result_path=canary_evidence["gate_result_path"],
    )
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            str(record_path),
            "--require-evidence-files",
            "--evidence-root",
            ".",
            "--require-git-checkpoint",
            "--repo-root",
            ".",
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {record_path}" in result.stdout


def test_tier0_canary_evidence_cli_generates_from_workspace_artifacts(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    output_path = tmp_path / "generated-canary-evidence.json"
    gate_result_path = tmp_path / "gate-result.json"
    gate_result_path.write_text(
        json.dumps(_gate_result_payload(tmp_path), ensure_ascii=False),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(output_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--generate-canary-evidence",
            "--release-id",
            "tier0-canary-20260706",
            "--canary-workspace",
            "novels/tier0-canary",
            "--canary-gate-result",
            str(gate_result_path),
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 canary evidence GENERATED: {output_path}" in result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    validate_tier0_canary_evidence(payload)
    validate_tier0_canary_evidence_artifacts(payload, artifact_root=tmp_path)


def test_tier0_canary_evidence_cli_generation_refuses_existing_file(tmp_path):
    canary_evidence = _canary_evidence_payload()
    _write_canary_artifact_files(tmp_path, canary_evidence)
    output_path = tmp_path / "existing-canary-evidence.json"
    gate_result_path = tmp_path / "gate-result.json"
    gate_result_path.write_text(
        json.dumps(_gate_result_payload(tmp_path), ensure_ascii=False),
        encoding="utf-8",
    )
    output_path.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(output_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--generate-canary-evidence",
            "--release-id",
            "tier0-canary-20260706",
            "--canary-workspace",
            "novels/tier0-canary",
            "--canary-gate-result",
            str(gate_result_path),
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "canary evidence already exists" in result.stdout
    assert output_path.read_text(encoding="utf-8") == "{}"


def test_tier0_release_record_cli_rejects_canary_artifacts_without_evidence():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            EXAMPLE_PATH,
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--require-canary-artifacts",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "requires --canary-evidence" in result.stdout


def test_tier0_release_record_cli_rejects_canary_artifact_outside_workspace(tmp_path):
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    canary_evidence["final_artifact_paths"][0] = "outside/audit_report.json"
    canary_evidence["final_artifact_sha256"]["outside/audit_report.json"] = (
        canary_evidence["final_artifact_sha256"].pop(
            "novels/tier0-canary/output/audit/audit_report.json"
        )
    )
    record_path = tmp_path / "release-record.json"
    canary_path = tmp_path / "canary-evidence.json"
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _attach_canary_evidence_paths(record, canary_path, canary_evidence)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "workspace output/audit final artifacts" in result.stdout


def test_tier0_release_record_cli_rejects_canary_artifact_hash_mismatch(tmp_path):
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    record_path = tmp_path / "release-record.json"
    canary_path = tmp_path / "canary-evidence.json"
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _attach_canary_evidence_paths(record, canary_path, canary_evidence)
    target = tmp_path / canary_evidence["final_artifact_paths"][0]
    target.write_text('{"changed": true}\n', encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "sha256 mismatch" in result.stdout


def test_tier0_release_record_cli_rejects_canary_artifact_shape_mismatch(tmp_path):
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    record_path = tmp_path / "release-record.json"
    canary_path = tmp_path / "canary-evidence.json"
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _attach_canary_evidence_paths(record, canary_path, canary_evidence)
    artifact = canary_evidence["final_artifact_paths"][3]
    target = tmp_path / artifact
    target.write_text(
        json.dumps({"issues": [], "reminders": [], "route": "pass"}),
        encoding="utf-8",
    )
    canary_evidence["final_artifact_sha256"][artifact] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    record_path.write_text(json.dumps(record), encoding="utf-8")
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "rebuild_package.json shape validation failed" in result.stdout


def test_tier0_release_record_cli_rejects_canary_artifact_semantic_mismatch(tmp_path):
    record = _example_payload()
    canary_evidence = _canary_evidence_payload()
    record_path = tmp_path / "release-record.json"
    canary_path = tmp_path / "canary-evidence.json"
    _write_canary_artifact_files(tmp_path, canary_evidence)
    _attach_canary_evidence_paths(record, canary_path, canary_evidence)
    _rewrite_canary_artifact(
        tmp_path,
        canary_evidence,
        "audit_report.json",
        AuditReport(source_text_ref="canary_input.txt", route="rewrite")
        .model_dump_json(indent=2)
        + "\n",
    )
    record_path.write_text(json.dumps(record), encoding="utf-8")
    canary_path.write_text(json.dumps(canary_evidence), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
            "--canary-evidence",
            str(canary_path),
            "--require-canary-artifacts",
            "--canary-artifact-root",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "audit_report.route must match" in result.stdout


def test_tier0_release_record_cli_requires_git_checkpoint(tmp_path):
    head = _current_git_head()
    record_path = tmp_path / "release-record.json"
    payload = build_tier0_release_record(
        release_id="tier0-canary-20260706",
        created_at_utc="2026-07-06T00:00:00Z",
        release_tag_or_checkpoint=head,
        git_commit=head,
        expected_baseline=EXPECTED_BASELINE,
        full_pytest_command=FULL_PYTEST_COMMAND,
        record_path=str(record_path),
    )
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--require-git-checkpoint",
            "--repo-root",
            ".",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {record_path}" in result.stdout


def test_tier0_release_record_cli_rejects_baseline_mismatch():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            EXAMPLE_PATH,
            "--expected-baseline",
            str(EXPECTED_BASELINE - 1),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "baseline_tests_passing must match" in result.stdout


def test_tier0_release_record_cli_rejects_invalid_git_commit_hash(tmp_path):
    record_path = tmp_path / "bad-git-release-record.json"
    payload = _example_payload()
    payload["git_commit"] = "0123456789abcdef"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            EXAMPLE_PATH,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "40-character lowercase hexadecimal" in result.stdout


def test_tier0_release_record_cli_rejects_invalid_json(tmp_path):
    record_path = tmp_path / "bad-release-record.json"
    record_path.write_text("{bad json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Tier 0 release record FAIL:" in result.stdout


def test_tier0_release_record_cli_rejects_missing_file(tmp_path):
    record_path = tmp_path / "missing-release-record.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Tier 0 release record FAIL:" in result.stdout
    assert record_path.name in result.stdout


def test_tier0_release_record_cli_uses_explicit_record_path_binding(tmp_path):
    record_path = tmp_path / "release-record.json"
    payload = _example_payload()
    payload["evidence_paths"][-1] = "docs/00_project/releases/tier0-release.json"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            "docs/00_project/releases/tier0-release.json",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record PASS: {record_path}" in result.stdout


def test_tier0_release_record_cli_generates_record(tmp_path):
    record_path = tmp_path / "generated-release-record.json"
    logical_record_path = "docs/00_project/releases/generated-release-record.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            logical_record_path,
            "--generate",
            "--release-id",
            "tier0-canary-20260706",
            "--created-at-utc",
            "2026-07-06T00:00:00Z",
            "--release-tag-or-checkpoint",
            "tier0-v0.1.0",
            "--git-commit",
            "0123456789abcdef0123456789abcdef01234567",
            "--full-pytest-command",
            FULL_PYTEST_COMMAND,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Tier 0 release record GENERATED: {record_path}" in result.stdout
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    validate_tier0_release_record(
        payload,
        expected_baseline=EXPECTED_BASELINE,
        record_path=logical_record_path,
    )


def test_tier0_release_record_cli_generates_record_with_canary_evidence(tmp_path):
    record_path = tmp_path / "generated-release-record.json"
    logical_record_path = "docs/00_project/releases/generated-release-record.json"
    canary_evidence_path = tmp_path / "tier0-canary-evidence.json"
    canary_evidence_path.write_text(
        json.dumps(_canary_evidence_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--record-path",
            logical_record_path,
            "--generate",
            "--release-id",
            "tier0-canary-20260706",
            "--created-at-utc",
            "2026-07-06T00:00:00Z",
            "--release-tag-or-checkpoint",
            "tier0-v0.1.0",
            "--git-commit",
            "0123456789abcdef0123456789abcdef01234567",
            "--full-pytest-command",
            FULL_PYTEST_COMMAND,
            "--canary-evidence",
            str(canary_evidence_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert str(canary_evidence_path) in payload["evidence_paths"]
    assert _canary_evidence_payload()["gate_result_path"] in payload["evidence_paths"]
    validate_tier0_release_record_canary_evidence(
        payload,
        _canary_evidence_payload(),
        canary_evidence_path=str(canary_evidence_path),
    )


def test_tier0_release_record_cli_rejects_generate_with_evidence_file_check(tmp_path):
    record_path = tmp_path / "generated-release-record.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--generate",
            "--release-id",
            "tier0-canary-20260706",
            "--created-at-utc",
            "2026-07-06T00:00:00Z",
            "--release-tag-or-checkpoint",
            "tier0-v0.1.0",
            "--git-commit",
            "0123456789abcdef0123456789abcdef01234567",
            "--full-pytest-command",
            FULL_PYTEST_COMMAND,
            "--require-evidence-files",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "cannot be used with --generate" in result.stdout
    assert not record_path.exists()


def test_tier0_release_record_cli_generate_refuses_existing_file(tmp_path):
    record_path = tmp_path / "existing-release-record.json"
    record_path.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--generate",
            "--release-id",
            "tier0-canary-20260706",
            "--created-at-utc",
            "2026-07-06T00:00:00Z",
            "--release-tag-or-checkpoint",
            "tier0-v0.1.0",
            "--git-commit",
            "0123456789abcdef0123456789abcdef01234567",
            "--full-pytest-command",
            FULL_PYTEST_COMMAND,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "release record already exists" in result.stdout


def test_tier0_release_record_cli_generate_requires_metadata(tmp_path):
    record_path = tmp_path / "missing-metadata-release-record.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.boundary_control.release_record",
            str(record_path),
            "--expected-baseline",
            str(EXPECTED_BASELINE),
            "--generate",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "missing Tier 0 release record generation field" in result.stdout
    assert not record_path.exists()
