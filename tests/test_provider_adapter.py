import json
import sqlite3
import urllib.error
from pathlib import Path

import pytest

from src.llm_interface import DirectAPIInterface
from src.object_state.autonomous import (
    AutonomousBudget,
    ProviderProfile,
)
from src.provider_adapter import (
    A1_CLOSED_LOOP_ALLOWED,
    A1_PROVIDER_CALLS_IMPLEMENTED,
    AnthropicMessagesProvider,
    AutonomousBudgetLedger,
    ProviderBudgetError,
    ProviderConfigurationError,
    ProviderSchemaError,
)


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _profile_payload() -> dict:
    return {
        "schema_version": "1.0",
        "profile_id": "provider-a",
        "transport": "anthropic_messages_http",
        "endpoint": {
            "settings_path_from_user_home": ".claude/settings.json",
            "base_url_json_path": "env.ANTHROPIC_BASE_URL",
            "credential_json_path": "env.ANTHROPIC_AUTH_TOKEN",
            "messages_path": "/v1/messages",
            "auth_scheme": "bearer",
            "anthropic_version": "2023-06-01",
            "user_agent": "AutomaticNovelNarrativeSystem/0.1",
            "timeout_seconds": 10,
            "max_attempts": 1,
        },
        "provider_audit": {
            "database_path_from_user_home": ".cc-switch/cc-switch.db",
            "provider_id": "provider-id",
            "provider_name": "provider-name",
            "provider_category": "third_party",
            "upstream_url": "https://provider.invalid",
            "expected_actual_model": "model-a",
            "failover_allowed": False,
        },
        "roles": {
            role: {
                "request_model": "model-a",
                "expected_actual_model": "model-a",
                "temperature": 0.7 if role == "generation" else 0.0,
            }
            for role in (
                "generation",
                "fact_judge",
                "character_judge",
                "reader_judge",
            )
        },
        "pricing_usd_per_million_tokens": {
            "input": 0.14,
            "output": 0.28,
            "cache_read": 0.0028,
            "cache_creation": 0,
            "source": "pricing-table",
            "frozen_at": "2026-08-11",
        },
        "smoke_evidence": {
            "request_model": "model-a",
            "actual_model": "model-a",
            "input_tokens": 10,
            "output_tokens": 2,
            "cost_usd": 0.000002,
            "status_code": 200,
        },
    }


def _budget(**updates) -> AutonomousBudget:
    payload = {
        "max_total_calls": 10,
        "max_total_input_tokens": 10000,
        "max_total_output_tokens": 1000,
        "max_total_cost_usd": 1,
        "max_wall_clock_seconds": 1000,
        "max_chapters_per_run": 1,
        "max_canary_runs": 1,
        "max_canary_chapters_total": 1,
    }
    payload.update(updates)
    return AutonomousBudget.model_validate(payload)


def _provider_files(tmp_path: Path, *, provider_id: str = "provider-id") -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
                    "ANTHROPIC_AUTH_TOKEN": "secret-value",
                }
            }
        ),
        encoding="utf-8",
    )
    db_dir = tmp_path / ".cc-switch"
    db_dir.mkdir()
    with sqlite3.connect(db_dir / "cc-switch.db") as connection:
        connection.execute(
            """
            CREATE TABLE providers (
                id TEXT, app_type TEXT, name TEXT, in_failover_queue INTEGER,
                settings_config TEXT, is_current INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO providers VALUES (?, 'claude', 'provider-name', 0, ?, 1)",
            (
                provider_id,
                json.dumps(
                    {"env": {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "model-a"}}
                ),
            ),
        )


def _adapter(tmp_path: Path, **budget_updates) -> AnthropicMessagesProvider:
    _provider_files(tmp_path)
    profile = ProviderProfile.model_validate(_profile_payload())
    ledger = AutonomousBudgetLedger(
        budget=_budget(**budget_updates),
        pricing=profile.pricing_usd_per_million_tokens,
    )
    return AnthropicMessagesProvider(
        profile=profile,
        role="reader_judge",
        max_output_tokens=100,
        audit_dir=tmp_path / "audit",
        ledger=ledger,
        user_home=tmp_path,
    )


def _success_payload(model: str = "model-a") -> dict:
    return {
        "type": "message",
        "model": model,
        "content": [
            {"type": "thinking", "thinking": "not persisted"},
            {"type": "text", "text": '{"winner":"A"}'},
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 4,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 0,
        },
    }


def test_a1_provider_capability_is_separate_from_tier0_boundary():
    assert A1_PROVIDER_CALLS_IMPLEMENTED is True
    assert A1_CLOSED_LOOP_ALLOWED is True


def test_concrete_provider_integrates_with_direct_api_and_redacts_audit(
    tmp_path, monkeypatch
):
    adapter = _adapter(tmp_path)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        assert request.headers["Authorization"] == "Bearer secret-value"
        return _Response(_success_payload())

    monkeypatch.setattr("src.provider_adapter.urllib.request.urlopen", fake_urlopen)
    interface = DirectAPIInterface(model="model-a", provider_call=adapter)
    text = interface.call("private prose")

    assert text == '{"winner":"A"}'
    assert len(calls) == 1
    assert adapter.ledger.usage.calls == 1
    audit_path = tmp_path / "audit" / "call_000001.json"
    raw_audit = audit_path.read_text(encoding="utf-8")
    audit = json.loads(raw_audit)
    assert audit["status"] == "success"
    assert audit["actual_model"] == "model-a"
    assert "private prose" not in raw_audit
    assert "secret-value" not in raw_audit
    assert "thinking" not in raw_audit


def test_actual_model_mismatch_is_explicit_and_charges_consumed_call(
    tmp_path, monkeypatch
):
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        lambda request, timeout: _Response(_success_payload(model="other-model")),
    )

    with pytest.raises(ProviderSchemaError, match="actual model"):
        DirectAPIInterface(model="model-a", provider_call=adapter).call("prompt")

    audit = json.loads(
        (tmp_path / "audit" / "call_000001.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "failed"
    assert audit["error_type"] == "ProviderSchemaError"
    assert adapter.ledger.usage.calls == 1


def test_budget_blocks_before_network_call(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, max_total_output_tokens=10)
    calls = []
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        lambda request, timeout: calls.append(request),
    )

    with pytest.raises(ProviderBudgetError, match="output_tokens"):
        DirectAPIInterface(model="model-a", provider_call=adapter).call("prompt")

    assert calls == []
    assert not (tmp_path / "audit").exists()


def test_network_failure_is_audited_once_without_error_message(
    tmp_path, monkeypatch
):
    adapter = _adapter(tmp_path)
    calls = []

    def fail_once(request, timeout):
        calls.append(request)
        raise urllib.error.URLError("secret network detail")

    monkeypatch.setattr("src.provider_adapter.urllib.request.urlopen", fail_once)
    with pytest.raises(urllib.error.URLError):
        DirectAPIInterface(model="model-a", provider_call=adapter).call("private")

    assert len(calls) == 1
    raw_audit = (tmp_path / "audit" / "call_000001.json").read_text(
        encoding="utf-8"
    )
    assert "secret network detail" not in raw_audit
    assert "private" not in raw_audit
    assert json.loads(raw_audit)["error_type"] == "URLError"


def test_constructor_refuses_provider_identity_drift(tmp_path):
    _provider_files(tmp_path, provider_id="different-provider")
    profile = ProviderProfile.model_validate(_profile_payload())
    ledger = AutonomousBudgetLedger(
        budget=_budget(), pricing=profile.pricing_usd_per_million_tokens
    )
    with pytest.raises(ProviderConfigurationError, match="frozen profile"):
        AnthropicMessagesProvider(
            profile=profile,
            role="generation",
            max_output_tokens=100,
            audit_dir=tmp_path / "audit",
            ledger=ledger,
            user_home=tmp_path,
        )
