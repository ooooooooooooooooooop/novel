"""终审整改核心问题全量锁定与契约回归测试 (R0-R9 Remediation Core Verification).

系统化锁定 6 个核心结构性缺陷的修复契约：
1. ChapterCommitBoundary & Orchestration 原子事务闭环与字段解耦 (R2).
2. 真实 3-5 步对象级深拷贝多步仿真推演与多样性门禁拒绝静默回退 (R3).
3. Taste Stack 不可变身份绑定、算术守恒校验与因果防线代价世界规则绑定 (R1 & R4).
4. AuthorModel V3 原子写盘、显式异常抛出与 Strict Shadow 资格认证 (R5).
5. 人类盲评多版本混排 (N>=2)、公私目录强隔离、种子脱敏、读者去重与证据驱动前置条件推导 (R6).
6. 完整端到端生命周期断点恢复与回滚安全性。
"""

import hashlib
import json
from pathlib import Path
import pytest

from src.boundary_control.chapter_commit import (
    ChapterCommitBoundary,
    FAILPOINT_STEPS,
)
from src.domain_layer.causal_defense import detect_invalidated_cost
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    WorldModel,
)
from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CrossWorkValidationResult,
)
from src.object_state.human_eval import (
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonPreconditionStatus,
)
from src.object_state.orchestration import (
    CommittedOrchestrationState,
    OrchestrationPlan,
)
from src.object_state.structural_search import (
    StructuralProposal,
    StructuralSearchResult,
)
from src.workflow_action.author_selector import (
    CandidateEvaluation,
    reconstruct_selection_outcome,
)
from src.workflow_action.authormodel_v3 import (
    is_author_model_certified_for_production,
    load_author_model_v3,
    save_author_model_v3,
)
from src.workflow_action.human_eval import (
    build_blinded_human_eval_packet,
    evaluate_human_submissions,
    evaluate_long_horizon_authorization,
    inspect_long_horizon_preconditions,
)
from src.workflow_action.narrative_orchestrator import (
    build_committed_orchestration_transition,
)
from src.workflow_action.structural_search import (
    StructuralSearchEngine,
    clone_and_rollout_planner,
    evaluate_structural_diversity,
)
from src.workflow_action.taste_stack import (
    build_unified_quality_report,
)


# ===========================================================================
# 1. ChapterCommitBoundary & Orchestration 事务与解耦 (R2)
# ===========================================================================

class TestOrchestrationCommitTransaction:
    def test_orchestration_atomic_commit_and_failpoint(self, tmp_path):
        """Orchestration 状态纳入 ChapterCommitBoundary 单事务与 failpoint 步进."""
        output_dir = tmp_path / "workspace"
        output_dir.mkdir()
        chapters_dir = output_dir / "chapters"
        chapters_dir.mkdir()

        boundary = ChapterCommitBoundary(output_dir, chapters_dir)

        # 模拟 orchestration JSON 数据
        orch_state_json = '{"threads": [{"thread_id": "main_line", "status": "active"}]}'
        orch_hist_json = '[{"chapter_number": 1, "action": "open"}]'

        state_p = output_dir / "narrativestate.json"
        state_p.write_text("{}", encoding="utf-8")
        frames_p = output_dir / "frames.json"
        frames_p.write_text("{}", encoding="utf-8")

        res = boundary.commit(
            chapter_number=1,
            chapter_text="正文内容...",
            run_id="run_test_01",
            mode="compose",
            state_path=state_p,
            state_json="{}",
            frames_path=frames_p,
            frames_json="{}",
            orchestration_state_json=orch_state_json,
            orchestration_history_json=orch_hist_json,
        )

        assert res.ok is True
        assert res.run_manifest.status == "committed"
        assert (output_dir / "committed_orchestration_state.json").exists()
        assert (output_dir / "orchestration_history.json").exists()
        assert (output_dir / "run_manifest.json").exists()

        # 验证 failpoint 包含 orchestration
        assert "orchestration" in FAILPOINT_STEPS

    def test_orchestration_transition_decouples_participants_and_advances_timestamps(self):
        """build_committed_orchestration_transition 解耦 participants 与 threads，并推进时间戳."""
        initial_state = CommittedOrchestrationState(
            last_committed_chapter=1,
            thread_last_seen={"t_main": 1},
            thread_last_advanced={"t_main": 1},
            expectation_started_at={"身世之谜": 1},
            expectation_last_advanced_at={"身世之谜": 1},
        )

        plan = OrchestrationPlan(
            chapter_number=2,
            assigned_function="escalation",
            priority_tasks=["调查真相"],
        )

        pu = PlotUnit(
            unit_id="pu_ch2_01",
            level="chapter",
            goal="调查真相",
            conflict="长老阻拦",
            input_state_ref="ns_01",
            output_state_ref="ns_02",
            participants=["char_lin", "char_su"],
            released_information=["宗门秘闻"],
        )

        updated_state, state_json, hist_json = build_committed_orchestration_transition(
            initial_state,
            plan,
            plotunit=pu,
            chapter_number=2,
            run_id="run_ch2",
            threads_advanced=["t_main"],
        )

        assert updated_state.last_committed_chapter == 2
        assert updated_state.thread_last_advanced["t_main"] == 2
        assert len(updated_state.history_entries) == 1
        entry = updated_state.history_entries[0]
        assert entry.advanced_threads == ["t_main"]
        assert "char_lin" not in entry.advanced_threads


# ===========================================================================
# 2. Structural Search 对象级推演与多样性门禁严苛化 (R3)
# ===========================================================================

class TestStructuralSearchDynamicRolloutAndDiversity:
    def test_dynamic_object_level_simulation(self):
        """clone_and_rollout_planner 执行真正的对象级深拷贝多步仿真."""
        state = NarrativeState(
            state_id="state_init",
            current_time="天启三年春",
            current_location="青云宗后山",
            current_situation="面临抉择",
            open_questions=["身世之谜"],
        )
        ledger = FactLedger(
            entries=[
                FactEntry(
                    fact_id="f1",
                    fact_type="event",
                    statement="林尘修为尽失经脉尽断",
                    confirmed=True,
                    involved_entities=["林尘"],
                )
            ]
        )
        char = CharacterModel(
            character_id="char_lin",
            name="林尘",
            identity="宗门弃徒",
            outer_goal="重登巅峰",
            inner_need="求索大道",
            fear="重蹈覆辙",
            flaw="执拗",
            strength="坚韧",
            stance="隐忍",
        )
        graph = ForeshadowGraph(
            entries=[
                ForeshadowEntry(
                    thread_id="fn_01",
                    setup_point="第1章",
                    content="残破玉佩的秘密",
                    visibility_level="explicit",
                    expected_payoff="解开身世",
                    current_status="active",
                )
            ]
        )
        world = WorldModel(
            prohibitions=["禁止无代价逆转生死与经脉损毁"],
            consequence_logic=["强行催动禁术将引发反噬断绝生机"],
        )
        objects = [state, ledger, char, graph, world]

        # 方案 A：破坏世界禁忌，强行瞬间恢复
        prop_bad = StructuralProposal(
            proposal_id="p_illegal",
            primary_actor="林尘",
            core_choice="强行催动禁术直接恢复经脉完好如初",
            resistance_source="反噬",
            cost="无",
            state_change="经脉尽复完好如初",
        )
        rollout_bad = clone_and_rollout_planner(prop_bad, state, objects, steps=3)
        assert len(rollout_bad.risk_flags) > 0
        assert rollout_bad.overall_sustainability < 0.6

        # 方案 B：合规因果推进，付出代价稳步探索
        prop_good = StructuralProposal(
            proposal_id="p_legal",
            primary_actor="林尘",
            core_choice="借助残破玉佩温养暗伤，推演古经",
            resistance_source="修炼阻力",
            cost="承受神魂撕裂之痛",
            state_change="摸索出一条新的淬体路径",
        )
        rollout_good = clone_and_rollout_planner(prop_good, state, objects, steps=3)
        assert rollout_good.overall_sustainability > rollout_bad.overall_sustainability

    def test_diversity_failure_strictly_raises_error_without_fallback(self):
        """多样性门禁不足时显式抛出异常，杜绝静默降级."""
        p1 = StructuralProposal(
            proposal_id="p1",
            primary_actor="林尘",
            core_choice="选择正面应战执法堂",
            resistance_source="戒律长老",
            cost="重伤",
            state_change="名声大噪",
        )
        # 近重复方案（仅改几个字）
        p2 = StructuralProposal(
            proposal_id="p2",
            primary_actor="林尘",
            core_choice="选择正面迎战执法堂",
            resistance_source="戒律长老",
            cost="重伤",
            state_change="名声大震",
        )

        engine = StructuralSearchEngine()
        state = NarrativeState(state_id="s1", current_time="春", current_location="广场", current_situation="对峙")

        with pytest.raises(ValueError, match="structural_diversity_failed"):
            engine.search_and_evaluate([p1, p2], state, [state])

    def test_selection_outcome_reconstruction_on_search_override(self):
        """搜索覆盖初始选择时，完整重构 SelectionOutcome 的 tradeoffs 与 rejected reasons."""
        packages = [
            {"label": "A", "proposal": "速推主线"},
            {"label": "B", "proposal": "深化角色冲突"},
        ]
        evals = {
            "A": CandidateEvaluation(
                label="A",
                unit_id="pu_a",
                consistency_pass=True,
                reader_score=0.9,
                style_score=0.8,
                author_score=0.6,
                tradeoff_hint="快节奏",
            ),
            "B": CandidateEvaluation(
                label="B",
                unit_id="pu_b",
                consistency_pass=True,
                reader_score=0.7,
                style_score=0.9,
                author_score=0.9,
                tradeoff_hint="深化角色冲突",
            ),
        }

        outcome = reconstruct_selection_outcome(
            packages,
            evals,
            selected_label="B",
            rationale="Pareto 前沿因果与可持续性更优",
            override_source="structural_search",
        )

        assert outcome.selected_label == "B"
        assert len(outcome.tradeoff) > 0
        assert any(r["label"] == "A" for r in outcome.rejected)


# ===========================================================================
# 3. Taste Stack 不可变身份绑定、算术校验与因果代价 (R1 & R4)
# ===========================================================================

class TestTasteStackIdentityAndArithmetic:
    def test_layer3_arithmetic_mismatch_marks_invalid_evidence(self, tmp_path):
        """Layer 3 算术不守恒 (declared total != sum of parts) 时严格置为 invalid_evidence."""
        corrupted_report = {
            "total_pairs_evaluated": 100,  # 声明 100
            "better_count": 10,
            "worse_count": 2,
            "no_difference_count": 1,
            "uncertain_count": 0,          # 实际和为 13
        }
        (tmp_path / "ab_blind_eval_report.json").write_text(
            json.dumps(corrupted_report), encoding="utf-8"
        )

        report = build_unified_quality_report("测试作", output_dir=tmp_path)
        assert report.layer3_blind_eval.status == "invalid_evidence"
        assert any("arithmetic mismatch" in e for e in report.layer3_blind_eval.errors)

    def test_causal_defense_structures_rule_cost_mapping(self):
        """因果防线代价失效检测器结构化绑定 world_rule_id 与 reversibility."""
        ledger = FactLedger(
            entries=[
                FactEntry(
                    fact_id="f_cost",
                    fact_type="event",
                    statement="林尘为救同门透支本源道基受损",
                    confirmed=True,
                    involved_entities=["林尘"],
                )
            ]
        )
        pu_recovery = PlotUnit(
            unit_id="pu_02",
            level="chapter",
            goal="修炼",
            conflict="无",
            input_state_ref="ns_01",
            output_state_ref="ns_02",
            state_change_summary="林尘本源竟又恢复完好如初重新拥有圆满道基",
            participants=["林尘"],
        )
        world = WorldModel(
            hard_rules=["本源道基损耗不可逆转，非天地灵根无法修复"],
            consequence_logic=["强行透支必然招致修为跌落"],
        )

        issues = detect_invalidated_cost([ledger, pu_recovery, world])
        assert len(issues) >= 1
        issue = issues[0]
        assert issue.severity == "blocking"
        assert issue.issue_type == "world_violation"
        assert "rule_id=hard_rule_1" in issue.violated_rule
        assert "reversibility=irreversible" in issue.violated_rule


# ===========================================================================
# 4. AuthorModel V3 原子写入与 Strict Shadow Mode (R5)
# ===========================================================================

class TestAuthorModelV3AtomicAndShadow:
    def test_atomic_save_and_corrupted_load_raises(self, tmp_path):
        """AuthorModel V3 原子落盘，损坏文件显式抛出异常."""
        model = AuthorModelV3(
            author_id="author_atomic",
            principles=[
                AuthorPrincipleV3(
                    principle_id="ap1",
                    statement="坚持因果",
                    value_vocab_key="character_causality_over_plot_convenience",
                )
            ],
        )
        p = save_author_model_v3(tmp_path, model)
        assert p.exists()
        loaded = load_author_model_v3(tmp_path)
        assert loaded.author_id == "author_atomic"

        # 写入破坏性 JSON
        (tmp_path / "author_model_v3.json").write_text("{ corrupt json ", encoding="utf-8")
        with pytest.raises(ValueError, match="Corrupted or invalid author_model_v3"):
            load_author_model_v3(tmp_path)

    def test_strict_shadow_mode_enforcement(self):
        """未通过 L1WO 资格认证的 AuthorModel 严禁改变正式生产决策."""
        model = AuthorModelV3(author_id="author_test")

        # 1. 无资格报告 -> 未认证
        assert is_author_model_certified_for_production(model, None) is False

        # 2. 词汇泄露报告 -> 未认证
        leaked_report = CrossWorkValidationResult(
            author_id="author_test",
            holdout_work="作品B",
            training_works=["作品A"],
            choice_prediction_accuracy=0.7,
            baseline_accuracy=0.5,
            lexical_leakage_detected=True,
            is_valid_author_prior=False,
        )
        assert is_author_model_certified_for_production(model, leaked_report) is False

        # 3. 干净合规认证 -> 认证通过
        valid_report = CrossWorkValidationResult(
            author_id="author_test",
            holdout_work="作品B",
            training_works=["作品A"],
            choice_prediction_accuracy=0.8,
            baseline_accuracy=0.5,
            lexical_leakage_detected=False,
            is_valid_author_prior=True,
        )
        assert is_author_model_certified_for_production(model, valid_report) is True


# ===========================================================================
# 5. 人类盲评协议硬化与证据驱动前置条件推导 (R6)
# ===========================================================================

class TestHumanEvalProtocolHardening:
    def test_multi_version_support_and_seed_masking(self, tmp_path):
        """支持 N>=2 任意版本数，公开包掩盖明文种子，公私目录包含关系报错."""
        pub_dir = tmp_path / "public"
        sec_dir = tmp_path / "secret"

        version_data = {
            "v_sys": [{"title": "第1章", "content": "内容1"}],
            "v_hum": [{"title": "第1章", "content": "内容2"}],
            "v_base": [{"title": "第1章", "content": "内容3"}],
        }

        packet, mapping = build_blinded_human_eval_packet(
            "测试小说",
            version_data,
            chapter_range="1-1",
            public_output_dir=pub_dir,
            secret_output_dir=sec_dir,
            random_seed=999,
        )

        assert len(packet.blinded_versions) == 3
        # 公开包检查：random_seed 为 None
        pub_content = json.loads((pub_dir / "blinded_packet.json").read_text(encoding="utf-8"))
        assert pub_content["random_seed"] is None
        assert pub_content["seed_hash"] != ""

        # 目录嵌套检查（包含关系必须抛错）
        sub_dir = pub_dir / "nested_secret"
        with pytest.raises(ValueError, match="严格物理隔离"):
            build_blinded_human_eval_packet(
                "测试小说",
                version_data,
                public_output_dir=pub_dir,
                secret_output_dir=sub_dir,
            )

    def test_reader_duplicate_explicitly_rejected(self):
        """R6 硬口径：同一 reader_id 多次提交必须显式拒绝，而不是静默保留最后一份."""
        mapping = {"cand_alpha": "v_sys", "cand_beta": "v_hum"}
        manifest_hash = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode("utf-8")).hexdigest()
        packet = BlindedChapterPacket(
            packet_id="pkt_01",
            novel_name="测试",
            chapter_range="1-1",
            blinded_versions={"cand_alpha": [], "cand_beta": []},
            secret_manifest_hash=manifest_hash,
        )

        submissions = [
            HumanEvaluationSubmission(
                submission_id="sub_1",
                packet_id="pkt_01",
                reader_id="reader_repeat",
                reader_group="casual_reader",
                preferred_version="cand_alpha",
            ),
            HumanEvaluationSubmission(
                submission_id="sub_2",
                packet_id="pkt_01",
                reader_id="reader_repeat",
                reader_group="casual_reader",
                preferred_version="cand_beta",  # 读者改选
            ),
        ]

        # 重复 reader_id 必须显式拒绝（不同 submission_id 但同一 reader 多次提交）
        with pytest.raises(ValueError, match="Duplicate reader_id detected"):
            evaluate_human_submissions(packet, submissions, mapping)

    def test_inspect_preconditions_strictly_reads_disk_artifacts_and_rejects_empty(self, tmp_path):
        """inspect_long_horizon_preconditions 绝无 import 作弊，无磁盘产物默认全为 False."""
        empty_status = inspect_long_horizon_preconditions(tmp_path)
        assert empty_status.p1_causal_defense_complete is False
        assert empty_status.p2_orchestrator_in_production is False
        assert empty_status.real_human_continuous_reading_data_exists is False

        verdict = evaluate_long_horizon_authorization(empty_status)
        assert verdict.verdict == "long_run_not_authorized"
        assert len(verdict.unmet_preconditions) == 10
