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
    DecisionEventV2,
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
    validate_decision_signature_v2,
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


# ---------------------------------------------------------------------------
# Decision Signature v2 对抗性门禁测试
# ---------------------------------------------------------------------------


def _v2_event(author, work, topic, stage, selected="a", *, anchor=None, candidates=None):
    """构造最小结构化出版文本决策事件；只使用中性测试标识。"""
    candidates = candidates or ["a", "b"]
    return DecisionEventV2(
        author_id=author,
        work_slot=work,
        stage=stage,
        topic_tag=topic,
        actor_role="protagonist",
        power_gap=1,
        reversibility=0,
        threat=1,
        dependence=0,
        info_uncertainty=1,
        loyalty_conflict=0,
        candidates=candidates,
        selected=selected,
        rejected=[candidate for candidate in candidates if candidate != selected],
        cost_label="cost",
        protected_value_key="character_causality_over_plot_convenience",
        evidence_anchor=anchor or f"anchor-{author}-{work}-{stage}",
        confidence=0.95,
    )


def _v2_minimal_events():
    """构造两个交叉题材、两个作者、每作者三个作品槽位的合法小样本。"""
    events = []
    for author, action in (("author-a", "a"), ("author-b", "b")):
        for work_index in range(3):
            work = f"work-{author[-1]}-{work_index}"
            for topic in ("topic-1", "topic-2"):
                for stage in ("setup", "payoff"):
                    events.append(
                        _v2_event(
                            author,
                            work,
                            topic,
                            stage,
                            selected=action,
                            anchor=f"{author}-{work}-{topic}-{stage}",
                        )
                    )
    return events


def test_v2_holdout_leakage_is_not_pass():
    events = _v2_minimal_events()
    events[-1].evidence_anchor = "training_stats:pooled"
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"
    assert result.holdout_leakage_detected is True


def test_v2_topic_alias_is_not_pass():
    events = []
    for author in ("author-a", "author-b"):
        for index in range(3):
            for stage in ("setup", "payoff"):
                events.append(_v2_event(author, f"work-{author}-{index}", author, stage, anchor=f"{author}-{index}-{stage}"))
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"
    assert result.topic_alias_detected is True


def test_v2_candidate_first_bias_is_not_pass():
    events = _v2_minimal_events()
    for index, event in enumerate(events):
        if index % 2 == 0:
            event.candidates = ["a", "b"]
        else:
            event.candidates = ["b", "a"]
        event.selected = event.candidates[0]
        event.rejected = [event.candidates[1]]
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"


def test_v2_no_author_advantage_is_not_pass():
    events = _v2_minimal_events()
    for event in events:
        event.selected = "a"
        event.rejected = ["b"]
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"
    assert result.author_advantage <= 0


def test_v2_empty_or_invalid_input_never_returns_neutral_half():
    empty = validate_decision_signature_v2([])
    invalid = validate_decision_signature_v2([{"author_id": "author-a"}])
    assert empty.state == "INVALID"
    assert invalid.state == "INVALID"
    assert empty.author_accuracy != 0.5
    assert empty.baselines == {}


def test_v2_missing_hard_negative_is_degraded():
    events = [_v2_event("author-a", f"work-a-{i}", "topic-a", "setup", anchor=f"a-{i}") for i in range(3)]
    events.extend(_v2_event("author-b", f"work-b-{i}", "topic-b", "payoff", selected="b", anchor=f"b-{i}") for i in range(3))
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"
    assert any("题材" in warning or "困难" in warning for warning in result.invalid_reasons + result.warnings)


def test_v2_silent_fold_drop_is_reported():
    events = _v2_minimal_events()
    events.append(_v2_event("author-a", "work-a-extra", "topic-1", "setup", anchor="extra-a"))
    result = validate_decision_signature_v2(events)
    assert result.state != "PASS"
    assert result.fold_count == result.expected_fold_count or result.invalid_reasons


def test_v2_low_confidence_is_invalid():
    events = _v2_minimal_events()
    events[0].confidence = 0.84
    result = validate_decision_signature_v2(events)
    assert result.state == "INVALID"
    assert any("置信度" in reason for reason in result.invalid_reasons)


def test_v2_legal_small_sample_passes():
    result = validate_decision_signature_v2(_v2_minimal_events())
    assert result.state == "PASS", result.invalid_reasons + result.warnings
    assert result.author_advantage > 0
    assert result.hard_negative_advantage > 0
    assert result.confidence_interval_lower > 0


# ---------------------------------------------------------------------------
# Decision Signature v8 双平面与选择性覆盖测试
# ---------------------------------------------------------------------------


def _v8_events_with_unseen_holdouts():
    events = []
    for author, action in (("author-a", "a"), ("author-b", "b")):
        for work_index in range(3):
            work = f"collection20-{author[-1]}{work_index:03d}"
            for topic in ("topic-urban", "topic-fantasy"):
                for stage in ("setup", "payoff"):
                    event = _v2_event(
                        author, work, topic, stage, selected=action,
                        anchor=f"{author}-{work}-{topic}-{stage}",
                    )
                    if work_index == 2 and stage == "payoff":
                        event.stage = "unseen-stage"
                    events.append(event)
    return events


def test_v8_dual_plane_statistical_pass_full_coverage_fail():
    result = validate_decision_signature_v2(_v8_events_with_unseen_holdouts())
    assert result.statistical_state in {"PASS", "PARTIAL"}
    assert result.statistical_state != "INVALID"
    assert result.full_coverage_deployment_state == "FAIL"
    assert result.coverage < 1.0


def test_v8_full_coverage_pass_requires_zero_abstention():
    result = validate_decision_signature_v2(_v8_events_with_unseen_holdouts())
    assert result.abstention_count > 0
    assert result.full_coverage_deployment_state == "FAIL"


def test_v8_backoff_family_reduces_abstention():
    events = _v8_events_with_unseen_holdouts()
    none_result = validate_decision_signature_v2(events, backoff="none")
    family_result = validate_decision_signature_v2(events, backoff="family")
    assert family_result.abstention_count < none_result.abstention_count
    assert family_result.backoff_used == "family"


def test_v8_backoff_partial_pool_further_reduces():
    events = _v8_events_with_unseen_holdouts()
    family_result = validate_decision_signature_v2(events, backoff="family")
    pooled_result = validate_decision_signature_v2(events, backoff="partial_pool")
    assert pooled_result.abstention_count <= family_result.abstention_count
    assert pooled_result.backoff_used == "partial_pool"


def test_v8_backoff_never_reads_holdout():
    events = _v8_events_with_unseen_holdouts()
    holdout_labels = {event.selected for event in events if event.stage == "unseen-stage"}
    result = validate_decision_signature_v2(events, backoff="partial_pool")
    assert result.holdout_leakage_detected is False
    assert holdout_labels == {"a", "b"}
    assert not any("holdout" in reason.lower() for reason in result.invalid_reasons)


def test_v8_coverage_and_selective_risk_reported():
    events = _v8_events_with_unseen_holdouts()
    result = validate_decision_signature_v2(events, backoff="none")
    answered = result.evaluated_event_count - result.abstention_count
    assert result.coverage == pytest.approx(answered / result.evaluated_event_count)
    assert result.selective_risk is not None
    assert 0.0 <= result.selective_risk <= 1.0
    assert result.aurc is not None


def test_v8_c_at_1_formula():
    result = validate_decision_signature_v2(_v8_events_with_unseen_holdouts(), backoff="none")
    n = result.evaluated_event_count
    u = result.abstention_count
    correct = round((1.0 - (result.selective_risk or 0.0)) * (n - u))
    expected = (correct + u * correct / n) / n
    assert result.c_at_1 == pytest.approx(expected)
    assert result.f_half_u is not None


def test_v8_operating_coverage_enforced():
    result = validate_decision_signature_v2(
        _v8_events_with_unseen_holdouts(),
        backoff="none",
        operating_coverage=1.0,
    )
    assert result.operating_coverage == 1.0
    assert result.coverage < result.operating_coverage
    assert result.statistical_state in {"FAIL", "PARTIAL"}

