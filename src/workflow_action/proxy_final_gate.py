"""S2（54 计划 §S2 备选路径）——纯代理指标终审闸（proxy final gate）。

裁判换位一致性在实机达不到 0.9 时的备选路线：把 drift 指标、AB 修订净收益
（Wilson CI）、true miss rate 组合成可审计的终审判定，完全绕开 LLM 裁判。

判定协议（全部确定性，无 LLM）：
- drift_axis     ：章节 AI 化指标密度增量超阈值 → fail（同向漂移提示质量退化）
- ab_gain_axis   ：AB 修订净收益（better−worse）Wilson CI 下界 ≤ 0 → fail
- miss_axis      ：独立盲审 true miss rate 超阈值 → fail（Review 漏检过多）

全轴 pass → route=pass；任一 fail → route=blocked；缺报告 → 该轴 unarmed
（显式，不静默放行，对齐 reader gate 先例）。

输入为结构化 dict（从 drift_report.json / blind_eval summary / pass_audit
summary 提取），用 .get 防御式读取，缺字段即 unarmed。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# 缺省阈值（S2 完成判据的可操作化；可在 evaluate 时覆盖）
PROXY_GATE_DEFAULTS: dict[str, float] = {
    "drift_ai_delta_max": 0.20,  # AI 化指标密度增量上限（baseline → 章节均值）
    "ab_net_gain_ci_low_min": 0.0,  # Wilson CI 下界必须 > 0 才算有净收益
    "true_miss_rate_max": 0.30,  # true miss rate 上限
}


@dataclass
class ProxyAxisResult:
    axis: str
    met: bool
    unarmed: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProxyFinalGateResult:
    met: bool
    route: str  # pass | blocked | unarmed
    axes: list[ProxyAxisResult]
    violations: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)


def _ai_density(metrics: Optional[dict]) -> Optional[float]:
    """从 measure_text 的 metrics 计算 AI 化指标密度（ai 计数 / 总字符数）.

    metrics 形如 {"surface": {...}, "ai": {...}, "chars": N}；ai 值为计数 dict。
    """
    if not metrics or "chars" not in metrics:
        return None
    chars = metrics["chars"]
    if not chars:
        return None
    ai = metrics.get("ai") or {}
    total = sum(v for v in ai.values() if isinstance(v, (int, float)))
    return total / chars


def evaluate_drift_axis(drift_report: Optional[dict], threshold: float) -> ProxyAxisResult:
    if not drift_report or "baseline" not in drift_report or "chapters" not in drift_report:
        return ProxyAxisResult("drift", met=False, unarmed=True, detail={"reason": "no drift report"})
    base = _ai_density(drift_report["baseline"])
    if base is None:
        return ProxyAxisResult("drift", met=False, unarmed=True, detail={"reason": "baseline unmeasurable"})
    chapter_densities = [
        d for d in (_ai_density(row.get("metrics")) for row in drift_report["chapters"]) if d is not None
    ]
    if not chapter_densities:
        return ProxyAxisResult("drift", met=False, unarmed=True, detail={"reason": "no chapter metrics"})
    mean_delta = sum(chapter_densities) / len(chapter_densities) - base
    met = mean_delta <= threshold
    return ProxyAxisResult(
        "drift",
        met=met,
        detail={"baseline_density": base, "chapter_mean_density": base + mean_delta,
                "mean_delta": mean_delta, "threshold": threshold},
    )


def evaluate_ab_gain_axis(ab_summary: Optional[dict], ci_low_min: float) -> ProxyAxisResult:
    if not ab_summary:
        return ProxyAxisResult("ab_gain", met=False, unarmed=True, detail={"reason": "no ab summary"})
    ci = ab_summary.get("wilson_ci_low")
    if ci is None and isinstance(ab_summary.get("ci"), dict):
        ci = ab_summary["ci"].get("low")
    if ci is None:
        return ProxyAxisResult("ab_gain", met=False, unarmed=True,
                               detail={"reason": "no wilson ci low bound"})
    met = ci > ci_low_min
    return ProxyAxisResult(
        "ab_gain", met=met,
        detail={"wilson_ci_low": ci, "ci_low_min": ci_low_min,
                "net_rate": ab_summary.get("net_rate")},
    )


def evaluate_miss_axis(audit_summary: Optional[dict], max_rate: float) -> ProxyAxisResult:
    if not audit_summary:
        return ProxyAxisResult("miss", met=False, unarmed=True, detail={"reason": "no audit summary"})
    tmr = audit_summary.get("true_miss_rate")
    if tmr is None:
        return ProxyAxisResult("miss", met=False, unarmed=True,
                               detail={"reason": "no true_miss_rate"})
    met = tmr <= max_rate
    return ProxyAxisResult(
        "miss", met=met,
        detail={"true_miss_rate": tmr, "max_rate": max_rate,
                "actionable": audit_summary.get("actionable_true_miss_rate"),
                "blocking": audit_summary.get("blocking_true_miss_rate")},
    )


def evaluate_proxy_final_gate(
    *,
    drift_report: Optional[dict] = None,
    ab_summary: Optional[dict] = None,
    audit_summary: Optional[dict] = None,
    thresholds: Optional[dict[str, float]] = None,
) -> ProxyFinalGateResult:
    """组合三轴为终审判定。全 unarmed → route=unarmed（不静默放行）。"""
    t = {**PROXY_GATE_DEFAULTS, **(thresholds or {})}
    axes = [
        evaluate_drift_axis(drift_report, t["drift_ai_delta_max"]),
        evaluate_ab_gain_axis(ab_summary, t["ab_net_gain_ci_low_min"]),
        evaluate_miss_axis(audit_summary, t["true_miss_rate_max"]),
    ]
    armed = [a for a in axes if not a.unarmed]
    if not armed:
        return ProxyFinalGateResult(
            met=False, route="unarmed", axes=axes,
            violations=["no armed axis: gate cannot adjudicate without evidence"],
            evidence={"thresholds": t},
        )
    violations = [a.axis for a in armed if not a.met]
    met = not violations
    return ProxyFinalGateResult(
        met=met,
        route="pass" if met else "blocked",
        axes=axes,
        violations=[f"{v} unmet" for v in violations],
        evidence={"thresholds": t},
    )
