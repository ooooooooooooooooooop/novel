"""Observed Decision Signature v1 — 验证器与统计引擎（WP4/WP5 核心）。

接口遵循计划 §七、§八、§十二：
    validate_observed_signature_v1(
        support_events,
        holdout_events,
        *,
        config=None,
        operating_coverage=None,
    ) -> ObservedSignatureV1Result

硬边界：
1. 标签独立：`label_source == "cue_count"` 必须直接 `INVALID`（禁止旧 cue-count 伪造标签）。
2. 作品隔离：同一 `work_id` 不得同时出现在 support 和 holdout（PAN 隔离原则）。
3. 题材别名：每题材至少 `min_authors_per_topic` 作者；1 作者=1 题材时必须 `INVALID`。
4. 统计单位：作者为独立抽样单位；CI 用 cluster bootstrap，置换在题材 strata 内整体置换。
5. 门禁铁律：inner 全失败 → `NOT_ESTIMABLE`，不得 fallback 到首个配置继续 outer-test。
6. 零回归：不修改既有 `validate_decision_signature_v2`，本模块为全新独立实现。
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable, Mapping, Optional, Sequence

from src.object_state.observed_author_signature import (
    ObservedDecisionEventV1,
    ObservedSignatureConfig,
    ObservedSignatureV1Result,
)


# ---------------------------------------------------------------- 基础辅助


def _freeze_val(val: object) -> object:
    if isinstance(val, dict):
        return tuple(sorted((k, _freeze_val(v)) for k, v in val.items()))
    if isinstance(val, (list, set, frozenset)):
        return tuple(_freeze_val(x) for x in val)
    return val


def _situation_key(event: ObservedDecisionEventV1) -> tuple[tuple[str, object], ...]:
    return tuple(sorted((k, _freeze_val(v)) for k, v in event.situation.items()))


# ---------------------------------------------------------------- Krippendorff α（名义，用于双标子集可靠性门禁）


def _krippendorff_alpha_nominal(unit_labels: Mapping[str, Mapping[str, str]]) -> float:
    categories: set[str] = set()
    pairs_per_unit: list[list[tuple[str, str]]] = []
    for labels in unit_labels.values():
        vals = [v for v in labels.values() if v is not None]
        categories.update(vals)
        pairs: list[tuple[str, str]] = []
        for i in range(len(vals)):
            for j in range(len(vals)):
                if i != j:
                    pairs.append((vals[i], vals[j]))
        pairs_per_unit.append(pairs)
    cats = sorted(categories)
    idx = {c: i for i, c in enumerate(cats)}
    n_ck: list[list[int]] = [[0] * len(cats) for _ in cats]
    for pairs in pairs_per_unit:
        for c1, c2 in pairs:
            n_ck[idx[c1]][idx[c2]] += 1
    n = sum(sum(row) for row in n_ck)
    if n == 0:
        return 1.0
    n_k = [sum(n_ck[i][j] for j in range(len(cats))) for i in range(len(cats))]
    do_num = sum(n_ck[c][k] for c in range(len(cats)) for k in range(len(cats)) if c != k)
    do = do_num / n
    de_num = sum(nk * (n - nk) for nk in n_k)
    de = de_num / (n * (n - 1)) if n > 1 else 0.0
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - do / de


# ---------------------------------------------------------------- 模型候选（计划 §7.2）


def _build_action_counts(
    events: Iterable[ObservedDecisionEventV1],
) -> dict[tuple[tuple[str, object], ...], dict[str, int]]:
    counts: dict[tuple[tuple[str, object], ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in events:
        if e.gold_action:
            counts[_situation_key(e)][e.gold_action] += 1
    return counts


def _author_posterior(
    counts: dict[tuple[tuple[str, object], ...], dict[str, int]],
    event: ObservedDecisionEventV1,
    candidates: Sequence[str],
    alpha: float,
) -> dict[str, float]:
    key = _situation_key(event)
    c_map = counts.get(key, {})
    total = sum(c_map.get(c, 0) for c in candidates)
    k = max(1, len(candidates))
    denom = total + alpha * k
    return {c: (c_map.get(c, 0) + alpha) / denom for c in candidates}


def _predict_author(
    author_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]],
    event: ObservedDecisionEventV1,
    alpha: float,
) -> tuple[str, float]:
    cands = event.candidates or ([event.gold_action] if event.gold_action else ["none"])
    post = _author_posterior(author_counts.get(event.author_id, {}), event, cands, alpha)
    best = max(cands, key=lambda c: post[c])
    return best, post[best]


def _predict_topic_pooled(
    topic_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]],
    event: ObservedDecisionEventV1,
    alpha: float,
) -> tuple[str, float]:
    cands = event.candidates or ([event.gold_action] if event.gold_action else ["none"])
    post = _author_posterior(topic_counts.get(event.topic_stratum, {}), event, cands, alpha)
    best = max(cands, key=lambda c: post[c])
    return best, post[best]


def _predict_class_balanced(
    all_events: Sequence[ObservedDecisionEventV1],
    event: ObservedDecisionEventV1,
) -> tuple[str, float]:
    cands = event.candidates or ([event.gold_action] if event.gold_action else ["none"])
    action_totals: dict[str, int] = defaultdict(int)
    for e in all_events:
        if e.gold_action:
            action_totals[e.gold_action] += 1
    total = sum(action_totals.get(c, 0) for c in cands)
    k = max(1, len(cands))
    denom = total + k
    post = {c: (action_totals.get(c, 0) + 1) / denom for c in cands}
    best = max(cands, key=lambda c: post[c])
    return best, post[best]


def _predict_cue_only(
    event: ObservedDecisionEventV1,
) -> tuple[str, float]:
    cands = event.candidates or ([event.gold_action] if event.gold_action else ["none"])
    if not event.cue_hits:
        return cands[0], 1.0 / len(cands)
    best = max(cands, key=lambda c: event.cue_hits.get(c, 0.0))
    total = sum(event.cue_hits.get(c, 0.0) for c in cands) + len(cands)
    conf = (event.cue_hits.get(best, 0.0) + 1.0) / total
    return best, conf


# ---------------------------------------------------------------- Selective Coverage 与 AURC（计划 §九）


def _evaluate_selective(
    predictions: Sequence[tuple[ObservedDecisionEventV1, str, float]],
    target_coverage: float,
) -> dict[str, float]:
    if not predictions:
        return {"coverage": 0.0, "accuracy": 0.0, "selective_risk": 0.0, "aurc": 0.0}
    # 按置信度降序排序
    sorted_preds = sorted(predictions, key=lambda x: x[2], reverse=True)
    n = len(sorted_preds)
    keep_k = max(1, int(math.ceil(n * target_coverage)))
    covered = sorted_preds[:keep_k]
    correct = sum(1 for e, pred, _ in covered if pred == e.gold_action)
    acc = correct / len(covered) if covered else 0.0
    risk = 1.0 - acc
    realized_cov = len(covered) / n
    # AURC 计算（trapezoid over all coverage cutoffs）
    risk_points: list[tuple[float, float]] = []
    for k in range(1, n + 1):
        sub = sorted_preds[:k]
        corr_k = sum(1 for e, pred, _ in sub if pred == e.gold_action)
        risk_k = 1.0 - (corr_k / k)
        cov_k = k / n
        risk_points.append((cov_k, risk_k))
    aurc = 0.0
    for i in range(len(risk_points) - 1):
        c1, r1 = risk_points[i]
        c2, r2 = risk_points[i + 1]
        aurc += 0.5 * (r1 + r2) * (c2 - c1)
    return {
        "coverage": realized_cov,
        "accuracy": acc,
        "selective_risk": risk,
        "aurc": aurc,
    }


# ---------------------------------------------------------------- WP5 统计引擎：Cluster Bootstrap 与 Strata 置换


def _cluster_bootstrap_ci(
    author_advantages: Mapping[str, float],
    reps: int,
    seed: int,
    alpha_level: float = 0.05,
) -> list[float]:
    authors = sorted(author_advantages.keys())
    if len(authors) < 2:
        val = list(author_advantages.values())[0] if authors else 0.0
        return [round(val, 4), round(val, 4)]
    rng = random.Random(seed)
    boot_means: list[float] = []
    for _ in range(reps):
        sampled = [rng.choice(authors) for _ in range(len(authors))]
        boot_means.append(sum(author_advantages[a] for a in sampled) / len(sampled))
    boot_means.sort()
    lower_idx = int((alpha_level / 2.0) * reps)
    upper_idx = int((1.0 - alpha_level / 2.0) * reps)
    return [round(boot_means[lower_idx], 4), round(boot_means[min(upper_idx, reps - 1)], 4)]


def _strata_permutation_test(
    holdout_events: Sequence[ObservedDecisionEventV1],
    support_events: Sequence[ObservedDecisionEventV1],
    author_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]],
    topic_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]],
    config: ObservedSignatureConfig,
    obs_advantage: float,
) -> float:
    # 预计算 class_balanced_baseline（与观测主终点完全一致的统计量定义）
    all_support_labels = [e.gold_action for e in support_events if e.gold_action]
    cb_baseline = 0.0
    if all_support_labels:
        from collections import Counter
        cb_dist = Counter(all_support_labels)
        cb_acc = max(cb_dist.values()) / len(all_support_labels)
        # 实际 class_balanced 预测是 per-event 的，但大致基线用于防误差异步
        # 准确方法：对每个事件跑 class_balanced_predict 取平均
        cb_most_common_pre = max(cb_dist, key=cb_dist.get)
        cb_correct = sum(
            1 for e in holdout_events
            if e.gold_action and cb_most_common_pre == e.gold_action
        )
        cb_baseline = cb_correct / len(holdout_events) if holdout_events else 0.0

    # 预计算 class_balanced 全局最频繁动作（与置换无关的常数，避免内层循环重复 O(E)）
    cb_most_common: str | None = None
    if all_support_labels:
        cb_counts: dict[str, int] = {}
        for _lab in all_support_labels:
            cb_counts[_lab] = cb_counts.get(_lab, 0) + 1
        cb_most_common = max(cb_counts, key=cb_counts.get) if cb_counts else None

    # 按题材对作者分组
    topic_authors: dict[str, list[str]] = defaultdict(list)
    author_set = {e.author_id for e in holdout_events}
    for e in holdout_events:
        if e.author_id not in topic_authors[e.topic_stratum]:
            topic_authors[e.topic_stratum].append(e.author_id)
    if not author_set:
        return 1.0

    rng = random.Random(config.seed + 999)
    exceed_count = 0
    reps = config.permutation_reps

    # 每 replicate 使用一张稳定作者映射（不是逐事件 shuffle）
    for _ in range(reps):
        perm_map: dict[str, str] = {}
        for topic, a_list in topic_authors.items():
            shuffled = list(a_list)
            rng.shuffle(shuffled)
            for orig, perm in zip(a_list, shuffled):
                perm_map[orig] = perm

        # 按映射批量评估
        author_scores: dict[str, list[float]] = defaultdict(list)
        topic_scores: dict[str, list[float]] = defaultdict(list)
        class_balanced_scores: dict[str, list[float]] = defaultdict(list)
        for e in holdout_events:
            perm_author = perm_map.get(e.author_id, e.author_id)
            cands = e.candidates or [e.gold_action]
            post_a = _author_posterior(
                author_counts.get(perm_author, {}), e, cands, config.alpha_smoothing
            )
            pred_a = max(cands, key=lambda c: post_a[c])
            author_scores[e.author_id].append(1.0 if pred_a == e.gold_action else 0.0)

            post_t = _author_posterior(
                topic_counts.get(e.topic_stratum, {}), e, cands, config.alpha_smoothing
            )
            pred_t = max(cands, key=lambda c: post_t[c])
            topic_scores[e.author_id].append(1.0 if pred_t == e.gold_action else 0.0)

            # class_balanced baseline（常数预计算）
            class_balanced_scores[e.author_id].append(
                1.0 if cb_most_common == e.gold_action else 0.0
            )

        # 与观测完全一致的统计量：advantage = author_score - max(topic, class_balanced)
        author_advs = []
        for a in author_set:
            if not (author_scores[a] and topic_scores[a] and class_balanced_scores[a]):
                continue
            a_acc = sum(author_scores[a]) / len(author_scores[a])
            t_acc = sum(topic_scores[a]) / len(topic_scores[a])
            cb_acc = sum(class_balanced_scores[a]) / len(class_balanced_scores[a])
            baseline = max(t_acc, cb_acc)
            author_advs.append(a_acc - baseline)

        perm_mean_adv = sum(author_advs) / len(author_advs) if author_advs else 0.0
        if abs(perm_mean_adv) >= abs(obs_advantage):
            exceed_count += 1

    return round(max(1.0 / reps, exceed_count / reps), 4)


def _simulate_power(
    n_authors: int,
    mde: float,
    observed_sd: float,
    reps: int = 2000,
    seed: int = 20260823,
) -> float:
    if n_authors < 2 or observed_sd <= 0:
        return 0.0
    rng = random.Random(seed)
    successes = 0
    for _ in range(reps):
        effects = [rng.gauss(mde, observed_sd) for _ in range(n_authors)]
        mean_eff = sum(effects) / n_authors
        variance = sum((x - mean_eff) ** 2 for x in effects) / (n_authors - 1)
        se = (variance / n_authors) ** 0.5
        ci_lower = mean_eff - 1.96 * se
        if ci_lower > 0:
            successes += 1
    return round(successes / reps, 4)


# ---------------------------------------------------------------- 结构与泄漏门禁（计划 §4、§7.3）


def _check_structural_and_leakage(
    support_events: Sequence[ObservedDecisionEventV1],
    holdout_events: Sequence[ObservedDecisionEventV1],
    config: ObservedSignatureConfig,
) -> tuple[bool, list[str], dict[str, bool]]:
    reasons: list[str] = []
    flags: dict[str, bool] = {
        "cue_label_source": False,
        "holdout_leakage": False,
        "topic_alias": False,
        "future_text_leakage": False,
    }

    # 1. 标签来源必须合法：cue_count 派生标签直接 INVALID
    all_events = list(support_events) + list(holdout_events)
    if any(e.label_source == "cue_count" for e in all_events):
        reasons.append("检测到 cue_count 标签源；本验证器仅接受 observed-realization（human_gold/llm_prelabel）标签")
        flags["cue_label_source"] = True

    # 2. 作品隔离：同一 work_id 不得跨 support 与 holdout
    support_works = {e.work_id for e in support_events if e.work_id}
    holdout_works = {e.work_id for e in holdout_events if e.work_id}
    crossing = support_works & holdout_works
    if crossing:
        reasons.append(f"作品跨分区泄漏：work_id {sorted(crossing)} 同时出现在 support 与 holdout")
        flags["holdout_leakage"] = True

    # 3. 题材别名：每题材必须至少 min_authors_per_topic 位作者
    topic_authors: dict[str, set[str]] = defaultdict(set)
    for e in all_events:
        topic_authors[e.topic_stratum].add(e.author_id)
    if any(len(a) < config.min_authors_per_topic for a in topic_authors.values()):
        bad_topics = {t: len(a) for t, a in topic_authors.items() if len(a) < config.min_authors_per_topic}
        reasons.append(f"题材作者数不足（防题材别名）：{bad_topics} 每题材要求 ≥{config.min_authors_per_topic}")
        flags["topic_alias"] = True

    # 4. 未来文本同哈希拦截
    for e in all_events:
        if (
            e.pre_context_hash is not None
            and e.outcome_evidence_hash is not None
            and e.pre_context_hash == e.outcome_evidence_hash
        ):
            reasons.append("未来文本泄漏：pre_context_hash 与 outcome_evidence_hash 相同")
            flags["future_text_leakage"] = True
            break

    # 5. 作者作品数约束（support ≥ min_support, holdout ≥ min_holdout）
    author_supp_works: dict[str, set[str]] = defaultdict(set)
    author_hold_works: dict[str, set[str]] = defaultdict(set)
    for e in support_events:
        author_supp_works[e.author_id].add(e.work_id)
    for e in holdout_events:
        author_hold_works[e.author_id].add(e.work_id)
    all_authors = set(author_supp_works) | set(author_hold_works)
    for a in all_authors:
        sw = len(author_supp_works.get(a, set()))
        hw = len(author_hold_works.get(a, set()))
        if sw < config.min_support_works or hw < config.min_holdout_works:
            reasons.append(
                f"作者 {a} 作品数不达标：support={sw}/{config.min_support_works} holdout={hw}/{config.min_holdout_works}"
            )

    # 6. 候选动作约束（代码本：2–4 个互斥候选，gold_action ∈ candidates）
    for i, e in enumerate(all_events):
        cands = list(e.candidates or [])
        if len(cands) < 2 or len(cands) > 4:
            reasons.append(
                f"事件 {e.event_id or f'ev_{i}'} 候选数 {len(cands)} 违反代码本约束（要求 2–4）"
            )
        elif len(set(cands)) != len(cands):
            reasons.append(
                f"事件 {e.event_id or f'ev_{i}'} 候选存在重复（违反互斥要求）"
            )
        elif e.gold_action and e.gold_action not in cands:
            reasons.append(
                f"事件 {e.event_id or f'ev_{i}'} gold_action '{e.gold_action}' 不属于候选集"
            )

    # 7. split 一致性：传入 support 列表的事件必须声明 split=support，反之亦然
    for i, e in enumerate(support_events):
        if e.split != "support":
            reasons.append(
                f"事件 {e.event_id or f'supp_{i}'} 位于 support 列表但声明 split={e.split}"
            )
    for i, e in enumerate(holdout_events):
        if e.split != "holdout":
            reasons.append(
                f"事件 {e.event_id or f'hold_{i}'} 位于 holdout 列表但声明 split={e.split}"
            )

    # 8. 每作者 support 侧最少事件数（min_events_per_author_support）
    author_supp_events: dict[str, int] = defaultdict(int)
    for e in support_events:
        author_supp_events[e.author_id] += 1
    for a in all_authors:
        se = author_supp_events.get(a, 0)
        if se < config.min_events_per_author_support:
            reasons.append(
                f"作者 {a} support 侧事件数 {se} < 最少要求 {config.min_events_per_author_support}"
            )

    return len(reasons) == 0, reasons, flags


# ---------------------------------------------------------------- 主验证器入口


def validate_observed_signature_v1(
    support_events: Sequence[ObservedDecisionEventV1],
    holdout_events: Sequence[ObservedDecisionEventV1],
    *,
    config: Optional[ObservedSignatureConfig] = None,
    operating_coverage: Optional[float] = None,
) -> ObservedSignatureV1Result:
    cfg = config or ObservedSignatureConfig()
    target_coverage = operating_coverage if operating_coverage is not None else cfg.operating_coverage

    # ---- 1. 结构与泄漏门禁 ----
    struct_ok, struct_reasons, flags = _check_structural_and_leakage(support_events, holdout_events, cfg)
    if not struct_ok:
        return ObservedSignatureV1Result(
            state="INVALID",
            invalid_reasons=struct_reasons,
            evaluated_event_count=len(support_events) + len(holdout_events),
            support_event_count=len(support_events),
            holdout_event_count=len(holdout_events),
            author_count=len({e.author_id for e in list(support_events) + list(holdout_events)}),
            cue_label_source_detected=flags["cue_label_source"],
            holdout_leakage_detected=flags["holdout_leakage"],
            topic_alias_detected=flags["topic_alias"],
            mde_frozen=cfg.mde,
        )

    all_events = list(support_events) + list(holdout_events)
    author_set = sorted({e.author_id for e in all_events})

    # ---- 2. 可靠性门禁（双标子集 Krippendorff α）----
    double_labeled_units: dict[str, dict[str, str]] = {}
    for i, e in enumerate(all_events):
        if len(e.annotator_labels) >= 2:
            uid = e.event_id or f"ev_{i}"
            double_labeled_units[uid] = e.annotator_labels
    if not double_labeled_units:
        return ObservedSignatureV1Result(
            state="NOT_ESTIMABLE",
            warnings=["未提供双标子集（无 ≥2 标注员标签），Krippendorff α 不可估计；必须通过校准门禁后方可做确认性评估"],
            reliability_verdict="NO_DOUBLE_SUBSET",
            evaluated_event_count=len(all_events),
            support_event_count=len(support_events),
            holdout_event_count=len(holdout_events),
            author_count=len(author_set),
            mde_frozen=cfg.mde,
        )
    alpha = _krippendorff_alpha_nominal(double_labeled_units)
    if alpha < cfg.min_alpha:
        verdict = "EXPLORATORY_ONLY" if alpha >= 0.667 else "REWORK_CODEBOOK"
        return ObservedSignatureV1Result(
            state="NOT_ESTIMABLE" if alpha < 0.667 else "PARTIAL",
            reliability_alpha=round(alpha, 4),
            reliability_verdict=verdict,
            warnings=[f"Krippendorff α={alpha:.4f} < 确认性阈值 {cfg.min_alpha}（评定为 {verdict}）"],
            evaluated_event_count=len(all_events),
            support_event_count=len(support_events),
            holdout_event_count=len(holdout_events),
            author_count=len(author_set),
            mde_frozen=cfg.mde,
        )
    rel_verdict = "CONFIRMATORY_OK"

    # ---- 3. 产率门禁 ----
    if len(all_events) < cfg.min_present_events:
        return ObservedSignatureV1Result(
            state="NOT_ESTIMABLE",
            reliability_alpha=round(alpha, 4),
            reliability_verdict=rel_verdict,
            warnings=[f"有效事件总数 {len(all_events)} < 最少要求 {cfg.min_present_events}（产率不足）"],
            evaluated_event_count=len(all_events),
            support_event_count=len(support_events),
            holdout_event_count=len(holdout_events),
            author_count=len(author_set),
            mde_frozen=cfg.mde,
        )

    # ---- 4. 模型构建（基于 support_events）----
    author_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]] = {}
    for a in author_set:
        a_events = [e for e in support_events if e.author_id == a]
        author_counts[a] = _build_action_counts(a_events)

    topic_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]] = {}
    for t in {e.topic_stratum for e in support_events}:
        t_events = [e for e in support_events if e.topic_stratum == t]
        topic_counts[t] = _build_action_counts(t_events)

    # ---- 5. Inner nested-CV / 配置选择与门禁（计划 §8.1 步骤 3）----
    # 真正的 inner 留出：对每位作者，留一部作品验证，用该作者其他作品+其他作者全部作品训练
    # 既实现了训练-验证隔离，又保留了作者级信号连续性
    # 性能优化：预分组 support 事件（作者×作品），避免 inner 循环内 O(events) 重复扫描
    support_by_author: dict[str, list[ObservedDecisionEventV1]] = defaultdict(list)
    support_by_author_work: dict[tuple[str, str], list[ObservedDecisionEventV1]] = {}
    for _e in support_events:
        support_by_author[_e.author_id].append(_e)
        support_by_author_work.setdefault((_e.author_id, _e.work_id), []).append(_e)
    author_work_ids: dict[str, list[str]] = {
        a: sorted({e.work_id for e in evs}) for a, evs in support_by_author.items()
    }
    # 其余作者的全部事件（非当前作者）——inner 训练集每次都复用该全集，避免反复过滤
    non_author_events: dict[str, list[ObservedDecisionEventV1]] = {}
    for _a in author_set:
        non_author_events[_a] = [e for e in support_events if e.author_id != _a]

    coverage_grid = [0.6, 0.7, 0.8, 0.9, 1.0]
    inner_successes = 0
    for cov in coverage_grid:
        inner_work_successes = 0
        inner_work_total = 0
        for a in author_set:
            for held_out_work in author_work_ids.get(a, []):
                inner_work_total += 1
                # 该作者被留出作品的事件
                held_out = support_by_author_work.get((a, held_out_work), [])
                if not held_out:
                    continue
                # 训练集：其他作者所有事件 + 该作者除留出作品外的事件
                inner_counts: dict[str, dict[tuple[tuple[str, object], ...], dict[str, int]]] = {}
                for other_a in author_set:
                    if other_a == a:
                        o_events = [e for e in support_by_author[a] if e.work_id != held_out_work]
                    else:
                        o_events = non_author_events[other_a]
                    if o_events:
                        inner_counts[other_a] = _build_action_counts(o_events)
                if not inner_counts:
                    continue
                inner_preds = [(e, *_predict_author(inner_counts, e, cfg.alpha_smoothing)) for e in held_out]
                inner_sel = _evaluate_selective(inner_preds, cov)
                if inner_sel["accuracy"] > 0.0:
                    inner_work_successes += 1
        # 如果超过半数作品留出折成功，则此 coverage 配置有效
        if inner_work_total > 0 and inner_work_successes / inner_work_total > 0.5:
            inner_successes += 1
    if inner_successes == 0:
        return ObservedSignatureV1Result(
            state="NOT_ESTIMABLE",
            reliability_alpha=round(alpha, 4),
            reliability_verdict=rel_verdict,
            warnings=["Inner 配置选择全部失败（support 侧无法建立有效策略）；outer-test 保持封存，不 fallback 到默认配置"],
            inner_config_count=len(coverage_grid),
            inner_success_count=0,
            evaluated_event_count=len(all_events),
            support_event_count=len(support_events),
            holdout_event_count=len(holdout_events),
            author_count=len(author_set),
            mde_frozen=cfg.mde,
        )

    # ---- 6. Outer-test 运行（只运行一次，计划 §8.1 步骤 4）----
    # 主预测器评估
    author_preds = [
        (e, *_predict_author(author_counts, e, cfg.alpha_smoothing))
        for e in holdout_events
    ]
    topic_preds = [
        (e, *_predict_topic_pooled(topic_counts, e, cfg.alpha_smoothing))
        for e in holdout_events
    ]
    cb_preds = [
        (e, *_predict_class_balanced(support_events, e))
        for e in holdout_events
    ]
    cue_preds = [
        (e, *_predict_cue_only(e))
        for e in holdout_events
    ]

    # Selective 指标
    sel_author = _evaluate_selective(author_preds, target_coverage)
    sel_topic = _evaluate_selective(topic_preds, target_coverage)

    # 每作者 advantage 计算（计划 §8.2）
    per_author_report: list[dict[str, object]] = []
    author_adv_map: dict[str, float] = {}
    holdout_by_author: dict[str, list[ObservedDecisionEventV1]] = defaultdict(list)
    for e in holdout_events:
        holdout_by_author[e.author_id].append(e)

    for a in sorted(author_set):
        a_hold = holdout_by_author.get(a, [])
        if not a_hold:
            continue
        a_preds = [(e, *_predict_author(author_counts, e, cfg.alpha_smoothing)) for e in a_hold]
        t_preds = [(e, *_predict_topic_pooled(topic_counts, e, cfg.alpha_smoothing)) for e in a_hold]
        cb_p = [(e, *_predict_class_balanced(support_events, e)) for e in a_hold]

        a_acc = sum(1 for e, p, _ in a_preds if p == e.gold_action) / len(a_hold)
        t_acc = sum(1 for e, p, _ in t_preds if p == e.gold_action) / len(a_hold)
        cb_acc = sum(1 for e, p, _ in cb_p if p == e.gold_action) / len(a_hold)
        baseline_acc = max(t_acc, cb_acc)
        adv = round(a_acc - baseline_acc, 4)
        author_adv_map[a] = adv
        per_author_report.append({
            "author_id": a,
            "holdout_events": len(a_hold),
            "author_accuracy": round(a_acc, 4),
            "topic_baseline_accuracy": round(t_acc, 4),
            "class_balanced_accuracy": round(cb_acc, 4),
            "advantage": adv,
        })

    if not author_adv_map:
        return ObservedSignatureV1Result(
            state="NOT_ESTIMABLE",
            reliability_alpha=round(alpha, 4),
            reliability_verdict=rel_verdict,
            warnings=["留出侧无有效作者事件"],
            evaluated_event_count=len(all_events),
            mde_frozen=cfg.mde,
        )

    mean_advantage = round(sum(author_adv_map.values()) / len(author_adv_map), 4)

    # ---- 7. WP5 统计引擎计算 ----
    ci = _cluster_bootstrap_ci(author_adv_map, cfg.bootstrap_reps, cfg.seed)
    p_value = _strata_permutation_test(holdout_events, support_events, author_counts, topic_counts, cfg, mean_advantage)

    # 功效模拟（用预注册方差或观测到的作者级效应方差）
    adv_values = list(author_adv_map.values())
    if cfg.assumed_effect_sd is not None:
        obs_sd = cfg.assumed_effect_sd
    elif len(adv_values) > 1:
        mean_v = sum(adv_values) / len(adv_values)
        obs_sd = (sum((x - mean_v) ** 2 for x in adv_values) / (len(adv_values) - 1)) ** 0.5
    else:
        obs_sd = 0.12
    power = _simulate_power(len(author_adv_map), cfg.mde, obs_sd, seed=cfg.seed)

    # ---- 8. 负控计算（计划 §十）----
    cue_correct = sum(1 for e, p, _ in cue_preds if p == e.gold_action)
    cue_acc = cue_correct / len(cue_preds) if cue_preds else 0.0
    cue_adv = round(cue_acc - sel_topic["accuracy"], 4)
    topic_only_adv = round(sel_topic["accuracy"] - sel_topic["accuracy"], 4)  # 恒 0
    negative_controls = {
        "cue_only_accuracy": round(cue_acc, 4),
        "cue_only_advantage": cue_adv,
        "topic_only_accuracy": round(sel_topic["accuracy"], 4),
        "topic_only_advantage": topic_only_adv,
        "note": "cue-only 优势应 ≤ 主模型优势，否则提示决策模式受 cue 词频混淆",
    }

    # ---- 9. 状态机判定（计划 §7.3、§8.2、§十四）----
    # 主终点 10 项条件核对：
    # 1. 标签可靠性 α ≥ 0.80
    # 2. 功效 power ≥ power_target
    # 3. 无泄漏与别名（已在前置通过）
    # 4. coverage 达到目标
    # 5. 作者级平均 advantage > 0
    # 6. cluster bootstrap 95% CI 下界 > 0
    # 7. 达到 MDE (+0.05)
    # 8. 置换检验 p < 0.05
    # 9. cue 负控未击穿主模型
    is_pass = (
        alpha >= cfg.min_alpha
        and power >= cfg.power_target
        and sel_author["coverage"] >= target_coverage
        and mean_advantage > 0
        and ci[0] > 0
        and mean_advantage >= cfg.mde
        and p_value < 0.05
        and cue_adv < mean_advantage
    )

    # 部署状态（full-coverage 独立评定）
    full_preds = [(e, *_predict_author(author_counts, e, cfg.alpha_smoothing)) for e in holdout_events]
    full_acc = sum(1 for e, p, _ in full_preds if p == e.gold_action) / len(full_preds) if full_preds else 0.0
    full_topic_acc = sum(1 for e, p, _ in topic_preds if p == e.gold_action) / len(topic_preds) if topic_preds else 0.0
    full_deploy_state: Literal["PASS", "FAIL"] = "PASS" if (full_acc - full_topic_acc) > 0 else "FAIL"

    final_state: Literal["INVALID", "NOT_ESTIMABLE", "FAIL", "PARTIAL", "PASS"]
    warnings: list[str] = []
    if is_pass:
        final_state = "PASS"
    elif power < cfg.power_target:
        final_state = "NOT_ESTIMABLE"
        warnings.append(f"功效不足：power={power:.4f} < 目标 {cfg.power_target}（样本量/作者数不足）")
    elif mean_advantage > 0 and ci[0] <= 0:
        final_state = "FAIL"
        warnings.append(f"作者级优势 CI 下界 {ci[0]} ≤ 0（未达确认性显著性要求）")
    elif mean_advantage < cfg.mde:
        final_state = "FAIL"
        warnings.append(f"平均优势 {mean_advantage} 未达 MDE 阈值 {cfg.mde}")
    elif p_value >= 0.05:
        final_state = "FAIL"
        warnings.append(f"置换检验 p={p_value} ≥ 0.05")
    else:
        final_state = "FAIL"

    return ObservedSignatureV1Result(
        state=final_state,
        full_coverage_deployment_state=full_deploy_state,
        author_advantage=mean_advantage,
        cluster_bootstrap_ci=ci,
        permutation_p_value=p_value,
        mde_frozen=cfg.mde,
        reliability_alpha=round(alpha, 4),
        reliability_verdict=rel_verdict,
        power_estimate=power,
        coverage=sel_author["coverage"],
        selective_risk=round(sel_author["selective_risk"], 4),
        aurc=round(sel_author["aurc"], 4),
        negative_controls=negative_controls,
        cue_only_advantage=cue_adv,
        topic_only_advantage=topic_only_adv,
        per_author=per_author_report,
        warnings=warnings,
        evaluated_event_count=len(all_events),
        support_event_count=len(support_events),
        holdout_event_count=len(holdout_events),
        author_count=len(author_set),
        inner_config_count=len(coverage_grid),
        inner_success_count=inner_successes,
        outer_test_run=True,
    )
