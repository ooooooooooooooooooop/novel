"""Regression tests for orchestration gate movement."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.boundary_control.handoff import HandoffBoundaryUnit, HandoffPacket, NextRoute
from src.boundary_control.orchestration import OrchestrationGateUnit
from src.boundary_control.review_object_contracts import (
    review_issue_from_payload,
    review_issue_open_item,
    review_reminder_from_payload,
    review_reminder_open_item,
)
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state import (
    FactEntry,
    FactLedger,
    NarrativeState,
    ReviewIssue,
    ReviewReminder,
    WorkSpec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _packet(target: str, next_route: NextRoute) -> HandoffPacket:
    review_target_ref = "review_result.json"
    route_update = {}
    if review_target_ref not in next_route.must_read_first:
        route_update["must_read_first"] = [
            *next_route.must_read_first,
            review_target_ref,
        ]
    if not next_route.do_not_skip:
        route_update["do_not_skip"] = ["honor ReviewIssue and ReviewReminder state"]
    if route_update:
        next_route = next_route.model_copy(update=route_update)
    return HandoffPacket(
        handoff_header={
            "source": "ReviewUnit",
            "target": target,
            "reason": next_route.route_reason,
        },
        input_anchor={"review_target_ref": review_target_ref},
        output_anchor={"state_ref": "ns_001"},
        change_set=[
            {
                "action": "review",
                "route": next_route.review_route,
                "issue_count": 0,
                "reminder_count": 0,
            }
        ],
        next_route=next_route,
    )


def _base_package():
    return SerializationBoundaryUnit().build_package(
        WorkSpec(
            genre="test",
            audience="test",
            theme="test",
            tone="test",
            pacing="test",
        ),
        NarrativeState(
            state_id="ns_001",
            current_time="now",
            current_location="room",
            current_situation="ready",
        ),
    )


def _package_with_layer_item(package, layer_name: str, type_name: str, items: list):
    layer = package.model_dump()[layer_name]
    layer[type_name] = items
    return package.model_copy(update={layer_name: layer})


def _corrupt_package_layer(package, layer_name: str, type_name: str, items: object):
    layer = package.model_dump()[layer_name]
    layer[type_name] = items
    object.__setattr__(package, layer_name, layer)
    return package


def _package_with_repair_items(package, type_name: str, items: list):
    return _package_with_layer_item(package, "repair_control", type_name, items)


def _handoff_review_issue(**overrides):
    issue = {
        "type": "ReviewIssue",
        "issue_id": "iss_handoff",
        "issue_type": "fact_conflict",
        "severity": "blocking",
        "location": "FactLedger",
        "scope_of_impact": "current packet",
        "violated_rule": "route gate",
        "description": "handoff issue blocks movement",
    }
    for key, value in overrides.items():
        if value is None:
            issue.pop(key, None)
        else:
            issue[key] = value
    return issue


def _handoff_review_reminder(**overrides):
    reminder = {
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
            reminder.pop(key, None)
        else:
            reminder[key] = value
    return reminder


def _append_open_item(packet: HandoffPacket, item: object) -> None:
    object.__setattr__(packet, "open_items", (*packet.open_items, item))
    if not isinstance(item, Mapping):
        return
    if not packet.change_set:
        return
    review_entry = dict(packet.change_set[0])
    if review_entry.get("action") != "review":
        return
    field_name = None
    if item.get("type") == "ReviewIssue":
        field_name = "issue_count"
    if item.get("type") == "ReviewReminder":
        field_name = "reminder_count"
    if field_name is None:
        return
    review_entry[field_name] = int(review_entry.get(field_name, 0)) + 1
    object.__setattr__(packet, "change_set", (review_entry, *packet.change_set[1:]))


def test_orchestration_gate_uses_runtime_models_for_review_objects():
    source = (PROJECT_ROOT / "src/boundary_control/orchestration.py").read_text(
        encoding="utf-8"
    )
    contract_source = (
        PROJECT_ROOT / "src/boundary_control/review_object_contracts.py"
    ).read_text(encoding="utf-8")

    assert "review_issue_from_payload" in source
    assert "review_reminder_from_payload" in source
    assert "ReviewIssue(**payload)" in contract_source
    assert "ReviewReminder(**payload)" in contract_source
    assert "REQUIRED_OPEN_REVIEW_ISSUE_FIELDS" not in source
    assert "OPEN_REVIEW_ISSUE_" not in source
    assert "REMINDER_ESCALATION_MATRIX" not in source


def test_handoff_and_gate_share_review_object_contract_helpers():
    handoff_source = (PROJECT_ROOT / "src/boundary_control/handoff.py").read_text(
        encoding="utf-8"
    )
    gate_source = (PROJECT_ROOT / "src/boundary_control/orchestration.py").read_text(
        encoding="utf-8"
    )

    assert "review_object_contracts import" in handoff_source
    assert "review_object_contracts import" in gate_source
    assert "ReviewIssue(**payload)" not in handoff_source
    assert "ReviewIssue(**payload)" not in gate_source
    assert "ReviewReminder(**payload)" not in handoff_source
    assert "ReviewReminder(**payload)" not in gate_source


@pytest.mark.parametrize(
    "parser",
    [
        review_issue_from_payload,
        review_issue_open_item,
        review_reminder_from_payload,
        review_reminder_open_item,
    ],
)
def test_review_object_contract_helpers_reject_non_object_payloads(parser):
    with pytest.raises(ValueError, match="payload must be an object"):
        parser(["not", "an", "object"])


@pytest.mark.parametrize(
    "parser",
    [
        review_issue_from_payload,
        review_issue_open_item,
        review_reminder_from_payload,
        review_reminder_open_item,
    ],
)
def test_review_object_contract_helpers_reject_non_string_keys(parser):
    with pytest.raises(ValueError, match="payload keys must be strings"):
        parser({1: "not a json object key"})


@pytest.mark.parametrize(
    ("parser", "payload", "expected_type"),
    [
        (
            review_issue_from_payload,
            _handoff_review_issue(type="ReviewReminder"),
            "ReviewIssue",
        ),
        (
            review_issue_open_item,
            _handoff_review_issue(type="ReviewReminder"),
            "ReviewIssue",
        ),
        (
            review_reminder_from_payload,
            _handoff_review_reminder(type="ReviewIssue"),
            "ReviewReminder",
        ),
        (
            review_reminder_open_item,
            _handoff_review_reminder(type="ReviewIssue"),
            "ReviewReminder",
        ),
    ],
)
def test_review_object_contract_helpers_reject_conflicting_type_metadata(
    parser, payload, expected_type
):
    with pytest.raises(ValueError, match=f"payload type must be {expected_type}"):
        parser(payload)


def test_rebuild_to_review_handoff_can_enter_review():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ReviewUnit",
            "reason": "reconstruction complete",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=[{"action": "create", "objects": ["WorkSpec"]}],
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = gate.verify_entry(packet)

    assert ok
    assert violations == []


def test_handoff_verify_reports_malformed_outer_container_fields():
    cases = [
        ("handoff_header", ["not", "an", "object"], "handoff_header must be an object"),
        ("input_anchor", ["not", "an", "object"], "input_anchor must be an object"),
        ("output_anchor", ["not", "an", "object"], "output_anchor must be an object"),
        (
            "confidence_and_gaps",
            ["not", "an", "object"],
            "confidence_and_gaps must be an object",
        ),
        ("change_set", {"not": "a list"}, "change_set must be a list"),
        ("change_set", [["not", "an", "object"]], "change_set entries must be objects"),
        ("open_items", {"not": "a list"}, "open_items must be a list"),
        ("open_items", [["not", "an", "object"]], "open_items entries must be objects"),
        ("next_route", "ReviewUnit", "next_route must be a structured NextRoute"),
    ]

    for field_name, value, expected_violation in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )
        object.__setattr__(packet, field_name, value)

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("open_item", "expected_violation"),
    [
        (
            _handoff_review_issue(description=None),
            "open_items ReviewIssue must match runtime model",
        ),
        (
            _handoff_review_reminder(window=None),
            "open_items ReviewReminder must match runtime model",
        ),
    ],
)
def test_handoff_verify_rejects_incomplete_review_open_items(
    open_item,
    expected_violation,
):
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review complete",
            review_route="pass",
        ),
    )
    _append_open_item(packet, open_item)

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


def test_handoff_packet_rejects_invalid_assignment_shapes():
    cases = [
        ("handoff_header", ["not", "an", "object"]),
        ("input_anchor", ["not", "an", "object"]),
        ("output_anchor", ["not", "an", "object"]),
        ("confidence_and_gaps", ["not", "an", "object"]),
        ("change_set", {"not": "a list"}),
        ("change_set", [["not", "an", "object"]]),
        ("open_items", {"not": "a list"}),
        ("open_items", [["not", "an", "object"]]),
        ("next_route", "ReviewUnit"),
        ("handoff_header", {1: "bad"}),
        ("input_anchor", {1: "bad"}),
        ("output_anchor", {1: "bad"}),
        ("confidence_and_gaps", {1: "bad"}),
        ("change_set", [{1: "bad"}]),
        ("open_items", [{1: "bad"}]),
    ]

    for field_name, value in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )

        with pytest.raises(ValidationError):
            setattr(packet, field_name, value)

        packet_data = {
            "handoff_header": {"source": "RebuildUnit", "target": "ReviewUnit"},
            "input_anchor": {"source_text": "input.txt"},
            "output_anchor": {"reconstructed_objects": {"WorkSpec": {}}},
            "next_route": NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        }
        packet_data[field_name] = value

        with pytest.raises(ValidationError):
            HandoffPacket(**packet_data)

        with pytest.raises(ValidationError):
            packet.model_copy(update={field_name: value})

    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ReviewUnit",
            "reason": "reconstruction complete",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=[{"action": "create"}],
        open_items=[{"type": "confidence_gap", "content": "uncertain"}],
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    assert packet.change_set == ({"action": "create"},)
    assert packet.open_items == ({"type": "confidence_gap", "content": "uncertain"},)
    assert packet.model_dump()["change_set"] == [{"action": "create"}]
    assert packet.model_dump()["open_items"] == [
        {"type": "confidence_gap", "content": "uncertain"}
    ]
    assert packet.model_dump()["handoff_header"] == {
        "source": "RebuildUnit",
        "target": "ReviewUnit",
        "reason": "reconstruction complete",
    }
    with pytest.raises(AttributeError):
        packet.open_items.append({"type": "late_mutation"})
    with pytest.raises(TypeError):
        packet.handoff_header["late"] = "mutation"
    with pytest.raises(TypeError):
        packet.change_set[0]["late"] = "mutation"
    with pytest.raises(TypeError):
        packet.open_items[0]["late"] = "mutation"
    copied = packet.model_copy(update={"confidence_and_gaps": {"gaps": ["known"]}})
    assert copied.confidence_and_gaps == {"gaps": ["known"]}
    assert copied.model_dump()["confidence_and_gaps"] == {"gaps": ["known"]}
    with pytest.raises(TypeError):
        copied.confidence_and_gaps["late"] = "mutation"
    deep_copied = packet.model_copy(deep=True)
    assert deep_copied.model_dump() == packet.model_dump()
    with pytest.raises(TypeError):
        deep_copied.handoff_header["late"] = "mutation"
    deep_updated = packet.model_copy(
        update={"confidence_and_gaps": {"gaps": ["deep-known"]}},
        deep=True,
    )
    assert deep_updated.model_dump()["confidence_and_gaps"] == {
        "gaps": ["deep-known"]
    }
    with pytest.raises(TypeError):
        deep_updated.confidence_and_gaps["late"] = "mutation"


def test_handoff_verify_reports_non_string_outer_object_keys():
    cases = [
        ("handoff_header", {1: "bad"}, "handoff_header keys must be strings"),
        ("input_anchor", {1: "bad"}, "input_anchor keys must be strings"),
        ("output_anchor", {1: "bad"}, "output_anchor keys must be strings"),
        (
            "confidence_and_gaps",
            {1: "bad"},
            "confidence_and_gaps keys must be strings",
        ),
        ("change_set", [{1: "bad"}], "change_set entries keys must be strings"),
        ("open_items", [{1: "bad"}], "open_items entries keys must be strings"),
    ]

    for field_name, value, expected_violation in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )
        object.__setattr__(packet, field_name, value)

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    "change_set",
    [
        [{"objects": ["WorkSpec"]}],
        [{"action": " ", "objects": ["WorkSpec"]}],
        [{"action": 1, "objects": ["WorkSpec"]}],
    ],
)
def test_handoff_verify_requires_change_set_entries_to_include_action(change_set):
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ReviewUnit",
            "reason": "reconstruction complete",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=change_set,
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(
        "change_set entries must include non-empty action" in violation
        for violation in violations
    )


@pytest.mark.parametrize(
    ("gaps", "expected_violation"),
    [
        ("gap text", "confidence_and_gaps.gaps must be a list"),
        ([1], "confidence_and_gaps.gaps entries must be non-empty strings"),
        ([" "], "confidence_and_gaps.gaps entries must be non-empty strings"),
    ],
)
def test_handoff_verify_rejects_invalid_confidence_gaps(gaps, expected_violation):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        confidence_and_gaps={"gaps": gaps},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize("content", [" ", 1, None])
def test_handoff_verify_rejects_invalid_confidence_gap_open_items(content):
    item = {"type": "confidence_gap"}
    if content is not None:
        item["content"] = content
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        open_items=[item],
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(
        "open_items confidence_gap content must be a non-empty string" in violation
        for violation in violations
    )


@pytest.mark.parametrize(
    ("confidence_and_gaps", "open_items"),
    [
        ({}, [{"type": "confidence_gap", "content": "uncertain source"}]),
        ({"gaps": ["uncertain source"]}, []),
        (
            {"gaps": ["uncertain source"]},
            [{"type": "confidence_gap", "content": "different source"}],
        ),
    ],
)
def test_handoff_verify_requires_confidence_gap_open_items_to_match_gaps(
    confidence_and_gaps,
    open_items,
):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=[{"action": "create", "objects": ["WorkSpec"]}],
        open_items=open_items,
        confidence_and_gaps=confidence_and_gaps,
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(
        "confidence_gap open items must match confidence_and_gaps.gaps" in violation
        for violation in violations
    )


@pytest.mark.parametrize(
    ("input_anchor", "output_anchor", "expected_violation"),
    [
        (
            {"source_text": " "},
            {"reconstructed_objects": {"WorkSpec": {}}},
            "input_anchor.source_text must be a non-empty string",
        ),
        (
            {"review_target_ref": 1},
            {"state_ref": "ns_001"},
            "input_anchor.review_target_ref must be a non-empty string",
        ),
        (
            {"review_target_ref": "review_result.json"},
            {"state_ref": " "},
            "output_anchor.state_ref must be a non-empty string",
        ),
        (
            {"source_text": "input.txt"},
            {"reconstructed_objects": []},
            "output_anchor.reconstructed_objects must be a non-empty object",
        ),
        (
            {"source_text": "input.txt"},
            {"reconstructed_objects": {}},
            "output_anchor.reconstructed_objects must be a non-empty object",
        ),
    ],
)
def test_handoff_verify_rejects_invalid_standard_anchor_fields(
    input_anchor,
    output_anchor,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor=input_anchor,
        output_anchor=output_anchor,
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("input_anchor", "must_read_first", "expected_violation"),
    [
        (
            {"source_text": "input.txt"},
            [],
            "next_route.must_read_first must include input_anchor.source_text",
        ),
        (
            {"review_target_ref": "review_result.json"},
            ["other_result.json"],
            "next_route.must_read_first must include input_anchor.review_target_ref",
        ),
    ],
)
def test_handoff_verify_requires_must_read_first_to_include_input_anchors(
    input_anchor,
    must_read_first,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor=input_anchor,
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=must_read_first,
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("header", "next_route", "expected_violation"),
    [
        (
            {"source": "RebuildUnit", "target": "ReviewUnit"},
            NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
                must_read_first=["input.txt"],
            ),
            "RebuildUnit handoff must include next_route.do_not_skip",
        ),
        (
            {"source": "ReviewUnit", "target": "ContinueUnit"},
            NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="review complete",
                review_route="pass",
                must_read_first=["review_result.json"],
            ),
            "ReviewUnit handoff must include next_route.do_not_skip",
        ),
    ],
)
def test_handoff_verify_requires_standard_route_do_not_skip(
    header,
    next_route,
    expected_violation,
):
    input_anchor = (
        {"source_text": "input.txt"}
        if header["source"] == "RebuildUnit"
        else {"review_target_ref": "review_result.json"}
    )
    output_anchor = (
        {"reconstructed_objects": {"WorkSpec": {}}}
        if header["source"] == "RebuildUnit"
        else {"state_ref": "ns_001"}
    )
    packet = HandoffPacket(
        handoff_header=header,
        input_anchor=input_anchor,
        output_anchor=output_anchor,
        change_set=[
            {"action": "create", "objects": ["WorkSpec"]}
            if header["source"] == "RebuildUnit"
            else {
                "action": "review",
                "route": "pass",
                "issue_count": 0,
                "reminder_count": 0,
            }
        ],
        next_route=next_route,
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("header", "next_route", "expected_violation"),
    [
        (
            {"source": "RebuildUnit", "target": "ReviewUnit"},
            NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
                must_read_first=["input.txt"],
                do_not_skip=["generic review"],
            ),
            "RebuildUnit handoff do_not_skip must include review reconstructed object layers",
        ),
        (
            {"source": "ReviewUnit", "target": "ContinueUnit"},
            NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="review complete",
                review_route="pass",
                must_read_first=["review_result.json"],
                do_not_skip=["generic continuation"],
            ),
            "ReviewUnit handoff do_not_skip must include ReviewIssue and ReviewReminder state",
        ),
    ],
)
def test_handoff_verify_requires_standard_route_do_not_skip_guard_content(
    header,
    next_route,
    expected_violation,
):
    input_anchor = (
        {"source_text": "input.txt"}
        if header["source"] == "RebuildUnit"
        else {"review_target_ref": "review_result.json"}
    )
    output_anchor = (
        {"reconstructed_objects": {"WorkSpec": {}}}
        if header["source"] == "RebuildUnit"
        else {"state_ref": "ns_001"}
    )
    packet = HandoffPacket(
        handoff_header=header,
        input_anchor=input_anchor,
        output_anchor=output_anchor,
        change_set=[
            {"action": "create", "objects": ["WorkSpec"]}
            if header["source"] == "RebuildUnit"
            else {
                "action": "review",
                "route": "pass",
                "issue_count": 0,
                "reminder_count": 0,
            }
        ],
        next_route=next_route,
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("header", "input_anchor", "output_anchor", "expected_violation"),
    [
        (
            {"source": "RebuildUnit", "target": "ReviewUnit"},
            {},
            {"reconstructed_objects": {"WorkSpec": {}}},
            "RebuildUnit handoff must include input_anchor.source_text",
        ),
        (
            {"source": "RebuildUnit", "target": "ReviewUnit"},
            {"source_text": "input.txt"},
            {"state_ref": "ns_001"},
            "RebuildUnit handoff must include output_anchor.reconstructed_objects",
        ),
        (
            {"source": "ReviewUnit", "target": "ContinueUnit"},
            {},
            {"state_ref": "ns_001"},
            "ReviewUnit handoff must include input_anchor.review_target_ref",
        ),
        (
            {"source": "ReviewUnit", "target": "ContinueUnit"},
            {"review_target_ref": "review_result.json"},
            {},
            "ReviewUnit handoff must include output_anchor.state_ref",
        ),
    ],
)
def test_handoff_verify_requires_workflow_standard_anchors(
    header,
    input_anchor,
    output_anchor,
    expected_violation,
):
    must_read_first = []
    if "source_text" in input_anchor:
        must_read_first.append(input_anchor["source_text"])
    if "review_target_ref" in input_anchor:
        must_read_first.append(input_anchor["review_target_ref"])
    review_route = "pass" if header["source"] == "ReviewUnit" else None
    packet = HandoffPacket(
        handoff_header=header,
        input_anchor=input_anchor,
        output_anchor=output_anchor,
        next_route=NextRoute(
            recommended_workflow=header["target"],
            route_reason="standard anchor regression",
            review_route=review_route,
            must_read_first=must_read_first,
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("change_set", "open_items", "expected_violation"),
    [
        (
            [],
            [],
            "ReviewUnit handoff must include review change_set entry",
        ),
        (
            [
                {
                    "action": "review",
                    "route": "pass",
                    "issue_count": 0,
                    "reminder_count": 0,
                },
                {
                    "action": "review",
                    "route": "pass",
                    "issue_count": 0,
                    "reminder_count": 0,
                },
            ],
            [],
            "ReviewUnit handoff must include exactly one review change_set entry",
        ),
        (
            [
                {
                    "action": "review",
                    "route": "rewrite",
                    "issue_count": 0,
                    "reminder_count": 0,
                }
            ],
            [],
            "review change_set route must match next_route.review_route",
        ),
        (
            [
                {
                    "action": "review",
                    "route": "pass",
                    "issue_count": 0,
                    "reminder_count": 0,
                }
            ],
            [_handoff_review_issue(severity="warning")],
            "review change_set issue_count must match open_items",
        ),
        (
            [
                {
                    "action": "review",
                    "route": "pass",
                    "issue_count": 0,
                    "reminder_count": 0,
                }
            ],
            [_handoff_review_reminder()],
            "review change_set reminder_count must match open_items",
        ),
        (
            [
                {
                    "action": "review",
                    "route": "pass",
                    "issue_count": "0",
                    "reminder_count": 0,
                }
            ],
            [],
            "review change_set issue_count must be a non-negative integer",
        ),
    ],
)
def test_handoff_verify_requires_review_change_set_to_match_route_and_items(
    change_set,
    open_items,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header={"source": "ReviewUnit", "target": "ContinueUnit"},
        input_anchor={"review_target_ref": "review_result.json"},
        output_anchor={"state_ref": "ns_001"},
        change_set=change_set,
        open_items=open_items,
        next_route=NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review complete",
            review_route="pass",
            must_read_first=["review_result.json"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("change_set", "expected_violation"),
    [
        (
            [],
            "RebuildUnit handoff must include create change_set entry",
        ),
        (
            [
                {"action": "create", "objects": ["WorkSpec"]},
                {"action": "create", "objects": ["WorkSpec"]},
            ],
            "RebuildUnit handoff must include exactly one create change_set entry",
        ),
        (
            [{"action": "create"}],
            "rebuild change_set objects must be a list",
        ),
        (
            [{"action": "create", "objects": [" "]}],
            "rebuild change_set objects entries must be non-empty strings",
        ),
        (
            [{"action": "create", "objects": ["WorkSpec", "WorkSpec"]}],
            "rebuild change_set objects entries must be unique",
        ),
        (
            [{"action": "create", "objects": ["FactLedger"]}],
            "rebuild change_set objects must match output_anchor.reconstructed_objects",
        ),
    ],
)
def test_handoff_verify_requires_rebuild_change_set_to_match_reconstructed_objects(
    change_set,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=change_set,
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("header_update", "expected_violation"),
    [
        (
            {"source": "TypoUnit", "target": "ReviewUnit"},
            "handoff_header.source must be a supported workflow",
        ),
        (
            {"source": "RebuildUnit", "target": "TypoUnit"},
            "handoff_header.target must be a supported workflow",
        ),
        (
            {"source": ["RebuildUnit"], "target": "ReviewUnit"},
            "handoff_header.source must be a supported workflow",
        ),
        (
            {"source": "RebuildUnit", "target": {"workflow": "ReviewUnit"}},
            "handoff_header.target must be a supported workflow",
        ),
    ],
)
def test_handoff_verify_rejects_unsupported_header_workflows(
    header_update,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header=header_update,
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


def test_handoff_verify_rejects_same_source_and_target_workflow():
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "RebuildUnit",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=[{"action": "create", "objects": ["WorkSpec"]}],
        next_route=NextRoute(
            recommended_workflow="RebuildUnit",
            route_reason="self route should not advance",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(
        "handoff source and target must be different workflows" in violation
        for violation in violations
    )


def test_handoff_verify_rejects_unsupported_workflow_transition():
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ContinueUnit",
            "reason": "unsupported transition",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"state_ref": "ns_001"},
        change_set=[{"action": "create", "objects": ["WorkSpec"]}],
        next_route=NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="unsupported transition",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any("handoff transition must be supported" in violation for violation in violations)


@pytest.mark.parametrize(
    ("reason", "expected_violation"),
    [
        (" ", "handoff_header.reason must be a non-empty string"),
        (
            {"reason": "reconstruction complete"},
            "handoff_header.reason must be a non-empty string",
        ),
        ("different reason", "handoff reason must match next_route.route_reason"),
    ],
)
def test_handoff_verify_rejects_invalid_header_reason(reason, expected_violation):
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ReviewUnit",
            "reason": reason,
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("header", "next_route", "expected_violation"),
    [
        (
            {"source": "RebuildUnit", "target": "ReviewUnit"},
            NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
                must_read_first=["input.txt"],
                do_not_skip=["review reconstructed object layers"],
            ),
            "standard handoff must include handoff_header.reason",
        ),
        (
            {"source": "ReviewUnit", "target": "ContinueUnit"},
            NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="review complete",
                review_route="pass",
                must_read_first=["review_result.json"],
                do_not_skip=["honor ReviewIssue and ReviewReminder state"],
            ),
            "standard handoff must include handoff_header.reason",
        ),
    ],
)
def test_handoff_verify_requires_standard_header_reason(
    header,
    next_route,
    expected_violation,
):
    input_anchor = (
        {"source_text": "input.txt"}
        if header["source"] == "RebuildUnit"
        else {"review_target_ref": "review_result.json"}
    )
    output_anchor = (
        {"reconstructed_objects": {"WorkSpec": {}}}
        if header["source"] == "RebuildUnit"
        else {"state_ref": "ns_001"}
    )
    packet = HandoffPacket(
        handoff_header=header,
        input_anchor=input_anchor,
        output_anchor=output_anchor,
        change_set=[
            {"action": "create", "objects": ["WorkSpec"]}
            if header["source"] == "RebuildUnit"
            else {
                "action": "review",
                "route": "pass",
                "issue_count": 0,
                "reminder_count": 0,
            }
        ],
        next_route=next_route,
    )

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


def test_next_route_rejects_invalid_assignment_shapes():
    cases = [
        ("recommended_workflow", "BogusUnit"),
        ("route_reason", " "),
        ("review_route", "skip"),
        ("must_read_first", {"not": "a list"}),
        ("must_read_first", [1]),
        ("must_read_first", ["input.txt", "input.txt"]),
        ("do_not_skip", {"not": "a list"}),
        ("do_not_skip", [""]),
        ("do_not_skip", ["review", "review"]),
    ]

    for field_name, value in cases:
        route = NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        )

        with pytest.raises(ValidationError):
            setattr(route, field_name, value)

        with pytest.raises(ValidationError):
            route.model_copy(update={field_name: value})

    route = NextRoute(
        recommended_workflow="ReviewUnit",
        route_reason="reconstruction complete",
        must_read_first=["input.txt"],
        do_not_skip=["review reconstructed object layers"],
    )

    assert route.must_read_first == ("input.txt",)
    assert route.do_not_skip == ("review reconstructed object layers",)
    assert route.model_dump()["must_read_first"] == ["input.txt"]
    assert route.model_dump()["do_not_skip"] == ["review reconstructed object layers"]
    with pytest.raises(AttributeError):
        route.must_read_first.append("late mutation")
    copied = route.model_copy(update={"must_read_first": ["new-input.txt"]})
    assert copied.must_read_first == ("new-input.txt",)
    assert copied.model_dump()["must_read_first"] == ["new-input.txt"]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("must_read_first", ["input.txt", "input.txt"]),
        ("do_not_skip", ["review", "review"]),
    ],
)
def test_next_route_rejects_duplicate_route_reference_entries(field_name, value):
    route = NextRoute(
        recommended_workflow="ReviewUnit",
        route_reason="reconstruction complete",
    )

    with pytest.raises(ValidationError):
        setattr(route, field_name, value)

    with pytest.raises(ValidationError):
        route.model_copy(update={field_name: value})


def test_handoff_verify_reports_mutated_next_route_field_shapes():
    cases = [
        (
            "recommended_workflow",
            "BogusUnit",
            "next_route.recommended_workflow must be a supported workflow",
        ),
        (
            "route_reason",
            " ",
            "next_route.route_reason must be a non-empty string",
        ),
        (
            "review_route",
            "skip",
            "next_route.review_route must be pass, rewrite, block, or null",
        ),
        (
            "must_read_first",
            {"not": "a list"},
            "next_route.must_read_first must be a list",
        ),
        (
            "must_read_first",
            [1],
            "next_route.must_read_first entries must be non-empty strings",
        ),
        (
            "must_read_first",
            ["input.txt", "input.txt"],
            "next_route.must_read_first entries must be unique",
        ),
        (
            "do_not_skip",
            {"not": "a list"},
            "next_route.do_not_skip must be a list",
        ),
        (
            "do_not_skip",
            [""],
            "next_route.do_not_skip entries must be non-empty strings",
        ),
        (
            "do_not_skip",
            ["review", "review"],
            "next_route.do_not_skip entries must be unique",
        ),
    ]

    for field_name, value, expected_violation in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )
        object.__setattr__(packet.next_route, field_name, value)

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


@pytest.mark.parametrize(
    ("field_name", "value", "expected_violation"),
    [
        (
            "must_read_first",
            ["input.txt", "input.txt"],
            "next_route.must_read_first entries must be unique",
        ),
        (
            "do_not_skip",
            [
                "review reconstructed object layers",
                "review reconstructed object layers",
            ],
            "next_route.do_not_skip entries must be unique",
        ),
    ],
)
def test_handoff_verify_rejects_mutated_duplicate_route_reference_entries(
    field_name,
    value,
    expected_violation,
):
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        change_set=[{"action": "create", "objects": ["WorkSpec"]}],
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )
    object.__setattr__(packet.next_route, field_name, value)

    ok, violations = HandoffBoundaryUnit().verify(packet)

    assert not ok
    assert any(expected_violation in violation for violation in violations)


def test_gate_reports_malformed_handoff_outer_fields_as_violations():
    gate = OrchestrationGateUnit()
    cases = [
        ("handoff_header", ["not", "an", "object"], "handoff_header must be an object"),
        ("output_anchor", ["not", "an", "object"], "output_anchor must be an object"),
        ("open_items", {"not": "a list"}, "open_items must be a list"),
        ("next_route", "ReviewUnit", "next_route must be a structured NextRoute"),
    ]

    for field_name, value, expected_violation in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )
        object.__setattr__(packet, field_name, value)

        ok, violations = gate.verify_entry(packet)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


def test_gate_reports_non_string_handoff_outer_object_keys():
    gate = OrchestrationGateUnit()
    cases = [
        ("handoff_header", {1: "bad"}, "handoff_header keys must be strings"),
        ("change_set", [{1: "bad"}], "change_set entries keys must be strings"),
        ("open_items", [{1: "bad"}], "open_items entries keys must be strings"),
    ]

    for field_name, value, expected_violation in cases:
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "input.txt"},
            output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )
        object.__setattr__(packet, field_name, value)

        ok, violations = gate.verify_entry(packet)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


def test_gate_reports_malformed_package_outer_fields_as_violations():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )
    cases = [
        ("stable_memory", ["not", "an", "object"], "stable_memory must be an object"),
        ("working_set", ["not", "an", "object"], "working_set must be an object"),
        (
            "repair_control",
            ["not", "an", "object"],
            "repair_control must be an object",
        ),
        ("confidence", ["not", "an", "object"], "confidence must be an object"),
        ("metadata", ["not", "an", "object"], "metadata must be an object"),
    ]

    for field_name, value, expected_violation in cases:
        package = _base_package()
        object.__setattr__(package, field_name, value)

        ok, violations = gate.verify_entry(packet, package)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


def test_gate_reports_non_string_package_metadata_keys():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )
    cases = [
        ("confidence", {1: "bad"}, "confidence keys must be strings"),
        ("metadata", {1: "bad"}, "metadata keys must be strings"),
    ]

    for field_name, value, expected_violation in cases:
        package = _base_package()
        object.__setattr__(package, field_name, value)

        ok, violations = gate.verify_entry(packet, package)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


def test_continue_entry_reports_malformed_package_working_set_before_route_scan():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    object.__setattr__(package, "working_set", ["not", "an", "object"])

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("working_set must be an object" in violation for violation in violations)


def test_gate_reports_malformed_package_bucket_shapes_as_violations():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )
    cases = [
        ("stable_memory", {1: []}, "stable_memory type keys must be strings"),
        (
            "working_set",
            {"NarrativeState": {"not": "a list"}},
            "working_set.NarrativeState must be a list",
        ),
        (
            "repair_control",
            {"ReviewIssue": ["not an object"]},
            "repair_control.ReviewIssue entries must be objects",
        ),
    ]

    for field_name, value, expected_violation in cases:
        package = _base_package()
        object.__setattr__(package, field_name, value)

        ok, violations = gate.verify_entry(packet, package)

        assert not ok
        assert any(expected_violation in violation for violation in violations)


def test_continue_entry_rejects_non_object_narrative_state_bucket_entry():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _corrupt_package_layer(
        package,
        "working_set",
        "NarrativeState",
        ["not an object"],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any(
        "working_set.NarrativeState entries must be objects" in violation
        for violation in violations
    )


def test_gate_rejects_unknown_package_type_before_route_entry():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"WorkSpec": {}}},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(package, "stable_memory", "MysteryObject", [])

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any(
        "stable_memory contains unknown type MysteryObject" in violation
        for violation in violations
    )


def test_gate_rejects_package_type_in_wrong_layer_before_route_entry():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(package, "working_set", "ReviewIssue", [])

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("working_set contains ReviewIssue" in violation for violation in violations)


def test_gate_rejects_incomplete_serialized_working_set_object_before_route_entry():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(
        package,
        "working_set",
        "NarrativeState",
        [
            {
                "state_id": "ns_incomplete",
                "current_time": "now",
                "current_location": "room",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any(
        "Serialized NarrativeState missing serialized field(s)" in violation
        for violation in violations
    )


def test_gate_rejects_invalid_serialized_stable_memory_object_before_route_entry():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
        input_anchor={"source_text": "input.txt"},
        output_anchor={},
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(
        package,
        "stable_memory",
        "WorkSpec",
        [
            {
                "genre": "test",
                "subgenre": None,
                "audience": "test",
                "theme": "test",
                "tone": "test",
                "pacing": "test",
                "structure_template": None,
                "platform": None,
                "length_target": "long",
                "constraints": [],
                "romance_weight": None,
                "mystery_weight": None,
                "action_weight": None,
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("Failed to deserialize WorkSpec" in violation for violation in violations)


def test_continue_entry_requires_runnable_state():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = SerializationBoundaryUnit().build_package(
        WorkSpec(
            genre="test",
            audience="test",
            theme="test",
            tone="test",
            pacing="test",
        )
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("NarrativeState" in violation for violation in violations)


def test_continue_entry_blocks_unresolved_blocking_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(
        package,
        "repair_control",
        "ReviewIssue",
        [
            ReviewIssue(
                issue_id="iss_block",
                issue_type="fact_conflict",
                severity="blocking",
                location="FactLedger",
                scope_of_impact="current packet",
                violated_rule="continue gate",
                description="cannot continue with blocking issue",
            ).model_dump(mode="json")
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("unresolved ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_unresolved_blocking_handoff_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_handoff_block",
            severity="critical",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("unresolved ReviewIssue" in violation for violation in violations)


def test_continue_entry_allows_resolved_blocking_handoff_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_handoff_resolved",
            severity="blocking",
            status="resolved",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert ok
    assert violations == []


def test_continue_entry_treats_missing_handoff_issue_status_as_open():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_missing_status",
            severity="blocking",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("unresolved ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_invalid_handoff_issue_status():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_invalid_status",
            severity="warning",
            status="closed",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_conflicting_handoff_issue_status_fields():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_conflicting_status",
            severity="warning",
            status="resolved",
            resolution_status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_unknown_handoff_issue_fields():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_unknown_field",
            severity="warning",
            status="open",
            adapter_hint="ui should not extend review issues",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_missing_handoff_issue_severity():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_missing_severity",
            severity=None,
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_missing_handoff_issue_location():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_missing_location",
            location=None,
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_blank_handoff_issue_location():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_blank_location",
            location="   ",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_missing_handoff_issue_id():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id=None,
            severity="warning",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_requires_blocking_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_accepts_blocking_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_layer_item(
        package,
        "repair_control",
        "ReviewIssue",
        [
            ReviewIssue(
                issue_id="iss_rewrite",
                issue_type="weak_progression",
                severity="critical",
                location="PlotUnit",
                scope_of_impact="candidate progression",
                violated_rule="rewrite gate",
                description="blocking issue requires rewrite",
            ).model_dump(mode="json")
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert ok
    assert violations == []


def test_rewrite_entry_rejects_missing_handoff_issue_id_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id=None,
            severity="critical",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_blank_handoff_issue_id_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="   ",
            severity="critical",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_invalid_handoff_issue_type_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_invalid_type",
            issue_type="plot_problem",
            severity="critical",
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_conflicting_handoff_issue_status_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_rewrite_conflicting_status",
            severity="critical",
            status="open",
            resolution_status="resolved",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_missing_handoff_issue_location_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_rewrite_missing_location",
            severity="critical",
            location=None,
            status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_accepts_handoff_issue_resolution_status_open():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    _append_open_item(packet,
        _handoff_review_issue(
            issue_id="iss_rewrite_handoff",
            severity="critical",
            resolution_status="open",
        )
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert ok
    assert violations == []


def test_continue_entry_treats_missing_package_issue_resolution_status_as_open():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_missing_resolution_status",
                "issue_type": "fact_conflict",
                "severity": "blocking",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "missing status should stay unresolved",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("unresolved ReviewIssue" in violation for violation in violations)


def test_continue_entry_allows_resolved_blocking_package_issue():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_resolved",
                "issue_type": "fact_conflict",
                "severity": "blocking",
                "resolution_status": "resolved",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "resolved blocking issue should not block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert ok
    assert violations == []


def test_continue_entry_blocks_missing_package_issue_severity():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_missing_severity",
                "issue_type": "fact_conflict",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "missing severity should block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_invalid_package_issue_severity():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_invalid_severity",
                "issue_type": "fact_conflict",
                "severity": "urgent",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "invalid severity should block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_conflicting_package_issue_status_fields():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_conflicting_status",
                "issue_type": "fact_conflict",
                "severity": "warning",
                "status": "resolved",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "conflicting status fields should block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_unknown_package_issue_fields():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_unknown_field",
                "issue_type": "fact_conflict",
                "severity": "warning",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "unknown issue fields should block continue",
                "adapter_hint": "ui should not extend review issues",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_missing_package_issue_location():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_missing_location",
                "issue_type": "fact_conflict",
                "severity": "warning",
                "resolution_status": "open",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "missing location should block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_blank_package_issue_description():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_blank_description",
                "issue_type": "fact_conflict",
                "severity": "warning",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "   ",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_continue_entry_blocks_missing_package_issue_id():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_type": "fact_conflict",
                "severity": "warning",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "continue gate",
                "description": "missing issue id should block continue",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_missing_package_issue_id_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_type": "fact_conflict",
                "severity": "critical",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "rewrite gate",
                "description": "missing issue id should not drive rewrite",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_blank_package_issue_violated_rule_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_blank_violated_rule",
                "issue_type": "fact_conflict",
                "severity": "critical",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "   ",
                "description": "blank rule should not drive rewrite",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_invalid_package_issue_status_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_invalid_status",
                "issue_type": "fact_conflict",
                "severity": "critical",
                "resolution_status": "closed",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "rewrite gate",
                "description": "invalid status should not drive rewrite",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_conflicting_package_issue_status_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_rewrite_conflicting_status",
                "issue_type": "fact_conflict",
                "severity": "critical",
                "status": "resolved",
                "resolution_status": "open",
                "location": "FactLedger",
                "scope_of_impact": "current packet",
                "violated_rule": "rewrite gate",
                "description": "conflicting status fields should not drive rewrite",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_rewrite_entry_rejects_missing_package_issue_location_as_blocking_evidence():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "RewriteUnit",
        NextRoute(
            recommended_workflow="RewriteUnit",
            route_reason="rewrite requested",
            review_route="rewrite",
        ),
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_rewrite_missing_location",
                "issue_type": "fact_conflict",
                "severity": "critical",
                "resolution_status": "open",
                "scope_of_impact": "current packet",
                "violated_rule": "rewrite gate",
                "description": "missing location should not drive rewrite",
            }
        ],
    )

    ok, violations = gate.verify_entry(packet, package)

    assert not ok
    assert any("complete blocking ReviewIssue" in violation for violation in violations)


def test_blocking_open_item_blocks_route_movement():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, {"type": "manual_decision", "blocking": True})

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("blocking open item" in violation for violation in violations)


def test_non_object_open_item_becomes_gate_violation():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, ["not", "an", "object"])

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("open item must be an object" in violation for violation in violations)


def test_continue_entry_blocks_missing_handoff_reminder_window():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(window=None))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_invalid_handoff_reminder_family():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(family="unknown_family"))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_invalid_handoff_reminder_status():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(status="pending"))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_invalid_handoff_reminder_priority():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(priority="urgent"))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_accepts_missing_handoff_reminder_status_and_priority_defaults():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(status=None, priority=None))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert ok
    assert violations == []


def test_continue_entry_blocks_blank_handoff_reminder_source_review():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(source_review="   "))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_invalid_handoff_reminder_escalation_target():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_reminder(escalation_issue_type="information_leak")
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_blank_handoff_reminder_closure_condition():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet, _handoff_review_reminder(closure_condition="   "))

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_continue_entry_blocks_unknown_handoff_reminder_fields():
    gate = OrchestrationGateUnit()
    packet = _packet(
        "ContinueUnit",
        NextRoute(
            recommended_workflow="ContinueUnit",
            route_reason="review passed",
            review_route="pass",
        ),
    )
    _append_open_item(packet,
        _handoff_review_reminder(adapter_hint="ui should not extend reminders")
    )

    ok, violations = gate.verify_entry(packet, _base_package())

    assert not ok
    assert any("incomplete ReviewReminder" in violation for violation in violations)


def test_exit_gate_runs_no_regression_validation():
    gate = OrchestrationGateUnit()
    packet = HandoffPacket(
        handoff_header={
            "source": "RebuildUnit",
            "target": "ReviewUnit",
            "reason": "reconstruction complete",
        },
        input_anchor={"source_text": "input.txt"},
        output_anchor={"reconstructed_objects": {"FactLedger": {}}},
        change_set=[{"action": "create", "objects": ["FactLedger"]}],
        next_route=NextRoute(
            recommended_workflow="ReviewUnit",
            route_reason="reconstruction complete",
            must_read_first=["input.txt"],
            do_not_skip=["review reconstructed object layers"],
        ),
    )
    package = SerializationBoundaryUnit().build_package(
        FactLedger(
            entries=[
                FactEntry(
                    fact_id="f_unconfirmed",
                    statement="not confirmed",
                    fact_type="event",
                    confirmed=False,
                )
            ]
        )
    )

    ok, violations = gate.verify_exit(packet, package)

    assert not ok
    assert any("unconfirmed fact" in violation for violation in violations)


def test_review_pass_route_builder_can_enter_continue():
    issue = ReviewIssue(
        issue_id="iss_warning",
        issue_type="weak_progression",
        severity="warning",
        location="PlotUnit",
        scope_of_impact="next unit",
        violated_rule="warning only",
        description="warning does not block continue",
    )
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="pass",
        issues=[issue.model_dump(mode="json")],
        reminders=[],
        output_state_ref="ns_001",
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, _base_package())

    assert ok
    assert violations == []
    assert packet.next_route.recommended_workflow == "ContinueUnit"
    assert packet.next_route.review_route == "pass"
    assert packet.open_items[0]["location"] == "PlotUnit"
    assert packet.open_items[0]["violated_rule"] == "warning only"


def test_review_pass_route_builder_preserves_reminder_escalation_fields():
    reminder = ReviewReminder(
        reminder_id="rem_missing_cost",
        family="missing_cost",
        trigger_condition="next unit still has no cost",
        window="plotunit_count=1_or_2",
        escalation_issue_type="missing_cost",
        early_escalation_condition="continued zero-cost operation",
        closure_condition="cost or accountability becomes explicit",
        priority="high",
        source_review="review_result.json",
    )
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="pass",
        issues=[],
        reminders=[reminder.model_dump(mode="json")],
        output_state_ref="ns_001",
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, _base_package())

    assert ok
    assert violations == []
    item = packet.open_items[0]
    assert item["type"] == "ReviewReminder"
    assert item["window"] == "plotunit_count=1_or_2"
    assert item["escalation_issue_type"] == "missing_cost"
    assert item["early_escalation_condition"] == "continued zero-cost operation"
    assert item["closure_condition"] == "cost or accountability becomes explicit"
    assert item["source_review"] == "review_result.json"


def test_review_route_builder_rejects_incomplete_issue_before_packet_creation():
    with pytest.raises(ValueError, match="location"):
        HandoffBoundaryUnit().build_review_route(
            review_target_ref="review_result.json",
            route="block",
            issues=[
                _handoff_review_issue(
                    issue_id="iss_builder_incomplete",
                    location=None,
                    status="open",
                )
            ],
            reminders=[],
            output_state_ref="ns_001",
        )


def test_review_route_builder_rejects_incomplete_reminder_before_packet_creation():
    with pytest.raises(ValueError, match="window"):
        HandoffBoundaryUnit().build_review_route(
            review_target_ref="review_result.json",
            route="pass",
            issues=[],
            reminders=[_handoff_review_reminder(window=None)],
            output_state_ref="ns_001",
        )


def test_review_rewrite_route_builder_can_enter_rewrite():
    issue = ReviewIssue(
        issue_id="iss_rewrite_route",
        issue_type="fact_conflict",
        severity="blocking",
        location="FactLedger",
        scope_of_impact="current packet",
        violated_rule="rewrite required",
        description="blocking issue must route to rewrite",
    )
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="rewrite",
        issues=[issue.model_dump(mode="json")],
        reminders=[],
        output_state_ref="ns_001",
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [issue.model_dump(mode="json")],
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, package)

    assert ok
    assert violations == []
    assert packet.next_route.recommended_workflow == "RewriteUnit"
    assert packet.open_items[0]["issue_id"] == "iss_rewrite_route"
    assert packet.open_items[0]["location"] == "FactLedger"
    assert packet.open_items[0]["scope_of_impact"] == "current packet"


def test_review_block_route_builder_preserves_escalated_reminder_fields():
    reminder = ReviewReminder(
        reminder_id="rem_knowledge",
        family="knowledge_check_needed",
        trigger_condition="character may act on unknown information",
        window="plotunit_count=1",
        escalation_issue_type="information_leak",
        early_escalation_condition="character acts on illegal knowledge",
        closure_condition="knowledge ownership is explicit",
        status="escalated",
    )
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[reminder.model_dump(mode="json")],
        output_state_ref="ns_001",
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet)

    assert ok
    assert violations == []
    item = packet.open_items[0]
    assert item["type"] == "ReviewReminder"
    assert item["status"] == "escalated"
    assert item["window"] == "plotunit_count=1"
    assert item["escalation_issue_type"] == "information_leak"


def test_review_block_route_builder_defaults_to_stop():
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[],
        output_state_ref="ns_001",
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet)

    assert ok
    assert violations == []
    assert packet.next_route.recommended_workflow == "Stop"
    assert packet.next_route.review_route == "block"


@pytest.mark.parametrize("block_target", ["Stop", "RebuildUnit", "Replan"])
def test_review_block_route_rejects_incomplete_handoff_issue(block_target):
    packet = HandoffPacket(
        handoff_header={
            "source": "ReviewUnit",
            "target": block_target,
            "reason": "review_completed",
        },
        input_anchor={"review_target_ref": "review_result.json"},
        output_anchor={"state_ref": "ns_001"},
        open_items=[
            _handoff_review_issue(
                issue_id="iss_incomplete_block",
                location=None,
                status="open",
            )
        ],
        next_route=NextRoute(
            recommended_workflow=block_target,
            route_reason="review_completed",
            review_route="block",
        ),
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet)

    assert not ok
    assert any("incomplete ReviewIssue" in violation for violation in violations)


@pytest.mark.parametrize("block_target", ["Stop", "RebuildUnit", "Replan"])
def test_review_block_route_rejects_incomplete_package_issue(block_target):
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[],
        output_state_ref="ns_001",
        block_target=block_target,
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewIssue",
        [
            {
                "issue_id": "iss_package_incomplete_block",
                "issue_type": "fact_conflict",
                "severity": "blocking",
                "resolution_status": "open",
                "scope_of_impact": "current packet",
                "violated_rule": "block gate",
                "description": "malformed package issue should block every route",
            }
        ],
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, package)

    assert not ok
    assert any("package gate: incomplete ReviewIssue" in violation for violation in violations)


@pytest.mark.parametrize("block_target", ["Stop", "RebuildUnit", "Replan"])
def test_review_block_route_rejects_incomplete_package_reminder(block_target):
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[],
        output_state_ref="ns_001",
        block_target=block_target,
    )
    package = _base_package()
    package = _package_with_repair_items(
        package,
        "ReviewReminder",
        [
            {
                "reminder_id": "rem_package_incomplete_block",
                "family": "missing_cost",
                "trigger_condition": "next unit still has no cost",
                "escalation_issue_type": "missing_cost",
                "early_escalation_condition": "continued zero-cost operation",
                "closure_condition": "cost or accountability becomes explicit",
            }
        ],
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, package)

    assert not ok
    assert any(
        "package gate: incomplete ReviewReminder" in violation
        for violation in violations
    )


def test_review_block_route_reports_non_object_package_reminder_as_violation():
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[],
        output_state_ref="ns_001",
    )
    package = _base_package()
    package = _corrupt_package_layer(
        package,
        "repair_control",
        "ReviewReminder",
        [["not", "an", "object"]],
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet, package)

    assert not ok
    assert "package gate: repair_control.ReviewReminder entries must be objects" in violations


def test_review_block_route_builder_allows_explicit_replan_target():
    packet = HandoffBoundaryUnit().build_review_route(
        review_target_ref="review_result.json",
        route="block",
        issues=[],
        reminders=[],
        output_state_ref="ns_001",
        block_target="Replan",
    )

    ok, violations = OrchestrationGateUnit().verify_entry(packet)

    assert ok
    assert violations == []
    assert packet.next_route.recommended_workflow == "Replan"



