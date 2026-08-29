"""Q2 第一层 v3：特征-动作关联检验（决定性）。

问：pre_context 文本的确定性语义特征（对抗/退避/求助词频）与 gold_action
是否有关联？若有，则近邻经验决策应能利用；若无，说明在 3 候选代码本粒度下，
真实人类小说的决策前文本不携带可检测的动作信号（与 observed-signature 零效应一致）。

方法：对每个事件，读原始 txt 切出 pre_context 窗口，统计三类动作词频，
计算：特征与动作的点二列关联（用均值差 + 判定率），并与随机基线比较。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

_CONFRONT_TERMS = [
    "出手", "翻脸", "质问", "动手", "摊牌", "硬碰", "直接", "怒斥", "反击", "拒绝",
    "威逼", "对峙", "冲", "杀", "打", "骂", "冷笑", "发难",
]
_DEFER_TERMS = [
    "忍", "避", "退", "让", "等", "躲", "不吭声", "沉默", "离开", "暂缓",
    "压住", "按捺", "退让", "回避", "隐忍", "缓一缓", "暂且",
]
_ALLY_TERMS = [
    "求", "请", "找", "商量", "结盟", "联手", "求助", "托付", "告知",
    "商议", "合作", "依靠", "请托", "寻求",
]


def load_raw_text(txt_path: str) -> str:
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def load_work_text_map(manifest_path: Path) -> dict[str, str]:
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    out: dict[str, str] = {}
    for a in m["authors"]:
        for w in a.get("works", []):
            txt = w.get("txt_path") or w.get("txt")
            out[w["work_id"]] = load_raw_text(txt)
    return out


def load_offset_map(discovery_path: Path) -> dict[str, tuple[str, int, int]]:
    with open(discovery_path, encoding="utf-8") as f:
        disc = json.load(f)
    out: dict[str, tuple[str, int, int]] = {}
    for a in disc["authors"]:
        for w in a.get("works", []):
            work_id = w["work_id"]
            for c in w.get("candidates", []):
                pc = c.get("pre_context", {})
                out[c["event_id"]] = (work_id, pc.get("start_offset", -1), pc.get("end_offset", -1))
    return out


def term_counts(text: str) -> tuple[int, int, int]:
    return (
        sum(text.count(t) for t in _CONFRONT_TERMS),
        sum(text.count(t) for t in _DEFER_TERMS),
        sum(text.count(t) for t in _ALLY_TERMS),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    work_text = load_work_text_map(args.manifest)
    offset_map = load_offset_map(args.discovery)

    # 每类动作的词频分布（按事件）
    action_freqs: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    n_text = 0
    for e in data["events"]:
        gold = e["gold_action"]
        if gold not in ACTIONS:
            continue
        meta = offset_map.get(e["event_id"])
        if not meta:
            continue
        work_id, s, en = meta
        raw = work_text.get(work_id, "")
        if s < 0 or en <= s or not raw:
            continue
        text = raw[s:en]
        action_freqs[gold].append(term_counts(text))
        n_text += 1

    report: dict[str, Any] = {"events_with_text": n_text}
    # 每类动作的平均词频
    report["action_mean_terms"] = {}
    for act, rows in action_freqs.items():
        n = len(rows)
        avg_conf = sum(r[0] for r in rows) / n
        avg_def = sum(r[1] for r in rows) / n
        avg_all = sum(r[2] for r in rows) / n
        report["action_mean_terms"][act] = {
            "n": n,
            "avg_confront": round(avg_conf, 3),
            "avg_defer": round(avg_def, 3),
            "avg_ally": round(avg_all, 3),
        }

    # 判别强度：对每个事件，取词频最高的类作为预测；命中率 vs 随机 1/3
    hits = 0
    total = 0
    for act, rows in action_freqs.items():
        for conf, defer, ally in rows:
            total += 1
            pred = max(
                ("direct_confront", conf), ("defer", defer), ("seek_ally", ally),
                key=lambda x: x[1],
            )[0]
            if pred == act:
                hits += 1
    report["term_majority_prediction"] = {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "random_baseline": round(1 / 3, 4),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"events_with_text={n_text}")
    for act, m in report["action_mean_terms"].items():
        print(f"  {act}: n={m['n']} conf={m['avg_confront']} defer={m['avg_defer']} ally={m['avg_ally']}")
    p = report["term_majority_prediction"]
    print(f"term_majority_prediction: hit_rate={p['hit_rate']} (random={p['random_baseline']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
