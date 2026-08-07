"""CharacterUpdate tests — 角色受后果而变的中间对象（作者性 Phase A 地基）.

覆盖：
- CharacterUpdate 构造与校验（必填文本非空 / 置信度 0-1 / extra=forbid）
- 五种变化 update_type + 维度 Literal
- JSON round-trip（sidecar 兼容）
- 向后兼容：默认值（permanence/confidence/status）正确
"""

import json

import pytest

from src.object_state.characterupdate import CharacterUpdate


def _mk_cu(**overrides):
    base = dict(
        character_id="c1",
        trigger="pu_001",
        observed_consequence="信任的朋友再次利用了自己",
        affected_dimension="pressure",
        update_type="reinforce",
        proposed_after="『不能相信任何人』的信念进一步加强",
    )
    base.update(overrides)
    return CharacterUpdate(**base)


def test_characterupdate_construction():
    cu = _mk_cu()
    assert cu.character_id == "c1"
    assert cu.trigger == "pu_001"
    assert cu.affected_dimension == "pressure"
    assert cu.update_type == "reinforce"
    assert cu.proposed_after == "『不能相信任何人』的信念进一步加强"


def test_defaults_backward_compat():
    cu = _mk_cu()
    assert cu.before is None
    assert cu.evidence is None
    assert cu.permanence == "medium"
    assert cu.confidence == 0.5
    assert cu.status == "proposed"


def test_required_text_non_blank():
    with pytest.raises(ValueError):
        _mk_cu(character_id="")
    with pytest.raises(ValueError):
        _mk_cu(observed_consequence="")
    with pytest.raises(ValueError):
        _mk_cu(proposed_after="")


def test_confidence_unit_interval():
    with pytest.raises(ValueError):
        _mk_cu(confidence=1.5)
    with pytest.raises(ValueError):
        _mk_cu(confidence=-0.1)
    cu = _mk_cu(confidence=0.9)
    assert cu.confidence == 0.9


def test_extra_forbid():
    with pytest.raises(ValueError):
        _mk_cu(unknown_field="x")


def test_update_type_five_states():
    for t in ("reinforce", "shift", "destabilize", "unresolved", "misinterpret"):
        cu = _mk_cu(update_type=t)
        assert cu.update_type == t
    with pytest.raises(ValueError):
        _mk_cu(update_type="grow")  # 不是五态之一


def test_affected_dimension_literal():
    for d in ("fear", "goal", "relation", "self_image", "pressure", "trajectory"):
        cu = _mk_cu(affected_dimension=d)
        assert cu.affected_dimension == d
    with pytest.raises(ValueError):
        _mk_cu(affected_dimension="mood")


def test_json_round_trip():
    cu = _mk_cu(
        affected_dimension="trajectory",
        update_type="shift",
        before="只能靠自己",
        evidence="持续三次拒绝他人帮助",
        permanence="long",
        confidence=0.85,
    )
    data = json.loads(cu.model_dump_json())
    cu2 = CharacterUpdate(**data)
    assert cu2.update_type == "shift"
    assert cu2.before == "只能靠自己"
    assert cu2.evidence == "持续三次拒绝他人帮助"
    assert cu2.permanence == "long"
    assert cu2.confidence == 0.85
