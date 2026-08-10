"""SerialReaderUnit — 连续章/窗口读者审查工作流.

Q1 Phase 4（单章与滑动窗口读者门禁）的窗口层单元。从连续 N 章正文评估
相邻章/窗口读者质量，产出 SerialReaderReport（route=none，不阻断）。

流程（对齐 ReaderExperienceUnit 的 staged 模式）：
1. 确定性预分析（纯代码，复用 prose_evidence/prose_reconcile 的
   开头签名 / 顿悟核心 / 元文本检测 / 结尾预览）——给 LLM 辅助证据
2. LLM 质性分级标注（response-file [WAITING] 循环）——相邻章 + 窗口维度
   各给 good/needs_work/weak；needs_work/weak 维才入 findings
3. 合并 → SerialReaderReport（window 1/3/5）

与 ReaderExperienceUnit（单章 7 维）分工：本单元判断「连续几章是否连续可信、
是否在重复」，是窗口层读者质量门禁的输入。
"""

import json
from pathlib import Path
from typing import Optional

from src.domain_layer.serial_reader_rules import (
    build_serial_reader_dimension_guidance,
)
from src.object_state.serialreader import (
    SERIAL_READER_DIMENSIONS,
    SerialReaderFinding,
    SerialReaderReport,
)
from src.workflow_action.prose_evidence import (
    extract_prose_evidence,
    opening_signature,
)
from src.workflow_action.prose_reconcile import _conclusion_core, conclusion_sentences

# 每章正文注入上限：窗口最大 5 章，单章超长时只保留头尾（开头/结尾是
# 相邻章与结尾结构判断的关键），中段省略防 prompt 膨胀。
_CHAPTER_PROMPT_CHARS = 2000
_HEAD_CHARS = 1000
_TAIL_CHARS = 800


def _bounded_chapter(text: str, max_chars: int = _CHAPTER_PROMPT_CHARS) -> str:
    """截断单章正文：超长保留头尾，中间标省略。"""
    if len(text) <= max_chars:
        return text
    head = text[:_HEAD_CHARS]
    tail = text[-_TAIL_CHARS:]
    return f"{head}\n……[中段省略 {len(text) - _HEAD_CHARS - _TAIL_CHARS} 字符]……\n{tail}"


# --------------------------------------------------------------------------
# 确定性预分析（纯代码，给 LLM 的辅助证据）
# --------------------------------------------------------------------------


def analyze_window_proxy(chapters: list[str]) -> str:
    """逐章确定性预分析：开头签名 / 顿悟核心 / 元文本命中 / 结尾预览.

    供 LLM 作为辅助证据（诚实标注为代理，不替代正文阅读）。
    """
    lines: list[str] = []
    all_cores: list[str] = []
    for i, ch in enumerate(chapters):
        idx = i + 1
        sig = opening_signature(ch)
        cores = [_conclusion_core(c) for c in conclusion_sentences(ch)]
        all_cores.extend(cores)
        meta = [
            it.evidence
            for it in extract_prose_evidence(ch).items
            if it.kind == "meta_text"
        ]
        ending = "".join(ch.split())[-40:] or ""
        lines.append(f"- 第{idx}章: 开头签名={sig[:16] or '（无）'}"
                     f" | 顿悟核心={cores[:2] or '（无）'}"
                     f" | 元文本={meta or '（无）'}"
                     f" | 结尾预览={ending}...")
    # 跨章重复顿悟核心统计
    if all_cores:
        from collections import Counter

        dup = {c: n for c, n in Counter(all_cores).items() if n >= 2}
        lines.append(f"- 跨章重复顿悟核心: {dup or '（无）'}")
    return "\n".join(lines)


class SerialReaderUnit:
    """连续章/窗口读者审查：连续正文 → 相邻章 + 窗口维度分级标注."""

    def build_prompt(
        self,
        chapters: list[str],
        *,
        window: int,
        chapter_refs: list[str],
        review_target: str,
        reader_contract_context: str = "",
        reader_expectation_context: str = "",
    ) -> str:
        """生成连续阅读审查 prompt.

        Args:
            chapters: 窗口内连续章正文（从旧到新，长度 == window）。
            window: 窗口大小（1/3/5）。
            chapter_refs: 窗口内章节标识（如 chapter_24/chapter_25/chapter_26）。
            review_target: 审查目标（最后章节标识）。
            reader_contract_context: ReaderContract 上下文（可选）。
            reader_expectation_context: ReaderExpectation 台账（可选）。
        """
        if len(chapters) != window:
            raise ValueError(
                f"chapters length ({len(chapters)}) must equal window ({window})"
            )
        proxy = analyze_window_proxy(chapters)

        chapter_blocks = []
        for ref, ch in zip(chapter_refs, chapters):
            chapter_blocks.append(f"## {ref}\n{_bounded_chapter(ch)}")

        sections = [
            "你是一位小说连续阅读审查专家。请对以下连续章节做相邻章/窗口读者审查：",
            "判断连续几章是否连续可信、是否在重复、阅读快感是否在衰减。",
            "",
            f"【审查窗口】window={window}（{' → '.join(chapter_refs)}，审查目标 {review_target}）",
            "",
            "【连续章正文】",
            "\n\n".join(chapter_blocks),
            "",
            "【确定性预分析（纯代码，仅供辅助证据，需结合正文阅读确认）】",
            proxy,
        ]
        if reader_contract_context:
            sections += ["", "【读者契约（读者为什么选择这本书）】", reader_contract_context]
        if reader_expectation_context:
            sections += ["", "【读者预期台账（读者正在等什么）】", reader_expectation_context]
        sections += [
            "",
            "【相邻章 + 窗口判定标准】",
            build_serial_reader_dimension_guidance(),
            "",
            "【分级标注要求】",
            "1. 对 12 维各给 good / needs_work / weak 分级（依据上面的判定标准）",
            "2. 只有 needs_work / weak 的维度才写入 findings；good 维不写入",
            "3. 每个 finding 标注:",
            "   - grade: needs_work / weak",
            "   - severity: objective=客观连续性/生成痕迹硬错误（读者能一眼看出的），"
            "aesthetic=审美/节奏分歧（可修或交人工）",
            "   - issue_type: 映射到现有失败类型之一 "
            "(fact_conflict/character_distortion/world_violation/weak_progression/"
            "promise_loss/style_drift/generative_indicia/missing_consequence/relationship_jump/"
            "motivation_gap/information_leak/timeline_error/abrupt_payoff/redundancy/"
            "duplication_of_threads)",
            "4. 每维附证据锚点（引正文具体内容）+ 一句诊断 + 改法方向",
            "5. 诚实分级：不要因为单章文笔不错就给窗口全 good，逐维独立判断",
            "6. overall = 窗口最差档（有 objective 硬错误至少 needs_work；"
            "多个 weak 或有客观硬错误则 weak）",
            "",
            "【输出格式】严格输出 JSON，不要 Markdown 代码块标记:",
            "{",
            '  "findings": [',
            "    {",
            '      "dimension": "reset_without_event",',
            '      "grade": "weak",',
            '      "severity": "objective",',
            '      "issue_type": "fact_conflict",',
            '      "evidence": "第2章『他早已找到的人，又不见了』",',
            '      "location": "第2章 中段",',
            '      "diagnosis": "上一章已找到，本章无事件重置回失踪",',
            '      "fix_direction": "补事件或改为延续状态"',
            "    }",
            "  ],",
            '  "overall": "weak"',
            "}",
        ]
        return "\n".join(sections)

    def parse_response(self, response: str) -> dict:
        """解析 LLM 分级标注响应，严格校验字段."""
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("Serial reader response must be a JSON object")
        required = {"findings", "overall"}
        missing = required - set(data)
        if missing:
            raise ValueError(
                "Serial reader response missing required field(s): "
                + ", ".join(sorted(missing))
            )
        extra = sorted(set(data) - required)
        if extra:
            raise ValueError(
                "Serial reader response has unexpected field(s): "
                + ", ".join(extra)
            )
        if not isinstance(data["findings"], list):
            raise ValueError(
                "Serial reader response field findings must be a list"
            )
        if data["overall"] not in ("good", "needs_work", "weak"):
            raise ValueError(
                "Serial reader response field overall must be one of "
                "good/needs_work/weak"
            )
        valid_dims = {dim for dim, _ in SERIAL_READER_DIMENSIONS}
        for item in data["findings"]:
            if not isinstance(item, dict):
                raise ValueError("each finding must be a JSON object")
            missing_item = {
                "dimension",
                "grade",
                "severity",
                "issue_type",
                "evidence",
                "location",
                "diagnosis",
            } - set(item)
            if missing_item:
                raise ValueError(
                    "finding missing required field(s): "
                    + ", ".join(sorted(missing_item))
                )
            if item["dimension"] not in valid_dims:
                raise ValueError(
                    f"finding dimension '{item['dimension']}' not in "
                    f"{sorted(valid_dims)}"
                )
            if item["grade"] not in ("needs_work", "weak"):
                raise ValueError(
                    f"finding grade must be needs_work/weak, got '{item['grade']}'"
                )
            if item["severity"] not in ("objective", "aesthetic"):
                raise ValueError(
                    f"finding severity must be objective/aesthetic, "
                    f"got '{item['severity']}'"
                )
        return data

    def merge(
        self,
        qualitative: dict,
        *,
        window: int,
        review_target: str,
        chapter_refs: list[str],
    ) -> SerialReaderReport:
        """合并 LLM 分级标注为 SerialReaderReport."""
        findings = [
            SerialReaderFinding(
                finding_id=f"ser_{window}_{item['dimension']}",
                dimension=item["dimension"],
                grade=item["grade"],
                severity=item["severity"],
                issue_type=item["issue_type"],
                evidence=item["evidence"],
                location=item.get("location", ""),
                diagnosis=item["diagnosis"],
                fix_direction=item.get("fix_direction", ""),
            )
            for item in qualitative["findings"]
        ]
        return SerialReaderReport(
            schema_version=1,
            window=window,
            review_target=review_target,
            chapter_refs=chapter_refs,
            findings=findings,
            overall=qualitative["overall"],
            route="none",
        )

    @staticmethod
    def overall_from_findings(findings: list[SerialReaderFinding]) -> str:
        """从 findings 计算 overall（确定性兜底：有 objective 硬错误或任一 weak → weak）.

        纯代码兜底：LLM 未给 overall 时的确定性回退（正常流程由 LLM 给出）。
        """
        if not findings:
            return "good"
        if any(f.grade == "weak" for f in findings) or any(
            f.severity == "objective" for f in findings
        ):
            return "weak"
        return "needs_work"


# 供 CLI/flow 复用的加载辅助
def load_serial_report(output_dir: Path) -> Optional[SerialReaderReport]:
    """读取 output/reader_experience/serial_reader_report.json；不存在/非法返回 None."""
    path = output_dir / "serial_reader_report.json"
    if not path.exists():
        return None
    try:
        return SerialReaderReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return None
