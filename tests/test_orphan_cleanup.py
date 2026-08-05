"""E 档孤儿清理验证测试.

覆盖：
- 已删除的孤儿符号不再存在（真孤儿）
- 保留的活 helper / test-fed getter 仍可访问
- style.py 不再持有死 import（消费方仍可 import）
"""

from src.domain_layer import rules, style_knowledge, style_rules
from src.workflow_action import style as style_action


# ---------- 已删除孤儿不存在 ----------

def test_style_knowledge_orphans_removed():
    for name in ("PARALLEL_ITEM_SEP", "AUTHOR_STYLE_ANCHORS", "TEMPERAMENT_NAMES"):
        assert not hasattr(style_knowledge, name), name


def test_rules_list_platforms_removed():
    assert not hasattr(rules, "list_platforms")


def test_style_rules_getter_group_removed():
    removed = (
        "get_description_techniques",
        "get_omission_axis",
        "get_subtle_techniques",
        "get_character_methods",
        "get_dialogue_techniques",
        "get_decision_grounding_axis",
        "get_temperament_buckets",
        "list_available_temperaments",
    )
    for name in removed:
        assert not hasattr(style_rules, name), name


# ---------- 保留活 helper / test-fed getter ----------

def test_style_rules_live_helpers_kept():
    for name in (
        "get_temperament_bucket",
        "build_temperament_guidance",
        "build_worldview_axis_guidance",
        "build_style_knowledge_context",
        "get_ai_flavor_markers",
        "list_available_tones",
        "get_tone_style_traits",
        "lookup_marker",
    ):
        assert hasattr(style_rules, name), name


def test_style_rules_test_fed_getters_kept():
    # test_style_knowledge.py 引用的 test-fed getter 保留
    for name in (
        "get_genre_style_guidance",
        "get_weak_adverb_set",
        "build_tone_guidance",
    ):
        assert hasattr(style_rules, name), name


def test_rules_test_fed_helpers_kept():
    # test 引用的 helpers 保留（非孤儿）
    for name in ("list_available_formulas", "validate_emotional_shift"):
        assert hasattr(rules, name), name


# ---------- style.py 消费方无死 import ----------

def test_style_action_imports_clean():
    # style.py 只依赖保留符号，import 本身不抛错即通过
    assert callable(style_action.auto_style_id) or hasattr(style_action, "auto_style_id")


def test_style_action_only_imports_live_getters():
    # 确认 style.py 未引用已删除符号
    import src.workflow_action.style as style_mod

    for name in ("PARALLEL_ITEM_SEP", "AUTHOR_STYLE_ANCHORS", "TEMPERAMENT_NAMES"):
        assert not hasattr(style_mod, name), name
