"""T5 — 多 PlotUnit 候选搜索单元测试（design §7；doc 48 §6 step 6）.

覆盖：规范化压缩（事件身份不变纪律）、候选批次严格解析、输出状态变化签名、
语义去重（首现优先封顶）、G5 数量/差异约束确定性验证器、state_necessity
计划层闸（effective 单元无状态变化 → 硬违例）。
"""

import pytest
from pydantic import ValidationError

from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.plan_search import (
    build_plot_batch_prompt,
    compact_text,
    dedup_plan_candidates,
    parse_plot_batch_response,
    plan_candidate_signature,
    state_necessity_violation,
    verify_plan_diversity,
)


def _plotunit(unit_id="pu_001", *, released=("释放A",), consequences=("后果B",),
              is_effective=True, conflict="冲突", **overrides) -> PlotUnit:
    payload = {
        "unit_id": unit_id,
        "level": "scene",
        "goal": "推进",
        "participants": ["c001"],
        "conflict": conflict,
        "input_state_ref": "ns_001",
        "output_state_ref": "ns_002",
        "released_information": list(released),
        "consequences": list(consequences),
        "is_effective": is_effective,
    }
    payload.update(overrides)
    return PlotUnit(**payload)


def _state(state_id="ns_002", *, location="地点", situation="局势",
           time="稍后", chars=("c001",)) -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time=time,
        current_location=location,
        current_situation=situation,
        active_characters=list(chars),
    )


def _input_state() -> NarrativeState:
    return NarrativeState(
        state_id="ns_001",
        current_time="夜晚",
        current_location="案发现场",
        current_situation="调查开始",
        active_characters=["c001"],
    )


def _plan(plotunit, new_state, new_facts=None, gaps=None):
    return (plotunit, new_state, new_facts or [], gaps or [])


# ---------------------------------------------------------------- compact_text


class TestCompactText:
    def test_strips_whitespace_and_punct_keeps_chars(self):
        assert compact_text("他，走了。她？") == "他走了她"

    def test_nfkc_normalizes_fullwidth(self):
        assert compact_text("ＡＢＣ（甲）") == "ABC甲"

    def test_empty_and_none(self):
        assert compact_text("") == ""
        assert compact_text(None) == ""

    def test_particle_alternation_is_whole_word(self):
        # 整个短语「于是」按字类删会把「于」从「终于」里剥掉，改变事件身份。
        assert compact_text("于是……终于") == "于是终于"


# ---------------------------------------------------------------- prompt


class TestBuildPlotBatchPrompt:
    def test_wraps_base_prompt_without_duplicating_context(self):
        base = "【续写要求】……【输出格式】……"
        wrapped = build_plot_batch_prompt(base, count=3)
        assert "【多候选要求】" in wrapped
        assert "3 个互不相同" in wrapped
        # 不重复注入上下文：字节只追加。
        assert wrapped.startswith(base)

    def test_count_must_be_positive(self):
        with pytest.raises(ValueError):
            build_plot_batch_prompt("base", count=0)


# ---------------------------------------------------------------- parse


class TestParsePlotBatchResponse:
    def test_parses_valid_batch(self):
        payload = {
            "candidates": [
                {
                    "plotunit": _plotunit("pu_001").model_dump(),
                    "new_state": _state().model_dump(),
                    "new_facts": [],
                    "confidence_gaps": ["还缺动机"],
                }
            ]
        }
        parsed = parse_plot_batch_response(
            '{"candidates": ['
            + '{"plotunit": ' + _plotunit("pu_001").model_dump_json()
            + ', "new_state": ' + _state().model_dump_json()
            + ', "new_facts": [], "confidence_gaps": ["还缺动机"]}]}',
            count=2,
        )
        assert len(parsed) == 1
        plotunit, new_state, new_facts, gaps = parsed[0]
        assert plotunit.unit_id == "pu_001"
        assert new_state.current_situation == "局势"
        assert new_facts == []
        assert gaps == ["还缺动机"]

    def test_extra_key_rejected(self):
        with pytest.raises(ValueError, match="only 'candidates'"):
            parse_plot_batch_response('{"candidates": [], "extra": 1}', count=2)

    def test_empty_list_rejected(self):
        with pytest.raises(ValueError, match="between 1 and"):
            parse_plot_batch_response('{"candidates": []}', count=2)

    def test_over_count_rejected(self):
        item = (
            '{"plotunit": ' + _plotunit("pu_x").model_dump_json()
            + ', "new_state": ' + _state().model_dump_json()
            + ', "new_facts": [], "confidence_gaps": []}'
        )
        with pytest.raises(ValueError, match="between 1 and"):
            parse_plot_batch_response('{"candidates": [' + item + "," + item + "]}", count=1)

    def test_candidate_missing_field_rejected(self):
        with pytest.raises(ValueError, match="missing field"):
            parse_plot_batch_response(
                '{"candidates": [{"plotunit": '
                + _plotunit("pu_x").model_dump_json()
                + ', "new_state": ' + _state().model_dump_json()
                + ', "new_facts": []}]}',
                count=1,
            )

    def test_bad_gaps_rejected(self):
        with pytest.raises(ValueError, match="confidence_gaps"):
            parse_plot_batch_response(
                '{"candidates": [{"plotunit": '
                + _plotunit("pu_x").model_dump_json()
                + ', "new_state": ' + _state().model_dump_json()
                + ', "new_facts": [], "confidence_gaps": ["  "]}]}',
                count=1,
            )

    def test_invalid_plotunit_model_rejected(self):
        with pytest.raises(ValidationError):
            parse_plot_batch_response(
                '{"candidates": [{"plotunit": {"unit_id": ""}, "new_state": '
                + _state().model_dump_json()
                + ', "new_facts": [], "confidence_gaps": []}]}',
                count=1,
            )


# ---------------------------------------------------------------- signature / dedup


class TestPlanCandidateSignature:
    def test_signature_changes_with_output_state_change(self):
        a = _plan(_plotunit("pu_a"), _state(location="东"), [])
        b = _plan(_plotunit("pu_b"), _state(location="西"), [])
        assert plan_candidate_signature(a) != plan_candidate_signature(b)

    def test_signature_changes_with_released_information(self):
        a = _plan(_plotunit("pu_a", released=("甲",)), _state(), [])
        b = _plan(_plotunit("pu_b", released=("乙",)), _state(), [])
        assert plan_candidate_signature(a) != plan_candidate_signature(b)

    def test_signature_same_for_equal_plans(self):
        a = _plan(_plotunit("pu_a"), _state(), [])
        b = _plan(_plotunit("pu_b"), _state(), [])
        assert plan_candidate_signature(a) == plan_candidate_signature(b)


class TestDedupPlanCandidates:
    def test_duplicate_output_state_change_keeps_first(self):
        plans = [
            _plan(_plotunit("pu_a"), _state(location="东"), []),
            _plan(_plotunit("pu_b"), _state(location="东"), []),  # 同签名
        ]
        kept = dedup_plan_candidates(plans, max_candidates=4)
        assert len(kept) == 1
        assert kept[0][0].unit_id == "pu_a"

    def test_distinct_survive_and_capped(self):
        plans = [
            _plan(_plotunit("pu_a"), _state(location="东"), []),
            _plan(_plotunit("pu_b"), _state(location="西"), []),
            _plan(_plotunit("pu_c"), _state(location="南"), []),
        ]
        kept = dedup_plan_candidates(plans, max_candidates=2)
        assert [plan[0].unit_id for plan in kept] == ["pu_a", "pu_b"]

    def test_max_candidates_must_be_positive(self):
        with pytest.raises(ValueError):
            dedup_plan_candidates([], max_candidates=0)


class TestVerifyPlanDiversity:
    def test_empty_rejected(self):
        ok, reason = verify_plan_diversity([], max_candidates=3)
        assert not ok
        assert "no plot candidate" in reason

    def test_exceeding_max_rejected(self):
        plans = [
            _plan(_plotunit("pu_a"), _state(location="东"), []),
            _plan(_plotunit("pu_b"), _state(location="西"), []),
        ]
        ok, reason = verify_plan_diversity(plans, max_candidates=1)
        assert not ok
        assert "exceed" in reason

    def test_duplicate_signature_rejected(self):
        plans = [
            _plan(_plotunit("pu_a"), _state(location="东"), []),
            _plan(_plotunit("pu_b"), _state(location="东"), []),
        ]
        ok, reason = verify_plan_diversity(plans, max_candidates=3)
        assert not ok
        assert "duplicate" in reason

    def test_valid_accepted(self):
        plans = [
            _plan(_plotunit("pu_a"), _state(location="东"), []),
            _plan(_plotunit("pu_b"), _state(location="西"), []),
        ]
        ok, reason = verify_plan_diversity(plans, max_candidates=3)
        assert ok
        assert "2 distinct" in reason


# ---------------------------------------------------------------- state_necessity


class TestStateNecessityViolation:
    def test_effective_no_change_is_hard_violation(self):
        plotunit = _plotunit(is_effective=True)
        violation = state_necessity_violation(
            plotunit, _input_state(), _input_state()
        )
        assert violation is not None
        axis, reason = violation
        assert axis == "state_necessity"
        assert "完全相同" in reason

    def test_effective_with_change_passes(self):
        violation = state_necessity_violation(
            _plotunit(is_effective=True), _input_state(), _state(location="茶楼")
        )
        assert violation is None

    def test_effective_time_change_counts(self):
        violation = state_necessity_violation(
            _plotunit(is_effective=True), _input_state(), _state(time="三日后")
        )
        assert violation is None

    def test_non_effective_not_enforced(self):
        violation = state_necessity_violation(
            _plotunit(is_effective=False), _input_state(), _input_state()
        )
        assert violation is None
