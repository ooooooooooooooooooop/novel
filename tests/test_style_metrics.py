"""Tests for the pure-code style metrics analyzer."""

from src.boundary_control.style_metrics import (
    analyze_style_metrics,
    detect_dash_colons,
    detect_explanatory_phrases,
    detect_metaphor_repeats,
    detect_shell_patterns,
    dialogue_ratio,
    sentence_length_distribution,
)


def test_weak_adverb_density():
    # 5 微微 in ~914 chars -> density ~5.5/千字
    text = ("微微" * 5) + "，" + ("正" * 900) + "。"
    stats = analyze_style_metrics(text)
    assert stats.weak_adverb_counts["微微"] == 5
    assert stats.weak_adverb_density_per_1000 > 4.0
    assert stats.weak_adverb_density_per_1000 < 7.0


def test_metaphor_repeat_detection():
    text = "记忆像潮水一样涌来。声音像潮水一般退去。情绪像潮水似的漫上来。"
    hits = detect_metaphor_repeats(text)
    assert len(hits) == 1
    assert hits[0].vehicle == "潮水"
    assert hits[0].count == 3
    assert len(hits[0].sample_snippets) >= 1


def test_metaphor_below_threshold_not_reported():
    text = "记忆像潮水一样涌来。风像刀一样刮过。"
    hits = detect_metaphor_repeats(text, min_count=3)
    assert hits == []


def test_explanatory_phrase_count():
    text = "他忽然明白了。这意味着什么。他终于懂了。他觉得累。"
    assert detect_explanatory_phrases(text) == 4


def test_shell_not_a_but_b():
    text = "不是怕，而是悔。不是困。是另一种东西。不是A，而是B。"
    shells = detect_shell_patterns(text)
    assert shells["not_a_but_b"] == 2


def test_parallel_four_anaphora():
    text = "他不记得名字，他不记得藏经阁，他不记得大比，他不记得那张脸。"
    shells = detect_shell_patterns(text)
    assert shells.get("parallel4") == 1


def test_parallel_four_ignores_long_comma_sentence():
    # 普通逗号长句（不同前缀）不是同构排比
    text = "他蹲下身子，擦了擦手，看了看远处，然后站起身，往屋里走。"
    assert detect_shell_patterns(text).get("parallel4") is None


def test_sentence_length_distribution():
    sentences = ["短。", "短句。", "这是一个很长的句子它包含了足够多的字符数并且还有更多的内容一直延续到超过三十个字符。", "中句。"]
    dist = sentence_length_distribution(sentences)
    assert dist["short_ratio"] > 0.2
    assert dist["long_ratio"] > 0.2


def test_dialogue_ratio():
    sentences = ['他说："你好。"', "他点点头。", "天黑了。"]
    ratio = dialogue_ratio(sentences)
    assert 0 < ratio < 1


def test_dash_colon_density_not_double_counted():
    text = "他顿住了——那是他的名字。此处——另起一句。：冒号。"
    density = detect_dash_colons(text)
    # 两个—— = 4 个 —，加 1 个：，共 5 个符号
    assert density > 0
    assert density == 5 / len(text) * 1000


def test_full_analysis_clean_text_no_risks():
    text = (
        "顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。"
        "他这双手在藏书阁待了六年。今天那扇门是开着的。"
        "他推开了门。"
    )
    stats = analyze_style_metrics(text)
    assert stats.total_chars > 0
    assert stats.sentence_count >= 4
    assert stats.metaphor_repeats == []
    assert stats.explanatory_phrase_count == 0
