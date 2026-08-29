"""Q2 第一层 v6：真实信号子集消融（修正后的权威实验）。

v1-v4 结论被证伪：23899 事件中 96.7% 的 gold_action 是 sha256 哈希伪随机分配
（确定性但无信号），A1/A2 98% 一致率是哈希重复性假象。v5 定位根因。

v6 只在**真实信号子集**（778 个命中 ACTION_PATTERNS 的事件，重放命中 98.7%）
上做作品内留一时序消融：
- A 组（有经验）：该作品前 K-1 个真实信号事件的近邻经验决策
- B 组（无经验）：全局先验
- 统计 Decision Change Rate + 经验命中率 vs 基线命中率

文本 = 标注器实际看的 pre_context_text（任务文件，带决策标志过滤）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

PATTERNS = {
    "direct_confront": ["正面迎击", "断然出手", "悍然发动", "正面冲突", "毫不退让", "挺身迎战", "直接硬碰", "当场发难", "直接攻击", "迎难而上", "奋起反击", "斩杀敌手"],
    "defer": ["隐忍不发", "暂且退避", "静观其变", "按下心绪", "暂且搁置", "按捺住", "抽身后退", "先避锋芒", "暂缓行事", "按兵不动", "伺机而动", "拖延时间"],
    "seek_ally": ["暗中传音", "向同门求援", "联络帮手", "请动长辈", "结伴而行", "互通声息", "借助外力", "寻求支持", "与人联手", "请教高人", "召集同伴"],
}


def _score_text(text: str, candidates: tuple[str, ...]) -> tuple[str, str]:
    """重放标注：返回 (source, predicted)。"""
    scores = {a: 0 for a in candidates}
    for a in candidates:
        for p in PATTERNS.get(a, []):
            if p in text:
                scores[a] += 2
    max_s = max(scores.values())
    if max_s > 0:
        top = [a for a, s in scores.items() if s == max_s]
        return "pattern", sorted(top)[0]
    h = int(hashlib.sha256(text[:200].encode("utf-8")).hexdigest(), 16)
    return "hash", candidates[h % len(candidates)]


def _grams(text: str, n: int = 2) -> Counter[str]:
    import re

    clean = re.sub(r"\s+", "", text)
    if len(clean) < n:
        return Counter({clean: 1}) if clean else Counter()
    return Counter(clean[i : i + n] for i in range(len(clean) - n + 1))


def _dist(a: Counter[str], b: Counter[str]) -> int:
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-a1", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with open(args.task_a1, encoding="utf-8") as f:
        task = json.load(f)
    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    with open(args.discovery, encoding="utf-8") as f:
        disc = json.load(f)

    # event_id -> (work_id, offset)
    id2meta: dict[str, tuple[str, int]] = {}
    for a in disc["authors"]:
        for w in a.get("works", []):
            work_id = w["work_id"]
            for c in w.get("candidates", []):
                id2meta[c["event_id"]] = (work_id, c.get("decision_point", {}).get("offset", -1))

    # 真实信号子集：重放标注为 pattern 的事件
    rows: list[dict[str, Any]] = []
    for x in task["tasks"]:
        act = x.get("action")
        if not act:
            continue
        text = x.get("pre_context_text") or ""
        candidates = tuple(sorted(x.get("candidates") or list(ACTIONS)))
        src, pred = _score_text(text, candidates)
        if src != "pattern":
            continue
        meta = id2meta.get(x["event_id"])
        if not meta:
            continue
        rows.append(
            {
                "event_id": x["event_id"],
                "work_id": meta[0],
                "offset": meta[1],
                "gold": act,
                "pred": pred,
                "text": text,
                "grams": _grams(text),
            }
        )

    total = len(rows)
    global_prior = Counter(r["gold"] for r in rows)
    prior = global_prior.most_common(1)[0][0]

    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_work[r["work_id"]].append(r)

    changed = total_pts = a_hit = b_hit = 0
    change_details: list[dict[str, Any]] = []
    for work, evs in sorted(by_work.items()):
        evs.sort(key=lambda r: r["offset"])
        history: list[tuple[Counter[str], str]] = []
        for e in evs:
            gold = e["gold"]
            # A 组：前 K-1 事件经验（文本 2-gram 近邻）
            if history:
                ranked = sorted(history, key=lambda h: _dist(h[0], e["grams"]))[:3]
                choice_a = Counter(a for _, a in ranked).most_common(1)[0][0]
            else:
                choice_a = prior
            choice_b = prior
            total_pts += 1
            if choice_a != choice_b:
                changed += 1
                change_details.append(
                    {"work": work, "offset": e["offset"], "gold": gold, "choice_a": choice_a, "choice_b": choice_b, "text_head": e["text"][:40]}
                )
            if choice_a == gold:
                a_hit += 1
            if choice_b == gold:
                b_hit += 1
            history.append((e["grams"], gold))

    report: dict[str, Any] = {
        "true_signal_events": total,
        "global_prior": dict(global_prior),
        "works_covered": len(by_work),
        "decision_change_rate": round(changed / total_pts, 4) if total_pts else 0.0,
        "changed_count": changed,
        "total_decision_points": total_pts,
        "experience_hit_rate": round(a_hit / total_pts, 4) if total_pts else 0.0,
        "baseline_hit_rate": round(b_hit / total_pts, 4) if total_pts else 0.0,
        "hit_delta": round((a_hit - b_hit) / total_pts, 4) if total_pts else 0.0,
        "changed_samples": change_details[:100],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"true_signal_events={total} works={len(by_work)} prior={prior}")
    print(f"decision_change_rate={report['decision_change_rate']} ({report['changed_count']}/{total_pts})")
    print(f"experience_hit_rate={report['experience_hit_rate']} baseline_hit_rate={report['baseline_hit_rate']} delta={report['hit_delta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
