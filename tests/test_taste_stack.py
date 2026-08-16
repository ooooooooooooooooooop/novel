"""P4 Taste Stack 评价体系与统一质量报告测试.

覆盖：
1. 5 层评价体系数据模型约束（Layer 1 硬门禁、Layer 2 专门轴、Layer 3 Blind Eval、Layer 4 PASS Audit、Layer 5 人类盲评）。
2. G7 退役声明与历史记录不变性（G7RetirementNotice）。
3. 统一质量报告渲染（Markdown / JSON），严格杜绝单一加权标量总分。
4. 聚合器 (build_unified_quality_report) 行为：工作区台账解析、落盘、与零真人数据时诚实输出 not_run。
"""

import json
from pathlib import Path

import pytest

from src.object_state.taste_stack import (
    G7RetirementNotice,
    Layer1HardGatesSummary,
    Layer2SpecializedAxesSummary,
    Layer3BlindEvalSummary,
    Layer4PassAuditSummary,
    Layer5HumanBlindEvalSummary,
    StyleDriftSummary,
    UnifiedQualityReport,
)
from src.workflow_action.taste_stack import build_unified_quality_report


class TestTasteStackModels:
    def test_layer1_hard_gates_model(self):
        layer1 = Layer1HardGatesSummary(
            status="passed",
            checked_gates=["fact_consistency", "causal_defense_5_detectors"],
            blocking_issues_count=0,
            evidence_count=2,
        )
        assert layer1.status == "passed"
        assert layer1.blocking_issues_count == 0
        assert "causal_defense_5_detectors" in layer1.checked_gates

    def test_layer2_specialized_axes_model(self):
        layer2 = Layer2SpecializedAxesSummary(
            status="completed",
            evaluated_axes={
                "character_agency": {"verdict": "satisfied"},
                "emotional_landing": {"verdict": "satisfied"},
            },
            unreviewable_axes=["longterm_world_reputation"],
            notes=["证据不足的轴诚实标记为 unreviewable"],
        )
        assert layer2.status == "completed"
        assert "unreviewable" in layer2.notes[0]
        assert "longterm_world_reputation" in layer2.unreviewable_axes

    def test_layer3_blind_eval_model(self):
        layer3 = Layer3BlindEvalSummary(
            status="completed",
            total_pairs_evaluated=20,
            better_count=16,
            worse_count=2,
            no_difference_count=2,
            net_improvement_rate=0.7,
            wilson_ci_95=(0.48, 0.85),
        )
        assert layer3.status == "completed"
        assert layer3.better_count == 16
        assert layer3.wilson_ci_95[0] < layer3.wilson_ci_95[1]

    def test_layer4_pass_audit_model(self):
        layer4 = Layer4PassAuditSummary(
            status="completed",
            total_pass_chapters_audited=10,
            clean_chapters_count=9,
            clean_rate=0.9,
            actionable_miss_rate=0.1,
            blocking_miss_rate=0.0,
            findings_by_type={"minor_scene_vagueness": 1},
        )
        assert layer4.clean_rate == 0.9
        assert layer4.blocking_miss_rate == 0.0

    def test_layer5_human_blind_eval_honest_not_run(self):
        layer5 = Layer5HumanBlindEvalSummary(status="not_run")
        assert layer5.status == "not_run"
        assert "暂无真人连续阅读实验数据" in layer5.notes

    def test_g7_retirement_notice(self):
        notice = G7RetirementNotice()
        assert notice.status == "decommissioned_research_only"
        assert "不再作为系统总发布门" in notice.notice
        assert notice.historical_record_intact is True


class TestUnifiedQualityReport:
    def test_report_structure_and_no_single_score(self):
        report = UnifiedQualityReport(
            report_id="qr_test_01",
            novel_name="测试小说",
            layer1_hard_gates=Layer1HardGatesSummary(status="passed"),
            layer2_specialized_axes=Layer2SpecializedAxesSummary(status="completed"),
            layer3_blind_eval=Layer3BlindEvalSummary(status="not_run"),
            layer4_pass_audit=Layer4PassAuditSummary(status="not_run"),
            layer5_human_blind_eval=Layer5HumanBlindEvalSummary(status="not_run"),
            style_drift=StyleDriftSummary(status="not_run"),
            g7_status=G7RetirementNotice(),
            narrative_evaluation_summary="定性诊断：硬门禁全过，未出现战力透支，真人验证待接入。",
        )

        md = report.render_markdown()
        assert "# 统一叙事质量报告: 测试小说" in md
        assert "第 1 层：确定性硬门禁" in md
        assert "G7 状态与退役说明" in md
        assert "decommissioned_research_only" in md
        assert "杜绝虚假确定性，严禁输出单一加权「大神分」" in md

        data = report.model_dump(mode="json")
        assert "score" not in data
        assert "overall_score" not in data
        assert "mastery_score" not in data

    def test_build_unified_quality_report_with_ledger(self, tmp_path):
        # 准备模拟 A/B 台账
        ab_ledger = [
            {"pair_id": "p1", "winner": "candidate_a"},
            {"pair_id": "p2", "winner": "candidate_a"},
        ]
        (tmp_path / "prose_revision_ledger.json").write_text(
            json.dumps(ab_ledger), encoding="utf-8"
        )

        report = build_unified_quality_report("万物伏藏", output_dir=tmp_path)

        assert report.novel_name == "万物伏藏"
        assert report.layer1_hard_gates.status == "passed"
        assert report.layer3_blind_eval.status == "completed"
        assert report.layer3_blind_eval.total_pairs_evaluated == 2
        assert report.layer5_human_blind_eval.status == "not_run"
        assert (tmp_path / "unified_quality_report.json").exists()
        assert (tmp_path / "unified_quality_report.md").exists()
