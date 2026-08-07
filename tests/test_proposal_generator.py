"""Proposal Generator tests — 作者性 2A.

验证：build_proposal_prompt 要求 n>=2（N=1 走原 Continue 路径，本模块完全不
参与 → 零成本契约）；多候选输出格式含真实决策差异要求；prompt 前段与单候选
Continue 逐字节一致（复用 build_prompt 头）；parse_proposals_response 严格解析
（n 精确、unit_id/state_id 唯一、缺字段/多余字段拒绝）；candidate_label 映射。
"""

import json

import pytest

from src.object_state import (
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.proposal_generator import (
    build_proposal_prompt,
    candidate_label,
    parse_proposals_response,
)


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="ns_in",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["c001"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _build(n: int, **kw) -> str:
    cont = ContinueUnit()
    return build_proposal_prompt(
        cont,
        n,
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        **kw,
    )


def _single_base(**kw) -> str:
    """N=1 时用的原 Continue prompt（不经过 proposal 模块）."""
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        **kw,
    )


# ---------------------------------------------------------------------------
# build_proposal_prompt
# ---------------------------------------------------------------------------
def test_build_requires_n_at_least_2():
    with pytest.raises(ValueError):
        _build(1)
    with pytest.raises(ValueError):
        _build(0)


def test_build_contains_multi_candidate_section():
    prompt = _build(3)
    assert "【多候选要求】" in prompt
    assert "A=A方案" in prompt
    assert "B=B方案" in prompt
    assert "C=C方案" in prompt
    assert "必须生成 3 个 PlotUnit 候选" in prompt


def test_build_head_byte_identical_to_single_candidate():
    """复用 Continue 前段 → N 候选 prompt 的约束前段与单候选逐字节一致."""
    multi = _build(2)
    single = _single_base()
    # 多候选 prompt = 原前段（截至【输出格式】）+ 新【多候选要求】块
    multi_preamble = multi.split("【多候选要求】", 1)[0]
    single_preamble = single.split("【输出格式】", 1)[0]
    assert multi_preamble == single_preamble


def test_build_demands_real_decision_differences():
    prompt = _build(2)
    assert "真正不同的故事走向" in prompt
    assert "不是同一情节的措辞/风格变体" in prompt
    assert "tradeoff" in prompt


def test_build_keeps_continue_constraints():
    prompt = _build(2)
    # 多候选仍必须满足原续写要求全部约束
    assert "结构有效推进" in prompt
    assert "角色行为符合" in prompt
    assert "信息释放服务伏笔推进" in prompt


def test_build_passes_through_context_params():
    prompt = _build(2, style_context="克制文风", nsfw_context="成人向授权")
    assert "克制文风" in prompt
    assert "成人向授权" in prompt
    assert "【写作风格】" in prompt


# ---------------------------------------------------------------------------
# parse_proposals_response
# ---------------------------------------------------------------------------
def _plotunit_json(unit_id: str, state_id: str) -> dict:
    return {
        "unit_id": unit_id,
        "level": "scene",
        "goal": "候选目标",
        "participants": ["c001"],
        "conflict": "候选冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": state_id,
        "released_information": ["新信息"],
        "emotional_shift": "紧张",
        "hook": "门外响起脚步声",
        "formula_node": "climax",
        "consequences": ["后果"],
        "is_effective": True,
        "scene_experience": {
            "protagonist_sees": "雨线敲在窗上",
            "obstacles": ["对手堵门"],
            "choice_grounding": "身为长子，不能退",
            "outcome": "他留下对峙",
            "cognition_shift": "有些事放下，也放不下",
        },
    }


def _new_state(state_id: str) -> dict:
    return {
        "state_id": state_id,
        "current_time": "深夜",
        "current_location": "旧宅前厅",
        "active_characters": ["c001"],
        "current_situation": "对峙中",
        "active_conflicts": ["坦白还是隐瞒"],
        "public_information": ["对手来了"],
        "hidden_information": ["信物在柜中"],
    }


def _proposal(label: str) -> dict:
    return {
        "plotunit": _plotunit_json(f"pu_{label}", f"ns_{label}"),
        "new_state": _new_state(f"ns_{label}"),
        "new_facts": [
            {
                "fact_id": f"f_{label}_001",
                "statement": f"{label} 确认的事实",
                "fact_type": "event",
                "involved_entities": ["c001"],
                "confirmed": True,
            }
        ],
        "confidence_gaps": ["对方是否知情"],
        "tradeoff_hint": f"{label} 放弃 X 换取 Y",
    }


def _response(n: int) -> str:
    return json.dumps({"proposals": [_proposal(chr(ord("A") + i)) for i in range(n)]}, ensure_ascii=False)


def test_parse_correct_n():
    packages = parse_proposals_response(_response(2), 2)
    assert len(packages) == 2
    assert packages[0]["plotunit"].unit_id == "pu_A"
    assert packages[1]["plotunit"].unit_id == "pu_B"
    assert packages[0]["new_state"].state_id == "ns_A"
    assert packages[0]["tradeoff_hint"]  # tradeoff_hint 透传


def test_parse_wrong_n_rejected():
    with pytest.raises(ValueError, match="expected 2 proposals, got 3"):
        parse_proposals_response(_response(3), 2)


def test_parse_duplicate_unit_id_rejected():
    data = {"proposals": [_proposal("A"), _proposal("A")]}
    with pytest.raises(ValueError, match="duplicate unit_id"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 2)


def test_parse_duplicate_state_id_rejected():
    p_a = _proposal("A")
    p_b = _proposal("B")
    p_b["new_state"]["state_id"] = "ns_A"
    data = {"proposals": [p_a, p_b]}
    with pytest.raises(ValueError, match="duplicate state_id"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 2)


def test_parse_missing_field_rejected():
    data = {"proposals": [{"plotunit": _plotunit_json("pu_A", "ns_A"), "new_state": _new_state("ns_A")}]}
    with pytest.raises(ValueError, match="missing required field"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 1)


def test_parse_unexpected_field_rejected():
    data = {"proposals": [_proposal("A")], "extra": 1}
    with pytest.raises(ValueError, match="unexpected field"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 1)


def test_parse_unexpected_candidate_field_rejected():
    p = _proposal("A")
    p["mystery"] = 1
    data = {"proposals": [p]}
    with pytest.raises(ValueError, match="unexpected field"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 1)


def test_parse_bad_new_facts_type_rejected():
    p = _proposal("A")
    p["new_facts"] = "not a list"
    data = {"proposals": [p]}
    with pytest.raises(ValueError, match="new_facts must be a list"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 1)


def test_parse_non_string_confidence_gap_rejected():
    p = _proposal("A")
    p["confidence_gaps"] = [1, 2]
    data = {"proposals": [p]}
    with pytest.raises(ValueError, match="confidence_gaps must be strings"):
        parse_proposals_response(json.dumps(data, ensure_ascii=False), 1)


def test_parse_not_json_object():
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_proposals_response("[1, 2]", 1)


def test_parse_proposals_not_list():
    with pytest.raises(ValueError, match="proposals must be a list"):
        parse_proposals_response(json.dumps({"proposals": "nope"}), 1)


# ---------------------------------------------------------------------------
# candidate_label
# ---------------------------------------------------------------------------
def test_candidate_label_mapping():
    assert [candidate_label(i) for i in range(7)] == ["A", "B", "C", "D", "E", "F", "G"]
    assert candidate_label(7) == "C7"
