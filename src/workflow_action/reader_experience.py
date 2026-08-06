"""ReaderExperienceUnit — 读者体验审查工作流.

从正文章节评估读者体验质量，产出分级标注报告（docs/03_rules/10_reader_experience_rules.md）。

流程：
1. 量化代理分析（纯代码，复用 analyze_style_metrics）——给 LLM 辅助证据
2. LLM 质性分级标注（response-file [WAITING] 循环）——7 维各给 good/needs_work/weak
3. 合并 → reader_report.json（route=none，不阻断）

与 ReviewUnit（核心1 一致性）并行：ReviewUnit 判断「故事对不对」，本单元判断
「好不好看」。产物 ReaderExperienceReport 与 ReviewIssue 分离，各自独立验证。

对齐 style_short_form 的 [WAITING] 循环模式：缺失 response 时提示 [WAITING] 并正常退出，
重跑同一命令继续。
"""

import json
from pathlib import Path

from src.boundary_control.style_metrics import analyze_style_metrics
from src.domain_layer.reader_experience_rules import (
    READER_DIMENSION_RULES,
    build_reader_dimension_guidance,
    build_reader_quantitative_guidance,
)
from src.object_state.readerreport import (
    READER_DIMENSIONS,
    READER_GRADES,
    ReaderDimension,
    ReaderExperienceReport,
)


class ReaderExperienceUnit:
    """读者体验审查：正文 → 7 维分级标注."""

    def build_prompt(
        self,
        prose_text: str,
        chapter_id: str,
        style_context: str = "",
        plotunit_context: str = "",
        workspec_context: str = "",
    ) -> str:
        """生成读者体验审查 prompt.

        Args:
            prose_text: 章节正文全文
            chapter_id: 章节标识（如 chapter_1）
            style_context: StyleProfile 画像（可选，辅助判断情绪落地/场景现场感）
            plotunit_context: 该章 PlotUnit 画像（可选，对照计划 vs 正文兑现）
            workspec_context: WorkSpec 约束（可选）
        """
        quantitative = analyze_style_metrics(prose_text)
        stats_lines = [
            f"- 总字数: {quantitative.total_chars} | 句子数: {quantitative.sentence_count}",
            f"- 平均句长: {quantitative.avg_sentence_len} 字符 | "
            f"短句占比: {quantitative.short_sentence_ratio:.2f} | "
            f"长句占比: {quantitative.long_sentence_ratio:.2f}",
            f"- 对话占比: {quantitative.dialogue_ratio:.2f}",
            f"- 弱化副词密度: {quantitative.weak_adverb_density_per_1000:.2f}/千字",
            f"- 景物句占比: {quantitative.scenery_sentence_ratio:.2f} | "
            f"感官动词密度: {quantitative.sensory_density_per_1000:.2f}/千字",
            f"- 解释腔: {quantitative.explanatory_phrase_count} | "
            f"情绪宣布词: {quantitative.emotion_announcement_count}",
            f"- 对话标签密度: {quantitative.dialogue_tag_density_per_1000:.2f}/千字 | "
            f"修饰词负载: {quantitative.modifier_load_density:.2f}/千字",
            f"- 心理动词密度: {quantitative.psych_verb_density_per_1000:.2f}/千字 | "
            f"动作动词密度: {quantitative.action_verb_density_per_1000:.2f}/千字",
        ]

        sections = [
            "你是一位小说读者体验审查专家。请对以下章节正文做读者体验分级标注。",
            "",
            f"【审查章节】{chapter_id}",
            "",
            "【正文全文】",
            prose_text,
            "",
            "【量化代理分析（纯代码，辅助证据）】",
            "\n".join(stats_lines),
            "",
            build_reader_quantitative_guidance(),
        ]

        if workspec_context:
            sections += ["", "【作品约束】", workspec_context]
        if style_context:
            sections += ["", "【写作风格画像】", style_context]
        if plotunit_context:
            sections += ["", "【本章 PlotUnit（计划，对照正文兑现）】", plotunit_context]

        sections += [
            "",
            "【七维判定标准】",
            build_reader_dimension_guidance(),
            "",
            "【分级标注要求】",
            "1. 对 7 个维度各给出 good / needs_work / weak 分级",
            "2. 每维附位置锚点（如 第1-2段/改写完成段）+ 一句诊断 + 改法方向",
            "3. 诊断要引用正文具体内容，不要空泛；改法方向给出可操作建议",
            "4. overall = 7 维中最差档；若最差档有多个，取钩子（hook）优先",
            "5. 诚实分级：不要因为文笔整体不错就给全部 good，逐维独立判断",
            "",
            "【输出格式】严格输出 JSON，不要 Markdown 代码块标记:",
            "{",
            '  "dimensions": [',
            "    {",
            '      "dimension": "open",',
            '      "name": "开头是否拖沓",',
            '      "grade": "good",',
            '      "anchor": "第1-2段",',
            '      "diagnosis": "前三段即进入事件（碑面晃动），背景穿插自然",',
            '      "fix_direction": ""',
            "    }",
            "  ],",
            '  "overall": "needs_work"',
            "}",
        ]
        return "\n".join(sections)

    def parse_response(self, response: str) -> dict:
        """解析 LLM 分级标注响应，严格校验字段."""
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("Reader experience response must be a JSON object")
        required = {"dimensions", "overall"}
        missing = required - set(data)
        if missing:
            raise ValueError(
                "Reader experience response missing required field(s): "
                + ", ".join(sorted(missing))
            )
        extra = sorted(set(data) - required)
        if extra:
            raise ValueError(
                "Reader experience response has unexpected field(s): "
                + ", ".join(extra)
            )
        if not isinstance(data["dimensions"], list):
            raise ValueError("Reader experience response field dimensions must be a list")
        if data["overall"] not in READER_GRADES:
            raise ValueError(
                f"Reader experience response field overall must be one of {READER_GRADES}"
            )
        return data

    def merge(
        self,
        qualitative: dict,
        review_target: str,
        chapter_id: str | None = None,
    ) -> ReaderExperienceReport:
        """合并 LLM 分级标注为 ReaderExperienceReport.

        校验 7 维齐全、每维字段合法（缺失维度报错——7 维是完整契约）。
        """
        dims: list[ReaderDimension] = []
        for item in qualitative["dimensions"]:
            dims.append(ReaderDimension(**item))
        return ReaderExperienceReport(
            schema_version=1,
            review_target=review_target,
            chapter_id=chapter_id,
            dimensions=dims,
            overall=qualitative["overall"],
            route="none",
        )

    @staticmethod
    def _overall_from_dimensions(dimensions: list[ReaderDimension]) -> str:
        """从 7 维档位计算 overall（取最差；钩子优先作 tie-break）.

        纯代码兜底：LLM 未给 overall 时的确定性回退（正常流程由 LLM 给出）。
        """
        order = {"good": 0, "needs_work": 1, "weak": 2}
        worst = max(order[d.grade] for d in dimensions)
        # tie-break：钩子权重最高——若存在比 worst 更差的钩子档，提升到钩子档
        hook_grade = next(
            (d.grade for d in dimensions if d.dimension == "hook"), None
        )
        if hook_grade is not None and order[hook_grade] > worst:
            worst = order[hook_grade]
        return {0: "good", 1: "needs_work", 2: "weak"}[worst]
