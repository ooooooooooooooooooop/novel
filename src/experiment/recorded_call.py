"""Small, provider-agnostic call receipt used by bounded research runs.

This module records an immutable reservation before calling a transport.  The
reservation is the quota boundary; result files are written separately, so a
crash cannot make a call disappear or overwrite an older receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


UNKNOWN = "UNKNOWN"
HARD_ATTEMPT_LIMIT = 3


class RecordedCallError(RuntimeError):
    """A call was refused, failed, or returned an unusable provider payload."""


class ResponseSchemaError(RecordedCallError):
    """The transport returned no usable OpenAI-shaped text response."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _create_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Create an immutable JSON artifact with an exclusive filesystem slot."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _key(prompt: str, model: str) -> tuple[str, str]:
    prompt_hash = _sha256(prompt)
    canonical = json.dumps(
        {"prompt_sha256": prompt_hash, "requested_model": model},
        sort_keys=True,
        separators=(",", ":"),
    )
    return prompt_hash, _sha256(canonical)


def _reservations(evidence_dir: Path, key: str) -> list[Path]:
    return sorted(evidence_dir.glob(f"call-{key}-*.reserved.json"), key=lambda p: p.name)


def _results(evidence_dir: Path, key: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in evidence_dir.glob(f"call-{key}-*.result.json"):
        try:
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, dict):
                value["_receipt_path"] = str(path)
                found.append(value)
        except (OSError, ValueError):
            continue
    return found


def _reservation_records(evidence_dir: Path, key: str) -> list[dict[str, Any] | None]:
    records: list[dict[str, Any] | None] = []
    for path in _reservations(evidence_dir, key):
        try:
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
            records.append(value if isinstance(value, dict) else None)
        except (OSError, ValueError):
            records.append(None)
    return records


def _is_terminal(result: Mapping[str, Any]) -> bool:
    return (
        result.get("status") != "success"
        and result.get("retryable") is not True
        and result.get("allow_next_call") is not True
    )


def _http_status(value: Any) -> int | None:
    if isinstance(value, Mapping):
        for name in ("status_code", "status", "http_status", "code"):
            candidate = value.get(name)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                return candidate
        error = value.get("error")
        if isinstance(error, Mapping):
            for name in ("status_code", "status", "http_status", "code"):
                candidate = error.get(name)
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    return candidate
    return None


def _exception_status(error: BaseException) -> int | None:
    for name in ("status_code", "status", "code"):
        candidate = getattr(error, name, None)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    match = re.search(r"\b(429|5\d\d)\b", str(error))
    return int(match.group(1)) if match else None


def _is_timeout(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, socket.timeout)) or "timeout" in type(error).__name__.lower()


def _extract_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message")
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    pieces = [
                        item.get("text") for item in content
                        if isinstance(item, Mapping) and isinstance(item.get("text"), str)
                    ]
                    if pieces:
                        return "".join(pieces)
            text = first.get("text")
            if isinstance(text, str):
                return text
    output = payload.get("output")
    if isinstance(output, list):
        pieces: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if isinstance(content, list):
                pieces.extend(
                    part.get("text") for part in content
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str)
                )
        if pieces:
            return "".join(pieces)
    raise ResponseSchemaError("provider response contains no usable text")


def _error_message(error: BaseException) -> str:
    text = str(error).strip()
    return text[:1000] or type(error).__name__


def _write_result(
    evidence_dir: Path,
    key: str,
    attempt_id: str,
    base: Mapping[str, Any],
    **fields: Any,
) -> None:
    payload = dict(base)
    payload.update(fields)
    payload["ended_at"] = _now()
    _create_json(evidence_dir / f"call-{key}-{attempt_id}.result.json", payload)


def call_recorded(
    prompt: str,
    model: str,
    transport: Callable[[float], Mapping[str, Any]],
    evidence_dir: str | os.PathLike[str],
    max_attempts: int = 3,
    timeout_s: float = 600,
) -> str:
    """Call ``transport`` with immutable, cross-process attempt accounting.

    Only HTTP 429/5xx failures are retried, and only while the shared hard
    limit of three reservations has not been consumed.  Schema errors,
    timeouts, and other exceptions are recorded once and raised immediately.
    """
    if not isinstance(prompt, str) or not isinstance(model, str) or not model:
        raise ValueError("prompt and model must be non-empty strings")
    if max_attempts < 1 or timeout_s <= 0:
        raise ValueError("max_attempts must be positive and timeout_s must be positive")
    cap = min(int(max_attempts), HARD_ATTEMPT_LIMIT)
    directory = Path(evidence_dir)
    directory.mkdir(parents=True, exist_ok=True)
    prompt_hash, call_key = _key(prompt, model)

    while True:
        results = _results(directory, call_key)
        reservations = _reservations(directory, call_key)
        reservation_records = _reservation_records(directory, call_key)
        result_ids = {item.get("attempt_id") for item in results}
        for reservation in reservation_records:
            if not reservation or reservation.get("attempt_id") not in result_ids:
                raise RecordedCallError(
                    "in-flight unknown: a prior reservation has no final receipt"
                )
        for result in results:
            if _is_terminal(result):
                raise RecordedCallError(
                    "prior call is terminal; refusing blind retry: "
                    f"{result.get('status', UNKNOWN)}"
                )

        for attempt_number in range(1, cap + 1):
            attempt_id = uuid.uuid4().hex
            base = {
                "schema_version": "recorded_call.v1",
                "call_key": call_key,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "prompt_sha256": prompt_hash,
                "requested_model": model,
                "reserved_at": _now(),
                "started_at": _now(),
                "status": "reserved",
            }
            reservation_path = directory / f"call-{call_key}-{attempt_number}.reserved.json"
            try:
                _create_json(reservation_path, base)
                break
            except FileExistsError:
                # A concurrent caller may have won this slot after the state
                # scan.  Re-check it: an unfinished slot is fail-closed.
                current = _reservation_records(directory, call_key)
                current_results = _results(directory, call_key)
                current_ids = {item.get("attempt_id") for item in current_results}
                matches = [item for item in current
                           if item and item.get("attempt_number") == attempt_number]
                if len(matches) != 1 or matches[0].get("attempt_id") not in current_ids:
                    raise RecordedCallError("in-flight unknown: reservation has no final receipt")
                winner = next(
                    item for item in current_results
                    if item.get("attempt_id") == matches[0].get("attempt_id")
                )
                if _is_terminal(winner):
                    raise RecordedCallError(
                        "prior call is terminal; refusing blind retry: "
                        f"{winner.get('status', UNKNOWN)}"
                    )
        else:
            raise RecordedCallError(
                f"attempt limit exhausted for {call_key}: {len(reservations)}"
            )

        try:
            raw = transport(timeout_s)
            if not isinstance(raw, Mapping):
                raise ResponseSchemaError("provider response is not an object")
            status_code = _http_status(raw)
            if status_code is not None and status_code >= 400:
                retryable = status_code == 429 or status_code >= 500
                error = RecordedCallError(f"provider returned HTTP {status_code}")
                _write_result(
                    directory, call_key, attempt_id, base,
                    status=f"http_{status_code}", http_status=status_code,
                    retryable=retryable, allow_next_call=retryable,
                    error_type=type(error).__name__,
                    error_message=str(error), response_model=UNKNOWN,
                )
                setattr(error, "_receipt_written", True)
                if retryable and attempt_number < cap:
                    time.sleep(min(0.25 * attempt_number, 1.0))
                    continue
                raise error
            text = _extract_text(raw)
            response_model = raw.get("model")
            response_model = response_model if isinstance(response_model, str) and response_model else UNKNOWN
            success_fields: dict[str, Any] = {
                "status": "success", "retryable": False,
                "response_model": response_model,
                "response_sha256": _sha256(text), "response_text": text,
            }
            if "usage" in raw:
                success_fields["usage"] = raw["usage"]
            if "id" in raw:
                success_fields["id"] = raw["id"]
            _write_result(
                directory, call_key, attempt_id, base, **success_fields,
            )
            return text
        except BaseException as error:
            if getattr(error, "_receipt_written", False):
                raise
            status_code = _exception_status(error)
            retryable = status_code == 429 or (status_code is not None and status_code >= 500)
            if isinstance(error, (ResponseSchemaError,)):
                status = "schema_error"
                allow_next_call = True
            elif _is_timeout(error):
                status = "timeout"
                retryable = False
                allow_next_call = False
            elif status_code is not None:
                status = f"http_{status_code}"
                allow_next_call = retryable
            else:
                status = "failed"
                retryable = False
                allow_next_call = False
            _write_result(
                directory, call_key, attempt_id, base,
                status=status, http_status=status_code, retryable=retryable,
                allow_next_call=allow_next_call,
                response_model=UNKNOWN, error_type=type(error).__name__,
                error_message=_error_message(error),
            )
            if retryable and attempt_number < cap:
                time.sleep(min(0.25 * attempt_number, 1.0))
                continue
            raise


def provenance_for_text(text: str, evidence_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Resolve a response hash using only immutable success receipts.

    No current/default model is consulted.  Distinct requested/actual model
    pairs for the same response are reported as ``AMBIGUOUS``.
    """
    response_hash = _sha256(text)
    directory = Path(evidence_dir)
    matches: list[dict[str, Any]] = []
    if directory.exists():
        for path in directory.rglob("call-*.result.json"):
            try:
                with path.open(encoding="utf-8") as handle:
                    receipt = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(receipt, dict) and receipt.get("status") == "success" and receipt.get("response_sha256") == response_hash:
                matches.append({
                    "receipt": str(path),
                    "requested_model": receipt.get("requested_model", UNKNOWN),
                    "response_model": receipt.get("response_model", UNKNOWN),
                    "id": receipt.get("id", UNKNOWN),
                    "prompt_sha256": receipt.get("prompt_sha256", UNKNOWN),
                })
    if not matches:
        return {"status": UNKNOWN, "response_sha256": response_hash, "receipt_found": False,
                "receipts": [], "requested_models": [], "response_models": []}
    requested_models = sorted({item["requested_model"] for item in matches})
    response_models = sorted({item["response_model"] for item in matches})
    sources = {
        (item["requested_model"], item["response_model"])
        for item in matches
    }
    if len(sources) > 1:
        # AMBIGUOUS with a single requested_model means every candidate receipt
        # came from the same request; only the upstream response label differs
        # (e.g. pooled variants reporting gemini-3.8-flash vs -exp-a).
        return {"status": "AMBIGUOUS", "response_sha256": response_hash, "receipt_found": True,
                "receipts": matches, "requested_models": requested_models,
                "response_models": response_models,
                "requested_model_consistent": len(requested_models) == 1}
    first = matches[0]
    status = "KNOWN" if first["response_model"] != UNKNOWN else UNKNOWN
    return {
        "status": status,
        "response_sha256": response_hash,
        "receipt_found": True,
        "requested_model": first["requested_model"],
        "response_model": first["response_model"],
        "receipts": matches,
        "requested_models": requested_models,
        "response_models": response_models,
    }
