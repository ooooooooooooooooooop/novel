"""Q2 第一层 v5：标注信号审计（决定性根因检验）。

auto_annotate_tasks.py 的标注逻辑：
1) 文本无 DECISION_MARKERS → missing_unusable（丢弃）
2) 文本命中 ACTION_PATTERNS → 得 2 分，选最高分动作（真实信号）
3) 未命中任何模式 → sha256(text[:200]) % len(candidates) 哈希均匀分配（伪随机）

本脚本对全部事件重跑该标注逻辑，量化：
- pattern_hit_ratio：真实信号（模式命中）事件比例
- hash_ratio：伪随机（哈希分配）事件比例
- pattern 子集 vs hash 子集 上"模式预测 == gold_action"的命中率：
    若 pattern 子集命中率高（≈1）而 hash 子集 ≈ 1/3 → gold 大部分是伪随机
- 两个子集上的文本词袋信号检验：只在真实信号子集上，文本能否预测动作
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACTIONS = ("direct_confront", "defer", "seek_ally")

# 与 auto_annotate_tasks.py 完全一致的 3 候选模式（候选集内）
PATTERNS = {
    "direct_confront": ["正面迎击", "断然出手", "悍然发动", "正面冲突", "毫不退让", "挺身迎战", "直接硬碰", "当场发难", "直接攻击", "迎难而上", "奋起反击", "斩杀敌手"],
    "defer": ["隐忍不发", "暂且退避", "静观其变", "按下心绪", "暂且搁置", "按捺住", "抽身后退", "先避锋芒", "暂缓行事", "按兵不动", "伺机而动", "拖延时间"],
    "seek_ally": ["暗中传音", "向同门求援", "联络帮手", "请动长辈", "结伴而行", "互通声息", "借助外力", "寻求支持", "与人联手", "请教高人", "召集同伴"],
    # 6 动作代码本中的其余三类（任务候选集若含它们也匹配）
    "sacrifice": ["甘冒奇险", "不惜自损", "燃烧精血", "强行催动", "舍命一击", "断尾求生", "付出代价", "玉石俱焚", "拼死一搏", "损耗修为", "以伤换命"],
    "withhold": ["隐瞒实情", "守口如瓶", "故作不知", "暗自隐藏", "不动声色", "掩盖痕迹", "守住秘密", "密而不宣", "不露端倪", "深藏不露", "三缄其口"],
    "compromise": ["各退一步", "权衡利弊后答应", "接受议和", "达成妥协", "顺水推舟", "接受条件", "互相让步", "暂息干戈", "握手言和", "互换利益", "低头认同"],
}
DECISION_MARKERS = ["若是", "如果", "进退", "抉择", "只能", "如何是好", "该当如何", "心念电转", "沉吟", "打算", "决定", "犹豫", "当即", "不如", "权衡", "思忖"]
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


def replay_annotate(text: str, candidates: tuple[str, ...]) -> dict[str, Any]:
    """重放 auto_annotate_tasks.py 的标注逻辑，返回 (source, predicted)。"""
    has_marker = any(m in text for m in DECISION_MARKERS)
    if not has_marker:
        return {"source": "missing", "pred": None}
    scores = {a: 0 for a in candidates}
    for action in candidates:
        for pat in PATTERNS.get(action, []):
            if pat in text:
                scores[action] += 2
    max_s = max(scores.values())
    if max_s > 0:
        top = [a for a, s in scores.items() if s == max_s]
        return {"source": "pattern", "pred": sorted(top)[0]}
    h_val = int(hashlib.sha256(text[:200].encode("utf-8")).hexdigest(), 16)
    return {"source": "hash", "pred": candidates[h_val % len(candidates)]}


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

    candidates = ACTIONS
    rows: list[dict[str, Any]] = []
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
        replay = replay_annotate(text, candidates)
        rows.append(
            {
                "work_id": work_id,
                "offset": meta[1],
                "gold": gold,
                "source": replay["source"],
                "pred": replay["pred"],
                "text": text,
                "grams": _grams(text),
            }
        )

    by_source: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "hit": 0, "author": Counter(), "work": Counter(), "gold": Counter()}
    )
    for r in rows:
        st = by_source[r["source"]]
        st["n"] += 1
        if r["pred"] == r["gold"]:
            st["hit"] += 1

    report: dict[str, Any] = {
        "total_events": len(rows),
        "source_distribution": {},
        "pred_hit_by_source": {},
    }
    for src, st in sorted(by_source.items()):
        report["source_distribution"][src] = {
            "n": st["n"],
            "ratio": round(st["n"] / len(rows), 4) if rows else 0.0,
        }
        report["pred_hit_by_source"][src] = {
            "hit_rate": round(st["hit"] / st["n"], 4) if st["n"] else 0.0,
            "hits": st["hit"],
        }

    # 只在真实信号（pattern）子集上做词袋信号检验：文本能否预测动作
    pattern_rows = [r for r in rows if r["source"] == "pattern"]
    hash_rows = [r for r in rows if r["source"] == "hash"]

    def _bow_hit(subset: list[dict[str, Any]], vocab_size: int) -> float:
        """最近质心词袋预测命中率（subset 内 5-fold 留一近似：用一半训练一半测试）。"""
        if len(subset) < 10:
            return 0.0
        # 用前 60% 训练，后 40% 测试（按 offset 时序，无泄漏）
        subset_sorted = sorted(subset, key=lambda r: (r["work_id"], r["offset"]))
        split = int(len(subset_sorted) * 0.6)
        train, test = subset_sorted[:split], subset_sorted[split:]
        if len(set(r["gold"] for r in train)) < 2:
            return 0.0
        centroids: dict[str, dict[int, float]] = {}
        for act in ACTIONS:
            members = [r["grams"] for r in train if r["gold"] == act]
            if not members:
                continue
            sums: dict[int, float] = {}
            for m in members:
                for g, cnt in m.items():
                    sums[g] = sums.get(g, 0.0) + cnt
            centroids[act] = {g: v / len(members) for g, v in sums.items()}
        hits = 0
        for r in test:
            best = max(centroids, key=lambda a: sum(cnt * centroids[a].get(g, 0) for g, cnt in r["grams"].items()) if centroids[a] else -1.0)
            if best == r["gold"]:
                hits += 1
        return round(hits / len(test), 4) if test else 0.0

    report["bow_signal"] = {
        "pattern_subset_hit_rate": _bow_hit(pattern_rows, 300),
        "pattern_subset_n": len(pattern_rows),
        "hash_subset_hit_rate": _bow_hit(hash_rows, 300),
        "hash_subset_n": len(hash_rows),
        "random_baseline": round(1 / 3, 4),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"total={report['total_events']}")
    for src, d in report["source_distribution"].items():
        hit = report["pred_hit_by_source"][src]
        print(f"  source={src} n={d['n']} ratio={d['ratio']} pred_hit={hit['hit_rate']}")
    b = report["bow_signal"]
    print(f"bow: pattern_subset={b['pattern_subset_hit_rate']} n={b['pattern_subset_n']} hash_subset={b['hash_subset_hit_rate']} n={b['hash_subset_n']} random={b['random_baseline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
