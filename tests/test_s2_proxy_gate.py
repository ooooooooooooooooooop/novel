"""S2（54 计划）备选纯代理指标终审闸测试.

验证 evaluate_proxy_final_gate 三轴判定：
- drift 轴：AI 化密度增量超阈值 fail / 不超 pass / 缺报告 unarmed
- ab_gain 轴：Wilson CI 下界 ≤0 fail / >0 pass / 缺报告 unarmed
- miss 轴：true miss rate 超阈值 fail / 不超 pass / 缺报告 unarmed
- 全 unarmed → route=unarmed（不静默放行）
"""
from __future__ import annotations

from src.workflow_action.proxy_final_gate import (
    PROXY_GATE_DEFAULTS,
    evaluate_proxy_final_gate,
)


def _drift(base_ai: float, chapter_ais: list[float]) -> dict:
    """构造 drift_report 样例：ai 密度由调用方直接给（chars=1 时 ai 计数=密度）. """
    def metrics(ai: float) -> dict:
        return {"surface": {"len": 10}, "ai": {"he_realized": ai}, "chars": 1}

    return {
        "baseline": metrics(base_ai),
        "chapters": [{"chapter_ref": f"c{i}", "metrics": metrics(a)}
                     for i, a in enumerate(chapter_ais)],
    }


def _ab(ci_low: float, net_rate: float = 0.1) -> dict:
    return {"net_rate": net_rate, "wilson_ci_low": ci_low}


def _audit(tmr: float, actionable: float = 0.1, blocking: float = 0.05) -> dict:
    return {
        "true_miss_rate": tmr,
        "actionable_true_miss_rate": actionable,
        "blocking_true_miss_rate": blocking,
    }


def test_drift_axis_pass() -> None:
    # baseline 0.05，章节均值 0.10 → delta 0.05 < 0.20 → pass
    result = evaluate_proxy_final_gate(drift_report=_drift(0.05, [0.10, 0.10]))
    assert result.route == "pass"
    assert result.met is True
    drift = result.axes[0]
    assert drift.met and not drift.unarmed


def test_drift_axis_fail() -> None:
    # baseline 0.05，章节均值 0.55 → delta 0.50 > 0.20 → fail
    result = evaluate_proxy_final_gate(drift_report=_drift(0.05, [0.55, 0.55]))
    assert result.route == "blocked"
    assert "drift unmet" in result.violations


def test_drift_axis_unarmed_without_report() -> None:
    result = evaluate_proxy_final_gate(ab_summary=_ab(0.05), audit_summary=_audit(0.1))
    assert result.axes[0].unarmed


def test_ab_gain_axis_pass_and_fail() -> None:
    assert evaluate_proxy_final_gate(
        drift_report=_drift(0.05, [0.10]), ab_summary=_ab(0.05),
        audit_summary=_audit(0.1)).route == "pass"
    blocked = evaluate_proxy_final_gate(
        drift_report=_drift(0.05, [0.10]), ab_summary=_ab(-0.02),
        audit_summary=_audit(0.1))
    assert blocked.route == "blocked"
    assert "ab_gain unmet" in blocked.violations


def test_miss_axis_fail() -> None:
    result = evaluate_proxy_final_gate(
        drift_report=_drift(0.05, [0.10]), ab_summary=_ab(0.05),
        audit_summary=_audit(0.60))
    assert result.route == "blocked"
    assert "miss unmet" in result.violations


def test_all_unarmed_is_explicit_unarmed() -> None:
    result = evaluate_proxy_final_gate()
    assert result.route == "unarmed"
    assert result.met is False
    assert result.violations and "no armed axis" in result.violations[0]


def test_thresholds_overridable() -> None:
    # 覆盖阈值：drift 上限 0.60 → delta 0.50 通过
    result = evaluate_proxy_final_gate(
        drift_report=_drift(0.05, [0.55]),
        ab_summary=_ab(0.05), audit_summary=_audit(0.1),
        thresholds={"drift_ai_delta_max": 0.60})
    assert result.route == "pass"


def test_defaults_are_sane() -> None:
    assert PROXY_GATE_DEFAULTS["drift_ai_delta_max"] == 0.20
    assert PROXY_GATE_DEFAULTS["ab_net_gain_ci_low_min"] == 0.0
    assert PROXY_GATE_DEFAULTS["true_miss_rate_max"] == 0.30
