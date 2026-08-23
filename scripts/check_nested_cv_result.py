"""nested-CV 确认性 pilot 结果核对脚本。

用法：将 pilot 回报的 OUTER_TEST 段 JSON 复制到此处，运行本脚本核对主/次终点。
"""

from __future__ import annotations
from typing import Any


def check_primary_endpoint(result: dict[str, Any], operating_coverage: float) -> tuple[str, list[str]]:
    """主终点：statistical_state == PASS 且 coverage >= operating_coverage 且 CI 下界 > 0."""
    reasons: list[str] = []
    state = result.get("statistical_state", "INVALID")
    coverage = result.get("coverage", 0.0)
    ci = result.get("confidence_interval", [0.0, 0.0])
    advantage = result.get("author_advantage", 0.0)

    if state != "PASS":
        reasons.append(f"statistical_state={state} 不是 PASS")
    if coverage < operating_coverage:
        reasons.append(f"coverage={coverage:.6f} < operating_coverage={operating_coverage}")
    if ci[0] <= 0:
        reasons.append(f"CI 下界={ci[0]:.6f} 不大于 0")
    if advantage <= 0:
        reasons.append(f"author_advantage={advantage:.6f} 不大于 0")

    if not reasons:
        return ("PASS", ["主终点通过：出版文本代理预测资格（确认性）"])
    return ("FAIL", reasons)


def check_secondary_endpoints(result: dict[str, Any]) -> dict[str, Any]:
    """次终点：独立报告，不混入统计状态。"""
    return {
        "aurc": result.get("aurc"),
        "c_at_1": result.get("c_at_1"),
        "f_half_u": result.get("f_half_u"),
        "hard_negative_advantage": result.get("hard_negative_advantage"),
        "full_coverage_deployment_state": result.get("full_coverage_deployment_state"),
    }


def full_report(result: dict[str, Any], operating_coverage: float) -> str:
    lines = [
        "=== nested-CV 确认性 pilot 结果核对 ===",
        "",
        f"statistical_state           = {result.get('statistical_state')}",
        f"full_coverage_deployment    = {result.get('full_coverage_deployment_state')}",
        f"coverage                    = {result.get('coverage'):.6f}" if result.get('coverage') is not None else "coverage = None",
        f"selective_risk              = {result.get('selective_risk')}",
        f"aurc                        = {result.get('aurc')}",
        f"c_at_1                      = {result.get('c_at_1')}",
        f"f_half_u                    = {result.get('f_half_u')}",
        f"author_accuracy             = {result.get('author_accuracy', 0.0):.4f}",
        f"hard_negative_accuracy      = {result.get('hard_negative_accuracy', 0.0):.4f}",
        f"author_advantage            = {result.get('author_advantage', 0.0):.4f}",
        f"confidence_interval         = {result.get('confidence_interval')}",
        f"permutation_p_value         = {result.get('permutation_p_value')}",
        f"hard_negative_advantage     = {result.get('hard_negative_advantage', 0.0):.4f}",
        f"evaluated_event_count       = {result.get('evaluated_event_count')}",
        f"fold_count                  = {result.get('fold_count')}",
        f"invalid_reasons             = {result.get('invalid_reasons')}",
        f"warnings                    = {result.get('warnings')}",
        f"backoff_used                = {result.get('backoff_used')}",
        f"backoff_events              = {result.get('backoff_events')}",
        f"operating_coverage          = {result.get('operating_coverage')}",
        "",
    ]
    status, reasons = check_primary_endpoint(result, operating_coverage)
    lines.append(f"主终点：{status}")
    for r in reasons:
        lines.append(f"  - {r}")
    lines.append("")
    sec = check_secondary_endpoints(result)
    lines.append("次终点（独立报告）：")
    for k, v in sec.items():
        lines.append(f"  {k} = {v}")
    lines.append("")
    lines.append(f"整体结论：{status}")
    if status == "PASS":
        lines.append("出版文本代理预测资格（确认性）—— 可记录。")
    else:
        lines.append("未达主终点；如实记录 FAIL/PARTIAL，不得事后调阈值。")
    return "\n".join(lines)


if __name__ == "__main__":
    # 示例：将 outer_test 结果 JSON 粘贴为以下字典
    SAMPLE = {
        "statistical_state": "PASS",
        "full_coverage_deployment_state": "PASS",
        "coverage": 1.0,
        "selective_risk": 0.0,
        "aurc": 0.0,
        "c_at_1": 1.0,
        "f_half_u": 1.0,
        "author_accuracy": 1.0,
        "hard_negative_accuracy": 0.0,
        "author_advantage": 0.9167,
        "confidence_interval": [0.88469, 0.948643],
        "permutation_p_value": 0.0,
        "hard_negative_advantage": 1.0,
        "evaluated_event_count": 72,
        "fold_count": 6,
        "invalid_reasons": [],
        "warnings": [],
        "backoff_used": "partial_pool",
        "backoff_events": 0,
        "operating_coverage": 0.9,
    }
    print(full_report(SAMPLE, 0.9))