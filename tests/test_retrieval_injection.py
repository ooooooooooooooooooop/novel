"""Tests for retrieval_context injection into Continue prompt."""

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


def _base_prompt(retrieval_context: str = "") -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        platform=None,
        genre=None,
        retrieval_context=retrieval_context,
    )


def test_no_retrieval_no_section():
    prompt = _base_prompt()
    assert "【相关事实检索】" not in prompt


def test_retrieval_adds_section():
    prompt = _base_prompt("藏经阁密室 f_001")
    assert "【相关事实检索】" in prompt
    assert "藏经阁密室 f_001" in prompt


def test_retrieval_single_header_no_double_layer():
    """双层段头回归：loader 已去内层头，外层【相关事实检索】恰好 1 次.

    loader 正文以 (top-k 与当前叙事状态相关) 开头，不含【相关事实检索】标记。
    """
    retrieval = "(top-k 与当前叙事状态相关)\n- [事实] 古书藏于藏经阁密室 (id=f_001)"
    prompt = _base_prompt(retrieval)
    assert prompt.count("【相关事实检索】") == 1
    assert "古书藏于藏经阁密室 (id=f_001)" in prompt


def test_retrieval_section_under_constraints():
    prompt = _base_prompt("藏经阁")
    constraints_pos = prompt.find("【作品约束】")
    retrieval_pos = prompt.find("【相关事实检索】")
    state_pos = prompt.find("【当前叙事状态】")
    assert constraints_pos < retrieval_pos < state_pos


def test_retrieval_context_default_unchanged_prompt():
    """默认 retrieval_context='' 时 prompt 与无此参数时字节一致（防回归）."""
    cont = ContinueUnit()
    with_retrieval_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        retrieval_context="",
    )
    without_retrieval_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
    )
    assert with_retrieval_param == without_retrieval_param


def test_retrieval_context_absent_still_byte_identical_with_style():
    """带 style_context 时，retrieval_context 缺省（空）不改变输出."""
    cont = ContinueUnit()
    with_retrieval_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        style_context="调性: 克制",
        retrieval_context="",
    )
    without_retrieval_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        style_context="调性: 克制",
    )
    assert with_retrieval_param == without_retrieval_param


def test_retrieval_section_after_style_section():
    cont = ContinueUnit()
    prompt = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        style_context="调性: 克制",
        retrieval_context="藏经阁",
    )
    style_pos = prompt.find("【写作风格】")
    retrieval_pos = prompt.find("【相关事实检索】")
    assert style_pos < retrieval_pos


def test_positional_ten_args_still_work():
    """旧 10 位置参调用不受影响（第 11 参默认空串）."""
    cont = ContinueUnit()
    prompt = cont.build_prompt(
        _state(),
        [],
        FactLedger(entries=[]),
        ForeshadowGraph(entries=[]),
        "作品类型: 仙侠",
        None,
        None,
        None,
        None,
        "调性: 克制",
    )
    assert "【写作风格】" in prompt
    assert "【相关事实检索】" not in prompt


def test_retrieval_with_platform_and_genre():
    cont = ContinueUnit()
    prompt = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        platform="web_novel_daily",
        genre="仙侠",
        retrieval_context="藏经阁",
    )
    assert "【相关事实检索】" in prompt
    assert "平台约束" in prompt
    assert "仙侠 类型约束" in prompt
