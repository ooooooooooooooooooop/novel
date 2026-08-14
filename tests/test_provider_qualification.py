"""G7/G8 Provider 资格门测试——角色资格由证据裁决，阈值不降.

锁死三件事：
1. 评审角色资格 = 冻结 holdout met + dimension_met 全真（0.65/0.5/0.9 取 policy，
   不二次测量、不降阈值）；任一维 false → not_qualified + 显式原因。
2. 生成角色资格 = 无人冒烟提交 ≥1 章 + 终态非 execution_failed + 投影成本 ≤ 预算。
3. 报告凭证无关：只含模型身份/门布尔/原因/证据标量，无正文/凭证/机器路径。
"""

import json

from src.object_state.autonomous import (
    AutonomousBudget,
    AutonomousEvaluationPolicy,
    AutonomousPolicy,
    ProviderProfile,
)
from src.workflow_action.provider_qualification import (
    ProviderCapabilityReport,
    qualify_generation,
    qualify_judge,
)


def _policy(ceiling: float = 10.0, chapters_per_run: int = 30) -> AutonomousPolicy:
    return AutonomousPolicy.model_validate(
        {
            "schema_version": "1.0",
            "policy_id": "p-test",
            "provider_profile_id": "prof-test",
            "runtime": {
                "manual_allowed": False,
                "waiting_allowed": False,
                "provider_fallback_allowed": False,
                "network_retry_allowed": False,
                "max_provider_attempts_per_call": 1,
                "resume_may_skip_gate": False,
            },
            "search": {
                "premise_candidates": 2,
                "plot_candidates": 2,
                "prose_variants_per_plot": 2,
                "max_decision_rounds": 1,
                "pairwise_orderings": ["A/B", "B/A"],
                "judge_roles": ["fact_judge", "character_judge", "reader_judge"],
            },
            "chapter": {
                "target_chinese_characters_min": 3000,
                "target_chinese_characters_max": 4000,
                "planner_max_output_tokens": 2000,
                "prose_max_output_tokens": 3000,
                "judge_max_output_tokens": 1500,
            },
            "budget": {
                "max_total_calls": 1000,
                "max_total_input_tokens": 10_000_000,
                "max_total_output_tokens": 5_000_000,
                "max_total_cost_usd": ceiling,
                "max_wall_clock_seconds": 3600,
                "max_chapters_per_run": chapters_per_run,
                "max_canary_runs": 3,
                "max_canary_chapters_total": chapters_per_run * 3,
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
                "preference_source": "bench.json",
                "preference_source_sha256": "0" * 64,
                "preference_split_manifest": "split.json",
                "preference_split_manifest_sha256": "0" * 64,
                "human_distribution_manifest": "human.json",
                "human_distribution_manifest_sha256": "0" * 64,
            },
            "canary": {
                "genres": ["contemporary_officialdom", "mythic_fantasy", "historical_strategy"],
                "chapters_per_genre": chapters_per_run,
                "long_horizon_checkpoints": [chapters_per_run],
            },
        }
    )


def _profile() -> ProviderProfile:
    return ProviderProfile.model_validate(
        {
            "schema_version": "1.0",
            "profile_id": "prof-test",
            "transport": "anthropic_messages_http",
            "endpoint": {
                "settings_path_from_user_home": ".claude/settings.json",
                "base_url_json_path": "env.ANTHROPIC_BASE_URL",
                "credential_json_path": "env.ANTHROPIC_AUTH_TOKEN",
                "messages_path": "/v1/messages",
                "auth_scheme": "bearer",
                "anthropic_version": "2023-06-01",
                "user_agent": "Test/1.0",
                "timeout_seconds": 60,
                "max_attempts": 1,
            },
            "provider_audit": {
                "database_path_from_user_home": ".cc-switch/cc-switch.db",
                "provider_id": "prism",
                "provider_name": "prism",
                "provider_category": "third_party",
                "upstream_url": "https://example.invalid",
                "expected_actual_model": "claude-sonnet-4-6",
                "failover_allowed": False,
            },
            "roles": {
                role: {
                    "request_model": "claude-sonnet-4-6",
                    "expected_actual_model": "claude-sonnet-4-6",
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
                "input": 3.0,
                "output": 15.0,
                "cache_read": 0.0,
                "cache_creation": 0.0,
                "source": "test",
                "frozen_at": "2026-08-13",
            },
            "smoke_evidence": {
                "request_model": "claude-sonnet-4-6",
                "actual_model": "claude-sonnet-4-6",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "status_code": 200,
            },
        }
    )


def _holdout(met: bool, overall: bool, per_tag: bool, position: bool) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": "r",
        "thresholds_id": "t-abc",
        "split": "holdout",
        "overall_accuracy": 0.7 if overall else 0.6,
        "per_tag_accuracy": {},
        "position_consistency": 0.95 if position else 0.5,
        "met": met,
        "dimension_met": {
            "overall": overall,
            "per_tag": per_tag,
            "position_consistency": position,
        },
        "violations": [] if met else ["test violation"],
        "run_at": "2026-08-13T00:00:00+00:00",
        "abstain_count": 0,
    }


def _terminal(status: str, committed: int, cost: float) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": "r",
        "status": status,
        "committed_chapters": committed,
        "usage": {
            "calls": 3,
            "input_tokens": 10000,
            "output_tokens": 8000,
            "cost_usd": cost,
        },
        "terminal_reason": None if status in ("completed", "narrative_stopped") else "boom",
        "accepted_candidate_id": "c1" if committed else None,
    }


# ---------------------------------------------------------------------------
# 评审角色资格
# ---------------------------------------------------------------------------

def test_judge_qualified_when_holdout_met_all_dims(tmp_path):
    h = tmp_path / "holdout_report.json"
    h.write_text(json.dumps(_holdout(True, True, True, True), ensure_ascii=False), encoding="utf-8")
    rep = qualify_judge(_profile(), _policy(), h)
    assert isinstance(rep, ProviderCapabilityReport)
    assert rep.qualified is True
    assert rep.role == "reader_judge"
    assert "thresholds_id=t-abc" in " ".join(rep.reasons)


def test_judge_not_qualified_when_any_dim_fails(tmp_path):
    for met, overall, per_tag, position in [
        (False, True, True, True),   # overall met=false
        (True, False, True, True),   # overall accuracy < 0.65
        (True, True, False, True),   # per-tag < 0.5
        (True, True, True, False),   # position < 0.9
    ]:
        h = tmp_path / "holdout_report.json"
        h.write_text(json.dumps(_holdout(met, overall, per_tag, position), ensure_ascii=False), encoding="utf-8")
        rep = qualify_judge(_profile(), _policy(), h)
        assert rep.qualified is False, (met, overall, per_tag, position)
        assert rep.reasons  # 显式原因
    # 不降阈值：失败原因必须引用冻结阈值本身（0.65/0.5/0.9 均来自 policy.evaluation）。
    h = tmp_path / "holdout_report.json"
    h.write_text(json.dumps(_holdout(True, False, True, True), ensure_ascii=False), encoding="utf-8")
    rep = qualify_judge(_profile(), _policy(), h)
    assert rep.qualified is False
    assert "0.65" in " ".join(rep.reasons)  # overall < 0.65 必须显式报出冻结下界


# ---------------------------------------------------------------------------
# 生成角色资格
# ---------------------------------------------------------------------------

def test_generation_qualified_after_committed_smoke(tmp_path):
    t = tmp_path / "terminal.json"
    t.write_text(json.dumps(_terminal("completed", 1, 0.3), ensure_ascii=False), encoding="utf-8")
    rep = qualify_generation(_profile(), _policy(ceiling=10.0), t)
    assert rep.qualified is True
    # 1 章 $0.3 → 30 章投影 $9 ≤ $10.
    assert rep.role == "generation"
    assert rep.cost_usd == 0.3


def test_generation_not_qualified_when_zero_committed(tmp_path):
    t = tmp_path / "terminal.json"
    t.write_text(json.dumps(_terminal("execution_failed", 0, 0.3), ensure_ascii=False), encoding="utf-8")
    rep = qualify_generation(_profile(), _policy(), t)
    assert rep.qualified is False
    assert "0 chapters committed" in " ".join(rep.reasons)


def test_generation_not_qualified_when_cost_exceeds_budget(tmp_path):
    # 单章成本过高：1 章 $20 → 30 章投影 $600 ≫ $10.
    t = tmp_path / "terminal.json"
    t.write_text(json.dumps(_terminal("completed", 1, 20.0), ensure_ascii=False), encoding="utf-8")
    rep = qualify_generation(_profile(), _policy(ceiling=10.0), t)
    assert rep.qualified is False
    assert "exceeds" in " ".join(rep.reasons)


def test_report_is_privacy_clean():
    # 报告只含标量/门布尔/模型身份；不得有正文、凭证或机器路径。
    rep = ProviderCapabilityReport(
        profile_id="prof-test",
        role="generation",
        request_model="m",
        actual_model="m",
        qualified=True,
        reasons=["ok"],
        evidence={"committed_chapters": 1},
        cost_usd=0.3,
        checked_at="2026-08-13T00:00:00+00:00",
    )
    blob = json.dumps(rep.model_dump(mode="json"), ensure_ascii=False)
    assert "ANTHROPIC" not in blob.upper()
    assert "C:" not in blob and "D:" not in blob
    assert "example.invalid" not in blob
