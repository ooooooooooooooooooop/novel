"""Tests for StyleLintUnit — AI 味 lint."""

import pytest

from src.boundary_control.style_metrics import analyze_style_metrics
from src.object_state.styleprofile import StyleRisk
from src.workflow_action.style import StyleLintUnit


def test_lint_clean_text_no_issues():
    clean = (
        "顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。"
        "他这双手在藏书阁待了六年。今天那扇门是开着的。他推开了门。"
    )
    issues = StyleLintUnit().lint(clean)
    assert issues == []


def test_lint_ai_flavored_text_reports():
    bad = "他忽然明白了。" + "他微微点了点头，轻轻说道。" * 10 + "微微" * 10
    issues = StyleLintUnit().lint(bad)
    assert issues, "AI 味文本应检出 issue"
    issue_ids = {issue.issue_id for issue in issues}
    assert "style_lint_ai_weak_adverb_density" in issue_ids
    assert "style_lint_ai_explanatory_voice" in issue_ids


def test_lint_issue_type_and_severity():
    bad = "他忽然明白了。" + "微微" * 20
    issues = StyleLintUnit().lint(bad)
    for issue in issues:
        assert issue.issue_type == "generative_indicia"
        assert issue.severity in ("warning", "low")
        assert issue.scope_of_impact == "表达层"


def test_lint_stats_returns_risks():
    stats = analyze_style_metrics("他忽然明白了。" + "微微" * 20)
    risks = StyleLintUnit().lint_stats(stats)
    rule_ids = {risk.rule_id for risk in risks}
    assert "ai_weak_adverb_density" in rule_ids
    assert "ai_explanatory_voice" in rule_ids
    assert all(risk.category == "ai_flavor" for risk in risks)


def test_risk_threshold_respected():
    # 低于阈值不报
    stats = analyze_style_metrics("这是干净的文本。没有弱化副词。")
    risks = StyleLintUnit().lint_stats(stats)
    assert "ai_weak_adverb_density" not in {risk.rule_id for risk in risks}


def test_lint_stats_connective_marker_fires():
    text = "此外，他走了。同时，他回来了。此外，他又笑了。同时，他又走了。"
    risks = StyleLintUnit().lint_stats(analyze_style_metrics(text))
    rule_ids = {risk.rule_id for risk in risks}
    assert "ai_connective_abuse" in rule_ids
    risk = next(r for r in risks if r.rule_id == "ai_connective_abuse")
    assert risk.value >= 1.0


def test_lint_stats_colon_enumeration_marker_fires():
    text = "一是铺垫，二是推进，三是回收。一是暗线，二是明线，三是主线。"
    risks = StyleLintUnit().lint_stats(analyze_style_metrics(text))
    rule_ids = {risk.rule_id for risk in risks}
    assert "ai_colon_enumeration" in rule_ids
    risk = next(r for r in risks if r.rule_id == "ai_colon_enumeration")
    assert risk.value >= 1.0


def test_lint_emits_connective_abuse_issue():
    bad = "此外，他走了。同时，他回来了。此外，他又笑了。"
    issue_ids = {issue.issue_id for issue in StyleLintUnit().lint(bad)}
    assert "style_lint_ai_connective_abuse" in issue_ids


def test_lint_emits_colon_enumeration_issue():
    bad = "一是铺垫，二是推进，三是回收。一是暗线，二是明线，三是主线。"
    issue_ids = {issue.issue_id for issue in StyleLintUnit().lint(bad)}
    assert "style_lint_ai_colon_enumeration" in issue_ids


def test_lint_clean_text_no_new_rule_ids():
    clean = (
        "顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。"
        "他这双手在藏书阁待了六年。今天那扇门是开着的。他推开了门。"
    )
    issue_ids = {issue.issue_id for issue in StyleLintUnit().lint(clean)}
    assert "style_lint_ai_connective_abuse" not in issue_ids
    assert "style_lint_ai_colon_enumeration" not in issue_ids


def test_lint_connective_threshold_respected():
    # 句首无连接词 → 0 < 阈值 1.0，不报
    stats = analyze_style_metrics("他推开门，走了进去。他手里还攥着钥匙。")
    risks = StyleLintUnit().lint_stats(stats)
    assert "ai_connective_abuse" not in {risk.rule_id for risk in risks}


def test_lint_severity_passthrough_blocking(monkeypatch):
    # 锁 severity passthrough 修复（原实现把 blocking 静默降级为 low）
    unit = StyleLintUnit()

    def fake_lint_stats(self, stats):
        return [
            StyleRisk(
                rule_id="ai_blocking_marker",
                category="ai_flavor",
                measure="blocking 级 marker",
                value=1.0,
                threshold=1.0,
                severity="blocking",
                description="锁定 severity passthrough 修复",
            )
        ]

    monkeypatch.setattr(StyleLintUnit, "lint_stats", fake_lint_stats)
    issues = unit.lint("任意文本。")
    assert len(issues) == 1
    assert issues[0].severity == "blocking"
    assert issues[0].issue_id == "style_lint_ai_blocking_marker"
