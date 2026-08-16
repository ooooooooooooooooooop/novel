"""AutoCalibrate 测试（design §10 / T7.4–T7.6）.

偏好基准载入 + calibration/holdout 严格分离 + 阈值冻结（唯一来源=calibration）
+ holdout 只读验证（禁止据 holdout 调参）.
"""

import json
from pathlib import Path

import pytest

from src.object_state.autonomous import AutonomousPolicy
from src.object_state.qualitythresholds import (
    AccuracyReport,
    PreferencePair,
    QualityThresholds,
)
from src.workflow_action.auto_calibrate import (
    MIN_CALIBRATION_PROMPT_IDS,
    MIN_CALIBRATION_TAGS,
    _stratified_position_sample,
    build_preference_judge_prompt,
    compute_accuracy,
    freeze_quality_thresholds,
    load_frozen_preference_bench,
    measure_position_consistency,
    parse_preference_response,
    run_holdout,
    run_preference_judge,
)
from src.workflow_action.preference_review import ReviewQualityExhaustedError

# 【split 事实纠正 2026-08-14】以下 _SPLIT/_SPLIT_SHA 是**污染划分**
# split_manifest.json/20864f82（165 cal/43 holdout，被 A1 早期调参），本测试冻结的阈值
# 基于该污染数据——只读保留为历史冻结证据并**视为失效**；不得在 v2 划分（split_manifest_v2.json/
# c45cd6ad，103 cal/35 holdout）上沿用。G7 阈值需在 v2 重冻结（任务 #11）。
_BENCH = (
    "reference_texts/a1_benchmark/sources/writing_preference_bench/"
    "WP_bench_chinese.json"
)
_SPLIT = (
    "reference_texts/a1_benchmark/sources/writing_preference_bench/"
    "split_manifest.json"
)
_BENCH_SHA = "fd9c8faf85b7f4ae4b48f938c9fd608e5ed2011f726789130b37c1588f2ab6e0"
_SPLIT_SHA = "20864f824a91acfd406ee2cf72ecceb576141900b1b9ef4cffed79fbcc6bd560"


def _policy() -> AutonomousPolicy:
    return AutonomousPolicy.model_validate(
        {
            "schema_version": "1.0",
            "policy_id": "policy-a1-canary",
            "provider_profile_id": "provider-a",
            "runtime": {
                "manual_allowed": False,
                "waiting_allowed": False,
                "provider_fallback_allowed": False,
                "network_retry_allowed": False,
                "max_provider_attempts_per_call": 1,
                "resume_may_skip_gate": False,
            },
            "search": {
                "premise_candidates": 4,
                "plot_candidates": 4,
                "prose_variants_per_plot": 2,
                "max_decision_rounds": 2,
                "pairwise_orderings": ["A/B", "B/A"],
                "judge_roles": ["fact_judge", "character_judge", "reader_judge"],
            },
            "chapter": {
                "target_chinese_characters_min": 2500,
                "target_chinese_characters_max": 5000,
                "planner_max_output_tokens": 2000,
                "prose_max_output_tokens": 6000,
                "judge_max_output_tokens": 1500,
            },
            "budget": {
                "max_total_calls": 2500,
                "max_total_input_tokens": 30_000_000,
                "max_total_output_tokens": 15_000_000,
                "max_total_cost_usd": 10,
                "max_wall_clock_seconds": 86_400,
                "max_chapters_per_run": 30,
                "max_canary_runs": 3,
                "max_canary_chapters_total": 90,
            },
            "evaluation": {
                "holdout_overall_accuracy_min": 0.65,
                "holdout_genre_accuracy_min": 0.5,
                "pairwise_position_consistency_min": 0.9,
                "hard_fact_conflicts_allowed": 0,
                "manual_routes_allowed": 0,
                "unarmed_required_axes_allowed": 0,
            },
            "benchmarks": {
                "preference_source": "WP_bench_chinese.json",
                "preference_source_sha256": _BENCH_SHA,
                "preference_split_manifest": "split_manifest.json",
                "preference_split_manifest_sha256": _SPLIT_SHA,
                "human_distribution_manifest": "human.json",
                "human_distribution_manifest_sha256": "c" * 64,
            },
            "canary": {
                "genres": ["悬疑", "仙侠", "古装"],
                "chapters_per_genre": 30,
                "long_horizon_checkpoints": [1, 3, 5, 10, 20, 30],
            },
        }
    )


def _pair(prompt_id="p-001", tag="悬疑-推理故事", split="calibration",
          chosen="甲文", rejected="乙文") -> PreferencePair:
    return PreferencePair(
        prompt_id=prompt_id,
        tag=tag,
        prompt="写一个故事",
        chosen=chosen,
        rejected=rejected,
        split=split,
        bucket=0,
    )


# ---------------------------------------------------------------------------
# 基准载入与划分（严格分离）
# ---------------------------------------------------------------------------

def test_load_frozen_bench_splits_and_disjoint_prompt_ids():
    # 冻结证据（gitignored 污染划分 split_manifest.json，20864f82）在克隆机上可能
    # 不存在——该文件从未入库、原始字节已随历史重写丢失且不可恢复。无证据无法做
    # 字节校验，诚实跳过而非失败；证据存在（作者机）时仍全量验证。
    if not Path(_SPLIT).is_file():
        pytest.skip("frozen polluted split evidence absent (split_manifest.json not present on this clone)")
    calibration, holdout = load_frozen_preference_bench(
        _BENCH, _SPLIT,
        expected_source_sha256=_BENCH_SHA,
        expected_split_sha256=_SPLIT_SHA,
    )
    assert len(calibration) == 165
    assert len(holdout) == 43
    calib_ids = {p.prompt_id for p in calibration}
    holdout_ids = {p.prompt_id for p in holdout}
    assert not (calib_ids & holdout_ids)  # prompt_id 零交叉
    assert all(p.split == "calibration" for p in calibration)
    assert all(p.split == "holdout" for p in holdout)


def test_load_frozen_bench_rejects_sha256_mismatch():
    with pytest.raises(ValueError, match="SHA-256"):
        load_frozen_preference_bench(
            _BENCH, _SPLIT,
            expected_source_sha256="f" * 64,
            expected_split_sha256=_SPLIT_SHA,
        )


# ---------------------------------------------------------------------------
# 匿名偏好评审 prompt 与解析
# ---------------------------------------------------------------------------

def test_build_preference_prompt_is_anonymous_and_strict():
    prompt = build_preference_judge_prompt(
        "写一个故事", "甲", "乙", role="reader_judge"
    )
    assert "候选甲" in prompt and "候选乙" in prompt
    assert '"preferred": "A"' in prompt  # JSON 规范
    assert "不要猜测" in prompt  # 身份保密约束


def test_parse_preference_response_accepts_A_B_no_difference():
    assert parse_preference_response('{"preferred": "A", "rationale": "好"}', "p") == "A"
    assert parse_preference_response('{"preferred": "B", "rationale": "差"}', "p") == "B"
    assert (
        parse_preference_response(
            '{"preferred": "no_difference", "rationale": "难分"}', "p"
        )
        == "no_difference"
    )


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"preferred": "C", "rationale": "x"}',
        '{"rationale": "x"}',              # 缺 preferred
        '{"preferred": "A"}',              # 缺 rationale
        '{"preferred": "A", "rationale": ""}',
        '{"preferred": "A", "rationale": "x", "extra": 1}',
    ],
)
def test_parse_preference_response_rejects_bad_shapes(text):
    with pytest.raises(ValueError):
        parse_preference_response(text, "p")


# ---------------------------------------------------------------------------
# 预测 + 准确率
# ---------------------------------------------------------------------------

def _perfect_judge(pair, role):
    return "A"  # 永远选甲 = 选 chosen（正确）


def _stable_correct_judge(pair, role):
    # 恒偏好「甲文」这份内容且甲文恰是 chosen → 既正确又换位稳定
    return "A" if pair.chosen == "甲文" else "B"


def _reverse_judge(pair, role):
    return "B"


def _abstain_judge(pair, role):
    return "no_difference"


def test_run_preference_judge_labels_correctness():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2", split="holdout")]
    predictions = run_preference_judge(pairs, "reader_judge", _perfect_judge)
    assert [p.correct for p in predictions] == [True, True]
    assert all(p.human_label == "chosen" for p in predictions)
    reverse = run_preference_judge(pairs, "reader_judge", _reverse_judge)
    assert [p.correct for p in reverse] == [False, False]
    abstain = run_preference_judge(pairs, "reader_judge", _abstain_judge)
    assert [p.correct for p in abstain] == [False, False]


def test_compute_accuracy_overall_and_per_tag():
    pairs = [
        _pair(prompt_id="p-1", tag="悬疑-推理故事"),
        _pair(prompt_id="p-2", tag="悬疑-推理故事"),
        _pair(prompt_id="p-3", tag="仙侠小说"),
    ]
    report = compute_accuracy(run_preference_judge(pairs, "reader_judge", _perfect_judge))
    assert report.overall_accuracy == 1.0
    assert report.abstain_count == 0
    assert report.per_tag_accuracy["悬疑-推理故事"] == 1.0
    assert report.per_tag_n["仙侠小说"] == 1
    assert 0.0 < report.wilson_low <= 1.0


def test_compute_accuracy_counts_abstain_as_incorrect():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2")]
    report = compute_accuracy(run_preference_judge(pairs, "reader_judge", _abstain_judge))
    assert report.overall_accuracy == 0.0
    assert report.abstain_count == 2
    assert report.unreviewable_count == 0


def test_compute_accuracy_mixed_abstain_counts_as_wrong():
    # 冻结口径：弃权=错，分母=全部样本（10 对 5 正确 5 弃权 → 0.5，而非旧口径 1.0）.
    pairs = [
        _pair(prompt_id="p-1", tag="悬疑-推理故事"),
        _pair(prompt_id="p-2", tag="悬疑-推理故事"),
        _pair(prompt_id="p-3", tag="仙侠小说"),
        _pair(prompt_id="p-4", tag="仙侠小说"),
    ]

    def judge(pair, role):
        return "A" if pair.prompt_id in ("p-1", "p-2") else "no_difference"

    report = compute_accuracy(run_preference_judge(pairs, "reader_judge", judge))
    assert report.n == 4
    assert report.abstain_count == 2
    assert report.overall_accuracy == 0.5
    assert report.per_tag_accuracy["悬疑-推理故事"] == 1.0
    assert report.per_tag_accuracy["仙侠小说"] == 0.0  # 全弃权 tag → 0.0（分母=全部样本）
    assert report.per_tag_n["仙侠小说"] == 2
    assert report.wilson_low < 0.5  # Wilson 以全部样本为分母


def _failing_judge(fail_prompt_id):
    def judge(pair, role):
        if pair.prompt_id == fail_prompt_id:
            raise ReviewQualityExhaustedError("fabricated anchor exhausted")
        # 非失败对走内容稳定评审（恒偏好「甲文」内容 → 换位稳定）
        return _stable_correct_judge(pair, role)
    return judge


def test_run_preference_judge_unreviewable_counts_as_wrong():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2"), _pair(prompt_id="p-3")]
    recorded = []
    predictions = run_preference_judge(
        pairs, "reader_judge", _failing_judge("p-2"),
        on_pair_unreviewable=lambda pair, exc: recorded.append(
            (pair.prompt_id, type(exc).__name__)
        ),
    )
    # 冻结口径：耗尽对记 predicted="unreviewable"、correct=False，绝不静默排除
    assert [p.prompt_id for p in predictions] == ["p-1", "p-2", "p-3"]
    by_id = {p.prompt_id: p for p in predictions}
    assert by_id["p-2"].predicted == "unreviewable"
    assert by_id["p-2"].correct is False
    assert by_id["p-2"].reason
    assert by_id["p-1"].correct is True and by_id["p-3"].correct is True
    assert recorded == [("p-2", "ReviewQualityExhaustedError")]
    # 计入分母：n=3、耗尽 1 条 → 准确率 2/3（overall 已四舍五入到 4 位）
    report = compute_accuracy(predictions)
    assert report.n == 3
    assert report.unreviewable_count == 1
    assert report.overall_accuracy == pytest.approx(2 / 3, abs=1e-3)


def test_run_preference_judge_unreviewable_without_callback_raises():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2")]
    with pytest.raises(ReviewQualityExhaustedError):
        run_preference_judge(pairs, "reader_judge", _failing_judge("p-2"))


def test_run_preference_judge_nonquality_error_still_raises_with_callback():
    def bad_judge(pair, role):
        raise RuntimeError("network 5xx")

    with pytest.raises(RuntimeError, match="5xx"):
        run_preference_judge(
            [_pair(prompt_id="p-1")], "reader_judge", bad_judge,
            on_pair_unreviewable=lambda pair, exc: None,
        )


def test_position_consistency_unreviewable_counts_as_inconsistent():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2")]
    recorded = []
    position = measure_position_consistency(
        pairs, _failing_judge("p-2"), role="reader_judge",
        on_pair_unreviewable=lambda pair, exc: recorded.append(pair.prompt_id),
    )
    # 冻结口径：耗尽计为「不一致」并计入分母（1/2），绝不静默排除
    assert position == 0.5
    assert recorded == ["p-2"]


def test_position_consistency_all_unreviewable_is_zero():
    def always_exhaust(pair, role):
        raise ReviewQualityExhaustedError("exhausted")

    position = measure_position_consistency(
        [_pair(prompt_id="p-1"), _pair(prompt_id="p-2")],
        always_exhaust, role="reader_judge",
        on_pair_unreviewable=lambda pair, exc: None,
    )
    assert position == 0.0  # 空评 ≠ 完美（旧实现返回 1.0 是测量漏洞）


def test_position_consistency_stratified_sample_not_prefix():
    # 6 对：仙侠 3 对 + 悬疑 3 对；sample=2 应各取 1（按 tag 分层），
    # 而不是旧的 pairs[:2] 前缀（会全落在同一 tag）.
    pairs = (
        [_pair(prompt_id=f"a-{i}", tag="仙侠小说") for i in range(3)]
        + [_pair(prompt_id=f"b-{i}", tag="悬疑-推理故事") for i in range(3)]
    )
    sampled = _stratified_position_sample(pairs, 2)
    assert sorted(p.tag for p in sampled) == ["仙侠小说", "悬疑-推理故事"]
    assert sampled[0].prompt_id == "a-0"
    assert sampled[1].prompt_id == "b-0"
    # 分层采样确定性：两次调用结果一致
    assert [p.prompt_id for p in _stratified_position_sample(pairs, 2)] == [
        p.prompt_id for p in sampled
    ]


# ---------------------------------------------------------------------------
# 阈值冻结（唯一来源 = calibration）
# ---------------------------------------------------------------------------

def _calibration_span_pairs(n_prompts: int) -> list[PreferencePair]:
    pairs = []
    for i in range(n_prompts):
        tag = "悬疑-推理故事" if i % 2 == 0 else "仙侠小说"
        pairs.append(_pair(prompt_id=f"p-{i:03d}", tag=tag))
    return pairs


def _freeze(pairs, report=None):
    report = report or compute_accuracy(
        run_preference_judge(pairs, "reader_judge", _perfect_judge)
    )
    return freeze_quality_thresholds(
        pairs,
        report,
        _policy(),
        role="reader_judge",
        policy_sha256="a" * 64,
        frozen_at="2026-08-12T00:00:00Z",
        frozen_by_run="run-cal",
        source_sha256={
            "preference_source": _BENCH_SHA,
            "preference_split": _SPLIT_SHA,
            "human_distribution": "c" * 64,
        },
    )


def test_freeze_thresholds_requires_minimum_span():
    too_few_prompts = _calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS - 1)
    with pytest.raises(ValueError, match="prompt_ids"):
        _freeze(too_few_prompts)
    single_tag = [
        _pair(prompt_id=f"p-{i:03d}", tag="悬疑-推理故事")
        for i in range(MIN_CALIBRATION_PROMPT_IDS)
    ]
    with pytest.raises(ValueError, match="tags"):
        _freeze(single_tag)


def test_freeze_thresholds_records_frozen_evidence():
    pairs = _calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS + 4)
    thresholds = _freeze(pairs)
    assert isinstance(thresholds, QualityThresholds)
    assert thresholds.generated_from == "calibration_split"
    assert thresholds.role == "reader_judge"
    assert thresholds.overall_accuracy_min == pytest.approx(0.65)
    assert thresholds.preference_source_sha256 == _BENCH_SHA
    assert thresholds.calibration_span["distinct_prompt_ids"] == len(pairs)
    assert thresholds.calibration_span["distinct_tags"] >= MIN_CALIBRATION_TAGS


def test_freeze_thresholds_id_is_deterministic():
    pairs = _calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS + 2)
    first = _freeze(pairs)
    second = _freeze(pairs)
    assert first.thresholds_id == second.thresholds_id


# ---------------------------------------------------------------------------
# 位置一致性 + holdout（只读，T7.6）
# ---------------------------------------------------------------------------

def test_measure_position_consistency_stable_judge():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2"), _pair(prompt_id="p-3")]
    # 稳定判断：恒偏好「甲文」内容，换位后仍命名同一响应 → 一致
    assert measure_position_consistency(pairs, _stable_correct_judge,
                                        role="reader_judge") == 1.0


def test_measure_position_consistency_positional_judge():
    pairs = [_pair(prompt_id="p-1"), _pair(prompt_id="p-2")]

    def positional(pair, role):
        return "A"  # 恒选候选甲，与内容无关 → 换位后翻转

    assert measure_position_consistency(pairs, positional,
                                        role="reader_judge") == 0.0


def test_run_holdout_met_with_stable_correct_judge():
    pairs = [_pair(prompt_id=f"h-{i:03d}", tag="仙侠小说", split="holdout")
             for i in range(6)]
    thresholds = _freeze(_calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS + 2))
    report = run_holdout(
        thresholds, pairs, "reader_judge", _stable_correct_judge,
        run_id="run-holdout", run_at="2026-08-12T00:00:00Z", position_sample=None,
    )
    assert report.met is True
    assert report.thresholds_id == thresholds.thresholds_id
    assert report.dimension_met["overall"] is True
    assert report.dimension_met["position_consistency"] is True


def test_run_holdout_does_not_rewrite_thresholds():
    pairs = [_pair(prompt_id=f"h-{i:03d}", tag="仙侠小说", split="holdout")
             for i in range(4)]
    thresholds = _freeze(_calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS + 2))
    frozen = thresholds.model_dump()
    report = run_holdout(
        thresholds, pairs, "reader_judge", _reverse_judge,
        run_id="run-holdout", run_at="2026-08-12T00:00:00Z", position_sample=None,
    )
    assert report.met is False
    assert report.violations  # 降级只报违规，不回写阈值
    assert thresholds.model_dump() == frozen  # T7.6：阈值不被 holdout 调整


def test_run_holdout_fully_abstained_tag_fails_per_tag():
    # 冻结口径：整 tag 弃权 → 该 tag 准确率 0.0 < 0.5 → per-tag 门 FAIL，
    # 不再是「无预测 tag 虚过」.
    pairs = [_pair(prompt_id=f"h-{i:03d}", tag="仙侠小说", split="holdout")
             for i in range(6)]
    thresholds = _freeze(_calibration_span_pairs(MIN_CALIBRATION_PROMPT_IDS + 2))

    def abstain_judge(pair, role):
        return "no_difference"

    report = run_holdout(
        thresholds, pairs, "reader_judge", abstain_judge,
        run_id="run-holdout", run_at="2026-08-12T00:00:00Z",
    )
    assert report.met is False
    assert report.dimension_met["per_tag"] is False
    assert report.overall_accuracy == 0.0
    assert report.abstain_count == 6
    assert any("per-tag accuracy" in v for v in report.violations)
