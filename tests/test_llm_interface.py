"""LLM interface contract tests."""

import ast
import hashlib
import inspect
import textwrap

import pytest

from src.llm_interface import (
    DIRECT_API_REQUEST_PAYLOAD_FIELDS,
    DIRECT_API_RESPONSE_PAYLOAD_FIELDS,
    DirectAPIInterface,
    DirectAPIRequest,
    DirectAPIResponse,
    FileExchangeAction,
    FileExchangeInterface,
    parse_direct_api_payload,
    parse_file_exchange_action_block,
)


def test_file_exchange_refuses_existing_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("old prompt", encoding="utf-8")
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(ValueError, match="prompt file already exists"):
        interface.call("new prompt")

    assert prompt_path.read_text(encoding="utf-8") == "old prompt"
    assert not response_path.exists()


def test_file_exchange_existing_prompt_evidence_preempts_bad_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("old prompt", encoding="utf-8")
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(ValueError, match="prompt file already exists"):
        interface.call("\ud800")

    assert prompt_path.read_text(encoding="utf-8") == "old prompt"
    assert not response_path.exists()


def test_file_exchange_existing_response_evidence_preempts_bad_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    response_path.write_text("old response", encoding="utf-8")
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(ValueError, match="response file already exists"):
        interface.call("\ud800")

    assert not prompt_path.exists()
    assert response_path.read_text(encoding="utf-8") == "old response"


def test_file_exchange_requires_matching_response_path_before_writing_prompt(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    wrong_response_path = tmp_path / "audit_report.json"

    with pytest.raises(ValueError, match="response path must match prompt path"):
        FileExchangeInterface(prompt_path, wrong_response_path, timeout=0)

    assert not prompt_path.exists()
    assert not wrong_response_path.exists()


def test_file_exchange_rejects_empty_slot_prompt_path_at_construction(tmp_path):
    prompt_path = tmp_path / "_prompt.txt"
    response_path = tmp_path / "_response.txt"

    with pytest.raises(ValueError, match="invalid prompt slot id"):
        FileExchangeInterface(prompt_path, response_path, timeout=0)

    assert not prompt_path.exists()
    assert not response_path.exists()


def test_file_exchange_rejects_negative_timeout_at_construction(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"

    with pytest.raises(ValueError, match="timeout must be a non-negative integer"):
        FileExchangeInterface(prompt_path, response_path, timeout=-1)


def test_file_exchange_rejects_non_integer_timeout_at_construction(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"

    with pytest.raises(ValueError, match="timeout must be a non-negative integer"):
        FileExchangeInterface(prompt_path, response_path, timeout="1")


def test_file_exchange_rejects_empty_prompt_before_writing_files(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(ValueError, match="prompt text must be a non-empty string"):
        interface.call("  ")

    assert not prompt_path.exists()
    assert not response_path.exists()


def test_file_exchange_rejects_unencodable_prompt_before_creating_slot(tmp_path):
    output_dir = tmp_path / "run"
    prompt_path = output_dir / "review_prompt.txt"
    response_path = output_dir / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(UnicodeEncodeError):
        interface.call("\ud800")

    assert not output_dir.exists()
    assert not prompt_path.exists()
    assert not response_path.exists()


def test_file_exchange_action_block_includes_prompt_hash_and_bytes(tmp_path, capsys):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(TimeoutError, match="Response not received"):
        interface.call("new prompt")

    output = capsys.readouterr().out
    expected_hash = hashlib.md5(b"new prompt").hexdigest()
    expected_bytes = len(b"new prompt")
    action = parse_file_exchange_action_block(output)
    assert prompt_path.read_text(encoding="utf-8") == "new prompt"
    assert action.to_payload() == {
        "schema_version": "1",
        "type": "LLM_CALL",
        "prompt_file": str(prompt_path),
        "response_file": str(response_path),
        "slot_id": "review",
        "prompt_hash": expected_hash,
        "prompt_bytes": str(expected_bytes),
        "interface": "FileExchangeInterface",
    }
    assert not response_path.exists()


def _valid_file_exchange_action(**overrides):
    payload = {
        "schema_version": 1,
        "type": "LLM_CALL",
        "prompt_file": "review_prompt.txt",
        "response_file": "review_response.txt",
        "slot_id": "review",
        "prompt_hash": hashlib.md5(b"new prompt").hexdigest(),
        "prompt_bytes": len(b"new prompt"),
        "interface": "FileExchangeInterface",
    }
    payload.update(overrides)
    return FileExchangeAction(**payload)


def test_file_exchange_action_rejects_unsupported_schema_version():
    with pytest.raises(ValueError, match="unsupported action block schema_version"):
        _valid_file_exchange_action(schema_version=2)


def test_file_exchange_action_rejects_unsupported_type():
    with pytest.raises(ValueError, match="unsupported action block type"):
        _valid_file_exchange_action(type="OTHER_CALL")


def test_file_exchange_action_rejects_unsupported_interface():
    with pytest.raises(ValueError, match="unsupported action block interface"):
        _valid_file_exchange_action(interface="DirectAPIInterface(model)")


def test_file_exchange_action_rejects_non_staged_prompt_file():
    with pytest.raises(ValueError, match="_prompt.txt"):
        _valid_file_exchange_action(
            prompt_file="prompt.txt",
            response_file="response.txt",
        )


def test_file_exchange_action_rejects_response_file_mismatch():
    with pytest.raises(ValueError, match="response_file must match prompt_file"):
        _valid_file_exchange_action(response_file="other_response.txt")


def test_file_exchange_action_rejects_slot_id_mismatch():
    with pytest.raises(ValueError, match="slot_id must match prompt_file"):
        _valid_file_exchange_action(slot_id="continue")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("prompt_file", " ", "action prompt_file"),
        ("response_file", "", "action response_file"),
        ("slot_id", object(), "action slot_id"),
        ("slot_id", " review", "action slot_id"),
        ("slot_id", "review_prompt.txt", "action slot_id"),
        ("slot_id", "review_response.txt", "action slot_id"),
        ("slot_id", "review.v1", "action slot_id"),
        ("slot_id", "review v1", "action slot_id"),
        ("slot_id", "审查", "action slot_id"),
    ],
)
def test_file_exchange_action_rejects_empty_required_metadata(
    field,
    value,
    message,
):
    with pytest.raises(ValueError, match=message):
        _valid_file_exchange_action(**{field: value})


def test_file_exchange_action_rejects_invalid_prompt_hash():
    with pytest.raises(ValueError, match="invalid action prompt_hash"):
        _valid_file_exchange_action(prompt_hash="abc")


@pytest.mark.parametrize("prompt_bytes", [0, -1, True, "10", 1.5])
def test_file_exchange_action_rejects_invalid_prompt_bytes(prompt_bytes):
    with pytest.raises(ValueError, match="prompt_bytes must be a positive integer"):
        _valid_file_exchange_action(prompt_bytes=prompt_bytes)


def test_file_exchange_action_to_payload_revalidates_path_contract():
    action = object.__new__(FileExchangeAction)
    object.__setattr__(action, "schema_version", 1)
    object.__setattr__(action, "type", "LLM_CALL")
    object.__setattr__(action, "prompt_file", "review_prompt.txt")
    object.__setattr__(action, "response_file", "other_response.txt")
    object.__setattr__(action, "slot_id", "review")
    object.__setattr__(action, "prompt_hash", hashlib.md5(b"new prompt").hexdigest())
    object.__setattr__(action, "prompt_bytes", len(b"new prompt"))
    object.__setattr__(action, "interface", "FileExchangeInterface")

    with pytest.raises(
        ValueError,
        match="action block payload response_file must match prompt_file",
    ):
        action.to_payload()


def test_file_exchange_action_to_payload_revalidates_schema_version():
    action = _valid_file_exchange_action()
    object.__setattr__(action, "schema_version", 2)

    with pytest.raises(
        ValueError,
        match="unsupported action block payload schema_version",
    ):
        action.to_payload()


def test_file_exchange_action_to_payload_revalidates_type():
    action = _valid_file_exchange_action()
    object.__setattr__(action, "type", "OTHER_CALL")

    with pytest.raises(ValueError, match="unsupported action block payload type"):
        action.to_payload()


def test_file_exchange_action_to_payload_revalidates_interface():
    action = _valid_file_exchange_action()
    object.__setattr__(action, "interface", "DirectAPIInterface(model)")

    with pytest.raises(
        ValueError,
        match="unsupported action block payload interface",
    ):
        action.to_payload()


def test_file_exchange_action_to_payload_revalidates_prompt_bytes():
    action = _valid_file_exchange_action()
    object.__setattr__(action, "prompt_bytes", "010")

    with pytest.raises(ValueError, match="invalid action block payload prompt_bytes"):
        action.to_payload()


def test_parse_file_exchange_action_block_rejects_missing_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="missing action block field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_non_string_output():
    with pytest.raises(ValueError, match="AGENT_ACTION output"):
        parse_file_exchange_action_block(object())


def test_parse_file_exchange_action_block_rejects_blank_output():
    with pytest.raises(ValueError, match="AGENT_ACTION output"):
        parse_file_exchange_action_block("  ")


def test_parse_file_exchange_action_block_rejects_unknown_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "route: pass",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="unknown action block field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_credential_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "api_key: key-a",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="credential field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_execution_claim_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "fallback_provider: other",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="execution claim field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_cross_contract_metadata_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "automation_ready: true",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_schema_mismatch():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 2",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="unsupported action block schema_version"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_noncanonical_prompt_bytes():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 010",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="invalid action block prompt_bytes"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_zero_prompt_bytes():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 0",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="invalid action block prompt_bytes"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_duplicate_field():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="duplicate action block field"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_unsupported_type():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: OTHER_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="unsupported action block type"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_unsupported_interface(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            f"prompt_bytes: {len(b'prompt')}",
            "interface: DirectAPIInterface(model)",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="unsupported action block interface"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_multiple_blocks():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: continue_prompt.txt",
            "response_file: continue_response.txt",
            "slot_id: continue",
            "prompt_hash: def",
            "prompt_bytes: 8",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="expected exactly one AGENT_ACTION block"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_invalid_block_order():
    output = "\n".join(
        [
            "[/AGENT_ACTION]",
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
        ]
    )

    with pytest.raises(ValueError, match="invalid AGENT_ACTION block order"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_response_file_mismatch():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: other_response.txt",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="response_file must match prompt_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_slot_id_mismatch():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file: review_response.txt",
            "slot_id: continue",
            "prompt_hash: abc",
            "prompt_bytes: 10",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="slot_id must match prompt_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_blank_prompt_file():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file:  ",
            "response_file: review_response.txt",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            "prompt_bytes: 6",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="action prompt_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_blank_response_file():
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            "prompt_file: review_prompt.txt",
            "response_file:  ",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            "prompt_bytes: 6",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="action response_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_invalid_prompt_hash(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            "prompt_hash: abc",
            "prompt_bytes: 6",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="invalid action block prompt_hash"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            "prompt_bytes: many",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="invalid action block prompt_bytes"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_prompt_bytes_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            "prompt_bytes: 999",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="prompt_bytes must match prompt_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_missing_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            f"prompt_bytes: {len(b'prompt')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(FileNotFoundError, match="prompt_file not found"):
        parse_file_exchange_action_block(output)


def test_parse_action_block_existing_response_preempts_missing_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    response_path.write_text("existing response", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            f"prompt_bytes: {len(b'prompt')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(FileExistsError, match="response_file already exists"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_prompt_hash_mismatch(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("actual prompt", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'other prompt').hexdigest()}",
            f"prompt_bytes: {len(b'actual prompt')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="prompt_hash must match prompt_file"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_empty_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("  ", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'  ').hexdigest()}",
            f"prompt_bytes: {len(b'  ')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="prompt_file must be non-empty"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_bom_only_prompt_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    bom_bytes = b"\xef\xbb\xbf"
    prompt_path.write_bytes(bom_bytes)
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(bom_bytes).hexdigest()}",
            f"prompt_bytes: {len(bom_bytes)}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(ValueError, match="prompt_file must be non-empty"):
        parse_file_exchange_action_block(output)


def test_parse_file_exchange_action_block_rejects_existing_response_file(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_text("prompt", encoding="utf-8")
    response_path.write_text("existing response", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            f"prompt_bytes: {len(b'prompt')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(FileExistsError, match="response_file already exists"):
        parse_file_exchange_action_block(output)


def test_parse_action_block_existing_response_preempts_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_path.write_bytes(b"\xff")
    response_path.write_text("existing response", encoding="utf-8")
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(b'prompt').hexdigest()}",
            f"prompt_bytes: {len(b'prompt')}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(FileExistsError, match="response_file already exists"):
        parse_file_exchange_action_block(output)


def test_parse_pending_action_block_rejects_invalid_prompt_bytes(tmp_path):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    prompt_bytes = b"\xff"
    prompt_path.write_bytes(prompt_bytes)
    output = "\n".join(
        [
            "[AGENT_ACTION]",
            "schema_version: 1",
            "type: LLM_CALL",
            f"prompt_file: {prompt_path}",
            f"response_file: {response_path}",
            "slot_id: review",
            f"prompt_hash: {hashlib.md5(prompt_bytes).hexdigest()}",
            f"prompt_bytes: {len(prompt_bytes)}",
            "interface: FileExchangeInterface",
            "[/AGENT_ACTION]",
        ]
    )

    with pytest.raises(UnicodeDecodeError):
        parse_file_exchange_action_block(output)
    assert not response_path.exists()


def test_file_exchange_rejects_response_if_prompt_changes_while_waiting(
    tmp_path,
    monkeypatch,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=2)
    mutated = False

    def mutate_prompt_and_response(_seconds):
        nonlocal mutated
        if not mutated:
            prompt_path.write_text("changed prompt", encoding="utf-8")
            response_path.write_text("response for original prompt", encoding="utf-8")
            mutated = True

    monkeypatch.setattr("time.sleep", mutate_prompt_and_response)

    with pytest.raises(ValueError, match="prompt hash mismatch"):
        interface.call("original prompt")

    assert response_path.read_text(encoding="utf-8") == "response for original prompt"


def test_file_exchange_preserves_response_newline_bytes(tmp_path, monkeypatch):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=2)
    wrote_response = False

    def write_crlf_response(_seconds):
        nonlocal wrote_response
        if not wrote_response:
            response_path.write_bytes(b"line1\r\nline2")
            wrote_response = True

    monkeypatch.setattr("time.sleep", write_crlf_response)

    response = interface.call("prompt")

    assert response == "line1\r\nline2"
    assert response_path.read_bytes() == b"line1\r\nline2"


def test_file_exchange_treats_utf8_bom_as_response_encoding_marker(
    tmp_path,
    monkeypatch,
):
    prompt_path = tmp_path / "review_prompt.txt"
    response_path = tmp_path / "review_response.txt"
    interface = FileExchangeInterface(prompt_path, response_path, timeout=2)
    wrote_response = False

    def write_bom_response(_seconds):
        nonlocal wrote_response
        if not wrote_response:
            response_path.write_bytes(b"\xef\xbb\xbf" + b'{"route": "pass"}')
            wrote_response = True

    monkeypatch.setattr("time.sleep", write_bom_response)

    response = interface.call("prompt")

    assert response == '{"route": "pass"}'
    assert response_path.read_bytes() == b"\xef\xbb\xbf" + b'{"route": "pass"}'


def test_directapi_without_provider_remains_unimplemented():
    interface = DirectAPIInterface(model="contract-model")

    with pytest.raises(NotImplementedError, match="no provider adapter"):
        interface.call("prompt")


def test_directapi_without_provider_still_validates_unencodable_prompt_first():
    interface = DirectAPIInterface(model="contract-model")

    with pytest.raises(UnicodeEncodeError):
        interface.call("\ud800")


def test_directapi_rejects_empty_prompt_before_provider_call():
    called = False

    def provider(_request: DirectAPIRequest) -> DirectAPIResponse:
        nonlocal called
        called = True
        return DirectAPIResponse(text="response", model="contract-model")

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match="prompt must be a non-empty string"):
        interface.call("  ")
    assert called is False


def test_directapi_rejects_unencodable_prompt_before_provider_call():
    called = False

    def provider(_request: DirectAPIRequest) -> DirectAPIResponse:
        nonlocal called
        called = True
        return DirectAPIResponse(text="response", model="contract-model")

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(UnicodeEncodeError):
        interface.call("\ud800")
    assert called is False


def test_directapi_rejects_empty_model_at_construction():
    with pytest.raises(ValueError, match="model must be a non-empty string"):
        DirectAPIInterface(model="")


def test_directapi_rejects_unencodable_model_at_construction():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIInterface(model="\ud800")


def test_directapi_rejects_padded_model_at_construction():
    with pytest.raises(ValueError, match="model must not contain whitespace"):
        DirectAPIInterface(model=" contract-model ")


def test_directapi_rejects_whitespace_inside_model_at_construction():
    with pytest.raises(ValueError, match="model must not contain whitespace"):
        DirectAPIInterface(model="contract model")


def test_directapi_rejects_empty_api_key_at_construction():
    with pytest.raises(ValueError, match="api_key must be a non-empty string"):
        DirectAPIInterface(api_key="", model="contract-model")


def test_directapi_rejects_unencodable_api_key_at_construction():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIInterface(api_key="\ud800", model="contract-model")


def test_directapi_rejects_padded_api_key_at_construction():
    with pytest.raises(ValueError, match="api_key must not contain whitespace"):
        DirectAPIInterface(api_key=" key ", model="contract-model")


def test_directapi_rejects_whitespace_inside_api_key_at_construction():
    with pytest.raises(ValueError, match="api_key must not contain whitespace"):
        DirectAPIInterface(api_key="key value", model="contract-model")


def test_directapi_rejects_non_string_api_key_at_construction():
    with pytest.raises(ValueError, match="api_key must be a non-empty string"):
        DirectAPIInterface(api_key=object(), model="contract-model")


def test_directapi_rejects_non_callable_provider_at_construction():
    with pytest.raises(TypeError, match="provider_call must be callable"):
        DirectAPIInterface(
            model="contract-model",
            provider_call="not-callable",
        )


def test_directapi_name_uses_validated_model_identifier():
    interface = DirectAPIInterface(model="contract-model")

    assert interface.name() == "DirectAPIInterface(contract-model)"


def test_directapi_name_rejects_corrupted_model_snapshot():
    interface = DirectAPIInterface(model="contract-model")
    interface.__dict__["_model"] = "invalid model"

    with pytest.raises(ValueError, match="model must not contain whitespace"):
        interface.name()


def test_directapi_request_rejects_empty_prompt():
    with pytest.raises(ValueError, match="DirectAPIRequest prompt"):
        DirectAPIRequest(prompt=" ", model="contract-model")


def test_directapi_request_rejects_unencodable_prompt():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIRequest(prompt="\ud800", model="contract-model")


def test_directapi_request_rejects_empty_model():
    with pytest.raises(ValueError, match="DirectAPIRequest model"):
        DirectAPIRequest(prompt="prompt", model="")


def test_directapi_request_rejects_unencodable_model():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIRequest(prompt="prompt", model="\ud800")


def test_directapi_request_rejects_padded_model():
    with pytest.raises(
        ValueError,
        match="DirectAPIRequest model must not contain whitespace",
    ):
        DirectAPIRequest(prompt="prompt", model=" contract-model ")


def test_directapi_request_rejects_whitespace_inside_model():
    with pytest.raises(
        ValueError,
        match="DirectAPIRequest model must not contain whitespace",
    ):
        DirectAPIRequest(prompt="prompt", model="contract model")


def test_directapi_request_payload_roundtrips():
    request = DirectAPIRequest(prompt="prompt text", model="contract-model")

    payload = request.to_payload()

    assert tuple(payload) == DIRECT_API_REQUEST_PAYLOAD_FIELDS
    assert payload == {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": "contract-model",
    }
    assert DirectAPIRequest.from_payload(payload) == request


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("prompt", " ", "DirectAPIRequest prompt"),
        (
            "model",
            "bad model",
            "DirectAPIRequest model must not contain whitespace",
        ),
    ],
)
def test_directapi_request_to_payload_revalidates_before_return(
    field,
    value,
    message,
):
    request = object.__new__(DirectAPIRequest)
    object.__setattr__(request, "prompt", "prompt text")
    object.__setattr__(request, "model", "contract-model")
    object.__setattr__(request, field, value)

    with pytest.raises(ValueError, match=message):
        request.to_payload()


def test_directapi_request_payload_rejects_unknown_field():
    payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    payload["route"] = "pass"

    with pytest.raises(ValueError, match="unknown DirectAPIRequest payload"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_audit_payloads_reject_credential_fields_before_unknown_fields():
    request_payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    request_payload["api_key"] = "key-a"

    with pytest.raises(ValueError, match="credential field"):
        DirectAPIRequest.from_payload(request_payload)

    response_payload = DirectAPIResponse(
        text="raw response",
        model="contract-model",
    ).to_payload()
    response_payload["token"] = "provider-token"

    with pytest.raises(ValueError, match="credential field"):
        DirectAPIResponse.from_payload(response_payload)


def test_directapi_audit_payloads_reject_execution_claim_fields_before_unknown_fields():
    request_payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    request_payload["retry"] = True

    with pytest.raises(ValueError, match="execution claim field"):
        DirectAPIRequest.from_payload(request_payload)

    response_payload = DirectAPIResponse(
        text="raw response",
        model="contract-model",
    ).to_payload()
    response_payload["fallback_provider"] = "backup-model"

    with pytest.raises(ValueError, match="execution claim field"):
        DirectAPIResponse.from_payload(response_payload)


def test_directapi_audit_payloads_reject_cross_contract_metadata_fields():
    request_payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    request_payload["automation_ready"] = True

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        DirectAPIRequest.from_payload(request_payload)

    response_payload = DirectAPIResponse(
        text="raw response",
        model="contract-model",
    ).to_payload()
    response_payload["provider_call_performed"] = False

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        DirectAPIResponse.from_payload(response_payload)


def test_directapi_request_payload_rejects_non_string_keys():
    payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="DirectAPIRequest payload keys"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_non_object():
    with pytest.raises(ValueError, match="DirectAPIRequest payload must be an object"):
        DirectAPIRequest.from_payload("not a payload")


def test_directapi_request_payload_rejects_missing_prompt():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="missing DirectAPIRequest payload"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_missing_model():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
    }

    with pytest.raises(ValueError, match="missing DirectAPIRequest payload"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_missing_identity_fields():
    payload = {
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="missing DirectAPIRequest payload"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_bool_schema_version():
    payload = {
        "schema_version": True,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="unsupported DirectAPIRequest schema_version"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_response_type():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="unsupported DirectAPIRequest type"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_blank_type():
    payload = {
        "schema_version": 1,
        "type": " ",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="DirectAPIRequest type"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_blank_prompt():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "prompt": " ",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="DirectAPIRequest prompt"):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_unencodable_prompt():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "prompt": "\ud800",
        "model": "contract-model",
    }

    with pytest.raises(UnicodeEncodeError):
        DirectAPIRequest.from_payload(payload)


def test_directapi_request_payload_rejects_padded_model():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": " contract-model ",
    }

    with pytest.raises(
        ValueError,
        match="DirectAPIRequest model must not contain whitespace",
    ):
        DirectAPIRequest.from_payload(payload)


def test_directapi_response_rejects_empty_text():
    with pytest.raises(ValueError, match="DirectAPIResponse text"):
        DirectAPIResponse(text=" ", model="contract-model")


def test_directapi_response_rejects_unencodable_text():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIResponse(text="\ud800", model="contract-model")


def test_directapi_response_rejects_empty_model():
    with pytest.raises(ValueError, match="DirectAPIResponse model"):
        DirectAPIResponse(text="response", model="")


def test_directapi_response_rejects_unencodable_model():
    with pytest.raises(UnicodeEncodeError):
        DirectAPIResponse(text="response", model="\ud800")


def test_directapi_response_rejects_padded_model():
    with pytest.raises(
        ValueError,
        match="DirectAPIResponse model must not contain whitespace",
    ):
        DirectAPIResponse(text="response", model=" contract-model ")


def test_directapi_response_rejects_whitespace_inside_model():
    with pytest.raises(
        ValueError,
        match="DirectAPIResponse model must not contain whitespace",
    ):
        DirectAPIResponse(text="response", model="contract model")


def test_directapi_response_payload_roundtrips():
    response = DirectAPIResponse(text="raw response", model="contract-model")

    payload = response.to_payload()

    assert tuple(payload) == DIRECT_API_RESPONSE_PAYLOAD_FIELDS
    assert payload == {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "text": "raw response",
        "model": "contract-model",
    }
    assert DirectAPIResponse.from_payload(payload) == response


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("text", " ", "DirectAPIResponse text"),
        (
            "model",
            "bad model",
            "DirectAPIResponse model must not contain whitespace",
        ),
    ],
)
def test_directapi_response_to_payload_revalidates_before_return(
    field,
    value,
    message,
):
    response = object.__new__(DirectAPIResponse)
    object.__setattr__(response, "text", "raw response")
    object.__setattr__(response, "model", "contract-model")
    object.__setattr__(response, field, value)

    with pytest.raises(ValueError, match=message):
        response.to_payload()


def test_directapi_response_payload_rejects_request_type():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_REQUEST",
        "text": "raw response",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="unsupported DirectAPIResponse type"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_non_string_type():
    payload = {
        "schema_version": 1,
        "type": object(),
        "text": "raw response",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="DirectAPIResponse type"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_unknown_field():
    payload = DirectAPIResponse(
        text="raw response",
        model="contract-model",
    ).to_payload()
    payload["route"] = "pass"

    with pytest.raises(ValueError, match="unknown DirectAPIResponse payload"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_non_string_keys():
    payload = DirectAPIResponse(
        text="raw response",
        model="contract-model",
    ).to_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="DirectAPIResponse payload keys"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_missing_text():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="missing DirectAPIResponse payload"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_missing_model():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "text": "raw response",
    }

    with pytest.raises(ValueError, match="missing DirectAPIResponse payload"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_missing_identity_fields():
    payload = {
        "text": "raw response",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="missing DirectAPIResponse payload"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_bool_schema_version():
    payload = {
        "schema_version": False,
        "type": "DIRECT_API_RESPONSE",
        "text": "raw response",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="unsupported DirectAPIResponse schema_version"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_blank_text():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "text": " ",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="DirectAPIResponse text"):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_unencodable_text():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "text": "\ud800",
        "model": "contract-model",
    }

    with pytest.raises(UnicodeEncodeError):
        DirectAPIResponse.from_payload(payload)


def test_directapi_response_payload_rejects_padded_model():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_RESPONSE",
        "text": "raw response",
        "model": " contract-model ",
    }

    with pytest.raises(
        ValueError,
        match="DirectAPIResponse model must not contain whitespace",
    ):
        DirectAPIResponse.from_payload(payload)


def test_parse_directapi_payload_accepts_request_payload():
    request = DirectAPIRequest(prompt="prompt text", model="contract-model")

    parsed = parse_direct_api_payload(request.to_payload())

    assert parsed == request


def test_parse_directapi_payload_accepts_response_payload():
    response = DirectAPIResponse(text="raw response", model="contract-model")

    parsed = parse_direct_api_payload(response.to_payload())

    assert parsed == response


def test_parse_directapi_payload_rejects_non_object():
    with pytest.raises(ValueError, match="DirectAPI payload must be an object"):
        parse_direct_api_payload("not a payload")


def test_parse_directapi_payload_rejects_non_string_keys_before_dispatch():
    payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    payload[1] = "adapter-only"

    with pytest.raises(ValueError, match="DirectAPI payload keys"):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_credential_fields_through_shared_gate():
    payload = DirectAPIRequest(
        prompt="prompt text",
        model="contract-model",
    ).to_payload()
    payload["api_key"] = "key-a"

    with pytest.raises(ValueError, match="credential field"):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_credential_fields_before_type_dispatch():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_STATUS",
        "api_key": "key-a",
    }

    with pytest.raises(ValueError, match="credential field"):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_execution_claim_fields_before_type_dispatch():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_STATUS",
        "provider_call_result": "called",
    }

    with pytest.raises(ValueError, match="execution claim field"):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_cross_contract_metadata_before_type_dispatch():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_STATUS",
        "automation_ready": True,
    }

    with pytest.raises(ValueError, match="cross-contract metadata field"):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_missing_identity_field():
    payload = {
        "schema_version": 1,
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(
        ValueError,
        match="missing DirectAPI payload identity field",
    ):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_missing_schema_version():
    payload = {
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(
        ValueError,
        match="missing DirectAPI payload identity field",
    ):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_bool_schema_version():
    payload = {
        "schema_version": True,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(
        ValueError,
        match="unsupported DirectAPI payload schema_version",
    ):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_unsupported_schema_version():
    payload = {
        "schema_version": 2,
        "type": "DIRECT_API_REQUEST",
        "prompt": "prompt text",
        "model": "contract-model",
    }

    with pytest.raises(
        ValueError,
        match="unsupported DirectAPI payload schema_version",
    ):
        parse_direct_api_payload(payload)


def test_parse_directapi_payload_rejects_unknown_type():
    payload = {
        "schema_version": 1,
        "type": "DIRECT_API_STATUS",
        "text": "raw response",
        "model": "contract-model",
    }

    with pytest.raises(ValueError, match="unsupported DirectAPI payload type"):
        parse_direct_api_payload(payload)


def test_directapi_provider_receives_prompt_and_returns_raw_text():
    seen: list[DirectAPIRequest] = []

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        seen.append(request)
        return DirectAPIResponse(text='{"route": "pass"}', model=request.model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    assert interface.call("prompt text") == '{"route": "pass"}'
    assert seen == [DirectAPIRequest(prompt="prompt text", model="contract-model")]


def test_directapi_preserves_raw_prompt_text_for_provider():
    raw_prompt = "  prompt text\r\n"
    seen: list[DirectAPIRequest] = []

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        seen.append(request)
        return DirectAPIResponse(text="response", model=request.model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    assert interface.call(raw_prompt) == "response"
    assert seen == [DirectAPIRequest(prompt=raw_prompt, model="contract-model")]


def test_directapi_preserves_raw_response_text():
    raw_response = '  {"route": "pass"}\r\n'

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        return DirectAPIResponse(text=raw_response, model=request.model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    assert interface.call("prompt text") == raw_response


def test_directapi_call_does_not_parse_routes_or_write_artifacts():
    source = textwrap.dedent(inspect.getsource(DirectAPIInterface.call))
    tree = ast.parse(source)
    banned_names = {
        "json",
        "Path",
        "HandoffBoundaryUnit",
        "parse_direct_api_payload",
        "ReviewUnit",
        "ResponseFileBoundaryUnit",
        "StagedResponseRunner",
    }
    banned_calls = {
        "loads",
        "dumps",
        "model_validate_json",
        "write_text",
        "write_bytes",
        "open",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in banned_names
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in banned_calls
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned_calls


def test_directapi_call_does_not_convert_request_response_payloads():
    source = textwrap.dedent(inspect.getsource(DirectAPIInterface.call))
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"to_payload", "from_payload"}


def test_directapi_call_has_no_retry_fallback_or_exception_translation_flow():
    source = textwrap.dedent(inspect.getsource(DirectAPIInterface.call))
    tree = ast.parse(source)

    for node in ast.walk(tree):
        assert not isinstance(node, ast.Try)
        assert not isinstance(node, (ast.For, ast.While))
        if isinstance(node, ast.Name):
            assert "retry" not in node.id.lower()
            assert "fallback" not in node.id.lower()
        if isinstance(node, ast.Attribute):
            assert "retry" not in node.attr.lower()
            assert "fallback" not in node.attr.lower()
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "sleep"
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr != "sleep"


def test_directapi_provider_error_surfaces_unchanged():
    error = RuntimeError("provider failed")

    def provider(_request: DirectAPIRequest) -> DirectAPIResponse:
        raise error

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(RuntimeError) as excinfo:
        interface.call("prompt text")
    assert excinfo.value is error


def test_directapi_provider_error_is_not_retried():
    calls = 0
    error = RuntimeError("provider failed")

    def provider(_request: DirectAPIRequest) -> DirectAPIResponse:
        nonlocal calls
        calls += 1
        raise error

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(RuntimeError) as excinfo:
        interface.call("prompt text")
    assert excinfo.value is error
    assert calls == 1


def test_directapi_rejects_non_contract_response():
    def provider(_request: DirectAPIRequest) -> str:
        return "raw string"

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(TypeError, match="DirectAPIResponse"):
        interface.call("prompt text")


def test_directapi_rejects_model_mismatch():
    def provider(_request: DirectAPIRequest) -> DirectAPIResponse:
        return DirectAPIResponse(text="response", model="other-model")

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match="model mismatch"):
        interface.call("prompt text")


def test_directapi_rejects_model_mutation_during_provider_call():
    interface = DirectAPIInterface(model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.model = "changed-model"
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(ValueError, match="model changed during provider call"):
        interface.call("prompt text")


def test_directapi_rejects_api_key_mutation_during_provider_call():
    interface = DirectAPIInterface(api_key="key-a", model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.api_key = "key-b"
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(ValueError, match="api_key changed during provider call"):
        interface.call("prompt text")


def test_directapi_rejects_provider_mutation_during_provider_call():
    interface = DirectAPIInterface(model="contract-model")

    def replacement(_request: DirectAPIRequest) -> DirectAPIResponse:
        return DirectAPIResponse(text="replacement", model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.provider_call = replacement
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(ValueError, match="provider_call changed during provider call"):
        interface.call("prompt text")


def test_directapi_revalidates_corrupted_model_snapshot_after_provider_call():
    interface = DirectAPIInterface(model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.__dict__["_model"] = "bad model"
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(ValueError, match="model must not contain whitespace"):
        interface.call("prompt text")


def test_directapi_revalidates_corrupted_api_key_snapshot_after_provider_call():
    interface = DirectAPIInterface(api_key="key-a", model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.__dict__["_api_key"] = "bad key"
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(ValueError, match="api_key must not contain whitespace"):
        interface.call("prompt text")


def test_directapi_revalidates_corrupted_provider_snapshot_after_provider_call():
    interface = DirectAPIInterface(model="contract-model")

    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        interface.__dict__["_provider_call"] = "not-callable"
        return DirectAPIResponse(text="response", model=request.model)

    interface.provider_call = provider

    with pytest.raises(TypeError, match="provider_call must be callable"):
        interface.call("prompt text")


def test_directapi_rejects_request_mutation_during_provider_call():
    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        object.__setattr__(request, "prompt", "changed prompt")
        return DirectAPIResponse(text="response", model=request.model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match="request prompt changed during provider call"):
        interface.call("prompt text")


def test_directapi_rejects_request_model_mutation_during_provider_call():
    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        original_model = request.model
        object.__setattr__(request, "model", "changed-model")
        return DirectAPIResponse(text="response", model=original_model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match="request model changed during provider call"):
        interface.call("prompt text")


def test_directapi_rejects_invalid_model_assignment():
    interface = DirectAPIInterface(model="contract-model")

    with pytest.raises(ValueError, match="model must not contain whitespace"):
        interface.model = "invalid model"


def test_directapi_rejects_invalid_api_key_assignment():
    interface = DirectAPIInterface(api_key="valid-key", model="contract-model")

    with pytest.raises(ValueError, match="api_key must not contain whitespace"):
        interface.api_key = "bad key"


def test_directapi_rejects_non_callable_provider_assignment():
    interface = DirectAPIInterface(model="contract-model")

    with pytest.raises(TypeError, match="provider_call must be callable"):
        interface.provider_call = "not-callable"


def test_directapi_revalidates_corrupted_model_snapshot_before_missing_provider():
    interface = DirectAPIInterface(model="contract-model")
    interface.__dict__["_model"] = "invalid model"

    with pytest.raises(ValueError, match="model must not contain whitespace"):
        interface.call("prompt text")


def test_directapi_revalidates_corrupted_api_key_snapshot_before_missing_provider():
    interface = DirectAPIInterface(api_key="valid-key", model="contract-model")
    interface.__dict__["_api_key"] = "bad key"

    with pytest.raises(ValueError, match="api_key must not contain whitespace"):
        interface.call("prompt text")


def test_directapi_revalidates_corrupted_provider_snapshot_before_request_build():
    interface = DirectAPIInterface(model="contract-model")
    interface.__dict__["_provider_call"] = "not-callable"

    with pytest.raises(TypeError, match="provider_call must be callable"):
        interface.call("prompt text")


def test_directapi_rejects_empty_response_text():
    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        return DirectAPIResponse(text="   ", model=request.model)

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match="DirectAPIResponse text"):
        interface.call("prompt text")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("text", "   ", "DirectAPIResponse text"),
        (
            "model",
            "bad model",
            "DirectAPIResponse model must not contain whitespace",
        ),
    ],
)
def test_directapi_rejects_corrupted_provider_response_object(
    field,
    value,
    message,
):
    def provider(request: DirectAPIRequest) -> DirectAPIResponse:
        response = object.__new__(DirectAPIResponse)
        object.__setattr__(response, "text", "response")
        object.__setattr__(response, "model", request.model)
        object.__setattr__(response, field, value)
        return response

    interface = DirectAPIInterface(model="contract-model", provider_call=provider)

    with pytest.raises(ValueError, match=message):
        interface.call("prompt text")
