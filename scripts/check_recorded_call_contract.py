"""Offline checks for the bounded recorded-call contract.

This script uses no provider and writes only temporary evidence directories.
Run from the repository root with ``python scripts/check_recorded_call_contract.py``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiment.recorded_call import (
    RecordedCallError,
    ResponseSchemaError,
    call_recorded,
    provenance_for_text,
)


def _success(model: str, text: str = "recorded") -> dict:
    return {
        "id": f"id-{model}",
        "model": model,
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        "choices": [{"message": {"content": text}}],
    }


def _assert_success_receipt(root: Path) -> None:
    calls = 0

    def transport(timeout_s: float) -> dict:
        nonlocal calls
        calls += 1
        assert timeout_s == 12
        return _success("actual-a", "ok")

    text = call_recorded("p-success", "requested-a", transport, root, timeout_s=12)
    assert text == "ok" and calls == 1
    assert call_recorded("p-success", "requested-a", transport, root, timeout_s=12) == "ok"
    assert call_recorded("p-success", "requested-a", transport, root, timeout_s=12) == "ok"
    assert calls == 3, "same prompt is allowed to produce three independent calls"
    try:
        call_recorded("p-success", "requested-a", transport, root, timeout_s=12)
    except RecordedCallError:
        pass
    else:
        raise AssertionError("a fourth call must be blocked by the shared quota")
    results = list(root.glob("call-*.result.json"))
    assert len(results) == 3
    receipt = json.loads(results[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "success"
    assert receipt["requested_model"] == "requested-a"
    assert receipt["response_model"] == "actual-a"
    assert receipt["prompt_sha256"] and receipt["response_sha256"]
    assert receipt["usage"]["completion_tokens"] == 2
    assert receipt["id"] == "id-actual-a"
    assert provenance_for_text("ok", root)["status"] == "KNOWN"


def _assert_503_shared_limit(root: Path) -> None:
    calls = 0

    def transport(_: float) -> dict:
        nonlocal calls
        calls += 1
        return {"status_code": 503, "error": {"message": "busy"}}

    try:
        call_recorded("p-503", "m", transport, root, max_attempts=99)
    except RecordedCallError:
        pass
    else:
        raise AssertionError("503 must fail after the bounded retry budget")
    assert calls == 3
    try:
        call_recorded("p-503", "m", transport, root, max_attempts=3)
    except RecordedCallError:
        pass
    else:
        raise AssertionError("a second process must see the consumed reservations")
    assert calls == 3
    assert len(list(root.glob("call-*.reserved.json"))) == 3


def _assert_400_once(root: Path) -> None:
    calls = 0

    class BadRequest(Exception):
        status_code = 400

    def transport(_: float) -> dict:
        nonlocal calls
        calls += 1
        raise BadRequest("invalid request")

    try:
        call_recorded("p-400", "m", transport, root)
    except BadRequest:
        pass
    else:
        raise AssertionError("400 should be raised without an automatic retry")
    assert calls == 1
    result = next(root.glob("call-*.result.json"))
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "http_400"


def _assert_timeout_once(root: Path) -> None:
    calls = 0

    def transport(_: float) -> dict:
        nonlocal calls
        calls += 1
        raise TimeoutError("transport timed out")

    try:
        call_recorded("p-timeout", "m", transport, root)
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout should be raised without an automatic retry")
    assert calls == 1
    try:
        call_recorded("p-timeout", "m", transport, root)
    except RecordedCallError:
        pass
    else:
        raise AssertionError("a timeout must block blind retries after restart")
    assert calls == 1
    result = next(root.glob("call-*.result.json"))
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "timeout"


def _assert_unknown_and_ambiguous(root: Path) -> None:
    assert provenance_for_text("old response", root)["status"] == "UNKNOWN"

    schema_calls = 0

    def schema_then_success(_: float) -> dict:
        nonlocal schema_calls
        schema_calls += 1
        return {} if schema_calls == 1 else _success("actual-schema", "schema retry")

    try:
        call_recorded("p-schema", "m", schema_then_success, root)
    except ResponseSchemaError:
        pass
    else:
        raise AssertionError("schema-invalid output should be surfaced")
    assert call_recorded("p-schema", "m", schema_then_success, root) == "schema retry"
    assert schema_calls == 2, "a later explicit call may request a new schema attempt"

    call_recorded("p-unknown-model", "requested-unknown", lambda _: {"choices": [{"message": {"content": "unknown model"}}]}, root)
    unknown = provenance_for_text("unknown model", root)
    assert unknown["status"] == "UNKNOWN" and unknown["receipt_found"] is True

    def first(_: float) -> dict:
        return _success("actual-one", "same text")

    def second(_: float) -> dict:
        return _success("actual-two", "same text")

    call_recorded("p-one", "requested-one", first, root)
    call_recorded("p-two", "requested-two", second, root)
    found = provenance_for_text("same text", root)
    assert found["status"] == "AMBIGUOUS"
    assert len(found["receipts"]) == 2


def _assert_concurrent_reservation(root: Path) -> None:
    calls = 0
    started = threading.Event()
    release = threading.Event()
    outcome: list[str] = []

    def transport(_: float) -> dict:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5), "test transport was not released"
        return _success("actual-live", "live")

    def first_call() -> None:
        outcome.append(call_recorded("p-live", "m", transport, root))

    worker = threading.Thread(target=first_call)
    worker.start()
    assert started.wait(5), "first reservation did not reach transport"
    try:
        call_recorded("p-live", "m", transport, root)
    except RecordedCallError as error:
        assert "in-flight unknown" in str(error)
    else:
        raise AssertionError("an active reservation must block a second dispatch")
    assert calls == 1
    release.set()
    worker.join(5)
    assert not worker.is_alive() and outcome == ["live"]


def main() -> None:
    checks = [
        _assert_success_receipt,
        _assert_503_shared_limit,
        _assert_400_once,
        _assert_timeout_once,
        _assert_unknown_and_ambiguous,
        _assert_concurrent_reservation,
    ]
    for check in checks:
        with tempfile.TemporaryDirectory(prefix="recorded-call-") as directory:
            check(Path(directory))
    print("RECORDED_CALL_OFFLINE_CHECK: 6/6 PASS")


if __name__ == "__main__":
    main()
