"""Tests for the pure-code style metrics analyzer."""

from src.boundary_control.style_metrics import (
    analyze_style_metrics,
    detect_bystander_reaction,
    detect_colon_enumeration,
    detect_connective_abuse,
    detect_dash_colons,
    detect_decision_grounding_markers,
    detect_explanatory_phrases,
    detect_key_segment_len_ratio,
    detect_metaphor_repeats,
    detect_modifier_load,
    detect_omission_markers,
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


def test_detect_connective_abuse_sentence_start():
    text = "此外，他走了。同时，他回来了。"
    assert detect_connective_abuse(text) == 2


def test_detect_connective_abuse_clean_and_mid_sentence_ignored():
    assert detect_connective_abuse("他推开门，走了进去。") == 0
    # 句中"同时"不算句首连接词滥用
    assert detect_connective_abuse("他同时走了。") == 0


def test_detect_colon_enumeration():
    text = "一是铺垫，二是推进，三是回收。"
    assert detect_colon_enumeration(text) == 1


def test_detect_colon_enumeration_clean():
    assert detect_colon_enumeration("他推开门，走了进去。") == 0
    # 缺"三是"不算完整枚举
    assert detect_colon_enumeration("一是铺垫，二是推进。") == 0


def test_style_stats_backward_compat_old_json():
    # 旧 style_profile.json 无新字段，反序列化必须成功且默认 0（Phase 2 先例）
    from src.object_state.styleprofile import StyleQuantitativeStats

    old_payload = {
        "total_chars": 100,
        "sentence_count": 5,
        "avg_sentence_len": 20.0,
        "short_sentence_ratio": 0.2,
        "long_sentence_ratio": 0.1,
        "dialogue_ratio": 0.3,
        "weak_adverb_density_per_1000": 1.0,
        "weak_adverb_counts": {},
        "metaphor_repeats": [],
        "explanatory_phrase_count": 0,
        "shell_counts": {},
        "dialogue_tag_density_per_1000": 0.0,
        "emotion_announcement_count": 0,
        "dash_colon_density_per_1000": 0.0,
    }
    stats = StyleQuantitativeStats.model_validate(old_payload)
    assert stats.connective_abuse_count == 0
    assert stats.colon_enumeration_count == 0


# --- v3: 写作手法世界观代理指标 ---


def test_modifier_load_positive_for_adverb_heavy_text():
    # "非常/十分/极其" 高修饰负载 → 白描负代理值高
    text = "他非常非常生气，十分愤怒，极其痛苦地攥紧了拳头。"
    assert detect_modifier_load(text) > 0


def test_modifier_load_zero_for_baimiao_text():
    # 白描文本（动词+名词）修饰负载低
    text = "他蹲在藏经阁的地板缝边上，把册子插回架。"
    assert detect_modifier_load(text) == 0.0


def test_bystander_reaction_density_and_ratio():
    text = "众人倒吸一口凉气。他抬了一眼，全场瞬间死寂。围观的人窃窃私语。"
    density, ratio = detect_bystander_reaction(text)
    assert density > 0
    assert ratio > 0
    assert 0.0 <= ratio <= 1.0


def test_bystander_reaction_clean_zero():
    text = "他蹲下身子，擦了擦手，往屋里走。"
    density, ratio = detect_bystander_reaction(text)
    assert density == 0.0
    assert ratio == 0.0


def test_omission_markers_counts_ellipsis():
    text = "他没有再说下去…… 那一夜…… 或许永远。"
    assert detect_omission_markers(text) == 2


def test_omission_markers_clean_zero():
    assert detect_omission_markers("他推开门，走了进去。") == 0


def test_decision_grounding_markers_density():
    text = "作为城主，他不得不做出这个决定。出于对宗门的责任，他宁可自己担责。"
    assert detect_decision_grounding_markers(text) > 0


def test_decision_grounding_clean_zero():
    assert detect_decision_grounding_markers("他推开门，走了进去。") == 0.0


def test_key_segment_len_ratio_dense_vs_transition():
    # 关键段写细、过渡段一笔带过 → 比值 > 1
    text = (
        "关键高潮段落非常非常长，描写每一个动作每一个眼神每一个细节"
        "都展开来写，让读者沉浸其中感受当时的紧张与压迫感。\n"
        "关键高潮第二段同样很长，继续铺陈情绪与动作，毫不吝惜笔墨。\n"
        "过了。\n"
        "第二天。\n"
        "他走了。\n"
        "三日后。\n"
    )
    assert detect_key_segment_len_ratio(text) > 1.0


def test_key_segment_len_ratio_uniform_near_one():
    # 均匀段落 → 比值接近 1
    text = "第一段话。\n第二段话。\n第三段话。\n第四段话。\n第五段话。\n"
    ratio = detect_key_segment_len_ratio(text)
    assert 0.0 < ratio <= 1.5


def test_key_segment_len_ratio_few_paragraphs_zero():
    assert detect_key_segment_len_ratio("只有一段。") == 0.0


def test_analyze_style_metrics_includes_v3_fields():
    text = "众人倒吸一口凉气。他非常冷静地转过身。……他不得不继续走下去。"
    stats = analyze_style_metrics(text)
    assert stats.modifier_load_density > 0
    assert stats.bystander_reaction_density > 0
    assert stats.omission_marker_count > 0
    assert stats.decision_grounding_marker_density > 0


def test_analyze_v3_all_zero_on_clean_text():
    # 干净文本 → 全部代理指标零（零风险、零注入契约）
    text = "他蹲在藏经阁的地板缝边上，把册子插回架。"
    stats = analyze_style_metrics(text)
    assert stats.modifier_load_density == 0.0
    assert stats.bystander_reaction_density == 0.0
    assert stats.foil_sentence_ratio == 0.0
    assert stats.omission_marker_count == 0
    assert stats.decision_grounding_marker_density == 0.0
