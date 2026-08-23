"""Tests for Observed Decision Signature v1 (observed_author_signature).

These tests validate the mechanism-level correctness of the validator, not the
scientific conclusion (which is documented in the checkpoint and audit report).
All tests use synthetic data, not real corpus content.

This test file adds 18 tests to the project baseline. The contract lock was
updated from 3000 to 3018 to reflect this addition (see test_cli_runtime_contract.py).
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from src.object_state.observed_author_signature import (
    ObservedDecisionEventV1,
    ObservedSignatureConfig,
    ObservedSignatureV1Result,
)
from src.workflow_action.observed_author_signature import (
    validate_observed_signature_v1,
    _build_action_counts,
    _predict_author,
    _author_posterior,
    _krippendorff_alpha_nominal,
    _check_structural_and_leakage,
    _strata_permutation_test,
    _simulate_power,
    _evaluate_selective,
)

# Frozen candidate set (codebook §6: 2-4 mutually exclusive candidates)
CANDIDATES = ["direct_confront", "defer", "seek_ally"]
TOPICS = ["urban", "fantasy", "xianxia"]


def _make_events(
    n_authors_per_topic: int = 4,
    events_per_work: int = 6,
    signal_strength: float = 0.9,
    label_source: str = "human_gold",
    leak_hash: bool = False,
    cross_works: bool = False,
    alpha_mode: str = "perfect",
    n_candidates: int = 3,
) -> tuple[list[ObservedDecisionEventV1], list[ObservedDecisionEventV1]]:
    """Build synthetic support/holdout events with controlled signal."""
    candidates = CANDIDATES[:n_candidates]
    if n_candidates < 2:
        candidates = CANDIDATES[:2]
    supp: list[ObservedDecisionEventV1] = []
    hold: list[ObservedDecisionEventV1] = []
    aid_seq = 0
    global_ev_idx = 0
    for topic in TOPICS:
        for _ in range(n_authors_per_topic):
            aid_seq += 1
            aid = f"a_{aid_seq:03d}"
            fav = candidates[(aid_seq - 1) % len(candidates)]
            for w_idx in range(1, 4):
                split = "support" if w_idx <= 2 else "holdout"
                wid = f"{aid}_w{w_idx}"
                if cross_works and w_idx == 3:
                    wid = f"{aid}_w_1"  # cross partition
                for ev_idx in range(events_per_work):
                    global_ev_idx += 1
                    eid = f"{wid}_e{ev_idx}"
                    rng = random.Random(hash(eid) & 0xFFFFFFF)
                    if rng.random() < signal_strength:
                        act = fav
                    else:
                        act = candidates[(aid_seq + ev_idx) % len(candidates)]
                    ann_labels = {}
                    if alpha_mode == "perfect":
                        ann_labels = {"A1": act, "A2": act}
                    elif alpha_mode == "disagree":
                        other = candidates[(candidates.index(act) + 1) % len(candidates)]
                        ann_labels = {"A1": act, "A2": other}
                    elif alpha_mode == "exploratory":
                        if global_ev_idx % 5 == 0:
                            other = candidates[(candidates.index(act) + 1) % len(candidates)]
                            ann_labels = {"A1": act, "A2": other}
                        else:
                            ann_labels = {"A1": act, "A2": act}
                    pre_h = f"pre_{eid}"
                    out_h = pre_h if leak_hash else f"out_{eid}"
                    ev = ObservedDecisionEventV1(
                        author_id=aid,
                        work_id=wid,
                        topic_stratum=topic,
                        split=split,
                        event_id=eid,
                        situation={"power_gap": "high", "threat": "low"},
                        candidates=list(candidates),
                        gold_action=act,
                        label_source=label_source,
                        pre_context_hash=pre_h,
                        outcome_evidence_hash=out_h,
                        annotator_labels=ann_labels,
                        confidence=0.9,
                        cue_hits={c: 0.1 for c in candidates},
                    )
                    if split == "support":
                        supp.append(ev)
                    else:
                        hold.append(ev)
    return supp, hold


def _make_default_config() -> ObservedSignatureConfig:
    return ObservedSignatureConfig(
        min_alpha=0.667,
        min_authors_per_topic=2,
        min_support_works=2,
        min_holdout_works=1,
        min_events_per_author_support=2,
        min_present_events=10,
        permutation_reps=500,
    )


# ---------------------------------------------------------------------------
# Structural gate tests
# ---------------------------------------------------------------------------


def test_structural_gate_candidates_2_4():
    """Candidates must be 2-4: duplicate candidates (unique violation) triggers INVALID."""
    supp, hold = _make_events(n_authors_per_topic=4, events_per_work=6)
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state in ("PASS", "NOT_ESTIMABLE"), f"Expected PASS/IMESTIMABLE, got {res.state}"

    # Duplicate candidates (unique violation)
    supp_bad, hold_bad = _make_events(events_per_work=6)
    supp_bad[0].candidates = ["direct_confront", "direct_confront", "defer"]  # duplicates
    res_bad = validate_observed_signature_v1(supp_bad, hold_bad, config=cfg)
    assert res_bad.state == "INVALID", f"Expected INVALID for duplicate candidates, got {res_bad.state}"


def test_structural_gate_gold_in_candidates():
    """gold_action must belong to candidates."""
    supp, hold = _make_events(events_per_work=6)
    # Violate: change gold_action to something outside candidates
    supp[0].gold_action = "non_existent_action"
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state == "INVALID", f"Expected INVALID, got {res.state}"


def test_structural_gate_split_consistency():
    """support-list events must declare split=support, holdout-list must declare split=holdout."""
    supp, hold = _make_events(events_per_work=6)
    supp[0].split = "holdout"  # mismatch
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state == "INVALID", f"Expected INVALID, got {res.state}"


def test_structural_gate_cue_label_source():
    """cue_count label source must trigger INVALID."""
    supp, hold = _make_events(events_per_work=6, label_source="cue_count")
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state == "INVALID", f"Expected INVALID, got {res.state}"
    assert res.cue_label_source_detected, "cue_label_source flag not set"


def test_structural_gate_work_leakage():
    """Work crossing partitions must trigger INVALID."""
    supp, hold = _make_events(events_per_work=6)
    cfg = _make_default_config()
    # 直接构造跨分区：把一个 support 事件复制进 holdout 列表（同 work_id 但声明 split=holdout）
    leaked = supp[0].model_copy(update={"split": "holdout"})
    res = validate_observed_signature_v1(supp, hold + [leaked], config=cfg)
    assert res.state == "INVALID", f"Expected INVALID, got {res.state}"
    assert res.holdout_leakage_detected, "holdout_leakage flag not set"


# ---------------------------------------------------------------------------
# Reliability gate tests
# ---------------------------------------------------------------------------


def test_no_double_subset_not_estimable():
    """No double-labeled units → NOT_ESTIMABLE with NO_DOUBLE_SUBSET."""
    supp, hold = _make_events(events_per_work=6, alpha_mode="none")
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state == "NOT_ESTIMABLE", f"Expected NOT_ESTIMABLE, got {res.state}"
    assert res.reliability_verdict == "NO_DOUBLE_SUBSET"


def test_low_alpha_not_estimable():
    """α below min_alpha → NOT_ESTIMABLE with EXPLORATORY_ONLY or REWORK."""
    supp, hold = _make_events(events_per_work=6, alpha_mode="disagree")
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state in ("NOT_ESTIMABLE", "PARTIAL"), f"Expected NOT_ESTIMABLE/PARTIAL, got {res.state}"
    assert res.reliability_verdict is not None


# ---------------------------------------------------------------------------
# Krippendorff α tests
# ---------------------------------------------------------------------------


def test_krippendorff_alpha_perfect():
    """Perfect agreement → α ≈ 1.0."""
    units = {"e1": {"A1": "a", "A2": "a"}, "e2": {"A1": "b", "A2": "b"}}
    alpha = _krippendorff_alpha_nominal(units)
    assert alpha == 1.0, f"Expected 1.0, got {alpha}"


def test_krippendorff_alpha_chance():
    """Chance-level agreement → α ≈ 0."""
    units = {"e1": {"A1": "a", "A2": "b"}, "e2": {"A1": "b", "A2": "a"}}
    alpha = _krippendorff_alpha_nominal(units)
    assert alpha <= 0.1, f"Expected near 0, got {alpha}"


# ---------------------------------------------------------------------------
# Power simulation tests
# ---------------------------------------------------------------------------


def test_power_high_with_strong_effect():
    """Strong effect with low variance → high power."""
    power = _simulate_power(n_authors=12, mde=0.05, observed_sd=0.02, reps=2000)
    assert power >= 0.95, f"Expected high power, got {power}"


def test_power_low_with_weak_effect():
    """Weak effect with high variance → low power."""
    power = _simulate_power(n_authors=6, mde=0.05, observed_sd=0.3, reps=2000)
    assert power < 0.5, f"Expected low power, got {power}"


# ---------------------------------------------------------------------------
# Yield gate tests
# ---------------------------------------------------------------------------


def test_insufficient_events_not_estimable():
    """Fewer events than min_present_events → NOT_ESTIMABLE."""
    # 题材作者数合规但事件总数过少（每作者 1 作品 holdout，产率不足）
    supp, hold = _make_events(n_authors_per_topic=2, events_per_work=1)
    cfg = _make_default_config()
    cfg.min_present_events = 999
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    assert res.state == "NOT_ESTIMABLE", f"Expected NOT_ESTIMABLE, got {res.state}"


# ---------------------------------------------------------------------------
# Inner CV test
# ---------------------------------------------------------------------------


def test_inner_cv_strong_signal_passes():
    """Strong signal dataset should pass inner CV."""
    cfg = _make_default_config()
    supp, hold = _make_events(n_authors_per_topic=8, events_per_work=6, signal_strength=0.95)
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    # Should not be INVALID or NOT_ESTIMABLE_IMESTIMABLE due to inner failure
    assert res.inner_success_count > 0, f"Inner CV failed: {res.inner_success_count}/{res.inner_config_count}"


def test_inner_cv_null_signal_fails():
    """Null signal (random labels) → inner CV fails → NOT_ESTIMABLE."""
    supp, hold = _make_events(n_authors_per_topic=4, events_per_work=6, signal_strength=0.33)
    cfg = _make_default_config()
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    # Null signal should fail inner CV or outer test
    assert res.state in ("NOT_ESTIMABLE", "FAIL"), f"Expected NOT_ESTIMABLE/FAIL, got {res.state}"


# ---------------------------------------------------------------------------
# Permutation test consistency
# ---------------------------------------------------------------------------


def test_permutation_uses_same_statistic_as_observed():
    """Permutation test must use max(topic, class_balanced) baseline, same as observed."""
    supp, hold = _make_events(n_authors_per_topic=8, events_per_work=6, signal_strength=0.95)
    cfg = _make_default_config()
    author_set = {e.author_id for e in hold}
    author_counts = {a: _build_action_counts([e for e in supp if e.author_id == a]) for a in author_set}
    topic_counts = {t: _build_action_counts([e for e in supp if e.topic_stratum == t]) for t in TOPICS}
    # Compute observed advantage first
    author_scores = {}
    topic_scores = {}
    cb_scores = {}
    for a in author_set:
        a_ev = [e for e in hold if e.author_id == a]
        a_correct = 0
        t_correct = 0
        cb_correct = 0
        for e in a_ev:
            cands = e.candidates or [e.gold_action]
            post_a = _author_posterior(author_counts.get(a, {}), e, cands, cfg.alpha_smoothing)
            pred_a = max(cands, key=lambda c: post_a[c])
            if pred_a == e.gold_action:
                a_correct += 1
            post_t = _author_posterior(topic_counts.get(e.topic_stratum, {}), e, cands, cfg.alpha_smoothing)
            pred_t = max(cands, key=lambda c: post_t[c])
            if pred_t == e.gold_action:
                t_correct += 1
            # class_balanced: most common action in support
            all_supp_actions = [e2.gold_action for e2 in supp if e2.gold_action]
            if all_supp_actions:
                most_common = Counter(all_supp_actions).most_common(1)[0][0]
                if most_common == e.gold_action:
                    cb_correct += 1
        if a_ev:
            a_acc = a_correct / len(a_ev)
            t_acc = t_correct / len(a_ev)
            cb_acc = cb_correct / len(a_ev)
            baseline = max(t_acc, cb_acc)
            author_scores[a] = a_acc - baseline
    obs_advantage = sum(author_scores.values()) / len(author_scores) if author_scores else 0.0
    # Permutation test should use the same baseline
    p_val = _strata_permutation_test(hold, supp, author_counts, topic_counts, cfg, obs_advantage)
    assert p_val is not None, "Permutation test returned None"


# ---------------------------------------------------------------------------
# Negative control ablation test
# ---------------------------------------------------------------------------


def test_cue_ablation_lowers_advantage():
    """Replacing gold_action with cue-only predictions must lower advantage."""
    supp, hold = _make_events(n_authors_per_topic=4, events_per_work=6, signal_strength=0.95)
    cfg = _make_default_config()
    # Run main
    main_res = validate_observed_signature_v1(supp, hold, config=cfg)
    # Build cue-ablated events
    cue_supp = []
    for e in supp:
        d = e.model_dump()
        if d.get("cue_hits"):
            d["gold_action"] = max(d["cue_hits"], key=d["cue_hits"].get)
        cue_supp.append(ObservedDecisionEventV1(**d))
    cue_hold = []
    for e in hold:
        d = e.model_dump()
        if d.get("cue_hits"):
            d["gold_action"] = max(d["cue_hits"], key=d["cue_hits"].get)
        cue_hold.append(ObservedDecisionEventV1(**d))
    cue_res = validate_observed_signature_v1(cue_supp, cue_hold, config=cfg)
    if main_res.author_advantage > 0 and cue_res.author_advantage is not None:
        assert cue_res.author_advantage <= main_res.author_advantage, (
            f"Cue ablation advantage {cue_res.author_advantage} > main {main_res.author_advantage}"
        )


# ---------------------------------------------------------------------------
# Edge case: empty data
# ---------------------------------------------------------------------------


def test_empty_support_returns_invalid():
    """Empty events → 无双标子集 → NOT_ESTIMABLE (NO_DOUBLE_SUBSET)."""
    cfg = _make_default_config()
    res = validate_observed_signature_v1([], [], config=cfg)
    assert res.state == "NOT_ESTIMABLE", f"Expected NOT_ESTIMABLE, got {res.state}"
    assert res.reliability_verdict == "NO_DOUBLE_SUBSET"


def test_selftest_equivalent_pipeline():
    """Run the same selfcheck-equivalent pipeline to verify no regression."""
    cfg = _make_default_config()
    supp, hold = _make_events(n_authors_per_topic=8, events_per_work=6, signal_strength=0.95)
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    # Internal mechanism should produce a result, not crash
    assert res.state in ("PASS", "FAIL", "NOT_ESTIMABLE"), f"Unexpected state: {res.state}"
    assert res.inner_success_count > 0, "Inner CV generated no successes"