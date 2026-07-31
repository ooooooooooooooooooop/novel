"""Shared staged automation metadata contracts.

This module defines names, field order, payload fragments, and fragment
validators only. It must stay independent from filesystem, provider, workflow,
route, and staged-response side effects.
"""

PENDING_AUTOMATION_CONTRACT_VERSION = 1
PENDING_AUTOMATION_CONTRACT = "pending_staged_response_preflight"
PENDING_AUTOMATION_ACTION = "materialize_staged_response_only"
PENDING_AUTOMATION_REASON_READY = "single_verified_pending_slot"
PENDING_AUTOMATION_BLOCKER_NO_PENDING = "no_pending_slots"
PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING = (
    "multiple_pending_slots_require_slot_id"
)
PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED = False
PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED = False
PENDING_AUTOMATION_METADATA_FIELDS = (
    "automation_contract_version",
    "automation_contract",
    "automation_ready",
    "automation_ready_reason",
    "automation_blockers",
    "allowed_automation_action",
    "provider_calls_implemented",
    "closed_loop_allowed",
)
PENDING_AUTOMATION_BOOLEAN_FIELDS = (
    "automation_ready",
    "provider_calls_implemented",
    "closed_loop_allowed",
)
PENDING_AUTOMATION_STRING_FIELDS = (
    "automation_contract",
    "automation_ready_reason",
    "allowed_automation_action",
)
AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS = (
    "api_key",
    "credential",
    "credentials",
    "secret",
    "token",
)
AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS = (
    "closed_loop_result",
    "fallback_provider",
    "provider_call_result",
    "provider_response",
    "retry",
)

RESPONSE_MATERIALIZATION_CONTRACT_VERSION = 1
RESPONSE_MATERIALIZATION_CONTRACT = "staged_response_materialization"
RESPONSE_PROVIDER_CALL_PERFORMED = False
RESPONSE_CLOSED_LOOP_ADVANCED = False
RESPONSE_MATERIALIZATION_METADATA_FIELDS = (
    "materialization_contract_version",
    "materialization_contract",
    "materialized_action",
    "provider_call_performed",
    "closed_loop_advanced",
)


def _require_string_keys(payload: dict[object, object], label: str) -> None:
    if any(not isinstance(field, str) for field in payload):
        raise ValueError(f"{label} keys must be strings")


def _require_no_credential_fields(payload: dict[object, object], label: str) -> None:
    forbidden = [
        field for field in AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS if field in payload
    ]
    if forbidden:
        raise ValueError(
            f"{label} must not include credential field(s): "
            f"{', '.join(forbidden)}"
        )


def _require_no_execution_claim_fields(
    payload: dict[object, object],
    label: str,
) -> None:
    forbidden = [
        field for field in AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS if field in payload
    ]
    if forbidden:
        raise ValueError(
            f"{label} must not include execution claim field(s): "
            f"{', '.join(forbidden)}"
        )


def _require_no_cross_contract_metadata_fields(
    payload: dict[object, object],
    *,
    forbidden_fields: tuple[str, ...],
    label: str,
) -> None:
    forbidden = [field for field in forbidden_fields if field in payload]
    if forbidden:
        raise ValueError(
            f"{label} must not include cross-contract metadata field(s): "
            f"{', '.join(forbidden)}"
        )


def _require_string_list(value: object, label: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} entries must be non-empty strings")


def _require_non_empty_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def pending_automation_metadata(*, pending_count: int) -> dict[str, object]:
    if (
        not isinstance(pending_count, int)
        or isinstance(pending_count, bool)
        or pending_count < 0
    ):
        raise ValueError("pending_count must be a non-negative integer")
    if pending_count == 1:
        readiness = PENDING_AUTOMATION_REASON_READY
        blockers: list[str] = []
    elif pending_count == 0:
        readiness = PENDING_AUTOMATION_BLOCKER_NO_PENDING
        blockers = [PENDING_AUTOMATION_BLOCKER_NO_PENDING]
    else:
        readiness = PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
        blockers = [PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING]
    metadata = {
        "automation_contract_version": PENDING_AUTOMATION_CONTRACT_VERSION,
        "automation_contract": PENDING_AUTOMATION_CONTRACT,
        "automation_ready": pending_count == 1,
        "automation_ready_reason": readiness,
        "automation_blockers": blockers,
        "allowed_automation_action": PENDING_AUTOMATION_ACTION,
        "provider_calls_implemented": PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED,
        "closed_loop_allowed": PENDING_AUTOMATION_CLOSED_LOOP_ALLOWED,
    }
    return {field: metadata[field] for field in PENDING_AUTOMATION_METADATA_FIELDS}


def pending_automation_metadata_fragment(
    payload: dict[object, object],
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("pending automation metadata source payload must be an object")
    _require_string_keys(payload, "pending automation metadata source payload")
    _require_no_credential_fields(
        payload,
        "pending automation metadata source payload",
    )
    _require_no_execution_claim_fields(
        payload,
        "pending automation metadata source payload",
    )
    _require_no_cross_contract_metadata_fields(
        payload,
        forbidden_fields=RESPONSE_MATERIALIZATION_METADATA_FIELDS,
        label="pending automation metadata source payload",
    )
    missing = [
        field for field in PENDING_AUTOMATION_METADATA_FIELDS if field not in payload
    ]
    if missing:
        raise ValueError(
            "missing pending automation metadata field(s): "
            f"{', '.join(missing)}"
        )
    return {field: payload[field] for field in PENDING_AUTOMATION_METADATA_FIELDS}


def validate_pending_automation_metadata(
    payload: dict[object, object],
    *,
    pending_count: int,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("pending automation metadata payload must be an object")
    _require_string_keys(payload, "pending automation metadata payload")
    _require_no_credential_fields(payload, "pending automation metadata payload")
    _require_no_execution_claim_fields(
        payload,
        "pending automation metadata payload",
    )
    expected = pending_automation_metadata(pending_count=pending_count)
    missing = [
        field for field in PENDING_AUTOMATION_METADATA_FIELDS if field not in payload
    ]
    if missing:
        raise ValueError(
            "missing pending automation metadata field(s): "
            f"{', '.join(missing)}"
        )
    unknown = [
        str(field) for field in payload if field not in PENDING_AUTOMATION_METADATA_FIELDS
    ]
    if unknown:
        raise ValueError(
            "unknown pending automation metadata field(s): "
            f"{', '.join(unknown)}"
        )
    for field in PENDING_AUTOMATION_METADATA_FIELDS:
        expected_value = expected[field]
        actual_value = payload[field]
        if field == "automation_contract_version":
            if (
                not isinstance(actual_value, int)
                or isinstance(actual_value, bool)
                or actual_value != expected_value
            ):
                raise ValueError(
                    f"unsupported pending automation metadata {field}: "
                    f"{actual_value}"
                )
            continue
        if field in PENDING_AUTOMATION_BOOLEAN_FIELDS:
            if actual_value is not expected_value:
                raise ValueError(
                    f"unsupported pending automation metadata {field}: "
                    f"{actual_value}"
                )
            continue
        if field == "automation_blockers":
            _require_string_list(
                actual_value,
                "pending automation metadata automation_blockers",
            )
        if field in PENDING_AUTOMATION_STRING_FIELDS:
            _require_non_empty_string(
                actual_value,
                f"pending automation metadata {field}",
            )
        if actual_value != expected_value:
            raise ValueError(
                f"unsupported pending automation metadata {field}: "
                f"{actual_value}"
            )


def validate_pending_automation_metadata_in_payload(
    payload: dict[object, object],
    *,
    pending_count: int,
) -> None:
    validate_pending_automation_metadata(
        pending_automation_metadata_fragment(payload),
        pending_count=pending_count,
    )


def response_materialization_metadata() -> dict[str, object]:
    metadata = {
        "materialization_contract_version": (
            RESPONSE_MATERIALIZATION_CONTRACT_VERSION
        ),
        "materialization_contract": RESPONSE_MATERIALIZATION_CONTRACT,
        "materialized_action": PENDING_AUTOMATION_ACTION,
        "provider_call_performed": RESPONSE_PROVIDER_CALL_PERFORMED,
        "closed_loop_advanced": RESPONSE_CLOSED_LOOP_ADVANCED,
    }
    return {
        field: metadata[field] for field in RESPONSE_MATERIALIZATION_METADATA_FIELDS
    }


def response_materialization_metadata_fragment(
    payload: dict[object, object],
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError(
            "response materialization metadata source payload must be an object"
        )
    _require_string_keys(
        payload,
        "response materialization metadata source payload",
    )
    _require_no_credential_fields(
        payload,
        "response materialization metadata source payload",
    )
    _require_no_execution_claim_fields(
        payload,
        "response materialization metadata source payload",
    )
    _require_no_cross_contract_metadata_fields(
        payload,
        forbidden_fields=PENDING_AUTOMATION_METADATA_FIELDS,
        label="response materialization metadata source payload",
    )
    missing = [
        field
        for field in RESPONSE_MATERIALIZATION_METADATA_FIELDS
        if field not in payload
    ]
    if missing:
        raise ValueError(
            "missing response materialization metadata field(s): "
            f"{', '.join(missing)}"
        )
    return {
        field: payload[field] for field in RESPONSE_MATERIALIZATION_METADATA_FIELDS
    }


def _metadata_string(payload: dict[object, object], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"response materialization metadata {field} must be a non-empty string"
        )
    return value


def _metadata_exact_false(payload: dict[object, object], field: str) -> None:
    if payload[field] is not False:
        raise ValueError(
            f"response materialization metadata {field} must be exact false"
        )


def validate_response_materialization_metadata(
    payload: dict[object, object],
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("response materialization metadata payload must be an object")
    _require_string_keys(payload, "response materialization metadata payload")
    _require_no_credential_fields(
        payload,
        "response materialization metadata payload",
    )
    _require_no_execution_claim_fields(
        payload,
        "response materialization metadata payload",
    )
    expected = response_materialization_metadata()
    missing = [
        field
        for field in RESPONSE_MATERIALIZATION_METADATA_FIELDS
        if field not in payload
    ]
    if missing:
        raise ValueError(
            "missing response materialization metadata field(s): "
            f"{', '.join(missing)}"
        )
    unknown = [
        str(field)
        for field in payload
        if field not in RESPONSE_MATERIALIZATION_METADATA_FIELDS
    ]
    if unknown:
        raise ValueError(
            "unknown response materialization metadata field(s): "
            f"{', '.join(unknown)}"
        )
    materialization_contract_version = payload[
        "materialization_contract_version"
    ]
    if (
        not isinstance(materialization_contract_version, int)
        or isinstance(materialization_contract_version, bool)
        or materialization_contract_version
        != RESPONSE_MATERIALIZATION_CONTRACT_VERSION
    ):
        raise ValueError(
            "unsupported response materialization metadata "
            "materialization_contract_version: "
            f"{materialization_contract_version}"
        )
    materialization_contract = _metadata_string(
        payload,
        "materialization_contract",
    )
    if materialization_contract != RESPONSE_MATERIALIZATION_CONTRACT:
        raise ValueError(
            "unsupported response materialization metadata "
            "materialization_contract: "
            f"{materialization_contract}"
        )
    materialized_action = _metadata_string(payload, "materialized_action")
    if materialized_action != PENDING_AUTOMATION_ACTION:
        raise ValueError(
            "unsupported response materialization metadata materialized_action: "
            f"{materialized_action}"
        )
    _metadata_exact_false(payload, "provider_call_performed")
    _metadata_exact_false(payload, "closed_loop_advanced")


def validate_response_materialization_metadata_in_payload(
    payload: dict[object, object],
) -> None:
    validate_response_materialization_metadata(
        response_materialization_metadata_fragment(payload)
    )
