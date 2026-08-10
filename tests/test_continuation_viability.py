"""Q1 Phase 3 — ContinuationViabilityUnit：续写可行性确定性判定.

R1：生成 PlotUnit 之前先判「是否还有有效下一步」。纯代码确定性信号
（no_active_frame / 活跃承诺 / 终止型节点 / 读者契约结束条件）直接判
continue / stop / needs_premise；信号冲突 → deterministic=False（交操作者）。
"""

from src.object_state import ForeshadowEntry, ForeshadowGraph, NarrativeState
from src.object_state.continuation_viability import (
    TERMINAL_FORMULA_NODES,
    ViabilityVerdict,
)
from src.object_state.readercontract import ReaderContract
from src.workflow_action.continuation_viability import (
    ContinuationViabilityUnit,
    analyze_continuation_viability,
    viability_continue_note,
)


def _state(situation: str = "当前局势") -> NarrativeState:
    return NarrativeState(
        state_id="ns_t",
        current_time="夜晚",
        current_location="场景",
        current_situation=situation,
        active_characters=["c001"],
    )


def _foreshadows(*contents: str) -> ForeshadowGraph:
    entries = [
        ForeshadowEntry(
            thread_id=f"th_{i}",
            setup_point="第1章",
            content=content,
            visibility_level="explicit",
            expected_payoff="回收",
            current_status="active",
        )
        for i, content in enumerate(contents)
    ]
    return ForeshadowGraph(entries=entries)


def _frame(no_active: bool, formula_node: str = "") -> dict:
    if no_active:
        return {
            "cursor": None,
            "current_frame": None,
            "parent_chain": [],
            "sibling_context": [],
            "active_threads": [],
            "no_active_frame": True,
        }
    return {
        "cursor": {"current_frame_id": "scene_001", "current_level": "scene"},
        "current_frame": {
            "frame_id": "scene_001",
            "level": "scene",
            "title": "场景",
            "purpose": "推进",
            "position": "middle",
            "status": "active",
            "formula_node": formula_node,
        },
        "parent_chain": [],
        "sibling_context": [],
        "active_threads": [],
        "no_active_frame": False,
    }


def _contract(ending_conditions: list[str]) -> ReaderContract:
    return ReaderContract(
        contract_id="default",
        audience="大众网文读者",
        core_pleasures=["围绕「核心矛盾」的张力推进", "每章产生可感知的新状态变化"],
        follow_reason="主角在压力下做出代价明确的选择",
        core_tension="「核心矛盾」驱动下的持续对抗",
        chapter_pacing="每章推进一个量级的事件",
        ending_conditions=ending_conditions,
        opening_minimum_promise="首章主角必须做出定义人物的主动选择",
    )


def test_fresh_active_frame_defaults_continue():
    """fresh 工作区（活跃帧、无冲突信号）→ 确定性 continue（不改变现有流程）."""
    d = analyze_continuation_viability(
        narrative_state=_state(),
        foreshadows=_foreshadows(),
        frame_context=_frame(no_active=False),
    )
    assert d.verdict == "continue"
    assert d.deterministic is True
    assert any("活跃叙事帧" in r for r in d.reasons)


def test_no_active_frame_no_promises_stop():
    """整个结构已完成且无未兑现承诺 → 确定性 stop."""
    d = analyze_continuation_viability(
        narrative_state=_state(),
        foreshadows=_foreshadows(),
        frame_context=_frame(no_active=True),
    )
    assert d.verdict == "stop"
    assert d.deterministic is True
    assert d.required_premise is None
    assert any("故事结构已完成" in r for r in d.reasons)


def test_no_active_frame_with_open_promises_needs_premise():
    """结构完成但仍有活跃承诺 → 确定性 needs_premise + required_premise."""
    d = analyze_continuation_viability(
        narrative_state=_state(),
        foreshadows=_foreshadows("身世之谜未解", "约定尚未兑现"),
        frame_context=_frame(no_active=True),
    )
    assert d.verdict == "needs_premise"
    assert d.deterministic is True
    assert d.required_premise is not None
    assert "2" in d.required_premise or "2" in " ".join(d.reasons)


def test_active_frame_ending_matched_no_promises_stop():
    """活跃帧但契约结束条件触发且无承诺 → 确定性 stop."""
    contract = _contract(ending_conditions=["尘埃落定"])
    d = analyze_continuation_viability(
        narrative_state=_state(situation="尘埃落定之后"),
        foreshadows=_foreshadows(),
        frame_context=_frame(no_active=False),
        contract=contract,
    )
    assert d.verdict == "stop"
    assert d.deterministic is True


def test_active_frame_ending_matched_with_promises_ambiguous():
    """契约要求结束但仍有未兑现承诺 → 信号冲突，deterministic=False."""
    contract = _contract(ending_conditions=["尘埃落定"])
    d = analyze_continuation_viability(
        narrative_state=_state(situation="尘埃落定"),
        foreshadows=_foreshadows("悬念未解"),
        frame_context=_frame(no_active=False),
        contract=contract,
    )
    assert d.verdict == "needs_premise"
    assert d.deterministic is False
    assert d.required_premise is not None


def test_terminal_node_injects_continue_note():
    """终止型节点但帧未闭合 → 继续，但 viability_continue_note 提示收束."""
    node = set(TERMINAL_FORMULA_NODES).pop()
    d = analyze_continuation_viability(
        narrative_state=_state(),
        foreshadows=_foreshadows(),
        frame_context=_frame(no_active=False, formula_node=node),
    )
    assert d.verdict == "continue"
    note = viability_continue_note(d)
    assert "终止型节点" in note


def test_fresh_default_continue_zero_cost():
    """无数据可判（fresh 工作区）→ 默认 continue，不改变现有流程字节."""
    d = analyze_continuation_viability(
        narrative_state=_state(),
        foreshadows=None,
        frame_context=None,
        workspec=None,
        contract=None,
        recent_chapter_count=0,
    )
    assert d.verdict == "continue"
    assert d.deterministic is True


def test_viability_unit_parse_response_validation():
    """staged 判定单元：verdict 枚举 / reasons 列表 / required_premise 可空."""
    unit = ContinuationViabilityUnit()
    # 合法
    d = unit.parse_response(
        '{"verdict": "needs_premise", "reasons": ["原因"], "required_premise": "新前提"}'
    )
    assert d.verdict == "needs_premise"
    assert d.required_premise == "新前提"
    # required_premise 可空
    d2 = unit.parse_response('{"verdict": "continue", "reasons": ["原因"]}')
    assert d2.verdict == "continue"
    assert d2.required_premise is None
    # 非法 verdict 拒绝
    try:
        unit.parse_response('{"verdict": "maybe", "reasons": ["x"]}')
        raise AssertionError("should have raised")
    except ValueError:
        pass
    # 缺失 reasons 拒绝
    try:
        unit.parse_response('{"verdict": "continue"}')
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_viability_prompt_mentions_contract():
    """冲突场景的 staged prompt 注入读者契约（若提供）."""
    unit = ContinuationViabilityUnit()
    analysis = analyze_continuation_viability(
        narrative_state=_state(situation="尘埃落定"),
        foreshadows=_foreshadows("悬念未解"),
        frame_context=_frame(no_active=False),
        contract=_contract(ending_conditions=["尘埃落定"]),
    )
    prompt = unit.build_prompt(analysis, contract_context=_contract([]).to_prompt_context())
    assert "【读者契约】" in prompt
    assert "核心张力" in prompt
