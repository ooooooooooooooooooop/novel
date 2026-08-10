"""Q1 Phase 4 — SerialReaderReport 对象 + SerialReaderUnit 单测.

验证窗口读者审查的对象模型与工作流：
- SerialReaderReport schema（window 1/3/5、chapter_refs、维度合法性）
- SerialReaderUnit build_prompt / parse_response / merge
- 确定性预分析（开头签名 / 顿悟核心 / 元文本 / 重复核心统计）
"""

import pytest

from src.object_state.serialreader import (
    SERIAL_READER_DIMENSIONS,
    SerialReaderReport,
)
from src.workflow_action.serial_reader import (
    SerialReaderUnit,
    _bounded_chapter,
    analyze_window_proxy,
)


def _valid_response() -> dict:
    return {
        "findings": [
            {
                "dimension": "repeated_insight",
                "grade": "weak",
                "severity": "objective",
                "issue_type": "redundancy",
                "evidence": "三章同样顿悟",
                "location": "第3章 中段",
                "diagnosis": "同一顿悟反复完成",
                "fix_direction": "改为行为落地",
            },
            {
                "dimension": "repeated_ending",
                "grade": "needs_work",
                "severity": "aesthetic",
                "issue_type": "weak_progression",
                "evidence": "三章都以决定收尾",
                "location": "第3章 章末",
                "diagnosis": "结尾结构单一",
                "fix_direction": "变换收尾方式",
            },
        ],
        "overall": "weak",
    }


def _three_chapters() -> list[str]:
    return [
        "第一章 他推开门，决定去追。结果发现了线索。他终于明白真相就在眼前。",
        "第二章 他又推开门，决定去追。结果还是同一处。他终于明白真相就在眼前。",
        "第三章 他再次推开门，决定去追。结果依旧。他终于明白真相就在眼前。",
    ]


class TestSerialReaderReportSchema:
    def test_valid_report(self):
        unit = SerialReaderUnit()
        report = unit.merge(
            _valid_response(),
            window=3,
            review_target="chapter_3",
            chapter_refs=["chapter_1", "chapter_2", "chapter_3"],
        )
        assert report.schema_version == 1
        assert report.window == 3
        assert report.route == "none"
        assert len(report.findings) == 2
        assert report.overall == "weak"

    def test_window_must_be_1_3_5(self):
        with pytest.raises(Exception):
            SerialReaderReport(
                window=2,
                review_target="chapter_3",
                chapter_refs=["chapter_1", "chapter_2"],
                findings=[],
                overall="good",
            )

    def test_window_gt1_requires_two_refs(self):
        with pytest.raises(Exception):
            SerialReaderReport(
                window=3,
                review_target="chapter_3",
                chapter_refs=["chapter_3"],
                findings=[],
                overall="good",
            )

    def test_dimensions_all_valid(self):
        assert len(SERIAL_READER_DIMENSIONS) == 12
        dims = {d for d, _ in SERIAL_READER_DIMENSIONS}
        assert {
            "reask_resolved",
            "reset_without_event",
            "scene_replay",
            "process_text",
            "mechanical_recap",
            "repeated_insight",
            "psych_summary_only",
            "repeated_ending",
            "expectation_stall",
            "narrowing_methods",
            "pleasure_dilution",
            "contract_drift",
        } == dims


class TestSerialReaderUnit:
    def test_build_prompt_includes_chapters_and_guidance(self):
        unit = SerialReaderUnit()
        chapters = _three_chapters()
        prompt = unit.build_prompt(
            chapters,
            window=3,
            chapter_refs=["chapter_1", "chapter_2", "chapter_3"],
            review_target="chapter_3",
        )
        assert "chapter_1" in prompt and "chapter_3" in prompt
        assert "reask_resolved" in prompt and "contract_drift" in prompt
        assert "【读者契约（读者为什么选择这本书）】" not in prompt  # 无契约上下文不注入
        assert "【读者预期台账】" not in prompt

    def test_build_prompt_injects_contract_and_expectations(self):
        unit = SerialReaderUnit()
        prompt = unit.build_prompt(
            _three_chapters(),
            window=3,
            chapter_refs=["chapter_1", "chapter_2", "chapter_3"],
            review_target="chapter_3",
            reader_contract_context="【读者契约】核心快感=真相推进",
            reader_expectation_context="【读者预期台账】等待主线悬念",
        )
        assert "【读者契约】" in prompt
        assert "【读者预期台账】" in prompt

    def test_build_prompt_rejects_window_mismatch(self):
        unit = SerialReaderUnit()
        with pytest.raises(ValueError):
            unit.build_prompt(
                ["a", "b"],
                window=3,
                chapter_refs=["chapter_1", "chapter_2"],
                review_target="chapter_2",
            )

    def test_parse_response_valid(self):
        unit = SerialReaderUnit()
        parsed = unit.parse_response(
            '{"findings": [], "overall": "good"}'
        )
        assert parsed["overall"] == "good"

    def test_parse_response_rejects_bad_dimension(self):
        unit = SerialReaderUnit()
        with pytest.raises(ValueError):
            unit.parse_response(
                '{"findings": [{"dimension": "nope", "grade": "weak", '
                '"severity": "objective", "issue_type": "redundancy", '
                '"evidence": "x", "location": "y", "diagnosis": "z"}], '
                '"overall": "weak"}'
            )

    def test_parse_response_rejects_bad_grade(self):
        unit = SerialReaderUnit()
        with pytest.raises(ValueError):
            unit.parse_response(
                '{"findings": [{"dimension": "process_text", "grade": "good", '
                '"severity": "objective", "issue_type": "redundancy", '
                '"evidence": "x", "location": "y", "diagnosis": "z"}], '
                '"overall": "weak"}'
            )

    def test_merge_round_trip(self):
        unit = SerialReaderUnit()
        report = unit.merge(
            _valid_response(),
            window=3,
            review_target="chapter_3",
            chapter_refs=["chapter_1", "chapter_2", "chapter_3"],
        )
        # 序列化往返
        data = report.model_dump(mode="json")
        restored = SerialReaderReport.model_validate(data)
        assert restored.findings[0].issue_type == "redundancy"
        assert restored.findings[1].severity == "aesthetic"

    def test_overall_from_findings(self):
        unit = SerialReaderUnit()
        assert unit.overall_from_findings([]) == "good"
        report = unit.merge(
            _valid_response(), window=3, review_target="c3",
            chapter_refs=["c1", "c2", "c3"],
        )
        assert unit.overall_from_findings(report.findings) == "weak"
        report2 = unit.merge(
            {
                "findings": [
                    {
                        "dimension": "repeated_ending",
                        "grade": "needs_work",
                        "severity": "aesthetic",
                        "issue_type": "weak_progression",
                        "evidence": "e",
                        "location": "l",
                        "diagnosis": "d",
                    }
                ],
                "overall": "needs_work",
            },
            window=3, review_target="c3", chapter_refs=["c1", "c2", "c3"],
        )
        assert unit.overall_from_findings(report2.findings) == "needs_work"


class TestWindowProxy:
    def test_analyze_window_proxy_reports_openings_and_repeats(self):
        proxy = analyze_window_proxy(_three_chapters())
        assert "开头签名" in proxy
        assert "跨章重复顿悟核心" in proxy
        # 三章同样的顿悟核心应被统计到重复
        assert "（无）" not in proxy.split("跨章重复顿悟核心")[1].splitlines()[0]

    def test_analyze_window_proxy_meta_text_hits(self):
        proxy = analyze_window_proxy(["上一章末她还在码头。本章她回到家。"])
        assert "元文本" in proxy
        assert "上一章" in proxy

    def test_bounded_chapter_preserves_head_and_tail(self):
        text = "开头" + "中" * 3000 + "结尾"
        bounded = _bounded_chapter(text)
        assert bounded.startswith("开头")
        assert bounded.endswith("结尾")
        assert "中段省略" in bounded
        assert len(bounded) < len(text)
