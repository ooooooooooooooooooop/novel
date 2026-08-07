"""Staged response-file boundary tests."""

import ast
import hashlib
import inspect
from pathlib import Path
import textwrap

import pytest

from src.boundary_control.automation_contracts import (
    response_materialization_metadata,
    validate_response_materialization_metadata_in_payload,
)
from src.boundary_control.response_file import (
    CYCLE_RESPONSE_FILES,
    PendingResponseSlot,
    ResponseFileBoundaryUnit,
    reset_consumed_responses,
    StagedResponseRunner,
    StagedResponseResult,
)
from src.llm_interface import LLMInterface


class RecordingInterface(LLMInterface):
    def __init__(self, response: str = "response", error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[str] = []

    def call(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response

    def name(self) -> str:
        return "RecordingInterface"


def _valid_pending_response_slot(tmp_path, **overrides):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    payload = {
        "prompt_path": prompt_path,
        "response_path": tmp_path / "review_response.txt",
        "prompt_mtime": prompt_path.stat().st_mtime,
        "prompt_hash": hashlib.md5(b"prompt").hexdigest(),
        "prompt_bytes": len(b"prompt"),
        "slot_id": "review",
    }
    payload.update(overrides)
    return PendingResponseSlot(**payload)


def test_pending_response_slot_normalizes_pathlike_metadata(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    slot = _valid_pending_response_slot(
        tmp_path,
        prompt_path=str(prompt_path),
        response_path=str(tmp_path / "review_response.txt"),
    )

    assert slot.prompt_path == prompt_path
    assert slot.response_path == tmp_path / "review_response.txt"
    assert slot.prompt_mtime == prompt_path.stat().st_mtime
    assert slot.prompt_bytes == len(b"prompt")


def test_pending_response_slot_rejects_response_path_mismatch(tmp_path):
    with pytest.raises(ValueError, match="response_path must match prompt_path"):
        _valid_pending_response_slot(
            tmp_path,
            response_path=tmp_path / "other_response.txt",
        )


def test_pending_response_slot_rejects_existing_response_file(tmp_path):
    response_path = tmp_path / "review_response.txt"
    response_path.write_text("completed response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="pending slot response file already exists"):
        _valid_pending_response_slot(tmp_path)


def test_pending_response_slot_rejects_relative_prompt_path(tmp_path):
    with pytest.raises(ValueError, match="pending slot prompt_path must be absolute"):
        _valid_pending_response_slot(
            tmp_path,
            prompt_path=Path("review_prompt.txt"),
            response_path=tmp_path / "review_response.txt",
        )


def test_pending_response_slot_rejects_relative_response_path(tmp_path):
    with pytest.raises(ValueError, match="pending slot response_path must be absolute"):
        _valid_pending_response_slot(
            tmp_path,
            response_path=Path("review_response.txt"),
        )


def test_pending_response_slot_rejects_slot_id_mismatch(tmp_path):
    with pytest.raises(ValueError, match="slot_id must match prompt_path"):
        _valid_pending_response_slot(tmp_path, slot_id="continue")


def test_pending_response_slot_rejects_invalid_prompt_hash(tmp_path):
    with pytest.raises(ValueError, match="invalid pending slot prompt_hash"):
        _valid_pending_response_slot(tmp_path, prompt_hash="abc")


def test_pending_response_slot_rejects_prompt_hash_mismatch(tmp_path):
    with pytest.raises(ValueError, match="prompt_hash must match prompt file"):
        _valid_pending_response_slot(
            tmp_path,
            prompt_hash=hashlib.md5(b"other prompt").hexdigest(),
        )


@pytest.mark.parametrize("prompt_bytes", [0, -1, True, "6", 1.5])
def test_pending_response_slot_rejects_invalid_prompt_bytes(tmp_path, prompt_bytes):
    with pytest.raises(ValueError, match="prompt_bytes must be a positive integer"):
        _valid_pending_response_slot(tmp_path, prompt_bytes=prompt_bytes)


def test_pending_response_slot_rejects_prompt_bytes_mismatch(tmp_path):
    with pytest.raises(ValueError, match="prompt_bytes must match prompt file"):
        _valid_pending_response_slot(tmp_path, prompt_bytes=len(b"other prompt"))


def test_pending_response_slot_rejects_missing_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    _valid_pending_response_slot(tmp_path)
    prompt_path.unlink()

    with pytest.raises(FileNotFoundError):
        PendingResponseSlot(
            prompt_path=prompt_path,
            response_path=tmp_path / "review_response.txt",
            prompt_mtime=1_700_000_000,
            prompt_hash=hashlib.md5(b"prompt").hexdigest(),
            prompt_bytes=len(b"prompt"),
            slot_id="review",
        )


@pytest.mark.parametrize("prompt_mtime", [-1, True, "recent", float("nan"), float("inf")])
def test_pending_response_slot_rejects_invalid_prompt_mtime(tmp_path, prompt_mtime):
    with pytest.raises(
        ValueError,
        match="prompt_mtime must be a finite non-negative number",
    ):
        _valid_pending_response_slot(tmp_path, prompt_mtime=prompt_mtime)


def test_pending_response_slot_rejects_prompt_mtime_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt_mtime must match prompt file"):
        PendingResponseSlot(
            prompt_path=prompt_path,
            response_path=tmp_path / "review_response.txt",
            prompt_mtime=prompt_path.stat().st_mtime + 1,
            prompt_hash=hashlib.md5(b"prompt").hexdigest(),
            prompt_bytes=len(b"prompt"),
            slot_id="review",
        )


def test_runner_rejects_non_boundary_at_construction():
    with pytest.raises(TypeError, match="boundary must be a ResponseFileBoundaryUnit"):
        StagedResponseRunner(boundary=object())


def test_materialize_response_writes_matching_response_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    written = ResponseFileBoundaryUnit().materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text='{"route": "pass"}',
    )

    assert written == response_path
    assert response_path.read_text(encoding="utf-8") == '{"route": "pass"}'


def test_materialize_response_preserves_lf_response_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    written = ResponseFileBoundaryUnit().materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text="line1\nline2",
    )

    assert written == response_path
    assert response_path.read_bytes() == b"line1\nline2"


def test_materialize_response_preserves_crlf_and_surrounding_whitespace(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    written = ResponseFileBoundaryUnit().materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text="  line1\r\nline2\r\n  ",
    )

    assert written == response_path
    assert response_path.read_bytes() == b"  line1\r\nline2\r\n  "


def test_materialize_response_accepts_matching_prompt_hash(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    written = ResponseFileBoundaryUnit().materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text="response",
        expected_prompt_hash=hashlib.md5(b"prompt").hexdigest(),
    )

    assert written == response_path
    assert response_path.read_text(encoding="utf-8") == "response"


def test_materialize_response_rejects_prompt_hash_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
            expected_prompt_hash=hashlib.md5(b"other prompt").hexdigest(),
        )

    assert not response_path.exists()


def test_materialize_response_rejects_invalid_expected_prompt_hash(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid expected_prompt_hash"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
            expected_prompt_hash="wrong-hash",
        )

    assert not response_path.exists()


def test_verify_prompt_hash_rejects_empty_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("  ", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        ResponseFileBoundaryUnit().verify_prompt_hash(prompt_path)


def test_verify_prompt_hash_rejects_bom_only_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_bytes(b"\xef\xbb\xbf")

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        ResponseFileBoundaryUnit().verify_prompt_hash(prompt_path)


def test_verify_prompt_hash_rejects_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        ResponseFileBoundaryUnit().verify_prompt_hash(prompt_path)


def test_verify_prompt_hash_requires_staged_prompt_name(tmp_path):
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="_prompt.txt"):
        ResponseFileBoundaryUnit().verify_prompt_hash(prompt_path)


def test_materialize_response_requires_existing_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"

    with pytest.raises(FileNotFoundError, match="prompt file not found"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


def test_materialize_response_rejects_relative_prompt_path_before_file_checks(tmp_path):
    response_path = tmp_path / "review_response.txt"

    with pytest.raises(ValueError, match="prompt_path must be absolute"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=Path("review_prompt.txt"),
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


def test_materialize_response_rejects_relative_response_path_before_writing(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="response_path must be absolute"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=Path("review_response.txt"),
            response_text="response",
        )

    assert not (tmp_path / "review_response.txt").exists()


def test_materialize_response_requires_non_empty_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("  ", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


def test_materialize_response_requires_prompt_naming_contract(tmp_path):
    prompt_path = tmp_path / "prompt.txt"
    response_path = tmp_path / "response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="_prompt.txt"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


def test_materialize_response_rejects_empty_slot_prompt_name(tmp_path):
    prompt_path = tmp_path / "_prompt.txt"
    response_path = tmp_path / "_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid prompt slot id"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


@pytest.mark.parametrize(
    "prompt_name",
    [
        " review_prompt.txt",
        "review_prompt.txt_prompt.txt",
        "review.v1_prompt.txt",
        "review v1_prompt.txt",
        "审查_prompt.txt",
    ],
)
def test_materialize_response_rejects_invalid_slot_prompt_name(tmp_path, prompt_name):
    prompt_path = tmp_path / prompt_name
    response_path = tmp_path / (
        prompt_name.removesuffix("_prompt.txt") + "_response.txt"
    )
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid prompt slot id"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert not response_path.exists()


def test_materialize_response_rejects_non_matching_response_path(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    wrong_response_path = tmp_path / "audit_report.json"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="response path must match prompt path"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=wrong_response_path,
            response_text="response",
        )

    assert not wrong_response_path.exists()


def test_materialize_response_refuses_to_overwrite_existing_response(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="new response",
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_materialize_response_existing_response_preempts_missing_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_materialize_response_existing_response_preempts_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_materialize_response_existing_response_preempts_invalid_expected_hash(
    tmp_path,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="response",
            expected_prompt_hash="wrong-hash",
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_materialize_response_existing_response_preempts_bad_response_text(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="\ud800",
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_materialize_response_uses_exclusive_create_after_slot_verification(tmp_path):
    class RacingBoundary(ResponseFileBoundaryUnit):
        def verify_response_slot(
            self,
            *,
            prompt_path,
            response_path,
            expected_prompt_hash=None,
        ):
            verified = super().verify_response_slot(
                prompt_path=prompt_path,
                response_path=response_path,
                expected_prompt_hash=expected_prompt_hash,
            )
            verified.write_text("raced response", encoding="utf-8")
            return verified

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(FileExistsError):
        RacingBoundary().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="new response",
        )

    assert response_path.read_text(encoding="utf-8") == "raced response"


def test_materialize_response_rejects_empty_response_text(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty string"):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="   ",
        )

    assert not response_path.exists()


def test_materialize_response_rejects_unencodable_response_before_creating_file(
    tmp_path,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="\ud800",
        )

    assert not response_path.exists()


def test_materialize_response_invalid_prompt_bytes_preempt_bad_response_text(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        ResponseFileBoundaryUnit().materialize_response(
            prompt_path=prompt_path,
            response_path=response_path,
            response_text="\ud800",
        )

    assert not response_path.exists()


def test_runner_calls_interface_and_materializes_raw_response(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface(response="not json but raw response")

    written = StagedResponseRunner().call_and_materialize(
        prompt_path=prompt_path,
        response_path=response_path,
        interface=interface,
    )

    assert written == response_path
    assert interface.calls == ["prompt text"]
    assert response_path.read_text(encoding="utf-8") == "not json but raw response"


def test_runner_result_reports_prompt_response_and_interface_evidence(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface(response="raw response")

    result = StagedResponseRunner().call_and_materialize_result(
        prompt_path=prompt_path,
        response_path=response_path,
        interface=interface,
    )

    assert result == StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    )
    assert interface.calls == ["prompt text"]
    assert response_path.read_text(encoding="utf-8") == "raw response"


def test_runner_rejects_interface_name_mutation_during_provider_call(tmp_path):
    class MutatingNameInterface(LLMInterface):
        def __init__(self):
            self.interface_name = "InitialInterface"
            self.calls: list[str] = []

        def call(self, prompt: str) -> str:
            self.calls.append(prompt)
            self.interface_name = "ChangedInterface"
            return "response"

        def name(self) -> str:
            return self.interface_name

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = MutatingNameInterface()

    with pytest.raises(ValueError, match="interface name changed"):
        StagedResponseRunner().call_and_materialize_result(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == ["prompt text"]
    assert not response_path.exists()


def test_staged_response_result_payload_is_machine_readable_without_response_text(
    tmp_path,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")

    result = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    )

    payload = result.to_payload()

    assert payload == {
        "schema_version": 1,
        "type": "STAGED_RESPONSE_RESULT",
        **response_materialization_metadata(),
        "prompt_file": "review_prompt.txt",
        "response_file": "review_response.txt",
        "prompt_path": str(prompt_path),
        "response_path": str(response_path),
        "slot_id": "review",
        "interface_name": "RecordingInterface",
        "prompt_hash": hashlib.md5(b"prompt text").hexdigest(),
        "prompt_bytes": len(b"prompt text"),
        "response_hash": hashlib.md5(b"raw response").hexdigest(),
        "response_bytes": len(b"raw response"),
        "response_chars": len("raw response"),
    }
    assert "response_text" not in payload
    assert "raw response" not in payload.values()


def test_staged_response_result_to_payload_revalidates_before_returning(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    result = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    )
    object.__setattr__(result, "response_hash", hashlib.md5(b"other").hexdigest())

    with pytest.raises(ValueError, match="response_hash must match response file"):
        result.to_payload()


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("prompt_bytes", "prompt_bytes must be a positive integer"),
        ("response_bytes", "response_bytes must be a positive integer"),
        ("response_chars", "response_chars must be a positive integer"),
    ],
)
def test_staged_response_result_to_payload_revalidates_positive_count_metadata(
    tmp_path,
    field,
    message,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    result = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    )
    object.__setattr__(result, field, 0)

    with pytest.raises(ValueError, match=message):
        result.to_payload()


def test_staged_response_result_roundtrips_from_payload(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    result = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    )

    parsed = StagedResponseResult.from_payload(result.to_payload())

    assert parsed == result

    old_payload = result.to_payload()
    del old_payload["materialization_contract"]
    with pytest.raises(
        ValueError,
        match="missing staged response result payload field",
    ):
        StagedResponseResult.from_payload(old_payload)

    provider_payload = result.to_payload()
    provider_payload["provider_call_performed"] = True
    with pytest.raises(ValueError, match="provider_call_performed"):
        StagedResponseResult.from_payload(provider_payload)
    with pytest.raises(ValueError, match="provider_call_performed"):
        validate_response_materialization_metadata_in_payload(provider_payload)


@pytest.mark.parametrize(
    "interface_name",
    [" RecordingInterface", "Recording Interface", "Recording\tInterface"],
)
def test_staged_response_result_payload_rejects_whitespace_interface_name(
    tmp_path,
    interface_name,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["interface_name"] = interface_name

    with pytest.raises(ValueError, match="interface_name must not contain whitespace"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_response_text_field(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["adapter_note"] = "raw response"

    with pytest.raises(ValueError, match="unknown staged response result payload"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_content_fields(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()

    for field in ("prompt", "response_text", "text", "model"):
        content_payload = dict(payload)
        content_payload[field] = "raw content"
        with pytest.raises(ValueError, match="prompt or response content field"):
            StagedResponseResult.from_payload(content_payload)


def test_staged_response_result_payload_rejects_pollution_fields(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()

    credential_payload = dict(payload)
    credential_payload["api_key"] = "key-a"
    with pytest.raises(ValueError, match="credential field"):
        StagedResponseResult.from_payload(credential_payload)

    execution_payload = dict(payload)
    execution_payload["retry"] = True
    with pytest.raises(ValueError, match="execution claim field"):
        StagedResponseResult.from_payload(execution_payload)

    pending_metadata_payload = dict(payload)
    pending_metadata_payload["automation_ready"] = True
    with pytest.raises(ValueError, match="pending automation metadata field"):
        StagedResponseResult.from_payload(pending_metadata_payload)


def test_staged_response_result_payload_rejects_non_string_keys(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="staged response result payload keys"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_non_string_prompt_path(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["prompt_path"] = object()

    with pytest.raises(ValueError, match="payload prompt_path"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_relative_prompt_path(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["prompt_path"] = "review_prompt.txt"

    with pytest.raises(ValueError, match="prompt_path must be absolute"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_relative_response_path(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["response_path"] = "review_response.txt"

    with pytest.raises(ValueError, match="response_path must be absolute"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_blank_response_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["response_file"] = " "

    with pytest.raises(ValueError, match="payload response_file"):
        StagedResponseResult.from_payload(payload)


def test_staged_response_result_payload_rejects_prompt_file_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = StagedResponseResult(
        prompt_path=prompt_path,
        response_path=response_path,
        slot_id="review",
        interface_name="RecordingInterface",
        prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
        prompt_bytes=len(b"prompt text"),
        response_hash=hashlib.md5(b"raw response").hexdigest(),
        response_bytes=len(b"raw response"),
        response_chars=len("raw response"),
    ).to_payload()
    payload["prompt_file"] = "other_prompt.txt"

    with pytest.raises(ValueError, match="prompt_file must match prompt_path"):
        StagedResponseResult.from_payload(payload)


def test_runner_single_pending_result_reports_slot_evidence(tmp_path):
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    prompt_path = output_dir / "continue_prompt.txt"
    prompt_path.write_text("continue prompt", encoding="utf-8")
    response_path = output_dir / "continue_response.txt"
    interface = RecordingInterface(response="continued text")

    result = StagedResponseRunner().call_single_pending_result(
        output_dir=output_dir,
        interface=interface,
    )

    assert result.prompt_path == prompt_path
    assert result.response_path == response_path
    assert result.slot_id == "continue"
    assert result.interface_name == "RecordingInterface"
    assert result.prompt_hash == hashlib.md5(b"continue prompt").hexdigest()
    assert result.response_hash == hashlib.md5(b"continued text").hexdigest()
    assert interface.calls == ["continue prompt"]
    assert response_path.read_text(encoding="utf-8") == "continued text"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("prompt_bytes", "prompt_bytes must be a positive integer"),
        ("response_bytes", "response_bytes must be a positive integer"),
        ("response_chars", "response_chars must be a positive integer"),
    ],
)
def test_staged_response_result_rejects_zero_count_metadata(
    tmp_path,
    field,
    message,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")
    payload = {
        "prompt_path": prompt_path,
        "response_path": response_path,
        "slot_id": "review",
        "interface_name": "RecordingInterface",
        "prompt_hash": hashlib.md5(b"prompt text").hexdigest(),
        "prompt_bytes": len(b"prompt text"),
        "response_hash": hashlib.md5(b"raw response").hexdigest(),
        "response_bytes": len(b"raw response"),
        "response_chars": len("raw response"),
    }
    payload[field] = 0

    with pytest.raises(ValueError, match=message):
        StagedResponseResult(**payload)


def test_staged_response_result_rejects_relative_prompt_path(tmp_path):
    with pytest.raises(ValueError, match="prompt_path must be absolute"):
        StagedResponseResult(
            prompt_path=Path("review_prompt.txt"),
            response_path=Path("review_response.txt"),
            slot_id="review",
            interface_name="RecordingInterface",
            prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"raw response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=len("raw response"),
        )


def test_staged_response_result_rejects_relative_response_path(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"

    with pytest.raises(ValueError, match="response_path must be absolute"):
        StagedResponseResult(
            prompt_path=prompt_path,
            response_path=Path("review_response.txt"),
            slot_id="review",
            interface_name="RecordingInterface",
            prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"raw response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=len("raw response"),
        )


@pytest.mark.parametrize(
    "interface_name",
    [" RecordingInterface", "Recording Interface", "Recording\tInterface"],
)
def test_staged_response_result_rejects_whitespace_interface_name(
    tmp_path,
    interface_name,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")

    with pytest.raises(ValueError, match="interface_name must not contain whitespace"):
        StagedResponseResult(
            prompt_path=prompt_path,
            response_path=response_path,
            slot_id="review",
            interface_name=interface_name,
            prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"raw response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=len("raw response"),
        )


def test_staged_response_result_rejects_prompt_hash_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt_hash must match prompt file"):
        StagedResponseResult(
            prompt_path=prompt_path,
            response_path=response_path,
            slot_id="review",
            interface_name="RecordingInterface",
            prompt_hash=hashlib.md5(b"other prompt").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"raw response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=len("raw response"),
        )


def test_staged_response_result_rejects_response_hash_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")

    with pytest.raises(ValueError, match="response_hash must match response file"):
        StagedResponseResult(
            prompt_path=prompt_path,
            response_path=response_path,
            slot_id="review",
            interface_name="RecordingInterface",
            prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"other response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=len("raw response"),
        )


def test_staged_response_result_rejects_response_chars_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("raw response", encoding="utf-8")

    with pytest.raises(ValueError, match="response_chars must match response file"):
        StagedResponseResult(
            prompt_path=prompt_path,
            response_path=response_path,
            slot_id="review",
            interface_name="RecordingInterface",
            prompt_hash=hashlib.md5(b"prompt text").hexdigest(),
            prompt_bytes=len(b"prompt text"),
            response_hash=hashlib.md5(b"raw response").hexdigest(),
            response_bytes=len(b"raw response"),
            response_chars=1,
        )


def test_runner_rejects_empty_interface_name_before_calling_provider(tmp_path):
    class EmptyNameInterface(RecordingInterface):
        def name(self) -> str:
            return " "

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = EmptyNameInterface()

    with pytest.raises(ValueError, match="interface name"):
        StagedResponseRunner().call_and_materialize_result(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


@pytest.mark.parametrize("interface_name", ["Recording Interface", "Recording\tInterface"])
def test_runner_rejects_whitespace_interface_name_before_calling_provider(
    tmp_path,
    interface_name,
):
    class WhitespaceNameInterface(RecordingInterface):
        def name(self) -> str:
            return interface_name

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = WhitespaceNameInterface()

    with pytest.raises(ValueError, match="interface name must not contain whitespace"):
        StagedResponseRunner().call_and_materialize_result(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_does_not_parse_routes_retry_or_write_artifacts():
    source = textwrap.dedent(inspect.getsource(StagedResponseRunner))
    tree = ast.parse(source)
    banned_names = {
        "json",
        "HandoffPacket",
        "HandoffBoundaryUnit",
        "NextRoute",
        "ReviewUnit",
        "ContinueUnit",
        "RewriteUnit",
        "RebuildUnit",
        "AuditReport",
    }
    banned_calls = {
        "loads",
        "dumps",
        "model_validate_json",
        "parse_response",
        "parse_file_exchange_action_block",
        "write_text",
        "write_bytes",
        "open",
        "sleep",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in banned_names
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in banned_calls
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned_calls


def test_runner_rejects_bad_slot_before_calling_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    wrong_response_path = tmp_path / "review_result.json"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="response path must match prompt path"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=wrong_response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not wrong_response_path.exists()


def test_runner_rejects_relative_prompt_path_before_calling_interface(tmp_path):
    response_path = tmp_path / "review_response.txt"
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="prompt_path must be absolute"):
        StagedResponseRunner().call_and_materialize_result(
            prompt_path=Path("review_prompt.txt"),
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_rejects_relative_response_path_before_calling_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="response_path must be absolute"):
        StagedResponseRunner().call_and_materialize_result(
            prompt_path=prompt_path,
            response_path=Path("review_response.txt"),
            interface=interface,
        )

    assert interface.calls == []
    assert not (tmp_path / "review_response.txt").exists()


def test_runner_rejects_non_llm_interface_before_writing_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")

    with pytest.raises(TypeError, match="interface must be an LLMInterface"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=object(),
        )

    assert not response_path.exists()


def test_runner_refuses_existing_response_before_rejecting_non_llm_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("old response", encoding="utf-8")

    with pytest.raises(FileExistsError, match="response file already exists"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=object(),
        )

    assert response_path.read_text(encoding="utf-8") == "old response"


def test_runner_rejects_prompt_hash_mismatch_before_calling_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
            expected_prompt_hash=hashlib.md5(b"other prompt").hexdigest(),
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_rejects_empty_prompt_after_slot_verification_before_calling_interface(
    tmp_path,
):
    class MutatingBoundary(ResponseFileBoundaryUnit):
        def verify_response_slot(
            self,
            *,
            prompt_path,
            response_path,
            expected_prompt_hash=None,
        ):
            verified = super().verify_response_slot(
                prompt_path=prompt_path,
                response_path=response_path,
                expected_prompt_hash=expected_prompt_hash,
            )
            prompt_path.write_text("   ", encoding="utf-8")
            return verified

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        StagedResponseRunner(boundary=MutatingBoundary()).call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_rejects_invalid_prompt_bytes_before_calling_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")
    interface = RecordingInterface()

    with pytest.raises(UnicodeDecodeError):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_rejects_invalid_prompt_bytes_before_non_llm_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=object(),
        )

    assert not response_path.exists()


def test_runner_refuses_existing_response_before_calling_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    response_path.write_text("old response", encoding="utf-8")
    interface = RecordingInterface(response="new response")

    with pytest.raises(FileExistsError, match="response file already exists"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == []
    assert response_path.read_text(encoding="utf-8") == "old response"


def test_runner_provider_error_surfaces_without_writing_response(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    error = RuntimeError("provider failed")
    interface = RecordingInterface(error=error)

    with pytest.raises(RuntimeError) as excinfo:
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert excinfo.value is error
    assert interface.calls == ["prompt text"]
    assert not response_path.exists()


def test_runner_refuses_to_write_if_prompt_changes_after_provider_call(tmp_path):
    class MutatingInterface(LLMInterface):
        def __init__(self, prompt_to_mutate):
            self.prompt_to_mutate = prompt_to_mutate
            self.calls: list[str] = []

        def call(self, prompt: str) -> str:
            self.calls.append(prompt)
            self.prompt_to_mutate.write_text("changed prompt", encoding="utf-8")
            return "response for old prompt"

        def name(self) -> str:
            return "MutatingInterface"

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = MutatingInterface(prompt_path)

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == ["prompt text"]
    assert not response_path.exists()


def test_runner_refuses_response_file_created_during_provider_call(tmp_path):
    class RacingInterface(LLMInterface):
        def __init__(self, response_to_create):
            self.response_to_create = response_to_create
            self.calls: list[str] = []

        def call(self, prompt: str) -> str:
            self.calls.append(prompt)
            self.response_to_create.write_text("racing response", encoding="utf-8")
            return "provider response"

        def name(self) -> str:
            return "RacingInterface"

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RacingInterface(response_path)

    with pytest.raises(FileExistsError, match="response file already exists"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == ["prompt text"]
    assert response_path.read_text(encoding="utf-8") == "racing response"


def test_runner_rejects_empty_interface_response_without_writing_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface(response=" ")

    with pytest.raises(ValueError, match="non-empty string"):
        StagedResponseRunner().call_and_materialize(
            prompt_path=prompt_path,
            response_path=response_path,
            interface=interface,
        )

    assert interface.calls == ["prompt text"]
    assert not response_path.exists()


def test_runner_calls_single_pending_slot_and_materializes_response(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface(response="raw response")

    written = StagedResponseRunner().call_single_pending(
        output_dir=tmp_path,
        interface=interface,
    )

    assert written == response_path
    assert interface.calls == ["prompt text"]
    assert response_path.read_text(encoding="utf-8") == "raw response"


def test_runner_single_pending_refuses_multiple_slots_without_calling_interface(tmp_path):
    (tmp_path / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="multiple pending response slots"):
        StagedResponseRunner().call_single_pending(
            output_dir=tmp_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not (tmp_path / "continue_response.txt").exists()
    assert not (tmp_path / "review_response.txt").exists()


def test_runner_single_pending_refuses_no_slot_before_non_llm_interface(tmp_path):
    with pytest.raises(ValueError, match="no pending response slot"):
        StagedResponseRunner().call_single_pending(
            output_dir=tmp_path,
            interface=object(),
        )


def test_runner_single_pending_rejects_prompt_change_after_discovery(tmp_path):
    class MutatingBoundary(ResponseFileBoundaryUnit):
        def require_single_pending_slot(self, output_dir, *, newer_than=None):
            slot = super().require_single_pending_slot(
                output_dir,
                newer_than=newer_than,
            )
            slot.prompt_path.write_text("changed prompt", encoding="utf-8")
            return slot

    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("original prompt", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        StagedResponseRunner(boundary=MutatingBoundary()).call_single_pending(
            output_dir=tmp_path,
            interface=interface,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_single_pending_rejects_invalid_newer_than_before_call(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(
        ValueError,
        match="newer_than must be a finite non-negative number",
    ):
        StagedResponseRunner().call_single_pending(
            output_dir=tmp_path,
            interface=interface,
            newer_than=True,
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_single_pending_rejects_invalid_expected_prompt_hash_before_call(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt text", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="invalid expected_prompt_hash"):
        StagedResponseRunner().call_single_pending(
            output_dir=tmp_path,
            interface=interface,
            expected_prompt_hash="",
        )

    assert interface.calls == []
    assert not response_path.exists()


def test_runner_call_pending_slot_targets_named_slot(tmp_path):
    (tmp_path / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")
    interface = RecordingInterface(response="review response")

    written = StagedResponseRunner().call_pending_slot(
        output_dir=tmp_path,
        slot_id="review",
        interface=interface,
    )

    assert written == tmp_path / "review_response.txt"
    assert interface.calls == ["review"]
    assert not (tmp_path / "continue_response.txt").exists()
    assert (tmp_path / "review_response.txt").read_text(encoding="utf-8") == (
        "review response"
    )


def test_runner_call_pending_slot_rejects_missing_slot_before_call(tmp_path):
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="pending response slot not found"):
        StagedResponseRunner().call_pending_slot(
            output_dir=tmp_path,
            slot_id="continue",
            interface=interface,
        )

    assert interface.calls == []
    assert not (tmp_path / "review_response.txt").exists()


def test_runner_call_pending_slot_rejects_missing_slot_before_non_llm_interface(
    tmp_path,
):
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="pending response slot not found"):
        StagedResponseRunner().call_pending_slot(
            output_dir=tmp_path,
            slot_id="continue",
            interface=object(),
        )

    assert not (tmp_path / "review_response.txt").exists()


def test_runner_call_pending_slot_ignores_completed_invalid_prompt_bytes(tmp_path):
    (tmp_path / "review_prompt.txt").write_bytes(b"\xff")
    (tmp_path / "review_response.txt").write_text("done", encoding="utf-8")

    with pytest.raises(ValueError, match="pending response slot not found"):
        StagedResponseRunner().call_pending_slot(
            output_dir=tmp_path,
            slot_id="review",
            interface=object(),
        )

    assert (tmp_path / "review_response.txt").read_text(encoding="utf-8") == "done"


def test_discover_pending_slots_requires_output_dir(tmp_path):
    missing_dir = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="output directory not found"):
        ResponseFileBoundaryUnit().discover_pending_slots(missing_dir)


def test_discover_pending_slots_rejects_relative_output_dir():
    with pytest.raises(ValueError, match="output directory must be absolute"):
        ResponseFileBoundaryUnit().discover_pending_slots(Path("run"))


def test_runner_single_pending_rejects_relative_output_dir_before_calling_interface():
    interface = RecordingInterface()

    with pytest.raises(ValueError, match="output directory must be absolute"):
        StagedResponseRunner().call_single_pending(
            output_dir=Path("run"),
            interface=interface,
        )

    assert interface.calls == []


def test_discover_pending_slots_skips_completed_prompts(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    response_path.write_text("response", encoding="utf-8")

    assert ResponseFileBoundaryUnit().discover_pending_slots(tmp_path) == []


def test_discover_pending_slots_skips_completed_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")
    response_path.write_text("response", encoding="utf-8")

    assert ResponseFileBoundaryUnit().discover_pending_slots(tmp_path) == []


def test_require_single_pending_slot_ignores_completed_invalid_prompt_bytes(tmp_path):
    completed_prompt = tmp_path / "review_prompt.txt"
    completed_response = tmp_path / "review_response.txt"
    pending_prompt = tmp_path / "continue_prompt.txt"
    completed_prompt.write_bytes(b"\xff")
    completed_response.write_text("response", encoding="utf-8")
    pending_prompt.write_text("continue", encoding="utf-8")

    slot = ResponseFileBoundaryUnit().require_single_pending_slot(tmp_path)

    assert slot.prompt_path == pending_prompt
    assert slot.response_path == tmp_path / "continue_response.txt"
    assert slot.slot_id == "continue"


def test_discover_pending_slots_rejects_empty_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("  ", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        ResponseFileBoundaryUnit().discover_pending_slots(tmp_path)

    assert not (tmp_path / "review_response.txt").exists()


def test_discover_pending_slots_rejects_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        ResponseFileBoundaryUnit().discover_pending_slots(tmp_path)

    assert not (tmp_path / "review_response.txt").exists()


def test_discover_pending_slots_rejects_empty_slot_prompt_name(tmp_path):
    prompt_path = tmp_path / "_prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid prompt slot id"):
        ResponseFileBoundaryUnit().discover_pending_slots(tmp_path)

    assert not (tmp_path / "_response.txt").exists()


@pytest.mark.parametrize(
    "prompt_name",
    [
        " review_prompt.txt",
        "review_prompt.txt_prompt.txt",
        "review.v1_prompt.txt",
        "review v1_prompt.txt",
        "审查_prompt.txt",
    ],
)
def test_discover_pending_slots_rejects_invalid_slot_prompt_name(tmp_path, prompt_name):
    prompt_path = tmp_path / prompt_name
    prompt_path.write_text("prompt", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid prompt slot id"):
        ResponseFileBoundaryUnit().discover_pending_slots(tmp_path)

    assert not (
        tmp_path / (prompt_name.removesuffix("_prompt.txt") + "_response.txt")
    ).exists()


def test_discover_pending_slots_returns_sorted_matching_slots(tmp_path):
    second_prompt = tmp_path / "review_prompt.txt"
    first_prompt = tmp_path / "continue_prompt.txt"
    second_prompt.write_text("second", encoding="utf-8")
    first_prompt.write_text("first", encoding="utf-8")
    first_time = 1_700_000_000
    second_time = 1_700_000_100
    first_response = tmp_path / "continue_response.txt"
    second_response = tmp_path / "review_response.txt"

    import os

    os.utime(first_prompt, (first_time, first_time))
    os.utime(second_prompt, (second_time, second_time))

    slots = ResponseFileBoundaryUnit().discover_pending_slots(tmp_path)

    assert [slot.prompt_path for slot in slots] == [first_prompt, second_prompt]
    assert [slot.response_path for slot in slots] == [first_response, second_response]
    assert [slot.prompt_mtime for slot in slots] == [first_time, second_time]
    assert [slot.prompt_hash for slot in slots] == [
        hashlib.md5(b"first").hexdigest(),
        hashlib.md5(b"second").hexdigest(),
    ]
    assert [slot.prompt_bytes for slot in slots] == [
        len(b"first"),
        len(b"second"),
    ]
    assert [slot.slot_id for slot in slots] == ["continue", "review"]


def test_discover_pending_slots_honors_newer_than_filter(tmp_path):
    old_prompt = tmp_path / "continue_prompt.txt"
    new_prompt = tmp_path / "review_prompt.txt"
    old_prompt.write_text("old", encoding="utf-8")
    new_prompt.write_text("new", encoding="utf-8")

    import os

    os.utime(old_prompt, (1_700_000_000, 1_700_000_000))
    os.utime(new_prompt, (1_700_000_100, 1_700_000_100))

    slots = ResponseFileBoundaryUnit().discover_pending_slots(
        tmp_path,
        newer_than=1_700_000_050,
    )

    assert [slot.prompt_path for slot in slots] == [new_prompt]


@pytest.mark.parametrize("newer_than", ["recent", float("nan"), float("inf")])
def test_discover_pending_slots_rejects_invalid_newer_than(tmp_path, newer_than):
    with pytest.raises(
        ValueError,
        match="newer_than must be a finite non-negative number",
    ):
        ResponseFileBoundaryUnit().discover_pending_slots(
            tmp_path,
            newer_than=newer_than,
        )


def test_discover_pending_slots_rejects_negative_newer_than(tmp_path):
    with pytest.raises(
        ValueError,
        match="newer_than must be a finite non-negative number",
    ):
        ResponseFileBoundaryUnit().discover_pending_slots(
            tmp_path,
            newer_than=-1,
        )


def test_require_single_pending_slot_returns_only_slot(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("prompt", encoding="utf-8")

    slot = ResponseFileBoundaryUnit().require_single_pending_slot(tmp_path)

    assert slot.prompt_path == prompt_path
    assert slot.response_path == tmp_path / "review_response.txt"
    assert slot.slot_id == "review"


def test_require_single_pending_slot_fails_when_none_waiting(tmp_path):
    with pytest.raises(ValueError, match="no pending response slot"):
        ResponseFileBoundaryUnit().require_single_pending_slot(tmp_path)


def test_require_single_pending_slot_fails_when_multiple_waiting(tmp_path):
    (tmp_path / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="multiple pending response slots"):
        ResponseFileBoundaryUnit().require_single_pending_slot(tmp_path)


def test_require_pending_slot_returns_matching_slot_id(tmp_path):
    (tmp_path / "continue_prompt.txt").write_text("continue", encoding="utf-8")
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    slot = ResponseFileBoundaryUnit().require_pending_slot(
        tmp_path,
        slot_id="review",
    )

    assert slot.prompt_path == tmp_path / "review_prompt.txt"
    assert slot.response_path == tmp_path / "review_response.txt"
    assert slot.prompt_hash == hashlib.md5(b"review").hexdigest()
    assert slot.prompt_bytes == len(b"review")


def test_require_pending_slot_accepts_matching_expected_prompt_hash(tmp_path):
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    slot = ResponseFileBoundaryUnit().require_pending_slot(
        tmp_path,
        slot_id="review",
        expected_prompt_hash=hashlib.md5(b"review").hexdigest(),
    )

    assert slot.prompt_path == tmp_path / "review_prompt.txt"


def test_require_pending_slot_rejects_expected_prompt_hash_mismatch(tmp_path):
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        ResponseFileBoundaryUnit().require_pending_slot(
            tmp_path,
            slot_id="review",
            expected_prompt_hash=hashlib.md5(b"other").hexdigest(),
        )


def test_require_pending_slot_ignores_completed_invalid_prompt_bytes(tmp_path):
    (tmp_path / "review_prompt.txt").write_bytes(b"\xff")
    (tmp_path / "review_response.txt").write_text("done", encoding="utf-8")

    with pytest.raises(ValueError, match="pending response slot not found"):
        ResponseFileBoundaryUnit().require_pending_slot(
            tmp_path,
            slot_id="review",
        )


def test_require_pending_slot_rejects_stale_discovery_prompt_hash(tmp_path):
    class StaleDiscoveryBoundary(ResponseFileBoundaryUnit):
        def discover_pending_slots(self, output_dir, *, newer_than=None):
            prompt_path = output_dir / "review_prompt.txt"
            return [
                PendingResponseSlot(
                    prompt_path=prompt_path,
                    response_path=output_dir / "review_response.txt",
                    prompt_mtime=1_700_000_000,
                    prompt_hash=hashlib.md5(b"stale").hexdigest(),
                    prompt_bytes=len(b"stale"),
                    slot_id="review",
                )
            ]

    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("current", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt_hash must match prompt file"):
        StaleDiscoveryBoundary().require_pending_slot(
            tmp_path,
            slot_id="review",
        )


def test_require_pending_slot_rejects_empty_current_prompt_after_discovery(tmp_path):
    class StaleDiscoveryBoundary(ResponseFileBoundaryUnit):
        def discover_pending_slots(self, output_dir, *, newer_than=None):
            prompt_path = output_dir / "review_prompt.txt"
            return [
                PendingResponseSlot(
                    prompt_path=prompt_path,
                    response_path=output_dir / "review_response.txt",
                    prompt_mtime=1_700_000_000,
                    prompt_hash=hashlib.md5(b"stale").hexdigest(),
                    prompt_bytes=len(b"stale"),
                    slot_id="review",
                )
            ]

    prompt_path = tmp_path / "review_prompt.txt"
    prompt_path.write_text("   ", encoding="utf-8")

    with pytest.raises(ValueError, match="prompt file must be non-empty"):
        StaleDiscoveryBoundary().require_pending_slot(
            tmp_path,
            slot_id="review",
        )


def test_require_pending_slot_rejects_invalid_slot_id(tmp_path):
    (tmp_path / "review_prompt.txt").write_text("review", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid slot_id"):
        ResponseFileBoundaryUnit().require_pending_slot(
            tmp_path,
            slot_id="../review",
        )


# ---------------------------------------------------------------------------
# 章节周期响应清理（重跑已完成章不产生重复章节的回归防线）
# ---------------------------------------------------------------------------


def test_reset_consumed_responses_removes_cycle_files_keeps_rebuild(tmp_path):
    """清理本章已消费的 staged 响应，保留跨章的 rebuild_response.

    重跑已完成章时，若 continue/prose/review 响应被复用，会把当前章
    PlotUnit 逐字节重渲染成重复的下章文件——reset 是防这道 bug 的闸门。
    """
    (tmp_path / "rebuild_response.txt").write_text("rebuild", encoding="utf-8")
    (tmp_path / "outline_response.txt").write_text("outline", encoding="utf-8")
    for name in CYCLE_RESPONSE_FILES:
        (tmp_path / name).write_text("cycle", encoding="utf-8")

    removed = reset_consumed_responses(tmp_path)

    assert sorted(removed) == sorted(CYCLE_RESPONSE_FILES)
    for name in CYCLE_RESPONSE_FILES:
        assert not (tmp_path / name).exists()
    # 跨章输入解析的响应不受影响
    assert (tmp_path / "rebuild_response.txt").exists()
    assert (tmp_path / "outline_response.txt").exists()


def test_reset_consumed_responses_idempotent_when_absent(tmp_path):
    """空目录/已清理目录调用不报错，返回空列表."""
    assert reset_consumed_responses(tmp_path) == []
    assert reset_consumed_responses(tmp_path) == []


def test_cycle_response_files_exclude_cross_chapter_prompts():
    """周期响应清单不得包含跨章输入解析（rebuild/outline）的响应."""
    assert "rebuild_response.txt" not in CYCLE_RESPONSE_FILES
    assert "outline_response.txt" not in CYCLE_RESPONSE_FILES
    assert "continue_response.txt" in CYCLE_RESPONSE_FILES
    assert "prose_response.txt" in CYCLE_RESPONSE_FILES
    assert "review_response.txt" in CYCLE_RESPONSE_FILES
