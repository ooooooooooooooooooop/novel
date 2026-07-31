"""Workflow handoff boundary control."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
)

from src.boundary_control.review_object_contracts import (
    review_issue_from_payload,
    review_issue_open_item,
    review_reminder_from_payload,
    review_reminder_open_item,
)


WorkflowRoute = Literal[
    "ReviewUnit",
    "ContinueUnit",
    "RewriteUnit",
    "RebuildUnit",
    "Replan",
    "Stop",
]
ReviewRoute = Literal["pass", "rewrite", "block"]
VALID_WORKFLOW_ROUTES = set(get_args(WorkflowRoute))
VALID_REVIEW_ROUTES = set(get_args(ReviewRoute))
VALID_HANDOFF_TRANSITIONS = {
    "RebuildUnit": {"ReviewUnit"},
    "ContinueUnit": {"ReviewUnit"},
    "RewriteUnit": {"ReviewUnit"},
    "ReviewUnit": {"ContinueUnit", "RewriteUnit", "Stop", "RebuildUnit", "Replan"},
}


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _object_container(
    value: object,
    field_name: str,
    violations: list[str],
) -> Mapping | None:
    if not isinstance(value, Mapping):
        violations.append(f"{field_name} must be an object")
        return None
    if any(not isinstance(key, str) for key in value):
        violations.append(f"{field_name} keys must be strings")
    return value


def _object_list_entries_have_string_keys(
    values: list[Mapping] | tuple[Mapping, ...],
    field_name: str,
    violations: list[str],
) -> None:
    if any(any(not isinstance(key, str) for key in item) for item in values):
        violations.append(f"{field_name} entries keys must be strings")


def _verify_change_set_action_fields(
    change_set: list[Mapping] | tuple[Mapping, ...],
    violations: list[str],
) -> None:
    for item in change_set:
        action = item.get("action")
        if not isinstance(action, str) or not action.strip():
            violations.append("change_set entries must include non-empty action")
            return


def _require_string_keys(value: Mapping, field_name: str) -> Mapping:
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


def _require_string_keys_in_list_entries(
    values: tuple[Mapping, ...],
    field_name: str,
) -> tuple[Mapping, ...]:
    if any(any(not isinstance(key, str) for key in item) for item in values):
        raise ValueError(f"{field_name} entries keys must be strings")
    return tuple(MappingProxyType(dict(value)) for value in values)


def _string_list_field(
    values: object,
    field_name: str,
    violations: list[str],
) -> None:
    if not isinstance(values, (list, tuple)):
        violations.append(f"{field_name} must be a list")
        return
    if any(not isinstance(value, str) or not value.strip() for value in values):
        violations.append(f"{field_name} entries must be non-empty strings")


def _unique_string_list_field(
    values: object,
    field_name: str,
    violations: list[str],
) -> None:
    if not isinstance(values, (list, tuple)):
        return
    string_values = [value for value in values if isinstance(value, str)]
    if len(string_values) != len(values):
        return
    if len(set(string_values)) != len(string_values):
        violations.append(f"{field_name} entries must be unique")


def _verify_next_route_fields(route: "NextRoute", violations: list[str]) -> None:
    recommended_workflow = getattr(route, "recommended_workflow", None)
    if (
        not isinstance(recommended_workflow, str)
        or recommended_workflow not in VALID_WORKFLOW_ROUTES
    ):
        violations.append(
            "next_route.recommended_workflow must be a supported workflow"
        )
    route_reason = getattr(route, "route_reason", None)
    if not isinstance(route_reason, str) or not route_reason.strip():
        violations.append("next_route.route_reason must be a non-empty string")
    review_route = getattr(route, "review_route", None)
    if review_route is not None and (
        not isinstance(review_route, str) or review_route not in VALID_REVIEW_ROUTES
    ):
        violations.append("next_route.review_route must be pass, rewrite, block, or null")
    _string_list_field(
        getattr(route, "must_read_first", None),
        "next_route.must_read_first",
        violations,
    )
    _unique_string_list_field(
        getattr(route, "must_read_first", None),
        "next_route.must_read_first",
        violations,
    )
    _string_list_field(
        getattr(route, "do_not_skip", None),
        "next_route.do_not_skip",
        violations,
    )
    _unique_string_list_field(
        getattr(route, "do_not_skip", None),
        "next_route.do_not_skip",
        violations,
    )


def _verify_review_open_item_fields(
    open_items: list[Mapping] | tuple[Mapping, ...],
    violations: list[str],
) -> None:
    for item in open_items:
        item_type = item.get("type")
        if item_type == "confidence_gap":
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                violations.append(
                    "open_items confidence_gap content must be a non-empty string"
                )
        if item_type == "ReviewIssue":
            try:
                review_issue_from_payload(item)
            except (ValidationError, ValueError):
                violations.append("open_items ReviewIssue must match runtime model")
        if item_type == "ReviewReminder":
            try:
                review_reminder_from_payload(item)
            except (ValidationError, ValueError):
                violations.append("open_items ReviewReminder must match runtime model")


def _verify_header_workflow(
    value: object,
    field_name: str,
    missing_message: str,
    violations: list[str],
) -> None:
    if not value:
        violations.append(missing_message)
        return
    if not isinstance(value, str) or value not in VALID_WORKFLOW_ROUTES:
        violations.append(f"handoff_header.{field_name} must be a supported workflow")


def _verify_header_transition(
    source: object,
    target: object,
    violations: list[str],
) -> None:
    if (
        isinstance(source, str)
        and isinstance(target, str)
        and source in VALID_WORKFLOW_ROUTES
        and target in VALID_WORKFLOW_ROUTES
    ):
        if source == target:
            violations.append("handoff source and target must be different workflows")
            return
        if target not in VALID_HANDOFF_TRANSITIONS.get(source, set()):
            violations.append("handoff transition must be supported")


def _verify_header_reason(
    value: object,
    route_reason: object,
    violations: list[str],
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        violations.append("handoff_header.reason must be a non-empty string")
        return
    if value != route_reason:
        violations.append("handoff reason must match next_route.route_reason")


def _verify_required_standard_header_reason(
    source: object,
    target: object,
    header_reason: object,
    violations: list[str],
) -> None:
    if source == "RebuildUnit" and target == "ReviewUnit" and header_reason is None:
        violations.append("standard handoff must include handoff_header.reason")
    if source == "ReviewUnit" and header_reason is None:
        violations.append("standard handoff must include handoff_header.reason")


def _verify_confidence_gaps_fields(
    confidence_and_gaps: Mapping | None,
    violations: list[str],
) -> None:
    if confidence_and_gaps is None or "gaps" not in confidence_and_gaps:
        return
    _string_list_field(
        confidence_and_gaps["gaps"],
        "confidence_and_gaps.gaps",
        violations,
    )


def _confidence_gap_open_item_contents(open_items: object) -> list[str] | None:
    if not isinstance(open_items, (list, tuple)):
        return None
    contents = []
    for item in open_items:
        if not isinstance(item, Mapping) or item.get("type") != "confidence_gap":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            contents.append(content)
    return contents


def _verify_confidence_gap_open_items_match_gaps(
    confidence_and_gaps: Mapping | None,
    open_items: object,
    violations: list[str],
) -> None:
    open_item_contents = _confidence_gap_open_item_contents(open_items)
    if open_item_contents is None:
        return
    gaps = None
    if confidence_and_gaps is not None and "gaps" in confidence_and_gaps:
        gaps = confidence_and_gaps["gaps"]
    if gaps is None:
        if open_item_contents:
            violations.append(
                "confidence_gap open items must match confidence_and_gaps.gaps"
            )
        return
    if not isinstance(gaps, (list, tuple)):
        return
    valid_gaps = [
        gap for gap in gaps if isinstance(gap, str) and gap.strip()
    ]
    if open_item_contents != valid_gaps:
        violations.append(
            "confidence_gap open items must match confidence_and_gaps.gaps"
        )


def _verify_optional_anchor_string(
    anchor: Mapping | None,
    anchor_name: str,
    field_name: str,
    violations: list[str],
) -> None:
    if anchor is None or field_name not in anchor:
        return
    value = anchor[field_name]
    if not isinstance(value, str) or not value.strip():
        violations.append(f"{anchor_name}.{field_name} must be a non-empty string")


def _anchor_has_non_blank_string(
    anchor: Mapping | None,
    field_name: str,
) -> bool:
    if anchor is None:
        return False
    value = anchor.get(field_name)
    return isinstance(value, str) and bool(value.strip())


def _anchor_has_non_empty_object(
    anchor: Mapping | None,
    field_name: str,
) -> bool:
    if anchor is None:
        return False
    value = anchor.get(field_name)
    return isinstance(value, Mapping) and bool(value)


def _verify_anchor_fields(
    input_anchor: Mapping | None,
    output_anchor: Mapping | None,
    violations: list[str],
) -> None:
    _verify_optional_anchor_string(
        input_anchor,
        "input_anchor",
        "source_text",
        violations,
    )
    _verify_optional_anchor_string(
        input_anchor,
        "input_anchor",
        "review_target_ref",
        violations,
    )
    _verify_optional_anchor_string(
        output_anchor,
        "output_anchor",
        "state_ref",
        violations,
    )
    if output_anchor is None or "reconstructed_objects" not in output_anchor:
        return
    reconstructed_objects = output_anchor["reconstructed_objects"]
    if not isinstance(reconstructed_objects, Mapping) or not reconstructed_objects:
        violations.append("output_anchor.reconstructed_objects must be a non-empty object")


def _verify_required_standard_anchors(
    source: object,
    target: object,
    input_anchor: Mapping | None,
    output_anchor: Mapping | None,
    violations: list[str],
) -> None:
    if source == "RebuildUnit" and target == "ReviewUnit":
        if not _anchor_has_non_blank_string(input_anchor, "source_text"):
            violations.append(
                "RebuildUnit handoff must include input_anchor.source_text"
            )
        if not _anchor_has_non_empty_object(output_anchor, "reconstructed_objects"):
            violations.append(
                "RebuildUnit handoff must include output_anchor.reconstructed_objects"
            )
    if source == "ReviewUnit":
        if not _anchor_has_non_blank_string(input_anchor, "review_target_ref"):
            violations.append(
                "ReviewUnit handoff must include input_anchor.review_target_ref"
            )
        if not _anchor_has_non_blank_string(output_anchor, "state_ref"):
            violations.append("ReviewUnit handoff must include output_anchor.state_ref")


def _review_open_item_counts(
    open_items: object,
) -> tuple[int, int]:
    if not isinstance(open_items, (list, tuple)):
        return 0, 0
    issue_count = 0
    reminder_count = 0
    for item in open_items:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "ReviewIssue":
            issue_count += 1
        if item.get("type") == "ReviewReminder":
            reminder_count += 1
    return issue_count, reminder_count


def _verify_review_change_set(
    source: object,
    change_set: object,
    open_items: object,
    review_route: object,
    violations: list[str],
) -> None:
    if source != "ReviewUnit":
        return
    if not isinstance(change_set, (list, tuple)):
        return
    review_entries = [
        item
        for item in change_set
        if isinstance(item, Mapping) and item.get("action") == "review"
    ]
    if not review_entries:
        violations.append("ReviewUnit handoff must include review change_set entry")
        return
    if len(review_entries) > 1:
        violations.append(
            "ReviewUnit handoff must include exactly one review change_set entry"
        )
        return
    review_entry = review_entries[0]
    if review_entry.get("route") != review_route:
        violations.append("review change_set route must match next_route.review_route")
    issue_count, reminder_count = _review_open_item_counts(open_items)
    for field_name, expected_count in (
        ("issue_count", issue_count),
        ("reminder_count", reminder_count),
    ):
        value = review_entry.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            violations.append(f"review change_set {field_name} must be a non-negative integer")
            continue
        if value != expected_count:
            violations.append(
                f"review change_set {field_name} must match open_items"
            )


def _verify_rebuild_change_set(
    source: object,
    target: object,
    change_set: object,
    output_anchor: Mapping | None,
    violations: list[str],
) -> None:
    if source != "RebuildUnit" or target != "ReviewUnit":
        return
    if not isinstance(change_set, (list, tuple)):
        return
    create_entries = [
        item
        for item in change_set
        if isinstance(item, Mapping) and item.get("action") == "create"
    ]
    if not create_entries:
        violations.append("RebuildUnit handoff must include create change_set entry")
        return
    if len(create_entries) > 1:
        violations.append(
            "RebuildUnit handoff must include exactly one create change_set entry"
        )
        return
    create_entry = create_entries[0]
    objects = create_entry.get("objects")
    if not isinstance(objects, (list, tuple)):
        violations.append("rebuild change_set objects must be a list")
        return
    if any(not isinstance(item, str) or not item.strip() for item in objects):
        violations.append("rebuild change_set objects entries must be non-empty strings")
        return
    if len(set(objects)) != len(objects):
        violations.append("rebuild change_set objects entries must be unique")
        return
    reconstructed_objects = (
        output_anchor.get("reconstructed_objects")
        if isinstance(output_anchor, Mapping)
        else None
    )
    if not isinstance(reconstructed_objects, Mapping):
        return
    if set(objects) != set(reconstructed_objects):
        violations.append(
            "rebuild change_set objects must match output_anchor.reconstructed_objects"
        )


def _verify_must_read_first_includes_input_anchors(
    input_anchor: Mapping | None,
    route: "NextRoute",
    violations: list[str],
) -> None:
    if input_anchor is None:
        return
    must_read_first = getattr(route, "must_read_first", None)
    if not isinstance(must_read_first, (list, tuple)):
        return
    for field_name in ("source_text", "review_target_ref"):
        anchor_ref = input_anchor.get(field_name)
        if not isinstance(anchor_ref, str) or not anchor_ref.strip():
            continue
        if anchor_ref not in must_read_first:
            violations.append(
                f"next_route.must_read_first must include input_anchor.{field_name}"
            )


def _verify_required_standard_route_guards(
    source: object,
    target: object,
    route: "NextRoute",
    violations: list[str],
) -> None:
    do_not_skip = getattr(route, "do_not_skip", None)
    has_guard = isinstance(do_not_skip, (list, tuple)) and bool(do_not_skip)
    if source == "RebuildUnit" and target == "ReviewUnit":
        if not has_guard:
            violations.append("RebuildUnit handoff must include next_route.do_not_skip")
            return
        if "review reconstructed object layers" not in do_not_skip:
            violations.append(
                "RebuildUnit handoff do_not_skip must include review reconstructed object layers"
            )
    if source == "ReviewUnit":
        if not has_guard:
            violations.append("ReviewUnit handoff must include next_route.do_not_skip")
            return
        if "honor ReviewIssue and ReviewReminder state" not in do_not_skip:
            violations.append(
                "ReviewUnit handoff do_not_skip must include ReviewIssue and ReviewReminder state"
            )


class NextRoute(BaseModel):
    """Structured route proposal consumed by orchestration gates."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    recommended_workflow: WorkflowRoute = Field(description="Recommended next workflow")
    route_reason: str = Field(description="Why this route is recommended")
    review_route: ReviewRoute | None = Field(
        default=None,
        description="Review route when this handoff is derived from ReviewUnit",
    )
    must_read_first: tuple[str, ...] = Field(default_factory=tuple)
    do_not_skip: tuple[str, ...] = Field(default_factory=tuple)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> "NextRoute":
        if update is None:
            return super().model_copy(deep=deep)
        payload = self.model_dump()
        payload.update(update)
        copied = type(self).model_validate(payload)
        if deep:
            return copied.model_copy(deep=True)
        return copied

    @field_validator("route_reason")
    @classmethod
    def _route_reason_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("must_read_first", "do_not_skip")
    @classmethod
    def _route_reference_items_must_be_non_blank(
        cls, values: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        if len(set(values)) != len(values):
            raise ValueError(f"{info.field_name} entries must be unique")
        return values

    @field_serializer("must_read_first", "do_not_skip")
    def _route_reference_items_dump_as_lists(
        self, values: tuple[str, ...]
    ) -> list[str]:
        return list(values)


class HandoffPacket(BaseModel):
    """Seven-part workflow handoff packet."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    handoff_header: Mapping[str, object] = Field(default_factory=dict)
    input_anchor: Mapping[str, object] = Field(default_factory=dict)
    output_anchor: Mapping[str, object] = Field(default_factory=dict)
    change_set: tuple[Mapping[str, object], ...] = Field(default_factory=tuple)
    open_items: tuple[Mapping[str, object], ...] = Field(default_factory=tuple)
    confidence_and_gaps: Mapping[str, object] = Field(default_factory=dict)
    next_route: NextRoute = Field(description="Structured next route")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> "HandoffPacket":
        if update is None:
            if deep:
                return type(self).model_validate(self.model_dump())
            return super().model_copy(deep=deep)
        payload = self.model_dump()
        payload.update(update)
        copied = type(self).model_validate(payload)
        if deep:
            return type(self).model_validate(copied.model_dump())
        return copied

    @field_validator(
        "handoff_header",
        "input_anchor",
        "output_anchor",
        "confidence_and_gaps",
    )
    @classmethod
    def _object_keys_must_be_strings(
        cls, value: Mapping, info: ValidationInfo
    ) -> Mapping:
        return _require_string_keys(value, info.field_name)

    @field_validator("change_set", "open_items")
    @classmethod
    def _entry_keys_must_be_strings(
        cls, values: tuple[Mapping, ...], info: ValidationInfo
    ) -> tuple[Mapping, ...]:
        return _require_string_keys_in_list_entries(values, info.field_name)

    @field_serializer(
        "handoff_header",
        "input_anchor",
        "output_anchor",
        "confidence_and_gaps",
    )
    def _objects_dump_as_dicts(self, value: Mapping) -> dict:
        return dict(value)

    @field_serializer("change_set", "open_items")
    def _object_entries_dump_as_lists(
        self, values: tuple[Mapping, ...]
    ) -> list[dict]:
        return [dict(value) for value in values]


class HandoffBoundaryUnit:
    """Assembles and verifies handoff packets.

    The handoff layer transfers workflow state. It does not admit facts,
    expand CharacterModel, or bypass same-packet synchronization.
    """

    def build_rebuild_to_review(
        self,
        source_text_ref: str,
        reconstructed_objects: dict,
        confidence_gaps: list[str],
    ) -> HandoffPacket:
        """Assemble a Rebuild -> Review handoff packet."""
        return HandoffPacket(
            handoff_header={
                "source": "RebuildUnit",
                "target": "ReviewUnit",
                "reason": "reconstruction_complete",
            },
            input_anchor={"source_text": source_text_ref},
            output_anchor={"reconstructed_objects": reconstructed_objects},
            change_set=[
                {
                    "action": "create",
                    "objects": list(reconstructed_objects.keys()),
                }
            ],
            open_items=[{"type": "confidence_gap", "content": g} for g in confidence_gaps],
            confidence_and_gaps={"gaps": confidence_gaps},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction_complete",
                must_read_first=[source_text_ref],
                do_not_skip=["review reconstructed object layers"],
            ),
        )

    def build_review_route(
        self,
        *,
        review_target_ref: str,
        route: ReviewRoute,
        issues: list[dict],
        reminders: list[dict],
        output_state_ref: str,
        route_reason: str = "review_completed",
        block_target: Literal["Stop", "RebuildUnit", "Replan"] = "Stop",
    ) -> HandoffPacket:
        """Assemble a Review -> next workflow route handoff packet."""
        target = self._target_for_review_route(route, block_target)
        validated_issues = [review_issue_open_item(issue) for issue in issues]
        validated_reminders = [
            review_reminder_open_item(reminder) for reminder in reminders
        ]
        return HandoffPacket(
            handoff_header={
                "source": "ReviewUnit",
                "target": target,
                "reason": route_reason,
            },
            input_anchor={"review_target_ref": review_target_ref},
            output_anchor={"state_ref": output_state_ref},
            change_set=[
                {
                    "action": "review",
                    "route": route,
                    "issue_count": len(validated_issues),
                    "reminder_count": len(validated_reminders),
                }
            ],
            open_items=[
                *validated_issues,
                *validated_reminders,
            ],
            confidence_and_gaps={},
            next_route=NextRoute(
                recommended_workflow=target,
                route_reason=route_reason,
                review_route=route,
                must_read_first=[review_target_ref],
                do_not_skip=["honor ReviewIssue and ReviewReminder state"],
            ),
        )

    def _target_for_review_route(
        self,
        route: ReviewRoute,
        block_target: Literal["Stop", "RebuildUnit", "Replan"],
    ) -> WorkflowRoute:
        if route == "pass":
            return "ContinueUnit"
        if route == "rewrite":
            return "RewriteUnit"
        return block_target

    def verify(self, packet: HandoffPacket) -> tuple[bool, list[str]]:
        """Verify minimum handoff integrity."""
        violations = []
        handoff_header = _object_container(
            packet.handoff_header,
            "handoff_header",
            violations,
        )
        input_anchor = _object_container(
            packet.input_anchor,
            "input_anchor",
            violations,
        )
        output_anchor = _object_container(
            packet.output_anchor,
            "output_anchor",
            violations,
        )
        confidence_and_gaps = _object_container(
            packet.confidence_and_gaps,
            "confidence_and_gaps",
            violations,
        )
        _verify_confidence_gaps_fields(confidence_and_gaps, violations)
        if not isinstance(packet.change_set, (list, tuple)):
            violations.append("change_set must be a list")
        elif any(not isinstance(item, Mapping) for item in packet.change_set):
            violations.append("change_set entries must be objects")
        else:
            _object_list_entries_have_string_keys(
                packet.change_set,
                "change_set",
                violations,
            )
            _verify_change_set_action_fields(packet.change_set, violations)
        if not isinstance(packet.open_items, (list, tuple)):
            violations.append("open_items must be a list")
        elif any(not isinstance(item, Mapping) for item in packet.open_items):
            violations.append("open_items entries must be objects")
        else:
            _object_list_entries_have_string_keys(
                packet.open_items,
                "open_items",
                violations,
            )
            _verify_review_open_item_fields(packet.open_items, violations)
        _verify_confidence_gap_open_items_match_gaps(
            confidence_and_gaps,
            packet.open_items,
            violations,
        )

        source = handoff_header.get("source") if handoff_header is not None else None
        _verify_header_workflow(
            source,
            "source",
            "missing source workflow",
            violations,
        )
        target = handoff_header.get("target") if handoff_header is not None else None
        _verify_header_workflow(
            target,
            "target",
            "missing target workflow",
            violations,
        )
        _verify_header_transition(source, target, violations)
        if input_anchor is not None and not input_anchor:
            violations.append("missing input_anchor")
        if output_anchor is not None and not output_anchor:
            violations.append("missing output_anchor")
        _verify_anchor_fields(input_anchor, output_anchor, violations)
        _verify_required_standard_anchors(
            source,
            target,
            input_anchor,
            output_anchor,
            violations,
        )

        route = packet.next_route
        if not isinstance(route, NextRoute):
            violations.append("next_route must be a structured NextRoute")
            return len(violations) == 0, violations
        _verify_next_route_fields(route, violations)
        _verify_must_read_first_includes_input_anchors(
            input_anchor,
            route,
            violations,
        )
        _verify_required_standard_route_guards(
            source,
            target,
            route,
            violations,
        )
        recommended_workflow = getattr(route, "recommended_workflow", None)
        route_reason = getattr(route, "route_reason", None)
        review_route = getattr(route, "review_route", None)
        if target and target != recommended_workflow:
            violations.append(
                "handoff target must match next_route.recommended_workflow"
            )
        header_reason = (
            handoff_header.get("reason") if handoff_header is not None else None
        )
        _verify_required_standard_header_reason(
            source,
            target,
            header_reason,
            violations,
        )
        _verify_header_reason(header_reason, route_reason, violations)
        if source == "ReviewUnit" and review_route is None:
            violations.append("ReviewUnit handoff must include review_route")
        if source and source != "ReviewUnit" and review_route is not None:
            violations.append("review_route can only be emitted by ReviewUnit")
        _verify_rebuild_change_set(
            source,
            target,
            packet.change_set,
            output_anchor,
            violations,
        )
        _verify_review_change_set(
            source,
            packet.change_set,
            packet.open_items,
            review_route,
            violations,
        )
        if review_route == "rewrite" and recommended_workflow != "RewriteUnit":
            violations.append("review_route=rewrite must route to RewriteUnit")
        if review_route == "pass" and recommended_workflow != "ContinueUnit":
            violations.append("review_route=pass must route to ContinueUnit")
        if review_route == "block" and recommended_workflow not in {
            "Stop",
            "RebuildUnit",
            "Replan",
        }:
            violations.append(
                "review_route=block must route to Stop, RebuildUnit, or Replan"
            )
        return len(violations) == 0, violations
