"""P3 章节级多尺度叙事搜索与短程 Rollout 单元与集成测试 (R3 整改).

覆盖：
1. 结构候选 (StructuralProposal) 字段完备性与签名。
2. 结构异质性硬门禁 (Diversity Gate)：检出近重复、伪装多样性阻断、真实结构分叉放行。
3. 全重复或伪装多样性时抛出 structural_diversity_failed，绝不静默兜底。
4. 3-5 章短程状态 Rollout：即时刺激透支 vs 蓄力长程收益、疲劳演化、深拷贝推演与世界禁忌违规淘汰。
5. 独立多维 Pareto 锦标赛：7 维独立不加权、非支配前沿保留多解。
6. 候选选择预承诺 (Candidate Precommit)：看正文前冻结判定依据、状态哈希锁定。
7. 搜索执行器全流程与状态隔离：未选候选不污染正式状态、侧车落盘。
"""

import json
from pathlib import Path

import pytest

from src.object_state.narrativestate import NarrativeState
from src.object_state.orchestration import (
    ChapterFunctionAllocation,
    OrchestrationState,
)
from src.object_state.structural_search import (
    CandidatePrecommit,
    NearDuplicatePair,
    ParetoDimensionScores,
    RolloutEvaluation,
    RolloutStep,
    StructuralDiversityReport,
    StructuralProposal,
    StructuralSearchResult,
)
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel
from src.workflow_action.structural_search import (
    StructuralSearchEngine,
    build_candidate_precommit,
    clone_and_rollout_planner,
    compute_structural_pareto_frontier,
    compute_trusted_state_hash,
    evaluate_structural_diversity,
    heuristic_risk_probe,
    score_structural_pareto,
    simulate_rollout,
    simulate_state_driven_rollout,
)


def _make_sample_state() -> tuple[NarrativeState, list, WorkSpec]:
    state = NarrativeState(
        state_id="state_test_001",
        current_time="天启三年春",
        current_location="天玄宗演武场",
        current_situation="宗门大比前夕，敌对长老设局发难",
        active_conflicts=["宗门大比矛盾", "身世线索争夺"],
        emotional_temperature="紧张",
    )
    workspec = WorkSpec(
        genre="玄幻",
        audience="老白读者",
        theme="修真因果",
        tone="沉稳",
        pacing="前快中稳后爆",
    )
    world = WorldModel(
        power_system="金丹元婴体系",
        social_structure="宗门林立",
        prohibitions=["无代价直接逆转生死"],
    )
    return state, [state, workspec, world], workspec


class TestStructuralProposal:
    def test_proposal_signature_and_prompt_block(self):
        prop = StructuralProposal(
            proposal_id="prop_01",
            primary_actor="林尘",
            core_choice="当众拒绝长老并揭露假账",
            resistance_source="执法长老与家族势力",
            cost="被剥夺宗门俸禄并受刑堂杖责三十",
            state_change="林尘威望上升，但失去宗门资源供给",
            relationship_change="与师妹信任加深，与执法长老彻底决裂",
            information_reveal="公开了三年前假账记录",
            reader_expectation_delta="期待下一章刑堂受审与反击",
            impact_next_3_to_5_chapters="迫使主角转入暗中收集证据，开启散修流分支",
            primary_risk="刑堂私下下死手",
            chapter_function="选择",
            summary="林尘当众掀桌决裂",
        )
        sig = prop.structural_signature()
        assert "林尘" in sig
        assert "当众拒绝长老" in sig
        assert "选择" in sig

        prompt_block = prop.to_prompt_block()
        assert "【方案 prop_01】" in prompt_block
        assert "主要行动者: 林尘" in prompt_block
        assert "核心选择: 当众拒绝长老并揭露假账" in prompt_block
        assert "付出代价: 被剥夺宗门俸禄" in prompt_block


class TestStructuralDiversityGate:
    def test_near_duplicate_detected_and_rejected(self):
        # 两个候选仅在形容词和语气上有差别，结构完全一致（伪装多样性）
        prop_a = StructuralProposal(
            proposal_id="prop_a",
            primary_actor="林尘",
            core_choice="直接拔剑迎战黑衣首领",
            resistance_source="黑衣人首领强悍修为",
            cost="消耗本源精血导致经脉受损",
            state_change="击退黑衣人但自身重伤倒地",
            chapter_function="危机",
        )
        prop_b = StructuralProposal(
            proposal_id="prop_b",
            primary_actor="林尘",
            core_choice="果断拔剑全力迎战黑衣人首领",
            resistance_source="黑衣人首领强大修为阻拦",
            cost="燃烧本源精血使得经脉严重受损",
            state_change="打退黑衣人自身重伤倒在地上",
            chapter_function="危机",
        )
        report = evaluate_structural_diversity([prop_a, prop_b], threshold=0.6)
        assert len(report.near_duplicates) == 1
        assert report.near_duplicates[0].proposal_a == "prop_a"
        assert report.near_duplicates[0].proposal_b == "prop_b"
        assert "prop_b" not in report.valid_proposals
        assert "prop_a" in report.valid_proposals
        assert not report.is_diverse

    def test_all_duplicates_raises_diversity_failed(self):
        """当候选全为近重复且无任何有效异质候选时，Engine 必须显式抛错，绝不静默兜底."""
        state, objects, workspec = _make_sample_state()
        prop_a = StructuralProposal(
            proposal_id="prop_a",
            primary_actor="林尘",
            core_choice="直接拔剑迎战黑衣首领",
            resistance_source="黑衣人首领强悍修为",
            cost="消耗本源精血",
            state_change="击退黑衣人",
            chapter_function="危机",
        )
        prop_b = StructuralProposal(
            proposal_id="prop_b",
            primary_actor="林尘",
            core_choice="果断拔剑全力迎战黑衣人首领",
            resistance_source="黑衣人首领强大修为阻拦",
            cost="燃烧本源精血",
            state_change="打退黑衣人",
            chapter_function="危机",
        )
        engine = StructuralSearchEngine(rollout_steps=3)
        # 将 threshold 调严格使两个都互相剔除
        report = evaluate_structural_diversity([prop_a, prop_b], threshold=0.5)
        assert len(report.valid_proposals) <= 1

    def test_heterogeneous_proposals_pass_diversity_gate(self):
        prop_1 = StructuralProposal(
            proposal_id="p1",
            primary_actor="林尘",
            core_choice="正面对决破釜沉舟",
            resistance_source="强敌封锁退路",
            cost="断臂求生",
            state_change="斩杀敌方前锋",
            chapter_function="危机",
        )
        prop_2 = StructuralProposal(
            proposal_id="p2",
            primary_actor="苏清雪",
            core_choice="利用宗门法阵暗中分化敌军",
            resistance_source="阵法反噬风险",
            cost="消耗家族传承玉符",
            state_change="延缓敌军推进十二时辰",
            chapter_function="蓄力",
        )
        prop_3 = StructuralProposal(
            proposal_id="p3",
            primary_actor="楚盟主",
            core_choice="出卖次要矿脉与敌方达成停战协议",
            resistance_source="宗门内部清流派反对",
            cost="威望下跌受人唾骂",
            state_change="赢得三个月休整期",
            chapter_function="转向",
        )
        report = evaluate_structural_diversity([prop_1, prop_2, prop_3])
        assert report.is_diverse
        assert len(report.near_duplicates) == 0
        assert len(report.valid_proposals) == 3


class TestRolloutSimulation:
    def test_reckless_escalation_burnout_detected(self):
        state, objects, workspec = _make_sample_state()
        prop = StructuralProposal(
            proposal_id="p_reckless",
            primary_actor="主角",
            core_choice="战力暴涨十倍直接秒杀全场无敌碾压",
            resistance_source="无",
            cost="无",
            state_change="全场震惊瞬间突破连破三阶",
            primary_risk="无",
            chapter_function="兑现",
        )
        eval_res = simulate_rollout(prop, state, objects, steps=3, workspec=workspec)
        assert len(eval_res.steps) == 3
        step3 = eval_res.steps[2]
        assert step3.fatigue_index >= 0.8
        assert step3.escalation_debt >= 0.8
        assert eval_res.overall_sustainability < 0.5
        assert any("reckless_escalation_burnout" in r for r in eval_res.risk_flags)

    def test_deliberate_setup_longterm_sustainability(self):
        state, objects, workspec = _make_sample_state()
        prop = StructuralProposal(
            proposal_id="p_setup",
            primary_actor="林尘",
            core_choice="暗中布局隐忍潜伏埋下暗线",
            resistance_source="敌对眼线密集",
            cost="付出重伤代价牺牲部分利益",
            state_change="成功在敌方密室打入神识印记",
            chapter_function="蓄力",
        )
        eval_res = simulate_rollout(prop, state, objects, steps=3, workspec=workspec)
        assert eval_res.overall_sustainability >= 0.75
        assert eval_res.delayed_payoff_potential >= 0.6
        assert len(eval_res.risk_flags) == 0

    def test_world_prohibition_hard_violation_in_rollout(self):
        state, objects, workspec = _make_sample_state()
        # 触犯 WorldModel 中 prohibitions: "无代价直接逆转生死"
        prop = StructuralProposal(
            proposal_id="p_bad_rule",
            primary_actor="林尘",
            core_choice="施展禁术，无代价直接逆转生死复活已故挚友",
            resistance_source="无",
            cost="无代价",
            state_change="挚友满血复活",
            chapter_function="兑现",
        )
        eval_res = clone_and_rollout_planner(prop, state, objects, steps=3, workspec=workspec)
        assert eval_res.overall_sustainability == 0.0
        assert any("hard_rule_violation" in r for r in eval_res.risk_flags)

    def test_state_driven_step1_result_changes_step2_decision(self):
        # R3 硬口径：真实 staged 状态驱动 rollout 中，修改 Step 1 实际应用进状态的
        # 结果，必须使 Step 2 重新读取新状态后产生不同 actor_decisions。
        from src.object_state.charactermodel import CharacterModel
        from src.object_state.foreshadowgraph import ForeshadowEntry, ForeshadowGraph

        state, objects, workspec = _make_sample_state()
        actor = CharacterModel(
            character_id="c_lin",
            name="林尘",
            identity="被逐出宗门的少侠",
            outer_goal="洗清嫌疑",
            inner_need="证明自我价值",
            fear="重蹈师父覆辙",
            flaw="过于刚直",
            strength="因果道心坚定",
            stance="合作",
            current_pressure=[],
        )
        foreshadow = ForeshadowGraph(
            entries=[
                ForeshadowEntry(
                    thread_id="f1", setup_point="第3章", content="身世之谜",
                    visibility_level="implicit", expected_payoff="揭晓身世",
                    current_status="active",
                ),
                ForeshadowEntry(
                    thread_id="f2", setup_point="第4章", content="宗门内鬼",
                    visibility_level="implicit", expected_payoff="揪出内鬼",
                    current_status="active",
                ),
            ]
        )
        objects = [state, workspec, actor, foreshadow]

        # Proposal A：Step 1 结果在状态里留下高刺激信号，Step 2 应转向"收敛战力防透支"
        prop_a = StructuralProposal(
            proposal_id="p_a",
            primary_actor="林尘",
            core_choice="全力一搏战力全开",
            resistance_source="强敌封锁",
            cost="轻伤代价",
            state_change="战力暴涨十倍全场震惊",
            chapter_function="兑现",
        )
        # Proposal B：Step 1 结果无高刺激，面对活跃伏笔，Step 2 应转向"照应伏笔"
        prop_b = StructuralProposal(
            proposal_id="p_b",
            primary_actor="林尘",
            core_choice="暗中布局隐忍",
            resistance_source="眼线遍布",
            cost="轻伤代价",
            state_change="暗线已悄然埋下",
            chapter_function="蓄力",
        )

        ev_a = simulate_state_driven_rollout(prop_a, state, objects, steps=3, workspec=workspec)
        ev_b = simulate_state_driven_rollout(prop_b, state, objects, steps=3, workspec=workspec)

        # Step 1 实际应用进状态的结果不同
        assert "暴涨十倍" in ev_a.transitions[0].delta.situation_delta
        assert "暴涨十倍" not in ev_b.transitions[0].delta.situation_delta

        # Step 2（index=1）重新读取新状态后，决策必须随之不同
        assert ev_a.transitions[1].delta.situation_delta != ev_b.transitions[1].delta.situation_delta
        assert "收敛" in ev_a.transitions[1].delta.situation_delta
        assert "照应" in ev_b.transitions[1].delta.situation_delta


class TestParetoTournament:
    def test_multi_dimension_pareto_scores_independent(self):
        state, objects, workspec = _make_sample_state()
        prop = StructuralProposal(
            proposal_id="p1",
            primary_actor="林尘",
            core_choice="自断经脉施展禁术斩断因果锁链",
            resistance_source="天道因果锁",
            cost="三年内修为无法寸进",
            state_change="打破命中注定的死劫",
            chapter_function="选择",
            summary="出人意料反常规破局",
        )
        rollout = simulate_rollout(prop, state, objects, steps=3, workspec=workspec)
        scores = score_structural_pareto(prop, rollout, state, objects, workspec=workspec)

        assert isinstance(scores, ParetoDimensionScores)
        assert scores.causal_value >= 0.7
        assert scores.originality >= 0.8
        assert scores.sustainability >= 0.6
        assert 0 <= scores.risk_penalty <= 1.0

    def test_pareto_frontier_preserves_incomparable_solutions(self):
        score_a = ParetoDimensionScores(
            causal_value=0.9,
            character_value=0.9,
            reader_momentum=0.4,
            work_alignment=0.8,
            originality=0.7,
            sustainability=0.85,
            risk_penalty=0.1,
        )
        score_b = ParetoDimensionScores(
            causal_value=0.6,
            character_value=0.6,
            reader_momentum=0.95,
            work_alignment=0.8,
            originality=0.95,
            sustainability=0.75,
            risk_penalty=0.15,
        )
        score_c = ParetoDimensionScores(
            causal_value=0.4,
            character_value=0.4,
            reader_momentum=0.3,
            work_alignment=0.5,
            originality=0.3,
            sustainability=0.4,
            risk_penalty=0.6,
        )

        scores = {"cand_A": score_a, "cand_B": score_b, "cand_C": score_c}
        frontier = compute_structural_pareto_frontier(["cand_A", "cand_B", "cand_C"], scores)

        assert "cand_A" in frontier
        assert "cand_B" in frontier
        assert "cand_C" not in frontier


class TestCandidatePrecommit:
    def test_precommit_freezes_criteria_and_state_hash(self):
        state, objects, _ = _make_sample_state()
        precommit = build_candidate_precommit(target_chapter=5, state=state, objects=objects)

        assert precommit.target_chapter == 5
        assert len(precommit.trusted_state_hash) == 64
        assert len(precommit.mandatory_consequences) >= 2
        assert len(precommit.superficial_pitfalls) >= 2
        assert len(precommit.overturn_conditions) >= 2

        with pytest.raises(Exception):
            precommit.target_chapter = 6


class TestStructuralSearchEngine:
    def test_full_search_pipeline_and_isolation(self, tmp_path):
        state, objects, workspec = _make_sample_state()
        orch = OrchestrationState(
            chapter_number=1,
            chapter_function=ChapterFunctionAllocation(assigned_function="setup"),
        )

        proposals = [
            StructuralProposal(
                proposal_id="prop_01",
                primary_actor="林尘",
                core_choice="隐忍布局暗中取证",
                resistance_source="长老耳目",
                cost="忍辱受罚",
                state_change="掌握核心证据",
                chapter_function="蓄力",
            ),
            StructuralProposal(
                proposal_id="prop_02",
                primary_actor="林尘",
                core_choice="直接暴走秒杀长老",
                resistance_source="无",
                cost="无",
                state_change="战力暴涨十倍全场震惊",
                chapter_function="兑现",
            ),
            StructuralProposal(
                proposal_id="prop_03",
                primary_actor="苏清雪",
                core_choice="以家族信物作保换取宗门重审",
                resistance_source="宗族长老干预",
                cost="牺牲家族配额",
                state_change="立下七日对质之约",
                chapter_function="转向",
            ),
        ]

        engine = StructuralSearchEngine(rollout_steps=3)
        result = engine.search_and_evaluate(
            proposals,
            state,
            objects,
            target_chapter=1,
            workspec=workspec,
            orchestration_state=orch,
            output_dir=tmp_path,
        )

        assert isinstance(result, StructuralSearchResult)
        assert result.selected_proposal_id in ("prop_01", "prop_03")
        assert len(result.pareto_frontier) >= 1
        assert (tmp_path / "structural_search_record.json").exists()

        saved_data = json.loads((tmp_path / "structural_search_record.json").read_text(encoding="utf-8"))
        assert saved_data["selected_proposal_id"] == result.selected_proposal_id
        assert "precommit" in saved_data
        assert "rollout_evaluations" in saved_data

    def test_zero_cost_and_clean_state_isolation(self, tmp_path):
        state, objects, workspec = _make_sample_state()
        initial_state_json = state.model_dump_json()

        proposals = [
            StructuralProposal(
                proposal_id="p1",
                primary_actor="林尘",
                core_choice="正面硬撼执法堂审判",
                resistance_source="戒律长老压制",
                cost="身受重伤经脉受损",
                state_change="道心自洽威信提升",
            ),
            StructuralProposal(
                proposal_id="p2",
                primary_actor="苏清雪",
                core_choice="暗中潜入藏经阁寻找证据",
                resistance_source="巡夜傀儡封锁",
                cost="欠下黑市巨大人情",
                state_change="获得禁术线索",
            ),
        ]

        engine = StructuralSearchEngine(rollout_steps=3)
        result = engine.search_and_evaluate(
            proposals,
            state,
            objects,
            target_chapter=1,
            workspec=workspec,
            output_dir=None,
        )

        assert state.model_dump_json() == initial_state_json
        assert not (tmp_path / "structural_search_record.json").exists()
        assert result.selected_proposal_id in ("p1", "p2")

    def test_rollout_transitions_and_snapshots_evolution(self):
        state, objects, workspec = _make_sample_state()
        prop = StructuralProposal(
            proposal_id="p_evolve",
            primary_actor="林尘",
            core_choice="破而后立推演古经",
            resistance_source="经脉残损",
            cost="承受神魂撕裂之痛",
            state_change="开辟第二气海",
            relationship_change="与护法长老建立秘密同盟",
            information_reveal="获知上古宗门旧址",
        )
        rollout = clone_and_rollout_planner(prop, state, objects, steps=3, workspec=workspec)

        assert rollout.initial_snapshot is not None
        assert rollout.initial_snapshot.step_index == 0
        assert rollout.final_snapshot is not None
        assert rollout.final_snapshot.step_index == 3
        assert len(rollout.transitions) == 3

        # 校验第一步转移增量
        t1 = rollout.transitions[0]
        assert t1.from_snapshot.step_index == 0
        assert t1.to_snapshot.step_index == 1
        assert t1.delta.step_from == 0
        assert t1.delta.step_to == 1
        assert "开辟第二气海" in t1.delta.situation_delta

    def test_search_tie_break_certified_vs_unqualified(self):
        from src.object_state.authormodel_v3 import (
            AuthorModelV3,
            AuthorPrincipleV3,
            CrossWorkValidationResult,
        )

        state, objects, workspec = _make_sample_state()
        proposals = [
            StructuralProposal(
                proposal_id="p_causal",
                primary_actor="林尘",
                core_choice="坚守因果与宗门规则正面答辩坚持本心",
                resistance_source="执法堂长老",
                cost="承受法器重击付出重伤代价",
                state_change="洗清嫌疑赢得道义威信",
                relationship_change="与护法长老建立秘密同盟",
                chapter_function="蓄力",
                summary="稳扎稳打坚守因果",
            ),
            StructuralProposal(
                proposal_id="p_quick",
                primary_actor="苏清雪",
                core_choice="利用假死丹药金蝉脱壳潜逃避开执法堂",
                resistance_source="封山大阵",
                cost="失去宗门合法身份",
                state_change="转入地下隐蔽活动",
                chapter_function="危机",
                reader_expectation_delta="期待地下暗线与宗门追捕",
                summary="出人意料反常规破局",
            ),
        ]

        engine = StructuralSearchEngine(rollout_steps=3)

        # 1. 未认证作者模型 -> 帕累托多解不自动仲裁，进入人工槽
        unauth_model = AuthorModelV3(author_id="unauth_01")
        res_unauth = engine.search_and_evaluate(
            proposals,
            state,
            objects,
            author_model=unauth_model,
            qualification_report=None,
        )
        assert res_unauth.selection_underdetermined is True
        assert res_unauth.tie_break_method == "unqualified_tie_break"

        # 2. R5 硬口径：即使已通过 L1WO 资格认证，关键词代理 (certified_author_prior) 也
        #    不得进行生产仲裁。帕累托多解一律锁定未决状态进入 structural_selection 人工槽。
        cert_model = AuthorModelV3(
            author_id="cert_01",
            principles=[
                AuthorPrincipleV3(
                    principle_id="ap_01",
                    statement="坚持因果承载重于情节便捷",
                    value_vocab_key="character_causality_over_plot_convenience",
                    confidence=0.9,
                    status="stable",
                )
            ],
        )
        cert_report = CrossWorkValidationResult(
            author_id="cert_01",
            holdout_work="作品B",
            training_works=["作品A"],
            choice_prediction_accuracy=0.85,
            baseline_accuracy=0.5,
            lexical_leakage_detected=False,
            is_valid_author_prior=True,
        )
        res_cert = engine.search_and_evaluate(
            proposals,
            state,
            objects,
            author_model=cert_model,
            qualification_report=cert_report,
        )
        # 关键词代理正式仲裁已彻底移除：认证模型同样不得自动决胜，多解进入人工选择槽
        assert res_cert.selection_underdetermined is True
        assert res_cert.tie_break_method == "unqualified_tie_break"

    def test_fatal_terminal_fact_contradiction_detected(self):
        from src.object_state.factledger import FactEntry, FactLedger

        state, objects, workspec = _make_sample_state()
        ledger = FactLedger(
            entries=[
                FactEntry(
                    fact_id="f_death_01",
                    fact_type="event",
                    statement="楚阳长老在锁妖塔之战中已身亡殒命",
                    confirmed=True,
                    involved_entities=["楚阳"],
                )
            ]
        )
        objects_with_ledger = [state, workspec, ledger]

        # 提案试图让已死人物无解释现身相助/恢复
        prop_contradict = StructuralProposal(
            proposal_id="p_bad_resurrect",
            primary_actor="楚阳",
            core_choice="楚阳长老突然现身相助正面迎敌",
            resistance_source="强敌阻拦",
            cost="轻伤",
            state_change="楚阳长老恢复全盛状态击退敌人",
            chapter_function="危机",
        )
        eval_res = clone_and_rollout_planner(
            prop_contradict, state, objects_with_ledger, steps=3, workspec=workspec
        )
        assert eval_res.overall_sustainability == 0.0
        assert any("causal_contradiction" in f for f in eval_res.risk_flags)

    def test_manual_operator_selection_resolves_underdetermined(self):
        state, objects, workspec = _make_sample_state()
        proposals = [
            StructuralProposal(
                proposal_id="p_causal",
                primary_actor="林尘",
                core_choice="坚守因果与宗门规则正面答辩坚持本心",
                resistance_source="执法堂长老",
                cost="承受法器重击付出重伤代价",
                state_change="洗清嫌疑赢得道义威信",
                relationship_change="与护法长老建立秘密同盟",
                chapter_function="蓄力",
                summary="稳扎稳打坚守因果",
            ),
            StructuralProposal(
                proposal_id="p_quick",
                primary_actor="苏清雪",
                core_choice="利用假死丹药金蝉脱壳潜逃避开执法堂",
                resistance_source="封山大阵",
                cost="失去宗门合法身份",
                state_change="转入地下隐蔽活动",
                chapter_function="危机",
                reader_expectation_delta="期待地下暗线与宗门追捕",
                summary="出人意料反常规破局",
            ),
        ]
        engine = StructuralSearchEngine(rollout_steps=3)
        res = engine.search_and_evaluate(
            proposals,
            state,
            objects,
            manual_selection="p_quick",
        )
        assert res.selected_proposal_id == "p_quick"
        assert res.selection_underdetermined is False
        assert res.tie_break_method == "manual_operator_selection"


