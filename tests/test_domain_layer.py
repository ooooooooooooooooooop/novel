"""Tests for web-fiction domain-layer rules."""

import pytest

from src.domain_layer.rules import (
    get_platform_constraints,
    get_structure_template,
    list_available_formulas,
    validate_emotional_shift,
    validate_plotunit_hook,
)


def test_eight_node_template_has_eight_nodes():
    template = get_structure_template("eight_node")

    assert len(template) == 8


def test_unknown_structure_template_raises():
    with pytest.raises(ValueError, match="unknown structure template"):
        get_structure_template("missing_template")


def test_valid_chapter_end_hook():
    assert validate_plotunit_hook("cliffhanger", "chapter_end") is True


def test_hook_type_mismatched_level_is_invalid():
    # 显式类型名不属于该层级 → 非法
    assert validate_plotunit_hook("cliffhanger", "scene") is False


def test_freetext_hook_not_rejected_for_level():
    # PlotUnit.hook 是自由文本钩子内容（LLM 生成的句子），
    # 不应因不等于类型枚举而被判"对层级不合法"（旧实现系统性误报的根源）
    assert validate_plotunit_hook("功法最后一页的封印内侧落着一个名字", "scene") is True
    assert validate_plotunit_hook("", "scene") is True  # 无 hook 不验证


def test_valid_catharsis_emotional_shift():
    assert validate_emotional_shift("压抑", "catharsis_arc") is True


def test_web_novel_daily_hook_pressure():
    constraints = get_platform_constraints("web_novel_daily")

    assert constraints["hook_pressure"] == "chapter_end mandatory"


def test_available_formulas_include_three_act():
    assert "three_act" in list_available_formulas()


def test_scene_level_hook_exists():
    from src.domain_layer.rules import validate_plotunit_hook

    assert validate_plotunit_hook("revelation", "scene") is True


def test_five_act_formula_has_five_nodes():
    from src.domain_layer.rules import get_structure_template

    assert len(get_structure_template("five_act")) == 5


def test_comeback_arc_template():
    from src.domain_layer.rules import validate_emotional_shift

    assert validate_emotional_shift("低谷", "comeback_arc") is True
    assert validate_emotional_shift("爆发", "comeback_arc") is True


def test_get_recommended_emotions_for_climax():
    from src.domain_layer.rules import get_recommended_emotions

    emotions = get_recommended_emotions("climax")
    assert "爆发" in emotions


def test_validate_node_emotion_match():
    from src.domain_layer.rules import validate_node_emotion

    assert validate_node_emotion("从压抑到爆发", "climax") is True


def test_validate_node_emotion_mismatch():
    from src.domain_layer.rules import validate_node_emotion

    assert validate_node_emotion("从信任到安稳", "climax") is False


def test_validate_node_emotion_none_returns_true():
    from src.domain_layer.rules import validate_node_emotion

    assert validate_node_emotion(None, "climax") is True
    assert validate_node_emotion("从压抑到爆发", None) is True
    assert validate_node_emotion(None, None) is True


def test_build_platform_guidance_web_novel_daily():
    from src.domain_layer.rules import build_platform_guidance

    guidance = build_platform_guidance("web_novel_daily")
    assert "钩子策略" in guidance
    assert "chapter_end mandatory" in guidance
    assert "读者耐心较低" in guidance


def test_build_platform_guidance_unknown_platform():
    from src.domain_layer.rules import build_platform_guidance

    guidance = build_platform_guidance("nonexistent")
    assert guidance == ""


def test_build_platform_guidance_short_form_burst():
    from src.domain_layer.rules import build_platform_guidance

    guidance = build_platform_guidance("short_form_burst")
    assert "every 500 words" in guidance
    assert "读者耐心极低" in guidance


def test_get_hook_effectiveness():
    from src.domain_layer.rules import get_hook_effectiveness

    assert get_hook_effectiveness("cliffhanger", "chapter_end") == "high"
    assert get_hook_effectiveness("transition", "scene") == "low"
    assert get_hook_effectiveness("unknown", "chapter_end") is None
    assert get_hook_effectiveness("cliffhanger", "unknown_level") is None


def test_is_critical_hook_node():
    from src.domain_layer.rules import is_critical_hook_node

    assert is_critical_hook_node("climax") is True
    assert is_critical_hook_node("resolution") is False
    assert is_critical_hook_node(None) is False


def test_get_genre_guidance_xianxia():
    from src.domain_layer.rules import get_genre_guidance

    guidance = get_genre_guidance("仙侠")
    assert "修为突破必须有代价" in guidance


def test_get_genre_guidance_unknown():
    from src.domain_layer.rules import get_genre_guidance

    assert get_genre_guidance("unknown") == ""
