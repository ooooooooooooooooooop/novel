"""P5 AuthorModel V3 动态决策先验、反例与跨作品验证测试.

覆盖：
1. 四层分离与 AuthorPrincipleV3 数据模型（支持样本、反例、边界、置信度动态校准）。
2. 从 Hindsight 回看结果动态回填反例 (update_author_model_from_hindsight) 与状态演化。
3. 决策先验评分 (score_author_prior) 对齐度计算（非硬门禁，作为 tie-break 信号）。
4. 跨作品留一验证 (L1WO) 与词汇泄漏检测。
"""

import pytest

from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CounterexampleSample,
    CrossWorkValidationResult,
    SupportingSample,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    RejectedRecord,
)
from src.object_state.structural_search import StructuralProposal
from src.workflow_action.authormodel_v3 import (
    score_author_prior,
    update_author_model_from_hindsight,
    validate_cross_work_separation,
)


class TestAuthorModelV3Principles:
    def test_principle_status_evolution(self):
        principle = AuthorPrincipleV3(
            principle_id="ap_causality_01",
            statement="宁可牺牲即时爽感也要保证人物因果自洽",
            value_vocab_key="character_causality_over_plot_convenience",
            scope="author_global",
        )
        assert principle.status == "candidate"

        # 增加支持样本
        principle.supporting_samples.append(
            SupportingSample(
                decision_id="dec_01",
                work_name="万物伏藏",
                chapter_number=3,
                context_summary="面临抉择",
                chosen_action="拒绝强行突破",
                tradeoff_rationale="坚持因果自洽",
            )
        )
        principle.update_status_from_evidence()
        assert principle.status == "weak"

        # 增加更多支持样本
        for i in range(2, 5):
            principle.supporting_samples.append(
                SupportingSample(
                    decision_id=f"dec_0{i}",
                    work_name="万物伏藏",
                    chapter_number=i + 2,
                    context_summary="持续坚持",
                    chosen_action="坚持自洽",
                    tradeoff_rationale="放弃便利",
                )
            )
        principle.update_status_from_evidence()
        assert principle.status == "stable"

        # 遭遇反例：Hindsight 回看发现过度压制导致剧情停滞
        principle.counterexamples.append(
            CounterexampleSample(
                decision_id="dec_05",
                work_name="万物伏藏",
                chapter_number=8,
                hindsight_status="partial_regret",
                observed_consequence="连续三章无实质推进，读者预期严重受挫",
                deviation_reason="过度克制，应在必要时刻给予释放",
            )
        )
        principle.update_status_from_evidence()
        assert principle.status == "contested"

    def test_update_author_model_from_hindsight(self):
        author_model = AuthorModelV3(
            author_id="author_x",
            author_name="测试作者",
        )
        choice = ChoiceRecord(
            decision_id="dec_100",
            decision_timestamp="2026-08-16T12:00:00Z",
            plot_context="主角面临执法堂审判",
            state_ref="state_ch5",
            chapter_number=5,
            candidates=[
                CandidateRecord(
                    candidate_id="cand_a",
                    summary="当众认罪换取免死",
                    plotunit={"goal": "自保"},
                    new_state_ref="state_ch5_a",
                ),
                CandidateRecord(
                    candidate_id="cand_b",
                    summary="据理力争承担受罚代价",
                    plotunit={"goal": "尊严"},
                    new_state_ref="state_ch5_b",
                ),
            ],
            selected_candidate="cand_b",
            rejected=[RejectedRecord(candidate_id="cand_a", reason="人物性格不会屈服")],
            tradeoff="放弃短期免责，换取道心自洽",
            value_conflicts=["character_causality_over_plot_convenience"],
            consequence="第七章主角因此获得宗门清流派长老暗中赏识，因果闭环",
            hindsight="still_supported",
            hindsight_note="长期因果收益兑现",
        )

        updated = update_author_model_from_hindsight(author_model, [choice], work_name="万物伏藏")
        assert updated == 1
        assert len(author_model.principles) == 1
        p = author_model.principles[0]
        assert p.value_vocab_key == "character_causality_over_plot_convenience"
        assert len(p.supporting_samples) == 1
        assert p.status == "weak"


class TestAuthorPriorScoring:
    def test_score_author_prior_alignment(self):
        principle = AuthorPrincipleV3(
            principle_id="ap_causality",
            statement="角色因果优先",
            value_vocab_key="character_causality_over_plot_convenience",
            confidence=0.8,
            status="stable",
        )
        author_model = AuthorModelV3(
            author_id="auth_01",
            principles=[principle],
        )

        # 吻合原则的方案（忠于人物、付出代价）
        aligned_prop = StructuralProposal(
            proposal_id="p_aligned",
            primary_actor="林尘",
            core_choice="人物因果优先，忠于人物内心情感选择正面应战",
            resistance_source="强敌",
            cost="身受重伤付出代价",
            state_change="道心稳固",
        )
        score_good = score_author_prior(aligned_prop, author_model)

        # 违背原则的方案（剧情便利、强行突变）
        contra_prop = StructuralProposal(
            proposal_id="p_contra",
            primary_actor="林尘",
            core_choice="剧情便利优先强行推进为剧情服务",
            resistance_source="无",
            cost="无",
            state_change="秒杀强敌",
        )
        score_bad = score_author_prior(contra_prop, author_model)

        assert score_good > 0.5
        assert score_bad < 0.5
        assert score_good > score_bad


class TestCrossWorkSeparation:
    def test_validate_cross_work_separation_and_leakage_detection(self):
        # 原则中意外包含了单作品专有名词（如 "天玄宗"）
        leaked_p = AuthorPrincipleV3(
            principle_id="p_leaked",
            statement="天玄宗弟子在面对长老时必须优先保存实力",
            value_vocab_key="character_causality_over_plot_convenience",
            scope="author_global",
            confidence=0.8,
            status="stable",
        )
        author_model = AuthorModelV3(
            author_id="auth_leaked",
            principles=[leaked_p],
        )

        choice_work_b = ChoiceRecord(
            decision_id="dec_b1",
            decision_timestamp="2026-08-16T12:00:00Z",
            plot_context="第二部作品情境",
            state_ref="state_b1",
            candidates=[
                CandidateRecord(
                    candidate_id="c1",
                    summary="人物因果优先忠于人物",
                    plotunit={},
                    new_state_ref="s1",
                ),
                CandidateRecord(
                    candidate_id="c2",
                    summary="剧情便利直接跳过",
                    plotunit={},
                    new_state_ref="s2",
                ),
            ],
            selected_candidate="c1",
            rejected=[RejectedRecord(candidate_id="c2", reason="便利不好")],
            tradeoff="自洽",
            value_conflicts=["character_causality_over_plot_convenience"],
        )

        works_records = {
            "万物伏藏": [],
            "星海纪元": [choice_work_b],
        }

        # 检查词汇泄漏（传入作品专有名词列表）
        res = validate_cross_work_separation(
            author_model,
            works_records,
            holdout_work="星海纪元",
            forbidden_work_entities=["天玄宗"],
        )

        assert res.lexical_leakage_detected is True
        assert "天玄宗" in res.leaked_terms
        assert res.is_valid_author_prior is False

    def test_author_model_v3_persistence_and_shadow_isolation(self, tmp_path):
        from src.workflow_action.authormodel_v3 import (
            load_author_model_v3,
            load_qualification_report,
            save_author_model_v3,
            save_qualification_report,
        )

        p = AuthorPrincipleV3(
            principle_id="ap_test",
            statement="始终坚持付出代价才能获得力量",
            value_vocab_key="character_causality_over_plot_convenience",
            confidence=0.85,
            status="stable",
        )
        model = AuthorModelV3(
            author_id="author_persisted",
            principles=[p],
            known_works=["作品A", "作品B"],
        )

        saved = save_author_model_v3(tmp_path, model)
        assert saved.exists()
        loaded = load_author_model_v3(tmp_path)
        assert loaded is not None
        assert loaded.author_id == "author_persisted"
        assert len(loaded.principles) == 1

        # 资格报告持久化
        qual = CrossWorkValidationResult(
            author_id="author_persisted",
            holdout_work="作品B",
            training_works=["作品A"],
            choice_prediction_accuracy=0.75,
            baseline_accuracy=0.5,
            lexical_leakage_detected=False,
            is_valid_author_prior=True,
        )
        q_saved = save_qualification_report(tmp_path, qual)
        assert q_saved.exists()
        q_loaded = load_qualification_report(tmp_path)
        assert q_loaded is not None
        assert q_loaded.is_valid_author_prior is True

