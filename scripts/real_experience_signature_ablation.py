"""Q2 第一层 v7：模式签名经验消融（真实信号子集，决定性）。

v6 用文本 2-gram 近邻做经验决策 → 命中率 −6.17pp，因为 2-gram 抓不到
"同类决策"语义。v7 改为**模式词签名**做经验近邻：
- 每个事件的特征 = 六类模式词命中签名（direct_confront/defer/seek_ally/
  sacrifice/withhold/compromise 各命中数）
- 经验决策 = 该作品前 K-1 个真实信号事件中签名最接近的 ≤3 个的多数动作

这检验"真实作品经验（同类情境的过去决策）能否预测下一个决策"——
即经验是否构成创作选择的因果节点。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

ALL_PATTERNS = {
    "direct_confront": ["正面迎击", "断然出手", "悍然发动", "正面冲突", "毫不退让", "挺身迎战", "直接硬碰", "当场发难", "直接攻击", "迎难而上", "奋起反击", "斩杀敌手"],
    "defer": ["隐忍不发", "暂且退避", "静观其变", "按下心绪", "暂且搁置", "按捺住", "抽身后退", "先避锋芒", "暂缓行事", "按兵不动", "伺机而动", "拖延时间"],
    "seek_ally": ["暗中传音", "向同门求援", "联络帮手", "请动长辈", "结伴而行", "互通声息", "借助外力", "寻求支持", "与人联手", "请教高人", "召集同伴"],
    "sacrifice": ["甘冒奇险", "不惜自损", "燃烧精血", "强行催动", "舍命一击", "断尾求生", "付出代价", "玉石俱焚", "拼死一搏", "损耗修为", "以伤换命"],
    "withhold": ["隐瞒实情", "守口如瓶", "故作不知", "暗自隐藏", "不动声色", "掩盖痕迹", "守住秘密", "密而不宣", "不露端倪", "深藏不露", "三缄其口"],
    "compromise": ["各退一步", "权衡利弊后答应", "接受议和", "达成妥协", "顺水推舟", "接受条件", "互相让步", "暂息干戈", "握手言和", "互换利益", "低头认同"],
}

SIGNATURE_ORDER = tuple(ALL_PATTERNS.keys())


def _signature(text: str) -> tuple[int, ...]:
    return tuple(sum(text.count(p) for p in ALL_PATTERNS[k]) for k in SIGNATURE_ORDER)


def _dist(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return sum(abs(x - y) for x, y in zip(a, b))


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

    id2meta: dict[str, tuple[str, int]] = {}
    for a in disc["authors"]:
        for w in a.get("works", []):
            for c in w.get("candidates", []):
                id2meta[c["event_id"]] = (w["work_id"], c.get("decision_point", {}).get("offset", -1))

    # 真实信号子集（3 候选内模式命中）
    rows: list[dict[str, Any]] = []
    for x in task["tasks"]:
        act = x.get("action")
        if not act or act not in ACTIONS:
            continue
        text = x.get("pre_context_text") or ""
        cands = sorted(x.get("candidates") or list(ACTIONS))
        sig3 = _signature(text)
        # 3 候选内模式命中（保证是真实信号）
        scores = {a: sum(text.count(p) for p in ALL_PATTERNS[a]) for a in cands}
        if max(scores.values()) <= 0:
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
                "sig": sig3,
                "text_head": text[:40],
            }
        )

    global_prior = Counter(r["gold"] for r in rows)
    prior = global_prior.most_common(1)[0][0]

    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_work[r["work_id"]].append(r)

    changed = total_pts = a_hit = b_hit = 0
    non_defer_pts = non_defer_a = non_defer_b = 0
    details: list[dict[str, Any]] = []
    for work, evs in sorted(by_work.items()):
        evs.sort(key=lambda r: r["offset"])
        history: list[tuple[tuple[int, ...], str]] = []
        for e in evs:
            gold = e["gold"]
            if history:
                ranked = sorted(history, key=lambda h: _dist(h[0], e["sig"]))[:3]
                choice_a = Counter(a for _, a in ranked).most_common(1)[0][0]
            else:
                choice_a = prior
            choice_b = prior
            total_pts += 1
            if gold != "defer":
                non_defer_pts += 1
                if choice_a == gold:
                    non_defer_a += 1
                if choice_b == gold:
                    non_defer_b += 1
            if choice_a != choice_b:
                changed += 1
                details.append({"work": work, "gold": gold, "a": choice_a, "b": choice_b, "text": e["text_head"]})
            if choice_a == gold:
                a_hit += 1
            if choice_b == gold:
                b_hit += 1
            history.append((e["sig"], gold))

    report: dict[str, Any] = {
        "true_signal_events": len(rows),
        "global_prior": dict(global_prior),
        "works_covered": len(by_work),
        "decision_change_rate": round(changed / total_pts, 4) if total_pts else 0.0,
        "changed_count": changed,
        "total_decision_points": total_pts,
        "experience_hit_rate": round(a_hit / total_pts, 4) if total_pts else 0.0,
        "baseline_hit_rate": round(b_hit / total_pts, 4) if total_pts else 0.0,
        "hit_delta": round((a_hit - b_hit) / total_pts, 4) if total_pts else 0.0,
        "non_defer": {
            "n": non_defer_pts,
            "experience_hit_rate": round(non_defer_a / non_defer_pts, 4) if non_defer_pts else 0.0,
            "baseline_hit_rate": round(non_defer_b / non_defer_pts, 4) if non_defer_pts else 0.0,
            "delta": round((non_defer_a - non_defer_b) / non_defer_pts, 4) if non_defer_pts else 0.0,
        },
        "changed_samples": details[:100],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"true_signal={len(rows)} works={len(by_work)} prior={prior}")
    print(f"decision_change_rate={report['decision_change_rate']} ({changed}/{total_pts})")
    print(f"hit: exp={report['experience_hit_rate']} base={report['baseline_hit_rate']} delta={report['hit_delta']}")
    nd = report["non_defer"]
    print(f"non_defer(n={nd['n']}): exp={nd['experience_hit_rate']} base={nd['baseline_hit_rate']} delta={nd['delta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
