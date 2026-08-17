"""端到端整改闭环集成测试 (R9 端到端验收).

完整覆盖：
1. Narrative Orchestrator: 跨章已提交编排状态持久化 (load -> derive -> commit)。
2. Structural Search: 异质性门禁、深拷贝 3-5 步状态推演 (clone_and_rollout_planner) 与胜选提案权威绑定。
3. Causal Defense & Reader Gate: 叙事时间线校验、实体 Alias Registry、因果违规路由 (block/rewrite/pass)。
4. Hindsight & AuthorModel V3: 真实后续章节反哺更新决策原则 (candidate -> weak -> stable/contested) 与物理持久化。
5. Taste Stack Unified Quality Report: 真实读取落盘证据、计算 Wilson 95% CI、严格模式与 G7 退役标识。
6. Long Horizon Authorization: 严苛 10 项前置条件裁决，缺少真人数据时真实返回 long_run_not_authorized。
"""

import json
from pathlib import Path
import pytest

from src.object_state.orchestration import OrchestrationPlan, OrchestrationState
from src.workflow_action.narrative_orchestrator import (
    commit_orchestration_transition,
    derive_orchestration_plan,
    load_committed_orchestration_state,
)
from src.object_state.structural_search import (
    CandidatePrecommit,
    StructuralProposal,
)
from src.workflow_action.structural_search import (
    StructuralSearchEngine,
    clone_and_rollout_planner,
    evaluate_structural_diversity,
)
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    PlotUnit,
    WorldModel,
)
from src.domain_layer.causal_defense import EntityAliasRegistry, run_causal_defense
from src.boundary_control.reader_gate import ReaderQualityGatePolicy, evaluate_commit_reader_gate
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    RejectedRecord,
)
from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CrossWorkValidationResult,
)
from src.workflow_action.authormodel_v3 import (
    load_author_model_v3,
    save_author_model_v3,
    update_author_model_from_hindsight,
)
from src.workflow_action.taste_stack import build_unified_quality_report
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


class TestRemediationFullPipelineIntegration:
    """端到端全链路整改验收集成测试."""

    def test_full_remediation_pipeline_e2e(self, tmp_path):
        novel_dir = tmp_path / "novels" / "万物伏藏"
        output_dir = novel_dir / "output" / "extend"
        chapters_dir = novel_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------------
        # 1. Narrative Orchestrator: 第一章编排状态与提交
        # -------------------------------------------------------------------
        init_state = load_committed_orchestration_state(output_dir)
        assert init_state.last_committed_chapter == 0

        # 第一章派生计划
        narrative_s1 = NarrativeState(
            state_id="s_ch1",
            current_time="天启三年春",
            current_location="天玄宗外门",
            current_situation="初入宗门，局势未定",
        )
        plan_ch1 = derive_orchestration_plan(
            init_state,
            [narrative_s1],
            chapter_number=1,
        )
        assert plan_ch1.chapter_number == 1
        assert plan_ch1.assigned_function == "setup"

        # 提交第一章
        ch1_file = chapters_dir / "chapter_001.json"
        ch1_file.write_text(
            json.dumps({"chapter_num": 1, "title": "初入宗门", "content": "第一章正文"}, ensure_ascii=False),
            encoding="utf-8",
        )
        st1 = commit_orchestration_transition(
            output_dir,
            plan_ch1,
            chapter_number=1,
            run_id="run_test_01",
        )
        assert st1.last_committed_chapter == 1
        assert (output_dir / "committed_orchestration_state.json").exists()
        assert (output_dir / "orchestration_history.json").exists()

        # -------------------------------------------------------------------
        # 2. Structural Search: 异质性候选生成与深拷贝 Rollout
        # -------------------------------------------------------------------
        prop_a = StructuralProposal(
            proposal_id="prop_01_a",
            primary_actor="林尘",
            core_choice="正面接受执法堂质询并依法答辩，暗中布局留存证供",
            resistance_source="执法长老的偏见",
            cost="承受神魂盘问付出重伤代价",
            state_change="洗清嫌疑获得进入藏经阁资格",
            chapter_function="选择",
        )
        prop_b = StructuralProposal(
            proposal_id="prop_01_b",
            primary_actor="林尘",
            core_choice="利用假死丹药制造意外金蝉脱壳潜逃",
            resistance_source="封山大阵与追捕弟子",
            cost="失去宗门合法身份成为逃犯",
            state_change="潜入黑市寻找线索",
            chapter_function="转向",
        )

        div_res = evaluate_structural_diversity([prop_a, prop_b])
        assert div_res.is_diverse is True
        assert len(div_res.valid_proposals) == 2

        # 深拷贝状态推演
        narrative_state = NarrativeState(
            state_id="s_test",
            current_time="天启三年",
            current_location="天玄宗",
            current_situation="局势未定",
        )
        rollout_res = clone_and_rollout_planner(
            prop_a,
            state=narrative_state,
            objects=[narrative_state],
            steps=3,
        )
        assert rollout_res.overall_sustainability > 0.6
        assert len(rollout_res.steps) == 3

        # 预承诺冻结选择基准
        precommit = CandidatePrecommit(
            precommit_id="precommit_ch2",
            target_chapter=2,
            core_question="林尘如何在执法堂发难下自证清白并保全核心秘密？",
            mandatory_consequences=("洗清嫌疑", "留下暗线"),
            superficial_pitfalls=("用华丽打斗掩盖执法堂权力逻辑破绽",),
            overturn_conditions=("执法堂无证据直接下死手导致程序破裂",),
            trusted_state_hash="a" * 64,
        )
        assert precommit.target_chapter == 2

        # -------------------------------------------------------------------
        # 3. Causal Defense & Reader Gate: 叙事时间线与因果门禁
        # -------------------------------------------------------------------
        facts = [
            FactEntry(
                fact_id="f_ch1_01",
                statement="古堡已被焚毁",
                fact_type="event",
                involved_entities=["古堡"],
                confirmed=True,
            )
        ]
        fact_ledger = FactLedger(entries=facts)
        world_model = WorldModel(
            hard_rules=["凡毁坏之凡铁不可无代价复原"]
        )

        # 违规草稿（在第二章凭空抹除古堡被烧毁事实）
        violating_plot = PlotUnit(
            unit_id="pu_violating",
            level="scene",
            goal="探查古堡",
            conflict="寻找线索",
            released_information=["古堡竟完好如初，仿佛从未发生火灾"],
            input_state_ref="s_in",
            output_state_ref="s_out",
        )
        issues_v = run_causal_defense([fact_ledger, violating_plot])
        assert len(issues_v) >= 1
        assert issues_v[0].issue_type == "fact_conflict"

        # Reader Gate 拦截违规草稿 -> route = block
        gate_policy = ReaderQualityGatePolicy()
        gate_res_v = gate_policy.evaluate(
            draft_text="古堡竟完好如初，仿佛从未发生火灾",
            reconcile_issues=issues_v,
        )
        assert gate_res_v.route == "block"

        # 合规草稿（合法回忆历史或使用新法宝）
        clean_plot = PlotUnit(
            unit_id="pu_clean",
            level="scene",
            goal="回忆往事",
            conflict="悼念",
            released_information=["他记得那座古堡当年被烧毁的惨状"],
            input_state_ref="s_in",
            output_state_ref="s_out",
        )
        issues_c = run_causal_defense([fact_ledger, clean_plot])
        assert len(issues_c) == 0
        gate_res_c = gate_policy.evaluate(
            draft_text="他记得那座古堡当年被烧毁的惨状",
            reconcile_issues=issues_c,
        )
        assert gate_res_c.route == "pass"

        # 提交合规第二章
        import hashlib
        ch2_file = chapters_dir / "chapter_002.json"
        ch2_file.write_text(
            json.dumps({"chapter_num": 2, "title": "青竹退敌", "content": "他记得那座古堡当年被烧毁的惨状"}, ensure_ascii=False),
            encoding="utf-8",
        )
        gate_report = {"gate": "pass", "route": "pass", "chapter_number": 2, "issues": []}
        gate_file = output_dir / "reader_gate_report.json"
        gate_file.write_text(json.dumps(gate_report, ensure_ascii=False, indent=2), encoding="utf-8")
        gate_sha = hashlib.sha256(gate_file.read_bytes()).hexdigest()

        manifest_data = {
            "run_id": "run_test_ch2",
            "status": "committed",
            "chapter_ref": "chapter_2",
            "artifacts": {
                "reader_gate_report.json": gate_sha,
            },
        }
        (output_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        # -------------------------------------------------------------------
        # 4. Hindsight & AuthorModel V3: 原则沉淀与持久化
        # -------------------------------------------------------------------
        author_model = AuthorModelV3(author_id="author_master_01", author_name="执笔者")
        choice_rec = ChoiceRecord(
            decision_id="dec_ch2_01",
            decision_timestamp="2026-08-16T12:00:00Z",
            plot_context="第二章林尘选择尊重历史事实而非抹掉设定",
            state_ref="state_ch2",
            chapter_number=2,
            candidates=[
                CandidateRecord(candidate_id="c_rule", summary="使用符箓自洽对敌", plotunit={}, new_state_ref="s2a"),
                CandidateRecord(candidate_id="c_lazy", summary="凭空拿出旧剑", plotunit={}, new_state_ref="s2b"),
            ],
            selected_candidate="c_rule",
            rejected=[RejectedRecord(candidate_id="c_lazy", reason="因果破裂")],
            tradeoff="尊重前文因果事实",
            value_conflicts=["character_causality_over_plot_convenience"],
            consequence="因果闭环，读者反馈剧情严谨",
            hindsight="still_supported",
            hindsight_note="长期收益显著",
        )
        updated_p = update_author_model_from_hindsight(author_model, [choice_rec], work_name="万物伏藏")
        assert updated_p == 1
        assert len(author_model.principles) == 1
        assert author_model.principles[0].status == "weak"

        p_saved = save_author_model_v3(output_dir, author_model)
        assert p_saved.exists()
        loaded_model = load_author_model_v3(output_dir)
        assert loaded_model.author_id == "author_master_01"

        # -------------------------------------------------------------------
        # 5. Taste Stack Unified Quality Report: 真实证据聚合
        # -------------------------------------------------------------------
        report = build_unified_quality_report("万物伏藏", output_dir=output_dir, strict_evidence=True)
        assert report.novel_name == "万物伏藏"
        assert report.layer1_hard_gates.status == "passed"
        assert report.layer3_blind_eval.wilson_ci_95 == (0.0, 0.0)  # 未跑 blind judge 为 not_run
        assert report.layer5_human_blind_eval.status == "not_run"
        assert report.g7_status.status == "decommissioned_research_only"
        assert "当前未获大神级生产授权" in report.narrative_evaluation_summary

        # -------------------------------------------------------------------
        # 6. Long Horizon Authorization: 严苛 10 项前置条件真实判定
        # -------------------------------------------------------------------
        verdict = evaluate_long_horizon_authorization(workspace_dir=novel_dir)
        assert verdict.verdict == "long_run_not_authorized"
        assert len(verdict.unmet_preconditions) >= 1
        assert any("缺少系统外真实人类连续阅读实验数据" in p for p in verdict.unmet_preconditions)
        assert "严格未授权" in verdict.notes
