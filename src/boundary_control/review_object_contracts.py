"""Shared ReviewIssue / ReviewReminder boundary contracts."""

from collections.abc import Mapping

from src.object_state.reviewissue import ReviewIssue, ReviewReminder


def _payload_object(payload: object, label: str) -> dict:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{label} payload keys must be strings")
    return dict(payload)


def _payload_type(payload: dict, label: str) -> None:
    payload_type = payload.get("type")
    if payload_type is not None and payload_type != label:
        raise ValueError(f"{label} payload type must be {label}")


def review_issue_from_payload(issue: object) -> ReviewIssue:
    """Validate a ReviewIssue payload with the handoff status alias."""
    issue = _payload_object(issue, "ReviewIssue")
    _payload_type(issue, "ReviewIssue")
    payload = {
        key: value for key, value in issue.items() if key not in {"type", "status"}
    }
    status = issue.get("status")
    resolution_status = issue.get("resolution_status")
    if status is not None:
        if resolution_status is not None and status != resolution_status:
            raise ValueError("ReviewIssue status fields conflict")
        if resolution_status is None:
            payload["resolution_status"] = status
    return ReviewIssue(**payload)


def review_reminder_from_payload(reminder: object) -> ReviewReminder:
    """Validate a ReviewReminder payload with optional handoff type metadata."""
    reminder = _payload_object(reminder, "ReviewReminder")
    _payload_type(reminder, "ReviewReminder")
    payload = {key: value for key, value in reminder.items() if key != "type"}
    return ReviewReminder(**payload)


def review_issue_open_item(issue: object) -> dict:
    """Build a ReviewIssue handoff open item after runtime model validation."""
    validated = review_issue_from_payload(issue).model_dump(mode="json")
    return {
        **validated,
        "type": "ReviewIssue",
        "status": validated.get("resolution_status", "open"),
    }


def review_reminder_open_item(reminder: object) -> dict:
    """Build a ReviewReminder handoff open item after runtime model validation."""
    validated = review_reminder_from_payload(reminder).model_dump(mode="json")
    return {
        **validated,
        "type": "ReviewReminder",
        "status": validated.get("status", "active"),
    }
