"""Tests for StyleExtractUnit — build_prompt / parse_response / merge."""

import json

import pytest

from src.boundary_control.style_metrics import analyze_style_metrics
from src.workflow_action.style import StyleExtractUnit, StyleLintUnit


def _valid_response() -> dict:
    return {
        "tone_labels": ["克制"],
        "genre_guess": "古典仙侠",
        "narrative_pov": "第三人称有限",
        "pacing_description": "叙述默认长句，情绪爆点短句独立成段",
        "sentence_habits": ["情绪靠身体反应"],
        "rhetorical_preferences": ["具象物比喻"],
        "show_dont_tell_notes": ["恐惧→冷汗/攥拳"],
        "closed_loop_objects": ["旧发带"],
        "chapter_end_hook_notes": ["章末留疑问钩"],
        "taboo_words": ["轻轻", "淡淡"],
        "style_references": ["tone_kz_01"],
        "confidence_gaps": [],
    }


def test_build_prompt_contains_sections():
    unit = StyleExtractUnit()
    prompt = unit.build_prompt(
        samples_text="第一章：顾临蹲在藏经阁。",
        total_stats={"chapter_count": 8, "total_chars": 14179, "avg_chars_per_chapter": 1772},
        quantitative_context="弱化副词密度: 0.42/千字",
        style_knowledge_context="【调性: 克制】",
    )
    assert "【输入文本（章节采样）】" in prompt
    assert "【量化分析（纯代码，已算出）】" in prompt
    assert "【风格知识参考（分类轴）】" in prompt
    assert "tone_labels" in prompt


def test_build_prompt_without_knowledge():
    unit = StyleExtractUnit()
    prompt = unit.build_prompt(
        samples_text="样本",
        total_stats={},
        quantitative_context="",
    )
    assert "【风格知识参考（分类轴）】" not in prompt


def test_parse_response_valid():
    unit = StyleExtractUnit()
    parsed = unit.parse_response(json.dumps(_valid_response(), ensure_ascii=False))
    assert parsed["tone_labels"] == ["克制"]
    assert parsed["narrative_pov"] == "第三人称有限"


def test_parse_response_missing_field():
    unit = StyleExtractUnit()
    resp = _valid_response()
    del resp["taboo_words"]
    with pytest.raises(ValueError, match="missing required field"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_parse_response_extra_field():
    unit = StyleExtractUnit()
    resp = _valid_response()
    resp["unknown_field"] = 1
    with pytest.raises(ValueError, match="unexpected field"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_parse_response_blank_list_item():
    unit = StyleExtractUnit()
    resp = _valid_response()
    resp["sentence_habits"] = [""]
    with pytest.raises(ValueError, match="list of strings"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_parse_response_blank_string():
    unit = StyleExtractUnit()
    resp = _valid_response()
    resp["narrative_pov"] = ""
    with pytest.raises(ValueError, match="non-empty string"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_merge_produces_valid_profile():
    unit = StyleExtractUnit()
    stats = analyze_style_metrics("这是测试文本。他说道。他忽然明白了。")
    risks = StyleLintUnit().lint_stats(stats)
    profile = unit.merge(
        _valid_response(),
        stats=stats,
        risks=risks,
        source_text_ref="t.txt",
    )
    assert profile.tone_labels == ["克制"]
    assert profile.genre_guess == "古典仙侠"
    assert profile.stats.total_chars == len("这是测试文本。他说道。他忽然明白了。")
    assert profile.confidence_gaps == []
    assert profile.to_prompt_context() != ""


def test_merge_unknown_tone_to_confidence_gaps():
    unit = StyleExtractUnit()
    stats = analyze_style_metrics("测试。")
    resp = _valid_response()
    resp["tone_labels"] = ["不存在的调性"]
    profile = unit.merge(resp, stats=stats, risks=[], source_text_ref="t.txt")
    assert profile.tone_labels == []
    assert "未知调性标签: 不存在的调性" in profile.confidence_gaps


def test_merge_keeps_weizhubiao():
    unit = StyleExtractUnit()
    stats = analyze_style_metrics("测试。")
    resp = _valid_response()
    resp["tone_labels"] = ["未标注"]
    profile = unit.merge(resp, stats=stats, risks=[], source_text_ref="t.txt")
    assert profile.tone_labels == ["未标注"]


# --- v3: 写作手法世界观（temperament + 6 质性轴）---


def test_build_prompt_injects_worldview_axis_and_temperament():
    unit = StyleExtractUnit()
    prompt = unit.build_prompt(
        samples_text="样本",
        total_stats={},
        quantitative_context="",
        style_knowledge_context="【调性: 克制】",
        temperament="散文型",
        worldview_axis_context="【描写手法轴】\n- 白描: ...",
    )
    assert "【写作手法世界观（完整分类轴）】" in prompt
    assert "【描写手法轴】" in prompt
    assert "12. temperament" in prompt
    assert "description_layering_notes" in prompt


def test_build_prompt_without_worldview_defaults_omitted():
    unit = StyleExtractUnit()
    prompt = unit.build_prompt(
        samples_text="样本", total_stats={}, quantitative_context=""
    )
    assert "【写作手法世界观（完整分类轴）】" not in prompt


def _v3_response() -> dict:
    return {
        **_valid_response(),
        "temperament": "散文型",
        "description_layering_notes": ["白描为本，衬托带情绪"],
        "omission_notes": ["关键动作写细，过渡一笔带过"],
        "subtle_technique_notes": ["闭环物象作象征"],
        "character_method_notes": ["动作/神态为主"],
        "dialogue_technique_notes": ["对白带潜文本"],
        "decision_grounding_notes": ["选择由身份与信念驱动"],
    }


def test_parse_response_v3_fields():
    unit = StyleExtractUnit()
    parsed = unit.parse_response(json.dumps(_v3_response(), ensure_ascii=False))
    assert parsed["temperament"] == "散文型"
    assert parsed["description_layering_notes"] == ["白描为本，衬托带情绪"]
    assert parsed["decision_grounding_notes"] == ["选择由身份与信念驱动"]


def test_parse_response_v3_fields_optional_default():
    """v3 字段缺省 → 补 []，temperament 补 None（向后兼容旧 response）. """
    unit = StyleExtractUnit()
    parsed = unit.parse_response(json.dumps(_valid_response(), ensure_ascii=False))
    assert parsed["temperament"] is None
    assert parsed["omission_notes"] == []
    assert parsed["character_method_notes"] == []


def test_parse_response_temperament_blank_rejected():
    unit = StyleExtractUnit()
    resp = _valid_response()
    resp["temperament"] = "  "
    with pytest.raises(ValueError, match="temperament"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_parse_response_temperament_non_str_rejected():
    unit = StyleExtractUnit()
    resp = _valid_response()
    resp["temperament"] = 123
    with pytest.raises(ValueError, match="temperament"):
        unit.parse_response(json.dumps(resp, ensure_ascii=False))


def test_merge_v3_fields_round_trip():
    unit = StyleExtractUnit()
    stats = analyze_style_metrics("顾临蹲在藏经阁。他轻轻放下了册子。")
    profile = unit.merge(
        _v3_response(),
        stats=stats,
        risks=[],
        source_text_ref="t.txt",
    )
    assert profile.schema_version == 3
    assert profile.temperament == "散文型"
    assert profile.description_layering_notes == ["白描为本，衬托带情绪"]
    assert profile.omission_notes == ["关键动作写细，过渡一笔带过"]
    assert profile.subtle_technique_notes == ["闭环物象作象征"]
    assert profile.character_method_notes == ["动作/神态为主"]
    assert profile.dialogue_technique_notes == ["对白带潜文本"]
    assert profile.decision_grounding_notes == ["选择由身份与信念驱动"]
    ctx = profile.to_prompt_context()
    assert "叙事气质: 散文型" in ctx
    assert "描写手法:" in ctx


def test_merge_v3_blank_fields_render_like_v1():
    """无 v3 字段的旧 response → merge 后 v3 字段空，渲染不产生 v3 行."""
    unit = StyleExtractUnit()
    stats = analyze_style_metrics("测试。")
    profile = unit.merge(_valid_response(), stats=stats, risks=[], source_text_ref="t.txt")
    assert profile.schema_version == 3
    assert profile.temperament is None
    assert profile.description_layering_notes == []
    ctx = profile.to_prompt_context()
    assert "叙事气质" not in ctx
    assert "描写手法:" not in ctx
    assert "决策依据" not in ctx
