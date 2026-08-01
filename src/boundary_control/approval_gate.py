"""Editor human-in-the-loop approval gate contracts.

Phase 5 of the improvement plan: `novel gate --require-approval` makes
severity=critical ReviewIssues require an explicit human approve/reject
decision before the workflow may advance.

This module is the pure logic layer (mirroring automation_contracts.py): it
owns the approval decision artifact model, the open critical/blocking issue
collection, and the approval verdict decision table. It deliberately imports
nothing from novel_cli or any provider/network module, so it is unit-testable
in isolation and cannot violate the Tier 0 contract
(provider_calls_implemented=false, no external calls).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from src.boundary_control.handoff import HandoffPacket
from src.boundary_control.review_object_contracts import review_issue_from_payload
from src.boundary_control.serialization import SerializationPackage

APPROVAL_DECISION_FILE = "approval_decision.json"
APPROVAL_GATE_CONTRACT_VERSION = 1

# Fields appended after the 13 standard gate JSON fields (novel_cli.py
# GATE_JSON_FIELDS) to form the approval gate JSON contract.
APPROVAL_GATE_EXTRA_FIELDS = (
    "approval_required",  # always True when --require-approval emits a verdict
    "critical_issue_ids",  # current open critical issue ids (deduped, sorted)
    "approval_decision",  # "approve" | "reject" | "-" (none required / no decision)
    "approval_ok",  # True iff every open critical issue is covered by an approve
)

# The exact violation string produced by
# OrchestrationGateUnit._continue_entry_violations for an unresolved open
# blocking issue. Extracted so approval-gate override logic cannot silently
# break if orchestration.py ever rewords it.
CONTINUE_BLOCKED_UNRESOLVED_ISSUE = (
    "route gate: ContinueUnit blocked by unresolved ReviewIssue"
)

_DECIDED_AT_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ApprovalDecision(BaseModel):
    """Operator-authored approval/reject decision artifact.

    Hand-written by the operator (the response-file precedent) and validated
    read-only by the gate. `extra="forbid"` pins the exact field set so a
    typo cannot silently pass.
    """

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="approve | reject")
    critical_issue_ids: list[str] = Field(
        description="critical issue ids this decision covers"
    )
    operator_note: str | None = Field(
        default=None, description="optional operator rationale"
    )
    decided_at_utc: str = Field(
        description="ISO8601 UTC decision timestamp, e.g. 2026-08-01T12:34:56Z"
    )

    @field_validator("decision")
    @classmethod
    def _decision_must_be_valid(
        cls, value: str, info: ValidationInfo
    ) -> str:
        _require_non_blank(value, info.field_name)
        if value not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")
        return value

    @field_validator("critical_issue_ids")
    @classmethod
    def _critical_issue_ids_must_be_non_empty_unique(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if not values:
            raise ValueError("critical_issue_ids must not be empty")
        seen: set[str] = set()
        for item in values:
            _require_non_blank(item, info.field_name)
            if item in seen:
                raise ValueError("critical_issue_ids entries must be unique")
            seen.add(item)
        return values

    @field_validator("operator_note")
    @classmethod
    def _operator_note_must_be_non_blank(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is not None:
            _require_non_blank(value, info.field_name)
        return value

    @field_validator("decided_at_utc")
    @classmethod
    def _decided_at_utc_must_be_iso8601(
        cls, value: str, info: ValidationInfo
    ) -> str:
        _require_non_blank(value, info.field_name)
        if not _DECIDED_AT_UTC_RE.match(value):
            raise ValueError(
                "decided_at_utc must be ISO8601 UTC with Z suffix, "
                "e.g. 2026-08-01T12:34:56Z"
            )
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"decided_at_utc is not a valid timestamp: {value}") from exc
        return value


def validate_approval_decision_payload(payload: object) -> ApprovalDecision:
    """Validate a raw approval decision payload into an ApprovalDecision."""
    return ApprovalDecision.model_validate(payload)


def load_approval_decision(path: Path) -> ApprovalDecision:
    """Load and validate the approval decision artifact at ``path``.

    Raises:
        ValueError: if the file is missing, is not valid JSON, or does not
            match the ApprovalDecision contract. The caller turns this into a
            blocked gate verdict (not a hard crash) so --json always emits the
            uniform approval-gate contract.
    """
    if not path.is_file():
        raise ValueError(f"missing approval decision file: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"invalid approval decision file: {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid approval decision JSON: {path}: {exc}") from exc
    try:
        return validate_approval_decision_payload(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid approval decision: {path}: {exc}") from exc


def _collect_open_review_issue_ids(
    items: tuple[Mapping[str, object], ...],
    *,
    severities: tuple[str, ...],
) -> set[str]:
    ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") is not None and item.get("type") != "ReviewIssue":
            continue
        try:
            issue = review_issue_from_payload(item)
        except (ValidationError, ValueError):
            continue
        if issue.resolution_status != "open":
            continue
        if issue.severity in severities:
            ids.add(issue.issue_id)
    return ids


def critical_review_issue_ids(
    packet: HandoffPacket,
    package: SerializationPackage | None,
) -> list[str]:
    """Collect open severity=critical ReviewIssue ids (deduped, sorted).

    Walks both delivery channels the gate sees: handoff open_items and the
    serialization package repair_control["ReviewIssue"]. Malformed items are
    skipped — the base orchestration gate already reports them as
    "incomplete ReviewIssue".
    """
    return _open_review_issue_ids(
        packet,
        package,
        severities=("critical",),
    )


def blocking_review_issue_ids(
    packet: HandoffPacket,
    package: SerializationPackage | None,
) -> list[str]:
    """Collect open severity=blocking ReviewIssue ids (deduped, sorted).

    Blocking issues are strictly not approvable; presence of any blocks the
    approve override even when all critical issues are covered.
    """
    return _open_review_issue_ids(
        packet,
        package,
        severities=("blocking",),
    )


def _open_review_issue_ids(
    packet: HandoffPacket,
    package: SerializationPackage | None,
    *,
    severities: tuple[str, ...],
) -> list[str]:
    ids: set[str] = set()
    ids.update(_collect_open_review_issue_ids(packet.open_items, severities=severities))
    if package is not None:
        repair_items = tuple(package.repair_control.get("ReviewIssue", []))
        ids.update(_collect_open_review_issue_ids(repair_items, severities=severities))
    return sorted(ids)


def resolve_approval_gate_verdict(
    *,
    critical_issue_ids: list[str],
    blocking_issue_ids: list[str],
    decision: ApprovalDecision | None,
    base_ok: bool,
    base_violations: list[str],
    review_route: str,
    next_workflow: str,
) -> dict[str, object]:
    """Resolve the approval gate verdict from the decision table.

    Decision table:
      A. no open critical        -> no approval path, base verdict unchanged.
      B. critical + no artifact  -> blocked (approval required).
      C. critical + reject       -> blocked (rejected by operator).
      D. critical + partial approve -> blocked (does not cover all ids).
      E. critical + full approve -> ok, next_workflow=ContinueUnit override,
                                    iff no blocking issue and the sole base
                                    violation is CONTINUE_BLOCKED_UNRESOLVED_ISSUE.
    """
    approval_required = bool(critical_issue_ids)
    if not approval_required:
        return {
            "approval_required": False,
            "critical_issue_ids": [],
            "approval_decision": "-",
            "approval_ok": True,
            "ok": base_ok,
            "next_workflow": next_workflow,
            "violations": base_violations,
        }

    if decision is None:
        return {
            "approval_required": True,
            "critical_issue_ids": critical_issue_ids,
            "approval_decision": "-",
            "approval_ok": False,
            "ok": False,
            "next_workflow": next_workflow,
            "violations": [
                "approval gate: "
                f"{len(critical_issue_ids)} critical issue(s) require operator "
                f"approval: {', '.join(critical_issue_ids)}"
            ],
        }

    if decision.decision == "reject":
        return {
            "approval_required": True,
            "critical_issue_ids": critical_issue_ids,
            "approval_decision": "reject",
            "approval_ok": False,
            "ok": False,
            "next_workflow": next_workflow,
            "violations": [
                "approval gate: critical issue(s) rejected by operator: "
                f"{', '.join(critical_issue_ids)}"
            ],
        }

    covered = set(decision.critical_issue_ids)
    open_ids = set(critical_issue_ids)
    uncovered = sorted(open_ids - covered)
    if uncovered:
        return {
            "approval_required": True,
            "critical_issue_ids": critical_issue_ids,
            "approval_decision": "approve",
            "approval_ok": False,
            "ok": False,
            "next_workflow": next_workflow,
            "violations": [
                "approval gate: approval does not cover critical issue(s): "
                f"{', '.join(uncovered)}"
            ],
        }

    # Full approve: determine whether the ContinueUnit override is legal.
    override = False
    if not blocking_issue_ids:
        residual = [
            violation
            for violation in base_violations
            if violation != CONTINUE_BLOCKED_UNRESOLVED_ISSUE
        ]
        if not residual:
            override = True

    if override:
        return {
            "approval_required": True,
            "critical_issue_ids": critical_issue_ids,
            "approval_decision": "approve",
            "approval_ok": True,
            "ok": True,
            "next_workflow": "ContinueUnit",
            "violations": [],
        }

    if blocking_issue_ids:
        # Blocking issues are strictly not approvable: even a full approve of
        # the critical issues cannot clear them. Return a hard failure naming
        # the blocking ids rather than echoing base_ok (which is True for a
        # rewrite/block handoff that legitimately carries a blocking issue).
        return {
            "approval_required": True,
            "critical_issue_ids": critical_issue_ids,
            "approval_decision": "approve",
            "approval_ok": True,
            "ok": False,
            "next_workflow": next_workflow,
            "violations": [
                "approval gate: blocking issue(s) not approvable by operator "
                f"approval: {', '.join(blocking_issue_ids)}"
            ],
        }

    # Approve covers all critical issues but a structural violation remains
    # (a base gate failure that operator approval of critical issues cannot
    # clear, e.g. a pending prompt newer than the handoff). Preserve the base
    # verdict verbatim.
    return {
        "approval_required": True,
        "critical_issue_ids": critical_issue_ids,
        "approval_decision": "approve",
        "approval_ok": True,
        "ok": base_ok,
        "next_workflow": next_workflow,
        "violations": base_violations,
    }
