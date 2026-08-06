"""CharacterModel v4 dynamic modeling tests — 动态角色建模升级.

覆盖：
- 新字段（current_pressure / change_trajectory / relation_behaviors）构造与校验
- 向后兼容：旧 state（无新字段）可反序列化，默认值正确
- 零成本契约：新字段为空时 to_prompt_context 与旧版逐字节一致（不渲染空字段行）
- 渲染：新字段填充时正确输出
"""

import json

from src.object_state.charactermodel import CharacterModel


def _mk_char(**overrides):
    base = dict(
        character_id="c1",
        name="林烬",
        identity="抄碑人",
        outer_goal="救沈望",
        inner_need="被认可",
        fear="暴露",
        flaw="执念",
        strength="谨慎",
        stance="中立",
    )
    base.update(overrides)
    return CharacterModel(**base)


def test_backward_compat_old_fields_default():
    """旧 state（无 v4 字段）可反序列化，默认值正确."""
    cm = _mk_char()
    assert cm.current_pressure == []
    assert cm.change_trajectory == []
    assert cm.relation_behaviors == {}


def test_new_fields_construction():
    cm = _mk_char(
        current_pressure=["处决文书今日到期", "观碑使已锁定"],
        change_trajectory=["从独行隐忍到被迫面对"],
        relation_behaviors={"c003": "对沈望报恩心切", "c002": "对苏观使戒备"},
    )
    assert cm.current_pressure == ["处决文书今日到期", "观碑使已锁定"]
    assert cm.change_trajectory == ["从独行隐忍到被迫面对"]
    assert cm.relation_behaviors["c002"] == "对苏观使戒备"


def test_json_round_trip_with_new_fields():
    """serialization 兼容：新字段经 JSON 序列化/反序列化不丢."""
    cm = _mk_char(
        current_pressure=["压力1"],
        change_trajectory=["轨迹1"],
        relation_behaviors={"c2": "差异1"},
    )
    data = json.loads(cm.model_dump_json())
    cm2 = CharacterModel(**data)
    assert cm2.current_pressure == ["压力1"]
    assert cm2.change_trajectory == ["轨迹1"]
    assert cm2.relation_behaviors == {"c2": "差异1"}


def test_zero_cost_render_when_empty():
    """空 v4 字段不渲染——与旧版逐字节一致（零成本契约）."""
    cm = _mk_char()
    ctx = cm.to_prompt_context()
    assert "当前压力" not in ctx
    assert "变化轨迹" not in ctx
    assert "关系行为差异" not in ctx
    # 基础字段仍渲染
    assert "【角色: 林烬】" in ctx
    assert "身份: 抄碑人" in ctx


def test_render_with_new_fields():
    cm = _mk_char(
        current_pressure=["观碑使已锁定"],
        change_trajectory=["从隐忍到面对"],
        relation_behaviors={"c002": "对苏观使戒备"},
    )
    ctx = cm.to_prompt_context()
    assert "当前压力: 观碑使已锁定" in ctx
    assert "变化轨迹: 从隐忍到面对" in ctx
    assert "关系行为差异: c002: 对苏观使戒备" in ctx


def test_pressure_entries_must_be_non_blank():
    import pytest

    with pytest.raises(ValueError):
        _mk_char(current_pressure=["", "空白条目"])


def test_relation_behaviors_entries_must_be_non_blank():
    import pytest

    with pytest.raises(ValueError):
        _mk_char(relation_behaviors={"c2": ""})
