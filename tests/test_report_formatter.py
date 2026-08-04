"""测试 AuditReport markdown 格式化（boundary_control.report_formatter）."""

from src.boundary_control.report_formatter import format_markdown


def test_format_markdown_minimal_report_uses_unknown_defaults():
    text = format_markdown({})

    assert "# Audit 报告" in text
    assert "**源文件**: unknown" in text
    assert "**最终路由**: unknown" in text
    assert "无问题。" in text


def test_format_markdown_header_from_source_and_route():
    text = format_markdown({"source_text_ref": "test.txt", "route": "pass"})

    assert "**源文件**: test.txt" in text
    assert "**最终路由**: pass" in text


def test_format_markdown_workspec_section_renders_fields():
    text = format_markdown(
        {
            "workspec": {
                "genre": "悬疑",
                "theme": "真相",
                "tone": "克制",
                "pacing": "短弧推进",
            }
        }
    )

    assert "## 作品规格" in text
    assert "- 类型: 悬疑" in text
    assert "- 主题: 真相" in text
    assert "- 语调: 克制" in text
    assert "- 节奏: 短弧推进" in text


def test_format_markdown_empty_workspec_omits_section():
    """空 dict 为假值，整个作品规格段被省略."""
    text = format_markdown({"workspec": {}})

    assert "## 作品规格" not in text


def test_format_markdown_workspec_missing_fields_fall_back_to_unknown():
    text = format_markdown({"workspec": {"theme": "真相"}})

    assert "- 类型: unknown" in text
    assert "- 主题: 真相" in text


def test_format_markdown_characters_section_renders_name_and_identity():
    text = format_markdown(
        {
            "characters": [
                {"name": "主角", "identity": "侦探"},
                {"name": "配角"},
            ]
        }
    )

    assert "## 角色" in text
    assert "- **主角** (侦探)" in text
    assert "- **配角** ()" in text


def test_format_markdown_issue_renders_all_fields():
    text = format_markdown(
        {
            "issues": [
                {
                    "severity": "warning",
                    "issue_type": "character_distortion",
                    "location": "第1章",
                    "description": "描述",
                    "violated_rule": "规则",
                }
            ]
        }
    )

    assert "共 1 项" in text
    assert "### [warning] character_distortion" in text
    assert "- 位置: 第1章" in text
    assert "- 描述: 描述" in text
    assert "- 违反规则: 规则" in text


def test_format_markdown_issue_missing_fields_fall_back_to_unknown():
    text = format_markdown({"issues": [{}]})

    assert "### [unknown] unknown" in text
    assert "- 位置: unknown" in text
    assert "- 描述: " in text
    assert "- 违反规则: " in text


def test_format_markdown_reminders_section_renders_nested_details():
    text = format_markdown(
        {
            "reminders": [
                {
                    "priority": "high",
                    "family": "promise_followup_needed",
                    "trigger_condition": "3 plots",
                    "window": "plotunit_count=3",
                    "escalation_issue_type": "missing_consequence",
                    "early_escalation_condition": "repeat",
                    "closure_condition": "advanced",
                }
            ]
        }
    )

    assert "## 提醒" in text
    assert "- [high] promise_followup_needed: 3 plots" in text
    assert "  - window: plotunit_count=3" in text
    assert "  - escalation: missing_consequence" in text
    assert "  - early escalation: repeat" in text
    assert "  - closure: advanced" in text


def test_format_markdown_rewrite_applied_section_renders_original_route_and_fix_count():
    text = format_markdown(
        {
            "rewrite_applied": True,
            "original_route": "block",
            "applied_fixes": [{"fix_id": "f1"}, {"fix_id": "f2"}],
        }
    )

    assert "## 修复记录" in text
    assert "原始路由: block" in text
    assert "应用修复数: 2" in text


def test_format_markdown_confidence_gaps_section_renders_gaps():
    text = format_markdown({"confidence_gaps": ["gap1", "gap2"]})

    assert "## 置信缺口" in text
    assert "- gap1" in text
    assert "- gap2" in text
