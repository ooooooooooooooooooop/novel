"""ComplianceUnit — 内容合规模块工作流.

纯代码扫描，无 LLM、可离线（对齐 StyleLintUnit 先例）。两种模式：
- prose 模式：对输入 .txt 扫敏感词——命中词/分类/严重级/段落位置锚点/替换建议/封号风险分级
- object 模式：对 PlotUnit 字段做平台政策字段检查（弱但可用）

敏感词做成开关：--sensitive off 时跳过词库扫描（平台政策检查仍跑）。
本模块是风险降低不是保证：平台审核是黑箱，过检 ≠ 不封号。
"""

from pathlib import Path

from src.domain_layer.compliance_rules import (
    build_lexicon_from_categories,
    get_platform_policy,
)
from src.object_state.reviewissue import ReviewIssue


class ComplianceHit:
    """单一敏感词命中."""

    def __init__(
        self,
        *,
        word: str,
        category: str,
        severity: str,
        line_number: int,
        snippet: str,
        note: str,
    ) -> None:
        self.word = word
        self.category = category
        self.severity = severity
        self.line_number = line_number
        self.snippet = snippet
        self.note = note

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "category": self.category,
            "severity": self.severity,
            "line_number": self.line_number,
            "snippet": self.snippet,
            "note": self.note,
        }


class ComplianceReport:
    """合规扫描报告（顶层产物，持久化为 compliance_report.json）."""

    def __init__(
        self,
        *,
        source_text_ref: str,
        platform: str,
        sensitive_scan: bool,
        hits: list[ComplianceHit],
        platform_policy: dict,
        issues: list[ReviewIssue],
    ) -> None:
        self.source_text_ref = source_text_ref
        self.platform = platform
        self.sensitive_scan = sensitive_scan
        self.hits = hits
        self.platform_policy = platform_policy
        self.issues = issues

    def _severity_rank(self, severity: str) -> int:
        return {"block": 3, "high": 2, "medium": 1, "low": 0}.get(severity, 0)

    def max_severity(self) -> str:
        """整个报告的最大命中严重级."""
        if not self.hits:
            return "none"
        ranks = {"block": 3, "high": 2, "medium": 1, "low": 0}
        worst = max(self.hits, key=lambda hit: ranks.get(hit.severity, 0))
        return worst.severity

    def risk_level(self) -> str:
        """封号风险分级（供人工判断，非平台保证）."""
        worst = self.max_severity()
        if worst == "block":
            return "critical"
        if worst == "high":
            return "high"
        if worst == "medium":
            return "medium"
        if worst == "low":
            return "low"
        return "clean"

    def to_dict(self) -> dict:
        return {
            "source_text_ref": self.source_text_ref,
            "platform": self.platform,
            "sensitive_scan": self.sensitive_scan,
            "route": "pass",
            "risk_level": self.risk_level(),
            "hit_count": len(self.hits),
            "max_severity": self.max_severity(),
            "hits": [hit.to_dict() for hit in self.hits],
            "platform_policy": self.platform_policy,
            "issue_count": len(self.issues),
            "issues": [issue.model_dump(mode="json") for issue in self.issues],
        }


class ComplianceUnit:
    """合规扫描单元."""

    def scan_prose(
        self,
        text: str,
        *,
        platform: str,
        sensitive_on: bool = True,
        custom_entries: list | None = None,
        source_text_ref: str = "",
    ) -> ComplianceReport:
        """对正文扫敏感词 + 平台政策检查.

        sensitive_on=False 时跳过词库扫描（平台政策检查仍跑）。
        """
        hits: list[ComplianceHit] = []
        lines = text.splitlines()
        lexicon = (
            build_lexicon_from_categories(custom_entries=custom_entries)
            if sensitive_on
            else []
        )

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            for entry in lexicon:
                word = entry["word"]
                if word not in line:
                    continue
                # 同一行同一词只报一次
                if any(
                    hit.word == word and hit.line_number == line_number
                    for hit in hits
                ):
                    continue
                snippet = _snippet_around(line, word)
                hits.append(
                    ComplianceHit(
                        word=word,
                        category=entry["category"],
                        severity=entry["severity"],
                        line_number=line_number,
                        snippet=snippet,
                        note=entry["note"],
                    )
                )

        policy = get_platform_policy(platform)
        issues = self._platform_policy_issues(text, policy)
        report = ComplianceReport(
            source_text_ref=source_text_ref,
            platform=platform,
            sensitive_scan=sensitive_on,
            hits=hits,
            platform_policy=policy,
            issues=issues,
        )
        return report

    def scan_objects(
        self,
        *,
        genre: str | None = None,
        hook: str | None = None,
        conflict: str | None = None,
        platform: str = "通用",
    ) -> list[ReviewIssue]:
        """对 PlotUnit 字段做平台政策字段检查（弱但可用）.

        无正文场景降级到此模式，不至于空转。
        """
        issues: list[ReviewIssue] = []
        policy = get_platform_policy(platform)
        redline = policy["redline_categories"]

        if genre and "涉政" in redline and _contains_redline_theme(genre):
            issues.append(
                ReviewIssue(
                    issue_id="compliance_platform_genre",
                    issue_type="world_violation",
                    severity="warning",
                    location="PlotUnit.genre",
                    scope_of_impact="平台合规",
                    violated_rule="平台红线题材",
                    description=(
                        f"PlotUnit.genre 命中平台红线主题: '{genre}'。"
                        f"目标平台 {platform} 红线: {', '.join(redline)}。"
                    ),
                )
            )
        if conflict and _contains_redline_theme(conflict):
            issues.append(
                ReviewIssue(
                    issue_id="compliance_platform_conflict",
                    issue_type="world_violation",
                    severity="warning",
                    location="PlotUnit.conflict",
                    scope_of_impact="平台合规",
                    violated_rule="平台红线题材",
                    description=(
                        f"PlotUnit.conflict 可能涉及平台红线: '{conflict}'。"
                        "请人工复核。"
                    ),
                )
            )
        return issues

    def _platform_policy_issues(self, text: str, policy: dict) -> list[ReviewIssue]:
        """平台政策检查：AI 直出禁令 + 章节字数目标."""
        issues: list[ReviewIssue] = []
        ai_rule = policy.get("ai_direct_output", "")
        if ai_rule == "禁止":
            issues.append(
                ReviewIssue(
                    issue_id="compliance_ai_direct_output",
                    issue_type="world_violation",
                    severity="warning",
                    location="全文",
                    scope_of_impact="平台合规",
                    violated_rule="平台禁止 AI 直出",
                    description=(
                        "目标平台禁止 AI 直出内容。本系统产出 PlotUnit 对象层"
                        "（非正文），正文由人工书写；若正文为 AI 直出需人工润色降痕。"
                    ),
                )
            )
        return issues


def _contains_redline_theme(text: str) -> bool:
    """启发式判断文本是否涉及红线主题（涉黄/涉政/涉黑/涉毒关键词）."""
    redline_keywords = [
        "杀人",
        "强暴",
        "毒品",
        "赌博",
        "赌场",
        "黑帮",
        "政变",
        "造反",
        "色情",
        "卖淫",
        "恐怖袭击",
    ]
    return any(keyword in text for keyword in redline_keywords)


def _snippet_around(line: str, word: str, radius: int = 8) -> str:
    """提取命中词所在行的上下文片段（供人工复核）."""
    index = line.find(word)
    if index < 0:
        return line
    start = max(0, index - radius)
    end = min(len(line), index + len(word) + radius)
    return line[start:end]
