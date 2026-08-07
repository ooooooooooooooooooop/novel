"""Staged response-file boundary."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from src.boundary_control.automation_contracts import (
    AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS,
    AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS,
    PENDING_AUTOMATION_METADATA_FIELDS,
    response_materialization_metadata,
    validate_response_materialization_metadata_in_payload,
)
from src.boundary_control.runtime_identity import (
    content_evidence_from_bytes,
    expected_staged_response_path,
    staged_slot_id,
    validate_content_hash,
    validate_staged_slot_id,
)
from src.llm_interface import LLMInterface

STAGED_RESPONSE_RESULT_SCHEMA_VERSION = 1
STAGED_RESPONSE_RESULT_PAYLOAD_FIELDS = (
    "schema_version",
    "type",
    "materialization_contract_version",
    "materialization_contract",
    "materialized_action",
    "provider_call_performed",
    "closed_loop_advanced",
    "prompt_file",
    "response_file",
    "prompt_path",
    "response_path",
    "slot_id",
    "interface_name",
    "prompt_hash",
    "prompt_bytes",
    "response_hash",
    "response_bytes",
    "response_chars",
)
STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS = (
    "model",
    "prompt",
    "response_text",
    "text",
)


def _validate_newer_than(newer_than: float | None) -> float | None:
    if newer_than is None:
        return None
    if (
        not isinstance(newer_than, (int, float))
        or isinstance(newer_than, bool)
        or not math.isfinite(newer_than)
        or newer_than < 0
    ):
        raise ValueError("newer_than must be a finite non-negative number")
    return float(newer_than)


def _validate_slot_id(slot_id: object) -> str:
    return validate_staged_slot_id(slot_id)


def _payload_non_empty_string(payload: dict[object, object], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"staged response result payload {field} must be a non-empty string"
        )
    return value


def _validate_interface_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    value.encode("utf-8")
    if any(char.isspace() for char in value):
        raise ValueError(f"{label} must not contain whitespace")
    return value


def _result_payload_forbidden_fields(
    payload: dict[str, object],
    fields: tuple[str, ...],
) -> list[str]:
    return [field for field in fields if field in payload]


def _read_non_empty_prompt_snapshot(prompt_path: Path):
    prompt_bytes = Path(prompt_path).read_bytes()
    prompt_text = prompt_bytes.decode("utf-8-sig")
    if not prompt_text.strip():
        raise ValueError(f"prompt file must be non-empty: {prompt_path}")
    return prompt_text, content_evidence_from_bytes(prompt_bytes)


def _prompt_evidence_from_non_empty_file(prompt_path: Path):
    _prompt_text, prompt_evidence = _read_non_empty_prompt_snapshot(prompt_path)
    return prompt_evidence


@dataclass(frozen=True)
class PendingResponseSlot:
    """One prompt waiting for its matching staged response file."""

    prompt_path: Path
    response_path: Path
    prompt_mtime: float
    prompt_hash: str
    prompt_bytes: int
    slot_id: str

    def __post_init__(self) -> None:
        prompt_path = Path(self.prompt_path)
        response_path = Path(self.response_path)
        if not prompt_path.is_absolute():
            raise ValueError("pending slot prompt_path must be absolute")
        if not response_path.is_absolute():
            raise ValueError("pending slot response_path must be absolute")
        expected_response_path = expected_staged_response_path(prompt_path)
        if response_path != expected_response_path:
            raise ValueError(
                f"pending slot response_path must match prompt_path: "
                f"expected {expected_response_path}, got {response_path}"
            )
        if response_path.exists():
            raise FileExistsError(
                f"pending slot response file already exists: {response_path}"
            )
        if (
            not isinstance(self.prompt_mtime, (int, float))
            or isinstance(self.prompt_mtime, bool)
            or not math.isfinite(self.prompt_mtime)
            or self.prompt_mtime < 0
        ):
            raise ValueError(
                "pending slot prompt_mtime must be a finite non-negative number"
            )
        prompt_mtime = float(self.prompt_mtime)
        expected_slot_id = staged_slot_id(prompt_path)
        slot_id = _validate_slot_id(self.slot_id)
        if slot_id != expected_slot_id:
            raise ValueError(
                f"pending slot slot_id must match prompt_path: "
                f"expected {expected_slot_id}, got {slot_id}"
            )
        object.__setattr__(self, "prompt_path", prompt_path)
        object.__setattr__(self, "response_path", response_path)
        object.__setattr__(
            self,
            "prompt_hash",
            validate_content_hash(self.prompt_hash, "pending slot prompt_hash"),
        )
        prompt_evidence = _prompt_evidence_from_non_empty_file(prompt_path)
        if prompt_evidence.content_hash != self.prompt_hash:
            raise ValueError(
                "pending slot prompt_hash must match prompt file: "
                f"expected {prompt_evidence.content_hash}, got {self.prompt_hash}"
            )
        if (
            not isinstance(self.prompt_bytes, int)
            or isinstance(self.prompt_bytes, bool)
            or self.prompt_bytes <= 0
        ):
            raise ValueError("pending slot prompt_bytes must be a positive integer")
        if prompt_evidence.byte_count != self.prompt_bytes:
            raise ValueError(
                "pending slot prompt_bytes must match prompt file: "
                f"expected {prompt_evidence.byte_count}, got {self.prompt_bytes}"
            )
        current_prompt_mtime = prompt_path.stat().st_mtime
        if current_prompt_mtime != prompt_mtime:
            raise ValueError(
                "pending slot prompt_mtime must match prompt file: "
                f"expected {current_prompt_mtime}, got {prompt_mtime}"
            )
        object.__setattr__(self, "prompt_mtime", prompt_mtime)
        object.__setattr__(self, "prompt_bytes", self.prompt_bytes)
        object.__setattr__(self, "slot_id", slot_id)


@dataclass(frozen=True)
class StagedResponseResult:
    """Audit metadata for one materialized staged response."""

    prompt_path: Path
    response_path: Path
    slot_id: str
    interface_name: str
    prompt_hash: str
    prompt_bytes: int
    response_hash: str
    response_bytes: int
    response_chars: int

    def __post_init__(self) -> None:
        prompt_path = Path(self.prompt_path)
        response_path = Path(self.response_path)
        if not prompt_path.is_absolute():
            raise ValueError(
                "staged response result prompt_path must be absolute"
            )
        if not response_path.is_absolute():
            raise ValueError(
                "staged response result response_path must be absolute"
            )
        expected_response_path = expected_staged_response_path(prompt_path)
        if response_path != expected_response_path:
            raise ValueError(
                "staged response result response_path must match prompt_path: "
                f"expected {expected_response_path}, got {response_path}"
            )
        slot_id = _validate_slot_id(self.slot_id)
        expected_slot_id = staged_slot_id(prompt_path)
        if slot_id != expected_slot_id:
            raise ValueError(
                "staged response result slot_id must match prompt_path: "
                f"expected {expected_slot_id}, got {slot_id}"
            )
        interface_name = _validate_interface_name(
            self.interface_name,
            "staged response result interface_name",
        )
        prompt_hash = validate_content_hash(
            self.prompt_hash,
            "staged response result prompt_hash",
        )
        response_hash = validate_content_hash(
            self.response_hash,
            "staged response result response_hash",
        )
        if (
            not isinstance(self.prompt_bytes, int)
            or isinstance(self.prompt_bytes, bool)
            or self.prompt_bytes <= 0
        ):
            raise ValueError(
                "staged response result prompt_bytes must be a positive integer"
            )
        if (
            not isinstance(self.response_bytes, int)
            or isinstance(self.response_bytes, bool)
            or self.response_bytes <= 0
        ):
            raise ValueError(
                "staged response result response_bytes must be a positive integer"
            )
        if (
            not isinstance(self.response_chars, int)
            or isinstance(self.response_chars, bool)
            or self.response_chars <= 0
        ):
            raise ValueError(
                "staged response result response_chars must be a positive integer"
            )
        prompt_evidence = _prompt_evidence_from_non_empty_file(prompt_path)
        if prompt_evidence.content_hash != prompt_hash:
            raise ValueError(
                "staged response result prompt_hash must match prompt file: "
                f"expected {prompt_evidence.content_hash}, got {prompt_hash}"
            )
        if prompt_evidence.byte_count != self.prompt_bytes:
            raise ValueError(
                "staged response result prompt_bytes must match prompt file: "
                f"expected {prompt_evidence.byte_count}, got {self.prompt_bytes}"
            )
        response_data = response_path.read_bytes()
        response_text = response_data.decode("utf-8")
        if not response_text.strip():
            raise ValueError(
                f"staged response result response file must be non-empty: {response_path}"
            )
        response_evidence = content_evidence_from_bytes(response_data)
        if response_evidence.content_hash != response_hash:
            raise ValueError(
                "staged response result response_hash must match response file: "
                f"expected {response_evidence.content_hash}, got {response_hash}"
            )
        if response_evidence.byte_count != self.response_bytes:
            raise ValueError(
                "staged response result response_bytes must match response file: "
                f"expected {response_evidence.byte_count}, got {self.response_bytes}"
            )
        if len(response_text) != self.response_chars:
            raise ValueError(
                "staged response result response_chars must match response file: "
                f"expected {len(response_text)}, got {self.response_chars}"
            )
        object.__setattr__(self, "prompt_path", prompt_path)
        object.__setattr__(self, "response_path", response_path)
        object.__setattr__(self, "slot_id", slot_id)
        object.__setattr__(self, "interface_name", interface_name)
        object.__setattr__(self, "prompt_hash", prompt_hash)
        object.__setattr__(self, "response_hash", response_hash)

    def to_payload(self) -> dict[str, object]:
        payload = {
            "schema_version": STAGED_RESPONSE_RESULT_SCHEMA_VERSION,
            "type": "STAGED_RESPONSE_RESULT",
            **response_materialization_metadata(),
            "prompt_file": self.prompt_path.name,
            "response_file": self.response_path.name,
            "prompt_path": str(self.prompt_path),
            "response_path": str(self.response_path),
            "slot_id": self.slot_id,
            "interface_name": self.interface_name,
            "prompt_hash": self.prompt_hash,
            "prompt_bytes": self.prompt_bytes,
            "response_hash": self.response_hash,
            "response_bytes": self.response_bytes,
            "response_chars": self.response_chars,
        }
        ordered_payload = {
            field: payload[field] for field in STAGED_RESPONSE_RESULT_PAYLOAD_FIELDS
        }
        StagedResponseResult.from_payload(ordered_payload)
        return ordered_payload

    @classmethod
    def from_payload(cls, payload: object) -> "StagedResponseResult":
        if not isinstance(payload, dict):
            raise ValueError("staged response result payload must be an object")
        if any(not isinstance(key, str) for key in payload):
            raise ValueError("staged response result payload keys must be strings")
        forbidden = _result_payload_forbidden_fields(
            payload,
            AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS,
        )
        if forbidden:
            raise ValueError(
                "staged response result payload must not include credential "
                f"field(s): {', '.join(forbidden)}"
            )
        forbidden = _result_payload_forbidden_fields(
            payload,
            AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS,
        )
        if forbidden:
            raise ValueError(
                "staged response result payload must not include execution "
                f"claim field(s): {', '.join(forbidden)}"
            )
        forbidden = _result_payload_forbidden_fields(
            payload,
            PENDING_AUTOMATION_METADATA_FIELDS,
        )
        if forbidden:
            raise ValueError(
                "staged response result payload must not include pending "
                f"automation metadata field(s): {', '.join(forbidden)}"
            )
        forbidden = _result_payload_forbidden_fields(
            payload,
            STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS,
        )
        if forbidden:
            raise ValueError(
                "staged response result payload must not include prompt or "
                f"response content field(s): {', '.join(forbidden)}"
            )
        fields = set(STAGED_RESPONSE_RESULT_PAYLOAD_FIELDS)
        keys = set(payload)
        missing = [field for field in STAGED_RESPONSE_RESULT_PAYLOAD_FIELDS if field not in payload]
        if missing:
            raise ValueError(
                "missing staged response result payload field(s): "
                f"{', '.join(missing)}"
            )
        unknown = sorted(keys - fields)
        if unknown:
            raise ValueError(
                "unknown staged response result payload field(s): "
                f"{', '.join(unknown)}"
            )
        schema_version = payload["schema_version"]
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != STAGED_RESPONSE_RESULT_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported staged response result schema_version: "
                f"{schema_version}"
            )
        payload_type = _payload_non_empty_string(payload, "type")
        if payload_type != "STAGED_RESPONSE_RESULT":
            raise ValueError(
                f"unsupported staged response result type: {payload_type}"
            )
        validate_response_materialization_metadata_in_payload(payload)
        prompt_file = _payload_non_empty_string(payload, "prompt_file")
        response_file = _payload_non_empty_string(payload, "response_file")
        prompt_path = Path(_payload_non_empty_string(payload, "prompt_path"))
        response_path = Path(_payload_non_empty_string(payload, "response_path"))
        if prompt_file != prompt_path.name:
            raise ValueError(
                "staged response result prompt_file must match prompt_path: "
                f"expected {prompt_path.name}, got {prompt_file}"
            )
        if response_file != response_path.name:
            raise ValueError(
                "staged response result response_file must match response_path: "
                f"expected {response_path.name}, got {response_file}"
            )
        return cls(
            prompt_path=prompt_path,
            response_path=response_path,
            slot_id=payload["slot_id"],
            interface_name=payload["interface_name"],
            prompt_hash=payload["prompt_hash"],
            prompt_bytes=payload["prompt_bytes"],
            response_hash=payload["response_hash"],
            response_bytes=payload["response_bytes"],
            response_chars=payload["response_chars"],
        )


class ResponseFileBoundaryUnit:
    """Controls the only file write DirectAPI/UI may perform in staged mode."""

    def expected_response_path(self, prompt_path: Path) -> Path:
        return expected_staged_response_path(prompt_path)

    def verify_prompt_hash(
        self,
        prompt_path: Path,
        expected_prompt_hash: str | None = None,
    ) -> str:
        prompt_path = Path(prompt_path)
        self.expected_response_path(prompt_path)
        if expected_prompt_hash is not None:
            expected_prompt_hash = validate_content_hash(
                expected_prompt_hash,
                "expected_prompt_hash",
            )
        prompt_evidence = _prompt_evidence_from_non_empty_file(prompt_path)
        if (
            expected_prompt_hash is not None
            and expected_prompt_hash != prompt_evidence.content_hash
        ):
            raise ValueError(
                f"prompt hash mismatch for {prompt_path}: "
                f"expected {expected_prompt_hash}, "
                f"actual {prompt_evidence.content_hash}"
            )
        return prompt_evidence.content_hash

    def verify_response_slot(
        self,
        *,
        prompt_path: Path,
        response_path: Path,
        expected_prompt_hash: str | None = None,
    ) -> Path:
        prompt_path = Path(prompt_path)
        response_path = Path(response_path)
        if not prompt_path.is_absolute():
            raise ValueError("response slot prompt_path must be absolute")
        if not response_path.is_absolute():
            raise ValueError("response slot response_path must be absolute")
        expected_path = self.expected_response_path(prompt_path)

        if response_path != expected_path:
            raise ValueError(
                f"response path must match prompt path: expected {expected_path}, "
                f"got {response_path}"
            )
        if response_path.exists():
            raise FileExistsError(f"response file already exists: {response_path}")
        if not prompt_path.exists() or not prompt_path.is_file():
            raise FileNotFoundError(f"prompt file not found: {prompt_path}")
        self.verify_prompt_hash(prompt_path, expected_prompt_hash)
        return response_path

    def materialize_response(
        self,
        *,
        prompt_path: Path,
        response_path: Path,
        response_text: str,
        expected_prompt_hash: str | None = None,
    ) -> Path:
        response_path = self.verify_response_slot(
            prompt_path=prompt_path,
            response_path=response_path,
            expected_prompt_hash=expected_prompt_hash,
        )

        if not isinstance(response_text, str) or not response_text.strip():
            raise ValueError("response text must be a non-empty string")

        response_bytes = response_text.encode("utf-8")
        with response_path.open("xb") as response_file:
            response_file.write(response_bytes)
        return response_path

    def discover_pending_slots(
        self,
        output_dir: Path,
        *,
        newer_than: float | None = None,
    ) -> list[PendingResponseSlot]:
        newer_than = _validate_newer_than(newer_than)
        output_dir = Path(output_dir)
        if not output_dir.is_absolute():
            raise ValueError("output directory must be absolute")
        if not output_dir.exists() or not output_dir.is_dir():
            raise FileNotFoundError(f"output directory not found: {output_dir}")

        slots: list[PendingResponseSlot] = []
        for prompt_path in output_dir.glob("*_prompt.txt"):
            prompt_mtime = prompt_path.stat().st_mtime
            if newer_than is not None and prompt_mtime <= newer_than:
                continue
            response_path = self.expected_response_path(prompt_path)
            if response_path.exists():
                continue
            prompt_evidence = _prompt_evidence_from_non_empty_file(prompt_path)
            slots.append(
                PendingResponseSlot(
                    prompt_path=prompt_path,
                    response_path=response_path,
                    prompt_mtime=prompt_mtime,
                    prompt_hash=prompt_evidence.content_hash,
                    prompt_bytes=prompt_evidence.byte_count,
                    slot_id=staged_slot_id(prompt_path),
                )
            )
        return sorted(
            slots,
            key=lambda slot: (slot.prompt_mtime, slot.prompt_path.name),
        )

    def require_single_pending_slot(
        self,
        output_dir: Path,
        *,
        newer_than: float | None = None,
    ) -> PendingResponseSlot:
        slots = self.discover_pending_slots(output_dir, newer_than=newer_than)
        if not slots:
            raise ValueError(f"no pending response slot found in {Path(output_dir)}")
        if len(slots) > 1:
            names = ", ".join(slot.response_path.name for slot in slots)
            raise ValueError(f"multiple pending response slots found: {names}")
        return slots[0]

    def require_pending_slot(
        self,
        output_dir: Path,
        *,
        slot_id: str,
        newer_than: float | None = None,
        expected_prompt_hash: str | None = None,
    ) -> PendingResponseSlot:
        slot_id = _validate_slot_id(slot_id)
        matches = [
            slot
            for slot in self.discover_pending_slots(output_dir, newer_than=newer_than)
            if slot.slot_id == slot_id
        ]
        if not matches:
            raise ValueError(f"pending response slot not found: {slot_id}")
        if len(matches) > 1:
            raise ValueError(f"multiple pending response slots found for slot_id: {slot_id}")
        slot = matches[0]
        if expected_prompt_hash is not None:
            expected_prompt_hash = validate_content_hash(
                expected_prompt_hash,
                "expected_prompt_hash",
            )
        current_prompt_evidence = _prompt_evidence_from_non_empty_file(slot.prompt_path)
        if (
            expected_prompt_hash is not None
            and expected_prompt_hash != current_prompt_evidence.content_hash
        ):
            raise ValueError(
                f"prompt hash mismatch for {slot.prompt_path}: "
                f"expected {expected_prompt_hash}, "
                f"actual {current_prompt_evidence.content_hash}"
            )
        return PendingResponseSlot(
            prompt_path=slot.prompt_path,
            response_path=slot.response_path,
            prompt_mtime=slot.prompt_mtime,
            prompt_hash=current_prompt_evidence.content_hash,
            prompt_bytes=current_prompt_evidence.byte_count,
            slot_id=slot.slot_id,
        )


class StagedResponseRunner:
    """Materializes one staged response by calling an LLM interface."""

    def __init__(self, boundary: ResponseFileBoundaryUnit | None = None):
        if boundary is not None and not isinstance(boundary, ResponseFileBoundaryUnit):
            raise TypeError("boundary must be a ResponseFileBoundaryUnit")
        self.boundary = boundary or ResponseFileBoundaryUnit()

    def call_and_materialize(
        self,
        *,
        prompt_path: Path,
        response_path: Path,
        interface: LLMInterface,
        expected_prompt_hash: str | None = None,
    ) -> Path:
        return self.call_and_materialize_result(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
            expected_prompt_hash=expected_prompt_hash,
        ).response_path

    def call_and_materialize_result(
        self,
        *,
        prompt_path: Path,
        response_path: Path,
        interface: LLMInterface,
        expected_prompt_hash: str | None = None,
    ) -> StagedResponseResult:
        prompt_path = Path(prompt_path)
        response_path = Path(response_path)
        self.boundary.verify_response_slot(
            prompt_path=prompt_path,
            response_path=response_path,
            expected_prompt_hash=expected_prompt_hash,
        )
        prompt, consumed_prompt_evidence = _read_non_empty_prompt_snapshot(prompt_path)
        if (
            expected_prompt_hash is not None
            and expected_prompt_hash != consumed_prompt_evidence.content_hash
        ):
            raise ValueError(
                f"prompt hash mismatch for {prompt_path}: "
                f"expected {expected_prompt_hash}, "
                f"actual {consumed_prompt_evidence.content_hash}"
            )
        if not isinstance(interface, LLMInterface):
            raise TypeError("interface must be an LLMInterface")
        interface_name = _validate_interface_name(
            interface.name(),
            "interface name",
        )
        response_text = interface.call(prompt)
        current_interface_name = _validate_interface_name(
            interface.name(),
            "interface name",
        )
        if current_interface_name != interface_name:
            raise ValueError(
                "interface name changed during provider call: "
                f"expected {interface_name}, got {current_interface_name}"
            )
        written_path = self.boundary.materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text=response_text,
            expected_prompt_hash=consumed_prompt_evidence.content_hash,
        )
        final_prompt_evidence = _prompt_evidence_from_non_empty_file(prompt_path)
        if final_prompt_evidence.content_hash != consumed_prompt_evidence.content_hash:
            raise ValueError(
                f"prompt hash mismatch for {prompt_path}: "
                f"expected {consumed_prompt_evidence.content_hash}, "
                f"actual {final_prompt_evidence.content_hash}"
            )
        response_data = written_path.read_bytes()
        response_evidence = content_evidence_from_bytes(response_data)
        return StagedResponseResult(
            prompt_path=prompt_path,
            response_path=written_path,
            slot_id=staged_slot_id(prompt_path),
            interface_name=interface_name,
            prompt_hash=final_prompt_evidence.content_hash,
            prompt_bytes=final_prompt_evidence.byte_count,
            response_hash=response_evidence.content_hash,
            response_bytes=response_evidence.byte_count,
            response_chars=len(response_text),
        )

    def call_single_pending(
        self,
        *,
        output_dir: Path,
        interface: LLMInterface,
        newer_than: float | None = None,
        expected_prompt_hash: str | None = None,
    ) -> Path:
        return self.call_single_pending_result(
            output_dir=output_dir,
            interface=interface,
            newer_than=newer_than,
            expected_prompt_hash=expected_prompt_hash,
        ).response_path

    def call_single_pending_result(
        self,
        *,
        output_dir: Path,
        interface: LLMInterface,
        newer_than: float | None = None,
        expected_prompt_hash: str | None = None,
    ) -> StagedResponseResult:
        slot = self.boundary.require_single_pending_slot(
            output_dir,
            newer_than=newer_than,
        )
        return self.call_and_materialize_result(
            prompt_path=slot.prompt_path,
            response_path=slot.response_path,
            interface=interface,
            expected_prompt_hash=(
                expected_prompt_hash
                if expected_prompt_hash is not None
                else slot.prompt_hash
            ),
        )

    def call_pending_slot(
        self,
        *,
        output_dir: Path,
        slot_id: str,
        interface: LLMInterface,
        newer_than: float | None = None,
        expected_prompt_hash: str | None = None,
    ) -> Path:
        return self.call_pending_slot_result(
            output_dir=output_dir,
            slot_id=slot_id,
            interface=interface,
            newer_than=newer_than,
            expected_prompt_hash=expected_prompt_hash,
        ).response_path

    def call_pending_slot_result(
        self,
        *,
        output_dir: Path,
        slot_id: str,
        interface: LLMInterface,
        newer_than: float | None = None,
        expected_prompt_hash: str | None = None,
    ) -> StagedResponseResult:
        slot = self.boundary.require_pending_slot(
            output_dir,
            slot_id=slot_id,
            newer_than=newer_than,
            expected_prompt_hash=expected_prompt_hash,
        )
        return self.call_and_materialize_result(
            prompt_path=slot.prompt_path,
            response_path=slot.response_path,
            interface=interface,
            expected_prompt_hash=(
                expected_prompt_hash
                if expected_prompt_hash is not None
                else slot.prompt_hash
            ),
        )


# 单章周期内被消费、不允许泄漏到下一章的 staged 响应。
# rebuild_response / outline_response 是跨章输入解析，不在此列。
CYCLE_RESPONSE_FILES: tuple[str, ...] = (
    "continue_response.txt",
    "proposals_response.txt",
    "character_update_response.txt",
    "review_response.txt",
    "prose_response.txt",
)


def reset_consumed_responses(output_dir: Path) -> list[str]:
    """移除已消费的本章 staged 响应，使下一章从全新 prompt 开始.

    防止重跑已完成章时，Continue/Prose/Review 复用上一章的 response，
    把当前章 PlotUnit 逐字节重渲染成重复的下章文件（已知腐蚀真实作品
    的 bug：重跑已完成章 → 生成逐字节重复的 chapter_N+1）。
    """
    output_dir = Path(output_dir)
    removed: list[str] = []
    for name in CYCLE_RESPONSE_FILES:
        path = output_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    return removed
