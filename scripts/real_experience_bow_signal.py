"""Q2 第一层 v4：词袋信号检验 + 作品内经验时序预测（决定性升级）。

v3 用 3 类动作词频（太粗）证明 ≈ 随机。v4 升级为：
1) 词袋信号检验：全词频特征（top-N 高频词）直接预测 gold_action，
   证明"文本中是否存在任何可预测动作的词汇信号"。
2) 作品内经验时序预测：用本作品前 K 事件的词袋特征训练，预测第 K+1 事件的
   gold_action —— 这是"真实作品经验能否改善预测"的直接测试。
3) 对照：跨作品经验（其他作品训练预测本作品）vs 作品内经验，
   区分"作者/作品特有经验"与"通用文本规律"。

全确定性，无人工标注；词频特征用字符 2-gram 计数（中文无分词）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

_WS = re.compile(r"\s+")


def _grams(text: str, n: int = 2) -> Counter[str]:
    clean = _WS.sub("", text)
    if len(clean) < n:
        return Counter({clean: 1}) if clean else Counter()
    return Counter(clean[i : i + n] for i in range(len(clean) - n + 1))


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


def build_dataset(
    events: list[dict[str, Any]],
    offset_map: dict[str, tuple[str, int, int]],
    work_text: dict[str, str],
    top_n: int = 400,
) -> tuple[list[dict[str, Any]], list[str]]:
    """构建 (work_id, offset, gold, 词袋向量) 数据集，返回特征词典。"""
    rows: list[dict[str, Any]] = []
    grams_global: Counter[str] = Counter()
    for e in events:
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
        grams_global.update(_grams(text))
        rows.append(
            {
                "work_id": work_id,
                "offset": meta[1],
                "gold": gold,
                "grams": _grams(text),
            }
        )
    top_grams = [g for g, _ in grams_global.most_common(top_n)]
    vocab_idx = {g: i for i, g in enumerate(top_grams)}
    for r in rows:
        sparse: dict[int, int] = {}
        for g, cnt in r["grams"].items():
            idx = vocab_idx.get(g)
            if idx is not None:
                sparse[idx] = cnt
        r["sparse"] = sparse
        r.pop("grams")
    return rows, top_grams


def _cosine_sparse(a: dict[int, int], b: dict[int, int]) -> float:
    dot = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb:
            dot += va * vb
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _vec_to_sparse(vec: list[int]) -> dict[int, int]:
    return {i: v for i, v in enumerate(vec) if v}


def _class_centroid_sparse(
    rows: list[dict[str, Any]], action: str, vocab_size: int
) -> dict[int, float]:
    members = [r["sparse"] for r in rows if r["gold"] == action]
    if not members:
        return {}
    sums: dict[int, float] = {}
    for m in members:
        for k, v in m.items():
            sums[k] = sums.get(k, 0.0) + v
    return {k: v / len(members) for k, v in sums.items()}


def _predict_sparse(
    sparse: dict[int, int], centroids: dict[str, dict[int, float]]
) -> str:
    best = max(
        centroids,
        key=lambda a: _cosine_sparse(sparse, centroids[a]) if centroids[a] else -1.0,
    )
    return best


def run_signal_and_experience(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """1) 全局词袋预测（文本有无信号）2) 作品内留一时序经验 3) 跨作品对照。"""
    total = len(rows)
    global_hits = 0

    # 作品内留一：前 K 事件训练质心 → 预测第 K+1
    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_work[r["work_id"]].append(r)
    intra_hits = 0
    intra_total = 0
    cross_hits = 0
    cross_total = 0

    # 全局质心（用于跨作品对照：用其他作品训练预测本作品）
    vocab_size = len(rows[0]["sparse"]) if rows else 0
    global_centroids = {a: _class_centroid_sparse(rows, a, vocab_size) for a in ACTIONS}
    # 预计算每个作品的"其他作品"质心（一次，避免 O(N²) 内层重算）
    by_work_full = defaultdict(list)
    for r in rows:
        by_work_full[r["work_id"]].append(r)
    cross_centroids_by_work: dict[str, dict[str, dict[int, float]]] = {}
    for work, evs in by_work_full.items():
        others = [r for r in rows if r["work_id"] != work]
        if len(set(r["gold"] for r in others)) >= 2:
            cross_centroids_by_work[work] = {
                a: _class_centroid_sparse(others, a, vocab_size) for a in ACTIONS
            }

    for work, evs in sorted(by_work.items()):
        evs.sort(key=lambda r: r["offset"])
        # 全局预测（无作品内经验）：用全局质心
        for r in evs:
            pred = _predict_sparse(r["sparse"], global_centroids)
            if pred == r["gold"]:
                global_hits += 1
        # 作品内留一时序：前 K 训练（只取 K=min(30, idx) 训练，控规模）
        cross_centroids = cross_centroids_by_work.get(work)
        for idx in range(1, len(evs)):
            train = evs[max(0, idx - 30) : idx]
            test = evs[idx]
            if len(set(r["gold"] for r in train)) < 2:
                continue
            centroids = {a: _class_centroid_sparse(train, a, vocab_size) for a in ACTIONS}
            pred_intra = _predict_sparse(test["sparse"], centroids)
            intra_total += 1
            if pred_intra == test["gold"]:
                intra_hits += 1
            # 跨作品对照：用预计算的其他作品质心
            if cross_centroids is None:
                continue
            pred_cross = _predict_sparse(test["sparse"], cross_centroids)
            cross_total += 1
            if pred_cross == test["gold"]:
                cross_hits += 1

    return {
        "total_events": total,
        "global_bow_hit_rate": round(global_hits / total, 4) if total else 0.0,
        "intra_work_experience_hit_rate": round(intra_hits / intra_total, 4) if intra_total else 0.0,
        "intra_work_total": intra_total,
        "cross_work_hit_rate": round(cross_hits / cross_total, 4) if cross_total else 0.0,
        "cross_work_total": cross_total,
        "random_baseline": round(1 / 3, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--top-n", type=int, default=400)
    args = parser.parse_args()

    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    work_text = load_work_text_map(args.manifest)
    offset_map = load_offset_map(args.discovery)
    rows, vocab = build_dataset(data["events"], offset_map, work_text, args.top_n)
    report = run_signal_and_experience(rows)
    report["vocab_size"] = len(vocab)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"events={report['total_events']} vocab={report['vocab_size']}")
    print(f"global_bow_hit_rate={report['global_bow_hit_rate']} (random={report['random_baseline']})")
    print(f"intra_work_experience_hit_rate={report['intra_work_experience_hit_rate']} n={report['intra_work_total']}")
    print(f"cross_work_hit_rate={report['cross_work_hit_rate']} n={report['cross_work_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
