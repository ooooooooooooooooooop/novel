"""P7 独立人类双盲评估工具包与长程无人生产授权裁决测试.

覆盖：
1. 双盲材料包组装 (build_blinded_human_eval_packet) 与密钥哈希锁定。
2. 真实读者提交聚合 (evaluate_human_submissions)：偏好、追读意愿独立性与弃读点统计。
3. 90 章长程生产 10 项前置条件严苛裁决 (evaluate_long_horizon_authorization)：
   - 缺真人数据时绝不放行，严格输出 long_run_not_authorized。
   - 10 项全满足时才输出 long_run_authorized。
"""

import json
from pathlib import Path

import pytest

from src.object_state.human_eval import (
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonAuthorizationVerdict,
    LongHorizonPreconditionStatus,
)
from src.workflow_action.human_eval import (
    build_blinded_human_eval_packet,
    evaluate_human_submissions,
    evaluate_long_horizon_authorization,
)


class TestHumanBlindEvalToolkit:
    def test_build_blinded_packet_and_anonymization(self, tmp_path):
        version_data = {
            "v3_system": [
                {"chapter_num": 1, "title": "初入宗门", "content": "正文内容A", "source_version": "v3"},
                {"chapter_num": 2, "title": "因果显现", "content": "正文内容B", "generator_info": "llm"},
            ],
            "human_original": [
                {"chapter_num": 1, "title": "初入宗门", "content": "人类原版内容A"},
                {"chapter_num": 2, "title": "因果显现", "content": "人类原版内容B"},
            ],
        }

        packet, secret_manifest = build_blinded_human_eval_packet(
            "万物伏藏",
            version_data,
            chapter_range="1-2",
            output_dir=tmp_path,
        )

        assert isinstance(packet, BlindedChapterPacket)
        assert len(packet.blinded_versions) == 2
        assert "cand_alpha" in packet.blinded_versions
        assert "cand_beta" in packet.blinded_versions
        assert len(packet.secret_manifest_hash) == 64

        # 验证内部 payload 的敏感标记已被抹除
        for ch in packet.blinded_versions["cand_alpha"]:
            assert "source_version" not in ch
            assert "generator_info" not in ch

        assert (tmp_path / "blinded_packet.json").exists()
        assert (tmp_path / "secret_manifest.json").exists()

    def test_evaluate_human_submissions(self):
        packet = BlindedChapterPacket(
            packet_id="packet_test_01",
            novel_name="万物伏藏",
            chapter_range="1-5",
            blinded_versions={"cand_alpha": [], "cand_beta": []},
            secret_manifest_hash="dummy_hash",
        )
        secret_manifest = {
            "cand_alpha": "system_v3",
            "cand_beta": "human_original",
        }

        submissions = [
            HumanEvaluationSubmission(
                submission_id="sub_01",
                packet_id="packet_test_01",
                reader_id="reader_pro_01",
                reader_group="professional_editor",
                preferred_version="cand_alpha",
                continuation_willingness=True,
            ),
            HumanEvaluationSubmission(
                submission_id="sub_02",
                packet_id="packet_test_01",
                reader_id="reader_vet_01",
                reader_group="veteran_reader",
                preferred_version="cand_beta",
                continuation_willingness=False,
                abandonment_point_chapter=4,
                abandonment_reason="第四章剧情拖沓",
            ),
            HumanEvaluationSubmission(
                submission_id="sub_03",
                packet_id="packet_test_01",
                reader_id="reader_vet_02",
                reader_group="veteran_reader",
                preferred_version="no_difference",
                continuation_willingness=True,
            ),
        ]

        result = evaluate_human_submissions(packet, submissions, secret_manifest)

        assert result["total_readers"] == 3
        assert result["preference_distribution"]["system_v3"] == pytest.approx(1 / 3)
        assert result["preference_distribution"]["human_original"] == pytest.approx(1 / 3)
        assert result["preference_distribution"]["no_difference"] == pytest.approx(1 / 3)
        assert len(result["abandonment_points"]) == 1
        assert result["abandonment_points"][0]["chapter"] == 4


class TestLongHorizonAuthorization:
    def test_default_status_strictly_rejects_authorization_due_to_missing_human_data(self):
        # 默认情况下真实人类实验数据未完成 (real_human_continuous_reading_data_exists=False)
        verdict = evaluate_long_horizon_authorization()

        assert verdict.verdict == "long_run_not_authorized"
        assert len(verdict.unmet_preconditions) == 1
        assert "缺少系统外真实人类连续阅读实验数据" in verdict.unmet_preconditions[0]
        assert "严格未授权" in verdict.notes

    def test_full_ten_preconditions_satisfied_grants_authorization(self):
        # 模拟 10 项条件全部满足
        full_status = LongHorizonPreconditionStatus(
            p1_causal_defense_complete=True,
            p2_orchestrator_in_production=True,
            p3_structural_search_active=True,
            p3_diversity_validated=True,
            p4_blind_eval_stable=True,
            p4_pass_audit_frozen=True,
            p4_human_eval_protocol_frozen=True,
            real_human_continuous_reading_data_exists=True,
            provider_profile_and_budget_frozen=True,
            historical_release_records_intact=True,
        )

        verdict = evaluate_long_horizon_authorization(full_status)

        assert verdict.verdict == "long_run_authorized"
        assert len(verdict.unmet_preconditions) == 0
        assert "长程无人生产获得授权" in verdict.notes

    def test_any_single_precondition_failure_blocks_authorization(self):
        # 即使有真人数据，若因果防线存在破绽或历史发布记录受损，立即阻断
        status = LongHorizonPreconditionStatus(
            p1_causal_defense_complete=False,
            real_human_continuous_reading_data_exists=True,
        )

        verdict = evaluate_long_horizon_authorization(status)
        assert verdict.verdict == "long_run_not_authorized"
        assert "P1 长程因果防线未完全闭环" in verdict.unmet_preconditions
