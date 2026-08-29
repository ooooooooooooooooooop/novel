"""S7（54 计划 §S7）「大神级」判据操作化——全自动可测指标合取裁决器.

把「大神级」从「等人类阅读实验裁决」重定义为全自动可测指标的合取：
全绿 → 输出 `long_run_authorized`；任一不绿 → 输出具体缺口报告并指回对应
S 阶段（终态永远是有路可走的工程问题，不是等批准的阻塞）。

指标集（阈值用项目已有历史实验数据初始标定，随数据滚动校准）：
  1. 读者门禁 12 维窗口无 weak                      （reader_window_weak=False）
  2. style drift 指标 ≤ 阈值                        （style_drift_within=True）
  3. AB 修订净收益 > 0（Wilson CI 下界 > 0）        （ab_net_gain_positive=True）
  4. true miss rate ≤ 阈值                          （true_miss_within=True）
  5. 因果对抗集全阻断（S3 资产复用）                 （causal_suite_blocked_all=True）
  6. 裁判换位一致性 ≥ 0.9（S2 资产复用）             （judge_swap_consistency_ge=True）
  7. 90 章无人 Canary 全绿（S6 资产复用）            （canary_90_all_green=True）

指标来源（probe）：优先从资产文件读取；无真机产物 → 该指标状态 = pending
（未武装，不静默放行）。显式 --metrics 传入 dict 用于可复现判定与测试。

用法：python scripts/long_run_judgment.py [--metrics metrics.json]
隐私：只读中性指标状态，不接触真实小说工作区。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# 指标定义：key → (说明, 对应 S 阶段, 缺口修复指引)
METRICS: dict[str, tuple[str, str, str]] = {
    "reader_window_weak": (
        "读者门禁 12 维窗口无 weak（True=无 weak）",
        "S6/读者门禁",
        "运行 novel reader --window 3|5 产 serial_reader_report.json，关键维 weak → 修订正文",
    ),
    "style_drift_within": (
        "style drift 指标 ≤ 阈值（True=在界内）",
        "S5/drift",
        "运行 novel drift 产 drift_report.json，AI 化指标超阈 → 调整生成/修订",
    ),
    "ab_net_gain_positive": (
        "AB 修订净收益 > 0（Wilson CI 下界 > 0，True=为正）",
        "S5/AB",
        "运行 novel ab 汇总 prose_revision_ledger.json，净收益非正 → 回看修订策略",
    ),
    "true_miss_within": (
        "PASS 盲审 true miss rate ≤ 阈值（True=在界内）",
        "S2/PASS 审计",
        "运行 novel audit-pass，miss rate 超阈 → 补审查维度/门禁",
    ),
    "causal_suite_blocked_all": (
        "因果对抗集全阻断（5 类攻击，S3 资产，True=全阻断）",
        "S3",
        "运行 scripts/run_causal_adversarial_suite.py，有漏阻断 → 补检测器",
    ),
    "judge_swap_consistency_ge": (
        "裁判换位一致性 ≥ 0.9（S2 资产，True=达标）",
        "S2",
        "换位一致性不足 → 裁判去偏/多裁判多数决治理",
    ),
    "canary_90_all_green": (
        "90 章无人 Canary 全绿（S6 资产，True=全绿）",
        "S6",
        "运行 a1_release_validation.py 聚合，有红 → 指回对应 S 阶段",
    ),
}

# 默认标定阈值（项目历史实验数据初始标定，随数据滚动校准）
DEFAULTS: dict[str, Any] = {
    "style_drift_max_ratio": 1.2,
    "ab_wilson_ci_lower_min": 0.0,
    "true_miss_rate_max": 0.20,
    "judge_swap_consistency_min": 0.9,
    "reader_window_size": 12,
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_legacy_evidence_anchor(
    anchor_path: Path | None = None,
) -> None:
    """运行时校验旧 S7 权威资产未被本轮原地改写。"""
    path = anchor_path or (
        REPO_ROOT / "runtime/refs/cpa_active/s7/final_evidence_anchor.json"
    )
    anchor = json.loads(path.read_text(encoding="utf-8"))
    for item in anchor.get("evidence", []):
        if item.get("type") != "artifact":
            continue
        artifact = REPO_ROOT / item["path"]
        if not artifact.is_file() or _sha256_file(artifact) != item.get("sha256"):
            raise ValueError(
                f"legacy S7 evidence hash mismatch: {item.get('path')}"
            )


def _resolve_source(bundle_path: Path, item: dict) -> Path:
    raw = Path(item["path"])
    path = raw if raw.is_absolute() else (bundle_path.parent / raw).resolve()
    if not path.is_file() or _sha256_file(path) != item.get("sha256"):
        raise ValueError(f"evidence source hash mismatch: {item.get('path')}")
    return path


def load_verified_metrics(bundle_path: Path) -> tuple[dict[str, bool], dict]:
    """从四类带 SHA 资产推导七指标；不读取用户自填布尔。"""
    verify_legacy_evidence_anchor()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if (
        bundle.get("schema_version") != 1
        or bundle.get("kind") != "s7_evidence_bundle"
        or set(bundle.get("sources", {}))
        != {"prospective_four_metric", "s6_canary", "ab_net_gain", "causal_suite"}
    ):
        raise ValueError("invalid S7 evidence bundle")
    sources = bundle["sources"]
    prospective_path = _resolve_source(
        bundle_path, sources["prospective_four_metric"]
    )
    s6_path = _resolve_source(bundle_path, sources["s6_canary"])
    ab_path = _resolve_source(bundle_path, sources["ab_net_gain"])
    causal_path = _resolve_source(bundle_path, sources["causal_suite"])
    prospective = json.loads(prospective_path.read_text(encoding="utf-8"))
    s6 = json.loads(s6_path.read_text(encoding="utf-8"))
    ab = json.loads(ab_path.read_text(encoding="utf-8"))
    causal = json.loads(causal_path.read_text(encoding="utf-8"))
    thresholds = prospective.get("thresholds") or {}
    if thresholds != {
        "style_drift_max_ratio": DEFAULTS["style_drift_max_ratio"],
        "true_miss_rate_max": DEFAULTS["true_miss_rate_max"],
        "judge_swap_consistency_min": DEFAULTS["judge_swap_consistency_min"],
    }:
        raise ValueError("prospective thresholds do not match frozen S7 thresholds")
    conjunction = prospective.get("conjunction") or {}
    required_four = {
        "reader_window_weak",
        "style_drift_within",
        "true_miss_within",
        "judge_swap_consistency_ge",
    }
    if set(conjunction) != required_four:
        raise ValueError("prospective four-metric conjunction is incomplete")
    metrics = {
        **{key: conjunction[key] is True for key in required_four},
        "ab_net_gain_positive": (
            bool(ab.get("met_net_gain"))
            and float(ab.get("wilson_ci_low", 0)) > DEFAULTS["ab_wilson_ci_lower_min"]
        ),
        "causal_suite_blocked_all": (
            bool(causal.get("suite_pass"))
            and int(causal.get("ok_cases", 0)) == int(causal.get("total_cases", -1))
            and int(causal.get("total_cases", 0)) > 0
        ),
        "canary_90_all_green": (
            bool(s6.get("certified"))
            and int(s6.get("total_expected", 0)) == 90
            and int(s6.get("total_committed", 0)) == 90
        ),
    }
    if set(metrics) != set(METRICS):
        raise ValueError("derived metric set differs from S7 contract")
    return metrics, bundle


def probe_metrics() -> dict[str, Any]:
    """从资产文件探测指标状态；无真机产物 → 对应指标 pending（未武装）."""
    state: dict[str, Any] = {}

    # S3 对抗集：直接运行脚本太重——检查其结构化报告入口；缺省 pending
    state["causal_suite_blocked_all"] = None  # pending：需运行 run_causal_adversarial_suite.py

    # S2 换位一致性：policy 常量在源码（autonomous.py pairwise_position_consistency_min）
    policy_src = (REPO_ROOT / "src" / "object_state" / "autonomous.py").read_text(encoding="utf-8")
    state["judge_swap_consistency_min"] = DEFAULTS["judge_swap_consistency_min"]

    # 读者门禁 12 维窗口无 weak：serial_reader_report.json 产物
    state["reader_window_weak"] = None  # pending

    # drift / AB / miss rate / canary：产物不存在 → pending
    state["style_drift_within"] = None
    state["ab_net_gain_positive"] = None
    state["true_miss_within"] = None
    state["canary_90_all_green"] = None
    return state


def judge(metrics: dict[str, Any]) -> dict[str, Any]:
    """合取裁决：全绿 → long_run_authorized；任一红/pending → 缺口报告."""
    results: dict[str, Any] = {}
    for key, (label, phase, fix) in METRICS.items():
        value = metrics.get(key)
        if value is None:
            results[key] = {"status": "pending", "label": label, "phase": phase, "fix": fix}
        elif value is True:
            results[key] = {"status": "green", "label": label, "phase": phase, "fix": fix}
        else:
            results[key] = {"status": "red", "label": label, "phase": phase, "fix": fix}
    green = [k for k, r in results.items() if r["status"] == "green"]
    red = [k for k, r in results.items() if r["status"] == "red"]
    pending = [k for k, r in results.items() if r["status"] == "pending"]
    authorized = not red and not pending
    return {
        "authorized": authorized,
        "verdict": "long_run_authorized" if authorized else "long_run_not_authorized",
        "green": green,
        "red": red,
        "pending": pending,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S7 大神级判据合取裁决器")
    parser.add_argument(
        "--evidence-bundle",
        type=Path,
        default=None,
        help="带 SHA 来源锁的 S7 evidence bundle；缺省只探测 pending，永不授权",
    )
    parser.add_argument("--output", type=Path, default=None,
                        help="可选：把完整授权/缺口裁决 JSON 写入此路径")
    args = parser.parse_args(argv)

    bundle = None
    if args.evidence_bundle is not None:
        if not args.evidence_bundle.is_file():
            print("Error: evidence bundle not found")
            return 1
        try:
            metrics, bundle = load_verified_metrics(args.evidence_bundle.resolve())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Error: invalid S7 evidence bundle: {exc}")
            return 1
    else:
        metrics = probe_metrics()

    outcome = judge(metrics)
    outcome["metrics"] = {key: metrics.get(key) for key in METRICS}
    if args.evidence_bundle is not None:
        outcome["evidence_bundle"] = {
            "path": str(args.evidence_bundle.resolve()),
            "sha256": _sha256_file(args.evidence_bundle.resolve()),
        }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("S7 大神级判据合取裁决")
    for key, result in outcome["results"].items():
        marker = {"green": "PASS", "red": "FAIL", "pending": "PEND"}[result["status"]]
        print(f"  [{marker}] {result['label']}")
    print(f"VERDICT: {outcome['verdict']}")
    if not outcome["authorized"]:
        print("缺口报告（终态是工程问题，不是等批准的阻塞）：")
        for key in outcome["red"] + outcome["pending"]:
            result = outcome["results"][key]
            print(f"  - [{key}] 阶段 {result['phase']}：{result['fix']}")
    return 0 if outcome["authorized"] else 1


if __name__ == "__main__":
    sys.exit(main())
