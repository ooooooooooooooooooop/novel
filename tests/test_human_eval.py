"""P7 独立人类双盲评估工具包与长程无人生产授权裁决测试 (R6 整改).

覆盖：
1. 双盲材料包组装 (build_blinded_human_eval_packet) 与真随机种子、密钥哈希锁定。
2. 严格公私目录物理隔离 (--public-output-dir vs --secret-output-dir)。
3. 真实读者提交聚合 (evaluate_human_submissions)：偏好、多版本独立追读意愿与弃读点统计。
4. 90 章长程生产 10 项前置条件严苛裁决 (evaluate_long_horizon_authorization)：
   - 缺真人数据时绝不放行，严格输出 long_run_not_authorized。
   - 10 项全满足时才输出 long_run_authorized。
"""

import hashlib
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
    inspect_long_horizon_preconditions,
)


class TestHumanBlindEvalToolkit:
    def test_build_blinded_packet_with_physical_isolation(self, tmp_path):
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

        pub_dir = tmp_path / "public"
        sec_dir = tmp_path / "secret"

        packet, secret_manifest = build_blinded_human_eval_packet(
            "万物伏藏",
            version_data,
            chapter_range="1-2",
            public_output_dir=pub_dir,
            secret_output_dir=sec_dir,
            random_seed=12345,
        )

        assert isinstance(packet, BlindedChapterPacket)
        assert len(packet.blinded_versions) == 2
        assert "cand_alpha" in packet.blinded_versions
        assert "cand_beta" in packet.blinded_versions
        assert packet.random_seed == 12345
        assert len(packet.seed_hash) == 64
        assert len(packet.secret_manifest_hash) == 64

        # 验证内部 payload 的敏感标记已被抹除
        for ch in packet.blinded_versions["cand_alpha"]:
            assert "source_version" not in ch
            assert "generator_info" not in ch

        # 验证公私目录物理隔离
        assert (pub_dir / "blinded_packet.json").exists()
        assert (pub_dir / "submission_template.json").exists()
        assert not (pub_dir / "secret_manifest.json").exists()  # 公开目录绝不含密钥

        assert (sec_dir / "secret_manifest.json").exists()
        secret_content = json.loads((sec_dir / "secret_manifest.json").read_text(encoding="utf-8"))
        assert secret_content["random_seed"] == 12345
        assert "mapping" in secret_content

    def test_build_blinded_packet_same_directory_raises_error(self, tmp_path):
        version_data = {"v1": [], "v2": []}
        with pytest.raises(ValueError, match="严格物理隔离"):
            build_blinded_human_eval_packet(
                "万物伏藏",
                version_data,
                public_output_dir=tmp_path,
                secret_output_dir=tmp_path,
            )

    def test_evaluate_human_submissions_per_version_metrics(self):
        secret_manifest = {
            "cand_alpha": "system_v3",
            "cand_beta": "human_original",
        }
        manifest_hash = hashlib.sha256(
            json.dumps(secret_manifest, sort_keys=True).encode("utf-8")
        ).hexdigest()
        packet = BlindedChapterPacket(
            packet_id="packet_test_01",
            novel_name="万物伏藏",
            chapter_range="1-5",
            blinded_versions={"cand_alpha": [], "cand_beta": []},
            secret_manifest_hash=manifest_hash,
        )

        submissions = [
            HumanEvaluationSubmission(
                submission_id="sub_01",
                packet_id="packet_test_01",
                reader_id="reader_pro_01",
                reader_group="professional_editor",
                preferred_version="cand_alpha",
                continuation_willingness_by_version={"cand_alpha": True, "cand_beta": True},
                abandonment_by_version={"cand_alpha": None, "cand_beta": None},
            ),
            HumanEvaluationSubmission(
                submission_id="sub_02",
                packet_id="packet_test_01",
                reader_id="reader_vet_01",
                reader_group="veteran_reader",
                preferred_version="cand_beta",
                continuation_willingness_by_version={"cand_alpha": False, "cand_beta": False},
                abandonment_by_version={"cand_alpha": 3, "cand_beta": 4},
                abandonment_reasons_by_version={"cand_alpha": "战力崩溃", "cand_beta": "剧情拖沓"},
            ),
            HumanEvaluationSubmission(
                submission_id="sub_03",
                packet_id="packet_test_01",
                reader_id="reader_vet_02",
                reader_group="veteran_reader",
                preferred_version="no_difference",
                continuation_willingness_by_version={"cand_alpha": True, "cand_beta": False},
                abandonment_by_version={"cand_alpha": None, "cand_beta": 2},
            ),
        ]

        result = evaluate_human_submissions(packet, submissions, secret_manifest)

        assert result["total_readers"] == 3
        assert result["preference_distribution"]["system_v3"] == pytest.approx(1 / 3, 0.01)
        assert result["preference_distribution"]["human_original"] == pytest.approx(1 / 3, 0.01)
        assert result["preference_distribution"]["no_difference"] == pytest.approx(1 / 3, 0.01)

        # 按版本独立的追读率
        assert result["continuation_rate_by_version"]["system_v3"] == pytest.approx(2 / 3, 0.01)
        assert result["continuation_rate_by_version"]["human_original"] == pytest.approx(1 / 3, 0.01)

        # 按版本独立的弃读统计
        assert result["abandonment_counts_by_version"]["system_v3"] == 1
        assert result["abandonment_counts_by_version"]["human_original"] == 2
        assert len(result["abandonment_points"]) == 3

    def test_evaluate_human_submissions_strict_validation(self):
        secret_manifest = {"cand_alpha": "v1", "cand_beta": "v2"}
        manifest_hash = hashlib.sha256(
            json.dumps(secret_manifest, sort_keys=True).encode("utf-8")
        ).hexdigest()
        packet = BlindedChapterPacket(
            packet_id="packet_test_valid",
            novel_name="万物伏藏",
            chapter_range="1-2",
            blinded_versions={"cand_alpha": [], "cand_beta": []},
            secret_manifest_hash=manifest_hash,
        )

        # 1. 重复 submission_id
        sub_dup1 = HumanEvaluationSubmission(
            submission_id="sub_dup",
            packet_id="packet_test_valid",
            reader_id="r1",
            reader_group="veteran_reader",
            preferred_version="cand_alpha",
        )
        sub_dup2 = HumanEvaluationSubmission(
            submission_id="sub_dup",
            packet_id="packet_test_valid",
            reader_id="r2",
            reader_group="veteran_reader",
            preferred_version="cand_beta",
        )
        with pytest.raises(ValueError, match="Duplicate submission_id detected"):
            evaluate_human_submissions(packet, [sub_dup1, sub_dup2], secret_manifest)

        # 2. packet_id 不匹配
        sub_mismatch = HumanEvaluationSubmission(
            submission_id="sub_mis",
            packet_id="packet_wrong_id",
            reader_id="r1",
            reader_group="veteran_reader",
            preferred_version="cand_alpha",
        )
        with pytest.raises(ValueError, match="Packet ID mismatch"):
            evaluate_human_submissions(packet, [sub_mismatch], secret_manifest)

        # 3. 未知版本代号（杜绝 fallback）
        sub_unknown = HumanEvaluationSubmission(
            submission_id="sub_unk",
            packet_id="packet_test_valid",
            reader_id="r1",
            reader_group="veteran_reader",
            preferred_version="cand_gamma_unregistered",
        )
        with pytest.raises(ValueError, match="not found in blinded packet manifest"):
            evaluate_human_submissions(packet, [sub_unknown], secret_manifest)

        # 4. 密钥哈希不匹配
        bad_packet = BlindedChapterPacket(
            packet_id="packet_bad_hash",
            novel_name="万物伏藏",
            chapter_range="1-2",
            blinded_versions={"cand_alpha": [], "cand_beta": []},
            secret_manifest_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        sub_ok = HumanEvaluationSubmission(
            submission_id="sub_ok_1",
            packet_id="packet_bad_hash",
            reader_id="r1",
            reader_group="veteran_reader",
            preferred_version="cand_alpha",
            continuation_willingness_by_version={"cand_alpha": True, "cand_beta": True},
            abandonment_by_version={"cand_alpha": None, "cand_beta": None},
        )
        with pytest.raises(ValueError, match="Secret manifest hash mismatch"):
            evaluate_human_submissions(bad_packet, [sub_ok], secret_manifest)

        # 5. 版本覆盖不全
        sub_incomplete = HumanEvaluationSubmission(
            submission_id="sub_inc",
            packet_id="packet_test_valid",
            reader_id="r1",
            reader_group="veteran_reader",
            preferred_version="cand_alpha",
            continuation_willingness_by_version={"cand_alpha": True},  # 缺少 cand_beta
            abandonment_by_version={"cand_alpha": None, "cand_beta": None},
        )
        with pytest.raises(ValueError, match="missing continuation evaluation for versions"):
            evaluate_human_submissions(packet, [sub_incomplete], secret_manifest)


class TestLongHorizonAuthorization:
    def test_default_status_strictly_rejects_authorization_due_to_missing_human_data(self):
        # 默认情况下真实人类实验数据未完成 (real_human_continuous_reading_data_exists=False)
        verdict = evaluate_long_horizon_authorization()

        assert verdict.verdict == "long_run_not_authorized"
        assert len(verdict.unmet_preconditions) >= 1
        assert any("缺少系统外真实人类连续阅读实验数据" in p for p in verdict.unmet_preconditions)
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
        # 即使有真人数据，若因果防线存在破绽，立即阻断
        status = LongHorizonPreconditionStatus(
            p1_causal_defense_complete=False,
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

        verdict = evaluate_long_horizon_authorization(status)
        assert verdict.verdict == "long_run_not_authorized"
        assert "P1 长程因果防线未完全闭环" in verdict.unmet_preconditions

    def test_inspect_preconditions_no_run_manifest_fallback_for_p9_p10(self, tmp_path):
        # 仅有 run_manifest.json，没有真实 provider_profiles 或 release_record
        manifest = {
            "status": "committed",
            "run_id": "run_001",
            "artifacts": {},
        }
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        status = inspect_long_horizon_preconditions(tmp_path)
        # P9 与 P10 绝不能因为存在 run_manifest.json 就被误判为 True
        assert status.provider_profile_and_budget_frozen is False
        assert status.historical_release_records_intact is False
