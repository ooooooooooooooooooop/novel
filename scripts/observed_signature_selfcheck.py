"""Observed Decision Signature v1 — 验证器自测套件（WP4/WP5 机制检验）。

纯标准库 + 内部合成数据，不修改既有测试套件，合同锁 3000 不变。
运行：python scripts/observed_signature_selfcheck.py
"""

from __future__ import annotations

import sys
from typing import Sequence

from src.object_state.observed_author_signature import (
    ObservedDecisionEventV1,
    ObservedSignatureConfig,
)
from src.workflow_action.observed_author_signature import (
    validate_observed_signature_v1,
)

TOPICS = ["urban", "fantasy", "xianxia"]
# 代码本约束：全场冻结同一组 2–4 互斥候选。此处统一 3 候选，作者差异体现在动作分布。
CANDIDATES = ["direct_confront", "defer", "seek_ally"]


def _make_events(
    n_authors_per_topic: int = 4,
    events_per_work: int = 3,
    signal_strength: float = 0.9,
    label_source: str = "human_gold",
    cross_works: bool = False,
    alias_mode: bool = False,
    alpha_mode: str = "perfect",  # perfect / disagree / exploratory / none
    leak_hash: bool = False,
) -> tuple[list[ObservedDecisionEventV1], list[ObservedDecisionEventV1]]:
    support_events: list[ObservedDecisionEventV1] = []
    holdout_events: list[ObservedDecisionEventV1] = []
    author_topics = {}
    aid_seq = 0
    topics_used = [TOPICS[0]] if alias_mode else TOPICS

    global_ev_idx = 0
    for topic in topics_used:
        for _ in range(n_authors_per_topic):
            aid_seq += 1
            aid = f"a_{aid_seq:03d}"
            author_topics[aid] = topic
            # 每个作者固定的偏好动作（从统一候选集中选取）
            fav_action = CANDIDATES[(aid_seq - 1) % len(CANDIDATES)]

            for w_idx in range(1, 4):
                split = "support" if w_idx <= 2 else "holdout"
                if cross_works and w_idx == 3:
                    wid = f"{aid}_work_1"  # 故意让 work_1 跨分区
                else:
                    wid = f"{aid}_work_{w_idx}"

                for ev_idx in range(events_per_work):
                    global_ev_idx += 1
                    eid = f"{wid}_ev_{ev_idx}"
                    # 确定动作：signal_strength 概率选偏好动作，否则轮询（在候选集内）
                    import random
                    rng = random.Random(hash(eid) & 0xFFFFFFF)
                    if rng.random() < signal_strength:
                        act = fav_action
                    else:
                        act = CANDIDATES[(aid_seq + ev_idx) % len(CANDIDATES)]

                    # 构造双标（分歧标签也必须来自候选集）
                    ann_labels = {}
                    if alpha_mode == "perfect":
                        ann_labels = {"A1": act, "A2": act}
                    elif alpha_mode == "disagree":
                        other = CANDIDATES[(CANDIDATES.index(act) + 1) % len(CANDIDATES)]
                        ann_labels = {"A1": act, "A2": other}
                    elif alpha_mode == "exploratory":
                        # 全局每 5 个单位固定 1 个分歧（严格 20% 分歧率，α 精确落在 0.72-0.76）
                        if global_ev_idx % 5 == 0:
                            other = CANDIDATES[(CANDIDATES.index(act) + 1) % len(CANDIDATES)]
                            ann_labels = {"A1": act, "A2": other}
                        else:
                            ann_labels = {"A1": act, "A2": act}
                    # none: 空 ann_labels

                    pre_h = f"pre_{eid}"
                    out_h = pre_h if leak_hash else f"out_{eid}"

                    event = ObservedDecisionEventV1(
                        author_id=aid,
                        work_id=wid,
                        topic_stratum=topic,
                        split=split,
                        event_id=eid,
                        situation={"power_gap": "high", "threat": "low"},
                        candidates=list(CANDIDATES),
                        gold_action=act,
                        label_source=label_source,
                        pre_context_hash=pre_h,
                        outcome_evidence_hash=out_h,
                        annotator_labels=ann_labels,
                        confidence=0.9,
                        cue_hits={c: 0.1 for c in CANDIDATES},
                    )
                    if split == "support":
                        support_events.append(event)
                    else:
                        holdout_events.append(event)

    return support_events, holdout_events


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            failures.append(f"FAIL [{name}]: {detail}")
            print(f"  [X] {name}: {detail}")
        else:
            print(f"  [OK] {name}")

    print("=== WP4/WP5 验证器机制自测 ===")

    # 1. 标签来源违规：cue_count → INVALID
    supp, hold = _make_events(label_source="cue_count")
    res = validate_observed_signature_v1(supp, hold)
    check("cue_label_source_invalid", res.state == "INVALID" and res.cue_label_source_detected,
          f"state={res.state} cue_detected={res.cue_label_source_detected}")

    # 2. 作品跨分区泄漏：work_id 交叉 → INVALID
    supp, hold = _make_events(cross_works=True)
    res = validate_observed_signature_v1(supp, hold)
    check("work_isolation_leakage", res.state == "INVALID" and res.holdout_leakage_detected,
          f"state={res.state} holdout_leak={res.holdout_leakage_detected}")

    # 3. 题材别名：每题材仅 1 作者 → INVALID
    supp, hold = _make_events(n_authors_per_topic=1, alias_mode=True)
    res = validate_observed_signature_v1(supp, hold)
    check("topic_alias_invalid", res.state == "INVALID" and res.topic_alias_detected,
          f"state={res.state} alias_detected={res.topic_alias_detected}")

    # 4. 未来文本泄漏：pre 与 out 哈希相同 → INVALID
    supp, hold = _make_events(leak_hash=True)
    res = validate_observed_signature_v1(supp, hold)
    check("future_text_leak_invalid", res.state == "INVALID", f"state={res.state}")

    # 5. 可靠性无双标子集 → NOT_ESTIMABLE
    supp, hold = _make_events(alpha_mode="none")
    res = validate_observed_signature_v1(supp, hold)
    check("no_double_subset_not_estimable", res.state == "NOT_ESTIMABLE" and res.reliability_verdict == "NO_DOUBLE_SUBSET",
          f"state={res.state} rel={res.reliability_verdict}")

    # 6. 可靠性完全不一致（α < 0.667）→ NOT_ESTIMABLE / REWORK_CODEBOOK
    supp, hold = _make_events(alpha_mode="disagree")
    res = validate_observed_signature_v1(supp, hold)
    check("disagree_rework_not_estimable", res.state == "NOT_ESTIMABLE" and res.reliability_verdict == "REWORK_CODEBOOK",
          f"state={res.state} rel={res.reliability_verdict}")

    # 7. 可靠性探索带（0.667 <= α < 0.80）→ PARTIAL / EXPLORATORY_ONLY
    supp, hold = _make_events(alpha_mode="exploratory")
    res = validate_observed_signature_v1(supp, hold)
    check("exploratory_alpha_partial", res.state == "PARTIAL" and res.reliability_verdict == "EXPLORATORY_ONLY",
          f"state={res.state} rel={res.reliability_verdict}")

    # 8. 强信号全门禁 PASS（24 作者，8 作者/题材 × 3 题材，每作者 12 support + 6 holdout = 18 事件）
    supp, hold = _make_events(n_authors_per_topic=8, events_per_work=6, signal_strength=0.95, alpha_mode="perfect")
    cfg = ObservedSignatureConfig(
        power_target=0.70,
        assumed_effect_sd=0.03,  # 显式提供强信号下的预期方差
        bootstrap_reps=500,
        permutation_reps=500,
    )
    res = validate_observed_signature_v1(supp, hold, config=cfg)
    check("strong_signal_pass", res.state == "PASS",
          f"state={res.state} adv={res.author_advantage} CI={res.cluster_bootstrap_ci} p={res.permutation_p_value} power={res.power_estimate}")
    check("ci_lower_positive", res.cluster_bootstrap_ci[0] > 0, f"CI={res.cluster_bootstrap_ci}")
    check("permutation_p_significant", res.permutation_p_value is not None and res.permutation_p_value < 0.05,
          f"p={res.permutation_p_value}")
    check("mde_exceeded", res.author_advantage >= cfg.mde, f"adv={res.author_advantage} mde={cfg.mde}")
    check("outer_test_ran_once", res.outer_test_run is True, "outer_test_run")
    check("cue_control_safe", res.cue_only_advantage is not None and res.cue_only_advantage < res.author_advantage,
          f"cue_adv={res.cue_only_advantage} main_adv={res.author_advantage}")

    # 9. 零信号（完全随机）→ advantage 接近 0，置换检验 p 不显著
    supp, hold = _make_events(n_authors_per_topic=4, events_per_work=3, signal_strength=0.0, alpha_mode="perfect")
    cfg_null = ObservedSignatureConfig(bootstrap_reps=500, permutation_reps=500)
    res_null = validate_observed_signature_v1(supp, hold, config=cfg_null)
    check("null_signal_fail", res_null.state in ("FAIL", "NOT_ESTIMABLE"),
          f"state={res_null.state} adv={res_null.author_advantage}")

    print("\n--------------------------------")
    if failures:
        print(f"自测 FAIL: {len(failures)} 项失败")
        for f in failures:
            print("  ", f)
        return 1
    print("自测全部 PASS（13 项机制检验通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
