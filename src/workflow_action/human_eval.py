"""独立人类双盲评估工具包与长程生产授权裁决器 (P7).

实现：
1. build_blinded_human_eval_packet: 生成双盲材料包，随机代号隐藏来源，锁定 manifest 哈希。
2. evaluate_human_submissions: 聚合真实读者提交，计算偏好率、追读率与弃读位置。
3. evaluate_long_horizon_authorization: 评估 10 项硬性前置条件并输出 long_run_authorized / long_run_not_authorized 裁决。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from src.object_state.human_eval import (
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonAuthorizationVerdict,
    LongHorizonPreconditionStatus,
)


def build_blinded_human_eval_packet(
    novel_name: str,
    version_chapters: dict[str, list[dict]],
    chapter_range: str = "1-10",
    output_dir: Optional[Path] = None,
) -> tuple[BlindedChapterPacket, dict[str, str]]:
    """组装隐藏来源双盲评测包，混排版本并锁定真实映射."""
    raw_keys = sorted(version_chapters.keys())
    # 确定性但匿名化的盲测代号映射（cand_alpha, cand_beta, cand_gamma 等）
    blind_labels = ["cand_alpha", "cand_beta", "cand_gamma", "cand_delta"]
    secret_manifest: dict[str, str] = {}
    blinded_data: dict[str, list[dict]] = {}

    for i, real_key in enumerate(raw_keys):
        blind_key = blind_labels[i % len(blind_labels)]
        secret_manifest[blind_key] = real_key
        # 清洗章节数据中的版本标识
        cleaned_chapters = []
        for ch in version_chapters[real_key]:
            cleaned = dict(ch)
            cleaned.pop("source_version", None)
            cleaned.pop("generator_info", None)
            cleaned_chapters.append(cleaned)
        blinded_data[blind_key] = cleaned_chapters

    manifest_json = json.dumps(secret_manifest, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

    packet = BlindedChapterPacket(
        packet_id=f"packet_{novel_name}_{chapter_range}_{manifest_hash[:8]}",
        novel_name=novel_name,
        chapter_range=chapter_range,
        blinded_versions=blinded_data,
        secret_manifest_hash=manifest_hash,
    )

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "blinded_packet.json").write_text(
            json.dumps(packet.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "secret_manifest.json").write_text(
            manifest_json, encoding="utf-8"
        )

    return packet, secret_manifest


def evaluate_human_submissions(
    packet: BlindedChapterPacket,
    submissions: list[HumanEvaluationSubmission],
    secret_manifest: dict[str, str],
) -> dict:
    """揭盲并聚合读者评价结果（偏好分布、追读意愿、弃读位置）."""
    total_submissions = len(submissions)
    if total_submissions == 0:
        return {
            "status": "no_submissions",
            "total_readers": 0,
            "preference_distribution": {},
            "continuation_rate_by_version": {},
            "abandonment_points": [],
        }

    pref_counts: dict[str, int] = {}
    continuation_counts: dict[str, int] = {}
    abandonments: list[dict] = []

    for sub in submissions:
        # 解析真实版本
        if sub.preferred_version == "no_difference":
            real_winner = "no_difference"
        else:
            real_winner = secret_manifest.get(sub.preferred_version, sub.preferred_version)

        pref_counts[real_winner] = pref_counts.get(real_winner, 0) + 1

        # 记录追读意愿
        for blind_key, real_key in secret_manifest.items():
            if sub.preferred_version in (blind_key, "no_difference") and sub.continuation_willingness:
                continuation_counts[real_key] = continuation_counts.get(real_key, 0) + 1

        if sub.abandonment_point_chapter is not None:
            abandonments.append(
                {
                    "reader_id": sub.reader_id,
                    "reader_group": sub.reader_group,
                    "preferred_version": real_winner,
                    "chapter": sub.abandonment_point_chapter,
                    "reason": sub.abandonment_reason or "未指明",
                }
            )

    pref_distribution = {k: v / total_submissions for k, v in pref_counts.items()}

    return {
        "status": "completed",
        "total_readers": total_submissions,
        "preference_distribution": pref_distribution,
        "continuation_willingness_counts": continuation_counts,
        "abandonment_points": abandonments,
    }


def evaluate_long_horizon_authorization(
    preconditions: Optional[LongHorizonPreconditionStatus] = None,
) -> LongHorizonAuthorizationVerdict:
    """评估 90 章长程全自动无人生产授权资格 (Plan §8)."""
    status = preconditions or LongHorizonPreconditionStatus()
    unmet = []

    if not status.p1_causal_defense_complete:
        unmet.append("P1 长程因果防线未完全闭环")
    if not status.p2_orchestrator_in_production:
        unmet.append("P2 叙事编排器未接入生产调用链")
    if not status.p3_structural_search_active:
        unmet.append("P3 章节级多尺度搜索未生效")
    if not status.p3_diversity_validated:
        unmet.append("P3 结构异质性门禁未验证")
    if not status.p4_blind_eval_stable:
        unmet.append("P4 Blind Eval 未稳定运行")
    if not status.p4_pass_audit_frozen:
        unmet.append("P4 PASS Audit 漏检率口径未冻结")
    if not status.p4_human_eval_protocol_frozen:
        unmet.append("P4 人类盲评协议未冻结")
    if not status.real_human_continuous_reading_data_exists:
        unmet.append("缺少系统外真实人类连续阅读实验数据（不可逾越硬红线）")
    if not status.provider_profile_and_budget_frozen:
        unmet.append("Provider 档案与预算硬上限未冻结")
    if not status.historical_release_records_intact:
        unmet.append("历史发布证据或 Tag 状态不完整")

    if not unmet:
        verdict = "long_run_authorized"
        notes = "全部 10 项前置条件（含外部真人连续阅读盲测）均已满足，长程无人生产获得授权。"
    else:
        verdict = "long_run_not_authorized"
        notes = f"尚有 {len(unmet)} 项前置条件未满足，长程无人自动生产严格未授权。"

    return LongHorizonAuthorizationVerdict(
        verdict=verdict,
        preconditions=status,
        unmet_preconditions=unmet,
        notes=notes,
    )
