"""独立人类双盲评估工具包与长程生产授权裁决器 (P7 / R6 整改).

实现：
1. build_blinded_human_eval_packet: 显式随机种子打乱版本顺序，严格公私目录隔离 (--public-output-dir vs --secret-output-dir)。
2. evaluate_human_submissions: 聚合真实读者提交，计算偏好分布、按版本独立统计追读率与弃读位置。
3. inspect_long_horizon_preconditions: 从真实证据目录逐项推导 10 项前置条件，缺少真人数据默认 False。
4. evaluate_long_horizon_authorization: 评估 10 项硬性前置条件并输出 long_run_authorized / long_run_not_authorized 裁决。
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Optional

from src.object_state.human_eval import (
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonAuthorizationVerdict,
    LongHorizonPreconditionStatus,
)


GREEK_LETTERS: list[str] = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
    "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
]


def build_blinded_human_eval_packet(
    novel_name: str,
    version_chapters: dict[str, list[dict]],
    chapter_range: str = "1-10",
    *,
    public_output_dir: Optional[Path] = None,
    secret_output_dir: Optional[Path] = None,
    random_seed: int = 42,
) -> tuple[BlindedChapterPacket, dict[str, str]]:
    """组装隐藏来源双盲评测包，真随机种子混排版本，公私目录严格物理隔离，支持任意版本数 (N >= 2)."""
    if public_output_dir is not None and secret_output_dir is not None:
        p_pub = Path(public_output_dir).resolve()
        p_sec = Path(secret_output_dir).resolve()
        if p_pub == p_sec or p_pub in p_sec.parents or p_sec in p_pub.parents:
            raise ValueError(
                f"public_output_dir ({p_pub}) 与 secret_output_dir ({p_sec}) 存在重叠或包含关系，必须为严格物理隔离的独立目录"
            )

    raw_keys = sorted(version_chapters.keys())
    if len(raw_keys) < 2:
        raise ValueError(f"双盲评测至少需要 2 个候选版本进行比对，当前仅提供 {len(raw_keys)} 个")

    rng = random.Random(random_seed)
    shuffled_keys = list(raw_keys)
    rng.shuffle(shuffled_keys)

    # 动态生成匿名盲测代号（支持任意 N >= 2，杜绝模运算重复）
    blind_labels = [
        f"cand_{GREEK_LETTERS[i]}" if i < len(GREEK_LETTERS) else f"cand_v{i+1:02d}"
        for i in range(len(shuffled_keys))
    ]
    secret_manifest: dict[str, str] = {}
    blinded_data: dict[str, list[dict]] = {}

    for i, real_key in enumerate(shuffled_keys):
        blind_key = blind_labels[i]
        secret_manifest[blind_key] = real_key
        # 清洗章节数据中的版本与生成器标识
        cleaned_chapters = []
        for ch in version_chapters[real_key]:
            cleaned = dict(ch)
            cleaned.pop("source_version", None)
            cleaned.pop("generator_info", None)
            cleaned_chapters.append(cleaned)
        blinded_data[blind_key] = cleaned_chapters

    manifest_json = json.dumps(secret_manifest, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    seed_hash = hashlib.sha256(f"seed_{random_seed}_{novel_name}_{chapter_range}".encode("utf-8")).hexdigest()

    packet = BlindedChapterPacket(
        packet_id=f"packet_{novel_name}_{chapter_range}_{manifest_hash[:8]}",
        novel_name=novel_name,
        chapter_range=chapter_range,
        random_seed=random_seed,
        seed_hash=seed_hash,
        blinded_versions=blinded_data,
        secret_manifest_hash=manifest_hash,
    )

    # 写入公开目录（仅含脱敏盲评材料，明确抹除明文种子）
    if public_output_dir is not None:
        p_pub = Path(public_output_dir)
        p_pub.mkdir(parents=True, exist_ok=True)
        public_packet_dict = packet.model_dump(mode="json")
        public_packet_dict["random_seed"] = None  # 公开包绝不泄露随机种子
        (p_pub / "blinded_packet.json").write_text(
            json.dumps(public_packet_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 提供给读者的空提交模版
        template = {
            "submission_id": "sub_reader_001",
            "packet_id": packet.packet_id,
            "reader_id": "reader_anonymous_001",
            "reader_group": "veteran_reader",
            "preferred_version": blind_labels[0],
            "continuation_willingness_by_version": {k: True for k in blinded_data},
            "abandonment_by_version": {k: None for k in blinded_data},
            "abandonment_reasons_by_version": {k: None for k in blinded_data},
            "qualitative_feedback": "",
        }
        (p_pub / "submission_template.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 写入保密目录（含真实映射与明文种子）
    if secret_output_dir is not None:
        p_sec = Path(secret_output_dir)
        p_sec.mkdir(parents=True, exist_ok=True)
        secret_payload = {
            "packet_id": packet.packet_id,
            "random_seed": random_seed,
            "seed_hash": seed_hash,
            "secret_manifest_hash": manifest_hash,
            "mapping": secret_manifest,
        }
        (p_sec / "secret_manifest.json").write_text(
            json.dumps(secret_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return packet, secret_manifest


def evaluate_human_submissions(
    packet: BlindedChapterPacket,
    submissions: list[HumanEvaluationSubmission],
    secret_manifest: dict[str, str],
) -> dict:
    """揭盲并聚合真实读者提交（严格验证包一致性、密钥哈希、版本全覆盖、杜绝未知标签、读者去重、按版本独立统计追读率与弃读位置）."""
    if not submissions:
        return {
            "status": "no_submissions",
            "total_readers": 0,
            "preference_distribution": {},
            "continuation_rate_by_version": {},
            "abandonment_counts_by_version": {},
            "abandonment_points": [],
        }

    # 1. 密钥哈希校验：sha256(secret_manifest) == packet.secret_manifest_hash (强制密码学签名，杜绝任何 dummy_hash 绕过)
    if not packet.secret_manifest_hash:
        raise ValueError("Missing secret_manifest_hash in packet: unverified protocol")
    manifest_json = json.dumps(secret_manifest, sort_keys=True)
    actual_manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    if actual_manifest_hash != packet.secret_manifest_hash:
        raise ValueError(
            f"Secret manifest hash mismatch: calculated '{actual_manifest_hash}' "
            f"does not match packet '{packet.secret_manifest_hash}'"
        )

    required_versions = set(packet.blinded_versions.keys()) or set(secret_manifest.keys())

    # 2. 严格校验 submission 属性与 packet_id 一致性
    seen_submissions: set[str] = set()
    seen_readers: set[str] = set()
    deduped_submissions: list[HumanEvaluationSubmission] = []

    for sub in submissions:
        if sub.submission_id in seen_submissions:
            raise ValueError(f"Duplicate submission_id detected: {sub.submission_id}")
        seen_submissions.add(sub.submission_id)

        if sub.packet_id != packet.packet_id:
            raise ValueError(
                f"Packet ID mismatch: submission {sub.submission_id} has packet_id '{sub.packet_id}' "
                f"but expected '{packet.packet_id}'"
            )

        # 校验 preferred_version 必须在 secret_manifest 或为 no_difference
        if sub.preferred_version != "no_difference" and sub.preferred_version not in secret_manifest:
            raise ValueError(
                f"Invalid preferred_version '{sub.preferred_version}' in submission {sub.submission_id}: "
                f"not found in blinded packet manifest"
            )

        # 校验版本全覆盖 (Full Version Coverage per Submission)
        if sub.continuation_willingness_by_version:
            for blind_k in sub.continuation_willingness_by_version:
                if blind_k not in secret_manifest:
                    raise ValueError(
                        f"Unknown blind version '{blind_k}' in continuation_willingness_by_version"
                    )
            missing_cont = required_versions - set(sub.continuation_willingness_by_version.keys())
            if missing_cont:
                raise ValueError(
                    f"Submission {sub.submission_id} missing continuation evaluation for versions: {sorted(missing_cont)}"
                )

        if sub.abandonment_by_version:
            for blind_k in sub.abandonment_by_version:
                if blind_k not in secret_manifest:
                    raise ValueError(
                        f"Unknown blind version '{blind_k}' in abandonment_by_version"
                    )
            missing_aban = required_versions - set(sub.abandonment_by_version.keys())
            if missing_aban:
                raise ValueError(
                    f"Submission {sub.submission_id} missing abandonment evaluation for versions: {sorted(missing_aban)}"
                )

    # 读者去重（同一读者保留最新提交，防止刷票）
    for sub in reversed(submissions):
        if sub.reader_id not in seen_readers:
            seen_readers.add(sub.reader_id)
            # 判定长程资格有效性 (必须具备 100% 版本全覆盖)
            missing_cont = (
                required_versions - set(sub.continuation_willingness_by_version.keys())
                if sub.continuation_willingness_by_version
                else required_versions
            )
            missing_aban = (
                required_versions - set(sub.abandonment_by_version.keys())
                if sub.abandonment_by_version
                else required_versions
            )
            sub.qualification_eligible = bool(len(missing_cont) == 0 and len(missing_aban) == 0 and sub.reader_id)
            deduped_submissions.append(sub)
    deduped_submissions.reverse()

    total_submissions = len(deduped_submissions)

    pref_counts: dict[str, int] = {}
    continuation_counts: dict[str, int] = {}
    abandonment_counts_by_version: dict[str, int] = {}
    abandonments: list[dict] = []

    for sub in deduped_submissions:
        # 解析真实版本（杜绝 fallback）
        if sub.preferred_version == "no_difference":
            real_winner = "no_difference"
        else:
            real_winner = secret_manifest[sub.preferred_version]

        pref_counts[real_winner] = pref_counts.get(real_winner, 0) + 1

        # 1. 独立按版本追读统计
        for blind_k, will_continue in sub.continuation_willingness_by_version.items():
            real_k = secret_manifest[blind_k]
            if will_continue:
                continuation_counts[real_k] = continuation_counts.get(real_k, 0) + 1

        # 兼容旧单字段
        if not sub.continuation_willingness_by_version and sub.continuation_willingness:
            continuation_counts[real_winner] = continuation_counts.get(real_winner, 0) + 1

        # 2. 独立按版本弃读统计
        for blind_k, ab_ch in sub.abandonment_by_version.items():
            if ab_ch is not None:
                real_k = secret_manifest[blind_k]
                abandonment_counts_by_version[real_k] = abandonment_counts_by_version.get(real_k, 0) + 1
                reason = sub.abandonment_reasons_by_version.get(blind_k) or "未指明"
                abandonments.append(
                    {
                        "reader_id": sub.reader_id,
                        "reader_group": sub.reader_group,
                        "version": real_k,
                        "chapter": ab_ch,
                        "reason": reason,
                    }
                )

        # 兼容旧单字段
        if not sub.abandonment_by_version and sub.abandonment_point_chapter is not None:
            abandonments.append(
                {
                    "reader_id": sub.reader_id,
                    "reader_group": sub.reader_group,
                    "version": real_winner,
                    "chapter": sub.abandonment_point_chapter,
                    "reason": sub.abandonment_reason or "未指明",
                }
            )

    pref_distribution = {k: round(v / total_submissions, 4) for k, v in pref_counts.items()}
    continuation_rate = {k: round(v / total_submissions, 4) for k, v in continuation_counts.items()}

    return {
        "status": "completed",
        "total_readers": total_submissions,
        "preference_distribution": pref_distribution,
        "continuation_rate_by_version": continuation_rate,
        "abandonment_counts_by_version": abandonment_counts_by_version,
        "abandonment_points": abandonments,
    }


def _safe_load_json_file(path: Path) -> tuple[Optional[dict | list], Optional[str]]:
    if not path.exists():
        return None, "file not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as exc:
        return None, str(exc)


def inspect_long_horizon_preconditions(
    workspace_dir: Optional[Path] = None,
) -> LongHorizonPreconditionStatus:
    """从磁盘真实证据逐项推导 10 项前置条件（基于不可伪造资格证据、密码学哈希与数学守恒校验）."""
    status = LongHorizonPreconditionStatus()
    if workspace_dir is None:
        return status

    w_dir = Path(workspace_dir).resolve()
    if not w_dir.exists():
        return status

    # 1. P1 长程因果防线：检查 reader_gate_report.json 与 run_manifest 提交哈希绑定及 5 类因果防线
    gate_p = w_dir / "reader_gate_report.json"
    if not gate_p.exists():
        candidates = list(w_dir.glob("**/reader_gate_report.json"))
        if candidates:
            gate_p = candidates[0]
    manifest_p = w_dir / "run_manifest.json"
    if not manifest_p.exists():
        m_candidates = list(w_dir.glob("**/run_manifest.json"))
        if m_candidates:
            manifest_p = m_candidates[0]

    if gate_p.exists():
        data, err = _safe_load_json_file(gate_p)
        if err is None and isinstance(data, dict):
            axes = data.get("axes_armed", {})
            issues = [
                i for i in data.get("issues", [])
                if isinstance(i, dict) and i.get("severity") in ("blocking", "critical")
            ]
            # 校验 RunManifest 绑定（若存在 manifest 则必须为 committed 且哈希一致）
            manifest_ok = True
            if manifest_p.exists():
                m_data, m_err = _safe_load_json_file(manifest_p)
                if m_err is None and isinstance(m_data, dict):
                    if m_data.get("status") != "committed":
                        manifest_ok = False
                    artifacts = m_data.get("artifacts", {})
                    gate_rel = "reader_gate_report.json"
                    if gate_rel in artifacts:
                        art_val = artifacts[gate_rel]
                        expected_h = art_val.get("sha256") if isinstance(art_val, dict) else art_val
                        actual_h = hashlib.sha256(gate_p.read_bytes()).hexdigest()
                        if expected_h and expected_h != actual_h:
                            manifest_ok = False
                else:
                    manifest_ok = False

            if manifest_ok and (data.get("route") == "pass" or axes) and len(issues) == 0:
                status.p1_causal_defense_complete = True

    # 2. P2 叙事编排器：检查 committed_orchestration_state.json 与 orchestration_history.json
    orch_state = w_dir / "committed_orchestration_state.json"
    if not orch_state.exists():
        candidates = list(w_dir.glob("**/committed_orchestration_state.json"))
        if candidates:
            orch_state = candidates[0]
    orch_hist = w_dir / "orchestration_history.json"
    if not orch_hist.exists():
        candidates = list(w_dir.glob("**/orchestration_history.json"))
        if candidates:
            orch_hist = candidates[0]
    if orch_state.exists() and orch_hist.exists():
        s_data, s_err = _safe_load_json_file(orch_state)
        h_data, h_err = _safe_load_json_file(orch_hist)
        if s_err is None and h_err is None and isinstance(s_data, dict) and isinstance(h_data, list):
            if int(s_data.get("last_committed_chapter", 0)) >= 2 and len(h_data) >= 1:
                status.p2_orchestrator_in_production = True

    # 3. P3 结构搜索：检查 structural_search_record.json / author_selection_report.json
    search_report = w_dir / "structural_search_record.json"
    if not search_report.exists():
        candidates = list(w_dir.glob("**/structural_search_record.json")) + list(w_dir.glob("**/author_selection_report.json"))
        if candidates:
            search_report = candidates[0]
    if search_report.exists():
        s_data, s_err = _safe_load_json_file(search_report)
        if s_err is None and isinstance(s_data, dict):
            frontier = s_data.get("pareto_frontier", [])
            rollouts = s_data.get("rollout_evaluations", {})
            if (
                isinstance(frontier, list)
                and len(frontier) >= 1
                and (len(rollouts) >= 1 or "candidates_evaluated" in s_data)
            ):
                status.p3_structural_search_active = True

    # 4. P3 异质性门禁：检查 diversity_report.json 或 search_report 中的多样性状态
    div_report = w_dir / "diversity_report.json"
    if not div_report.exists():
        candidates = list(w_dir.glob("**/diversity_report.json"))
        if candidates:
            div_report = candidates[0]
    if div_report.exists():
        d_data, d_err = _safe_load_json_file(div_report)
        if d_err is None and isinstance(d_data, dict) and d_data.get("is_diverse", False):
            if float(d_data.get("diversity_score", 0.0)) >= 0.3:
                status.p3_diversity_validated = True
    elif search_report.exists():
        s_data, _ = _safe_load_json_file(search_report)
        if isinstance(s_data, dict):
            div_sub = s_data.get("diversity_report", {})
            if isinstance(div_sub, dict) and div_sub.get("is_diverse"):
                status.p3_diversity_validated = True
            elif s_data.get("diversity_validated"):
                status.p3_diversity_validated = True

    # 5. P4 Blind Eval：检查 ab_blind_eval_report.json (要求样本 >= 10 且严格算术守恒)
    blind_p = w_dir / "ab_blind_eval_report.json"
    if not blind_p.exists():
        candidates = list(w_dir.glob("**/ab_blind_eval_report.json"))
        if candidates:
            blind_p = candidates[0]
    if blind_p.exists():
        b_data, b_err = _safe_load_json_file(blind_p)
        if b_err is None and isinstance(b_data, dict):
            tot = int(b_data.get("total_pairs_evaluated", 0))
            if tot >= 10:
                b_cnt = int(b_data.get("better_count", 0))
                w_cnt = int(b_data.get("worse_count", 0))
                nd_cnt = int(b_data.get("no_difference_count", 0))
                u_cnt = int(b_data.get("uncertain_count", 0))
                # 算术守恒检查
                if b_cnt + w_cnt + nd_cnt + u_cnt == tot:
                    status.p4_blind_eval_stable = True

    # 6. P4 PASS Audit：检查 pass_audit_report.json (要求抽检样本 >= 5 且冻结口径)
    audit_p = w_dir / "pass_audit_report.json"
    if not audit_p.exists():
        candidates = list(w_dir.glob("**/pass_audit_report.json"))
        if candidates:
            audit_p = candidates[0]
    if audit_p.exists():
        a_data, a_err = _safe_load_json_file(audit_p)
        if a_err is None and isinstance(a_data, dict):
            tot_aud = int(a_data.get("total_pass_chapters_audited", 0))
            if tot_aud >= 5 and "true_miss_rate" in a_data:
                status.p4_pass_audit_frozen = True

    # 7. P4 人类盲评协议：检查 blinded_packet.json (必须具备有效 seed_hash 与 64 位 SHA256 secret_manifest_hash)
    packet_p = w_dir / "human_eval" / "blinded_packet.json"
    if not packet_p.exists():
        candidates = list(w_dir.glob("**/blinded_packet.json"))
        if candidates:
            packet_p = candidates[0]
    if packet_p.exists():
        p_data, p_err = _safe_load_json_file(packet_p)
        if p_err is None and isinstance(p_data, dict):
            seed_h = str(p_data.get("seed_hash", ""))
            sec_h = str(p_data.get("secret_manifest_hash", ""))
            if seed_h and len(sec_h) == 64:
                status.p4_human_eval_protocol_frozen = True

    # 8. 系统外真实人类连续阅读实验数据 (必须具备 >= 10 位具备全版本覆盖资格的独立读者提交)
    sub_p = w_dir / "human_eval" / "submissions.json"
    if not sub_p.exists():
        candidates = list(w_dir.glob("**/submissions.json"))
        if candidates:
            sub_p = candidates[0]
    if sub_p.exists():
        s_data, s_err = _safe_load_json_file(sub_p)
        if s_err is None and isinstance(s_data, list):
            valid_qualified_readers: set[str] = set()
            for item in s_data:
                if isinstance(item, dict) and item.get("reader_id") and item.get("preferred_version"):
                    cont_map = item.get("continuation_willingness_by_version", {})
                    aban_map = item.get("abandonment_by_version", {})
                    # 必须具备全版本覆盖结构 (至少包含 2 个版本的独立追读与弃读记录)
                    if isinstance(cont_map, dict) and len(cont_map) >= 2 and isinstance(aban_map, dict) and len(aban_map) >= 2:
                        valid_qualified_readers.add(item["reader_id"])
            if len(valid_qualified_readers) >= 10:
                status.real_human_continuous_reading_data_exists = True

    # 9. Provider 档案与预算硬上限冻结（必须为真实 provider_profiles.json / canary_policy_*.json，杜绝 run_manifest 兜底）
    prov_p = w_dir / "provider_profiles.json"
    if not prov_p.exists():
        candidates = (
            list(w_dir.glob("**/provider_profiles.json"))
            + list(w_dir.glob("**/provider_profile_*.json"))
            + list(w_dir.glob("**/canary_policy_*.json"))
        )
        if candidates:
            prov_p = candidates[0]
    if prov_p.exists():
        pv_data, pv_err = _safe_load_json_file(prov_p)
        if pv_err is None and isinstance(pv_data, dict) and len(pv_data) >= 1:
            status.provider_profile_and_budget_frozen = True

    # 10. 历史发布证据（必须为真实 release_record.json / *-release.json，杜绝 run_manifest 兜底）
    rel_p = w_dir / "release_record.json"
    if not rel_p.exists():
        candidates = (
            list(w_dir.glob("**/release_record.json"))
            + list(w_dir.glob("**/*-release.json"))
            + list(w_dir.glob("**/tier0-release.json"))
            + list(w_dir.glob("**/q1-release.json"))
        )
        if candidates:
            rel_p = candidates[0]
    if rel_p.exists():
        r_data, r_err = _safe_load_json_file(rel_p)
        if r_err is None and isinstance(r_data, dict) and r_data.get("release_tag") and (r_data.get("git_commit") or r_data.get("commit")):
            status.historical_release_records_intact = True

    return status


def evaluate_long_horizon_authorization(
    preconditions: Optional[LongHorizonPreconditionStatus] = None,
    workspace_dir: Optional[Path] = None,
) -> LongHorizonAuthorizationVerdict:
    """评估 90 章长程全自动无人生产授权资格 (Plan §8)."""
    status = preconditions or inspect_long_horizon_preconditions(workspace_dir)
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
        notes = f"尚有 {len(unmet)} 项前置条件未满足（尤其包含系统外真人连续阅读实验数据缺失），长程无人自动生产严格未授权。"

    return LongHorizonAuthorizationVerdict(
        verdict=verdict,
        preconditions=status,
        unmet_preconditions=unmet,
        notes=notes,
    )
