"""StyleProfile schema v2 向后兼容 + 渲染测试."""

import pytest

from src.object_state.styleprofile import StyleProfile, StyleQuantitativeStats


def _v1_stats_json() -> dict:
    """v1 风格 stats（无任何 v2 叙事维度字段）."""
    return {
        "total_chars": 1000,
        "sentence_count": 50,
        "avg_sentence_len": 20.0,
        "short_sentence_ratio": 0.3,
        "long_sentence_ratio": 0.4,
        "dialogue_ratio": 0.25,
        "weak_adverb_density_per_1000": 0.5,
        "weak_adverb_counts": {"轻轻": 2},
        "metaphor_repeats": [],
        "explanatory_phrase_count": 1,
        "shell_counts": {},
        "dialogue_tag_density_per_1000": 1.0,
        "emotion_announcement_count": 0,
        "dash_colon_density_per_1000": 2.0,
        "connective_abuse_count": 0,
        "colon_enumeration_count": 0,
    }


def _v1_profile_json() -> dict:
    """完整 v1 StyleProfile JSON（无 schema_version、无 4 个 v2 质性字段）."""
    return {
        "profile_id": "style_001",
        "source_text_ref": "input.txt",
        "tone_labels": ["克制"],
        "genre_guess": "都市官商重生",
        "narrative_pov": "第三人称有限",
        "pacing_description": "叙述默认长句",
        "sentence_habits": ["长句铺陈"],
        "rhetorical_preferences": ["比喻少而实"],
        "show_dont_tell_notes": ["身体反应透情绪"],
        "closed_loop_objects": ["烟"],
        "chapter_end_hook_notes": ["章末埋线"],
        "taboo_words": ["深吸一口气"],
        "style_references": ["tone_kz_01"],
        "stats": _v1_stats_json(),
        "ai_flavor_risks": [],
        "confidence_gaps": [],
    }


def test_v1_profile_deserializes_with_schema_version_1():
    """旧 v1 档案（无 schema_version/无 4 质性字段）可反序列化，schema_version=1."""
    profile = StyleProfile.model_validate(_v1_profile_json())
    assert profile.schema_version == 1
    assert profile.environment_notes == []
    assert profile.scene_transition_notes == []
    assert profile.psychology_notes == []
    assert profile.rhythm_notes == []
    assert profile.stats.scenery_density_per_1000 == 0.0
    assert profile.stats.psych_verb_density_per_1000 == 0.0


def test_v1_stats_deserialize_with_v2_fields_zero():
    """v1 stats JSON（无 v2 字段）反序列化后新字段默认 0."""
    stats = StyleQuantitativeStats.model_validate(_v1_stats_json())
    assert stats.scenery_density_per_1000 == 0.0
    assert stats.scene_transition_count == 0
    assert stats.narration_sentence_ratio == 0.0


def test_v2_profile_round_trip():
    """v2 档案（含 schema_version=2 + 4 质性 + 11 stats）round-trip 保真."""
    profile = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 2,
            "environment_notes": ["白描为主"],
            "scene_transition_notes": ["第二天硬切"],
            "psychology_notes": ["间接内独白"],
            "rhythm_notes": ["叙述/对话约 4:3"],
            "stats": {
                **_v1_stats_json(),
                "scenery_density_per_1000": 3.1,
                "scene_transition_count": 2,
            },
        }
    )
    assert profile.schema_version == 2
    assert profile.environment_notes == ["白描为主"]
    assert profile.stats.scenery_density_per_1000 == 3.1
    # round-trip
    reloaded = StyleProfile.model_validate_json(profile.model_dump_json())
    assert reloaded.schema_version == 2
    assert reloaded.stats.scene_transition_count == 2


def test_v1_profile_render_no_v2_line():
    """v1 档案渲染不产生叙事维度量化行（与旧版逐字节兼容）。"""
    profile = StyleProfile.model_validate(_v1_profile_json())
    ctx = profile.to_prompt_context()
    assert "叙事维度量化" not in ctx
    assert "环境/景物描写" not in ctx
    assert ctx.startswith("【写作风格画像】")


def test_v2_profile_render_v2_blocks():
    """v2 档案渲染含新质性块 + 叙事维度量化行."""
    profile = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 2,
            "environment_notes": ["白描为主，景物承担交代时空"],
            "rhythm_notes": ["叙述句占比高"],
            "stats": {
                **_v1_stats_json(),
                "scenery_density_per_1000": 3.1,
                "narration_sentence_ratio": 0.6,
            },
        }
    )
    ctx = profile.to_prompt_context()
    assert "环境/景物描写:" in ctx
    assert "叙事节奏与结构:" in ctx
    assert "叙事维度量化" in ctx
    # 空字段不渲染
    assert "场景转换与过渡:" not in ctx
    assert "心理与内视角:" not in ctx


def test_to_prompt_context_include_header_false():
    """include_header=False 跳过【写作风格画像】首行."""
    profile = StyleProfile.model_validate(_v1_profile_json())
    ctx = profile.to_prompt_context(include_header=False)
    assert not ctx.startswith("【写作风格画像】")
    assert ctx.startswith("调性:")


def test_v2_blank_notes_render_identical_to_v1():
    """v2 但 4 质性空 + 11 stats 零 → 渲染与 v1 逐字节相同（仅 schema_version 差异不计入）."""
    v2_blank = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 2,
        }
    )
    v1 = StyleProfile.model_validate(_v1_profile_json())
    assert v2_blank.to_prompt_context() == v1.to_prompt_context()
