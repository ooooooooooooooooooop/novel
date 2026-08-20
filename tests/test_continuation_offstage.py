"""§14 盲续写迭代系统修复测试——离场人物在场感 + 叙事组织约束.

验证：
1. 零成本契约：无角色 / 所有角色都在场时，【离场人物在场感】段为空，prompt 与旧版一致；
2. 有离场人物时，段出现并列出其近况/关系（机制级召回）；
3. 续写要求新增第 8 项「延续本作品的叙事组织方式」（不预设具体形态）。
"""

from src.object_state import (
    FactEntry,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.object_state.charactermodel import CharacterModel
from src.workflow_action.continuation import ContinueUnit


def _state(active: list[str]) -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="江州",
        active_characters=active,
        current_situation="旧案初结",
        active_conflicts=["官场博弈"],
    )


def _char(cid: str, name: str, identity: str = "", pressure=None, rels=None) -> CharacterModel:
    return CharacterModel(
        character_id=cid,
        name=name,
        identity=identity or "人物",
        outer_goal="推进",
        inner_need="安稳",
        fear="被牵连",
        flaw="念旧",
        strength="识局",
        stance="合作",
        current_pressure=pressure or [],
        change_trajectory=[],
        relations=rels or {},
    )


def _prompt(state, characters) -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=state,
        characters=characters,
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 都市商战",
        platform=None,
        genre=None,
    )


def test_no_offstage_section_when_no_characters():
    """零成本契约：characters 为空 → 无在场感段（与旧版一致）."""
    prompt = _prompt(_state(active=["c1"]), [])
    assert "【离场人物在场感】" not in prompt


def test_no_offstage_section_when_all_active():
    """零成本契约：所有角色都在场 → 无在场感段."""
    chars = [_char("c1", "沈明"), _char("c2", "林静")]
    prompt = _prompt(_state(active=["c1", "c2"]), chars)
    assert "【离场人物在场感】" not in prompt


def test_offstage_section_when_state_unknown():
    """零成本契约：state 未标明在场者（active_characters 空）→ 无法判定离场 → 无段."""
    prompt = _prompt(_state(active=[]), [_char("c1", "沈明")])
    assert "【离场人物在场感】" not in prompt


def test_offstage_character_surfaced():
    """机制修复：离场人物被显式标出，带近况/关系，供多线并置召回."""
    chars = [
        _char("c1", "沈明", "主角", pressure=["正在推进商业布局"]),
        _char("c2", "林静", "关键证人", pressure=["省城聆训结束待归"],
              rels={"c1": "被沈明安排安置"}),
    ]
    prompt = _prompt(_state(active=["c1"]), chars)
    assert "【离场人物在场感】" in prompt
    assert "林静(c2)" in prompt
    assert "省城聆训结束待归" in prompt  # 近况在场感
    assert "被沈明安排安置" in prompt   # 关系在场感


def test_narrative_organization_requirement():
    """续写要求新增第 8 项：延续原作叙事组织方式（多线/单线皆可，不预设）."""
    prompt = _prompt(_state(active=["c1"]), [])
    assert "延续本作品的叙事组织方式" in prompt
    assert "若原作单线紧凑" in prompt


def test_delegation_requirement_present():
    """续写要求第 11 项：借力不出面（§14 边界修正，Step 4 单变量证伪实验支持）.

    零成本：与第 8 项同属常驻需求条，无新注入段；条件式措辞（若原作…请保持），
    不预设具体形态，不强制所有作品都借力。
    """
    prompt = _prompt(_state(active=["c1"]), [])
    assert "11. 借力不出面" in prompt
    assert "借力布局、委托他人出面处理事务" in prompt
    assert "不要让主角因续写而事事亲为" in prompt
    assert "若原作主角本就亲力亲为" in prompt  # 条件式，不预设
