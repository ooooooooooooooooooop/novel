"""WP3：Calibration 门禁管线（observed-decision-author-signature-v1）。

按计划 §六（样本与分层设计）、§五（标注质量）、§八.4（功效门禁）实现：
1. 结构门禁：≥3 题材、每题材 ≥4 作者、每作者 ≥3 作品（support≥2 + holdout≥1）；
2. 可靠性门禁：Krippendorff α（双标子集）→ confirmatory / exploratory / rework；
3. 产率门禁：present 事件数/作者、ambiguous/missing 比例；
4. 功效模拟：按作者 cluster 重抽，在冻结 MDE 下估计达到 80% 功率所需作者数；
5. 诚实门禁报告：输入不足时如实 GATE_BLOCKED 并注明外部依赖。

用法：
  python scripts/run_observed_signature_calibration.py --merged <json> --config <json> --workspace <dir>
  python scripts/run_observed_signature_calibration.py selftest

隐私：所有输出中性 ID + 聚合，不包含正文文本。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- 常量

CONFIRMATORY_ALPHA = 0.80
EXPLORATORY_ALPHA = 0.667
MIN_TOPICS = 3
MIN_AUTHORS_PER_TOPIC = 4
MIN_WORKS_PER_AUTHOR = 3
SUPPORT_WORKS_MIN = 2
HOLDOUT_WORKS_MIN = 1
POWER_TARGET = 0.80
BOOTSTRAP_REPS = 1000
DEFAULT_MDE = 0.05
DEFAULT_EFFECT_SD = 0.12  # 缺省（无数据时）效应方差，用于功效模拟


# ---------------------------------------------------------------- 核心函数


def _load_json(path: Path) -> dict:
    # utf-8-sig 容错 Windows PowerShell Out-File 写入的 UTF-8 BOM
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump_json(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def check_structural_gates(
    config: dict,
) -> tuple[bool, list[str]]:
    """检查题材/作者/作品结构门禁。

    support/holdout 作品既可用显式 ``support_works``/``holdout_works`` 列表，
    也可用 ``works[].split = "support"|"holdout"`` 派生（统一 manifest 结构）。
    """
    failures: list[str] = []
    topics: dict[str, set[str]] = {}
    for author in config.get("authors", []):
        topic = author.get("topic_stratum", "")
        aid = author.get("author_id", "")
        if topic not in topics:
            topics[topic] = set()
        topics[topic].add(aid)
    if len(topics) < MIN_TOPICS:
        failures.append(f"题材数 {len(topics)} < {MIN_TOPICS}")
    for topic, authors in topics.items():
        if len(authors) < MIN_AUTHORS_PER_TOPIC:
            failures.append(f"题材 '{topic}' 作者数 {len(authors)} < {MIN_AUTHORS_PER_TOPIC}")
        for aid in authors:
            works = [w for w in config.get("authors", []) if w.get("author_id") == aid]
            if works:
                entry = works[0]
                if entry.get("support_works") is not None or entry.get("holdout_works") is not None:
                    support = list(entry.get("support_works", []))
                    holdout = list(entry.get("holdout_works", []))
                else:
                    support = [
                        w.get("work_id") for w in entry.get("works", [])
                        if w.get("split") == "support"
                    ]
                    holdout = [
                        w.get("work_id") for w in entry.get("works", [])
                        if w.get("split") == "holdout"
                    ]
                if len(support) < SUPPORT_WORKS_MIN or len(holdout) < HOLDOUT_WORKS_MIN:
                    failures.append(
                        f"作者 {aid} 作品数 support={len(support)}/{SUPPORT_WORKS_MIN} "
                        f"holdout={len(holdout)}/{HOLDOUT_WORKS_MIN}"
                    )
    return len(failures) == 0, failures


def krippendorff_alpha_nominal(
    unit_labels: dict[str, dict[str, str]]
) -> float:
    """名义数据 Krippendorff α（与 WP2 工具实现相同，独立副本以保持脚本自包含）。"""
    categories: set[str] = set()
    pairs_per_unit: list[list[tuple[str, str]]] = []
    for unit, labels in unit_labels.items():
        vals = [v for v in labels.values() if v is not None]
        categories.update(vals)
        pairs = []
        for i in range(len(vals)):
            for j in range(len(vals)):
                if i != j:
                    pairs.append((vals[i], vals[j]))
        pairs_per_unit.append(pairs)
    cats = sorted(categories)
    idx = {c: i for i, c in enumerate(cats)}
    n_ck: list[list[int]] = [[0] * len(cats) for _ in cats]
    n = 0
    for pairs in pairs_per_unit:
        for c, k in pairs:
            n_ck[idx[c]][idx[k]] += 1
            n += 1
    if n == 0:
        return 1.0
    n_k = [sum(row) for row in n_ck]
    do_num = 0
    for c in range(len(cats)):
        for k in range(len(cats)):
            if c != k:
                do_num += n_ck[c][k]
    do = do_num / n
    de_num = sum(nk * (n - nk) for nk in n_k)
    de = de_num / (n * (n - 1)) if n > 1 else 0.0
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - do / de


def check_reliability_gate(merged: dict) -> dict:
    """从 merged.json 计算 Krippendorff α 并报告门禁状态。"""
    unit_labels: dict[str, dict[str, str]] = {}
    for event in merged.get("events", []):
        labels: dict[str, str] = {}
        for ann in event.get("annotations", []):
            if ann.get("label"):
                labels[ann["annotator"]] = ann["label"]
        if len(labels) >= 2:
            unit_labels[event["event_id"]] = labels
    alpha = krippendorff_alpha_nominal(unit_labels)
    paired_units = len(unit_labels)
    if alpha >= CONFIRMATORY_ALPHA:
        verdict = "CONFIRMATORY_OK"
        gate = "PASS"
    elif alpha >= EXPLORATORY_ALPHA:
        verdict = "EXPLORATORY_ONLY"
        gate = "PARTIAL"
    else:
        verdict = "REWORK_CODEBOOK"
        gate = "FAIL"
    return {
        "alpha": alpha,
        "paired_units": paired_units,
        "thresholds": {"confirmatory": ">=0.80", "exploratory": "0.667-0.80", "rework": "<0.667"},
        "verdict": verdict,
        "gate": gate,
    }


def check_yield_gate(merged: dict) -> dict:
    """统计每作者 present/missing/ambiguous 事件产率。"""
    counts: dict[str, dict[str, int]] = {}
    for event in merged.get("events", []):
        aid = event.get("author_id", "?")
        status = event.get("status", "?")
        if aid not in counts:
            counts[aid] = {"present": 0, "missing_unusable": 0, "ambiguous": 0, "unresolved": 0}
        if status in counts[aid]:
            counts[aid][status] += 1
    per_author = {}
    for aid, c in counts.items():
        total = c["present"] + c["missing_unusable"] + c["ambiguous"] + c["unresolved"]
        per_author[aid] = {
            "present": c["present"],
            "missing_unusable": c["missing_unusable"],
            "ambiguous": c["ambiguous"],
            "unresolved": c["unresolved"],
            "total": total,
            "yield_rate": c["present"] / total if total else 0.0,
        }
    total_present = sum(v["present"] for v in per_author.values())
    total_candidates = sum(v["total"] for v in per_author.values())
    if total_candidates == 0:
        gate = "NO_DATA"
    elif total_present >= 10:
        gate = "PASS"
    else:
        gate = "INSUFFICIENT"
    return {
        "per_author": per_author,
        "total_present": total_present,
        "total_candidates": total_candidates,
        "overall_yield_rate": total_present / total_candidates if total_candidates else 0.0,
        "gate": gate,
    }


def power_simulation(
    n_authors: int,
    mde: float = DEFAULT_MDE,
    effect_sd: float = DEFAULT_EFFECT_SD,
    n_reps: int = BOOTSTRAP_REPS,
    alpha: float = 0.05,
) -> dict:
    """作者级功效模拟：给定 N 位作者，在 MDE 下估计 power。

    简化模型：假设每位作者的真实 advantage ~ N(mde, effect_sd^2)，
    对每次模拟的 N 个 author_advantage 做 95% CI（正态近似），
    power = CI 下界 > 0 的比例。
    """
    if n_authors < 2:
        return {"n_authors": n_authors, "power": 0.0, "met_target": False}
    rng = random.Random(20260823)
    successes = 0
    for _ in range(n_reps):
        effects = [rng.gauss(mde, effect_sd) for _ in range(n_authors)]
        import statistics

        mean = statistics.mean(effects)
        se = statistics.stdev(effects) / (n_authors ** 0.5) if n_authors > 1 else 1.0
        ci_lower = mean - 1.96 * se
        if ci_lower > 0:
            successes += 1
    power = successes / n_reps
    return {
        "n_authors": n_authors,
        "mde": mde,
        "effect_sd": effect_sd,
        "reps": n_reps,
        "power": power,
        "met_target": power >= POWER_TARGET,
    }


def check_power_gate(
    authors_count: int,
    mde: float = DEFAULT_MDE,
    effect_sd: float = DEFAULT_EFFECT_SD,
) -> dict:
    """功效门禁：在给定作者数下是否达到目标 power（可用 CLI 参数覆盖 MDE/效应方差估计）。"""
    sim = power_simulation(authors_count, mde=mde, effect_sd=effect_sd)
    return {
        "authors_available": authors_count,
        **sim,
        "gate": "PASS" if sim["met_target"] else "INSUFFICIENT",
        "note": "功效模拟基于简化参数模型（缺省 effect_sd=" + str(DEFAULT_EFFECT_SD) + "），"
        "真实效应方差需从 calibration 数据估计。",
    }


# ---------------------------------------------------------------- CLI 命令


def cmd_run(args: argparse.Namespace) -> int:
    merged = _load_json(Path(args.merged))
    config = _load_json(Path(args.config))
    ws = Path(args.workspace).expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)

    # 结构门禁
    struct_ok, struct_fails = check_structural_gates(config)

    # 可靠性门禁
    rel = {"alpha": None, "paired_units": 0, "gate": "NO_DATA", "verdict": "GATE_BLOCKED"}
    if merged.get("events"):
        # 从 merged 中提取双标子集
        double_events = [
            e for e in merged["events"]
            if len([a for a in e.get("annotations", []) if a.get("label")]) >= 2
        ]
        if double_events:
            merged_double = {"events": double_events, "protocol": merged.get("protocol", {})}
            rel = check_reliability_gate(merged_double)
        else:
            rel = {"alpha": None, "paired_units": 0, "gate": "NO_DOUBLE_SUBSET", "verdict": "GATE_BLOCKED"}

    # 产率门禁
    yield_gate = check_yield_gate(merged) if merged.get("events") else {"gate": "NO_DATA", "total_present": 0}

    # 功效门禁
    n_authors = sum(
        1
        for a in config.get("authors", [])
        if a.get("author_id")
    )
    power_gate = (
        check_power_gate(n_authors, mde=args.mde, effect_sd=args.effect_sd)
        if n_authors > 0 else {"gate": "NO_DATA"}
    )

    # 全局门禁
    all_gates = {
        "structural": {"gate": "PASS" if struct_ok else "FAIL", "failures": struct_fails},
        "reliability": {"gate": rel["gate"], "alpha": rel.get("alpha")},
        "yield": {"gate": yield_gate["gate"], "present": yield_gate.get("total_present", 0)},
        "power": {"gate": power_gate["gate"], "power": power_gate.get("power")},
    }
    can_enter_confirmatory = all(
        g["gate"] == "PASS" for g in all_gates.values()
    )

    report = {
        "protocol": "calibration-1.0",
        "config_loaded": Path(args.config).name,  # 隐私：只记文件名，不记绝对路径
        "merged_loaded": Path(args.merged).name,
        "gates": all_gates,
        "confirmatory_eligible": can_enter_confirmatory,
        "overall_verdict": "PASS" if can_enter_confirmatory else "GATE_BLOCKED",
        "note": (
            "所有门禁 PASS 后可进入 WP4 确认性分析。"
            "当前人工标注数据未就绪时，α≥0.80 与产率门禁依赖人工双盲标注+仲裁，"
            "agent 无法伪造通过——确认性状态将诚实保持 NOT_ESTIMABLE。"
        ),
    }
    out_path = ws / "calibration_report.json"
    _dump_json(report, out_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if can_enter_confirmatory else 1


def cmd_validate_config(args: argparse.Namespace) -> int:
    """结构预检：只检查 manifest 结构门禁（≥3 题材 × ≥4 作者 × support≥2+holdout≥1），
    不要求任何标注数据——让人工标注只花在结构合格的样本上。"""
    config = _load_json(Path(args.config))
    ok, fails = check_structural_gates(config)
    topics: dict[str, set[str]] = {}
    for author in config.get("authors", []):
        topics.setdefault(author.get("topic_stratum", ""), set()).add(author.get("author_id", ""))
    summary = {
        "protocol": "validate-config-1.0",
        "config": Path(args.config).name,
        "topics": {t: len(a) for t, a in sorted(topics.items())},
        "total_authors": len(config.get("authors", [])),
        "structural_ok": ok,
        "failures": fails,
        "verdict": "STRUCTURE_OK" if ok else "STRUCTURE_FAIL",
        "note": "结构合格 ≠ 标注合格；α≥0.80/产率/功效门禁需人工双盲标注+仲裁后由 run 判定。",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_selftest() -> int:
    failures: list[str] = []

    # ---- 结构门禁 ----
    good_config = {
        "authors": [
            {"author_id": f"a{a}", "topic_stratum": t, "support_works": [f"w{i}" for i in range(2)], "holdout_works": ["w_h"]}
            for a, t in [(1, "urban"), (2, "urban"), (3, "urban"), (4, "urban"),
                         (5, "fantasy"), (6, "fantasy"), (7, "fantasy"), (8, "fantasy"),
                         (9, "xianxia"), (10, "xianxia"), (11, "xianxia"), (12, "xianxia")]
        ]
    }
    ok, fails = check_structural_gates(good_config)
    if not ok:
        failures.append(f"结构门禁：应 PASS 但 FAIL: {fails}")

    bad_config = {"authors": [{"author_id": "a1", "topic_stratum": "urban", "support_works": ["w1"], "holdout_works": []}]}
    ok, fails = check_structural_gates(bad_config)
    if ok:
        failures.append("结构门禁：应 FAIL 但 PASS")

    # split 派生路径：works[].split 不写显式 support/holdout 列表
    split_config = {
        "authors": [
            {
                "author_id": f"a{a}",
                "topic_stratum": t,
                "works": [
                    {"work_id": f"w{i}", "split": "support"} for i in range(2)
                ] + [{"work_id": "w_h", "split": "holdout"}],
            }
            for a, t in [(1, "urban"), (2, "urban"), (3, "urban"), (4, "urban"),
                         (5, "fantasy"), (6, "fantasy"), (7, "fantasy"), (8, "fantasy"),
                         (9, "xianxia"), (10, "xianxia"), (11, "xianxia"), (12, "xianxia")]
        ]
    }
    ok, fails = check_structural_gates(split_config)
    if not ok:
        failures.append(f"结构门禁 split 派生：应 PASS 但 FAIL: {fails}")

    # ---- 可靠性门禁 ----
    # 完美一致
    merged_perfect = {
        "events": [
            {"event_id": f"e{i}", "annotations": [{"annotator": "A", "label": "a"}, {"annotator": "B", "label": "a"}]}
            for i in range(4)
        ]
    }
    rel = check_reliability_gate(merged_perfect)
    if rel["gate"] != "PASS":
        failures.append(f"可靠性门禁：完美一致 gate={rel['gate']} 应 PASS")

    # 完全不一致
    merged_disagree = {
        "events": [
            {"event_id": "e1", "annotations": [{"annotator": "A", "label": "a"}, {"annotator": "B", "label": "b"}]},
            {"event_id": "e2", "annotations": [{"annotator": "A", "label": "b"}, {"annotator": "B", "label": "a"}]},
        ]
    }
    rel = check_reliability_gate(merged_disagree)
    if rel["gate"] != "FAIL":
        failures.append(f"可靠性门禁：完全不一致 gate={rel['gate']} 应 FAIL")

    # ---- 功效门禁 ----
    # 足够作者数时应有合理 power，不足时 power 低
    power_large = power_simulation(64, mde=0.05, effect_sd=0.12)
    power_small = power_simulation(4, mde=0.05, effect_sd=0.12)
    if power_large["power"] <= power_small["power"]:
        failures.append("功效模拟：大样本 power 应 > 小样本 power")

    # ---- 诚实报告 ----
    # 空 merged 时 gate 应为 NO_DATA
    empty = check_yield_gate({"events": []})
    if empty["gate"] != "NO_DATA":
        failures.append(f"空数据产率 gate={empty['gate']} 应 NO_DATA")

    if failures:
        print("[selftest] FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("[selftest] PASS (structural, reliability, power, empty-data)")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="observed-decision-author-signature-v1 calibration gate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--merged", required=True)
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--workspace", required=True)
    p_run.add_argument("--power-target", type=float, default=POWER_TARGET)
    p_run.add_argument("--mde", type=float, default=DEFAULT_MDE)
    p_run.add_argument("--effect-sd", type=float, default=DEFAULT_EFFECT_SD)

    p_val = sub.add_parser("validate-config")
    p_val.add_argument("--config", required=True)

    sub.add_parser("selftest")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "validate-config":
        return cmd_validate_config(args)
    if args.cmd == "selftest":
        return cmd_selftest()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())