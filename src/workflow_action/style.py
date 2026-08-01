"""StyleUnit — 写作风格提炼与 lint 工作流.

StyleExtractUnit: 从小说章节采样提取质性风格（LLM，response-file 模式）。
StyleLintUnit: 纯代码对全文做 AI 味 lint，产出 ReviewIssue。
load_style_context: compose/extend 读取风格档案并渲染注入文本（支持风格库引用）。
style_library_dir: 风格库目录 novels/_style_library。
"""

import json
import os
from pathlib import Path

from src.boundary_control.style_metrics import analyze_style_metrics
from src.domain_layer.style_rules import (
    build_style_knowledge_context,
    get_ai_flavor_markers,
    get_tone_style_traits,
    list_available_tones,
)
from src.object_state.reviewissue import ReviewIssue
from src.object_state.styleprofile import (
    StyleProfile,
    StyleQuantitativeStats,
    StyleRisk,
)

# 风格库默认根目录（与 novel_cli 的 DEFAULT_NOVELS_ROOT 一致）
DEFAULT_NOVELS_ROOT = Path(__file__).resolve().parent.parent.parent / "novels"

# StyleExtractUnit 需要但不直接 import 的常量（供 parse 校验）
_REQUIRED_RESPONSE_FIELDS = (
    "tone_labels",
    "genre_guess",
    "narrative_pov",
    "pacing_description",
    "sentence_habits",
    "rhetorical_preferences",
    "show_dont_tell_notes",
    "closed_loop_objects",
    "chapter_end_hook_notes",
    "taboo_words",
    "style_references",
    "confidence_gaps",
)


class StyleExtractUnit:
    """从小说章节采样中提炼质性写作风格."""

    def build_prompt(
        self,
        samples_text: str,
        total_stats: dict,
        quantitative_context: str,
        style_knowledge_context: str = "",
        available_tones: list[str] | None = None,
    ) -> str:
        """生成风格提炼 prompt.

        Args:
            samples_text: 章节采样文本（首+中+末均匀采样）
            total_stats: get_total_stats 的输出（章节数/字数）
            quantitative_context: 量化分析渲染文本
            style_knowledge_context: tone/genre 风格知识（给 LLM 分类轴）
            available_tones: 可用调性列表（未知调性进 confidence_gaps）
        """
        tones = available_tones or list_available_tones()
        knowledge_section = ""
        if style_knowledge_context:
            knowledge_section = (
                f"\n\n【风格知识参考（分类轴）】\n{style_knowledge_context}\n"
                f"可用调性标签: {' / '.join(tones)}"
            )

        return f"""你是一位小说文风分析专家。请从以下章节采样中提炼这部作品的写作风格档案。

【输入文本（章节采样）】
{samples_text}

【全文统计】
- 总章节数: {total_stats.get('chapter_count', '?')}
- 总字数: {total_stats.get('total_chars', '?')}
- 平均每章字数: {total_stats.get('avg_chars_per_chapter', '?')}

【量化分析（纯代码，已算出）】
{quantitative_context}
{knowledge_section}

【提炼要求】
1. tone_labels 从可用调性标签中选择（可多选；若文本不属于任何标签，写 '未标注'）
2. sentence_habits 描述句式习惯，如"叙述默认 20-30 字长句，情绪爆点用独立短句"
3. show_dont_tell_notes 描述情绪如何呈现（身体反应/动作/意象），不是"他感到"
4. closed_loop_objects 列出在文本中开头出现、结局变化/回归的闭环物象
5. chapter_end_hook_notes 描述章末如何留钩子
6. taboo_words 列出应避免的用词（本文本刻意回避的套话）
7. style_references 命中风格知识表中的规则（如 tone_kz_01），未知的不要编造

【输出格式】
严格输出 JSON，不要 Markdown 代码块标记:
{{
  "tone_labels": ["克制"],
  "genre_guess": "古典仙侠",
  "narrative_pov": "第三人称有限",
  "pacing_description": "叙述默认长句，情绪爆点短句独立成段",
  "sentence_habits": ["句式习惯1"],
  "rhetorical_preferences": ["修辞偏好1"],
  "show_dont_tell_notes": ["情绪呈现手法1"],
  "closed_loop_objects": ["物象1"],
  "chapter_end_hook_notes": ["章末钩子手法1"],
  "taboo_words": ["禁忌词1"],
  "style_references": ["tone_kz_01"],
  "confidence_gaps": ["不确定的信息"]
}}"""

    def parse_response(self, response: str) -> dict:
        """解析 LLM 风格提炼响应，严格校验字段."""
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("Style extraction response must be a JSON object")

        missing = [field for field in _REQUIRED_RESPONSE_FIELDS if field not in data]
        if missing:
            raise ValueError(
                "Style extraction response missing required field(s): "
                + ", ".join(missing)
            )
        extra = sorted(set(data) - set(_REQUIRED_RESPONSE_FIELDS))
        if extra:
            raise ValueError(
                "Style extraction response has unexpected field(s): "
                + ", ".join(extra)
            )

        list_fields = (
            "tone_labels",
            "sentence_habits",
            "rhetorical_preferences",
            "show_dont_tell_notes",
            "closed_loop_objects",
            "chapter_end_hook_notes",
            "taboo_words",
            "style_references",
            "confidence_gaps",
        )
        for field in list_fields:
            value = data[field]
            if not isinstance(value, list):
                raise ValueError(
                    f"Style extraction response field {field} must be a list"
                )
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(
                    f"Style extraction response field {field} must be a list of strings"
                )
        for field in ("genre_guess", "narrative_pov", "pacing_description"):
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Style extraction response field {field} must be a non-empty string"
                )
        return data

    def merge(
        self,
        qualitative: dict,
        stats: StyleQuantitativeStats,
        risks: list[StyleRisk],
        source_text_ref: str,
        profile_id: str = "style_001",
    ) -> StyleProfile:
        """合并质性提炼 + 量化统计为 StyleProfile.

        未知 tone_label 移入 confidence_gaps（graceful degradation）。
        """
        known_tones = set(list_available_tones())
        confidence_gaps = list(qualitative.get("confidence_gaps", []))
        tone_labels = list(qualitative.get("tone_labels", []))
        for tone in tone_labels:
            if tone not in known_tones and tone != "未标注":
                confidence_gaps.append(f"未知调性标签: {tone}")
        tone_labels = [tone for tone in tone_labels if tone in known_tones or tone == "未标注"]

        return StyleProfile(
            profile_id=profile_id,
            source_text_ref=source_text_ref,
            tone_labels=tone_labels,
            genre_guess=qualitative.get("genre_guess"),
            narrative_pov=qualitative["narrative_pov"],
            pacing_description=qualitative["pacing_description"],
            sentence_habits=qualitative.get("sentence_habits", []),
            rhetorical_preferences=qualitative.get("rhetorical_preferences", []),
            show_dont_tell_notes=qualitative.get("show_dont_tell_notes", []),
            closed_loop_objects=qualitative.get("closed_loop_objects", []),
            chapter_end_hook_notes=qualitative.get("chapter_end_hook_notes", []),
            taboo_words=qualitative.get("taboo_words", []),
            style_references=qualitative.get("style_references", []),
            stats=stats,
            ai_flavor_risks=risks,
            confidence_gaps=confidence_gaps,
        )


class StyleLintUnit:
    """纯代码对全文做 AI 味 lint，产出 ReviewIssue."""

    def lint_stats(self, stats: StyleQuantitativeStats) -> list[StyleRisk]:
        """根据量化统计判断 AI 味风险."""
        risks: list[StyleRisk] = []
        markers = get_ai_flavor_markers()
        by_id = {marker["rule_id"]: marker for marker in markers}

        checks = [
            (
                "ai_weak_adverb_density",
                stats.weak_adverb_density_per_1000,
                "per_1000_chars",
            ),
            ("ai_metaphor_repeat", float(len(stats.metaphor_repeats)), "absolute"),
            (
                "ai_explanatory_voice",
                float(stats.explanatory_phrase_count),
                "count",
            ),
            (
                "ai_shell_not_a_but_b",
                float(stats.shell_counts.get("not_a_but_b", 0)),
                "count",
            ),
            ("ai_parallel_four", float(stats.shell_counts.get("parallel4", 0)), "count"),
            (
                "ai_emotion_announcement",
                stats.emotion_announcement_count / max(stats.total_chars, 1) * 1000,
                "per_1000_chars",
            ),
            (
                "ai_dialogue_tag_density",
                stats.dialogue_tag_density_per_1000,
                "per_1000_chars",
            ),
            ("ai_dash_colon_density", stats.dash_colon_density_per_1000, "per_1000_chars"),
            (
                "ai_connective_abuse",
                float(stats.connective_abuse_count),
                "count",
            ),
            (
                "ai_colon_enumeration",
                float(stats.colon_enumeration_count),
                "count",
            ),
        ]

        for rule_id, value, measure_unit in checks:
            marker = by_id.get(rule_id)
            if not marker:
                continue
            if value < marker["threshold"]:
                continue
            risks.append(
                StyleRisk(
                    rule_id=rule_id,
                    category="ai_flavor",
                    measure=marker["description"],
                    value=round(value, 2),
                    threshold=marker["threshold"],
                    severity=marker["severity"],  # type: ignore[arg-type]
                    description="；".join(marker["instructions"]),
                )
            )
        return risks

    def lint(self, text: str, location: str = "全文") -> list[ReviewIssue]:
        """对全文做 AI 味 lint，产出 ReviewIssue."""
        stats = analyze_style_metrics(text)
        risks = self.lint_stats(stats)
        issues: list[ReviewIssue] = []
        for risk in risks:
            issues.append(
                ReviewIssue(
                    issue_id=f"style_lint_{risk.rule_id}",
                    issue_type="generative_indicia",
                    severity=risk.severity,  # type: ignore[arg-type]
                    location=location,
                    scope_of_impact="表达层",
                    violated_rule=risk.measure,
                    description=(
                        f"{risk.measure}: {risk.value:.1f}"
                        f"（阈值{risk.threshold:.1f}）。建议: {risk.description}"
                    ),
                )
            )
        return issues

    def lint_taboo_words(
        self, text: str, taboo_words: list[str], location: str = "全文"
    ) -> list[ReviewIssue]:
        """按风格档案的禁忌词做 style_drift 检查.

        命中任意禁忌词即报一条 style_drift issue，并附出现次数。
        """
        if not taboo_words:
            return []
        issues: list[ReviewIssue] = []
        for word in taboo_words:
            if not word or not word.strip():
                continue
            count = text.count(word)
            if count <= 0:
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"style_drift_taboo_{word}",
                    issue_type="style_drift",
                    severity="low",
                    location=location,
                    scope_of_impact="表达层",
                    violated_rule=f"禁忌词: {word}",
                    description=(
                        f"风格档案禁忌词 '{word}' 在文本中出现 {count} 次。"
                        "作者自查清单要求回避此词，请替换为具体动作/身体反应。"
                    ),
                )
            )
        return issues


def style_library_dir(novels_root: Path | None = None) -> Path:
    """风格库目录: <novels_root>/_style_library.

    novels_root 未指定时用 NOVELS_ROOT 环境变量（与 novel_cli 一致），否则默认 <工程>/novels。
    """
    if novels_root is not None:
        root = Path(novels_root)
    else:
        root_env = os.environ.get("NOVELS_ROOT")
        root = Path(root_env).resolve() if root_env else DEFAULT_NOVELS_ROOT
    return root / "_style_library"


def style_library_profile_path(name: str, novels_root: Path | None = None) -> Path:
    """风格库档案路径: <novels_root>/_style_library/<name>.json."""
    if not name or name.strip() != name or "/" in name or "\\" in name:
        raise ValueError(f"invalid style library name: {name!r}")
    return style_library_dir(novels_root) / f"{name}.json"


def load_style_context(output_dir: Path, style_name: str | None = None) -> str:
    """读取风格档案并渲染注入文本.

    style_name 指定时读风格库 <novels_root>/_style_library/<name>.json；
    否则读规范位置 <output_dir>/style/style_profile.json。
    不存在返回 ""；存在但损坏则抛错（stale/corrupt 文件应暴露）。
    """
    if style_name:
        profile_path = style_library_profile_path(style_name)
    else:
        style_dir = Path(output_dir).parent / "style"
        profile_path = style_dir / "style_profile.json"
    if not profile_path.exists():
        return ""
    profile = StyleProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    return profile.to_prompt_context()
