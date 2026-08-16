"""Taste Stack 评价体系与统一质量报告聚合器 (P4).

根据 docs/00_project/52_mastery_upgrade_plan.md §5:
- 聚合 5 层评价体系（确定性硬门禁 / 专门轴 / Blind Eval / PASS Audit / 人类隐藏来源验证）。
- 严格基于真实证据文件：无证据为 not_run，损坏为 invalid_evidence，只有经验证真实结果为 passed/completed。
- 禁止输出单一「最终大神分数」。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Optional

from src.object_state.taste_stack import (
    G7RetirementNotice,
    Layer1HardGatesSummary,
    Layer2SpecializedAxesSummary,
    Layer3BlindEvalSummary,
    Layer4PassAuditSummary,
    Layer5HumanBlindEvalSummary,
    StyleDriftSummary,
    UnifiedQualityReport,
)


def compute_wilson_ci(pos: int, total: int, z: float = 1.95996) -> tuple[float, float]:
    """计算 95% Wilson Score 置信区间 (用于盲评净收益)."""
    if total <= 0 or pos < 0:
        return (0.0, 0.0)
    p_hat = pos / total
    denom = 1.0 + (z * z) / total
    center = (p_hat + (z * z) / (2 * total)) / denom
    under_sqrt = (p_hat * (1.0 - p_hat) / total) + (z * z) / (4 * total * total)
    margin = (z * math.sqrt(max(0.0, under_sqrt))) / denom
    lower = round(max(0.0, center - margin), 4)
    upper = round(min(1.0, center + margin), 4)
    return (lower, upper)


def _safe_read_json(path: Path) -> tuple[Optional[dict | list], Optional[str]]:
    """安全读取 JSON 文件，返回 (data, error_str)."""
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw), None
    except UnicodeDecodeError as exc:
        return None, f"encoding error: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"corrupted json: {exc}"
    except OSError as exc:
        return None, f"io error: {exc}"


def _sha256_path(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _extract_layer1_evidence(output_dir: Optional[Path]) -> Layer1HardGatesSummary:
    """第 1 层确定性硬门禁：从 reader_gate_report.json / run_manifest.json 提取真实证据并严格绑定身份."""
    if output_dir is None:
        return Layer1HardGatesSummary(status="not_run")

    gate_report_path = output_dir / "reader_gate_report.json"
    if not gate_report_path.exists():
        # 尝试检查子目录或父目录
        candidates = list(output_dir.glob("**/reader_gate_report.json"))
        if candidates:
            gate_report_path = candidates[0]

    if not gate_report_path.exists():
        return Layer1HardGatesSummary(status="not_run")

    data, err = _safe_read_json(gate_report_path)
    if err is not None or not isinstance(data, dict):
        return Layer1HardGatesSummary(
            status="invalid_evidence",
            evidence_paths=[str(gate_report_path)],
            errors=[err or "invalid payload shape"],
        )

    # 检查 run_manifest.json 并核对不可变身份
    manifest_path = output_dir / "run_manifest.json"
    if not manifest_path.exists():
        candidates = list(output_dir.glob("**/run_manifest.json"))
        if candidates:
            manifest_path = candidates[0]

    evidence_hashes = {str(gate_report_path): _sha256_path(gate_report_path)}
    manifest_errors: list[str] = []
    if manifest_path.exists():
        evidence_hashes[str(manifest_path)] = _sha256_path(manifest_path)
        m_data, m_err = _safe_read_json(manifest_path)
        if m_err is not None or not isinstance(m_data, dict):
            manifest_errors.append(f"manifest corrupted: {m_err}")
        else:
            m_status = m_data.get("status")
            if m_status != "committed":
                manifest_errors.append(f"manifest status is '{m_status}', not 'committed'")
            gate_ch = data.get("chapter_ref")
            m_ch = m_data.get("chapter_ref")
            if gate_ch and m_ch and gate_ch != m_ch:
                manifest_errors.append(f"chapter_ref mismatch: gate ({gate_ch}) vs manifest ({m_ch})")

    route = data.get("route", "")
    reasons = data.get("reasons", [])
    issues = data.get("issues", [])
    axes_armed = data.get("axes_armed", {})

    blocking_issues = [i for i in issues if isinstance(i, dict) and i.get("severity") in ("blocking", "critical")]
    blocking_count = len(blocking_issues)

    if manifest_errors:
        status = "invalid_evidence" if any("corrupted" in e or "mismatch" in e for e in manifest_errors) else "blocked"
    else:
        status = "passed" if route == "pass" and blocking_count == 0 else "blocked"

    checked_gates = list(axes_armed.keys()) if axes_armed else ["reader_gate"]

    return Layer1HardGatesSummary(
        status=status,
        checked_gates=checked_gates,
        blocking_issues_count=blocking_count,
        blocking_issues_details=blocking_issues,
        evidence_count=len(axes_armed) if axes_armed else 1,
        evidence_paths=[str(gate_report_path)] + ([str(manifest_path)] if manifest_path.exists() else []),
        evidence_hashes=evidence_hashes,
        errors=manifest_errors,
    )


def _extract_layer2_evidence(output_dir: Optional[Path]) -> Layer2SpecializedAxesSummary:
    """第 2 层专门轴评价：从 reader_experience 真实产物提取."""
    if output_dir is None:
        return Layer2SpecializedAxesSummary(status="not_run")

    rx_dir = output_dir.parent / "reader_experience" if output_dir.name in ("audit", "extend", "compose") else output_dir / "reader_experience"
    report_candidates = []
    if rx_dir.exists():
        report_candidates.extend(list(rx_dir.glob("*.json")))

    if not report_candidates:
        return Layer2SpecializedAxesSummary(status="not_run")

    evaluated_axes = {}
    unreviewable = []
    evidence_paths = []
    errors = []

    for r_path in report_candidates:
        evidence_paths.append(str(r_path))
        data, err = _safe_read_json(r_path)
        if err is not None or not isinstance(data, dict):
            errors.append(f"{r_path.name}: {err or 'invalid json'}")
            continue

        # 解析报告中的 evaluation / axes 字段
        scores = data.get("scores") or data.get("axes") or {}
        if isinstance(scores, dict):
            for k, v in scores.items():
                if isinstance(v, dict):
                    evaluated_axes[k] = v
                else:
                    evaluated_axes[k] = {"score": v}

    if errors and not evaluated_axes:
        return Layer2SpecializedAxesSummary(
            status="invalid_evidence",
            evidence_paths=evidence_paths,
            errors=errors,
        )

    status = "completed" if evaluated_axes else "not_run"
    return Layer2SpecializedAxesSummary(
        status=status,
        evaluated_axes=evaluated_axes,
        unreviewable_axes=unreviewable,
        evidence_paths=evidence_paths,
        errors=errors,
    )


def _extract_layer3_evidence(output_dir: Optional[Path]) -> Layer3BlindEvalSummary:
    """第 3 层 Blind Eval：必须读取真实盲评结果计算 Wilson CI，不直接把 Revision Ledger 默认为 better."""
    if output_dir is None:
        return Layer3BlindEvalSummary(status="not_run")

    # 查找盲评报告
    blind_report_path = output_dir / "ab_blind_eval_report.json"
    if not blind_report_path.exists():
        candidates = list(output_dir.glob("**/ab_blind_eval_report.json"))
        if candidates:
            blind_report_path = candidates[0]

    if blind_report_path.exists():
        data, err = _safe_read_json(blind_report_path)
        if err is not None or not isinstance(data, dict):
            return Layer3BlindEvalSummary(
                status="invalid_evidence",
                evidence_paths=[str(blind_report_path)],
                errors=[err or "invalid blind eval report"],
            )
        better = int(data.get("better_count", 0))
        worse = int(data.get("worse_count", 0))
        no_diff = int(data.get("no_difference_count", 0))
        uncertain = int(data.get("uncertain_count", 0))
        sum_parts = better + worse + no_diff + uncertain

        if "total_pairs_evaluated" in data:
            declared_total = int(data["total_pairs_evaluated"])
            if declared_total != sum_parts:
                return Layer3BlindEvalSummary(
                    status="invalid_evidence",
                    evidence_paths=[str(blind_report_path)],
                    errors=[f"arithmetic mismatch: declared total {declared_total} != sum of parts ({sum_parts})"],
                )
            total = declared_total
        else:
            total = sum_parts

        net_rate = (better - worse) / total if total > 0 else 0.0
        wilson = compute_wilson_ci(better, total)

        return Layer3BlindEvalSummary(
            status="completed" if total > 0 else "not_run",
            total_pairs_evaluated=total,
            better_count=better,
            worse_count=worse,
            no_difference_count=no_diff,
            uncertain_count=uncertain,
            net_improvement_rate=round(net_rate, 4),
            wilson_ci_95=wilson,
            stratified_by_issue_type=data.get("stratified_by_issue_type", {}),
            evidence_paths=[str(blind_report_path)],
        )

    # 若仅存在 prose_revision_ledger.json 但没有盲评 Judge 结果，诚实报告 not_run
    ab_ledger_path = output_dir / "prose_revision_ledger.json"
    if not ab_ledger_path.exists():
        candidates = list(output_dir.glob("**/prose_revision_ledger.json"))
        if candidates:
            ab_ledger_path = candidates[0]

    if ab_ledger_path.exists():
        data, err = _safe_read_json(ab_ledger_path)
        if err is not None:
            return Layer3BlindEvalSummary(
                status="invalid_evidence",
                evidence_paths=[str(ab_ledger_path)],
                errors=[err],
            )
        entries = data if isinstance(data, list) else (data.get("entries", []) if isinstance(data, dict) else [])
        # 检查是否有实际 judge 结果
        judged_better = 0
        judged_worse = 0
        judged_no_diff = 0
        judged_uncertain = 0
        has_judge = False

        for e in entries:
            if isinstance(e, dict) and "judge_verdict" in e:
                has_judge = True
                v = e.get("judge_verdict")
                if v in ("better", "version_b_better", "revised_better"):
                    judged_better += 1
                elif v in ("worse", "version_a_better", "original_better"):
                    judged_worse += 1
                elif v == "no_difference":
                    judged_no_diff += 1
                else:
                    judged_uncertain += 1

        if has_judge:
            total = judged_better + judged_worse + judged_no_diff + judged_uncertain
            net_rate = (judged_better - judged_worse) / total if total > 0 else 0.0
            wilson = compute_wilson_ci(judged_better, total)
            return Layer3BlindEvalSummary(
                status="completed" if total > 0 else "not_run",
                total_pairs_evaluated=total,
                better_count=judged_better,
                worse_count=judged_worse,
                no_difference_count=judged_no_diff,
                uncertain_count=judged_uncertain,
                net_improvement_rate=round(net_rate, 4),
                wilson_ci_95=wilson,
                evidence_paths=[str(ab_ledger_path)],
            )

        return Layer3BlindEvalSummary(
            status="not_run",
            evidence_paths=[str(ab_ledger_path)],
            errors=["工作区仅有修订台账，尚未执行盲评 Judge"],
        )

    return Layer3BlindEvalSummary(status="not_run")


def _extract_layer4_evidence(output_dir: Optional[Path]) -> Layer4PassAuditSummary:
    """第 4 层 PASS Audit：从 pass_audit_report.json 提取真实数据."""
    if output_dir is None:
        return Layer4PassAuditSummary(status="not_run")

    audit_path = output_dir / "pass_audit_report.json"
    if not audit_path.exists():
        candidates = list(output_dir.glob("**/pass_audit_report.json"))
        if candidates:
            audit_path = candidates[0]

    if not audit_path.exists():
        return Layer4PassAuditSummary(status="not_run")

    data, err = _safe_read_json(audit_path)
    if err is not None or not isinstance(data, dict):
        return Layer4PassAuditSummary(
            status="invalid_evidence",
            evidence_paths=[str(audit_path)],
            errors=[err or "invalid pass audit report"],
        )

    total = int(data.get("total_pass_chapters_audited", 0))
    clean = int(data.get("clean_chapters_count", 0))
    clean_rate = float(data.get("clean_rate", (clean / total) if total > 0 else 0.0))
    actionable = float(data.get("actionable_miss_rate", 0.0))
    blocking = float(data.get("blocking_miss_rate", 0.0))

    return Layer4PassAuditSummary(
        status="completed" if total > 0 else "not_run",
        total_pass_chapters_audited=total,
        clean_chapters_count=clean,
        clean_rate=clean_rate,
        actionable_miss_rate=actionable,
        blocking_miss_rate=blocking,
        findings_by_type=data.get("findings_by_type", {}),
        severity_disagreements=data.get("severity_disagreements", []),
        evidence_paths=[str(audit_path)],
    )


def _extract_layer5_evidence(output_dir: Optional[Path]) -> Layer5HumanBlindEvalSummary:
    """第 5 层人类隐藏来源盲评：读取真实人类评测报告，无真人数据诚实标记 not_run."""
    if output_dir is None:
        return Layer5HumanBlindEvalSummary(status="not_run")

    human_report_path = output_dir / "human_eval_report.json"
    if not human_report_path.exists():
        candidates = list(output_dir.glob("**/human_eval_report.json"))
        if candidates:
            human_report_path = candidates[0]

    if not human_report_path.exists():
        return Layer5HumanBlindEvalSummary(status="not_run")

    data, err = _safe_read_json(human_report_path)
    if err is not None or not isinstance(data, dict):
        return Layer5HumanBlindEvalSummary(
            status="invalid_evidence",
            evidence_paths=[str(human_report_path)],
            errors=[err or "invalid human eval report"],
        )

    samples = int(data.get("samples_evaluated", 0))
    if samples <= 0:
        return Layer5HumanBlindEvalSummary(
            status="not_run",
            evidence_paths=[str(human_report_path)],
            notes="人类盲评报告中样本数为 0",
        )

    packet_id = data.get("packet_id", "")
    if not packet_id:
        return Layer5HumanBlindEvalSummary(
            status="invalid_evidence",
            evidence_paths=[str(human_report_path)],
            errors=["missing packet_id identity in human eval report"],
        )

    return Layer5HumanBlindEvalSummary(
        status="completed",
        participant_groups=data.get("participant_groups", []),
        samples_evaluated=samples,
        relative_preference=data.get("relative_preference", {}),
        continuation_willingness=data.get("continuation_willingness", {}),
        abandonment_points=data.get("abandonment_points", []),
        evidence_paths=[str(human_report_path)],
        notes="已汇聚真实外部读者盲评数据",
    )


def _extract_drift_evidence(output_dir: Optional[Path]) -> StyleDriftSummary:
    """Style Drift：从 drift_report.json 提取测量结果."""
    if output_dir is None:
        return StyleDriftSummary(status="not_run")

    drift_path = output_dir / "drift_report.json"
    if not drift_path.exists():
        candidates = list(output_dir.glob("**/drift_report.json"))
        if candidates:
            drift_path = candidates[0]

    if not drift_path.exists():
        return StyleDriftSummary(status="not_run")

    data, err = _safe_read_json(drift_path)
    if err is not None or not isinstance(data, dict):
        return StyleDriftSummary(
            status="invalid_evidence",
            evidence_paths=[str(drift_path)],
            errors=[err or "invalid drift report"],
        )

    return StyleDriftSummary(
        status="completed",
        drift_detected=bool(data.get("drift_detected", False)),
        homogenization_index=float(data.get("homogenization_index", 0.0)),
        metrics=data.get("metrics", {}),
        evidence_paths=[str(drift_path)],
    )


def build_unified_quality_report(
    novel_name: str,
    output_dir: Optional[Path] = None,
    *,
    report_id: Optional[str] = None,
    strict_evidence: bool = False,
    layer1_override: Optional[Layer1HardGatesSummary] = None,
    layer2_override: Optional[Layer2SpecializedAxesSummary] = None,
    layer3_override: Optional[Layer3BlindEvalSummary] = None,
    layer4_override: Optional[Layer4PassAuditSummary] = None,
    layer5_override: Optional[Layer5HumanBlindEvalSummary] = None,
    style_drift_override: Optional[StyleDriftSummary] = None,
) -> UnifiedQualityReport:
    """构建小说工作区的五层统一质量报告（无真实证据时严格为 not_run，禁止伪造任何正面结论）."""
    r_id = report_id or f"qr_{novel_name}_p4"

    # Layer 1: 确定性硬门禁
    layer1 = layer1_override or _extract_layer1_evidence(output_dir)

    # Layer 2: 专门轴评价
    layer2 = layer2_override or _extract_layer2_evidence(output_dir)

    # Layer 3: Blind Eval
    layer3 = layer3_override or _extract_layer3_evidence(output_dir)

    # Layer 4: PASS Audit
    layer4 = layer4_override or _extract_layer4_evidence(output_dir)

    # Layer 5: 人类隐藏来源盲评
    layer5 = layer5_override or _extract_layer5_evidence(output_dir)

    # Style Drift
    drift = style_drift_override or _extract_drift_evidence(output_dir)

    if strict_evidence:
        corrupted_layers = []
        for l_name, l_obj in (
            ("layer1", layer1),
            ("layer2", layer2),
            ("layer3", layer3),
            ("layer4", layer4),
            ("layer5", layer5),
            ("style_drift", drift),
        ):
            if getattr(l_obj, "status", None) == "invalid_evidence":
                corrupted_layers.append(f"{l_name}: {getattr(l_obj, 'errors', [])}")
        if corrupted_layers:
            raise ValueError(f"Strict evidence validation failed: {'; '.join(corrupted_layers)}")

    # 综合定性诊断（根据真实状态诚实陈述）
    summary_lines = [
        f"【{novel_name} 叙事质量全景诊断】",
        f"- 硬门禁 (Layer 1): {layer1.status.upper()} (阻断问题数: {layer1.blocking_issues_count}, 证据: {len(layer1.evidence_paths)} 文件)",
        f"- 专门轴 (Layer 2): {layer2.status.upper()} (已评轴: {len(layer2.evaluated_axes)}, unreviewable: {len(layer2.unreviewable_axes)})",
        f"- Blind Eval (Layer 3): {layer3.status.upper()} (样本对: {layer3.total_pairs_evaluated}, 净改善率: {layer3.net_improvement_rate * 100:.1f}%, Wilson CI: [{layer3.wilson_ci_95[0]:.2f}, {layer3.wilson_ci_95[1]:.2f}])",
        f"- PASS Audit (Layer 4): {layer4.status.upper()} (抽检章节: {layer4.total_pass_chapters_audited}, Clean 率: {layer4.clean_rate * 100:.1f}%)",
        f"- 人类双盲 (Layer 5): {layer5.status.upper()} ({layer5.notes})",
    ]

    if layer1.status == "passed" and layer5.status == "not_run":
        summary_lines.append("- 结论：确定性硬门禁已通过，但未接入外部人类长期双盲阅读实验数据，当前未获大神级生产授权。")
    elif layer1.status == "blocked":
        summary_lines.append("- 结论：确定性硬门禁存在阻断性问题，正文已被拦截或要求重写。")
    elif layer1.status == "not_run":
        summary_lines.append("- 结论：工作区未执行生产门禁链或无完整证据，全层评价处于 not_run 状态。")
    else:
        summary_lines.append("- 结论：状态已如实汇总，严禁输出单一加权大神总分。")

    report = UnifiedQualityReport(
        report_id=r_id,
        novel_name=novel_name,
        layer1_hard_gates=layer1,
        layer2_specialized_axes=layer2,
        layer3_blind_eval=layer3,
        layer4_pass_audit=layer4,
        layer5_human_blind_eval=layer5,
        style_drift=drift,
        g7_status=G7RetirementNotice(),
        narrative_evaluation_summary="\n".join(summary_lines),
    )

    if output_dir is not None:
        out_file = output_dir / "unified_quality_report.json"
        out_file.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_file = output_dir / "unified_quality_report.md"
        md_file.write_text(report.render_markdown(), encoding="utf-8")

    return report
