"""Unit tests for the editor human-in-the-loop approval gate module."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.boundary_control.approval_gate import (
    APPROVAL_DECISION_FILE,
    APPROVAL_GATE_CONTRACT_VERSION,
    APPROVAL_GATE_EXTRA_FIELDS,
    CONTINUE_BLOCKED_UNRESOLVED_ISSUE,
    ApprovalDecision,
    blocking_review_issue_ids,
    critical_review_issue_ids,
    load_approval_decision,
    resolve_approval_gate_verdict,
    validate_approval_decision_payload,
)
from src.boundary_control.handoff import HandoffPacket, NextRoute
from src.boundary_control.review_object_contracts import review_issue_open_item
from src.boundary_control.serialization import SerializationPackage
from src.object_state import ReviewIssue


def _review_issue(
    issue_id: str,
    severity: str,
    resolution_status: str = "open",
) -> ReviewIssue:
    return ReviewIssue(
        issue_id=issue_id,
        issue_type="weak_progression",
        severity=severity,  # type: ignore[arg-type]
        location="pu_scene_001",
        scope_of_impact="next unit",
        violated_rule="progression",
        description="test issue",
        resolution_status=resolution_status,  # type: ignore[arg-type]
    )


def _issue_open_item(
    issue_id: str,
    severity: str,
    resolution_status: str = "open",
) -> dict:
    return review_issue_open_item(
        _review_issue(issue_id, severity, resolution_status).model_dump(mode="json")
    )


def _packet(*open_items: dict) -> HandoffPacket:
    return HandoffPacket(
        handoff_header={"source": "ReviewUnit", "target": "ContinueUnit", "reason": "test"},
        input_anchor={"review_target_ref": "review_result.json"},
        output_anchor={"state_ref": "ns_001"},
        change_set=[{"action": "review", "route": "pass", "issue_count": 0, "reminder_count": 0}],
        open_items=open_items,
        next_route=NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="test",
            review_route="pass",
        ),
    )


def _package(*review_issues: dict) -> SerializationPackage:
    return SerializationPackage(repair_control={"ReviewIssue": list(review_issues)})


def _decision(decision: str = "approve", *, issue_ids=None, note=None, ts="2026-08-01T12:34:56Z") -> dict:
    return {
        "decision": decision,
        "critical_issue_ids": issue_ids if issue_ids is not None else ["iss_crit_1"],
        "operator_note": note,
        "decided_at_utc": ts,
    }


def _decision_model(*args, **kwargs) -> ApprovalDecision:
    return validate_approval_decision_payload(_decision(*args, **kwargs))


# --- decision model ---------------------------------------------------------


class TestApprovalDecisionModel:
    def test_valid_approve(self):
        model = _decision_model()
        assert model.decision == "approve"
        assert model.critical_issue_ids == ["iss_crit_1"]
        assert model.operator_note is None

    def test_reject_with_note(self):
        model = _decision_model("reject", note="设定冲突不可接受")
        assert model.decision == "reject"
        assert model.operator_note == "设定冲突不可接受"

    def test_invalid_decision_rejected(self):
        with pytest.raises(ValidationError):
            _decision_model("maybe")

    def test_empty_critical_issue_ids_rejected(self):
        with pytest.raises(ValidationError):
            _decision_model(issue_ids=[])

    def test_blank_issue_id_rejected(self):
        with pytest.raises(ValidationError):
            _decision_model(issue_ids=["iss_ok", "   "])

    def test_malformed_decided_at_utc_rejected(self):
        with pytest.raises(ValidationError):
            _decision_model(ts="2026/08/01 12:34:56")
        with pytest.raises(ValidationError):
            _decision_model(ts="2026-13-01T12:34:56Z")

    def test_blank_operator_note_rejected(self):
        with pytest.raises(ValidationError):
            _decision_model(note="   ")

    def test_unknown_fields_rejected(self):
        payload = _decision()
        payload["extra_field"] = True
        with pytest.raises(ValidationError):
            validate_approval_decision_payload(payload)


# --- load_approval_decision --------------------------------------------------


class TestLoadApprovalDecision:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="missing approval decision file"):
            load_approval_decision(tmp_path / APPROVAL_DECISION_FILE)

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / APPROVAL_DECISION_FILE
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid approval decision JSON"):
            load_approval_decision(path)

    def test_invalid_shape_raises(self, tmp_path):
        path = tmp_path / APPROVAL_DECISION_FILE
        path.write_text('{"decision": "nope"}', encoding="utf-8")
        with pytest.raises(ValueError, match="invalid approval decision"):
            load_approval_decision(path)

    def test_valid_round_trip(self, tmp_path):
        path = tmp_path / APPROVAL_DECISION_FILE
        path.write_text(
            '{"decision": "approve", "critical_issue_ids": ["iss_a"], '
            '"decided_at_utc": "2026-08-01T00:00:00Z"}',
            encoding="utf-8",
        )
        model = load_approval_decision(path)
        assert model.decision == "approve"
        assert model.critical_issue_ids == ["iss_a"]


# --- collection ---------------------------------------------------------------


class TestCollection:
    def test_collects_from_handoff_open_items(self):
        packet = _packet(
            _issue_open_item("iss_crit_1", "critical"),
            _issue_open_item("iss_block_1", "blocking"),
        )
        assert critical_review_issue_ids(packet, None) == ["iss_crit_1"]
        assert blocking_review_issue_ids(packet, None) == ["iss_block_1"]

    def test_collects_from_package_repair_control(self):
        package = _package(_review_issue("iss_crit_2", "critical").model_dump(mode="json"))
        assert critical_review_issue_ids(_packet(), package) == ["iss_crit_2"]

    def test_dedups_across_handoff_and_package(self):
        item = _issue_open_item("iss_crit_1", "critical")
        package = _package(_review_issue("iss_crit_1", "critical").model_dump(mode="json"))
        assert critical_review_issue_ids(_packet(item), package) == ["iss_crit_1"]

    def test_excludes_non_critical_severities(self):
        packet = _packet(
            _issue_open_item("iss_warn", "warning"),
            _issue_open_item("iss_low", "low"),
        )
        assert critical_review_issue_ids(packet, None) == []
        assert blocking_review_issue_ids(packet, None) == []

    def test_excludes_resolved_and_deferred(self):
        packet = _packet(
            _issue_open_item("iss_resolved", "critical", resolution_status="resolved"),
            _issue_open_item("iss_deferred", "critical", resolution_status="deferred"),
        )
        assert critical_review_issue_ids(packet, None) == []

    def test_skips_malformed_open_item(self):
        packet = _packet({"type": "ReviewIssue", "issue_id": "broken"})
        assert critical_review_issue_ids(packet, None) == []

    def test_empty_without_package(self):
        assert critical_review_issue_ids(_packet(), None) == []
        assert blocking_review_issue_ids(_packet(), None) == []

    def test_blocking_and_critical_strictly_separated(self):
        packet = _packet(
            _issue_open_item("iss_crit", "critical"),
            _issue_open_item("iss_block", "blocking"),
        )
        assert blocking_review_issue_ids(packet, None) == ["iss_block"]
        assert critical_review_issue_ids(packet, None) == ["iss_crit"]


# --- resolve decision table ---------------------------------------------------


class TestResolveDecisionTable:
    def test_no_critical_passthrough(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=[],
            blocking_issue_ids=[],
            decision=None,
            base_ok=True,
            base_violations=[],
            review_route="pass",
            next_workflow="ContinueUnit",
        )
        assert verdict["approval_required"] is False
        assert verdict["approval_ok"] is True
        assert verdict["ok"] is True
        assert verdict["next_workflow"] == "ContinueUnit"
        assert verdict["violations"] == []

    def test_no_critical_keeps_base_failure(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=[],
            blocking_issue_ids=[],
            decision=None,
            base_ok=False,
            base_violations=["route gate: pending prompt newer than handoff"],
            review_route="rewrite",
            next_workflow="RewriteUnit",
        )
        assert verdict["ok"] is False
        assert verdict["violations"] == ["route gate: pending prompt newer than handoff"]

    def test_missing_artifact_blocks(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=[],
            decision=None,
            base_ok=False,
            base_violations=[CONTINUE_BLOCKED_UNRESOLVED_ISSUE],
            review_route="block",
            next_workflow="Stop",
        )
        assert verdict["approval_ok"] is False
        assert verdict["ok"] is False
        assert "require operator approval" in verdict["violations"][0]

    def test_reject_blocks(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=[],
            decision=_decision_model("reject"),
            base_ok=False,
            base_violations=[CONTINUE_BLOCKED_UNRESOLVED_ISSUE],
            review_route="block",
            next_workflow="Stop",
        )
        assert verdict["approval_decision"] == "reject"
        assert verdict["approval_ok"] is False
        assert verdict["ok"] is False
        assert "rejected by operator" in verdict["violations"][0]

    def test_partial_approve_blocks(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1", "iss_crit_2"],
            blocking_issue_ids=[],
            decision=_decision_model(issue_ids=["iss_crit_1"]),
            base_ok=False,
            base_violations=[CONTINUE_BLOCKED_UNRESOLVED_ISSUE],
            review_route="block",
            next_workflow="Stop",
        )
        assert verdict["approval_ok"] is False
        assert verdict["ok"] is False
        assert "does not cover" in verdict["violations"][0]
        assert "iss_crit_2" in verdict["violations"][0]

    def test_full_approve_overrides_to_continue_unit(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=[],
            decision=_decision_model(),
            base_ok=False,
            base_violations=[CONTINUE_BLOCKED_UNRESOLVED_ISSUE],
            review_route="rewrite",
            next_workflow="RewriteUnit",
        )
        assert verdict["approval_ok"] is True
        assert verdict["ok"] is True
        assert verdict["next_workflow"] == "ContinueUnit"
        assert verdict["violations"] == []

    def test_full_approve_does_not_override_blocking_issue(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=["iss_block_1"],
            decision=_decision_model(),
            base_ok=True,
            base_violations=[],
            review_route="rewrite",
            next_workflow="RewriteUnit",
        )
        assert verdict["approval_ok"] is True
        assert verdict["ok"] is False
        assert verdict["next_workflow"] == "RewriteUnit"
        assert "blocking issue(s) not approvable" in verdict["violations"][0]
        assert "iss_block_1" in verdict["violations"][0]

    def test_full_approve_does_not_override_non_issue_violation(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=[],
            decision=_decision_model(),
            base_ok=False,
            base_violations=[
                "route gate: pending prompt newer than route handoff: review_prompt.txt"
            ],
            review_route="rewrite",
            next_workflow="RewriteUnit",
        )
        assert verdict["approval_ok"] is True
        assert verdict["ok"] is False
        assert verdict["next_workflow"] == "RewriteUnit"
        assert "pending prompt newer" in verdict["violations"][0]

    def test_full_approve_on_block_route_overrides_to_continue_unit(self):
        verdict = resolve_approval_gate_verdict(
            critical_issue_ids=["iss_crit_1"],
            blocking_issue_ids=[],
            decision=_decision_model(),
            base_ok=False,
            base_violations=[CONTINUE_BLOCKED_UNRESOLVED_ISSUE],
            review_route="block",
            next_workflow="Stop",
        )
        assert verdict["ok"] is True
        assert verdict["next_workflow"] == "ContinueUnit"


# --- contract guards -----------------------------------------------------------


class TestContractGuards:
    def test_extra_fields_constants(self):
        assert APPROVAL_GATE_EXTRA_FIELDS == (
            "approval_required",
            "critical_issue_ids",
            "approval_decision",
            "approval_ok",
        )

    def test_contract_version(self):
        assert APPROVAL_GATE_CONTRACT_VERSION == 1
