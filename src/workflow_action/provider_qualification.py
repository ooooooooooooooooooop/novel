"""A1 Provider 资格门（Phase 3）：按角色产出 ProviderCapabilityReport 并裁决资格.

G7/G8 根因（2026-08-12 实证）是**单一 provider 的角色能力**，而非代码缺口：
deepseek-v4-flash 评审准确率 0.61<0.65 且生成层 4 次冒烟全败（thinking-only/超时/5xx）。
本门把「资格」从声明还原为**角色证据**，并用冻结 policy 阈值裁决（不降阈值）：

- 评审角色（reader_judge / fact_judge / character_judge）：资格 = 冻结 holdout
  `met` + `dimension_met.{overall,per_tag,position_consistency}` 全真，阈值取
  `policy.evaluation.*`（0.65/0.5/0.9）。证据来源：`auto-calibrate` 落盘的
  holdout_report.json（G7 同一份证据，无二次测量）。
- 生成角色（generation）：资格 = 无人冒烟端到端提交 ≥1 章 + 终态非
  execution_failed + 单章成本可被冻结预算吸收（≤ 预算上限/预期章数）。
  证据来源：canary 冒烟 run 的 terminal.json + manifest.json。

报告全凭证无关（只含模型身份/token/费用/门布尔/阈值 id/检查时间），可安全作为
发布证据；任何 provider 的角色资格失败都显式记录原因，不降阈值、不换门禁口径。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.object_state.autonomous import _StrictModel

JUDGE_ROLES = {"reader_judge", "fact_judge", "character_judge"}

_TERMINAL_NOT_FAILED = {
    "completed",
    "narrative_stopped",
    "quality_exhausted",
    "premise_exhausted",
    "budget_exhausted",
    "aborted",
}


class ProviderCapabilityReport(_StrictModel):
    """一个 (profile, role) 的角色能力证据与资格裁决."""

    schema_version: str = "1.0"
    profile_id: str
    role: str
    request_model: str
    actual_model: str
    qualified: bool
    reasons: list[str] = []
    evidence: dict = {}
    cost_usd: float = 0.0
    checked_at: str = ""


def _utc_now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 评审角色资格
# ---------------------------------------------------------------------------

def _judge_reasons(
    report: dict, policy_eval, holdout_thresholds: dict
) -> tuple[bool, list[str], list[str]]:
    """返回 (qualified, pass_reasons, fail_reasons)."""
    pass_reasons: list[str] = []
    fail_reasons: list[str] = []
    met = bool(report.get("met"))
    dims = report.get("dimension_met") or {}
    overall = bool(dims.get("overall"))
    per_tag = bool(dims.get("per_tag"))
    position = bool(dims.get("position_consistency"))
    if met:
        pass_reasons.append(f"holdout met（overall={report.get('overall_accuracy')}）")
    else:
        fail_reasons.append(
            f"holdout not met: {report.get('violations') or 'unknown'}"
        )
    for key, label, threshold in (
        ("overall", "overall accuracy", policy_eval.holdout_overall_accuracy_min),
        ("per_tag", "per-tag lower bound", policy_eval.holdout_genre_accuracy_min),
        (
            "position_consistency",
            "position consistency",
            policy_eval.pairwise_position_consistency_min,
        ),
    ):
        if dims.get(key):
            pass_reasons.append(
                f"{label} {report.get(key)} >= {threshold}"
            )
        else:
            fail_reasons.append(
                f"{label} {report.get(key)} < {threshold}"
            )
    if holdout_thresholds.get("thresholds_id"):
        pass_reasons.append(
            f"frozen thresholds_id={holdout_thresholds['thresholds_id']}"
        )
    return (bool(met and overall and per_tag and position), pass_reasons, fail_reasons)


def qualify_judge(
    profile,
    policy,
    holdout_report: Path,
    calibration_result: Path | None = None,
) -> ProviderCapabilityReport:
    """用冻结 holdout 证据裁决评审角色资格（G7 同一证据，不二次测量）."""
    report = json.loads(holdout_report.read_text(encoding="utf-8"))
    qualified, pass_reasons, fail_reasons = _judge_reasons(
        report, policy.evaluation, report
    )
    unreviewable: list = []
    if calibration_result and calibration_result.is_file():
        cal = json.loads(calibration_result.read_text(encoding="utf-8"))
        unreviewable = cal.get("quality", {}).get("unreviewable_pairs", [])
        if unreviewable:
            fail_reasons.append(f"unreviewable pairs: {len(unreviewable)}")
    evidence = {
        "overall_accuracy": report.get("overall_accuracy"),
        "per_tag_accuracy": report.get("per_tag_accuracy"),
        "position_consistency": report.get("position_consistency"),
        "dimension_met": report.get("dimension_met"),
        "violations": report.get("violations"),
        "thresholds_id": report.get("thresholds_id"),
        "unreviewable_count": len(unreviewable),
    }
    return ProviderCapabilityReport(
        profile_id=profile.profile_id,
        role="reader_judge",
        request_model=profile.roles.reader_judge.request_model,
        actual_model=profile.roles.reader_judge.expected_actual_model,
        qualified=qualified,
        reasons=sorted(set(pass_reasons)) if qualified else sorted(set(fail_reasons)),
        evidence=evidence,
        checked_at=_utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# 生成角色资格
# ---------------------------------------------------------------------------

def qualify_generation(
    profile,
    policy,
    smoke_terminal: Path,
    smoke_manifest: Path | None = None,
) -> ProviderCapabilityReport:
    """用无人冒烟证据裁决生成角色资格（G8 前置）.

    合格要求：终态非 execution_failed、至少提交 1 章、单章成本可被冻结预算吸收
    （run 总成本 ≤ max_total_cost_usd × committed/预期章数）。
    """
    terminal = json.loads(smoke_terminal.read_text(encoding="utf-8"))
    status = terminal.get("status")
    committed = int(terminal.get("committed_chapters") or 0)
    usage = terminal.get("usage") or {}
    cost = float(usage.get("cost_usd") or 0.0)
    gen = profile.roles.generation
    pass_reasons: list[str] = []
    fail_reasons: list[str] = []
    if status in _TERMINAL_NOT_FAILED and status != "execution_failed":
        pass_reasons.append(f"smoke terminal status={status}")
    else:
        fail_reasons.append(
            f"smoke terminal status={status}: {terminal.get('terminal_reason')}"
        )
    if committed >= 1:
        pass_reasons.append(f"committed {committed} chapter(s) unattended")
    else:
        fail_reasons.append("0 chapters committed unattended")
    budget = policy.budget
    expected = max(1, budget.max_chapters_per_run)
    per_chapter = cost / max(committed, 1)
    projected = per_chapter * expected
    if projected <= budget.max_total_cost_usd:
        pass_reasons.append(
            f"cost ${cost:.4f} run / ${per_chapter:.4f} per chapter; "
            f"projected {expected}-chapter run ${projected:.2f} <= "
            f"budget ceiling ${budget.max_total_cost_usd}"
        )
    else:
        fail_reasons.append(
            f"projected {expected}-chapter run cost ${projected:.2f} exceeds "
            f"budget ceiling ${budget.max_total_cost_usd} (per-chapter ${per_chapter:.4f})"
        )
    qualified = not fail_reasons
    evidence = {
        "smoke_status": status,
        "terminal_reason": terminal.get("terminal_reason"),
        "committed_chapters": committed,
        "usage": usage,
        "model": gen.request_model,
    }
    return ProviderCapabilityReport(
        profile_id=profile.profile_id,
        role="generation",
        request_model=gen.request_model,
        actual_model=gen.expected_actual_model,
        qualified=qualified,
        reasons=pass_reasons if qualified else fail_reasons,
        evidence=evidence,
        cost_usd=cost,
        checked_at=_utc_now_iso(),
    )
