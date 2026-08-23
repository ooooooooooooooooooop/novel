"""nested-CV 确认性 pilot（确定性脚本版）。

按冻结规格（design.md + checkpoint）执行：
1. outer 拆分：90 位确认作者池中选 2 genre（都市/玄幻），每 genre 固定 seed 拆 train/test；
2. 事件构造：从真实正文 txt（GB18030）统计 cue 词，构造 DecisionEventV2（cue-count 确定性代理）；
3. inner CV：outer-train 上比较 backoff × operating_coverage 9 组合，只读 outer-train；
4. outer-test 一次评估：冻结参数，跑一次 validate_decision_signature_v2；
5. 报告主/次终点。

隐私：只输出 author_id/genre 中性标签，真实作者名/书名/路径不输出。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# 隐私纪律：不硬编码本机绝对路径；路径经环境变量注入（不入 Git）。
IDENTITY_MAP = Path(os.environ.get("NESTEDCV_IDENTITY_MAP", ""))
REPO = Path(os.environ.get("NESTEDCV_REPO", ""))
if not IDENTITY_MAP.is_file():
    raise SystemExit("NESTEDCV_IDENTITY_MAP 未设置或不可读（本地路径不入 Git，须经环境变量注入）")
sys.path.insert(0, str(REPO))

from src.object_state.authorkernel import VALUE_VOCAB  # noqa: E402
from src.object_state.authormodel_v3 import DecisionEventV2  # noqa: E402
from src.workflow_action.authormodel_v3 import validate_decision_signature_v2  # noqa: E402

EXCLUDE = {"collection20-a067", "collection20-a073", "collection20-a083", "collection20-a088", "collection20-a096"}

# cue 词簇：动作 -> 中文近义词（正文出现即 +1）
CUE_VOCAB: dict[str, tuple[str, ...]] = {
    "direct_confront": ("对峙", "质问", "翻脸", "摊牌", "顶撞", "挑衅", "反击", "剑拔弩张"),
    "defer": ("退让", "忍让", "退避", "避让", "息事宁人", "退一步", "低头"),
    "seek_ally": ("结盟", "求助", "联手", "联合", "找帮手", "搬救兵", "借助"),
    "sacrifice": ("牺牲", "舍弃", "割舍", "付出代价", "献身", "弃车保帅"),
    "withhold": ("隐瞒", "藏着", "不透露", "保留", "藏起", "欲言又止", "守口如瓶"),
    "compromise": ("折中", "各退一步", "谈条件", "商量", "和解", "讲和", "妥协"),
}
ACTIONS = tuple(CUE_VOCAB.keys())
SITUATIONS = [
    ("high", "low", "high", "low", "low", "none"),
    ("high", "high", "low", "high", "low", "low"),
    ("low", "low", "high", "high", "high", "none"),
    ("low", "high", "low", "low", "high", "high"),
    ("high", "low", "low", "high", "high", "low"),
    ("low", "high", "high", "low", "low", "high"),
]
STAGES = ("setup", "payoff")
ROLES = ("protagonist", "antagonist")
CHAPTER_SPLIT = re.compile(r"第[0-9一二三四五六七八九十百千]+[章节回卷]")


def load_pool() -> dict[str, dict[str, object]]:
    data = json.loads(IDENTITY_MAP.read_text(encoding="utf-8"))
    pool: dict[str, dict[str, object]] = {}
    for author in data.get("authors", []):
        aid = author["author_id"]
        if aid in EXCLUDE:
            continue
        works = author.get("works", [])
        txts = []
        genre = ""
        for w in works:
            if w.get("status") != "ok":
                continue
            genre = genre or w.get("genre", "")
            txts.extend(t for t in w.get("txt_files", []) if isinstance(t, str))
        if len(txts) >= 3:
            pool[aid] = {"txts": txts, "genre": genre}
    return pool


def cue_counts(txt_path: str, max_chars: int = 300_000) -> dict[str, int]:
    """读 GB18030 正文前 max_chars 字符，统计各动作 cue 出现次数。"""
    counts = {action: 0 for action in ACTIONS}
    try:
        raw = Path(txt_path).read_bytes()[: max_chars * 3]
        text = raw.decode("gb18030", errors="replace")
    except OSError:
        return counts
    for action, cues in CUE_VOCAB.items():
        total = 0
        for cue in cues:
            total += text.count(cue)
        counts[action] = total
    return counts


def author_strategy(aid: str, txts: list[str]) -> list[str]:
    """每作者确定性策略：前 3 个 work_slot 的 cue 计数最高动作（每 slot 独立）。"""
    strategy = []
    for txt in txts[:3]:
        counts = cue_counts(txt)
        # 平手用稳定作者顺序（aid 哈希序）
        best = sorted(ACTIONS, key=lambda a: (-counts[a], a))[0]
        strategy.append(best)
    return strategy


def build_events(authors: list[str], pool: dict[str, dict[str, object]]) -> list[DecisionEventV2]:
    events = []
    for aid in authors:
        entry = pool[aid]
        strategy = author_strategy(aid, entry["txts"])
        genre_key = "urban" if "都市" in entry["genre"] else ("fantasy" if "玄幻" in entry["genre"] else entry["genre"][:12])
        for slot_index, preferred in enumerate(strategy[:3]):
            for stage in STAGES:
                for role_index, role in enumerate(ROLES):
                    for situation_index, situation in enumerate(SITUATIONS):
                        candidates = list(ACTIONS)
                        rotated = candidates[(slot_index + situation_index) % 3 :] + candidates[: (slot_index + situation_index) % 3]
                        events.append(
                            DecisionEventV2(
                                author_id=aid,
                                work_slot=f"{aid}-w{slot_index + 1}",
                                stage=stage,
                                topic_tag=genre_key,
                                actor_role=role,
                                power_gap=situation[0],
                                reversibility=situation[1],
                                threat=situation[2],
                                dependence=situation[3],
                                info_uncertainty=situation[4],
                                loyalty_conflict=situation[5],
                                candidates=rotated,
                                selected=preferred,
                                rejected=[a for a in rotated if a != preferred],
                                cost_label="tangible",
                                protected_value_key=VALUE_VOCAB[(slot_index * 2 + situation_index) % len(VALUE_VOCAB)],
                                evidence_anchor=f"anchor-{aid}-w{slot_index + 1}-{stage}-{role_index}-{situation_index}",
                                confidence=0.90,
                            )
                        )
    return events


def summarize(result) -> dict[str, object]:
    return {
        "state": result.state,
        "statistical_state": result.statistical_state,
        "full_coverage_deployment_state": result.full_coverage_deployment_state,
        "coverage": result.coverage,
        "selective_risk": result.selective_risk,
        "aurc": result.aurc,
        "c_at_1": result.c_at_1,
        "f_half_u": result.f_half_u,
        "author_accuracy": round(result.author_accuracy, 6),
        "hard_negative_accuracy": round(result.hard_negative_accuracy, 6),
        "author_advantage": round(result.author_advantage, 6),
        "hard_negative_advantage": round(result.hard_negative_advantage, 6),
        "confidence_interval": result.confidence_interval,
        "permutation_p_value": result.permutation_p_value,
        "evaluated_event_count": result.evaluated_event_count,
        "fold_count": result.fold_count,
        "invalid_reasons": list(result.invalid_reasons),
        "warnings": list(result.warnings),
        "backoff_used": result.backoff_used,
        "backoff_events": result.backoff_events,
        "operating_coverage": result.operating_coverage,
    }


def main() -> None:
    pool = load_pool()
    urban = [aid for aid, e in pool.items() if "都市" in e["genre"]]
    fantasy = [aid for aid, e in pool.items() if "玄幻" in e["genre"]]
    print(f"pool_total={len(pool)} urban={len(urban)} fantasy={len(fantasy)}", flush=True)

    # 固定 seed 确定性拆分：每 genre 2/3 train + 1/3 test
    import random

    rng = random.Random(20260822)
    outer: dict[str, dict[str, list[str]]] = {}
    for name, group in (("urban", sorted(urban)), ("fantasy", sorted(fantasy))):
        rng.shuffle(group)
        split = max(2, int(len(group) * 2 / 3))
        outer[name] = {"train": sorted(group[:split]), "test": sorted(group[split:])}
        print(f"outer[{name}] train={len(outer[name]['train'])} test={len(outer[name]['test'])}", flush=True)

    train_authors = outer["urban"]["train"] + outer["fantasy"]["train"]
    test_authors = outer["urban"]["test"] + outer["fantasy"]["test"]
    print(f"train_authors={len(train_authors)} test_authors={len(test_authors)}", flush=True)

    # ---- inner CV：只读 outer-train ----
    train_events = build_events(train_authors, pool)
    print(f"train_events={len(train_events)}", flush=True)
    inner_results = []
    for backoff in ("none", "family", "partial_pool"):
        for op_cov in (0.70, 0.80, 0.90):
            res = validate_decision_signature_v2(train_events, backoff=backoff, operating_coverage=op_cov)
            inner_results.append(
                {
                    "backoff": backoff,
                    "operating_coverage": op_cov,
                    "statistical_state": res.statistical_state,
                    "author_advantage": round(res.author_advantage, 6),
                    "ci_lower": round(res.confidence_interval[0], 6),
                    "coverage": res.coverage,
                }
            )
            print(f"inner[{backoff},{op_cov}] -> {res.statistical_state} adv={res.author_advantage:.4f} ci_lower={res.confidence_interval[0]:.4f}", flush=True)

    # 选择标准：statistical_state 最高（PASS > PARTIAL > FAIL > INVALID），同级看 ci_lower
    rank = {"PASS": 3, "PARTIAL": 2, "FAIL": 1, "INVALID": 0}
    chosen = max(
        inner_results,
        key=lambda r: (rank.get(r["statistical_state"], 0), r["ci_lower"]),
    )
    print(f"CHOSEN: backoff={chosen['backoff']} operating_coverage={chosen['operating_coverage']} (outer-train only)", flush=True)

    # ---- outer-test 一次评估 ----
    test_events = build_events(test_authors, pool)
    print(f"test_events={len(test_events)}", flush=True)
    outer_result = validate_decision_signature_v2(
        test_events,
        backoff=chosen["backoff"],
        operating_coverage=chosen["operating_coverage"],
    )
    summary = summarize(outer_result)
    print("OUTER_TEST_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)

    # 主终点判定
    passed = (
        summary["statistical_state"] == "PASS"
        and summary["coverage"] >= chosen["operating_coverage"]
        and summary["confidence_interval"][0] > 0
    )
    print(f"PRIMARY_ENDPOINT={'PASS' if passed else 'FAIL/PARTIAL'}", flush=True)
    print(f"CHOSEN_JSON={json.dumps(chosen, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    main()
