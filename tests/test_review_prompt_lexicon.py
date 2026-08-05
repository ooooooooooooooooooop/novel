"""B/D 档 review prompt 注入测试.

覆盖：
- B 档：【失败类型字典】16 类全注入，含默认严重度 + 阻断倾向
- D 档：【信息凭证约束】注入（通道谱系 / 聚焦三分 / 凭证约束 P1-P4）
- 【信息差距形态】合法/非法 4+4 注入
"""

from src.workflow_action.review import FAILURE_TYPE_LEXICON, ReviewUnit


def test_review_prompt_contains_failure_type_lexicon():
    prompt = ReviewUnit().build_prompt([], context="audit")
    assert "【失败类型字典】" in prompt


def test_failure_type_lexicon_covers_all_16_types():
    types = [t[0] for t in FAILURE_TYPE_LEXICON]
    expected = {
        "fact_conflict",
        "world_violation",
        "timeline_error",
        "character_distortion",
        "information_leak",
        "abrupt_payoff",
        "motivation_gap",
        "relationship_jump",
        "weak_progression",
        "missing_cost",
        "promise_loss",
        "missing_consequence",
        "duplication_of_threads",
        "redundancy",
        "style_drift",
        "generative_indicia",
    }
    assert set(types) == expected


def test_failure_type_lexicon_each_entry_has_severity_and_blocking():
    for entry in FAILURE_TYPE_LEXICON:
        assert len(entry) == 3
        assert entry[0]
        assert entry[1]
        assert entry[2]


def test_review_prompt_renders_each_failure_type_with_blocking():
    prompt = ReviewUnit().build_prompt([], context="audit")
    for issue_type, severity, blocking in FAILURE_TYPE_LEXICON:
        assert f"- {issue_type}（默认 {severity}，{blocking}）" in prompt


def test_review_prompt_contains_duplication_of_threads_entry():
    prompt = ReviewUnit().build_prompt([], context="audit")
    assert "duplication_of_threads" in prompt


def test_review_prompt_contains_info_warrant_guidance():
    prompt = ReviewUnit().build_prompt([], context="audit")
    assert "【信息通道谱系】" in prompt
    assert "【聚焦三分】" in prompt
    assert "【凭证约束】" in prompt


def test_review_prompt_contains_p1_p4_constraints():
    prompt = ReviewUnit().build_prompt([], context="audit")
    for rule_id in ("P1", "P2", "P3", "P4"):
        assert rule_id in prompt


def test_review_prompt_contains_info_gap_forms():
    prompt = ReviewUnit().build_prompt([], context="audit")
    assert "【信息差距形态】" in prompt
    assert "[合法]" in prompt
    assert "[非法]" in prompt
    for gap_name in ("神秘", "悬念", "通道越界", "知识域翻转"):
        assert gap_name in prompt


def test_review_prompt_still_has_track_constraints_and_format():
    prompt = ReviewUnit().build_prompt([], context="audit")
    assert "【Track 1 约束】" in prompt
    assert "【Track 3 约束】" in prompt
    assert "【输出格式】严格输出 JSON" in prompt


def test_review_prompt_lexicon_order_stable():
    # 字典顺序稳定（元组序），供回归锁定
    prompt = ReviewUnit().build_prompt([], context="audit")
    idx_fact = prompt.index("fact_conflict")
    idx_world = prompt.index("world_violation")
    idx_redundancy = prompt.index("redundancy")
    assert idx_fact < idx_world < idx_redundancy
