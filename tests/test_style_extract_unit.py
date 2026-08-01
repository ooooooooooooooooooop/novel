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
