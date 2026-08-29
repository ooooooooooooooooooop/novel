"""Q2 第一层 v9：修复后作者签名验证（clean data, no hash noise）。

在 decision-detection discover 重建的 1527 个真实信号事件上，
检验作者级决策签名是否可检测（原 observed-signature 的零效应是因
96.7% 哈希伪随机导致的假阴性）。

方法：置换检验。
- 统计量：作者间动作分布的平均 pairwise 距离（卡方距离）。
- H0：作者标签无影响（置换作者标签 10000 次）。
- 若观察值 > 95% 置换分布 → 作者签名存在（p<0.05）。
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally", "sacrifice", "withhold", "compromise")


def _chi2_dist(a: Counter[str], b: Counter[str]) -> float:
    """卡方距离：sum((a_i - b_i)^2 / (a_i + b_i))。"""
    dist = 0.0
    for act in ACTIONS:
        n = a.get(act, 0) + b.get(act, 0)
        if n == 0:
            continue
        diff = a.get(act, 0) - b.get(act, 0)
        dist += diff * diff / n
    return dist


def _mean_pairwise_dist(profiles: dict[str, Counter[str]]) -> float:
    """所有作者对间的平均 pairwise 距离。"""
    aids = list(profiles.keys())
    total = 0.0
    pairs = 0
    for i in range(len(aids)):
        for j in range(i + 1, len(aids)):
            total += _chi2_dist(profiles[aids[i]], profiles[aids[j]])
            pairs += 1
    return total / pairs if pairs else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    with open(args.discovery, encoding="utf-8") as f:
        data = json.load(f)

    # 每作者动作分布
    profiles: dict[str, Counter[str]] = defaultdict(Counter)
    total_events = 0
    for a in data["authors"]:
        aid = a["author_id"]
        for w in a.get("works", []):
            for c in w.get("candidates", []):
                act = c.get("action")
                if act and act in ACTIONS:
                    profiles[aid][act] += 1
                    total_events += 1

    observed = _mean_pairwise_dist(profiles)

    # 置换检验：保持事件总数和每作者事件数，随机分配作者标签
    authors = list(profiles.keys())
    events_by_author = {a: sum(profiles[a].values()) for a in authors}
    all_events: list[str] = []
    for a, cnt in events_by_author.items():
        for act, c in profiles[a].items():
            all_events.extend([act] * c)
    rng = random.Random(args.seed)

    exceed = 0
    for _ in range(args.permutations):
        permuted = {a: Counter() for a in authors}
        idx = 0
        shuffled = all_events.copy()
        rng.shuffle(shuffled)
        for a in authors:
            n = events_by_author[a]
            for act in shuffled[idx : idx + n]:
                permuted[a][act] += 1
            idx += n
        perm_dist = _mean_pairwise_dist(permuted)
        if perm_dist >= observed:
            exceed += 1

    p_value = (exceed + 1) / (args.permutations + 1)

    report: dict[str, Any] = {
        "total_events": total_events,
        "authors_count": len(authors),
        "action_classes": list(ACTIONS),
        "per_author_events": dict(sorted(events_by_author.items())),
        "per_author_action_dist": {a: dict(profiles[a]) for a in sorted(authors)},
        "observed_mean_pairwise_distance": round(observed, 4),
        "permutations": args.permutations,
        "exceed_count": exceed,
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"total_events={total_events} authors={len(authors)}")
    print(f"observed_pairwise_dist={report['observed_mean_pairwise_distance']}")
    print(f"p_value={p_value} ({exceed}/{args.permutations} exceed)")
    print(f"significant={report['significant']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())