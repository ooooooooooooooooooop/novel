"""Tests for style knowledge tables and accessor functions."""

from src.domain_layer.style_rules import (
    build_style_knowledge_context,
    build_tone_guidance,
    get_ai_flavor_markers,
    get_genre_style_guidance,
    get_tone_style_traits,
    get_weak_adverb_set,
    list_available_tones,
    lookup_marker,
)


def test_tone_traits_for_kzhi():
    traits = get_tone_style_traits("克制")
    assert len(traits) >= 3
    first = traits[0]
    assert "trait" in first and "instruction" in first


def test_unknown_tone_returns_empty():
    assert get_tone_style_traits("不存在的调性") == []


def test_build_tone_guidance_contains_tone():
    guidance = build_tone_guidance("克制")
    assert "克制" in guidance
    assert "情绪" in guidance


def test_unknown_tone_guidance_empty():
    assert build_tone_guidance("不存在的调性") == ""


def test_all_tones_have_traits():
    for tone in list_available_tones():
        assert len(get_tone_style_traits(tone)) >= 3, f"{tone} 应至少有 3 条特征"


def test_genre_guidance_xianxia_nonempty():
    assert get_genre_style_guidance("仙侠") != ""


def test_unknown_genre_guidance_empty():
    assert get_genre_style_guidance("不存在的类型") == ""


def test_ai_flavor_markers_has_all_rules():
    markers = get_ai_flavor_markers()
    rule_ids = {m["rule_id"] for m in markers}
    assert len(markers) >= 5
    assert "ai_weak_adverb_density" in rule_ids
    assert "ai_metaphor_repeat" in rule_ids
    assert "ai_explanatory_voice" in rule_ids
    assert "ai_shell_not_a_but_b" in rule_ids
    assert "ai_parallel_four" in rule_ids


def test_marker_fields():
    for marker in get_ai_flavor_markers():
        assert marker["measure_unit"] in ("per_1000_chars", "absolute", "count")
        assert marker["severity"] in ("warning", "low")
        assert marker["instructions"]


def test_lookup_marker():
    marker = lookup_marker("ai_metaphor_repeat")
    assert marker is not None
    assert marker["threshold"] == 3.0
    assert lookup_marker("missing_rule") is None


def test_weak_adverb_set_contains_common_words():
    adverbs = get_weak_adverb_set()
    assert "微微" in adverbs
    assert "轻轻" in adverbs
    assert "淡淡" in adverbs


def test_style_knowledge_context_concatenates():
    context = build_style_knowledge_context(tone="克制", genre="仙侠")
    assert "克制" in context
    assert "仙侠" in context


def test_style_knowledge_context_empty():
    assert build_style_knowledge_context() == ""
