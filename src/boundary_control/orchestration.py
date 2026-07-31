"""Executable orchestration gate checks."""

from collections.abc import Mapping

from pydantic import ValidationError

from src.boundary_control.handoff import HandoffBoundaryUnit, HandoffPacket, NextRoute
from src.boundary_control.review_object_contracts import (
    review_issue_from_payload,
    review_reminder_from_payload,
)
from src.boundary_control.serialization import (
    SerializationBoundaryUnit,
    SerializationPackage,
)
from src.boundary_control.validation import NoRegressionValidationUnit


PACKAGE_CONTAINER_FIELDS = (
    "stable_memory",
    "working_set",
    "repair_control",
    "confidence",
    "metadata",
)
PACKAGE_SERIALIZED_LAYER_FIELDS = (
    "stable_memory",
    "working_set",
    "repair_control",
)


def _is_incomplete_open_review_issue(issue: Mapping) -> bool:
    try:
        review_issue_from_payload(issue)
    except (ValidationError, ValueError):
        return True
    return False


def _is_open_blocking_review_issue(issue: Mapping) -> bool:
    try:
        review_issue = review_issue_from_payload(issue)
    except (ValidationError, ValueError):
        return False
    return (
        review_issue.resolution_status == "open"
        and review_issue.severity in {"critical", "blocking"}
    )


def _is_incomplete_review_reminder(reminder: Mapping) -> bool:
    try:
        review_reminder_from_payload(reminder)
    except (ValidationError, ValueError):
        return True
    return False


class OrchestrationGateUnit:
    """Gate workflow movement without owning narrative truth.

    The gate consumes handoff, route, serialization, and validation state. It
    does not repair objects, decide review conclusions, admit facts, or change
    workflow order.
    """

    def verify_entry(
        self,
        packet: HandoffPacket,
        package: SerializationPackage | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify whether the packet can enter its recommended workflow."""
        violations = self._handoff_violations(packet)
        violations.extend(self._blocking_open_item_violations(packet))
        package_container_violations = self._package_container_violations(package)
        violations.extend(package_container_violations)
        if package_container_violations:
            return False, violations
        package_separation_violations = self._package_separation_violations(package)
        violations.extend(package_separation_violations)
        if package_separation_violations:
            return False, violations
        package_serialized_object_violations = (
            self._package_serialized_object_violations(package)
        )
        violations.extend(package_serialized_object_violations)
        if package_serialized_object_violations:
            return False, violations
        violations.extend(self._package_review_object_violations(package))
        violations.extend(self._route_entry_violations(packet, package))
        return len(violations) == 0, violations

    def verify_exit(
        self,
        packet: HandoffPacket,
        package: SerializationPackage,
    ) -> tuple[bool, list[str]]:
        """Verify whether a workflow output can move onward."""
        ok, violations = self.verify_entry(packet, package)
        if not ok:
            return False, violations

        validation_violations = NoRegressionValidationUnit().run(package)
        violations.extend(
            f"no-regression gate: {violation}"
            for violation in validation_violations
        )
        return len(violations) == 0, violations

    def _handoff_violations(self, packet: HandoffPacket) -> list[str]:
        _ok, violations = HandoffBoundaryUnit().verify(packet)
        return [f"handoff gate: {violation}" for violation in violations]

    def _blocking_open_item_violations(self, packet: HandoffPacket) -> list[str]:
        violations = []
        if not isinstance(packet.open_items, (list, tuple)):
            return ["open item gate: open_items must be a list"]
        for item in packet.open_items:
            if not isinstance(item, Mapping):
                violations.append("open item gate: open item must be an object")
                continue
            if item.get("blocking") is True:
                violations.append(
                    "open item gate: blocking open item remains unresolved"
                )
            if item.get("type") == "blocked_cross_handoff_rewrite":
                violations.append(
                    "open item gate: cross-handoff rewrite is not allowed"
                )
            if item.get("type") == "ReviewIssue" and _is_incomplete_open_review_issue(
                item
            ):
                violations.append("open item gate: incomplete ReviewIssue")
            if item.get("type") == "ReviewReminder" and _is_incomplete_review_reminder(
                item
            ):
                violations.append("open item gate: incomplete ReviewReminder")
        return violations

    def _package_container_violations(
        self,
        package: SerializationPackage | None,
    ) -> list[str]:
        if package is None:
            return []
        violations = []
        for field_name in PACKAGE_CONTAINER_FIELDS:
            value = getattr(package, field_name)
            if not isinstance(value, Mapping):
                violations.append(f"package gate: {field_name} must be an object")
                continue
            if field_name not in PACKAGE_SERIALIZED_LAYER_FIELDS:
                if any(not isinstance(key, str) for key in value):
                    violations.append(
                        f"package gate: {field_name} keys must be strings"
                    )
                continue
            for type_name, items in value.items():
                if not isinstance(type_name, str):
                    violations.append(
                        f"package gate: {field_name} type keys must be strings"
                    )
                    continue
                if not isinstance(items, (list, tuple)):
                    violations.append(
                        f"package gate: {field_name}.{type_name} must be a list"
                    )
                    continue
                if any(not isinstance(item, Mapping) for item in items):
                    violations.append(
                        f"package gate: {field_name}.{type_name} entries must be objects"
                    )
        return violations

    def _package_separation_violations(
        self,
        package: SerializationPackage | None,
    ) -> list[str]:
        if package is None:
            return []
        return [
            f"package gate: {violation}"
            for violation in SerializationBoundaryUnit().check_separation(package)
        ]

    def _package_serialized_object_violations(
        self,
        package: SerializationPackage | None,
    ) -> list[str]:
        if package is None:
            return []
        state_package = SerializationPackage(
            stable_memory=package.stable_memory,
            working_set=package.working_set,
        )
        try:
            SerializationBoundaryUnit().deserialize_package(state_package)
        except ValueError as exc:
            return [f"package gate: {exc}"]
        return []

    def _package_review_object_violations(
        self,
        package: SerializationPackage | None,
    ) -> list[str]:
        if package is None:
            return []
        violations = []
        for issue in package.repair_control.get("ReviewIssue", []):
            if _is_incomplete_open_review_issue(issue):
                violations.append("package gate: incomplete ReviewIssue")
        for reminder in package.repair_control.get("ReviewReminder", []):
            if _is_incomplete_review_reminder(reminder):
                violations.append("package gate: incomplete ReviewReminder")
        return violations

    def _route_entry_violations(
        self,
        packet: HandoffPacket,
        package: SerializationPackage | None,
    ) -> list[str]:
        if not isinstance(packet.next_route, NextRoute):
            return []
        route = packet.next_route.recommended_workflow
        if route == "ReviewUnit":
            return self._review_entry_violations(packet, package)
        if route == "ContinueUnit":
            return self._continue_entry_violations(packet, package)
        if route == "RewriteUnit":
            return self._rewrite_entry_violations(packet, package)
        if route in {"Stop", "RebuildUnit", "Replan"}:
            return []
        return [f"route gate: unsupported workflow {route}"]

    def _review_entry_violations(
        self,
        packet: HandoffPacket,
        package: SerializationPackage | None,
    ) -> list[str]:
        if (
            isinstance(packet.output_anchor, Mapping)
            and packet.output_anchor.get("reconstructed_objects")
        ):
            return []
        if package is not None and (
            package.stable_memory
            or package.working_set
            or package.repair_control
        ):
            return []
        return ["route gate: ReviewUnit requires reconstructed objects or package state"]

    def _continue_entry_violations(
        self,
        packet: HandoffPacket,
        package: SerializationPackage | None,
    ) -> list[str]:
        if package is None:
            return ["route gate: ContinueUnit requires a serialization package"]
        if not package.working_set.get("NarrativeState"):
            return ["route gate: ContinueUnit requires runnable NarrativeState"]
        if self._has_incomplete_open_handoff_issue(packet):
            return ["route gate: ContinueUnit blocked by incomplete ReviewIssue"]
        if self._has_incomplete_open_review_issue(package):
            return ["route gate: ContinueUnit blocked by incomplete ReviewIssue"]
        if self._has_blocking_handoff_issue(packet):
            return ["route gate: ContinueUnit blocked by unresolved ReviewIssue"]
        if self._has_blocking_review_issue(package):
            return ["route gate: ContinueUnit blocked by unresolved ReviewIssue"]
        return []

    def _rewrite_entry_violations(
        self,
        packet: HandoffPacket,
        package: SerializationPackage | None,
    ) -> list[str]:
        if self._has_incomplete_open_handoff_issue(packet):
            return ["route gate: RewriteUnit requires complete blocking ReviewIssue"]
        if package is not None and self._has_incomplete_open_review_issue(package):
            return ["route gate: RewriteUnit requires complete blocking ReviewIssue"]
        if self._has_blocking_handoff_issue(packet):
            return []
        if package is not None and self._has_blocking_review_issue(package):
            return []
        if package is None:
            return ["route gate: RewriteUnit requires blocking issue evidence"]
        if not self._has_blocking_review_issue(package):
            return ["route gate: RewriteUnit requires a blocking ReviewIssue"]
        return []

    def _has_blocking_handoff_issue(self, packet: HandoffPacket) -> bool:
        if not isinstance(packet.open_items, (list, tuple)):
            return False
        for item in packet.open_items:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") != "ReviewIssue":
                continue
            if _is_open_blocking_review_issue(item):
                return True
        return False

    def _has_incomplete_open_handoff_issue(self, packet: HandoffPacket) -> bool:
        if not isinstance(packet.open_items, (list, tuple)):
            return False
        for item in packet.open_items:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") != "ReviewIssue":
                continue
            if _is_incomplete_open_review_issue(item):
                return True
        return False

    def _has_incomplete_open_review_issue(
        self, package: SerializationPackage
    ) -> bool:
        for issue in package.repair_control.get("ReviewIssue", []):
            if _is_incomplete_open_review_issue(issue):
                return True
        return False

    def _has_blocking_review_issue(self, package: SerializationPackage) -> bool:
        for issue in package.repair_control.get("ReviewIssue", []):
            if _is_open_blocking_review_issue(issue):
                return True
        return False
