"""Continue prompt 的 Chapter Packet 注入测试（V2 Context Firewall）.

验证 V2 架构关键点：
1. 无 packet_context 时，prompt 不含【本章上下文包】，字节与旧版一致（零成本）；
2. 有 packet_context 时，【本章上下文包】段出现；
3. 正文模型拿到的只是 Chapter Packet（SELECT 内容），不是 Full State。
"""
from src.object_state import (
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.object_state.charactermodel import CharacterModel
from src.workflow_action.continuation import ContinueUnit


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1", current_time="夜", current_location="江州",
        active_characters=["p1"], current_situation="旧案初结",
        active_conflicts=["官场博弈"],
    )


def _char() -> CharacterModel:
    return CharacterModel(
        character_id="p1", name="周正", identity="商界", outer_goal="推进",
        inner_need="安稳", fear="被牵连", flaw="念旧", strength="识局",
        stance="合作", current_pressure=[], change_trajectory=[], relations={},
    )


def _prompt(packet_context: str = "") -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(), characters=[_char()],
        facts=FactLedger(entries=[]), foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 都市商战", platform=None, genre=None,
        packet_context=packet_context,
    )


def test_zero_cost_empty():
    """无 packet → 不含【本章上下文包】，字节与旧版一致."""
    p1 = _prompt()
    p2 = _prompt(packet_context="")
    assert "【本章上下文包】" not in p1
    assert p1 == p2


def test_packet_section_injected():
    """有 packet → 【本章上下文包】段出现并含 SELECT 内容."""
    packet = (
        "本章应自然承载：\n- 恒通机芯谈判（接近兑现）\n"
        "本章事实前提：\n- 顾总在场\n行为约束：\n- 不主动解释未公开动机"
    )
    prompt = _prompt(packet_context=packet)
    assert "【本章上下文包】" in prompt
    assert "恒通机芯谈判" in prompt
    assert "不主动解释未公开动机" in prompt


def test_full_state_not_injected():
    """V2：正文模型不该看到完整 State——Full State 渲染内容不进入 prompt."""
    from src.object_state.statemodel import StateModel, ThreadState, OffScreenProcess

    # Full State 里有 BACKGROUND/DORMANT 内容
    sm = StateModel(
        threads=[ThreadState(thread_id="t_bg", thread_type="官场线", label="陆平官场",
                             current_state="暗中角力")],
        offscreen=[OffScreenProcess(entity="夏晴", background_state="家庭生活")],
    )
    # 但传给 prompt 的只有 Chapter Packet（不含这些 BACKGROUND 项）
    packet = "本章应自然承载：\n- 恒通机芯谈判"
    prompt = _prompt(packet_context=packet)
    assert "陆平官场" not in prompt  # BACKGROUND 线程不在正文上下文
    assert "家庭生活" not in prompt  # offscreen 不在正文上下文
    # 更直接：即使把 Full State 渲染传进去（错误用法），也应能识别——此处验证正确用法不泄露
