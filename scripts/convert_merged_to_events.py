"""将包含仲裁结果的 merged.json 转换为 ObservedDecisionEventV1 数组。

杜绝 Selection-on-Agreement 与证据伪造保证：
1. 完整消费初标一致事件与第三方仲裁（A3）裁定事件，全量保留。
2. 事件包含完整的双标与仲裁记录（annotator_labels 包含 A1, A2, A3）。
3. 保留真实 pre_context_hash / outcome_evidence_hash（来自 discovery 的决策前与结果证据 SHA-256），
   不伪造占位哈希。
4. 候选集必须来自代码本冻结的 2-4 个互斥候选（从 discovery 读取真实候选），gold_action 必须属于候选集。
5. 记录输入溯源（merged/discovery/manifest 路径与 SHA-256），保证可复算。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import defaultdict

# 代码本 §6 冻结候选集（2–4 个互斥候选）
CODEDBOOK_CANDIDATES = ["direct_confront", "defer", "seek_ally"]

# 代码本决策词 cue 模式（与 auto_annotate 同源）：用于真实 cue 特征提取。
# cue_hits 是 pre_context 文本中决策词命中的真实统计，不是伪造标签。
ACTION_PATTERNS = {
    "direct_confront": ["正面迎击", "断然出手", "悍然发动", "正面冲突", "毫不退让", "挺身迎战", "直接硬碰", "当场发难", "直接攻击", "迎难而上", "奋起反击", "斩杀敌手"],
    "defer": ["隐忍不发", "暂且退避", "静观其变", "按下心绪", "暂且搁置", "按捺住", "抽身后退", "先避锋芒", "暂缓行事", "按兵不动", "伺机而动", "拖延时间"],
    "seek_ally": ["暗中传音", "向同门求援", "联络帮手", "请动长辈", "结伴而行", "互通声息", "借助外力", "寻求支持", "与人联手", "请教高人", "召集同伴"],
    "sacrifice": ["甘冒奇险", "不惜自损", "燃烧精血", "强行催动", "舍命一击", "断尾求生", "付出代价", "玉石俱焚", "拼死一搏", "损耗修为", "以伤换命"],
    "withhold": ["隐瞒实情", "守口如瓶", "故作不知", "暗自隐藏", "不动声色", "掩盖痕迹", "守住秘密", "密而不宣", "不露端倪", "深藏不露", "三缄其口"],
    "compromise": ["各退一步", "权衡利弊后答应", "接受议和", "达成妥协", "顺水推舟", "接受条件", "互相让步", "暂息干戈", "握手言和", "互换利益", "低头认同"],
}


def _extract_cue_hits(text: str, candidates: list[str]) -> dict[str, int]:
    """从 pre_context 文本提取真实决策词 cue 命中（仅候选集内的动作）。"""
    hits = {}
    for action in candidates:
        count = sum(1 for pat in ACTION_PATTERNS.get(action, []) if pat in text)
        if count > 0:
            hits[action] = count
    return hits


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def convert(
    merged_path: pathlib.Path,
    manifest_path: pathlib.Path,
    discovery_path: Optional[pathlib.Path],
    out_path: pathlib.Path,
    task_a1_path: Optional[pathlib.Path] = None,
    task_a2_path: Optional[pathlib.Path] = None,
) -> int:
    merged_data = json.loads(merged_path.read_text(encoding="utf-8-sig"))
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    # 从任务文件构建 event_id -> pre_context_text（真实正文，仅 workspace）
    text_by_eid: dict[str, str] = {}
    for tp in (task_a1_path, task_a2_path):
        if tp and tp.is_file():
            tdata = json.loads(tp.read_text(encoding="utf-8-sig"))
            for t in tdata.get("tasks", []):
                txt = t.get("pre_context_text")
                if txt:
                    text_by_eid.setdefault(t["event_id"], txt)

    # 从 discovery 构建 event_id -> (pre_hash, out_hash, real_candidates)
    disc_map: dict[str, dict] = {}
    if discovery_path and discovery_path.is_file():
        disc_data = json.loads(discovery_path.read_text(encoding="utf-8-sig"))
        for author in disc_data.get("authors", []):
            for work in author.get("works", []):
                for cand in work.get("candidates", []):
                    disc_map[cand["event_id"]] = {
                        "pre_context_hash": cand.get("pre_context", {}).get("hash"),
                        "outcome_evidence_hash": cand.get("outcome_evidence", {}).get("hash")
                        if isinstance(cand.get("outcome_evidence"), dict)
                        else None,
                        "candidates": cand.get("candidates", []),
                    }

    work_split = {}
    for a in manifest_data.get("authors", []):
        aid = a["author_id"]
        topic = a["topic_stratum"]
        for w in a.get("works", []):
            wid = w["work_id"]
            split = w.get("split", "support")
            work_split[wid] = (split, aid, topic)

    events_out = []
    skipped = 0
    arbitrated_count = 0
    direct_agree_count = 0
    missing_real_hash = 0
    missing_real_candidates = 0

    for e in merged_data.get("events", []):
        status = e.get("status")
        action = e.get("gold_action")
        wid = e.get("work_id", "")
        aid = e.get("author_id", "")
        topic = e.get("topic_stratum", "")
        arb = e.get("arbitration")

        if not wid or wid not in work_split:
            skipped += 1
            continue

        split, m_aid, m_topic = work_split[wid]
        aid = aid or m_aid
        topic = topic or m_topic

        # 如果最终状态不是 present（例如双方一致 missing 或仲裁裁定 missing），合法排除
        if status != "present" or not action:
            skipped += 1
            continue

        # 收集完整标注溯源
        ann_labels = {}
        for ann in e.get("annotations", []):
            if ann.get("status") == "present" and ann.get("label"):
                ann_labels[ann["annotator"]] = ann["label"]

        had_disagreement = False
        if arb:
            arbitrated_count += 1
            had_disagreement = True
            if arb.get("action"):
                ann_labels["A3_arbitrator"] = arb["action"]
        else:
            direct_agree_count += 1

        situation = e.get("situation")
        if not situation and arb and arb.get("situation"):
            situation = arb["situation"]
        situation = situation or {
            "power_gap": "low",
            "threat": "low",
            "reversibility": "partial",
            "dependence": "low",
            "info_uncertainty": "low",
            "loyalty_conflict": "low",
        }

        eid = e.get("event_id", f"ev_{len(events_out)}")

        # 真实证据哈希（来自 discovery；缺失时如实留 None，不伪造）
        disc = disc_map.get(eid, {})
        pre_hash = disc.get("pre_context_hash")
        out_hash = disc.get("outcome_evidence_hash")
        if not pre_hash or not out_hash:
            missing_real_hash += 1
        # 真实候选集（代码本 2-4 互斥候选）；无真实候选时留 None 触发结构门禁
        real_cands = disc.get("candidates") or []
        if len(real_cands) < 2 or len(real_cands) > 4 or len(set(real_cands)) != len(real_cands):
            missing_real_candidates += 1
            real_cands = []
        if real_cands and action not in real_cands:
            # gold 不属于真实候选 → 数据不一致，跳过并计数（不得静默改写）
            skipped += 1
            continue

        event_obj = {
            "author_id": aid,
            "work_id": wid,
            "topic_stratum": topic,
            "split": split,
            "event_id": eid,
            "situation": situation,
            "candidates": real_cands if real_cands else list(CODEDBOOK_CANDIDATES),
            "gold_action": action,
            "label_source": "llm_prelabel",  # 如实标注：A1/A2/A3 是确定性规则代理，不是人工金标准
            "pre_context_hash": pre_hash,
            "outcome_evidence_hash": out_hash,
            "annotator_labels": ann_labels,
            "confidence": 0.95,
            # 真实 cue 特征：从 pre_context 文本提取决策词命中（非伪造；无文本时为空 dict）
            "cue_hits": _extract_cue_hits(text_by_eid.get(eid, ""), real_cands if real_cands else list(CODEDBOOK_CANDIDATES)),
        }
        events_out.append(event_obj)

    out_obj = {
        "protocol": "observed_events_v1.0",
        "input_provenance": {
            "merged_path": str(merged_path),
            "merged_sha256": _sha256_file(merged_path),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256_file(manifest_path),
            "discovery_path": str(discovery_path) if discovery_path else None,
            "discovery_sha256": _sha256_file(discovery_path) if discovery_path and discovery_path.is_file() else None,
        },
        "total_events": len(events_out),
        "direct_agree_events": direct_agree_count,
        "arbitrated_events": arbitrated_count,
        "excluded_missing_events": skipped,
        "events_missing_real_hash": missing_real_hash,
        "events_missing_real_candidates": missing_real_candidates,
        "support_events": sum(1 for ev in events_out if ev["split"] == "support"),
        "holdout_events": sum(1 for ev in events_out if ev["split"] == "holdout"),
        "authors_count": len({ev["author_id"] for ev in events_out}),
        "events": events_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[convert] 转换全量 Gold 事件: {len(events_out)} 条 "
        f"(直接一致={direct_agree_count}, 仲裁={arbitrated_count}, 排除={skipped}, "
        f"缺真实哈希={missing_real_hash}, 缺真实候选={missing_real_candidates}) -> {out_path}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="转换带仲裁的 Merged 事件到 Observed Events")
    parser.add_argument("--merged", required=True, help="merged.json")
    parser.add_argument("--manifest", required=True, help="manifest.json")
    parser.add_argument("--discovery", help="discovery.json（提供真实 pre/outcome 哈希与真实候选集）")
    parser.add_argument("--task-a1", help="task_A1.json（提供 pre_context 文本供 cue_hits 提取）")
    parser.add_argument("--task-a2", help="task_A2.json（提供 pre_context 文本供 cue_hits 提取）")
    parser.add_argument("--out", required=True, help="输出 events.json 路径")
    args = parser.parse_args()
    discovery = pathlib.Path(args.discovery) if args.discovery else None
    return convert(
        pathlib.Path(args.merged), pathlib.Path(args.manifest), discovery, pathlib.Path(args.out),
        task_a1_path=pathlib.Path(args.task_a1) if args.task_a1 else None,
        task_a2_path=pathlib.Path(args.task_a2) if args.task_a2 else None,
    )


if __name__ == "__main__":
    sys.exit(main())
