"""AuditReport markdown formatting."""


def format_markdown(report_data: dict) -> str:
    """Convert an AuditReport dict to Markdown text."""
    lines = [
        "# Audit 报告",
        "",
        f"**源文件**: {report_data.get('source_text_ref', 'unknown')}",
        f"**最终路由**: {report_data.get('route', 'unknown')}",
        "",
    ]

    if ws := report_data.get("workspec"):
        lines.extend(
            [
                "## 作品规格",
                f"- 类型: {ws.get('genre', 'unknown')}",
                f"- 主题: {ws.get('theme', 'unknown')}",
                f"- 语调: {ws.get('tone', 'unknown')}",
                f"- 节奏: {ws.get('pacing', 'unknown')}",
                "",
            ]
        )

    if chars := report_data.get("characters"):
        lines.extend(
            [
                "## 角色",
                *[
                    f"- **{c.get('name', 'unknown')}** ({c.get('identity', '')})"
                    for c in chars
                ],
                "",
            ]
        )

    issues = report_data.get("issues", [])
    lines.extend(["## 审查问题", f"共 {len(issues)} 项", ""])
    for issue in issues:
        lines.extend(
            [
                (
                    f"### [{issue.get('severity', 'unknown')}] "
                    f"{issue.get('issue_type', 'unknown')}"
                ),
                f"- 位置: {issue.get('location', 'unknown')}",
                f"- 描述: {issue.get('description', '')}",
                f"- 违反规则: {issue.get('violated_rule', '')}",
                "",
            ]
        )
    if not issues:
        lines.extend(["无问题。", ""])

    reminders = report_data.get("reminders", [])
    if reminders:
        lines.append("## 提醒")
        for reminder in reminders:
            lines.extend(
                [
                    (
                        f"- [{reminder.get('priority', 'medium')}] "
                        f"{reminder.get('family', '')}: "
                        f"{reminder.get('trigger_condition', '')}"
                    ),
                    f"  - window: {reminder.get('window', '')}",
                    f"  - escalation: {reminder.get('escalation_issue_type', '')}",
                    (
                        "  - early escalation: "
                        f"{reminder.get('early_escalation_condition', '')}"
                    ),
                    f"  - closure: {reminder.get('closure_condition', '')}",
                ]
            )
        lines.append("")

    if report_data.get("rewrite_applied"):
        lines.extend(
            [
                "## 修复记录",
                f"原始路由: {report_data.get('original_route', 'unknown')}",
                f"应用修复数: {len(report_data.get('applied_fixes', []))}",
                "",
            ]
        )

    gaps = report_data.get("confidence_gaps", [])
    if gaps:
        lines.extend(["## 置信缺口", *[f"- {gap}" for gap in gaps], ""])

    return "\n".join(lines)
