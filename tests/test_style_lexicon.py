"""style_lexicon 词表 + 叙事维度 detector 测试."""

import pytest

from src.boundary_control.style_metrics import (
    analyze_style_metrics,
    detect_action_metrics,
    detect_narrative_ratio,
    detect_psych_metrics,
    detect_scenery_metrics,
    detect_transition_metrics,
)
from src.domain_layer.style_lexicon import (
    ACTION_VERBS,
    EXPLICIT_TRANSITION_MARKERS,
    INNER_MONOLOGUE_PHRASES,
    PSYCH_VERBS,
    SCENERY_NOUNS,
    SENSORY_VERBS,
    TIME_MARKERS,
)

_LEXICONS = (
    SCENERY_NOUNS,
    SENSORY_VERBS,
    TIME_MARKERS,
    EXPLICIT_TRANSITION_MARKERS,
    PSYCH_VERBS,
    INNER_MONOLOGUE_PHRASES,
    ACTION_VERBS,
)


@pytest.mark.parametrize("lexicon", _LEXICONS)
def test_lexicon_non_empty_and_no_blank(lexicon):
    """每个词表非空、无空串、无双字以下词（单字误报高）。"""
    assert lexicon, "词表不应为空"
    for word in lexicon:
        assert word.strip() == word
        assert word, "词条不应为空"
        assert len(word) >= 2, f"单字词误报高不应收录: {word!r}"


def test_scenery_metrics_detects_scenery():
    """含景物名词+感官动词的文本 → 密度/句占比 > 0."""
    text = (
        "暮色四合，远山的树影落在湖面上。"
        "他凝视着余晖，山峦的轮廓在霞光里渐渐模糊。"
    )
    m = detect_scenery_metrics(text)
    assert m["scenery_density_per_1000"] > 0
    assert m["scenery_sentence_ratio"] > 0


def test_transition_metrics_detects_time_jump():
    """时间跳转（第二天）→ 场景转换计数/时间标记密度 > 0."""
    text = "第二天，他站在江边。\n与此同时，办公室里的人已经散了大半。"
    m = detect_transition_metrics(text)
    assert m["scene_transition_count"] >= 1
    assert m["time_marker_density_per_1000"] > 0


def test_psych_metrics_detects_inner_monologue():
    """心理动词+内独白 → 心理密度/句占比/内独白占比 > 0."""
    text = "他心想，这件事不能再拖了。主角暗自盘算着下一步的棋。"
    m = detect_psych_metrics(text)
    assert m["psych_verb_density_per_1000"] > 0
    assert m["psych_sentence_ratio"] > 0
    assert m["inner_monologue_sentence_ratio"] > 0


def test_action_metrics_detects_actions():
    """动作动词 → 动作密度/句占比 > 0."""
    text = "他站起身，握紧拳头，转身推开门冲了出去。"
    m = detect_action_metrics(text)
    assert m["action_verb_density_per_1000"] > 0
    assert m["action_sentence_ratio"] > 0


def test_narrative_ratio_is_remainder():
    """叙述句占比是余集：纯叙述无引号无动作无景物无心理 → 高占比."""
    from src.boundary_control.style_metrics import _split_sentences

    sentences = _split_sentences(
        "这件事的背景早已埋下，只是当时无人察觉。局势在暗中慢慢起变化。"
    )
    ratio = detect_narrative_ratio(sentences)
    assert 0.0 < ratio <= 1.0


def test_analyze_style_metrics_has_v2_fields():
    """analyze_style_metrics 产出全部 11 个 v2 叙事维度字段."""
    text = (
        "暮色落在江面上，他站在船头凝视远山。"
        "主角心想，第二天必须有个决断。"
        "他转身握紧栏杆，片刻没有作声。"
    )
    s = analyze_style_metrics(text)
    for field in (
        "scenery_density_per_1000",
        "sensory_density_per_1000",
        "scenery_sentence_ratio",
        "scene_transition_count",
        "time_marker_density_per_1000",
        "psych_verb_density_per_1000",
        "psych_sentence_ratio",
        "inner_monologue_sentence_ratio",
        "action_verb_density_per_1000",
        "action_sentence_ratio",
        "narration_sentence_ratio",
    ):
        assert hasattr(s, field), f"缺失 v2 字段 {field}"
