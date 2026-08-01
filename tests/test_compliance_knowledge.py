"""Tests for compliance_knowledge.py + compliance_rules.py — 合规知识表."""

from src.domain_layer.compliance_knowledge import (
    COMMON_404_WORDS,
    DEFAULT_PLATFORM,
    PLATFORM_POLICY,
    SENSITIVE_LEXICON,
)
from src.domain_layer.compliance_rules import (
    build_lexicon_from_categories,
    get_platform_names,
    get_platform_policy,
    get_sensitive_categories,
    get_sensitive_entries,
)


def test_lexicon_has_all_categories():
    expected_categories = {
        "涉黄",
        "涉政",
        "涉黑",
        "涉赌",
        "涉毒",
        "迷信",
        "暴力",
        "未成年人",
        "宗教民族",
        "性别对立",
    }
    assert set(get_sensitive_categories()) == expected_categories


def test_lexicon_entries_valid():
    entries = get_sensitive_entries()
    assert len(entries) >= 50
    for entry in entries:
        assert entry["word"]
        assert entry["category"] in SENSITIVE_LEXICON
        assert entry["severity"] in {"block", "high", "medium", "low"}
        assert entry["note"]


def test_lexicon_has_redline_categories():
    # 红线分类（block 级）必须存在
    categories = set(get_sensitive_categories())
    assert {"涉黄", "涉政", "涉毒"} <= categories
    # block 级条目必须存在
    block_entries = [e for e in get_sensitive_entries() if e["severity"] == "block"]
    assert block_entries
    assert any("涉黄" == e["category"] for e in block_entries)


def test_build_lexicon_category_filter():
    # 只扫指定分类
    only_politics = build_lexicon_from_categories(categories=["涉政"])
    assert all(e["category"] == "涉政" for e in only_politics)
    # None = 全部分类
    all_entries = build_lexicon_from_categories()
    assert len(all_entries) == len(get_sensitive_entries())


def test_build_lexicon_custom_merge():
    custom = [{"word": "自定义敏感词", "category": "涉政", "severity": "high", "note": "测试"}]
    merged = build_lexicon_from_categories(custom_entries=custom)
    assert len(merged) == len(get_sensitive_entries()) + 1
    assert any(e["word"] == "自定义敏感词" for e in merged)


def test_platform_policy_default_is_generic():
    assert DEFAULT_PLATFORM == "通用"
    policy = get_platform_policy("通用")
    assert policy["ai_direct_output"] == "禁止"
    assert "redline_categories" in policy


def test_platform_policy_unknown_falls_back():
    # 未知平台回退通用
    policy = get_platform_policy("不存在的平台")
    assert policy is PLATFORM_POLICY["通用"]


def test_platform_policy_has_reference_entries():
    platforms = get_platform_names()
    assert "通用" in platforms
    # 具体平台条目作参考（存在但不阻塞）
    for name in ("番茄", "起点", "晋江"):
        assert name in platforms
        policy = get_platform_policy(name)
        assert policy["ai_direct_output"] == "禁止"


def test_common_404_words_present():
    # 404 词（平台过度审查可能误伤的普通词）存在，作提示性参考
    assert COMMON_404_WORDS
    assert "湿" in COMMON_404_WORDS
