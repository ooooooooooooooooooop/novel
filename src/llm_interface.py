"""LLM interface abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from src.boundary_control.automation_contracts import (
    PENDING_AUTOMATION_METADATA_FIELDS,
    RESPONSE_MATERIALIZATION_METADATA_FIELDS,
)
from src.boundary_control.runtime_identity import (
    content_evidence_from_bytes,
    expected_staged_response_path,
    file_content_evidence,
    file_content_hash,
    staged_slot_id,
    validate_content_hash,
    validate_staged_slot_id,
)

ACTION_BLOCK_SCHEMA_VERSION = 1
ACTION_BLOCK_INTERFACE = "FileExchangeInterface"
ACTION_BLOCK_FIELDS = (
    "schema_version",
    "type",
    "prompt_file",
    "response_file",
    "slot_id",
    "prompt_hash",
    "prompt_bytes",
    "interface",
)
DIRECT_API_PAYLOAD_SCHEMA_VERSION = 1
DIRECT_API_REQUEST_TYPE = "DIRECT_API_REQUEST"
DIRECT_API_RESPONSE_TYPE = "DIRECT_API_RESPONSE"
DIRECT_API_REQUEST_PAYLOAD_FIELDS = (
    "schema_version",
    "type",
    "prompt",
    "model",
)
DIRECT_API_RESPONSE_PAYLOAD_FIELDS = (
    "schema_version",
    "type",
    "text",
    "model",
)
DIRECT_API_FORBIDDEN_AUDIT_PAYLOAD_FIELDS = (
    "api_key",
    "credential",
    "credentials",
    "secret",
    "token",
)
DIRECT_API_FORBIDDEN_EXECUTION_CLAIM_FIELDS = (
    "closed_loop_result",
    "fallback_provider",
    "provider_call_result",
    "provider_response",
    "retry",
)
DIRECT_API_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS = (
    *PENDING_AUTOMATION_METADATA_FIELDS,
    *RESPONSE_MATERIALIZATION_METADATA_FIELDS,
)
ACTION_BLOCK_FORBIDDEN_CREDENTIAL_FIELDS = DIRECT_API_FORBIDDEN_AUDIT_PAYLOAD_FIELDS
ACTION_BLOCK_FORBIDDEN_EXECUTION_CLAIM_FIELDS = (
    DIRECT_API_FORBIDDEN_EXECUTION_CLAIM_FIELDS
)
ACTION_BLOCK_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS = (
    DIRECT_API_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS
)


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_utf8_encodable_string(value: object, label: str) -> str:
    value = _require_non_empty_string(value, label)
    value.encode("utf-8")
    return value


def _require_identifier_string(value: object, label: str) -> str:
    value = _require_utf8_encodable_string(value, label)
    if any(char.isspace() for char in value):
        raise ValueError(f"{label} must not contain whitespace")
    return value


def _require_optional_identifier_string(
    value: object | None,
    label: str,
) -> str | None:
    if value is None:
        return None
    return _require_identifier_string(value, label)


def _require_payload_fields(
    payload: object,
    *,
    fields: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError(f"{label} payload keys must be strings")
    forbidden = _direct_api_credential_fields(payload)
    if forbidden:
        raise ValueError(
            f"{label} payload must not include credential field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _direct_api_execution_claim_fields(payload)
    if forbidden:
        raise ValueError(
            f"{label} payload must not include execution claim field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _direct_api_cross_contract_metadata_fields(payload)
    if forbidden:
        raise ValueError(
            f"{label} payload must not include cross-contract metadata field(s): "
            f"{', '.join(forbidden)}"
        )
    keys = set(payload)
    expected = set(fields)
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"missing {label} payload field(s): {', '.join(missing)}")
    unknown = sorted(str(key) for key in keys - expected)
    if unknown:
        raise ValueError(f"unknown {label} payload field(s): {', '.join(unknown)}")
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != DIRECT_API_PAYLOAD_SCHEMA_VERSION
    ):
        raise ValueError(f"unsupported {label} schema_version: {schema_version}")
    return payload


def _direct_api_credential_fields(payload: dict[str, object]) -> list[str]:
    return [
        field for field in DIRECT_API_FORBIDDEN_AUDIT_PAYLOAD_FIELDS if field in payload
    ]


def _direct_api_execution_claim_fields(payload: dict[str, object]) -> list[str]:
    return [
        field
        for field in DIRECT_API_FORBIDDEN_EXECUTION_CLAIM_FIELDS
        if field in payload
    ]


def _direct_api_cross_contract_metadata_fields(
    payload: dict[str, object],
) -> list[str]:
    return [
        field
        for field in DIRECT_API_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS
        if field in payload
    ]


def _action_block_credential_fields(payload: dict[str, object]) -> list[str]:
    return [
        field for field in ACTION_BLOCK_FORBIDDEN_CREDENTIAL_FIELDS if field in payload
    ]


def _action_block_execution_claim_fields(payload: dict[str, object]) -> list[str]:
    return [
        field
        for field in ACTION_BLOCK_FORBIDDEN_EXECUTION_CLAIM_FIELDS
        if field in payload
    ]


def _action_block_cross_contract_metadata_fields(
    payload: dict[str, object],
) -> list[str]:
    return [
        field
        for field in ACTION_BLOCK_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS
        if field in payload
    ]


def _validate_action_block_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("action block payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("action block payload keys must be strings")
    forbidden = _action_block_credential_fields(payload)
    if forbidden:
        raise ValueError(
            "action block payload must not include credential field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _action_block_execution_claim_fields(payload)
    if forbidden:
        raise ValueError(
            "action block payload must not include execution claim field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _action_block_cross_contract_metadata_fields(payload)
    if forbidden:
        raise ValueError(
            "action block payload must not include cross-contract metadata field(s): "
            f"{', '.join(forbidden)}"
        )
    expected = set(ACTION_BLOCK_FIELDS)
    missing = [field for field in ACTION_BLOCK_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"missing action block payload field(s): {', '.join(missing)}")
    unknown = sorted(str(key) for key in set(payload) - expected)
    if unknown:
        raise ValueError(f"unknown action block payload field(s): {', '.join(unknown)}")
    if payload["schema_version"] != str(ACTION_BLOCK_SCHEMA_VERSION):
        raise ValueError(
            "unsupported action block payload schema_version: "
            f"{payload['schema_version']}"
        )
    if payload["type"] != "LLM_CALL":
        raise ValueError(f"unsupported action block payload type: {payload['type']}")
    if payload["interface"] != ACTION_BLOCK_INTERFACE:
        raise ValueError(
            "unsupported action block payload interface: "
            f"{payload['interface']}"
        )
    prompt_file = _require_non_empty_string(
        payload["prompt_file"],
        "action block payload prompt_file",
    )
    response_file = _require_non_empty_string(
        payload["response_file"],
        "action block payload response_file",
    )
    prompt_path = Path(prompt_file)
    expected_response_path = expected_staged_response_path(prompt_path)
    if Path(response_file) != expected_response_path:
        raise ValueError(
            "action block payload response_file must match prompt_file: "
            f"expected {expected_response_path}, got {response_file}"
        )
    expected_slot_id = staged_slot_id(prompt_path)
    slot_id = validate_staged_slot_id(
        payload["slot_id"],
        "action block payload slot_id",
    )
    if slot_id != expected_slot_id:
        raise ValueError(
            "action block payload slot_id must match prompt_file: "
            f"expected {expected_slot_id}, got {slot_id}"
        )
    validate_content_hash(payload["prompt_hash"], "action block payload prompt_hash")
    prompt_bytes_text = _require_non_empty_string(
        payload["prompt_bytes"],
        "action block payload prompt_bytes",
    )
    try:
        prompt_bytes = int(prompt_bytes_text)
    except ValueError as exc:
        raise ValueError(
            f"invalid action block payload prompt_bytes: {prompt_bytes_text}"
        ) from exc
    if prompt_bytes <= 0 or prompt_bytes_text != str(prompt_bytes):
        raise ValueError(
            f"invalid action block payload prompt_bytes: {prompt_bytes_text}"
        )


def parse_direct_api_payload(
    payload: object,
) -> "DirectAPIRequest | DirectAPIResponse":
    """Parse a DirectAPI audit payload through the shared schema gate."""

    if not isinstance(payload, dict):
        raise ValueError("DirectAPI payload must be an object")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("DirectAPI payload keys must be strings")
    forbidden = _direct_api_credential_fields(payload)
    if forbidden:
        raise ValueError(
            "DirectAPI payload must not include credential field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _direct_api_execution_claim_fields(payload)
    if forbidden:
        raise ValueError(
            "DirectAPI payload must not include execution claim field(s): "
            f"{', '.join(forbidden)}"
        )
    forbidden = _direct_api_cross_contract_metadata_fields(payload)
    if forbidden:
        raise ValueError(
            "DirectAPI payload must not include cross-contract metadata field(s): "
            f"{', '.join(forbidden)}"
        )
    missing = [
        field for field in ("schema_version", "type") if field not in payload
    ]
    if missing:
        raise ValueError(
            "missing DirectAPI payload identity field(s): "
            f"{', '.join(missing)}"
        )
    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != DIRECT_API_PAYLOAD_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported DirectAPI payload schema_version: {schema_version}"
        )
    payload_type = _require_identifier_string(
        payload["type"],
        "DirectAPI payload type",
    )
    if payload_type == DIRECT_API_REQUEST_TYPE:
        return DirectAPIRequest.from_payload(payload)
    if payload_type == DIRECT_API_RESPONSE_TYPE:
        return DirectAPIResponse.from_payload(payload)
    raise ValueError(f"unsupported DirectAPI payload type: {payload_type}")


@dataclass(frozen=True)
class FileExchangeAction:
    """Machine-readable metadata printed in the staged action block."""

    schema_version: int
    type: str
    prompt_file: str
    response_file: str
    slot_id: str
    prompt_hash: str
    prompt_bytes: int
    interface: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != ACTION_BLOCK_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported action block schema_version: "
                f"{self.schema_version}"
            )
        if self.type != "LLM_CALL":
            raise ValueError(f"unsupported action block type: {self.type}")
        if self.interface != ACTION_BLOCK_INTERFACE:
            raise ValueError(
                f"unsupported action block interface: {self.interface}"
            )
        _require_non_empty_string(self.prompt_file, "action prompt_file")
        _require_non_empty_string(self.response_file, "action response_file")
        prompt_path = Path(self.prompt_file)
        expected_response_path = expected_staged_response_path(prompt_path)
        if Path(self.response_file) != expected_response_path:
            raise ValueError(
                "action response_file must match prompt_file: "
                f"expected {expected_response_path}, got {self.response_file}"
            )
        expected_slot_id = staged_slot_id(prompt_path)
        slot_id = validate_staged_slot_id(self.slot_id, "action slot_id")
        if slot_id != expected_slot_id:
            raise ValueError(
                "action slot_id must match prompt_file: "
                f"expected {expected_slot_id}, got {slot_id}"
            )
        prompt_hash = validate_content_hash(
            self.prompt_hash,
            "action prompt_hash",
        )
        if (
            not isinstance(self.prompt_bytes, int)
            or isinstance(self.prompt_bytes, bool)
            or self.prompt_bytes <= 0
        ):
            raise ValueError("action prompt_bytes must be a positive integer")
        object.__setattr__(self, "slot_id", slot_id)
        object.__setattr__(self, "prompt_hash", prompt_hash)
        object.__setattr__(self, "prompt_bytes", self.prompt_bytes)

    def to_payload(self) -> dict[str, str]:
        payload = {
            "schema_version": str(self.schema_version),
            "type": self.type,
            "prompt_file": self.prompt_file,
            "response_file": self.response_file,
            "slot_id": self.slot_id,
            "prompt_hash": self.prompt_hash,
            "prompt_bytes": str(self.prompt_bytes),
            "interface": self.interface,
        }
        _validate_action_block_payload(payload)
        return {field: payload[field] for field in ACTION_BLOCK_FIELDS}

    def to_lines(self) -> list[str]:
        payload = self.to_payload()
        return [f"{field}: {payload[field]}" for field in ACTION_BLOCK_FIELDS]

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> "FileExchangeAction":
        payload: dict[str, str] = {}
        for line in lines:
            if ": " not in line:
                raise ValueError(f"invalid action block line: {line}")
            key, value = line.split(": ", 1)
            if key in payload:
                raise ValueError(f"duplicate action block field: {key}")
            if key in ACTION_BLOCK_FORBIDDEN_CREDENTIAL_FIELDS:
                raise ValueError(
                    "action block must not include credential field(s): "
                    f"{key}"
                )
            if key in ACTION_BLOCK_FORBIDDEN_EXECUTION_CLAIM_FIELDS:
                raise ValueError(
                    "action block must not include execution claim field(s): "
                    f"{key}"
                )
            if key in ACTION_BLOCK_FORBIDDEN_CROSS_CONTRACT_METADATA_FIELDS:
                raise ValueError(
                    "action block must not include cross-contract metadata field(s): "
                    f"{key}"
                )
            if key not in ACTION_BLOCK_FIELDS:
                raise ValueError(f"unknown action block field: {key}")
            payload[key] = value

        missing = [field for field in ACTION_BLOCK_FIELDS if field not in payload]
        if missing:
            raise ValueError(f"missing action block field(s): {', '.join(missing)}")
        if payload["schema_version"] != str(ACTION_BLOCK_SCHEMA_VERSION):
            raise ValueError(
                "unsupported action block schema_version: "
                f"{payload['schema_version']}"
            )
        try:
            prompt_bytes = int(payload["prompt_bytes"])
        except ValueError as exc:
            raise ValueError(
                f"invalid action block prompt_bytes: {payload['prompt_bytes']}"
            ) from exc
        if prompt_bytes <= 0 or payload["prompt_bytes"] != str(prompt_bytes):
            raise ValueError(
                f"invalid action block prompt_bytes: {payload['prompt_bytes']}"
            )
        try:
            action = cls(
                schema_version=ACTION_BLOCK_SCHEMA_VERSION,
                type=payload["type"],
                prompt_file=payload["prompt_file"],
                response_file=payload["response_file"],
                slot_id=payload["slot_id"],
                prompt_hash=payload["prompt_hash"],
                prompt_bytes=prompt_bytes,
                interface=payload["interface"],
            )
        except ValueError as exc:
            if str(exc).startswith("invalid action prompt_hash:"):
                raise ValueError(
                    "invalid action block prompt_hash: "
                    f"{payload['prompt_hash']}"
                ) from exc
            raise
        prompt_path = Path(action.prompt_file)
        expected_response_path = Path(action.response_file)
        if expected_response_path.exists():
            raise FileExistsError(
                f"action block response_file already exists: {expected_response_path}"
            )
        if not prompt_path.exists() or not prompt_path.is_file():
            raise FileNotFoundError(f"action block prompt_file not found: {prompt_path}")
        prompt_data = prompt_path.read_bytes()
        prompt_text = prompt_data.decode("utf-8-sig")
        if not prompt_text.strip():
            raise ValueError(f"action block prompt_file must be non-empty: {prompt_path}")
        prompt_evidence = content_evidence_from_bytes(prompt_data)
        if action.prompt_hash != prompt_evidence.content_hash:
            raise ValueError(
                "action block prompt_hash must match prompt_file: "
                f"expected {prompt_evidence.content_hash}, got {action.prompt_hash}"
            )
        if action.prompt_bytes != prompt_evidence.byte_count:
            raise ValueError(
                "action block prompt_bytes must match prompt_file: "
                f"expected {prompt_evidence.byte_count}, got {action.prompt_bytes}"
            )
        return action


def parse_file_exchange_action_block(output: str) -> FileExchangeAction:
    """Parse exactly one staged file-exchange action block from text output."""

    output = _require_non_empty_string(output, "AGENT_ACTION output")
    lines = output.splitlines()
    starts = [index for index, line in enumerate(lines) if line == "[AGENT_ACTION]"]
    ends = [index for index, line in enumerate(lines) if line == "[/AGENT_ACTION]"]
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("expected exactly one AGENT_ACTION block")
    if ends[0] <= starts[0]:
        raise ValueError("invalid AGENT_ACTION block order")
    return FileExchangeAction.from_lines(lines[starts[0] + 1 : ends[0]])


class LLMInterface(ABC):
    """LLM call interface abstraction.

    Implementations:
    - FileExchangeInterface: staged prompt/response file exchange.
    - DirectAPIInterface: reserved direct provider interface.
    """

    @abstractmethod
    def call(self, prompt: str) -> str:
        """Send prompt text and return raw LLM response text."""

    @abstractmethod
    def name(self) -> str:
        """Return interface name."""


class FileExchangeInterface(LLMInterface):
    """Staged file exchange interface.

    This is the default v0 runtime. It writes a prompt file, prints a machine
    readable action block, waits for a response file, and returns its text.
    Existing prompt or response files are treated as prior-run evidence and
    fail instead of being deleted or overwritten.
    """

    def __init__(self, prompt_path: Path, response_path: Path, timeout: int = 300):
        prompt_path = Path(prompt_path)
        response_path = Path(response_path)
        expected_response_path = expected_staged_response_path(prompt_path)
        if response_path != expected_response_path:
            raise ValueError(
                f"response path must match prompt path: expected "
                f"{expected_response_path}, got {response_path}"
            )
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
            raise ValueError("timeout must be a non-negative integer")
        self.prompt_path = prompt_path
        self.response_path = response_path
        self.timeout = timeout

    def name(self) -> str:
        return ACTION_BLOCK_INTERFACE

    def call(self, prompt: str) -> str:
        import time

        if self.response_path.exists():
            raise ValueError(f"response file already exists: {self.response_path}")
        if self.prompt_path.exists():
            raise ValueError(f"prompt file already exists: {self.prompt_path}")

        prompt = _require_utf8_encodable_string(prompt, "prompt text")
        prompt_data = prompt.encode("utf-8")

        self.prompt_path.parent.mkdir(parents=True, exist_ok=True)

        with self.prompt_path.open("xb") as prompt_file:
            prompt_file.write(prompt_data)
        prompt_evidence = file_content_evidence(self.prompt_path)
        action = FileExchangeAction(
            schema_version=ACTION_BLOCK_SCHEMA_VERSION,
            type="LLM_CALL",
            prompt_file=str(self.prompt_path),
            response_file=str(self.response_path),
            slot_id=staged_slot_id(self.prompt_path),
            prompt_hash=prompt_evidence.content_hash,
            prompt_bytes=prompt_evidence.byte_count,
            interface=self.name(),
        )

        print(f"\n{'=' * 60}")
        print("[AGENT_ACTION]")
        for line in action.to_lines():
            print(line)
        print("[/AGENT_ACTION]")
        print(f"{'=' * 60}")

        start = time.time()
        print(f"[LLMInterface] Waiting for response (timeout: {self.timeout}s)...")
        while time.time() - start < self.timeout:
            if self.response_path.exists():
                response_data = self.response_path.read_bytes()
                response = response_data.decode("utf-8-sig")
                if response.strip():
                    response_evidence = content_evidence_from_bytes(response_data)
                    current_prompt_hash = file_content_hash(self.prompt_path)
                    if current_prompt_hash != prompt_evidence.content_hash:
                        raise ValueError(
                            f"prompt hash mismatch for {self.prompt_path}: "
                            f"expected {prompt_evidence.content_hash}, "
                            f"actual {current_prompt_hash}"
                        )
                    print(
                        "[LLMInterface] Response received "
                        f"({len(response)} chars, "
                        f"{response_evidence.byte_count} bytes)"
                    )
                    return response
            time.sleep(1)

        raise TimeoutError(
            f"[LLMInterface] Response not received within {self.timeout}s. "
            f"Expected response at: {self.response_path}"
        )


@dataclass(frozen=True)
class DirectAPIRequest:
    """Provider-agnostic DirectAPI call input."""

    prompt: str
    model: str

    def __post_init__(self) -> None:
        prompt = _require_utf8_encodable_string(
            self.prompt,
            "DirectAPIRequest prompt",
        )
        model = _require_identifier_string(self.model, "DirectAPIRequest model")
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "model", model)

    def to_payload(self) -> dict[str, object]:
        payload = {
            "schema_version": DIRECT_API_PAYLOAD_SCHEMA_VERSION,
            "type": DIRECT_API_REQUEST_TYPE,
            "prompt": self.prompt,
            "model": self.model,
        }
        DirectAPIRequest.from_payload(payload)
        return {field: payload[field] for field in DIRECT_API_REQUEST_PAYLOAD_FIELDS}

    @classmethod
    def from_payload(cls, payload: object) -> "DirectAPIRequest":
        payload = _require_payload_fields(
            payload,
            fields=DIRECT_API_REQUEST_PAYLOAD_FIELDS,
            label="DirectAPIRequest",
        )
        payload_type = _require_identifier_string(
            payload["type"],
            "DirectAPIRequest type",
        )
        if payload_type != DIRECT_API_REQUEST_TYPE:
            raise ValueError(f"unsupported DirectAPIRequest type: {payload_type}")
        return cls(prompt=payload["prompt"], model=payload["model"])


@dataclass(frozen=True)
class DirectAPIResponse:
    """Provider-agnostic DirectAPI call output."""

    text: str
    model: str

    def __post_init__(self) -> None:
        text = _require_utf8_encodable_string(
            self.text,
            "DirectAPIResponse text",
        )
        model = _require_identifier_string(self.model, "DirectAPIResponse model")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "model", model)

    def to_payload(self) -> dict[str, object]:
        payload = {
            "schema_version": DIRECT_API_PAYLOAD_SCHEMA_VERSION,
            "type": DIRECT_API_RESPONSE_TYPE,
            "text": self.text,
            "model": self.model,
        }
        DirectAPIResponse.from_payload(payload)
        return {field: payload[field] for field in DIRECT_API_RESPONSE_PAYLOAD_FIELDS}

    @classmethod
    def from_payload(cls, payload: object) -> "DirectAPIResponse":
        payload = _require_payload_fields(
            payload,
            fields=DIRECT_API_RESPONSE_PAYLOAD_FIELDS,
            label="DirectAPIResponse",
        )
        payload_type = _require_identifier_string(
            payload["type"],
            "DirectAPIResponse type",
        )
        if payload_type != DIRECT_API_RESPONSE_TYPE:
            raise ValueError(f"unsupported DirectAPIResponse type: {payload_type}")
        return cls(text=payload["text"], model=payload["model"])


class DirectAPIInterface(LLMInterface):
    """Direct API interface placeholder.

    DirectAPI may eventually replace only the manual response-file authoring
    step. It must still consume the same prompt text and return the same raw
    response text that staged files use. Workflow order, handoff validation,
    route validation, reminder validation, and serialization contracts remain
    outside this interface.

    No provider retry, fallback provider, or exception swallowing belongs here.
    Provider errors must surface to the caller.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "unconfigured-model",
        provider_call: Callable[[DirectAPIRequest], DirectAPIResponse] | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.provider_call = provider_call

    @property
    def api_key(self) -> str | None:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        self._api_key = _require_optional_identifier_string(
            value,
            "DirectAPI api_key",
        )

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = _require_identifier_string(value, "DirectAPI model")

    @property
    def provider_call(self) -> Callable[[DirectAPIRequest], DirectAPIResponse] | None:
        return self._provider_call

    @provider_call.setter
    def provider_call(
        self,
        value: Callable[[DirectAPIRequest], DirectAPIResponse] | None,
    ) -> None:
        if value is not None and not callable(value):
            raise TypeError("DirectAPI provider_call must be callable")
        self._provider_call = value

    def name(self) -> str:
        model = _require_identifier_string(self.model, "DirectAPI model")
        return f"DirectAPIInterface({model})"

    def call(self, prompt: str) -> str:
        prompt = _require_utf8_encodable_string(prompt, "DirectAPI prompt")
        request_model = _require_identifier_string(
            self.model,
            "DirectAPI model",
        )
        request_api_key = _require_optional_identifier_string(
            self.api_key,
            "DirectAPI api_key",
        )
        provider_call = self.provider_call
        if provider_call is None:
            raise NotImplementedError(
                "DirectAPIInterface has no provider adapter; "
                "FileExchangeInterface remains the default v0 runtime"
            )
        if not callable(provider_call):
            raise TypeError("DirectAPI provider_call must be callable")

        request = DirectAPIRequest(prompt=prompt, model=request_model)
        response = provider_call(request)
        if not isinstance(response, DirectAPIResponse):
            raise TypeError("DirectAPI provider must return DirectAPIResponse")
        response = DirectAPIResponse(text=response.text, model=response.model)
        if request.prompt != prompt:
            raise ValueError("DirectAPI request prompt changed during provider call")
        if request.model != request_model:
            raise ValueError("DirectAPI request model changed during provider call")
        current_model = _require_identifier_string(
            self.model,
            "DirectAPI model",
        )
        current_api_key = _require_optional_identifier_string(
            self.api_key,
            "DirectAPI api_key",
        )
        current_provider_call = self.provider_call
        if not callable(current_provider_call):
            raise TypeError("DirectAPI provider_call must be callable")
        if current_model != request_model:
            raise ValueError(
                "DirectAPI model changed during provider call: "
                f"expected {request_model}, got {current_model}"
            )
        if current_api_key != request_api_key:
            raise ValueError("DirectAPI api_key changed during provider call")
        if current_provider_call is not provider_call:
            raise ValueError("DirectAPI provider_call changed during provider call")
        if response.model != request_model:
            raise ValueError(
                f"DirectAPI response model mismatch: expected {request_model}, "
                f"got {response.model}"
            )
        return response.text
