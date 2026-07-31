"""Tests for generative_indicia domain-rule checks."""

from src.object_state import PlotUnit
from src.workflow_action.review import ReviewUnit


def test_detects_over_modifiers():
    """过度修饰词达到阈值时生成 generative_indicia."""
    pu = PlotUnit(
        unit_id="pu_001",
        level="scene",
        goal="测试",
        conflict="测试",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
        emotional_shift="不可置信地强大，难以置信地震动",
    )

    issues = ReviewUnit()._domain_rules([pu])
    genind_issues = [i for i in issues if i.issue_type == "generative_indicia"]

    assert len(genind_issues) >= 1
    assert any("不可置信" in i.description for i in genind_issues)


def test_detects_emotional_stacking():
    """情绪标签密度过高时生成 generative_indicia."""
    pu = PlotUnit(
        unit_id="pu_002",
        level="scene",
        goal="测试",
        conflict="测试",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
        released_information=["他崩溃了", "绝望地疯狂", "撕心裂肺地痛苦"],
    )

    issues = ReviewUnit()._domain_rules([pu])
    genind_issues = [i for i in issues if i.issue_type == "generative_indicia"]

    assert any("情绪标记密度" in i.description for i in genind_issues)


def test_detects_goal_repetition():
    """相邻 PlotUnit goal 完全重复时生成 generative_indicia."""
    pu_a = PlotUnit(
        unit_id="pu_003",
        level="scene",
        goal="同一个目标",
        conflict="冲突A",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
    )
    pu_b = PlotUnit(
        unit_id="pu_004",
        level="scene",
        goal="同一个目标",
        conflict="冲突B",
        input_state_ref="ns_2",
        output_state_ref="ns_3",
    )

    issues = ReviewUnit()._domain_rules([pu_a, pu_b])
    genind_issues = [i for i in issues if i.issue_type == "generative_indicia"]

    assert any("goal 与 PlotUnit pu_003 完全重复" in i.description for i in genind_issues)


def test_no_false_positives_on_clean_text():
    """干净文本不应触发 generative_indicia."""
    pu = PlotUnit(
        unit_id="pu_clean",
        level="scene",
        goal="寻找线索",
        conflict="与守卫对峙",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
        emotional_shift="从平静到警觉",
    )

    issues = ReviewUnit()._domain_rules([pu])
    genind_issues = [i for i in issues if i.issue_type == "generative_indicia"]

    assert len(genind_issues) == 0
