"""T3 Phase 1: deterministic consequence + anchor-distance Pareto axes."""

import json

from src.object_state.narrativestate import NarrativeState
from src.object_state.structural_search import (
    ParetoDimensionScores,
    RolloutDelta,
    RolloutEvaluation,
    RolloutStateSnapshot,
    RolloutStep,
    RolloutTransition,
    StructuralProposal,
)
from src.object_state.workspec import WorkSpec
from src.workflow_action import structural_search
from src.workflow_action.structural_search import (
    compute_structural_pareto_frontier,
    score_structural_pareto,
)


LEGACY_SCORE_FIELDS = {
    "causal_value": 0.8,
    "character_value": 0.7,
    "reader_momentum": 0.6,
    "work_alignment": 0.5,
    "originality": 0.4,
    "sustainability": 0.9,
    "risk_penalty": 0.1,
}


def _proposal(name: str = "p") -> StructuralProposal:
    return StructuralProposal(
        proposal_id=name,
        primary_actor="主角",
        core_choice="承担代价取得关键证据",
        resistance_source="敌对势力封锁",
        cost="承受伤势并暴露退路",
        state_change="获得关键证据并改变追查方向",
        relationship_change="与盟友建立互信",
        information_reveal="证据指向幕后者",
        impact_next_3_to_5_chapters="追查幕后者",
        chapter_function="推进",
    )


def _rollout(*, risk_flags=None, advances=True) -> RolloutEvaluation:
    initial = RolloutStateSnapshot(
        step_index=0,
        state_id="state",
        current_situation="初始局势",
        open_questions=["幕后者是谁"],
        active_conflicts=["追查冲突"],
        active_threads=["promise-1"],
        character_pressures={},
        facts_count=0,
        prohibitions_checked=[],
    )
    final = RolloutStateSnapshot(
        step_index=1,
        state_id="state",
        current_situation="证据已落地",
        open_questions=["幕后者是谁", "证据如何使用"],
        active_conflicts=["追查冲突"],
        active_threads=["promise-1"],
        character_pressures={"主角": ["承受伤势"]},
        facts_count=1,
        prohibitions_checked=[],
    )
    delta = RolloutDelta(
        step_from=0,
        step_to=1,
        situation_delta="初始局势 -> 证据已落地",
        pressure_deltas={"主角": ["承受伤势"]},
        relationship_shifts=["互信建立"],
        new_facts_count=1,
        foreshadow_advancements=["promise-1"] if advances else [],
        rule_violations=[],
    )
    step = RolloutStep(
        step_index=1,
        projected_situation="证据落地",
        fatigue_index=0.1,
        escalation_debt=0.1,
        delayed_payoff_yield=0.8,
        rule_break_risk=0.0,
        sustainability=0.9,
        notes=[],
    )
    transition = RolloutTransition(
        from_snapshot=initial,
        delta=delta,
        to_snapshot=final,
        step_metrics=step,
    )
    return RolloutEvaluation(
        proposal_id="p",
        steps=[step],
        transitions=[transition],
        initial_snapshot=initial,
        final_snapshot=final,
        overall_sustainability=0.9,
        immediate_stimulus_vs_longterm_risk=0.8,
        delayed_payoff_potential=0.8,
        risk_flags=list(risk_flags or []),
        summary="deterministic fixture",
    )


def _state_objects():
    state = NarrativeState(
        state_id="state",
        current_time="春",
        current_location="城中",
        current_situation="追查开始",
        active_conflicts=["追查冲突"],
        emotional_temperature="紧张",
    )
    workspec = WorkSpec(genre="悬疑", audience="读者", theme="因果", tone="克制", pacing="稳")
    return state, [state, workspec], workspec


def test_t3_off_preserves_serialized_shape_and_frontier_order():
    score = ParetoDimensionScores(**LEGACY_SCORE_FIELDS)
    assert score.model_dump() == LEGACY_SCORE_FIELDS
    expected_json = json.dumps(LEGACY_SCORE_FIELDS, ensure_ascii=False, separators=(",", ":"))
    assert score.model_dump_json() == expected_json
    assert "consequence_reward" not in score.to_dimension_dict()
    assert "anchor_distance" not in score.to_dimension_dict()

    legacy_scores = {
        "a": ParetoDimensionScores(**LEGACY_SCORE_FIELDS),
        "b": ParetoDimensionScores(**{**LEGACY_SCORE_FIELDS, "causal_value": 0.7}),
    }
    assert compute_structural_pareto_frontier(["a", "b"], legacy_scores) == ["a"]


def test_t3_on_without_anchor_adds_only_consequence_axis():
    state, objects, workspec = _state_objects()
    score = score_structural_pareto(
        _proposal(),
        _rollout(),
        state,
        objects,
        workspec=workspec,
        t3_phase1_enabled=True,
    )
    assert score.consequence_reward is not None
    assert score.anchor_distance is None
    assert "consequence_reward" in score.to_dimension_dict()
    assert "anchor_distance" not in score.to_dimension_dict()


def test_t3_on_with_anchor_reports_two_independent_axes():
    state, objects, workspec = _state_objects()
    anchor_context = {
        "candidate_fingerprint": {"scene_transition_rate": 0.9, "stage_position": 0.9},
        "anchors": [
            {"statistical_fingerprint": {"scene_transition_rate": 0.1, "stage_position": 0.1}}
        ],
    }
    score = score_structural_pareto(
        _proposal(),
        _rollout(),
        state,
        objects,
        workspec=workspec,
        t3_phase1_enabled=True,
        anchor_context=anchor_context,
    )
    dimensions = score.to_dimension_dict()
    assert score.consequence_reward is not None
    assert score.anchor_distance is not None
    assert "consequence_reward" in dimensions
    assert "anchor_distance" in dimensions
    assert "total_score" not in dimensions


def test_t3_bad_consequences_score_below_valid_state_change_and_promise_progress():
    good = structural_search._consequence_reward(_rollout())
    bad = structural_search._consequence_reward(
        _rollout(risk_flags=["dead_end", "causal_contradiction", "promise_overdue"], advances=False)
    )
    assert good > bad
    assert bad == 0.0


def test_t3_empty_or_missing_anchor_context_is_anchor_noop():
    state, objects, workspec = _state_objects()
    for anchor_context in (None, {}, {"anchors": []}, {"anchors": [{}]}):
        score = score_structural_pareto(
            _proposal(),
            _rollout(),
            state,
            objects,
            workspec=workspec,
            t3_phase1_enabled=True,
            anchor_context=anchor_context,
        )
        assert score.anchor_distance is None
        assert "anchor_distance" not in score.to_dimension_dict()


def test_t3_scoring_path_has_no_llm_judge(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("T3 Phase 1 must not call an LLM judge")

    monkeypatch.setattr(structural_search, "llm_judge", fail_if_called, raising=False)
    monkeypatch.setattr(structural_search, "judge_pareto", fail_if_called, raising=False)
    state, objects, workspec = _state_objects()
    score = score_structural_pareto(
        _proposal(),
        _rollout(),
        state,
        objects,
        workspec=workspec,
        t3_phase1_enabled=True,
        anchor_context={"anchors": [{"statistical_fingerprint": {"stage_position": 0.1}}]},
    )
    assert score.consequence_reward is not None
