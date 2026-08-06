"""SceneExperience tests — 场景体验中间层（方向文档第四节）.

覆盖：
- SceneExperience 对象构造与校验
- PlotUnit 向后兼容：无 scene_experience 时可解析，渲染不输出新段
- PlotUnit 带 scene_experience：五维渲染进 to_prompt_context
- 嵌套对象经 JSON round-trip 不丢
"""

import json

import pytest

from src.object_state.plotunit import PlotUnit
from src.object_state.scene_experience import SceneExperience


def _mk_pu(**overrides):
    base = dict(
        unit_id="pu_001",
        level="scene",
        goal="改写规则救沈望",
        conflict="改写暴露风险",
        input_state_ref="ns_in",
        output_state_ref="ns_out",
        is_effective=True,
    )
    base.update(overrides)
    return PlotUnit(**base)


def _mk_se(**overrides):
    base = dict(
        protagonist_sees="碑面上被磨掉的旧字在日光下浮出轮廓",
        obstacles=["观碑使沿碑面逐寸检视"],
        choice_grounding="沈望是两年前救过自己的人，报恩心切",
        outcome="改写生效，处决文书斩改逐",
        cognition_shift="从以为眼花到确认真能改写",
    )
    base.update(overrides)
    return SceneExperience(**base)


def test_scene_experience_construction():
    se = _mk_se()
    assert se.protagonist_sees == "碑面上被磨掉的旧字在日光下浮出轮廓"
    assert se.obstacles == ["观碑使沿碑面逐寸检视"]
    assert se.choice_grounding == "沈望是两年前救过自己的人，报恩心切"
    assert se.outcome == "改写生效，处决文书斩改逐"
    assert se.cognition_shift == "从以为眼花到确认真能改写"


def test_scene_experience_required_text_non_blank():
    with pytest.raises(ValueError):
        _mk_se(protagonist_sees="")
    with pytest.raises(ValueError):
        _mk_se(choice_grounding="")


def test_scene_experience_obstacles_non_blank():
    with pytest.raises(ValueError):
        _mk_se(obstacles=["", "blank"])


def test_plotunit_backward_compat_no_scene_experience():
    """旧 PlotUnit（无 scene_experience）可解析，默认 None."""
    pu = _mk_pu()
    assert pu.scene_experience is None
    ctx = pu.to_prompt_context()
    assert "场景体验" not in ctx  # 空字段不渲染 → 与旧版逐字节一致
    assert "【PlotUnit: pu_001 | scene】" in ctx


def test_plotunit_with_scene_experience_renders():
    pu = _mk_pu(scene_experience=_mk_se())
    ctx = pu.to_prompt_context()
    assert "【场景体验: pu_001】" in ctx
    assert "主角看见: 碑面上被磨掉的旧字在日光下浮出轮廓" in ctx
    assert "阻碍: 观碑使沿碑面逐寸检视" in ctx
    assert "选择依据: 沈望是两年前救过自己的人，报恩心切" in ctx
    assert "结果: 改写生效，处决文书斩改逐" in ctx
    assert "认知变化: 从以为眼花到确认真能改写" in ctx


def test_scene_experience_json_round_trip():
    """嵌套对象经 JSON 序列化/反序列化不丢（serialization 兼容）."""
    pu = _mk_pu(scene_experience=_mk_se())
    data = json.loads(pu.model_dump_json())
    pu2 = PlotUnit(**data)
    assert pu2.scene_experience is not None
    assert pu2.scene_experience.protagonist_sees == "碑面上被磨掉的旧字在日光下浮出轮廓"
    assert pu2.scene_experience.obstacles == ["观碑使沿碑面逐寸检视"]


def test_scene_experience_to_prompt_context_no_unit():
    se = _mk_se()
    ctx = se.to_prompt_context()
    assert "【场景体验】" in ctx  # 无 unit_id 时用通用头


def test_plotunit_serialization_backward_compat():
    """旧 state（无 scene_experience 键）反序列化为 None，不报错."""
    old_data = {
        "unit_id": "pu_old",
        "level": "scene",
        "goal": "g",
        "conflict": "c",
        "input_state_ref": "a",
        "output_state_ref": "b",
        "is_effective": True,
    }
    pu = PlotUnit(**old_data)
    assert pu.scene_experience is None
