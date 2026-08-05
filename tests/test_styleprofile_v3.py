"""StyleProfile schema v3 — 写作手法世界观字段：向后兼容 + 零成本渲染契约.

v3 新增（全部 Optional + 全零静默）：
- temperament: Optional[str]（叙事气质）
- description_layering_notes / omission_notes / subtle_technique_notes /
  character_method_notes / dialogue_technique_notes / decision_grounding_notes: list[str]
- StyleQuantitativeStats 6 个世界观代理指标（全零默认）
"""

import pytest

from src.object_state.styleprofile import StyleProfile, StyleQuantitativeStats


def _v1_stats_json() -> dict:
    """v1 风格 stats（无 v2/v3 字段）."""
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
    """完整 v1 StyleProfile JSON（无 v2/v3 字段）."""
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


# --- 向后兼容：v1/v2 档案反序列化 v3 字段默认值 ---


def test_v1_profile_deserializes_v3_fields_default():
    """旧 v1 档案（无 v3 字段）反序列化后新字段默认 None/[]."""
    profile = StyleProfile.model_validate(_v1_profile_json())
    assert profile.temperament is None
    assert profile.description_layering_notes == []
    assert profile.omission_notes == []
    assert profile.subtle_technique_notes == []
    assert profile.character_method_notes == []
    assert profile.dialogue_technique_notes == []
    assert profile.decision_grounding_notes == []
    assert profile.stats.modifier_load_density == 0.0
    assert profile.stats.bystander_reaction_density == 0.0
    assert profile.stats.foil_sentence_ratio == 0.0
    assert profile.stats.omission_marker_count == 0
    assert profile.stats.decision_grounding_marker_density == 0.0
    assert profile.stats.key_segment_len_ratio == 0.0


def test_v1_stats_deserialize_v3_fields_zero():
    """v1 stats JSON（无 v3 字段）反序列化后新字段默认 0."""
    stats = StyleQuantitativeStats.model_validate(_v1_stats_json())
    assert stats.modifier_load_density == 0.0
    assert stats.omission_marker_count == 0


# --- v3 档案 round-trip 保真 ---


def test_v3_profile_round_trip():
    """v3 档案（含 temperament + 6 质性 + 6 stats）round-trip 保真."""
    profile = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 3,
            "temperament": "散文型",
            "description_layering_notes": ["白描为本，衬托带情绪"],
            "omission_notes": ["关键动作写细，过渡一笔带过"],
            "subtle_technique_notes": ["闭环物象作象征"],
            "character_method_notes": ["动作/神态为主"],
            "dialogue_technique_notes": ["对白带潜文本"],
            "decision_grounding_notes": ["选择由身份与信念驱动"],
            "stats": {
                **_v1_stats_json(),
                "modifier_load_density": 2.5,
                "omission_marker_count": 3,
            },
        }
    )
    assert profile.schema_version == 3
    assert profile.temperament == "散文型"
    assert profile.description_layering_notes == ["白描为本，衬托带情绪"]
    assert profile.stats.modifier_load_density == 2.5
    reloaded = StyleProfile.model_validate_json(profile.model_dump_json())
    assert reloaded.schema_version == 3
    assert reloaded.temperament == "散文型"
    assert reloaded.stats.omission_marker_count == 3


# --- 零成本渲染契约：空字段 → 与 v1 逐字节相同 ---


def test_v1_profile_render_no_v3_lines():
    """v1 档案渲染不产生世界观质性/量化行（与旧版逐字节兼容）。"""
    profile = StyleProfile.model_validate(_v1_profile_json())
    ctx = profile.to_prompt_context()
    assert "叙事气质" not in ctx
    assert "描写手法" not in ctx
    assert "留白与详略" not in ctx
    assert "含蓄手法" not in ctx
    assert "人物刻画手法" not in ctx
    assert "对白技巧" not in ctx
    assert "决策依据" not in ctx
    assert "世界观量化" not in ctx


def test_v3_blank_fields_render_identical_to_v1():
    """v3 但全部新字段空/None → 渲染与 v1 逐字节相同（零成本契约）。"""
    v3_blank = StyleProfile.model_validate(
        {**_v1_profile_json(), "schema_version": 3}
    )
    v1 = StyleProfile.model_validate(_v1_profile_json())
    assert v3_blank.to_prompt_context() == v1.to_prompt_context()


def test_v3_profile_render_v3_blocks():
    """v3 档案渲染含新质性块 + 世界观量化行."""
    profile = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 3,
            "temperament": "散文型",
            "description_layering_notes": ["白描为本，衬托带情绪"],
            "omission_notes": ["关键动作写细，过渡一笔带过"],
            "subtle_technique_notes": ["闭环物象作象征"],
            "character_method_notes": ["动作/神态为主"],
            "dialogue_technique_notes": ["对白带潜文本"],
            "decision_grounding_notes": ["选择由身份与信念驱动"],
            "stats": {
                **_v1_stats_json(),
                "modifier_load_density": 2.5,
                "omission_marker_count": 3,
            },
        }
    )
    ctx = profile.to_prompt_context()
    assert "叙事气质: 散文型" in ctx
    assert "描写手法:" in ctx
    assert "留白与详略:" in ctx
    assert "含蓄手法:" in ctx
    assert "人物刻画手法:" in ctx
    assert "对白技巧:" in ctx
    assert "决策依据:" in ctx
    assert "世界观量化" in ctx
    # 未填的新质性字段不渲染
    assert "场景转换与过渡:" not in ctx  # v2 字段仍空
    assert "心理与内视角:" not in ctx


def test_v3_qualitative_render_without_stats_zero():
    """v3 质性字段非空但 stats 全零 → 只渲染质性块，无量化行."""
    profile = StyleProfile.model_validate(
        {
            **_v1_profile_json(),
            "schema_version": 3,
            "temperament": "氛围型",
            "character_method_notes": ["肖像+神态"],
        }
    )
    ctx = profile.to_prompt_context()
    assert "叙事气质: 氛围型" in ctx
    assert "人物刻画手法:" in ctx
    assert "世界观量化" not in ctx


# --- validator：非空校验覆盖新字段 ---


def test_temperament_blank_rejected():
    with pytest.raises(ValueError):
        StyleProfile.model_validate(
            {**_v1_profile_json(), "temperament": "  "}
        )


def test_v3_notes_blank_entry_rejected():
    with pytest.raises(ValueError):
        StyleProfile.model_validate(
            {**_v1_profile_json(), "omission_notes": ["有效", "  "]}
        )
