"""S7（54 计划 §S7）大神级判据操作化测试.

锁住 long_run_judgment 的合取裁决逻辑：
- 全绿 → long_run_authorized
- 任一红 → 缺口报告含该指标 + 对应 S 阶段
- pending（未武装）→ 不授权（不静默放行）
- 七项指标齐备（54 §S7 指标集完整）
"""
from __future__ import annotations

import hashlib
import json

from scripts.long_run_judgment import METRICS, judge, main

ALL_GREEN = {
    "reader_window_weak": True,
    "style_drift_within": True,
    "ab_net_gain_positive": True,
    "true_miss_within": True,
    "causal_suite_blocked_all": True,
    "judge_swap_consistency_ge": True,
    "canary_90_all_green": True,
}


def test_all_green_authorizes() -> None:
    outcome = judge(ALL_GREEN)
    assert outcome["authorized"] is True
    assert outcome["verdict"] == "long_run_authorized"


def test_any_red_blocks_with_phase() -> None:
    for key in ALL_GREEN:
        metrics = dict(ALL_GREEN)
        metrics[key] = False
        outcome = judge(metrics)
        assert outcome["authorized"] is False
        assert outcome["verdict"] == "long_run_not_authorized"
        assert key in outcome["red"], f"{key} 应进缺口报告"


def test_pending_does_not_silently_pass() -> None:
    metrics = dict(ALL_GREEN)
    metrics["causal_suite_blocked_all"] = None  # 未武装
    outcome = judge(metrics)
    assert outcome["authorized"] is False, "pending 指标不得静默放行"
    assert "causal_suite_blocked_all" in outcome["pending"]


def test_every_metric_maps_to_s_phase() -> None:
    phases = {v[1] for v in METRICS.values()}
    assert len(phases) >= 5, "指标应覆盖 S2/S3/S5/S6 等多阶段"


def test_seven_metric_contract() -> None:
    assert set(METRICS) == set(ALL_GREEN), "54 §S7 指标集必须齐备"


def test_green_report_excludes_gaps(tmp_path) -> None:
    outcome = judge(ALL_GREEN)
    assert outcome["red"] == [] and outcome["pending"] == []
    assert len(outcome["green"]) == 7

    sources = {
        "prospective_four_metric": {
            "thresholds": {
                "style_drift_max_ratio": 1.2,
                "true_miss_rate_max": 0.2,
                "judge_swap_consistency_min": 0.9,
            },
            "conjunction": {
                "reader_window_weak": True,
                "style_drift_within": True,
                "true_miss_within": True,
                "judge_swap_consistency_ge": True,
            },
        },
        "s6_canary": {
            "certified": True,
            "total_expected": 90,
            "total_committed": 90,
        },
        "ab_net_gain": {
            "met_net_gain": True,
            "wilson_ci_low": 0.5,
        },
        "causal_suite": {
            "suite_pass": True,
            "total_cases": 10,
            "ok_cases": 10,
        },
    }
    refs = {}
    for name, payload in sources.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        refs[name] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    bundle_path = tmp_path / "evidence_bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "s7_evidence_bundle",
                "sources": refs,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "judgment.json"
    assert main([
        "--evidence-bundle", str(bundle_path),
        "--output", str(output_path),
    ]) == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["authorized"] is True
    assert written["metrics"] == ALL_GREEN
    sources["s6_canary"]["total_committed"] = 89
    (tmp_path / "s6_canary.json").write_text(
        json.dumps(sources["s6_canary"]), encoding="utf-8"
    )
    assert main(["--evidence-bundle", str(bundle_path)]) == 1
