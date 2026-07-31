"""Shared staged automation contract tests."""

import ast
import inspect

import pytest

import src.boundary_control.automation_contracts as automation_contracts
from src.boundary_control.automation_contracts import (
    PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING,
    PENDING_AUTOMATION_BLOCKER_NO_PENDING,
    PENDING_AUTOMATION_METADATA_FIELDS,
    PENDING_AUTOMATION_REASON_READY,
    RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    pending_automation_metadata,
    pending_automation_metadata_fragment,
    response_materialization_metadata,
    response_materialization_metadata_fragment,
    validate_pending_automation_metadata,
    validate_pending_automation_metadata_in_payload,
    validate_response_materialization_metadata,
    validate_response_materialization_metadata_in_payload,
)


def test_automation_contracts_module_stays_metadata_only():
    source = inspect.getsource(automation_contracts)
    tree = ast.parse(source)
    banned_import_roots = {
        "json",
        "pathlib",
        "src.boundary_control.handoff",
        "src.boundary_control.response_file",
        "src.boundary_control.orchestration",
        "src.llm_interface",
        "src.novel_cli",
    }
    banned_names = {
        "Path",
        "HandoffPacket",
        "HandoffBoundaryUnit",
        "OrchestrationGateUnit",
        "ResponseFileBoundaryUnit",
        "StagedResponseRunner",
        "DirectAPIInterface",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in banned_import_roots
        if isinstance(node, ast.ImportFrom):
            assert node.module not in banned_import_roots
        if isinstance(node, ast.Name):
            assert node.id not in banned_names


def test_pending_automation_metadata_fields_and_states_are_stable():
    ready = pending_automation_metadata(pending_count=1)
    no_pending = pending_automation_metadata(pending_count=0)
    multi_pending = pending_automation_metadata(pending_count=2)

    assert tuple(ready) == PENDING_AUTOMATION_METADATA_FIELDS
    assert ready["automation_ready"] is True
    assert ready["automation_ready_reason"] == PENDING_AUTOMATION_REASON_READY
    assert ready["automation_blockers"] == []
    assert no_pending["automation_ready"] is False
    assert (
        no_pending["automation_ready_reason"]
        == PENDING_AUTOMATION_BLOCKER_NO_PENDING
    )
    assert no_pending["automation_blockers"] == [PENDING_AUTOMATION_BLOCKER_NO_PENDING]
    assert multi_pending["automation_ready"] is False
    assert (
        multi_pending["automation_ready_reason"]
        == PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    )
    assert multi_pending["automation_blockers"] == [
        PENDING_AUTOMATION_BLOCKER_MULTIPLE_PENDING
    ]


def test_pending_automation_metadata_fragment_extracts_declared_fields():
    payload = {
        "command": "pending",
        **pending_automation_metadata(pending_count=1),
        "pending_count": 1,
    }
    fragment = pending_automation_metadata_fragment(payload)

    assert tuple(fragment) == PENDING_AUTOMATION_METADATA_FIELDS
    assert fragment == pending_automation_metadata(pending_count=1)
    validate_pending_automation_metadata(fragment, pending_count=1)
    validate_pending_automation_metadata_in_payload(payload, pending_count=1)

    missing = dict(payload)
    del missing["automation_blockers"]
    with pytest.raises(ValueError, match="missing pending automation metadata"):
        pending_automation_metadata_fragment(missing)
    with pytest.raises(ValueError, match="missing pending automation metadata"):
        validate_pending_automation_metadata_in_payload(missing, pending_count=1)


def test_pending_automation_metadata_rejects_non_string_keys():
    payload = pending_automation_metadata(pending_count=1)
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="pending automation metadata payload keys"):
        validate_pending_automation_metadata(payload, pending_count=1)

    source_payload = {
        "command": "pending",
        **pending_automation_metadata(pending_count=1),
        1: "adapter-only",
    }
    with pytest.raises(
        ValueError,
        match="pending automation metadata source payload keys",
    ):
        pending_automation_metadata_fragment(source_payload)
    with pytest.raises(
        ValueError,
        match="pending automation metadata source payload keys",
    ):
        validate_pending_automation_metadata_in_payload(source_payload, pending_count=1)


def test_automation_metadata_source_payloads_reject_credential_fields():
    pending_source = {
        "command": "pending",
        **pending_automation_metadata(pending_count=1),
        "api_key": "key-a",
    }

    with pytest.raises(ValueError, match="credential field"):
        pending_automation_metadata_fragment(pending_source)
    with pytest.raises(ValueError, match="credential field"):
        validate_pending_automation_metadata_in_payload(
            pending_source,
            pending_count=1,
        )

    response_source = {
        "command": "respond",
        **response_materialization_metadata(),
        "token": "provider-token",
    }

    with pytest.raises(ValueError, match="credential field"):
        response_materialization_metadata_fragment(response_source)
    with pytest.raises(ValueError, match="credential field"):
        validate_response_materialization_metadata_in_payload(response_source)


def test_automation_metadata_exact_payloads_reject_credential_fields():
    pending_payload = {
        **pending_automation_metadata(pending_count=1),
        "secret": "adapter-secret",
    }

    with pytest.raises(ValueError, match="credential field"):
        validate_pending_automation_metadata(pending_payload, pending_count=1)

    response_payload = {
        **response_materialization_metadata(),
        "credentials": "adapter-credentials",
    }

    with pytest.raises(ValueError, match="credential field"):
        validate_response_materialization_metadata(response_payload)


def test_automation_metadata_source_payloads_reject_execution_claim_fields():
    pending_source = {
        "command": "pending",
        **pending_automation_metadata(pending_count=1),
        "provider_call_result": "provider was called",
    }

    with pytest.raises(ValueError, match="execution claim field"):
        pending_automation_metadata_fragment(pending_source)
    with pytest.raises(ValueError, match="execution claim field"):
        validate_pending_automation_metadata_in_payload(
            pending_source,
            pending_count=1,
        )

    response_source = {
        "command": "respond",
        **response_materialization_metadata(),
        "fallback_provider": "backup-model",
    }

    with pytest.raises(ValueError, match="execution claim field"):
        response_materialization_metadata_fragment(response_source)
    with pytest.raises(ValueError, match="execution claim field"):
        validate_response_materialization_metadata_in_payload(response_source)


def test_automation_metadata_exact_payloads_reject_execution_claim_fields():
    pending_payload = {
        **pending_automation_metadata(pending_count=1),
        "retry": True,
    }

    with pytest.raises(ValueError, match="execution claim field"):
        validate_pending_automation_metadata(pending_payload, pending_count=1)

    response_payload = {
        **response_materialization_metadata(),
        "closed_loop_result": "advanced",
    }

    with pytest.raises(ValueError, match="execution claim field"):
        validate_response_materialization_metadata(response_payload)


def test_automation_metadata_source_payloads_reject_cross_contract_metadata_fields():
    pending_source = {
        "command": "pending",
        **pending_automation_metadata(pending_count=1),
        "provider_call_performed": False,
    }

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        pending_automation_metadata_fragment(pending_source)
    with pytest.raises(ValueError, match="cross-contract metadata field"):
        validate_pending_automation_metadata_in_payload(
            pending_source,
            pending_count=1,
        )

    response_source = {
        "command": "respond",
        **response_materialization_metadata(),
        "automation_ready": True,
    }

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        response_materialization_metadata_fragment(response_source)
    with pytest.raises(ValueError, match="cross-contract metadata field"):
        validate_response_materialization_metadata_in_payload(response_source)


def test_pending_automation_metadata_validator_rejects_invalid_payloads():
    payload = pending_automation_metadata(pending_count=1)

    validate_pending_automation_metadata(payload, pending_count=1)
    with pytest.raises(ValueError, match="payload must be an object"):
        validate_pending_automation_metadata([], pending_count=1)
    with pytest.raises(ValueError, match="automation_ready"):
        validate_pending_automation_metadata(payload, pending_count=0)
    missing = dict(payload)
    del missing["automation_contract"]
    with pytest.raises(ValueError, match="missing pending automation metadata"):
        validate_pending_automation_metadata(missing, pending_count=1)
    extra = dict(payload)
    extra["adapter_guess"] = "selected_by_timestamp"
    with pytest.raises(ValueError, match="unknown pending automation metadata"):
        validate_pending_automation_metadata(extra, pending_count=1)


def test_pending_automation_metadata_validator_rejects_numeric_boolean_values():
    payload = pending_automation_metadata(pending_count=1)

    numeric_ready = dict(payload)
    numeric_ready["automation_ready"] = 1
    with pytest.raises(ValueError, match="automation_ready"):
        validate_pending_automation_metadata(numeric_ready, pending_count=1)

    numeric_provider_flag = dict(payload)
    numeric_provider_flag["provider_calls_implemented"] = 0
    with pytest.raises(ValueError, match="provider_calls_implemented"):
        validate_pending_automation_metadata(
            numeric_provider_flag,
            pending_count=1,
        )

    numeric_closed_loop_flag = dict(payload)
    numeric_closed_loop_flag["closed_loop_allowed"] = 0
    with pytest.raises(ValueError, match="closed_loop_allowed"):
        validate_pending_automation_metadata(
            numeric_closed_loop_flag,
            pending_count=1,
        )


def test_pending_automation_metadata_validator_rejects_non_list_blockers():
    payload = pending_automation_metadata(pending_count=0)
    payload["automation_blockers"] = PENDING_AUTOMATION_BLOCKER_NO_PENDING

    with pytest.raises(ValueError, match="automation_blockers must be a list"):
        validate_pending_automation_metadata(payload, pending_count=0)


@pytest.mark.parametrize("blocker", [" ", 1])
def test_pending_automation_metadata_validator_rejects_invalid_blocker_entries(
    blocker,
):
    payload = pending_automation_metadata(pending_count=0)
    payload["automation_blockers"] = [blocker]

    with pytest.raises(ValueError, match="entries must be non-empty strings"):
        validate_pending_automation_metadata(payload, pending_count=0)


@pytest.mark.parametrize(
    "field",
    ["automation_contract", "automation_ready_reason", "allowed_automation_action"],
)
@pytest.mark.parametrize("value", [" ", 1])
def test_pending_automation_metadata_validator_rejects_invalid_string_fields(
    field,
    value,
):
    payload = pending_automation_metadata(pending_count=1)
    payload[field] = value

    with pytest.raises(ValueError, match=rf"{field} must be a non-empty string"):
        validate_pending_automation_metadata(payload, pending_count=1)


def test_pending_automation_metadata_validator_rejects_bool_contract_version():
    payload = pending_automation_metadata(pending_count=1)
    payload["automation_contract_version"] = True

    with pytest.raises(ValueError, match="automation_contract_version"):
        validate_pending_automation_metadata(payload, pending_count=1)


def test_response_materialization_metadata_fields_are_stable():
    payload = response_materialization_metadata()

    assert tuple(payload) == RESPONSE_MATERIALIZATION_METADATA_FIELDS
    validate_response_materialization_metadata(payload)


def test_response_materialization_metadata_fragment_extracts_declared_fields():
    payload = {
        "command": "respond",
        **response_materialization_metadata(),
        "response_hash": "abc",
    }
    fragment = response_materialization_metadata_fragment(payload)

    assert tuple(fragment) == RESPONSE_MATERIALIZATION_METADATA_FIELDS
    assert fragment == response_materialization_metadata()
    validate_response_materialization_metadata(fragment)
    validate_response_materialization_metadata_in_payload(payload)

    missing = dict(payload)
    del missing["materialized_action"]
    with pytest.raises(ValueError, match="missing response materialization metadata"):
        response_materialization_metadata_fragment(missing)
    with pytest.raises(ValueError, match="missing response materialization metadata"):
        validate_response_materialization_metadata_in_payload(missing)


def test_response_materialization_metadata_rejects_non_string_keys():
    payload = response_materialization_metadata()
    payload[1] = "adapter-only"

    with pytest.raises(
        ValueError,
        match="response materialization metadata payload keys",
    ):
        validate_response_materialization_metadata(payload)

    source_payload = {
        "command": "respond",
        **response_materialization_metadata(),
        1: "adapter-only",
    }
    with pytest.raises(
        ValueError,
        match="response materialization metadata source payload keys",
    ):
        response_materialization_metadata_fragment(source_payload)
    with pytest.raises(
        ValueError,
        match="response materialization metadata source payload keys",
    ):
        validate_response_materialization_metadata_in_payload(source_payload)


def test_response_materialization_metadata_validator_rejects_invalid_payloads():
    payload = response_materialization_metadata()

    with pytest.raises(ValueError, match="payload must be an object"):
        validate_response_materialization_metadata([])
    bad_action = dict(payload)
    bad_action["materialized_action"] = "call_provider"
    with pytest.raises(ValueError, match="materialized_action"):
        validate_response_materialization_metadata(bad_action)
    bad_provider_flag = dict(payload)
    bad_provider_flag["provider_call_performed"] = True
    with pytest.raises(ValueError, match="provider_call_performed"):
        validate_response_materialization_metadata(bad_provider_flag)
    extra = dict(payload)
    extra["raw_response_text"] = "must stay out of audit metadata"
    with pytest.raises(ValueError, match="unknown response materialization metadata"):
        validate_response_materialization_metadata(extra)


@pytest.mark.parametrize("field", ["provider_call_performed", "closed_loop_advanced"])
def test_response_materialization_metadata_rejects_numeric_false_flags(field):
    payload = response_materialization_metadata()
    payload[field] = 0

    with pytest.raises(ValueError, match=rf"{field} must be exact false"):
        validate_response_materialization_metadata(payload)


def test_response_materialization_metadata_validator_rejects_bool_contract_version():
    payload = response_materialization_metadata()
    payload["materialization_contract_version"] = True

    with pytest.raises(ValueError, match="materialization_contract_version"):
        validate_response_materialization_metadata(payload)
