"""Tests for StyleLintUnit — AI 味 lint."""

from src.boundary_control.style_metrics import analyze_style_metrics
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
