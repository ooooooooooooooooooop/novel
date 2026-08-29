"""Q2 第一层：真实历史消融（Real Experience Causal Validation）。

数据：observed-decision-author-signature-v1 的真实人类小说事件
（23899 事件 / 12 作者 / 36 作品 / 3 候选动作代码本）。

方法：作品内留一时序消融。
- 每部作品按 decision_point.offset 排序 → 真实事件时间序。
- 对第 K 个事件（K>=1）：
    A 组（有经验）：基于该作品前 K-1 个事件的 (situation, gold_action) 历史，
        用确定性近邻决策选择动作。
    B 组（无经验）：无作品历史，用全局动作先验选择。
- 统计 Decision Change Rate = A != B 的事件比例。
- 另报告真实命中率（A 组选择 == 真实 gold_action 的比例）：
    若经验确实起作用，A 组应至少不差于 B 组的真实命中。

纯标准库；situation 特征 = power_gap/threat/reversibility/dependence/
info_uncertainty/loyalty_conflict 六维序数（low/partial/high/none/mixed）。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

# 情境维度到序数打分（低=0 中=1 高=2；none/partial 按维度语义）
_DIM_ORDER = {
    "power_gap": {"none": 0, "low": 1, "high": 2},
    "threat": {"none": 0, "low": 1, "high": 2},
    "reversibility": {"low": 0, "partial": 1, "high": 2},
    "dependence": {"low": 0, "partial": 1, "high": 2},
    "info_uncertainty": {"low": 0, "partial": 1, "high": 2},
    "loyalty_conflict": {"none": 0, "low": 1, "high": 2},
}


def _situation_vector(situation: dict[str, str] | None) -> tuple[int, ...]:
    situation = situation or {}
    vec = []
    for dim, order in _DIM_ORDER.items():
        val = situation.get(dim, "low")
        vec.append(order.get(val, 1))
    return tuple(vec)


def _distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return sum(abs(x - y) for x, y in zip(a, b))


def load_with_order(
    events: list[dict[str, Any]], offset_map: dict[str, tuple[str, int]]
) -> list[dict[str, Any]]:
    """按 offset 给事件附加真实时序（同一作品内升序）。"""
    for e in events:
        work, off = offset_map.get(e["event_id"], ("", -1))
        e["_work"] = work
        e["_offset"] = off
    return sorted(events, key=lambda e: (e["_work"], e["_offset"]))


def experience_decision(
    history: list[tuple[tuple[int, ...], str]], situation_vec: tuple[int, ...]
) -> str:
    """确定性经验决策：历史中与当前情境最接近的 K 个事件的多数动作。

    无经验/无近邻时回退到历史全局多数；仍为空回退 'defer'（全局先验近似）。
    """
    if not history:
        return "defer"
    k = min(3, len(history))
    ranked = sorted(history, key=lambda h: _distance(h[0], situation_vec))[:k]
    counts: Counter[str] = Counter(action for _, action in ranked)
    return counts.most_common(1)[0][0]


def no_experience_decision(global_prior: Counter[str]) -> str:
    """无经验基线：全局动作先验（全体事件的多数动作）。"""
    return global_prior.most_common(1)[0][0]


def run_leave_one_out(events: list[dict[str, Any]]) -> dict[str, Any]:
    """按作品内时序做留一：前 K-1 事件为经验，第 K 事件为决策点。"""
    global_counts: Counter[str] = Counter()
    for e in events:
        if e["gold_action"] in ACTIONS:
            global_counts[e["gold_action"]] += 1
    prior = no_experience_decision(global_counts)

    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        if e["gold_action"] not in ACTIONS:
            continue
        by_work[e["_work"]].append(e)

    changed = 0
    total = 0
    a_hit = 0
    b_hit = 0
    change_details: list[dict[str, Any]] = []

    for work, work_events in sorted(by_work.items()):
        # 按 offset 升序
        work_events.sort(key=lambda e: e["_offset"])
        history: list[tuple[tuple[int, ...], str]] = []
        for idx, e in enumerate(work_events):
            situation_vec = _situation_vector(e.get("situation"))
            gold = e["gold_action"]
            # 经验只使用之前的事件（不泄漏当前事件的 gold）
            choice_a = experience_decision(history, situation_vec)
            choice_b = prior
            total += 1
            if choice_a != choice_b:
                changed += 1
                change_details.append(
                    {
                        "work": work,
                        "offset": e["_offset"],
                        "gold": gold,
                        "choice_a": choice_a,
                        "choice_b": choice_b,
                        "situation": e.get("situation"),
                    }
                )
            if choice_a == gold:
                a_hit += 1
            if choice_b == gold:
                b_hit += 1
            # 决策后把当前事件加入经验（真实时序：K 事件完成后进入历史）
            history.append((situation_vec, gold))

    return {
        "total_decision_points": total,
        "decision_change_rate": round(changed / total, 4) if total else 0.0,
        "changed_count": changed,
        "experience_hit_rate": round(a_hit / total, 4) if total else 0.0,
        "baseline_hit_rate": round(b_hit / total, 4) if total else 0.0,
        "global_prior": dict(global_counts),
        "changed_samples": change_details[:200],
    }


def load_offset_map(discovery_path: Path) -> dict[str, tuple[str, int]]:
    with open(discovery_path, encoding="utf-8") as f:
        disc = json.load(f)
    id2off: dict[str, tuple[str, int]] = {}
    for a in disc["authors"]:
        for w in a.get("works", []):
            work_id = w["work_id"]
            for c in w.get("candidates", []):
                off = c.get("decision_point", {}).get("offset", -1)
                id2off[c["event_id"]] = (work_id, off)
    return id2off


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    events = data["events"]
    offset_map = load_offset_map(args.discovery)

    ordered = load_with_order(events, offset_map)
    report = run_leave_one_out(ordered)
    report["input"] = {
        "events_total": len(events),
        "works": len({e["_work"] for e in ordered if e.get("_work")}),
        "events_with_order": sum(1 for e in ordered if e["_offset"] >= 0),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"total_decision_points={report['total_decision_points']}")
    print(f"decision_change_rate={report['decision_change_rate']}")
    print(f"changed_count={report['changed_count']}")
    print(f"experience_hit_rate={report['experience_hit_rate']}")
    print(f"baseline_hit_rate={report['baseline_hit_rate']}")
    print(f"global_prior={report['global_prior']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
