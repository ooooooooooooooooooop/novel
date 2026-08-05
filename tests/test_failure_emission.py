"""B 档 8 个失败类型弱信号发射测试.

覆盖：
- 8 条规则各构造命中场景 → 对应 issue_type 出现
- 正常依据对照 → 不误报
- ReviewIssueType Literal 含 duplication_of_threads（schema 层）
- WorldModel 接入：prohibitions/consequence_logic 存在时 iss_cost 才检查
"""

import pytest

from src.object_state import (
    CharacterModel,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    WorldModel,
)
from src.object_state.reviewissue import ReviewIssue, ReviewIssueType
from src.workflow_action.review import ReviewUnit

RU = ReviewUnit()


def _mk_char(character_id: str = "char_a", knowledge: list[str] | None = None) -> CharacterModel:
    return CharacterModel(
        character_id=character_id,
        name="主角",
        identity="掌门弟子",
        outer_goal="查清真相",
        inner_need="守护同门",
        fear="真相危及宗门",
        flaw="过度自负",
        strength="心思缜密",
        stance="坚定",
        knowledge_state=list(knowledge or []),
    )


def _mk_state(state_id: str, situation: str = "局势稳定") -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="第3天",
        current_location="客栈",
        current_situation=situation,
    )


def _mk_pu(
    unit_id: str,
    *,
    conflict: str = "线人失踪",
    released: list[str] | None = None,
    consequences: list[str] | None = None,
    participants: list[str] | None = None,
    input_ref: str = "s_in",
    output_ref: str = "s_out",
    hook: str | None = None,
) -> PlotUnit:
    return PlotUnit(
        unit_id=unit_id,
        level="scene",
        goal="推进调查",
        conflict=conflict,
        input_state_ref=input_ref,
        output_state_ref=output_ref,
        released_information=list(released or []),
        consequences=list(consequences or []),
        participants=list(participants or []),
        hook=hook,
    )


def _types_of(issues: list[ReviewIssue]) -> list[str]:
    return [i.issue_type for i in issues]


# ---------- schema：duplication_of_threads 已进 Literal ----------

def test_duplication_of_threads_in_literal():
    assert "duplication_of_threads" in ReviewIssueType.__args__


# ---------- iss_leak → information_leak ----------

def test_information_leak_hard_public_hidden_overlap():
    ns = _mk_state("s1", "局势稳定")
    ns.public_information = ["秘密"]
    ns.hidden_information = ["秘密"]
    issues = RU._domain_rules([ns])
    assert "information_leak" in _types_of(issues)


def test_information_leak_weak_unknown_claim_released():
    cm = _mk_char(knowledge=["没摸实顾府在哪"])
    pu = _mk_pu("pu_1", released=["顾府位置确认"], participants=["char_a"])
    issues = RU._domain_rules([cm, pu])
    leaks = [i for i in issues if i.issue_type == "information_leak"]
    assert leaks
    assert any("iss_leak_char_a_pu_1" == i.issue_id for i in leaks)


def test_information_leak_weak_no_false_positive():
    cm = _mk_char(knowledge=["没摸实顾府在哪"])
    # 释放信息与否定断言主题无关 → 不触发
    pu = _mk_pu("pu_1", released=["天气转凉"], participants=["char_a"])
    issues = RU._domain_rules([cm, pu])
    assert not [i for i in issues if i.issue_type == "information_leak"]


def test_information_leak_hard_no_false_positive():
    ns = _mk_state("s1", "局势稳定")
    ns.public_information = ["公开"]
    ns.hidden_information = ["秘密"]
    issues = RU._domain_rules([ns])
    assert "information_leak" not in _types_of(issues)


# ---------- iss_motivation → motivation_gap ----------

def test_motivation_gap_hits_jump_without_grounding():
    pu = _mk_pu("pu_1", conflict="他突然信任对方并交出账本")
    issues = RU._domain_rules([pu])
    assert "motivation_gap" in _types_of(issues)


def test_motivation_gap_grounded_no_false_positive():
    # 含"作为"决策依据词 → 不触发
    pu = _mk_pu("pu_1", conflict="他突然信任对方，作为掌门他不得不这样做")
    issues = RU._domain_rules([pu])
    assert "motivation_gap" not in _types_of(issues)


# ---------- iss_cost → missing_cost ----------

def test_missing_cost_high_risk_without_cost_in_consequences():
    world = WorldModel(prohibitions=["禁术有代价"])
    pu = _mk_pu("pu_1", conflict="强行突破境界", consequences=["突破成功"])
    issues = RU._domain_rules([world, pu])
    assert "missing_cost" in _types_of(issues)


def test_missing_cost_no_world_no_check():
    # 无 WorldModel（或规则/后果逻辑为空）→ 不检查
    pu = _mk_pu("pu_1", conflict="强行突破境界", consequences=["突破成功"])
    issues = RU._domain_rules([pu])
    assert "missing_cost" not in _types_of(issues)


def test_missing_cost_paid_no_false_positive():
    world = WorldModel(prohibitions=["禁术有代价"])
    pu = _mk_pu("pu_1", conflict="强行突破境界", consequences=["付出代价，重伤反噬"])
    issues = RU._domain_rules([world, pu])
    assert "missing_cost" not in _types_of(issues)


# ---------- iss_consequence → missing_consequence ----------

def test_missing_consequence_release_without_situation_change():
    s_in = _mk_state("s_in", "局势稳定")
    s_out = _mk_state("s_out", "局势稳定")
    pu = _mk_pu("pu_1", released=["线人是顾府卧底"])
    issues = RU._domain_rules([s_in, s_out, pu])
    assert "missing_consequence" in _types_of(issues)


def test_missing_consequence_situation_changed_no_false_positive():
    s_in = _mk_state("s_in", "局势稳定")
    s_out = _mk_state("s_out", "局势骤然逆转")
    pu = _mk_pu("pu_1", released=["线人是顾府卧底"])
    issues = RU._domain_rules([s_in, s_out, pu])
    assert "missing_consequence" not in _types_of(issues)


# ---------- iss_reljump → relationship_jump ----------

def test_relationship_jump_hits_jump_without_grounding():
    pu = _mk_pu("pu_1", conflict="二人宿敌和解，当场结为同盟")
    issues = RU._domain_rules([pu])
    assert "relationship_jump" in _types_of(issues)


def test_relationship_jump_grounded_no_false_positive():
    pu = _mk_pu("pu_1", conflict="二人宿敌和解，作为同门他不得不放下仇恨")
    issues = RU._domain_rules([pu])
    assert "relationship_jump" not in _types_of(issues)


# ---------- iss_redundancy → redundancy ----------

def test_redundancy_adjacent_conflict_repeat():
    pu_a = _mk_pu("pu_1", conflict="追查线人下落")
    pu_b = _mk_pu("pu_2", conflict="追查线人下落")
    issues = RU._domain_rules([pu_a, pu_b])
    assert "redundancy" in _types_of(issues)


def test_redundancy_adjacent_hook_repeat():
    pu_a = _mk_pu("pu_1", conflict="追查线人下落", hook="线人失踪")
    pu_b = _mk_pu("pu_2", conflict="继续追查", hook="线人失踪")
    issues = RU._domain_rules([pu_a, pu_b])
    assert "redundancy" in _types_of(issues)


def test_redundancy_distinct_no_false_positive():
    pu_a = _mk_pu("pu_1", conflict="追查线人下落")
    pu_b = _mk_pu("pu_2", conflict="与顾府对峙")
    issues = RU._domain_rules([pu_a, pu_b])
    assert "redundancy" not in _types_of(issues)


# ---------- iss_abrupt → abrupt_payoff ----------

def _fg_with_active(content: str, thread_id: str = "th_1") -> ForeshadowGraph:
    return ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id=thread_id,
                setup_point="第1章埋设",
                content=content,
                visibility_level="implicit",
                expected_payoff="回收揭晓",
                current_status="active",
            )
        ]
    )


def test_abrupt_payoff_payoff_marker_without_active_thread():
    fg = _fg_with_active("追查线人下落")
    pu = _mk_pu("pu_1", released=["真相大白，真凶是顾府二少爷"])
    issues = RU._domain_rules([fg, pu])
    assert "abrupt_payoff" in _types_of(issues)


def test_abrupt_payoff_thread_supports_no_false_positive():
    fg = _fg_with_active("凶手是谁的真相")
    pu = _mk_pu("pu_1", released=["真相大白，凶手是他"])
    issues = RU._domain_rules([fg, pu])
    assert "abrupt_payoff" not in _types_of(issues)


def test_abrupt_payoff_no_marker_no_false_positive():
    fg = _fg_with_active("追查线人下落")
    pu = _mk_pu("pu_1", released=["线人改口了"])
    issues = RU._domain_rules([fg, pu])
    assert "abrupt_payoff" not in _types_of(issues)


# ---------- iss_dupthread → duplication_of_threads ----------

def test_duplication_of_threads_similar_active_contents():
    fg = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="th_1", setup_point="第1章", content="主角身世之谜",
                visibility_level="implicit", expected_payoff="回收",
            ),
            ForeshadowEntry(
                thread_id="th_2", setup_point="第2章", content="主角身世之秘",
                visibility_level="implicit", expected_payoff="回收",
            ),
        ]
    )
    issues = RU._domain_rules([fg])
    assert "duplication_of_threads" in _types_of(issues)


def test_duplication_of_threads_distinct_no_false_positive():
    fg = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="th_1", setup_point="第1章", content="主角身世之谜",
                visibility_level="implicit", expected_payoff="回收",
            ),
            ForeshadowEntry(
                thread_id="th_2", setup_point="第2章", content="追查线人下落",
                visibility_level="implicit", expected_payoff="回收",
            ),
        ]
    )
    issues = RU._domain_rules([fg])
    assert "duplication_of_threads" not in _types_of(issues)
