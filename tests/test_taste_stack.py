"""P4 Taste Stack 评价体系与统一质量报告测试 (R1 整改).

覆盖：
1. 5 层评价体系数据模型约束。
2. G7 退役声明与历史记录不变性（G7RetirementNotice）。
3. 统一质量报告渲染（Markdown / JSON），严格杜绝单一加权标量总分。
4. 空工作区：五层全部 not_run，无任何 passed/completed/satisfied。
5. 只有 Revision Ledger 时：Blind Eval 仍为 not_run。
6. 真实 Blind Eval：better/worse/no_difference 计数与 Wilson CI 真实计算。
7. 损坏 JSON：invalid_evidence，strict 模式显式报错。
8. Reader Gate block -> blocked；Reader Gate pass -> passed。
9. 真人数据缺失 -> not_run。
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
from src.workflow_action.taste_stack import (
    build_unified_quality_report,
    compute_wilson_ci,
)


class TestWilsonScoreInterval:
    def test_zero_total_returns_zeros(self):
        assert compute_wilson_ci(0, 0) == (0.0, 0.0)
        assert compute_wilson_ci(5, 0) == (0.0, 0.0)

    def test_real_calculation(self):
        lower, upper = compute_wilson_ci(16, 20)
        assert 0.55 < lower < 0.65
        assert 0.88 < upper < 0.95
        assert lower < upper

    def test_boundary_zero_and_full(self):
        lower0, upper0 = compute_wilson_ci(0, 10)
        assert lower0 == 0.0
        assert upper0 > 0.0

        lower1, upper1 = compute_wilson_ci(10, 10)
        assert lower1 < 1.0
        assert upper1 == 1.0


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


class TestUnifiedQualityReportEvidenceAggregation:
    def test_empty_workspace_all_not_run_no_default_pass(self, tmp_path):
        """空工作区：五层全部 not_run，禁止默认 passed/completed/satisfied."""
        report = build_unified_quality_report("空小说", output_dir=tmp_path)
        assert report.layer1_hard_gates.status == "not_run"
        assert report.layer2_specialized_axes.status == "not_run"
        assert report.layer3_blind_eval.status == "not_run"
        assert report.layer4_pass_audit.status == "not_run"
        assert report.layer5_human_blind_eval.status == "not_run"
        assert report.style_drift.status == "not_run"
        assert "not_run" in report.narrative_evaluation_summary

    def test_only_revision_ledger_without_judge_is_not_run(self, tmp_path):
        """只有 Revision Ledger 而没有盲评 Judge 结果时，Blind Eval 仍为 not_run."""
        ab_ledger = [
            {"pair_id": "p1", "which_is_original": "version_a"},
            {"pair_id": "p2", "which_is_original": "version_b"},
        ]
        (tmp_path / "prose_revision_ledger.json").write_text(
            json.dumps(ab_ledger), encoding="utf-8"
        )
        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report.layer3_blind_eval.status == "not_run"
        assert report.layer3_blind_eval.total_pairs_evaluated == 0

    def test_real_blind_eval_calculates_wilson_ci(self, tmp_path):
        """真实 Blind Eval 报告：实时从计数计算净改善率与 Wilson CI."""
        eval_report = {
            "total_pairs_evaluated": 10,
            "better_count": 8,
            "worse_count": 1,
            "no_difference_count": 1,
            "uncertain_count": 0,
        }
        (tmp_path / "ab_blind_eval_report.json").write_text(
            json.dumps(eval_report), encoding="utf-8"
        )
        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report.layer3_blind_eval.status == "completed"
        assert report.layer3_blind_eval.better_count == 8
        assert report.layer3_blind_eval.worse_count == 1
        assert report.layer3_blind_eval.net_improvement_rate == 0.7  # (8-1)/10
        assert report.layer3_blind_eval.wilson_ci_95[0] > 0.4
        assert report.layer3_blind_eval.wilson_ci_95[1] <= 1.0

    def test_reader_gate_pass_and_block_integration(self, tmp_path):
        """Reader Gate 结果真实映射到 Layer 1，并强制核验 run_manifest.json."""
        import hashlib

        # 0. 无 manifest 时严格为 invalid_evidence
        gate_unverified = {"route": "pass", "issues": []}
        (tmp_path / "reader_gate_report.json").write_text(json.dumps(gate_unverified), encoding="utf-8")
        report_unverified = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report_unverified.layer1_hard_gates.status == "invalid_evidence"

        # 1. Block 情况
        gate_block = {
            "route": "block",
            "chapter_ref": "chapter_1",
            "reasons": ["因果防线：死亡后无因活跃"],
            "issues": [{"severity": "blocking", "description": "角色死而复生"}],
            "axes_armed": {"causal_defense": True},
        }
        gate_block_file = tmp_path / "reader_gate_report.json"
        gate_block_file.write_text(json.dumps(gate_block, ensure_ascii=False), encoding="utf-8")
        gate_sha = hashlib.sha256(gate_block_file.read_bytes()).hexdigest()

        manifest_block = {
            "run_id": "run_01",
            "status": "committed",
            "chapter_ref": "chapter_1",
            "artifacts": {
                "reader_gate_report.json": gate_sha,
            },
        }
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest_block), encoding="utf-8")

        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report.layer1_hard_gates.status == "blocked"
        assert report.layer1_hard_gates.blocking_issues_count == 1

        # 2. Pass 情况
        gate_pass = {
            "route": "pass",
            "chapter_ref": "chapter_1",
            "reasons": [],
            "issues": [],
            "axes_armed": {"fact_consistency": True, "temporal_consistency": True},
        }
        gate_pass_file = tmp_path / "reader_gate_report.json"
        gate_pass_file.write_text(json.dumps(gate_pass, ensure_ascii=False), encoding="utf-8")
        gate_pass_sha = hashlib.sha256(gate_pass_file.read_bytes()).hexdigest()

        manifest_pass = {
            "run_id": "run_01",
            "status": "committed",
            "chapter_ref": "chapter_1",
            "artifacts": {
                "reader_gate_report.json": gate_pass_sha,
            },
        }
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest_pass), encoding="utf-8")

        report_pass = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report_pass.layer1_hard_gates.status == "passed"
        assert report_pass.layer1_hard_gates.blocking_issues_count == 0

    def test_corrupted_json_invalid_evidence_and_strict_mode(self, tmp_path):
        """损坏证据文件应标记 invalid_evidence，strict_evidence 模式抛出错误."""
        (tmp_path / "reader_gate_report.json").write_text("{ corrupt json ", encoding="utf-8")
        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report.layer1_hard_gates.status == "invalid_evidence"
        assert len(report.layer1_hard_gates.errors) > 0

        with pytest.raises(ValueError, match="Strict evidence validation failed"):
            build_unified_quality_report("测试作", output_dir=tmp_path, strict_evidence=True)

    def test_no_mastery_score_in_payload_or_markdown(self, tmp_path):
        """严禁任何单一标量大神总分."""
        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        md = report.render_markdown()
        assert "严禁输出单一加权「大神分」" in md
        data = report.model_dump(mode="json")
        for forbidden in ("mastery_score", "overall_score", "score", "total_score"):
            assert forbidden not in data
