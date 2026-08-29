"""Q2 第一层 v8：决策检测 discover（修复标注协议的根因）。

根因：原 discover 用 split_spans 把全文机械平铺为连续 span，无任何决策检测；
auto_annotate 在无决策的 span 上找动作词 → 未命中 → sha256 哈希伪随机分配 gold
（96.7%）。协议注释要求"人工判定 status"，但被哈希回退替代。

v8 修复：只在**真实决策上下文**生成候选——
1) 扫全文找 DECISION_MARKERS（若是/如果/抉择/决定/犹豫/权衡…）位置；
2) 以决策标志为中心取上下文窗口（决策前 context + 决策点 + 后文 evidence）；
3) 只有命中决策标志的位置成为候选事件；全文无标志的段落不生成事件。

这样标注只在真实决策文本上运行，未检测到决策 = 无事件（不伪造）。
纯标准库，确定性，无人工。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

DECISION_MARKERS = ["若是", "如果", "进退", "抉择", "只能", "如何是好", "该当如何", "心念电转", "沉吟", "打算", "决定", "犹豫", "当即", "不如", "权衡", "思忖"]

ACTION_PATTERNS = {
    "direct_confront": ["正面迎击", "断然出手", "悍然发动", "正面冲突", "毫不退让", "挺身迎战", "直接硬碰", "当场发难", "直接攻击", "迎难而上", "奋起反击", "斩杀敌手"],
    "defer": ["隐忍不发", "暂且退避", "静观其变", "按下心绪", "暂且搁置", "按捺住", "抽身后退", "先避锋芒", "暂缓行事", "按兵不动", "伺机而动", "拖延时间"],
    "seek_ally": ["暗中传音", "向同门求援", "联络帮手", "请动长辈", "结伴而行", "互通声息", "借助外力", "寻求支持", "与人联手", "请教高人", "召集同伴"],
    "sacrifice": ["甘冒奇险", "不惜自损", "燃烧精血", "强行催动", "舍命一击", "断尾求生", "付出代价", "玉石俱焚", "拼死一搏", "损耗修为", "以伤换命"],
    "withhold": ["隐瞒实情", "守口如瓶", "故作不知", "暗自隐藏", "不动声色", "掩盖痕迹", "守住秘密", "密而不宣", "不露端倪", "深藏不露", "三缄其口"],
    "compromise": ["各退一步", "权衡利弊后答应", "接受议和", "达成妥协", "顺水推舟", "接受条件", "互相让步", "暂息干戈", "握手言和", "互换利益", "低头认同"],
}

CODEBOOK_CANDIDATES = ("direct_confront", "defer", "seek_ally")

WINDOW_BEFORE = 1200  # 决策标志前
WINDOW_AFTER = 600    # 决策标志后（evidence 窗口）

_WS = re.compile(r"\s+")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def detect_decision_spans(text: str) -> list[dict[str, Any]]:
    """定位真实决策上下文：以 DECISION_MARKERS 命中的位置为中心取窗口。

    同窗口内的多个命中合并为一个候选（决策点的上下文）；窗口间不重叠。
    返回 [{start, end, markers}]。
    """
    hits: list[int] = []
    for m in DECISION_MARKERS:
        idx = 0
        while True:
            i = text.find(m, idx)
            if i < 0:
                break
            hits.append(i)
            idx = i + len(m)
    hits.sort()
    if not hits:
        return []
    spans: list[dict[str, Any]] = []
    cur_start = max(0, hits[0] - WINDOW_BEFORE)
    cur_end = min(len(text), hits[0] + len(DECISION_MARKERS[0]) + WINDOW_AFTER)
    cur_markers = [hits[0]]
    for h in hits[1:]:
        new_start = max(0, h - WINDOW_BEFORE)
        if new_start <= cur_end:  # 窗口重叠/相邻 → 合并
            cur_end = min(len(text), h + WINDOW_AFTER)
            cur_markers.append(h)
        else:
            spans.append({"start": cur_start, "end": cur_end, "markers": cur_markers})
            cur_start = new_start
            cur_end = min(len(text), h + WINDOW_AFTER)
            cur_markers = [h]
    spans.append({"start": cur_start, "end": cur_end, "markers": cur_markers})
    return spans


def replay_action(text: str) -> tuple[str, str]:
    """在候选文本上重放动作标注：返回 (source, action)。无模式命中 → no_signal。"""
    scores = {a: 0 for a in ACTION_PATTERNS}
    for a, pats in ACTION_PATTERNS.items():
        for p in pats:
            if p in text:
                scores[a] += 2
    max_s = max(scores.values())
    if max_s == 0:
        return "no_signal", ""
    top = [a for a, s in scores.items() if s == max_s]
    return "pattern", sorted(top)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-per-work", type=int, default=0, help="每作品候选上限（0=不限）")
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    out: dict[str, Any] = {
        "protocol": "decision-detection-1.0",
        "total_candidates": 0,
        "total_with_action_signal": 0,
        "authors": [],
    }
    total_cand = 0
    total_signal = 0
    for author in manifest.get("authors", []):
        aid = author.get("author_id", "")
        aentry: dict[str, Any] = {"author_id": aid, "works": []}
        for work in author.get("works", []):
            wid = work.get("work_id", "")
            txt_val = work.get("txt") or work.get("txt_path", "")
            txt_path = Path(txt_val)
            if not txt_path.is_file():
                aentry["works"].append({"work_id": wid, "error": "txt_missing"})
                continue
            text = _read_text(txt_path)
            spans = detect_decision_spans(text)
            if args.max_per_work and len(spans) > args.max_per_work:
                spans = spans[: args.max_per_work]
            work_candidates = []
            work_signal = 0
            for sp in spans:
                window_text = text[sp["start"] : sp["end"]]
                src, action = replay_action(window_text)
                if src == "pattern":
                    work_signal += 1
                total_cand += 1
                total_signal += 1 if src == "pattern" else 0
                work_candidates.append(
                    {
                        "event_id": _sha256(f"{wid}:{sp['start']}")[:12],
                        "work_id": wid,
                        "author_id": aid,
                        "decision_point": {"offset": sp["start"]},
                        "pre_context": {
                            "start_offset": sp["start"],
                            "end_offset": sp["end"],
                            "length": sp["end"] - sp["start"],
                        },
                        "marker_count": len(sp["markers"]),
                        "window_text": window_text,
                        "action_source": src,
                        "action": action if src == "pattern" else None,
                        "status": "present" if src == "pattern" else "no_signal",
                    }
                )
            aentry["works"].append(
                {
                    "work_id": wid,
                    "char_length": len(text),
                    "candidate_count": len(work_candidates),
                    "signal_count": work_signal,
                    "candidates": work_candidates,
                }
            )
        out["authors"].append(aentry)

    out["total_candidates"] = total_cand
    out["total_with_action_signal"] = total_signal
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"total_candidates={total_cand} with_signal={total_signal} signal_rate={total_signal/total_cand if total_cand else 0:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
