"""Tests for style_context injection into Continue prompt."""

from src.object_state import FactLedger, ForeshadowGraph, NarrativeState
from src.workflow_action.continuation import ContinueUnit


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["gl"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _base_prompt(style_context: str = "") -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        platform=None,
        genre=None,
        style_context=style_context,
    )


def test_no_style_no_section():
    prompt = _base_prompt()
    assert "【写作风格】" not in prompt


def test_style_adds_section():
    prompt = _base_prompt("调性: 克制｜视角: 第三人称有限")
    assert "【写作风格】" in prompt
    assert "调性: 克制｜视角: 第三人称有限" in prompt


def test_style_section_under_constraints():
    prompt = _base_prompt("调性: 克制")
    constraints_pos = prompt.find("【作品约束】")
    style_pos = prompt.find("【写作风格】")
    assert constraints_pos < style_pos


def test_style_context_default_unchanged_prompt():
    """默认 style_context='' 时 prompt 与无此参数时字节一致（防回归）."""
    cont = ContinueUnit()
    with_style_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        style_context="",
    )
    # 显式传空串 与 不传（缺省）应得到相同输出
    without_style_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
    )
    assert with_style_param == without_style_param
