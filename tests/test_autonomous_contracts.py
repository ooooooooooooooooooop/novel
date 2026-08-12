from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.object_state.autonomous import (
    AutonomousBudget,
    AutonomousPolicy,
    AutonomousRun,
    AutonomousUsage,
    ProviderProfile,
    canonical_model_sha256,
    charge_usage,
    transition_autonomous_run,
)
from src.workflow_action.autonomous_decision import resolve_autonomous_decision


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
            "timeout_seconds": 120,
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


def _policy_payload() -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "policy-a",
        "provider_profile_id": "provider-a",
        "runtime": {
            "manual_allowed": False,
            "waiting_allowed": False,
            "provider_fallback_allowed": False,
            "network_retry_allowed": False,
            "max_provider_attempts_per_call": 1,
            "resume_may_skip_gate": False,
        },
        "search": {
            "premise_candidates": 4,
            "plot_candidates": 4,
            "prose_variants_per_plot": 2,
            "max_decision_rounds": 2,
            "pairwise_orderings": ["A/B", "B/A"],
            "judge_roles": ["fact_judge", "character_judge", "reader_judge"],
        },
        "chapter": {
            "target_chinese_characters_min": 2500,
            "target_chinese_characters_max": 5000,
            "planner_max_output_tokens": 2000,
            "prose_max_output_tokens": 6000,
            "judge_max_output_tokens": 1500,
        },
        "budget": {
            "max_total_calls": 100,
            "max_total_input_tokens": 1000,
            "max_total_output_tokens": 500,
            "max_total_cost_usd": 1,
            "max_wall_clock_seconds": 1000,
            "max_chapters_per_run": 30,
            "max_canary_runs": 3,
            "max_canary_chapters_total": 90,
        },
        "evaluation": {
            "holdout_overall_accuracy_min": 0.65,
            "holdout_genre_accuracy_min": 0.5,
            "pairwise_position_consistency_min": 0.9,
            "hard_fact_conflicts_allowed": 0,
            "manual_routes_allowed": 0,
            "unarmed_required_axes_allowed": 0,
        },
        "benchmarks": {
            "preference_source": "source.json",
            "preference_source_sha256": "a" * 64,
            "preference_split_manifest": "split.json",
            "preference_split_manifest_sha256": "b" * 64,
            "human_distribution_manifest": "human.json",
            "human_distribution_manifest_sha256": "c" * 64,
        },
        "canary": {
            "genres": ["one", "two", "three"],
            "chapters_per_genre": 30,
            "long_horizon_checkpoints": [1, 3, 5, 10, 20, 30],
        },
    }


def _run(status: str = "created", **updates) -> AutonomousRun:
    payload = {
        "run_id": "run-a",
        "policy_id": "policy-a",
        "policy_sha256": "a" * 64,
        "provider_profile_id": "provider-a",
        "provider_profile_sha256": "b" * 64,
        "status": status,
    }
    payload.update(updates)
    return AutonomousRun.model_validate(payload)


def _decision(**updates):
    payload = {
        "provider_error": None,
        "viability_verdict": "continue",
        "premise_candidates_remaining": 0,
        "required_axes_armed": True,
        "reader_route": "pass",
        "hard_violation": None,
        "candidates_remaining": 1,
        "budget_available": True,
        "accepted_candidate_id": None,
    }
    payload.update(updates)
    return resolve_autonomous_decision(**payload)


def test_provider_profile_freezes_actual_model_identity():
    profile = ProviderProfile.model_validate(_profile_payload())
    assert profile.provider_audit.expected_actual_model == "model-a"
    assert profile.endpoint.max_attempts == 1


def test_provider_profile_rejects_alias_as_different_actual_model():
    payload = _profile_payload()
    payload["roles"]["reader_judge"]["expected_actual_model"] = "alias-b"
    with pytest.raises(ValidationError, match="audited actual model"):
        ProviderProfile.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manual_allowed", True),
        ("waiting_allowed", True),
        ("provider_fallback_allowed", True),
        ("network_retry_allowed", True),
        ("resume_may_skip_gate", True),
        ("max_provider_attempts_per_call", 2),
    ],
)
def test_policy_rejects_human_or_fallback_runtime(field, value):
    payload = _policy_payload()
    payload["runtime"][field] = value
    with pytest.raises(ValidationError):
        AutonomousPolicy.model_validate(payload)


def test_policy_rejects_inconsistent_canary_budget():
    payload = _policy_payload()
    payload["budget"]["max_canary_chapters_total"] = 89
    with pytest.raises(ValidationError, match="canary chapter total"):
        AutonomousPolicy.model_validate(payload)


def test_policy_hash_is_canonical():
    left = AutonomousPolicy.model_validate(_policy_payload())
    right_payload = deepcopy(_policy_payload())
    right = AutonomousPolicy.model_validate(right_payload)
    assert canonical_model_sha256(left) == canonical_model_sha256(right)


def test_run_terminal_requires_reason_and_cannot_transition():
    with pytest.raises(ValidationError, match="terminal_reason"):
        _run("narrative_stopped")
    stopped = _run("narrative_stopped", terminal_reason="story ended")
    with pytest.raises(ValueError, match="cannot transition"):
        transition_autonomous_run(stopped, "running")


def test_run_transition_requires_candidate_while_committing():
    running = transition_autonomous_run(_run(), "running")
    with pytest.raises(ValidationError, match="accepted_candidate_id"):
        transition_autonomous_run(running, "committing")
    committing = transition_autonomous_run(
        running, "committing", accepted_candidate_id="candidate-a"
    )
    assert committing.status == "committing"


def test_run_cannot_decrease_committed_chapters():
    run = _run("running", committed_chapters=2)
    with pytest.raises(ValueError, match="cannot decrease"):
        transition_autonomous_run(run, "completed", committed_chapters=1)


def test_provider_error_has_priority_over_stop():
    decision = _decision(provider_error="schema invalid", viability_verdict="stop")
    assert decision.route == "execution_failed"
    assert decision.commit_allowed is False


def test_stop_blocks_generation_even_when_reader_would_continue():
    decision = _decision(viability_verdict="stop", reader_route="pass")
    assert decision.route == "narrative_stopped"
    assert decision.generation_allowed is False


def test_needs_premise_searches_or_exhausts_without_manual_route():
    searching = _decision(
        viability_verdict="needs_premise", premise_candidates_remaining=4
    )
    exhausted = _decision(
        viability_verdict="needs_premise", premise_candidates_remaining=0
    )
    assert searching.route == "search_premise"
    assert exhausted.route == "premise_exhausted"


def test_manual_and_unarmed_routes_become_explicit_incomplete_terminal():
    assert _decision(reader_route="manual").route == "evaluation_incomplete"
    assert _decision(required_axes_armed=False).route == "evaluation_incomplete"


def test_hard_failure_rejects_candidate_then_exhausts():
    rejected = _decision(hard_violation="fact conflict", candidates_remaining=1)
    exhausted = _decision(hard_violation="fact conflict", candidates_remaining=0)
    assert rejected.route == "reject_candidate"
    assert rejected.frame_advance_allowed is False
    assert exhausted.route == "quality_exhausted"


def test_only_accepted_candidate_can_commit_and_advance_frame():
    decision = _decision(accepted_candidate_id="candidate-a")
    assert decision.route == "accepted"
    assert decision.commit_allowed is True
    assert decision.frame_advance_allowed is True


def test_long_horizon_block_maps_to_quality_exhausted():
    # design §4：长程对账漂移 → quality_exhausted 终态（六终态契约不变）
    decision = _decision(long_horizon_block="promise never grounded")
    assert decision.route == "quality_exhausted"
    assert decision.generation_allowed is False
    assert decision.commit_allowed is False
    assert decision.frame_advance_allowed is False
    assert any("long-horizon" in r for r in decision.reasons)


def test_long_horizon_block_has_priority_over_candidate_acceptance():
    # 即使候选已过硬门，长程漂移仍阻断（drift > quality disagreement > candidate）
    decision = _decision(
        accepted_candidate_id="candidate-a", long_horizon_block="seam drift"
    )
    assert decision.route == "quality_exhausted"
    assert decision.accepted_candidate_id is None


def test_long_horizon_block_is_weaker_than_provider_error_and_stop():
    assert _decision(
        provider_error="boom", long_horizon_block="drift"
    ).route == "execution_failed"
    assert _decision(
        viability_verdict="stop", long_horizon_block="drift"
    ).route == "narrative_stopped"
    assert _decision(
        viability_verdict="needs_premise", premise_candidates_remaining=2,
        long_horizon_block="drift",
    ).route == "search_premise"
    assert _decision(
        hard_violation="fact conflict", candidates_remaining=1,
        long_horizon_block="drift",
    ).route == "reject_candidate"


def test_budget_charge_is_exact_and_rejects_overflow():
    budget = AutonomousBudget.model_validate(_policy_payload()["budget"])
    usage = charge_usage(
        AutonomousUsage(),
        budget,
        calls=1,
        input_tokens=10,
        output_tokens=5,
        cost_usd=Decimal("0.01"),
    )
    assert usage.cost_usd == Decimal("0.01")
    with pytest.raises(ValueError, match="cost_usd"):
        charge_usage(
            usage,
            budget,
            calls=0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("1"),
        )
