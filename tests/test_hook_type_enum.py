"""Tests for PlotUnit hook_type 显式枚举（W5）.

覆盖：
- PlotUnit.hook_type 字段：向后兼容（旧 PlotUnit 无该字段解析为 None）、
  渲染条件（有则渲染钩子类型行，无则与旧版逐字节一致）
- rules：validate_plotunit_hook_type 严格层级校验（None/空/未映射层放行，
  scene/chapter 已映射层严格枚举）；get_hook_types_for_level /
  get_hook_type_effectiveness / build_hook_type_guidance
- continuation：frame_context 已知层级（scene/chapter）时注入【层级钩子类型】
  段；无 frame 时不注入（零成本契约）
- review 信号：已填非法 hook_type → blocking iss_hook；已填合法 → 无 iss_hook；
  hook_type 未填 → 维持自由文本路径（不回归）；关键节点 effectiveness 优先查 hook_type
"""

from src.domain_layer.rules import (
    build_hook_type_guidance,
    get_hook_type_effectiveness,
    get_hook_types_for_level,
    validate_plotunit_hook_type,
)
from src.object_state import (
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
)
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.review import ReviewUnit

RU = ReviewUnit()


def _mk_pu(
    unit_id: str,
    *,
    level: str = "scene",
    hook: str | None = None,
    hook_type: str | None = None,
    formula_node: str | None = None,
) -> PlotUnit:
    return PlotUnit(
        unit_id=unit_id,
        level=level,
        goal="推进调查",
        conflict="线人失踪",
        input_state_ref="s_in",
        output_state_ref="s_out",
        hook=hook,
        hook_type=hook_type,
        formula_node=formula_node,
    )


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["gl"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _continue_prompt(*, frame_context=None) -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        frame_context=frame_context,
    )


def _scene_frame_context() -> dict:
    return {
        "cursor": {"current_frame_id": "scene_001", "current_level": "scene"},
        "current_frame": {
            "frame_id": "scene_001",
            "level": "scene",
            "title": "Scene 1",
            "purpose": "opener",
            "position": "start",
            "status": "active",
            "formula_node": "opener_hook",
        },
        "parent_chain": [],
        "sibling_context": [],
        "active_threads": [],
        "no_active_frame": False,
    }


# --- PlotUnit 字段：向后兼容 + 条件渲染 ---


def test_plotunit_backward_compat_no_hook_type():
    pu = _mk_pu("pu_1")
    assert pu.hook_type is None
    assert "钩子类型" not in pu.to_prompt_context()  # 空字段不渲染 → 与旧版逐字节一致


def test_plotunit_hook_type_rendered_when_present():
    pu = _mk_pu("pu_1", hook="门外叩门", hook_type="revelation")
    ctx = pu.to_prompt_context()
    assert "钩子: 门外叩门" in ctx
    assert "钩子类型: revelation" in ctx


def test_plotunit_hook_type_json_round_trip():
    pu = _mk_pu("pu_1", hook_type="cliffhanger")
    data = pu.model_dump(mode="json")
    assert data["hook_type"] == "cliffhanger"
    pu2 = PlotUnit(**data)
    assert pu2.hook_type == "cliffhanger"


# --- rules：validate_plotunit_hook_type 严格层级校验 ---


def test_hook_type_none_or_empty_valid():
    assert validate_plotunit_hook_type(None, "scene") is True
    assert validate_plotunit_hook_type("", "scene") is True
    assert validate_plotunit_hook_type("  ", "chapter") is True


def test_hook_type_valid_for_level():
    assert validate_plotunit_hook_type("revelation", "scene") is True
    assert validate_plotunit_hook_type("scene_hook", "scene") is True
    assert validate_plotunit_hook_type("transition", "scene") is True
    assert validate_plotunit_hook_type("cliffhanger", "chapter") is True
    assert validate_plotunit_hook_type("in_media_res", "chapter") is True


def test_hook_type_cross_level_invalid():
    # scene 层不许章末钩类型；chapter 层不许 scene 层类型
    assert validate_plotunit_hook_type("cliffhanger", "scene") is False
    assert validate_plotunit_hook_type("reveal", "scene") is False
    assert validate_plotunit_hook_type("revelation", "chapter") is False


def test_hook_type_unmapped_level_no_validation():
    # book/arc 层不映射 → 不校验，避免误报
    assert validate_plotunit_hook_type("cliffhanger", "arc") is True
    assert validate_plotunit_hook_type("任意类型", "book") is True
    assert validate_plotunit_hook_type("x", "unknown_level") is True


def test_get_hook_types_for_level():
    assert get_hook_types_for_level("scene") == {"revelation", "transition", "scene_hook"}
    assert get_hook_types_for_level("chapter") == {
        "cliffhanger",
        "reveal",
        "emotional_peak",
        "promise",
        "in_media_res",
        "mystery_setup",
        "emotional_anchor",
    }
    assert get_hook_types_for_level("book") == set()
    assert get_hook_types_for_level("arc") == set()


def test_get_hook_type_effectiveness():
    assert get_hook_type_effectiveness("revelation", "scene") == "high"
    assert get_hook_type_effectiveness("scene_hook", "scene") == "medium"
    assert get_hook_type_effectiveness("transition", "scene") == "low"
    assert get_hook_type_effectiveness("cliffhanger", "chapter") == "high"
    assert get_hook_type_effectiveness("cliffhanger", "scene") is None  # 跨层级不映射
    assert get_hook_type_effectiveness(None, "scene") is None


def test_build_hook_type_guidance_scene():
    guidance = build_hook_type_guidance("scene")
    assert "【层级钩子类型】" in guidance
    assert "当前层级: scene" in guidance
    assert "revelation（信息揭露, high）" in guidance
    assert "transition（场景过渡, low）" in guidance
    assert "plotunit.hook_type 合法枚举" in guidance


def test_build_hook_type_guidance_chapter():
    guidance = build_hook_type_guidance("chapter")
    assert "cliffhanger（悬念突转, high）" in guidance
    assert "in_media_res（切入动作, high）" in guidance


def test_build_hook_type_guidance_unmapped_empty():
    assert build_hook_type_guidance("book") == ""
    assert build_hook_type_guidance("arc") == ""
    assert build_hook_type_guidance("") == ""


# --- continuation：已知层级时注入，无 frame 时不注入（零成本） ---


def test_continue_prompt_hook_type_section_absent_without_frame():
    prompt = _continue_prompt()
    # 需求条与输出 spec 常驻（特性注入），但指引段本身不注入 → 零成本
    assert "10. hook_type 可选" in prompt
    assert '"hook_type"' in prompt
    assert "plotunit.hook_type 合法枚举" not in prompt
    assert "当前层级: scene" not in prompt


def test_continue_prompt_hook_type_section_injected_for_scene_frame():
    prompt = _continue_prompt(frame_context=_scene_frame_context())
    assert "【层级钩子类型】" in prompt
    assert "当前层级: scene" in prompt
    assert "revelation（信息揭露, high）" in prompt
    assert "plotunit.hook_type 合法枚举" in prompt


def test_continue_prompt_hook_type_section_absent_for_unmapped_level():
    ctx = _scene_frame_context()
    ctx["current_frame"] = {
        **ctx["current_frame"],
        "level": "arc",
        "formula_node": "",
    }
    prompt = _continue_prompt(frame_context=ctx)
    # 需求条 10 常驻引用"【层级钩子类型】"字样，故以指引段体断言不注入
    assert "plotunit.hook_type 合法枚举" not in prompt
    assert "当前层级: arc" not in prompt


# --- review 信号：已填 hook_type 严格校验（blocking），未填走自由文本 ---


def _hook_issues(objects) -> list:
    return [
        i for i in RU._domain_rules(objects)
        if i.issue_id.startswith("iss_hook_") and not i.issue_id.startswith("iss_hook_eff_")
    ]


def test_review_invalid_hook_type_blocking():
    pu = _mk_pu("pu_1", hook="门外叩门", hook_type="cliffhanger", level="scene")
    issues = _hook_issues([pu])
    assert len(issues) == 1
    assert issues[0].severity == "blocking"
    assert "hook_type 'cliffhanger' 对层级 'scene' 不合法" in issues[0].description


def test_review_valid_hook_type_no_issue():
    pu = _mk_pu("pu_1", hook="门外叩门", hook_type="revelation", level="scene")
    assert _hook_issues([pu]) == []


def test_review_hook_type_none_keeps_freetext_path():
    # hook_type 未填：自由文本钩子仍按旧路径校验（非空实质 → 合法）
    pu = _mk_pu("pu_1", hook="功法最后一页的封印内侧落着一个名字", level="scene")
    assert _hook_issues([pu]) == []
    # 自由文本钩子为空 → 不校验
    pu2 = _mk_pu("pu_2", hook=None, hook_type=None, level="scene")
    assert _hook_issues([pu2]) == []


def test_review_hook_type_preferred_for_effectiveness():
    # 关键节点 + 低 effectiveness 显式类型 → iss_hook_eff
    pu = _mk_pu(
        "pu_1",
        hook="门外叩门",
        hook_type="transition",
        formula_node="opener_hook",
        level="scene",
    )
    eff = [
        i for i in RU._domain_rules([pu])
        if i.issue_id.startswith("iss_hook_eff_")
    ]
    assert len(eff) == 1
    assert "transition" in eff[0].description

    # 关键节点 + high effectiveness 显式类型 → 无 iss_hook_eff
    pu2 = _mk_pu(
        "pu_2",
        hook="门外叩门",
        hook_type="revelation",
        formula_node="opener_hook",
        level="scene",
    )
    assert [i for i in RU._domain_rules([pu2]) if i.issue_id.startswith("iss_hook_eff_")] == []


def test_proposal_multi_candidate_spec_has_hook_type():
    from src.workflow_action.proposal_generator import _multi_candidate_output_section

    section = _multi_candidate_output_section(2)
    assert '"hook_type"' in section
    assert "【层级钩子类型】" in section or "钩子类型" in section
