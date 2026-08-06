"""信息凭证一致性维度测试（L0 数据表 + L5 审查规则 iss_info_*）.

覆盖：
- L0：通道谱系/聚焦三分/凭证约束 P1-P4/差距形态 数据表非空、字段齐全
- L5：iss_info_channel（P1 亲历凭证）/ iss_info_relay（P2/P3 转述时效）/
      iss_info_scope（P4 知识域翻转）命中与不误报
- 零成本：空对象不产出 iss_info issue
"""

from src.domain_layer.info_warrant_knowledge import (
    FIRSTHAND_DETAIL_MARKERS,
    FOCALIZATION_TYPES,
    INFO_CHANNELS,
    INFO_GAP_FORMS,
    RELAY_MARKERS,
    UNKNOWN_NEGATION_MARKERS,
    WARRANT_CONSTRAINTS,
)
from src.domain_layer.info_warrant_rules import build_info_warrant_guidance
from src.object_state import CharacterModel, PlotUnit
from src.workflow_action.review import ReviewUnit


# ---------- L0 数据表 ----------

def test_info_channels_nonempty_and_fielded():
    """通道谱系非空，每条含全部字段."""
    assert len(INFO_CHANNELS) == 6
    required = {"name", "definition", "detail_capacity", "reliability", "detection"}
    for ch in INFO_CHANNELS:
        assert required <= set(ch)
    names = {ch["name"] for ch in INFO_CHANNELS}
    assert {"亲历感知", "转述", "书面文件", "公开信息", "推断", "记忆"} <= names


def test_focalization_types_complete():
    """聚焦三分含零/内/外."""
    assert len(FOCALIZATION_TYPES) == 3
    joined = "".join(f["name"] for f in FOCALIZATION_TYPES)
    assert "零聚焦" in joined and "内聚焦" in joined and "外聚焦" in joined


def test_warrant_constraints_p1_p4_fielded():
    """四条凭证约束齐全，每条含四字段."""
    assert [c["rule_id"] for c in WARRANT_CONSTRAINTS] == ["P1", "P2", "P3", "P4"]
    required = {"rule_id", "name", "definition", "instruction", "misuse", "detection"}
    for c in WARRANT_CONSTRAINTS:
        assert required <= set(c)


def test_info_gap_forms_legal_and_illegal():
    """差距形态含合法（神秘/悬念/同步/切换）与非法（越界/泄漏/过期/翻转）."""
    legal = {f["name"] for f in INFO_GAP_FORMS if f["kind"] == "legal"}
    illegal = {f["name"] for f in INFO_GAP_FORMS if f["kind"] == "illegal"}
    assert {"神秘", "悬念", "同步共知", "聚焦切换"} <= legal
    assert {"通道越界", "叙述泄漏", "时效过期", "知识域翻转"} <= illegal


def test_firsthand_markers_exclude_broad_action_words():
    """亲历细节词集只收外观/神态描述，不收'看着/听见'等宽动作词（防误报）."""
    assert "看着" not in FIRSTHAND_DETAIL_MARKERS
    assert "听见" not in FIRSTHAND_DETAIL_MARKERS
    assert "脱了相" in FIRSTHAND_DETAIL_MARKERS
    assert "瘦了" in FIRSTHAND_DETAIL_MARKERS


def test_build_info_warrant_guidance_nonempty():
    """凭证指导文本非空，含通道谱系与 P1-P4."""
    g = build_info_warrant_guidance()
    assert g
    assert "【信息通道谱系】" in g
    assert "【凭证约束】" in g
    assert "P1" in g and "P4" in g


# ---------- L5 审查规则 ----------

def _mk_pu(uid, goal="", conflict="", released=None, hook=None, participants=None):
    return PlotUnit(
        unit_id=uid,
        level="scene",
        goal=goal or "推进",
        conflict=conflict or "冲突",
        input_state_ref="s0",
        output_state_ref="s1",
        released_information=released or [],
        hook=hook,
        participants=participants or [],
    )


def _mk_cm(cid, kstate):
    return CharacterModel(
        character_id=cid,
        name=cid,
        identity="x",
        outer_goal="g",
        inner_need="n",
        fear="f",
        flaw="w",
        strength="s",
        stance="中立",
        knowledge_state=kstate,
    )


def _iss_info(issues):
    return [i for i in issues if i.issue_id.startswith("iss_info")]


def test_info_channel_hits_warrant_breach():
    """事故文本：'没摸实位置 + 人瘦得脱了相' → iss_info_channel 命中."""
    accident = _mk_pu(
        "pu_accident",
        goal="部下甲电话汇报对手下落",
        conflict="具体在哪儿还没摸实，人瘦得脱了相",
        released=["对手活着"],
        hook="他这条命是自己藏的",
    )
    issues = ReviewUnit()._domain_rules([accident])
    channel = [i for i in _iss_info(issues) if i.issue_id == "iss_info_channel_pu_accident"]
    assert len(channel) == 1
    assert channel[0].severity == "warning"
    assert channel[0].issue_type == "weak_progression"
    assert "亲历" in channel[0].description


def test_info_relay_hits_relayed_firsthand():
    """转述通道 + 亲历细节且无亲历前提 → iss_info_relay 命中."""
    accident = _mk_pu(
        "pu_accident",
        goal="部下甲电话汇报对手下落",
        conflict="具体在哪儿还没摸实，人瘦得脱了相",
    )
    issues = ReviewUnit()._domain_rules([accident])
    relay = [i for i in _iss_info(issues) if i.issue_id == "iss_info_relay_pu_accident"]
    assert len(relay) == 1


def test_info_relay_exempts_witness_premise():
    """已补亲历前提（'远远看过一回'）→ relay 豁免，不命中."""
    fixed = _mk_pu(
        "pu_fixed",
        goal="部下甲电话汇报对手下落",
        conflict="办案的人摸到个大概，我让人远远看过一回，人瘦得脱了相",
        released=["对手活着"],
        hook="他要见主角本人",
    )
    issues = ReviewUnit()._domain_rules([fixed])
    assert not any("pu_fixed" in i.issue_id for i in _iss_info(issues))


def test_info_channel_no_false_positive_on_clean():
    """干净文本无亲历+未知共现 → 不命中."""
    clean = _mk_pu(
        "pu_clean",
        goal="主角在海外城过年",
        conflict="配角甲学着包饺子",
        released=["明天三十"],
    )
    issues = ReviewUnit()._domain_rules([clean])
    assert not _iss_info(issues)


def test_info_scope_hits_knowledge_flip():
    """角色断言'藏身地点不知'却参与产出亲历细节的单元 → iss_info_scope 命中."""
    scope_hit = _mk_pu(
        "pu_scope_hit",
        goal="主角复述对手眼下的样子",
        conflict="他躲在地窖里，瘦得脱了相，眼睛却亮",
        participants=["c_zhangke"],
    )
    cm = _mk_cm("c_zhangke", ["对手藏身地点不知"])
    issues = ReviewUnit()._domain_rules([scope_hit, cm])
    scope = [i for i in _iss_info(issues) if i.issue_id.startswith("iss_info_scope")]
    assert len(scope) == 1
    assert "pu_scope_hit" in scope[0].issue_id


def test_info_scope_no_false_positive():
    """角色断言未知但单元是安排他人观察（无亲历细节产出）→ 不命中."""
    scope_clean = _mk_pu(
        "pu_scope_clean",
        goal="主角指示看住对手",
        conflict="安排人远远看着，不许外人靠近",
        participants=["c_zhangke"],
    )
    cm = _mk_cm("c_zhangke", ["对手藏身地点不知"])
    issues = ReviewUnit()._domain_rules([scope_clean, cm])
    assert not any("pu_scope_clean" in i.issue_id for i in _iss_info(issues))


def test_info_zero_cost_on_empty_objects():
    """零成本契约：空对象列表不产出任何 iss_info issue."""
    issues = ReviewUnit()._domain_rules([])
    assert not _iss_info(issues)
