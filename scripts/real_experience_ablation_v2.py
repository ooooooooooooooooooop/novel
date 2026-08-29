"""Q2 第一层 v2：语义特征真实历史消融（pre_context 文本特征）。

v1 用六维 situation（98.3% 恒定）近邻，退化为多数投票。
v2 改为从原始 txt 按 discovery offset 切出 pre_context 文本，提取
确定性语义特征（决策动作倾向词 + 文本结构），再做作品内留一消融。

特征（纯标准库，确定性）：
- 动作倾向词命中：direct_confront/defer/seek_ally 三类的决策词频
  （对抗：出手/翻脸/质问/动手/摊牌/硬碰/直接/怒斥/反击/拒绝
   退避：忍/避/退/让/等/躲/不吭声/沉默/离开/暂缓
   求助：求/请/找/请人/商量/结盟/联手/求助/托付/告知）
- 决策窗口文本长度、句子数（粗代理：逗号/句号计数）
- 决策点前的直接引语数（对话密度）

A 组经验决策：历史事件中语义特征最接近的 ≤3 个多数动作。
B 组：全局动作先验。
"""

from __future__ import annotations

import argparse
import json
import re
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

_SENT_SPLIT = re.compile(r"[。！？!?；;\n]")


def _feature_vec(text: str) -> tuple[int, ...]:
    """确定性语义特征：三类动作词频 + 文本规模 + 对话密度。"""
    conf = sum(text.count(t) for t in _CONFRONT_TERMS)
    defer = sum(text.count(t) for t in _DEFER_TERMS)
    ally = sum(text.count(t) for t in _ALLY_TERMS)
    sent = len(_SENT_SPLIT.findall(text))
    quote = text.count("“") + text.count("”")
    return (conf, defer, ally, min(sent, 100), min(quote // 2, 50), min(len(text) // 500, 40))


def _distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return sum(abs(x - y) for x, y in zip(a, b))


def load_raw_text(txt_path: str) -> str:
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def load_work_text_map(manifest_path: Path) -> dict[str, str]:
    """work_id -> 全文（用于按 offset 切 pre_context）。"""
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    work_map: dict[str, str] = {}
    for a in m["authors"]:
        for w in a.get("works", []):
            txt = w.get("txt_path") or w.get("txt")
            work_map[w["work_id"]] = load_raw_text(txt)
    return work_map


def load_offset_map(discovery_path: Path) -> dict[str, tuple[str, int, int, int]]:
    """event_id -> (work_id, decision_offset, pre_start, pre_end)。"""
    with open(discovery_path, encoding="utf-8") as f:
        disc = json.load(f)
    out: dict[str, tuple[str, int, int, int]] = {}
    for a in disc["authors"]:
        for w in a.get("works", []):
            work_id = w["work_id"]
            for c in w.get("candidates", []):
                dp = c.get("decision_point", {})
                pc = c.get("pre_context", {})
                out[c["event_id"]] = (
                    work_id,
                    dp.get("offset", -1),
                    pc.get("start_offset", -1),
                    pc.get("end_offset", -1),
                )
    return out


def build_events(
    events: list[dict[str, Any]],
    offset_map: dict[str, tuple[str, int, int, int]],
    work_text: dict[str, str],
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for e in events:
        meta = offset_map.get(e["event_id"])
        if meta is None:
            continue
        work_id, off, pre_start, pre_end = meta
        text = ""
        raw = work_text.get(work_id)
        if raw and pre_start >= 0 and pre_end > pre_start:
            text = raw[pre_start:pre_end]
        ordered.append(
            {
                "author_id": e["author_id"],
                "work_id": work_id,
                "offset": off,
                "gold_action": e["gold_action"],
                "text": text,
                "feature": _feature_vec(text),
            }
        )
    return ordered


def experience_decision(
    history: list[tuple[tuple[int, ...], str]], feature: tuple[int, ...]
) -> str:
    if not history:
        return "defer"
    k = min(3, len(history))
    ranked = sorted(history, key=lambda h: _distance(h[0], feature))[:k]
    counts: Counter[str] = Counter(action for _, action in ranked)
    return counts.most_common(1)[0][0]


def run_leave_one_out(events: list[dict[str, Any]]) -> dict[str, Any]:
    global_counts: Counter[str] = Counter()
    for e in events:
        global_counts[e["gold_action"]] += 1
    prior = global_counts.most_common(1)[0][0]

    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_work[e["work_id"]].append(e)

    changed = total = a_hit = b_hit = 0
    change_details: list[dict[str, Any]] = []
    for work, evs in sorted(by_work.items()):
        evs.sort(key=lambda e: e["offset"])
        history: list[tuple[tuple[int, ...], str]] = []
        for e in evs:
            gold = e["gold_action"]
            choice_a = experience_decision(history, e["feature"])
            choice_b = prior
            total += 1
            if choice_a != choice_b:
                changed += 1
                change_details.append(
                    {
                        "work": work,
                        "offset": e["offset"],
                        "gold": gold,
                        "choice_a": choice_a,
                        "choice_b": choice_b,
                        "feature": list(e["feature"]),
                        "text_head": e["text"][:60],
                    }
                )
            if choice_a == gold:
                a_hit += 1
            if choice_b == gold:
                b_hit += 1
            history.append((e["feature"], gold))

    return {
        "total_decision_points": total,
        "decision_change_rate": round(changed / total, 4) if total else 0.0,
        "changed_count": changed,
        "experience_hit_rate": round(a_hit / total, 4) if total else 0.0,
        "baseline_hit_rate": round(b_hit / total, 4) if total else 0.0,
        "hit_delta": round((a_hit - b_hit) / total, 4) if total else 0.0,
        "global_prior": dict(global_counts),
        "changed_samples": change_details[:200],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with open(args.events, encoding="utf-8") as f:
        data = json.load(f)
    offset_map = load_offset_map(args.discovery)
    work_text = load_work_text_map(args.manifest)
    ordered = build_events(data["events"], offset_map, work_text)
    report = run_leave_one_out(ordered)
    report["input"] = {
        "events_total": len(ordered),
        "works": len({e["work_id"] for e in ordered}),
        "events_with_text": sum(1 for e in ordered if e["text"]),
        "mean_text_len": round(sum(len(e["text"]) for e in ordered) / len(ordered), 1) if ordered else 0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"events_with_text={report['input']['events_with_text']} mean_len={report['input']['mean_text_len']}")
    print(f"decision_change_rate={report['decision_change_rate']}")
    print(f"experience_hit_rate={report['experience_hit_rate']} baseline_hit_rate={report['baseline_hit_rate']} delta={report['hit_delta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
