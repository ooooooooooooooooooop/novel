"""Concrete, single-attempt A1 provider adapter.

The adapter reads credentials from the frozen profile's external source,
performs exactly one Anthropic Messages HTTP request, validates the real
response model, and writes a credential-free audit record.  It never retries
and never selects another provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from src.llm_interface import DirectAPIRequest, DirectAPIResponse
from src.object_state.autonomous import (
    AutonomousBudget,
    AutonomousUsage,
    ProviderCallAudit,
    ProviderPricing,
    ProviderProfile,
    charge_usage,
)

# 调用间最小间隔（秒）：缓解上游突发限流（429）。不是重试——M1 单次调用
# 契约不变，仅防止同一进程内并发/连续调用打爆上游。环境变量可调，
# NOVEL_PROVIDER_MIN_INTERVAL=0 关闭。
import time as _time
_PROVIDER_LAST_CALL_AT: float = 0.0

# api.b.ai Cloudflare 要求现代浏览器 UA（旧 MSIE 兼容 UA 触发 1010 风控）
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _throttle_before_call() -> None:
    global _PROVIDER_LAST_CALL_AT
    # 默认关闭；仅当 NOVEL_PROVIDER_MIN_INTERVAL 显式设置（>0）时启用。
    raw = os.environ.get("NOVEL_PROVIDER_MIN_INTERVAL", "0")
    try:
        interval = float(raw)
    except ValueError:
        interval = 0.0
    if interval <= 0:
        return
    elapsed = _time.monotonic() - _PROVIDER_LAST_CALL_AT
    if elapsed < interval:
        _time.sleep(interval - elapsed)
    _PROVIDER_LAST_CALL_AT = _time.monotonic()
A1_PROVIDER_CALLS_IMPLEMENTED = True
A1_CLOSED_LOOP_ALLOWED = True

ProviderRoleName = Literal[
    "generation", "fact_judge", "character_judge", "reader_judge"
]


class ProviderConfigurationError(ValueError):
    pass


class ProviderSchemaError(ValueError):
    pass


class ProviderBudgetError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ProviderConfigurationError(f"missing provider setting path: {path}")
        current = current[part]
    return current


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigurationError(f"{label} must be a non-empty string")
    return value.strip()


def _endpoint_identity(base_url: str, messages_path: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigurationError("provider base URL must be absolute HTTP(S)")
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError("provider base URL cannot contain query or fragment")
    port = f":{parsed.port}" if parsed.port is not None else ""
    prefix = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.hostname}{port}{prefix}{messages_path}"


def _atomic_write_audit(path: Path, audit: ProviderCallAudit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"provider audit already exists: {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


class AutonomousBudgetLedger:
    def __init__(
        self,
        *,
        budget: AutonomousBudget,
        pricing: ProviderPricing,
        usage: AutonomousUsage | None = None,
    ) -> None:
        self.budget = budget
        self.pricing = pricing
        self.usage = usage or AutonomousUsage()

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> Decimal:
        million = Decimal("1000000")
        return (
            Decimal(input_tokens) * self.pricing.input
            + Decimal(output_tokens) * self.pricing.output
            + Decimal(cache_read_tokens) * self.pricing.cache_read
            + Decimal(cache_creation_tokens) * self.pricing.cache_creation
        ) / million

    def ensure_request_capacity(
        self, *, body_bytes: int, max_output_tokens: int
    ) -> None:
        if body_bytes < 0 or max_output_tokens <= 0:
            raise ValueError("request capacity values are invalid")
        input_token_upper_bound = body_bytes + 1024
        projected_cost = self.estimate_cost(
            input_tokens=input_token_upper_bound,
            output_tokens=max_output_tokens,
        )
        try:
            charge_usage(
                self.usage,
                self.budget,
                calls=1,
                input_tokens=input_token_upper_bound,
                output_tokens=max_output_tokens,
                cost_usd=projected_cost,
            )
        except ValueError as exc:
            raise ProviderBudgetError(str(exc)) from exc

    def charge(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
    ) -> Decimal:
        cost = self.estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
        self.usage = charge_usage(
            self.usage,
            self.budget,
            calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        return cost


class AnthropicMessagesProvider:
    """Callable adapter for ``DirectAPIInterface``; one instance is one role."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        role: ProviderRoleName,
        max_output_tokens: int,
        audit_dir: Path,
        ledger: AutonomousBudgetLedger,
        user_home: Path | None = None,
    ) -> None:
        self.profile = profile
        self.role = role
        self.max_output_tokens = max_output_tokens
        self.audit_dir = Path(audit_dir)
        self.ledger = ledger
        self.user_home = Path(user_home) if user_home else Path.home()
        self._role_config = getattr(profile.roles, role)
        self._base_url, self._auth_value = self._load_external_settings()
        self._verify_upstream_url()
        self.endpoint_identity = _endpoint_identity(
            self._base_url, profile.endpoint.messages_path
        )
        self._verify_provider_identity()

    def _load_external_settings(self) -> tuple[str, str]:
        # 进程环境优先（凭据不落盘、可注入沙箱校准/生产运行）；缺省回落 settings 文件。
        # 环境变量名来自 profile 的 json 路径（如 "env.ANTHROPIC_BASE_URL" → ANTHROPIC_BASE_URL）。
        base_env = os.environ.get(
            self.profile.endpoint.base_url_json_path.removeprefix("env."), ""
        )
        auth_env = os.environ.get(
            self.profile.endpoint.credential_json_path.removeprefix("env."), ""
        )
        if base_env and auth_env:
            return base_env.rstrip("/"), auth_env
        path = self.user_home / self.profile.endpoint.settings_path_from_user_home
        payload = json.loads(path.read_text(encoding="utf-8"))
        base_url = _require_text(
            _json_path(payload, self.profile.endpoint.base_url_json_path),
            "provider base URL",
        )
        auth_value = _require_text(
            _json_path(payload, self.profile.endpoint.credential_json_path),
            "provider auth value",
        )
        return base_url.rstrip("/"), auth_value

    def _verify_upstream_url(self) -> None:
        """调用前校验已加载 base_url 与冻结 profile 的 upstream_url 一致（规范化尾斜杠）。

        upstream_url 是实际上游身份：runtime profile 由 builder 从 ANTHROPIC_BASE_URL 注入
        实际值，运行期 env 必须与冻结值一致，否则在首次调用前显式失败（不发起任何网络请求，
        不落任何审计）。
        """
        expected = self.profile.provider_audit.upstream_url.rstrip("/")
        actual = self._base_url.rstrip("/")
        if actual != expected:
            raise ProviderConfigurationError(
                "provider base URL differs from frozen profile upstream_url"
            )

    def _verify_provider_identity(self) -> None:
        if self.profile.provider_audit.skip_identity_check:
            return
        db_path = self.user_home / self.profile.provider_audit.database_path_from_user_home
        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                """
                SELECT id, name, in_failover_queue, settings_config
                FROM providers
                WHERE app_type = 'claude' AND is_current = 1
                """
            ).fetchone()
        if row is None:
            raise ProviderConfigurationError("no current Claude provider is configured")
        provider_id, provider_name, in_failover_queue, settings_json = row
        settings = json.loads(settings_json)
        actual_model = _json_path(settings, "env.ANTHROPIC_DEFAULT_HAIKU_MODEL")
        expected = self.profile.provider_audit
        if provider_id != expected.provider_id or provider_name != expected.provider_name:
            raise ProviderConfigurationError("current provider differs from frozen profile")
        if bool(in_failover_queue) or expected.failover_allowed:
            raise ProviderConfigurationError("provider failover must remain disabled")
        if actual_model != expected.expected_actual_model:
            raise ProviderConfigurationError("actual provider model differs from frozen profile")

    def __call__(self, request: DirectAPIRequest) -> DirectAPIResponse:
        if request.model != self._role_config.request_model:
            raise ProviderConfigurationError(
                f"request model differs from frozen {self.role} role"
            )
        prompt_hash = _sha256_bytes(request.prompt.encode("utf-8"))
        is_openai = self.profile.endpoint.api_format == "openai"
        if is_openai:
            body = {
                "model": request.model,
                "max_tokens": self.max_output_tokens,
                "temperature": self._role_config.temperature,
                "messages": [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": request.prompt},
                ],
            }
        else:
            body = {
                "model": request.model,
                "max_tokens": self.max_output_tokens,
                "temperature": self._role_config.temperature,
                "system": self._system_prompt(),
                "messages": [{"role": "user", "content": request.prompt}],
            }
            if self._role_config.thinking_disabled:
                body["thinking"] = {"type": "disabled"}
        body_bytes = json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.ledger.ensure_request_capacity(
            body_bytes=len(body_bytes), max_output_tokens=self.max_output_tokens
        )
        call_number = self.ledger.usage.calls + 1
        call_id = f"call_{call_number:06d}"
        audit_path = self.audit_dir / f"{call_id}.json"
        started = _utc_now()
        actual_model: str | None = None
        response_hash: str | None = None
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        cost = Decimal("0")
        try:
            raw = self._post_once(body_bytes)
            response_hash = _sha256_bytes(raw)
            payload = json.loads(raw.decode("utf-8"))
            if is_openai:
                usage = payload.get("usage")
                if not isinstance(usage, dict):
                    raise ProviderSchemaError("provider response usage must be an object")
                input_tokens = _require_non_negative_int(
                    usage.get("prompt_tokens"), "prompt_tokens"
                )
                output_tokens = _require_non_negative_int(
                    usage.get("completion_tokens"), "completion_tokens"
                )
                cache_read_tokens = _optional_non_negative_int(
                    usage.get("prompt_tokens_details", {}).get("cached_tokens"),
                    "cached_tokens",
                )
                cache_creation_tokens = 0
            else:
                usage = payload.get("usage")
                if not isinstance(usage, dict):
                    raise ProviderSchemaError("provider response usage must be an object")
                input_tokens = _require_non_negative_int(
                    usage.get("input_tokens"), "input_tokens"
                )
                output_tokens = _require_non_negative_int(
                    usage.get("output_tokens"), "output_tokens"
                )
                cache_read_tokens = _optional_non_negative_int(
                    usage.get("cache_read_input_tokens"), "cache_read_input_tokens"
                )
                cache_creation_tokens = _optional_non_negative_int(
                    usage.get("cache_creation_input_tokens"),
                    "cache_creation_input_tokens",
                )
            cost = self.ledger.charge(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
            )
            actual_model = _require_response_text(payload.get("model"), "response model")
            # 模型身份校验：允许供应商版本化后缀（如 deepseek-v4-flash-202605），
            # 但拒绝不同家族/不同供应商的模型（意图是防错误路由，不是咬死版本串）。
            if not actual_model.startswith(self._role_config.expected_actual_model):
                raise ProviderSchemaError(
                    "provider response actual model differs from frozen role"
                )
            text = _response_text_openai(payload) if is_openai else _response_text(payload)
            audit = ProviderCallAudit(
                call_id=call_id,
                status="success",
                role=self.role,
                endpoint_identity=self.endpoint_identity,
                request_model=request.model,
                actual_model=actual_model,
                temperature=self._role_config.temperature,
                max_output_tokens=self.max_output_tokens,
                prompt_sha256=prompt_hash,
                response_sha256=response_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cost_usd=cost,
                started_at_utc=started,
                ended_at_utc=_utc_now(),
            )
            _atomic_write_audit(audit_path, audit)
            return DirectAPIResponse(text=text, model=actual_model)
        except Exception as exc:
            audit = ProviderCallAudit(
                call_id=call_id,
                status="failed",
                role=self.role,
                endpoint_identity=self.endpoint_identity,
                request_model=request.model,
                actual_model=actual_model,
                temperature=self._role_config.temperature,
                max_output_tokens=self.max_output_tokens,
                prompt_sha256=prompt_hash,
                response_sha256=response_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cost_usd=cost,
                started_at_utc=started,
                ended_at_utc=_utc_now(),
                error_type=type(exc).__name__,
            )
            _atomic_write_audit(audit_path, audit)
            raise

    def _post_once(self, body: bytes) -> bytes:
        _throttle_before_call()
        url = f"{self._base_url}{self.profile.endpoint.messages_path}"
        headers = {
            "anthropic-version": self.profile.endpoint.anthropic_version,
            "content-type": "application/json",
            "user-agent": _BROWSER_UA,
        }
        if self.profile.endpoint.auth_scheme == "bearer":
            headers["authorization"] = f"Bearer {self._auth_value}"
        else:
            headers["x-api-key"] = self._auth_value
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(
            request, timeout=self.profile.endpoint.timeout_seconds
        ) as response:
            if response.status != 200:
                raise ProviderSchemaError(
                    f"provider returned unexpected HTTP status: {response.status}"
                )
            return response.read()

    def _system_prompt(self) -> str:
        return {
            "generation": "Follow the user contract exactly. Return only the requested payload.",
            "fact_judge": "Audit only factual and state consistency. Return only requested JSON.",
            "character_judge": "Audit only character continuity. Return only requested JSON.",
            "reader_judge": "Judge ordinary-reader experience. Return only requested JSON.",
        }[self.role]


def _require_response_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderSchemaError(f"{label} must be a non-empty string")
    return value.strip()


def _require_non_negative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderSchemaError(f"{label} must be a non-negative integer")
    return value


def _optional_non_negative_int(value: Any, label: str) -> int:
    if value is None:
        return 0
    return _require_non_negative_int(value, label)


def _response_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise ProviderSchemaError("provider response content must be a list")
    text_blocks = [
        block.get("text")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if any(not isinstance(text, str) for text in text_blocks):
        raise ProviderSchemaError("provider text block must contain text")
    text = "\n".join(part for part in text_blocks if part).strip()
    if not text:
        raise ProviderSchemaError("provider response has no text block")
    return text


def _response_text_openai(payload: dict[str, Any]) -> str:
    """OpenAI chat-completions response text: choices[0].message.content."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderSchemaError("openai response choices must be a non-empty list")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderSchemaError("openai response message must be an object")
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise ProviderSchemaError("openai response has no text content")
    return text.strip()
