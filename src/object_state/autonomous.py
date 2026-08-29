"""A1 autonomous runtime contracts.

These objects belong only to the opt-in A1 runtime.  They do not change the
Tier 0 staged-response contracts and never contain provider credentials or
novel prose.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AutonomousTerminalStatus = Literal[
    "completed",
    "narrative_stopped",
    "premise_exhausted",
    "quality_exhausted",
    "evaluation_incomplete",
    "execution_failed",
]
AutonomousRunStatus = Literal[
    "created",
    "running",
    "committing",
    "completed",
    "narrative_stopped",
    "premise_exhausted",
    "quality_exhausted",
    "evaluation_incomplete",
    "execution_failed",
]
AutonomousDecisionRoute = Literal[
    "continue_generation",
    "search_premise",
    "reject_candidate",
    "accepted",
    "narrative_stopped",
    "premise_exhausted",
    "quality_exhausted",
    "evaluation_incomplete",
    "execution_failed",
]
ProviderCallStatus = Literal["success", "failed"]

TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "narrative_stopped",
        "premise_exhausted",
        "quality_exhausted",
        "evaluation_incomplete",
        "execution_failed",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderEndpoint(_StrictModel):
    settings_path_from_user_home: str = Field(min_length=1)
    base_url_json_path: str = Field(min_length=1)
    credential_json_path: str = Field(min_length=1)
    messages_path: str = Field(pattern=r"^/")
    auth_scheme: Literal["bearer", "x-api-key"]
    anthropic_version: str = Field(min_length=1)
    user_agent: str = Field(min_length=1)
    timeout_seconds: int = Field(gt=0)
    max_attempts: Literal[1]
    # api_format: "anthropic" (default) uses /v1/messages payload/response schema;
    # "openai" uses /v1/chat/completions schema.
    api_format: Literal["anthropic", "openai"] = "anthropic"


class ProviderAuditIdentity(_StrictModel):
    database_path_from_user_home: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    provider_category: str = Field(min_length=1)
    upstream_url: str = Field(min_length=1)
    expected_actual_model: str = Field(min_length=1)
    failover_allowed: Literal[False]
    # True for non-Claude providers (e.g. cpa/OpenAI gateway) that don't
    # have a cc-switch.db to verify against.  Classic Claude providers
    # must keep this False (default).
    skip_identity_check: bool = False


class ProviderRole(_StrictModel):
    request_model: str = Field(min_length=1)
    expected_actual_model: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)
    # Provider capability knob: send "thinking": {"type": "disabled"} on this
    # role's requests.  Required for thinking-native providers (e.g. kimi k3)
    # where hidden thinking tokens otherwise consume the whole judge output
    # budget and truncate the JSON text block.  Absent -> body unchanged.
    thinking_disabled: bool = False


class ProviderRoles(_StrictModel):
    generation: ProviderRole
    fact_judge: ProviderRole
    character_judge: ProviderRole
    reader_judge: ProviderRole


class ProviderPricing(_StrictModel):
    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_read: Decimal = Field(ge=0)
    cache_creation: Decimal = Field(ge=0)
    source: str = Field(min_length=1)
    frozen_at: str = Field(min_length=1)


class ProviderSmokeEvidence(_StrictModel):
    request_model: str = Field(min_length=1)
    actual_model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    status_code: int = Field(ge=100, le=599)


class ProviderProfile(_StrictModel):
    schema_version: Literal["1.0"]
    profile_id: str = Field(min_length=1)
    transport: Literal["anthropic_messages_http", "openai_chat_completions"]
    endpoint: ProviderEndpoint
    provider_audit: ProviderAuditIdentity
    roles: ProviderRoles
    pricing_usd_per_million_tokens: ProviderPricing
    smoke_evidence: ProviderSmokeEvidence

    @model_validator(mode="after")
    def _actual_model_identity_is_frozen(self) -> "ProviderProfile":
        expected = self.provider_audit.expected_actual_model
        roles = self.roles.model_dump().values()
        if any(role["expected_actual_model"] != expected for role in roles):
            raise ValueError("all provider roles must freeze the audited actual model")
        if not self.smoke_evidence.actual_model.startswith(expected):
            raise ValueError("smoke evidence actual model differs from provider audit")
        return self


class AutonomousRuntimeRules(_StrictModel):
    manual_allowed: Literal[False]
    waiting_allowed: Literal[False]
    provider_fallback_allowed: Literal[False]
    network_retry_allowed: Literal[False]
    max_provider_attempts_per_call: Literal[1]
    resume_may_skip_gate: Literal[False]


class AutonomousSearchPolicy(_StrictModel):
    premise_candidates: int = Field(gt=0)
    plot_candidates: int = Field(gt=1)
    prose_variants_per_plot: int = Field(gt=1)
    max_decision_rounds: int = Field(gt=0)
    pairwise_orderings: tuple[Literal["A/B", "B/A"], Literal["A/B", "B/A"]]
    judge_roles: tuple[
        Literal["fact_judge", "character_judge", "reader_judge"],
        Literal["fact_judge", "character_judge", "reader_judge"],
        Literal["fact_judge", "character_judge", "reader_judge"],
    ]

    @model_validator(mode="after")
    def _search_axes_are_distinct(self) -> "AutonomousSearchPolicy":
        if set(self.pairwise_orderings) != {"A/B", "B/A"}:
            raise ValueError("pairwise_orderings must contain A/B and B/A once each")
        if set(self.judge_roles) != {
            "fact_judge",
            "character_judge",
            "reader_judge",
        }:
            raise ValueError("judge_roles must contain all three isolated roles")
        return self


class AutonomousChapterPolicy(_StrictModel):
    target_chinese_characters_min: int = Field(gt=0)
    target_chinese_characters_max: int = Field(gt=0)
    planner_max_output_tokens: int = Field(gt=0)
    prose_max_output_tokens: int = Field(gt=0)
    judge_max_output_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def _character_range_is_ordered(self) -> "AutonomousChapterPolicy":
        if self.target_chinese_characters_min > self.target_chinese_characters_max:
            raise ValueError("chapter character minimum exceeds maximum")
        return self


class AutonomousBudget(_StrictModel):
    max_total_calls: int = Field(gt=0)
    max_total_input_tokens: int = Field(gt=0)
    max_total_output_tokens: int = Field(gt=0)
    max_total_cost_usd: Decimal = Field(gt=0)
    max_wall_clock_seconds: int = Field(gt=0)
    max_chapters_per_run: int = Field(gt=0)
    max_canary_runs: int = Field(gt=0)
    max_canary_chapters_total: int = Field(gt=0)

    @model_validator(mode="after")
    def _canary_budget_is_consistent(self) -> "AutonomousBudget":
        expected = self.max_chapters_per_run * self.max_canary_runs
        if expected != self.max_canary_chapters_total:
            raise ValueError("canary chapter total differs from runs times chapters")
        return self


class AutonomousEvaluationPolicy(_StrictModel):
    holdout_overall_accuracy_min: float = Field(gt=0.5, le=1.0)
    holdout_genre_accuracy_min: float = Field(ge=0.5, le=1.0)
    pairwise_position_consistency_min: float = Field(ge=0.9, le=1.0)
    hard_fact_conflicts_allowed: Literal[0]
    manual_routes_allowed: Literal[0]
    unarmed_required_axes_allowed: Literal[0]


class AutonomousBenchmarks(_StrictModel):
    preference_source: str = Field(min_length=1)
    preference_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preference_split_manifest: str = Field(min_length=1)
    preference_split_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_distribution_manifest: str = Field(min_length=1)
    human_distribution_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AutonomousCanaryPolicy(_StrictModel):
    genres: tuple[str, str, str]
    chapters_per_genre: int = Field(gt=0)
    long_horizon_checkpoints: tuple[int, ...]

    @model_validator(mode="after")
    def _canary_shape_is_valid(self) -> "AutonomousCanaryPolicy":
        if len(set(self.genres)) != 3 or any(not item.strip() for item in self.genres):
            raise ValueError("canary requires three distinct non-empty genres")
        if tuple(sorted(set(self.long_horizon_checkpoints))) != self.long_horizon_checkpoints:
            raise ValueError("long horizon checkpoints must be unique and increasing")
        if self.long_horizon_checkpoints[-1] != self.chapters_per_genre:
            raise ValueError("last checkpoint must equal chapters_per_genre")
        return self


class AutonomousPolicy(_StrictModel):
    schema_version: Literal["1.0"]
    policy_id: str = Field(min_length=1)
    provider_profile_id: str = Field(min_length=1)
    runtime: AutonomousRuntimeRules
    search: AutonomousSearchPolicy
    chapter: AutonomousChapterPolicy
    budget: AutonomousBudget
    evaluation: AutonomousEvaluationPolicy
    benchmarks: AutonomousBenchmarks
    canary: AutonomousCanaryPolicy

    @model_validator(mode="after")
    def _canary_budget_covers_shape(self) -> "AutonomousPolicy":
        requested = len(self.canary.genres) * self.canary.chapters_per_genre
        if requested != self.budget.max_canary_chapters_total:
            raise ValueError("canary shape differs from frozen chapter budget")
        return self


class AutonomousUsage(_StrictModel):
    calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)


class AutonomousRun(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_profile_id: str = Field(min_length=1)
    provider_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AutonomousRunStatus
    committed_chapters: int = Field(default=0, ge=0)
    usage: AutonomousUsage = Field(default_factory=AutonomousUsage)
    terminal_reason: str | None = None
    accepted_candidate_id: str | None = None

    @model_validator(mode="after")
    def _terminal_shape_is_valid(self) -> "AutonomousRun":
        terminal = self.status in TERMINAL_STATUSES
        if terminal and not self.terminal_reason:
            raise ValueError("terminal autonomous run requires terminal_reason")
        if not terminal and self.terminal_reason is not None:
            raise ValueError("non-terminal autonomous run cannot have terminal_reason")
        if self.status in {"committing", "completed"}:
            if not self.accepted_candidate_id:
                raise ValueError(f"{self.status} run requires accepted_candidate_id")
        elif self.accepted_candidate_id is not None:
            raise ValueError(
                "accepted_candidate_id is only valid while committing or completed"
            )
        return self


class AutonomousDecision(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    route: AutonomousDecisionRoute
    reasons: tuple[str, ...]
    accepted_candidate_id: str | None = None
    generation_allowed: bool
    commit_allowed: bool
    frame_advance_allowed: bool

    @model_validator(mode="after")
    def _decision_capabilities_match_route(self) -> "AutonomousDecision":
        if not self.reasons:
            raise ValueError("autonomous decision requires reasons")
        if self.route == "accepted":
            if not self.accepted_candidate_id:
                raise ValueError("accepted decision requires candidate id")
            if not self.commit_allowed or not self.frame_advance_allowed:
                raise ValueError("accepted decision must allow commit and frame advance")
        elif self.commit_allowed or self.frame_advance_allowed:
            raise ValueError("only accepted decision may commit or advance frame")
        if self.route == "narrative_stopped" and self.generation_allowed:
            raise ValueError("narrative_stopped cannot allow generation")
        return self


class ProviderCallAudit(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    call_id: str = Field(min_length=1)
    status: ProviderCallStatus
    role: Literal["generation", "fact_judge", "character_judge", "reader_judge"]
    endpoint_identity: str = Field(min_length=1)
    request_model: str = Field(min_length=1)
    actual_model: str | None = None
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(gt=0)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_creation_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    started_at_utc: str = Field(min_length=1)
    ended_at_utc: str = Field(min_length=1)
    error_type: str | None = None

    @model_validator(mode="after")
    def _audit_shape_matches_status(self) -> "ProviderCallAudit":
        if self.status == "success":
            if not self.actual_model or not self.response_sha256:
                raise ValueError("successful provider audit requires response identity")
            if self.error_type is not None:
                raise ValueError("successful provider audit cannot contain error_type")
        elif not self.error_type:
            raise ValueError("failed provider audit requires error_type")
        return self


def _canonicalize_value(value):
    """Normalize values so canonical hash is independent of load path.

    Pydantic renders ``Decimal`` fields as ``str`` in ``mode="json"`` and the
    exact string depends on how the model was loaded: ``model_validate_json``
    keeps ``10`` as ``Decimal('10')`` -> ``"10"``, while
    ``model_validate(json.loads(...))`` sees float ``10.0`` -> ``"10.0"``.
    Normalizing every Decimal before serialization makes the hash identical for
    both load paths, so a run manifest's ``policy_sha256``/``provider_profile_sha256``
    always matches the G0 record of the same frozen file.
    """
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, dict):
        return {k: _canonicalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_value(v) for v in value]
    return value


def canonical_model_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        _canonicalize_value(model.model_dump(mode="python")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"running", "execution_failed"}),
    "running": frozenset(
        {
            "committing",
            "completed",
            "narrative_stopped",
            "premise_exhausted",
            "quality_exhausted",
            "evaluation_incomplete",
            "execution_failed",
        }
    ),
    "committing": frozenset({"running", "completed", "execution_failed"}),
}


def transition_autonomous_run(
    run: AutonomousRun,
    status: AutonomousRunStatus,
    *,
    terminal_reason: str | None = None,
    accepted_candidate_id: str | None = None,
    committed_chapters: int | None = None,
) -> AutonomousRun:
    if run.status in TERMINAL_STATUSES:
        raise ValueError(f"terminal autonomous run cannot transition: {run.status}")
    allowed = _ALLOWED_TRANSITIONS[run.status]
    if status not in allowed:
        raise ValueError(f"illegal autonomous run transition: {run.status} -> {status}")
    chapter_count = run.committed_chapters if committed_chapters is None else committed_chapters
    if chapter_count < run.committed_chapters:
        raise ValueError("committed chapter count cannot decrease")
    payload = run.model_dump(mode="python")
    payload.update(
        {
            "status": status,
            "terminal_reason": terminal_reason,
            "accepted_candidate_id": accepted_candidate_id,
            "committed_chapters": chapter_count,
        }
    )
    return AutonomousRun.model_validate(payload)


def charge_usage(
    usage: AutonomousUsage,
    budget: AutonomousBudget,
    *,
    calls: int,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
) -> AutonomousUsage:
    if calls < 0 or input_tokens < 0 or output_tokens < 0 or cost_usd < 0:
        raise ValueError("usage charge values must be non-negative")
    charged = AutonomousUsage(
        calls=usage.calls + calls,
        input_tokens=usage.input_tokens + input_tokens,
        output_tokens=usage.output_tokens + output_tokens,
        cost_usd=usage.cost_usd + cost_usd,
    )
    exceeded: list[str] = []
    if charged.calls > budget.max_total_calls:
        exceeded.append("calls")
    if charged.input_tokens > budget.max_total_input_tokens:
        exceeded.append("input_tokens")
    if charged.output_tokens > budget.max_total_output_tokens:
        exceeded.append("output_tokens")
    if charged.cost_usd > budget.max_total_cost_usd:
        exceeded.append("cost_usd")
    if exceeded:
        raise ValueError(f"autonomous budget exceeded: {', '.join(exceeded)}")
    return charged
