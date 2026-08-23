"""AuthorModel V3 动作与跨作品验证器 (P5).

实现：
1. 候选作者先验对齐打分 (score_author_prior)：作为候选排序与 tie-break 信号（非硬门禁）。
2. 依据 Hindsight 结果回填反例与支撑样本 (update_author_model_from_hindsight)。
3. 跨作品留一验证 (validate_cross_work_separation)：检测词汇泄漏并计算留出作品选择预测率。
"""

from __future__ import annotations

import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.object_state.authorkernel import (
    VALUE_VOCAB,
    VALUE_VOCAB_CONTRA_KEYWORDS,
    VALUE_VOCAB_KEYWORDS,
    VALUE_VOCAB_PRO_KEYWORDS,
    value_direction,
)
from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CounterexampleSample,
    CrossWorkValidationResult,
    DecisionEventV2,
    ProxySignatureV2Result,
    SupportingSample,
)
from src.object_state.choicerecord import ChoiceRecord
from src.object_state.structural_search import StructuralProposal
from src.object_state.workspec import WorkSpec


def score_author_prior(
    proposal: StructuralProposal,
    author_model: Optional[AuthorModelV3],
    work_spec: Optional[WorkSpec] = None,
) -> float:
    """计算结构候选与作者决策先验的关键词对齐度（Shadow Measurement 仅供观察与离线分析，严禁用于正式生产 tie-break）."""
    if author_model is None or not author_model.principles:
        return 0.5  # 中性默认先验

    score_acc = 0.5
    matched_principles = 0
    text_corpus = (
        f"{proposal.core_choice} {proposal.cost} {proposal.state_change} "
        f"{proposal.summary} {proposal.primary_risk}"
    )

    for principle in author_model.principles:
        # 已废弃或争议极大的原则降低权重或忽略
        if principle.status == "deprecated":
            continue

        weight = principle.confidence
        if principle.status == "stable":
            weight *= 1.2
        elif principle.status == "contested":
            weight *= 0.5

        vocab_key = principle.value_vocab_key
        direction = value_direction(text_corpus, vocab_key)

        # 1. 词汇语义方向对齐
        if direction == "pro":
            score_acc += 0.15 * weight
            matched_principles += 1
        elif direction == "contra":
            score_acc -= 0.2 * weight
            matched_principles += 1

        # 2. 结构化案例支撑与反例权衡 (Case-based / Grounding Evaluation)
        for sup in getattr(principle, "supporting_samples", []):
            if sup.tradeoff_rationale and any(chunk in text_corpus for chunk in sup.tradeoff_rationale.split() if len(chunk) >= 2):
                score_acc += 0.05 * weight
                break
        for contra in getattr(principle, "counterexamples", []):
            if contra.deviation_reason and any(chunk in text_corpus for chunk in contra.deviation_reason.split() if len(chunk) >= 2):
                score_acc -= 0.08 * weight
                break

    return max(0.0, min(1.0, round(score_acc, 3)))


def update_author_model_from_hindsight(
    author_model: AuthorModelV3,
    choice_records: list[ChoiceRecord],
    work_name: str,
) -> int:
    """从已回填 Hindsight 的 ChoiceRecord 更新作者原则（支持样本与反例）."""
    updated_count = 0

    for choice in choice_records:
        if choice.hindsight is None or choice.consequence is None:
            continue

        for conflict_key in choice.value_conflicts:
            # 找到或创建对应原则
            matching_p = next(
                (p for p in author_model.principles if p.value_vocab_key == conflict_key),
                None,
            )

            if matching_p is None:
                if conflict_key in VALUE_VOCAB:
                    matching_p = AuthorPrincipleV3(
                        principle_id=f"ap_{conflict_key}",
                        statement=f"关于 {conflict_key} 的决策原则",
                        value_vocab_key=conflict_key,
                        scope="author_global",
                        confidence=0.5,
                        status="candidate",
                    )
                    author_model.principles.append(matching_p)
                else:
                    continue

            if choice.hindsight in ("overturned", "partial_regret", "complex"):
                # 记录反例
                existing_contra = any(
                    c.decision_id == choice.decision_id for c in matching_p.counterexamples
                )
                if not existing_contra:
                    matching_p.counterexamples.append(
                        CounterexampleSample(
                            decision_id=choice.decision_id,
                            work_name=work_name,
                            chapter_number=choice.chapter_number,
                            hindsight_status=choice.hindsight,
                            observed_consequence=choice.consequence,
                            deviation_reason=choice.hindsight_note or "回看发现负面后果或代价估计失误",
                        )
                    )
                    matching_p.update_status_from_evidence()
                    updated_count += 1
            elif choice.hindsight == "still_supported":
                # 记录支持样本
                existing_sup = any(
                    s.decision_id == choice.decision_id for s in matching_p.supporting_samples
                )
                if not existing_sup:
                    matching_p.supporting_samples.append(
                        SupportingSample(
                            decision_id=choice.decision_id,
                            work_name=work_name,
                            chapter_number=choice.chapter_number,
                            context_summary=choice.plot_context,
                            chosen_action=choice.selected_candidate,
                            rejected_actions=[r.candidate_id for r in choice.rejected],
                            tradeoff_rationale=choice.tradeoff,
                        )
                    )
                    matching_p.update_status_from_evidence()
                    updated_count += 1

    if work_name not in author_model.known_works:
        author_model.known_works.append(work_name)

    return updated_count


def validate_cross_work_separation(
    author_model: AuthorModelV3,
    works_choice_records: dict[str, list[ChoiceRecord]],
    holdout_work: str,
    forbidden_work_entities: Optional[list[str]] = None,
) -> CrossWorkValidationResult:
    """执行留一作品验证 (L1WO)，检测词汇泄漏与选择预测表现."""
    training_works = [w for w in works_choice_records if w != holdout_work]
    holdout_records = works_choice_records.get(holdout_work, [])

    # 1. 词汇泄漏检测：全局原则陈述中不得包含作品专有专有名词
    leaked_terms = []
    forbidden = forbidden_work_entities or []
    for p in author_model.principles:
        if p.scope == "author_global":
            for term in forbidden:
                if term and term in p.statement:
                    leaked_terms.append(term)

    lexical_leakage = len(leaked_terms) > 0

    # 2. 留出作品选择预测准确率评估
    correct_predictions = 0
    evaluable_choices = 0

    for rec in holdout_records:
        if not rec.candidates or not rec.selected_candidate:
            continue
        evaluable_choices += 1

        # 用原则匹配预测哪一个候选最可能被作者选中
        cand_scores = {}
        for c in rec.candidates:
            summary = c.summary
            cand_score = 0.5
            for p in author_model.principles:
                if p.status == "deprecated":
                    continue
                if p.value_vocab_key in rec.value_conflicts:
                    pro_kws = VALUE_VOCAB_PRO_KEYWORDS.get(p.value_vocab_key, ())
                    if any(kw in summary for kw in pro_kws):
                        cand_score += 0.2 * p.confidence
            cand_scores[c.candidate_id] = cand_score

        predicted_winner = max(cand_scores, key=cand_scores.get)
        if predicted_winner == rec.selected_candidate:
            correct_predictions += 1

    accuracy = (
        round(correct_predictions / evaluable_choices, 3)
        if evaluable_choices > 0
        else 0.5
    )

    is_valid = (accuracy > 0.5) and (not lexical_leakage) and (len(training_works) >= 1)

    return CrossWorkValidationResult(
        author_id=author_model.author_id,
        holdout_work=holdout_work,
        training_works=training_works,
        choice_prediction_accuracy=accuracy,
        baseline_accuracy=0.5,
        lexical_leakage_detected=lexical_leakage,
        leaked_terms=leaked_terms,
        is_valid_author_prior=is_valid,
    )



# ---------------------------------------------------------------------------
# Published-Text Behavioral Signature Proxy v2（研究性、离线、确定性）
# ---------------------------------------------------------------------------


def _freeze_v2(value: object) -> object:
    """把情境维度变成稳定可哈希值，且不依赖候选输入顺序。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze_v2(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_v2(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_v2(item) for item in value), key=repr))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _v2_anchor_key(anchor: object) -> object:
    """返回证据锚的稳定键；空锚返回 None。"""
    if anchor is None:
        return None
    frozen = _freeze_v2(anchor)
    if frozen in ("", (), {}, None):
        return None
    return frozen


def _v2_situation(event: DecisionEventV2) -> tuple[object, ...]:
    """情境键只由预注册结构化字段构成，不读取文本风格。"""
    return (
        event.stage,
        event.topic_tag,
        event.actor_role,
        _freeze_v2(event.power_gap),
        _freeze_v2(event.reversibility),
        _freeze_v2(event.threat),
        _freeze_v2(event.dependence),
        _freeze_v2(event.info_uncertainty),
        _freeze_v2(event.loyalty_conflict),
    )


def _v2_action_counts(events: Iterable[DecisionEventV2]) -> dict[tuple[object, ...], dict[str, int]]:
    """按情境重建离散策略；调用方保证事件已经通过结构门禁。"""
    counts: dict[tuple[object, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        counts[_v2_situation(event)][event.selected] += 1
    return {key: dict(value) for key, value in counts.items()}


def _v2_predict(
    counts: Mapping[tuple[object, ...], Mapping[str, int]],
    situation: tuple[object, ...],
    candidates: Iterable[str],
) -> Optional[str]:
    """使用拉普拉斯平滑的离散策略预测；并列时 abstain。"""
    candidate_list = sorted(set(candidates))
    if not candidate_list:
        return None
    observed = counts.get(situation)
    if not observed:
        return None
    total = sum(observed.values())
    alpha = 1.0
    scores = {
        action: (observed.get(action, 0) + alpha) / (total + alpha * len(candidate_list))
        for action in candidate_list
    }
    best = max(scores.values())
    winners = [action for action, score in scores.items() if abs(score - best) <= 1e-12]
    return winners[0] if len(winners) == 1 else None


def _v2_situation_family(event: DecisionEventV2) -> tuple[object, ...]:
    """把 stage 折叠掉，保留题材/角色与六维情境族。"""
    return (
        event.topic_tag,
        event.actor_role,
        _freeze_v2(event.power_gap),
        _freeze_v2(event.reversibility),
        _freeze_v2(event.threat),
        _freeze_v2(event.dependence),
        _freeze_v2(event.info_uncertainty),
        _freeze_v2(event.loyalty_conflict),
    )


def _v2_family_counts(events: Iterable[DecisionEventV2]) -> dict[tuple[object, ...], dict[str, int]]:
    """建立 author×situation-family 统计；输入必须是训练事件。"""
    counts: dict[tuple[object, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        counts[_v2_situation_family(event)][event.selected] += 1
    return {key: dict(value) for key, value in counts.items()}


def _v2_scores(
    counts: Mapping[tuple[object, ...], Mapping[str, int]],
    key: tuple[object, ...],
    candidates: Iterable[str],
) -> tuple[Optional[str], float]:
    """返回唯一最高动作及其 top-2 概率 margin。"""
    candidate_list = sorted(set(candidates))
    observed = counts.get(key)
    if not candidate_list or not observed:
        return None, 0.0
    total = sum(observed.values())
    alpha = 1.0
    scores = {
        action: (observed.get(action, 0) + alpha) / (total + alpha * len(candidate_list))
        for action in candidate_list
    }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    margin = ordered[0][1] - (ordered[1][1] if len(ordered) > 1 else 0.0)
    if len(ordered) > 1 and abs(ordered[0][1] - ordered[1][1]) <= 1e-12:
        return None, margin
    return ordered[0][0], margin


def _v2_partial_pool_predict(
    target_training: Iterable[DecisionEventV2],
    pooled_training: Iterable[DecisionEventV2],
    candidates: Iterable[str],
) -> tuple[Optional[str], float]:
    """作者级 Dirichlet 部分池化：作者计数 + pooled 训练先验。"""
    candidate_list = sorted(set(candidates))
    if not candidate_list:
        return None, 0.0
    target_totals: dict[str, int] = defaultdict(int)
    pooled_totals: dict[str, int] = defaultdict(int)
    for event in target_training:
        target_totals[event.selected] += 1
    for event in pooled_training:
        pooled_totals[event.selected] += 1
    pooled_total = sum(pooled_totals.values())
    prior_mass = 2.0
    prior_denominator = pooled_total + len(candidate_list)
    prior = {
        action: (pooled_totals.get(action, 0) + 1.0) / prior_denominator
        for action in candidate_list
    }
    author_total = sum(target_totals.values())
    denominator = author_total + prior_mass
    scores = {
        action: (target_totals.get(action, 0) + prior_mass * prior[action]) / denominator
        for action in candidate_list
    }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    margin = ordered[0][1] - (ordered[1][1] if len(ordered) > 1 else 0.0)
    # A tiny posterior margin is not a defensible author prediction.
    if len(ordered) > 1 and margin <= 0.05:
        return None, margin
    return ordered[0][0], margin


def _v2_predict_with_backoff(
    event: DecisionEventV2,
    target_counts: Mapping[tuple[object, ...], Mapping[str, int]],
    family_counts: Mapping[tuple[object, ...], Mapping[str, int]],
    target_training: Iterable[DecisionEventV2],
    pooled_training: Iterable[DecisionEventV2],
    backoff: str,
) -> tuple[Optional[str], float, str]:
    """按 exact → family → partial_pool 顺序预测，仅消费训练统计。"""
    predicted, margin = _v2_scores(target_counts, _v2_situation(event), event.candidates)
    if predicted is not None:
        return predicted, margin, "none"
    if backoff in {"family", "partial_pool"}:
        predicted, margin = _v2_scores(
            family_counts, _v2_situation_family(event), event.candidates
        )
        if predicted is not None:
            return predicted, margin, "family"
    if backoff == "partial_pool":
        predicted, margin = _v2_partial_pool_predict(
            target_training, pooled_training, event.candidates
        )
        if predicted is not None:
            return predicted, margin, "partial_pool"
    return None, margin, "none"


def _v2_pooled_counts(events: Iterable[DecisionEventV2]) -> dict[tuple[object, ...], dict[str, int]]:
    """建立不区分作者的 pooled-majority 条件统计。"""
    return _v2_action_counts(events)


def _v2_class_balanced_predict(
    counts: Mapping[tuple[object, ...], Mapping[str, int]],
    situation: tuple[object, ...],
    candidates: Iterable[str],
    class_totals: Mapping[str, int],
) -> Optional[str]:
    """建立不区分作者的 class-balanced 条件基线。

    对 pooled 训练统计按动作总频次做逆频率校正，避免多数动作直接支配
    基线；该函数不读取 author_id，也不把目标作者单独作为训练来源。
    """
    candidate_list = sorted(set(candidates))
    observed = counts.get(situation)
    if not observed:
        return None
    scores = {
        candidate: observed.get(candidate, 0) / class_totals.get(candidate, 1)
        for candidate in candidate_list
    }
    best = max(scores.values())
    winners = [candidate for candidate, value in scores.items() if abs(value - best) <= 1e-12]
    return winners[0] if len(winners) == 1 else None


def _v2_macro(values: Mapping[object, list[float]]) -> float:
    """对 topic/role 分组做宏平均；空组不参与。"""
    means = [sum(items) / len(items) for items in values.values() if items]
    return sum(means) / len(means) if means else 0.0


def _v2_ci(differences: list[float]) -> list[float]:
    """计算确定性正态近似区间；差值恒定时区间退化为点。"""
    if not differences:
        return [0.0, 0.0]
    mean = sum(differences) / len(differences)
    if len(differences) == 1:
        return [round(mean, 6), round(mean, 6)]
    variance = sum((item - mean) ** 2 for item in differences) / (len(differences) - 1)
    margin = 1.96 * math.sqrt(variance / len(differences))
    return [round(mean - margin, 6), round(mean + margin, 6)]


def _v2_permutation_p(differences: list[float]) -> float:
    """对非零配对差做确定性符号置换检验。"""
    signs = [1 if item > 0 else -1 for item in differences if item != 0]
    n = len(signs)
    if n == 0:
        return 1.0
    wins = sum(sign == 1 for sign in signs)
    tail = sum(math.comb(n, k) for k in range(wins, n + 1))
    return round(min(1.0, 2.0 * tail / (2**n)), 6)


def _v2_invalid_result(reasons: list[str], warnings: Optional[list[str]] = None) -> ProxySignatureV2Result:
    """集中构造 INVALID 报告，防止无数据回落成旧版 0.5。"""
    return ProxySignatureV2Result(
        state="INVALID",
        invalid_reasons=list(dict.fromkeys(reasons)),
        warnings=list(dict.fromkeys(warnings or [])),
    )


def _v2_invalid_with_v8(
    reasons: list[str],
    backoff: str,
    operating_coverage: Optional[float],
) -> ProxySignatureV2Result:
    """构造结构无效报告，并显式固定双平面失败状态。"""
    result = _v2_invalid_result(reasons)
    result.backoff_used = backoff
    result.backoff_events = 0
    result.operating_coverage = operating_coverage
    result.statistical_state = "INVALID"
    result.full_coverage_deployment_state = "FAIL"
    result.coverage = 0.0
    result.selective_risk = None
    result.aurc = None
    result.c_at_1 = None
    result.f_half_u = None
    return result


def _v2_selective_metrics(
    records: Iterable[tuple[Optional[float], bool]],
) -> dict[str, Optional[float]]:
    """计算 answered-only 风险及五态选择性指标。

    ``records`` 每项是 ``(margin, error)``；margin 为 None 表示 abstain。
    AURC 以每个 answered 前缀的风险按全体事件宽度 1/N 做离散积分。
    多分类 F^u_{0.5} 映射为命中 TP、错误 FN、弃答 U、FP=0。
    """
    rows = list(records)
    n = len(rows)
    answered = [(margin, error) for margin, error in rows if margin is not None]
    abstentions = n - len(answered)
    correct = sum(not error for _, error in answered)
    errors = len(answered) - correct
    coverage = len(answered) / n if n else 0.0
    selective_risk = errors / len(answered) if answered else None
    ordered = sorted(answered, key=lambda item: (-float(item[0]), bool(item[1])))
    prefix_errors = 0
    aurc_area = 0.0
    for index, (_, error) in enumerate(ordered, start=1):
        prefix_errors += int(error)
        aurc_area += (prefix_errors / index) / n if n else 0.0
    c_at_1 = ((correct + abstentions * correct / n) / n) if n else None
    denominator = 1.25 * correct + 0.25 * (errors + abstentions)
    f_half_u = 1.25 * correct / denominator if denominator else 0.0
    return {
        "coverage": coverage,
        "selective_risk": selective_risk,
        "aurc": aurc_area if n else None,
        "c_at_1": c_at_1,
        "f_half_u": f_half_u,
    }


def validate_decision_signature_v2(
    events: Iterable[DecisionEventV2 | Mapping[str, Any]],
    *,
    backoff: str = "none",
    operating_coverage: Optional[float] = None,
) -> ProxySignatureV2Result:
    """验证出版文本作者决策签名 v2，并提供 v8 双平面裁决扩展。

    每个 ``(author_id, work_slot)`` 是一个 L1WO 折；目标作者的训练统计
    只来自其余作品。函数只消费结构化事件，不生成候选、不读取文本风格，
    返回的 ``state`` 保留 v2 全覆盖硬门禁语义；``statistical_state``
    允许 selective coverage。所有 backoff 参数只从训练折估计，绝不读取
    当前 holdout 标签。``operating_coverage`` 是预注册部署下限，不是
    事后从结果选择的阈值。
    """
    if backoff not in {"none", "family", "partial_pool"}:
        raise ValueError("backoff must be one of: none, family, partial_pool")
    if operating_coverage is not None and not 0.0 <= operating_coverage <= 1.0:
        raise ValueError("operating_coverage must be between 0.0 and 1.0")
    raw_events = list(events) if events is not None else []
    if not raw_events:
        return _v2_invalid_with_v8(["无可评估事件"], backoff, operating_coverage)

    parsed: list[DecisionEventV2] = []
    reasons: list[str] = []
    for index, raw in enumerate(raw_events):
        try:
            event = raw if isinstance(raw, DecisionEventV2) else DecisionEventV2.model_validate(raw)
        except Exception as exc:
            reasons.append(f"事件 {index} 结构非法: {exc}")
            continue
        parsed.append(event)

    if reasons:
        return _v2_invalid_with_v8(reasons, backoff, operating_coverage)

    # 结构、词表、置信度和真实候选集合门禁。
    anchors: dict[object, tuple[str, str]] = {}
    for index, event in enumerate(parsed):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (event.author_id, event.work_slot, event.stage, event.topic_tag, event.actor_role)
        ):
            reasons.append(f"事件 {index} 缺少作者/作品/阶段/题材/角色实体")
        candidates = list(event.candidates)
        if len(candidates) < 2 or len(set(candidates)) != len(candidates):
            reasons.append(f"事件 {index} 候选集少于 2 个或含重复动作")
        if not event.selected or event.selected not in candidates:
            reasons.append(f"事件 {index} selected 不在候选集")
        if any(action not in candidates for action in event.rejected):
            reasons.append(f"事件 {index} rejected 不属于候选集")
        if event.selected in event.rejected:
            reasons.append(f"事件 {index} selected 不能同时是 rejected")
        if not event.cost_label or not str(event.cost_label).strip():
            reasons.append(f"事件 {index} 缺少代价标签")
        if event.protected_value_key not in VALUE_VOCAB:
            reasons.append(f"事件 {index} 使用未知受限价值词汇键")
        if _v2_anchor_key(event.evidence_anchor) is None:
            reasons.append(f"事件 {index} 缺少证据锚")
        if event.confidence < 0.85:
            reasons.append(f"事件 {index} 提取置信度低于 0.85")
        anchor_key = _v2_anchor_key(event.evidence_anchor)
        if anchor_key is not None:
            previous = anchors.get(anchor_key)
            if previous is not None and previous[0] != event.work_slot:
                reasons.append("检测到跨作品重复证据锚，疑似 holdout 泄漏")
            anchors[anchor_key] = (event.work_slot, event.author_id)
        # 显式携带训练统计的锚不能作为留出证据。
        anchor_text = repr(event.evidence_anchor).lower()
        if any(token in anchor_text for token in ("training_stats", "train_stats", "holdout_stats", "pooled_statistics")):
            reasons.append(f"事件 {index} 证据锚显式携带训练统计")

    if reasons:
        result = _v2_invalid_with_v8(reasons, backoff, operating_coverage)
        result.holdout_leakage_detected = any("泄漏" in reason or "训练统计" in reason for reason in reasons)
        return result

    authors = sorted({event.author_id for event in parsed})
    stages = {event.stage for event in parsed}
    work_by_author: dict[str, set[str]] = defaultdict(set)
    authors_by_topic: dict[str, set[str]] = defaultdict(set)
    topics_by_author: dict[str, set[str]] = defaultdict(set)
    for event in parsed:
        work_by_author[event.author_id].add(event.work_slot)
        authors_by_topic[event.topic_tag].add(event.author_id)
        topics_by_author[event.author_id].add(event.topic_tag)

    if len(authors) < 2:
        reasons.append("作者实体不足 2 个")
    if len(stages) < 2:
        reasons.append("训练与留出证据覆盖阶段不足 2 个")
    if any(len(works) < 3 for works in work_by_author.values()):
        reasons.append("至少一位作者独立 work_slot 少于 3 个")
    stages_by_work: dict[tuple[str, str], set[str]] = defaultdict(set)
    for event in parsed:
        stages_by_work[(event.author_id, event.work_slot)].add(event.stage)
    if any(len(work_stages) < 2 for work_stages in stages_by_work.values()):
        reasons.append("存在作品折未覆盖至少 2 个阶段，疑似静默丢折")
    if any(len(topic_authors) < 2 for topic_authors in authors_by_topic.values()):
        reasons.append("存在题材没有至少 2 位作者，困难负样本不可构造")
    if all(
        len(topics_by_author[author]) == 1
        and len(authors_by_topic[next(iter(topics_by_author[author]))]) == 1
        for author in authors
    ):
        reasons.append("author 与 topic 完全别名")

    # 每个作者/作品槽位生成一折；不会静默丢弃任何槽位。
    folds = sorted((author, work) for author, works in work_by_author.items() for work in works)
    expected_fold_count = len(folds)
    if not folds:
        reasons.append("没有可构造的 L1WO 折")
    if reasons:
        result = _v2_invalid_with_v8(reasons, backoff, operating_coverage)
        result.expected_fold_count = expected_fold_count
        result.fold_count = 0
        result.holdout_leakage_detected = any("泄漏" in reason or "训练统计" in reason for reason in reasons)
        result.topic_alias_detected = any("别名" in reason for reason in reasons)
        return result

    per_fold: list[dict[str, object]] = []
    all_author_correct: list[float] = []
    all_pooled_correct: list[float] = []
    all_balanced_correct: list[float] = []
    all_hard_correct: list[float] = []
    paired_differences: list[float] = []
    hard_differences: list[float] = []
    topic_role_author: dict[tuple[str, str], list[float]] = defaultdict(list)
    topic_role_pooled: dict[tuple[str, str], list[float]] = defaultdict(list)
    topic_role_balanced: dict[tuple[str, str], list[float]] = defaultdict(list)
    topic_role_hard: dict[tuple[str, str], list[float]] = defaultdict(list)
    abstentions = 0
    fallback_predictions = 0
    backoff_events_used = 0
    answered_correct = 0
    prediction_records: list[tuple[Optional[float], bool]] = []
    fold_warnings: list[str] = []

    for author, holdout_work in folds:
        holdout = [event for event in parsed if event.author_id == author and event.work_slot == holdout_work]
        target_training = [
            event for event in parsed if event.author_id == author and event.work_slot != holdout_work
        ]
        if len({event.work_slot for event in target_training}) < 2:
            fold_warnings.append(f"折 {author}/{holdout_work} 训练作品少于 2 个")
        if not holdout:
            fold_warnings.append(f"折 {author}/{holdout_work} 无留出事件")
            continue
        target_counts = _v2_action_counts(target_training)
        family_counts = _v2_family_counts(target_training)
        # 仅排除当前作者的当前作品折；其他作者同名槽位仍属训练观测，
        # 防止仅按 work_slot 过滤造成跨作者误排除。
        pooled_training = [
            event
            for event in parsed
            if not (event.author_id == author and event.work_slot == holdout_work)
        ]
        pooled_counts = _v2_pooled_counts(pooled_training)
        pooled_class_totals: dict[str, int] = defaultdict(int)
        for event in pooled_training:
            pooled_class_totals[event.selected] += 1
        topic_other_counts: dict[str, dict[tuple[object, ...], dict[str, int]]] = {}
        for topic in {event.topic_tag for event in holdout}:
            topic_other_counts[topic] = {
                other: _v2_action_counts(
                    event
                    for event in pooled_training
                    if event.topic_tag == topic and event.author_id == other
                )
                for other in authors
                if other != author
            }

        fold_author: list[float] = []
        fold_pooled: list[float] = []
        fold_balanced: list[float] = []
        fold_hard: list[float] = []
        fold_hard_differences: list[float] = []
        action_distribution: dict[str, int] = defaultdict(int)
        candidate_distribution: dict[str, int] = defaultdict(int)
        hard_available = False
        hard_evaluable_count = 0
        for event in holdout:
            action_distribution[event.selected] += 1
            candidate_distribution[str(len(event.candidates))] += 1
            situation = _v2_situation(event)
            predicted, prediction_margin, used_level = _v2_predict_with_backoff(
                event,
                target_counts,
                family_counts,
                target_training,
                pooled_training,
                backoff,
            )
            if used_level != "none":
                backoff_events_used += 1
            if predicted is None:
                abstentions += 1
                fallback_predictions += 1
            else:
                answered_correct += int(predicted == event.selected)
                prediction_records.append((prediction_margin, bool(predicted != event.selected)))
            author_hit = float(predicted == event.selected)
            pooled_predicted = _v2_predict(pooled_counts, situation, event.candidates)
            balanced_predicted = _v2_class_balanced_predict(
                pooled_counts, situation, event.candidates, pooled_class_totals
            )
            pooled_hit = float(pooled_predicted == event.selected)
            balanced_hit = float(balanced_predicted == event.selected)

            other_predictions: list[Optional[str]] = []
            for other_counts in topic_other_counts.get(event.topic_tag, {}).values():
                other_predictions.append(_v2_predict(other_counts, situation, event.candidates))
            usable_other = [prediction for prediction in other_predictions if prediction is not None]
            if usable_other:
                hard_available = True
                hard_evaluable_count += 1
            if usable_other:
                hard_hit = float(any(prediction == event.selected for prediction in usable_other))
                hard_advantage_hit = author_hit - hard_hit
                fold_hard.append(hard_hit)
                fold_hard_differences.append(hard_advantage_hit)
                all_hard_correct.append(hard_hit)
                hard_differences.append(hard_advantage_hit)
                topic_role_hard[(event.topic_tag, event.actor_role)].append(hard_hit)
            fold_author.append(author_hit)
            fold_pooled.append(pooled_hit)
            fold_balanced.append(balanced_hit)
            all_author_correct.append(author_hit)
            all_pooled_correct.append(pooled_hit)
            all_balanced_correct.append(balanced_hit)
            paired_differences.append(author_hit - max(pooled_hit, balanced_hit))
            group = (event.topic_tag, event.actor_role)
            topic_role_author[group].append(author_hit)
            topic_role_pooled[group].append(pooled_hit)
            topic_role_balanced[group].append(balanced_hit)

        if not hard_available:
            fold_warnings.append(f"折 {author}/{holdout_work} 缺少同题材其他作者可预测策略")
        per_fold.append(
            {
                "author_id": author,
                "work_slot": holdout_work,
                "event_count": len(holdout),
                "candidate_count_distribution": dict(sorted(candidate_distribution.items())),
                "selected_action_distribution": dict(sorted(action_distribution.items())),
                "author_accuracy": round(sum(fold_author) / len(fold_author), 6),
                "pooled_majority_accuracy": round(sum(fold_pooled) / len(fold_pooled), 6),
                "class_balanced_accuracy": round(sum(fold_balanced) / len(fold_balanced), 6),
                "hard_negative_accuracy": round(sum(fold_hard) / len(fold_hard), 6) if fold_hard else 0.0,
                "training_work_count": len({event.work_slot for event in target_training}),
                "hard_negative_available": hard_available,
                "hard_negative_evaluable_event_count": hard_evaluable_count,
            }
        )

    if len(per_fold) != expected_fold_count or any(
        int(fold.get("event_count", 0)) == 0 for fold in per_fold
    ):
        reasons.append("L1WO 存在静默丢折或空留出折")
    # abstention/fallback 属于部署平面约束，不是 statistical INVALID 的结构违规。
    structural_reasons = list(reasons)
    if fallback_predictions:
        reasons.append("存在回退预测或情境统计不足")
    if not all_author_correct:
        reasons.append("无可评估事件")

    author_accuracy = _v2_macro(topic_role_author)
    pooled_accuracy = _v2_macro(topic_role_pooled)
    balanced_accuracy = _v2_macro(topic_role_balanced)
    hard_accuracy = _v2_macro(topic_role_hard)
    author_advantage = author_accuracy - max(pooled_accuracy, balanced_accuracy)
    hard_advantage = author_accuracy - hard_accuracy
    interval = _v2_ci(paired_differences)
    p_value = _v2_permutation_p(paired_differences)
    report_warnings = list(dict.fromkeys(fold_warnings))
    if not hard_differences or not all(
        int(fold.get("hard_negative_evaluable_event_count", 0)) == int(fold.get("event_count", 0))
        for fold in per_fold
    ):
        report_warnings.append("困难负样本不可评估")
    if author_advantage <= 0:
        report_warnings.append("作者策略未严格优于 pooled/class-balanced 基线")
    if hard_advantage <= 0:
        report_warnings.append("作者策略未产生同题材身份优势")
    if interval[0] <= 0:
        report_warnings.append("优势置信区间下界不大于 0")

    # v8 selective-coverage metrics use only the author prediction stream.
    total_events = len(all_author_correct)
    answered_events = total_events - abstentions
    coverage = answered_events / total_events if total_events else 0.0
    selective_risk = (
        (answered_events - answered_correct) / answered_events
        if answered_events
        else None
    )
    c_at_1 = (
        (answered_correct + abstentions * answered_correct / total_events) / total_events
        if total_events
        else None
    )
    # PAN F_{0.5u}: TP=correct answered, FN=wrong answered, U=abstention, FP=0.
    f_half_u = (
        1.25 * answered_correct
        / (1.25 * answered_correct + 0.25 * ((answered_events - answered_correct) + abstentions))
        if (1.25 * answered_correct + 0.25 * ((answered_events - answered_correct) + abstentions))
        else 0.0
    )
    # 离散前缀 risk-coverage 曲线：按 margin 降序逐步扩大 coverage。
    aurc = None
    if prediction_records:
        ordered_confidences = sorted(
            prediction_records,
            key=lambda item: (-float(item[0]), item[1]),
        )
        prefix_errors = 0
        area = 0.0
        previous_coverage = 0.0
        for index, (_, error) in enumerate(ordered_confidences, start=1):
            prefix_errors += int(error)
            current_coverage = index / total_events if total_events else 0.0
            area += (current_coverage - previous_coverage) * (prefix_errors / index)
            previous_coverage = current_coverage
        aurc = area

    structural_invalid = bool(structural_reasons)
    enough_hard_negative = all(
        int(fold.get("hard_negative_evaluable_event_count", 0)) == int(fold.get("event_count", 0))
        for fold in per_fold
    )
    statistical_reasons = list(structural_reasons)
    if operating_coverage is not None and coverage < operating_coverage:
        statistical_reasons.append(
            f"coverage {coverage:.6f} 低于预注册 operating_coverage {operating_coverage:.6f}"
        )
    statistical_state = "INVALID" if structural_invalid else "FAIL"
    if not structural_invalid:
        if operating_coverage is not None and coverage < operating_coverage:
            statistical_state = "FAIL"
        elif not enough_hard_negative:
            statistical_state = "PARTIAL"
        elif (
            author_advantage > 0
            and hard_advantage > 0
            and interval[0] > 0
            and author_accuracy > pooled_accuracy
            and author_accuracy > balanced_accuracy
        ):
            statistical_state = "PASS"
    result_state = "INVALID" if reasons else "FAIL"
    if not reasons:
        enough_hard_negative = all(
            int(fold.get("hard_negative_evaluable_event_count", 0)) == int(fold.get("event_count", 0))
            for fold in per_fold
        )
        if not enough_hard_negative:
            result_state = "PARTIAL"
        elif (
            author_advantage > 0
            and hard_advantage > 0
            and interval[0] > 0
            and author_accuracy > pooled_accuracy
            and author_accuracy > balanced_accuracy
        ):
            result_state = "PASS"

    result = ProxySignatureV2Result(
        state=result_state,
        statistical_state=statistical_state,
        full_coverage_deployment_state=(
            "PASS"
            if not abstentions and statistical_state == "PASS" and not statistical_reasons
            else "FAIL"
        ),
        coverage=coverage,
        selective_risk=selective_risk,
        aurc=aurc,
        c_at_1=c_at_1,
        f_half_u=f_half_u,
        backoff_used=backoff,
        backoff_events=backoff_events_used,
        operating_coverage=operating_coverage,
        per_fold=per_fold,
        baselines={
            "pooled_majority": round(pooled_accuracy, 6),
            "class_balanced": round(balanced_accuracy, 6),
        },
        author_accuracy=round(author_accuracy, 6),
        hard_negative_accuracy=round(hard_accuracy, 6),
        author_advantage=round(author_advantage, 6),
        hard_negative_advantage=round(hard_advantage, 6),
        confidence_interval=interval,
        permutation_p_value=p_value,
        invalid_reasons=list(
            dict.fromkeys(statistical_reasons if backoff != "none" else reasons)
        ),
        warnings=report_warnings,
        evaluated_event_count=len(all_author_correct),
        fold_count=len(per_fold),
        expected_fold_count=expected_fold_count,
        abstention_count=abstentions,
        fallback_prediction_count=fallback_predictions,
        holdout_leakage_detected=any("泄漏" in reason or "训练统计" in reason for reason in reasons),
        topic_alias_detected=any("别名" in reason for reason in reasons),
        candidate_order_bias_detected=any("候选顺序" in reason for reason in reasons),
    )
    # 报告宏平均明细，便于审计 topic/role 是否被单一大组掩盖。
    result.macro_by_topic_role = {
        f"{topic}/{role}": {
            "author": round(sum(topic_role_author[(topic, role)]) / len(topic_role_author[(topic, role)]), 6),
            "pooled_majority": round(sum(topic_role_pooled[(topic, role)]) / len(topic_role_pooled[(topic, role)]), 6),
            "class_balanced": round(sum(topic_role_balanced[(topic, role)]) / len(topic_role_balanced[(topic, role)]), 6),
            "hard_negative": (
                round(
                    sum(topic_role_hard[(topic, role)])
                    / len(topic_role_hard[(topic, role)]),
                    6,
                )
                if topic_role_hard[(topic, role)]
                else 0.0
            ),
        }
        for topic, role in sorted(topic_role_author)
    }
    return result


def _atomic_write_text(path: Path, content: str) -> None:
    """使用临时文件与原子替换写入文件，杜绝写入中断导致数据损坏."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = path.parent
    fd, temp_file = tempfile.mkstemp(prefix=f"{path.stem}_", suffix=".tmp", dir=temp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_file, path)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        raise


def load_author_model_v3(path_or_dir: Path) -> Optional[AuthorModelV3]:
    """从指定路径或目录读取 author_model_v3.json. 损坏文件将显式抛出异常."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "author_model_v3.json"
    if not p.exists():
        return None
    try:
        return AuthorModelV3.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted or invalid author_model_v3 at {p}: {exc}") from exc


def save_author_model_v3(path_or_dir: Path, model: AuthorModelV3) -> Path:
    """原子持久化保存 author_model_v3.json."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "author_model_v3.json"
    _atomic_write_text(p, model.model_dump_json(indent=2))
    return p


def load_qualification_report(path_or_dir: Path) -> Optional[CrossWorkValidationResult]:
    """读取跨作品留一验证资格报告 qualification_report.json. 损坏文件将显式抛出异常."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "qualification_report.json"
    if not p.exists():
        return None
    try:
        return CrossWorkValidationResult.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted or invalid qualification_report at {p}: {exc}") from exc


def save_qualification_report(path_or_dir: Path, report: CrossWorkValidationResult) -> Path:
    """原子持久化保存 qualification_report.json."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "qualification_report.json"
    _atomic_write_text(p, report.model_dump_json(indent=2))
    return p


def is_author_model_certified_for_production(
    author_model: Optional[AuthorModelV3],
    qualification_report: Optional[CrossWorkValidationResult],
) -> bool:
    """检查 AuthorModel 是否获得 L1WO 跨作品留一资格认证.

    只有在存在资格报告且 is_valid_author_prior=True 且无词汇泄露且准确率超基线时才认证.
    未认证前，任何生产链路必须保持 strict shadow-only 模式，不得改变生产决策.
    """
    if author_model is None or qualification_report is None:
        return False
    if qualification_report.author_id != author_model.author_id:
        return False
    return bool(
        qualification_report.is_valid_author_prior
        and not qualification_report.lexical_leakage_detected
        and qualification_report.choice_prediction_accuracy > qualification_report.baseline_accuracy
    )

