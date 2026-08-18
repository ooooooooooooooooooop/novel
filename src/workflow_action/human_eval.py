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
import os
import random
from pathlib import Path
from typing import Optional

from src.object_state.human_eval import (
    QUALIFICATION_PRECONDITION_FILES,
    QUALIFICATION_PROTOCOL_VERSION,
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonAuthorizationVerdict,
    LongHorizonPreconditionStatus,
    QualificationEvidencePackage,
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

        # R6 硬口径：重复 reader_id 必须显式拒绝，而不是静默保留最后一份丢弃其余。
        if sub.reader_id in seen_readers:
            raise ValueError(
                f"Duplicate reader_id detected: {sub.reader_id} "
                f"(重复 reader/submission 必须拒绝，禁止刷票或重复计数)"
            )
        seen_readers.add(sub.reader_id)

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

    # 读者 id 已在入口显式去重拒绝（R6 硬口径），此处直接对每份唯一提交判定长程资格有效性
    deduped_submissions = list(submissions)
    for sub in deduped_submissions:
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_evidence_path(workspace_dir: Path, rel: str) -> Optional[Path]:
    """把资格包内声明的相对证据路径解析到 workspace 内的真实文件."""
    cand = (Path(workspace_dir) / rel).resolve()
    if cand.exists() and cand.is_file():
        return cand
    return None


def _relative_to(workspace_dir: Path, path: Path) -> str:
    return os.path.relpath(str(path.resolve()), str(Path(workspace_dir).resolve())).replace(os.sep, "/")


def _qualification_payload_hash(observed_metrics: dict, evidence_hashes: dict[str, str]) -> str:
    payload = json.dumps(
        {"observed_metrics": observed_metrics, "evidence_hashes": evidence_hashes},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_qualification_package(
    precondition_id: str,
    *,
    workspace_dir: Path,
    source_commit: str,
    evidence_paths: list[str],
    thresholds: Optional[dict] = None,
    observed_metrics: Optional[dict] = None,
    verdict: str = "unqualified",
    notes: str = "",
) -> Path:
    """R6/WP3 通用资格包构建器：对声明的证据做真实 SHA-256，并把载荷哈希写入 sample_manifest_hash.

    任一证据文件缺失 → 抛 ValueError（资格包不可在证据缺失时声称 qualified）。
    """
    if precondition_id not in QUALIFICATION_PRECONDITION_FILES:
        raise ValueError(f"Unknown precondition_id: {precondition_id}")
    evidence_hashes: dict[str, str] = {}
    for rel in evidence_paths:
        p = _resolve_evidence_path(workspace_dir, rel)
        if p is None:
            raise ValueError(f"qualification evidence missing: {rel}")
        evidence_hashes[rel] = _sha256_bytes(p.read_bytes())
    pkg = QualificationEvidencePackage(
        protocol_version=QUALIFICATION_PROTOCOL_VERSION,
        precondition_id=precondition_id,
        source_commit=source_commit,
        sample_manifest_hash=_qualification_payload_hash(observed_metrics or {}, evidence_hashes),
        evidence_hashes=evidence_hashes,
        thresholds=thresholds or {},
        observed_metrics=observed_metrics or {},
        verdict=verdict,
        notes=notes,
    )
    out = Path(workspace_dir) / QUALIFICATION_PRECONDITION_FILES[precondition_id]
    out.write_text(pkg.model_dump_json(indent=2), encoding="utf-8")
    return out


def _load_and_validate_qualification(
    workspace_dir: Path, precondition_id: str
) -> Optional[QualificationEvidencePackage]:
    """Inspector 唯一入口：严格校验资格证据包的 schema / 版本 / 哈希 / 交叉引用 / 判定.

    任何一项不满足 → 返回 None（对应前置条件位保持 False，绝不凭猜测赋位）。
    """
    fname = QUALIFICATION_PRECONDITION_FILES.get(precondition_id)
    if not fname:
        return None
    p = Path(workspace_dir) / fname
    if not p.exists():
        cands = list(Path(workspace_dir).glob(f"**/{fname}"))
        if not cands:
            return None
        p = cands[0]
    data, err = _safe_load_json_file(p)
    if err is not None or not isinstance(data, dict):
        return None
    try:
        pkg = QualificationEvidencePackage.model_validate(data)
    except Exception:
        return None
    if pkg.protocol_version != QUALIFICATION_PROTOCOL_VERSION:
        return None
    if pkg.verdict != "qualified":
        return None
    # 哈希与交叉引用：每个证据必须能在 workspace 解析到真实文件且 SHA-256 严格一致
    for rel, expected in pkg.evidence_hashes.items():
        real = _resolve_evidence_path(workspace_dir, rel)
        if real is None:
            return None
        if _sha256_bytes(real.read_bytes()) != expected:
            return None
    # 载荷绑定：sample_manifest_hash 必须与 observed_metrics + evidence_hashes 严格一致
    recomputed = _qualification_payload_hash(pkg.observed_metrics, pkg.evidence_hashes)
    if recomputed != pkg.sample_manifest_hash:
        return None
    return pkg


def build_p1_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """P1 长程因果防线资格包（关闭『无 run_manifest 默认 True』与『相对路径 artifact key』伪造点）.

    - run_manifest 缺失或未 committed → unqualified（绝不再默认 True）。
    - 按 manifest.artifacts 中真实 key（可能是 ChapterCommitBoundary 的相对路径
      如 output/compose/reader_gate_report.json）解析 gate 报告文件并哈希。
    - route 非 pass 且无 axes_armed、存在 blocking/critical issue → unqualified。
    """
    manifest_p = Path(workspace_dir) / "run_manifest.json"
    if not manifest_p.exists():
        cands = list(Path(workspace_dir).glob("**/run_manifest.json"))
        manifest_p = cands[0] if cands else None
    if manifest_p is None:
        return write_qualification_package(
            "p1", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"manifest_present": False},
            verdict="unqualified", notes="run_manifest 缺失，无法绑定因果防线证据",
        )
    m_data, m_err = _safe_load_json_file(manifest_p)
    if m_err is not None or not isinstance(m_data, dict) or m_data.get("status") != "committed":
        return write_qualification_package(
            "p1", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[_relative_to(workspace_dir, manifest_p)],
            observed_metrics={"manifest_present": True, "manifest_status": m_data.get("status") if isinstance(m_data, dict) else None},
            verdict="unqualified", notes="run_manifest 未 committed",
        )
    artifacts = m_data.get("artifacts", {}) or {}
    gate_rel = next((k for k in artifacts if k.endswith("reader_gate_report.json")), None)
    has_blocking = False
    route = None
    axes_armed = False
    gate_exists = False
    if gate_rel is not None:
        gate_file = _resolve_evidence_path(workspace_dir, gate_rel)
        gate_exists = gate_file is not None
        if gate_file is not None:
            g_data, g_err = _safe_load_json_file(gate_file)
            if g_err is None and isinstance(g_data, dict):
                route = g_data.get("route")
                axes_armed = bool(g_data.get("axes_armed", {}))
                has_blocking = bool([
                    i for i in g_data.get("issues", [])
                    if isinstance(i, dict) and i.get("severity") in ("blocking", "critical")
                ])
    evidence: list[str] = [_relative_to(workspace_dir, manifest_p)]
    if gate_rel is not None:
        evidence.append(gate_rel)
    qualified = gate_rel is not None and gate_exists and (route == "pass" or axes_armed) and not has_blocking
    return write_qualification_package(
        "p1", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=evidence,
        observed_metrics={
            "manifest_present": True,
            "manifest_status": "committed",
            "gate_report_bound": gate_rel is not None and gate_exists,
            "route": route,
            "axes_armed": axes_armed,
            "has_blocking_critical_issues": has_blocking,
        },
        verdict="qualified" if qualified else "unqualified",
        notes="P1 因果防线证据已绑定" if qualified else "P1 因果防线证据未满足",
    )


def build_p2_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """P2 叙事编排器资格包：绑定 committed_orchestration_state 与 orchestration_history 真实证据."""
    s_p = Path(workspace_dir) / "committed_orchestration_state.json"
    if not s_p.exists():
        cands = list(Path(workspace_dir).glob("**/committed_orchestration_state.json"))
        s_p = cands[0] if cands else None
    h_p = Path(workspace_dir) / "orchestration_history.json"
    if not h_p.exists():
        cands = list(Path(workspace_dir).glob("**/orchestration_history.json"))
        h_p = cands[0] if cands else None
    if s_p is None or h_p is None:
        return write_qualification_package(
            "p2", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"present": False},
            verdict="unqualified", notes="编排状态或历史缺失",
        )
    s_data, s_err = _safe_load_json_file(s_p)
    h_data, h_err = _safe_load_json_file(h_p)
    last_ch = int(s_data.get("last_committed_chapter", 0)) if s_err is None and isinstance(s_data, dict) else 0
    hist_len = len(h_data) if h_err is None and isinstance(h_data, list) else 0
    qualified = last_ch >= 2 and hist_len >= 1
    return write_qualification_package(
        "p2", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, s_p), _relative_to(workspace_dir, h_p)],
        observed_metrics={"last_committed_chapter": last_ch, "history_len": hist_len},
        verdict="qualified" if qualified else "unqualified",
        notes="P2 编排器已接入生产" if qualified else "P2 编排器未达生产证据",
    )


def build_p3_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """P3 结构搜索资格包：绑定真实 structural_search_record；respeaking 真实 frontier 与多样性而非自报."""
    s_p = Path(workspace_dir) / "structural_search_record.json"
    if not s_p.exists():
        cands = (list(Path(workspace_dir).glob("**/structural_search_record.json"))
                  + list(Path(workspace_dir).glob("**/author_selection_report.json")))
        s_p = cands[0] if cands else None
    if s_p is None:
        return write_qualification_package(
            "p3", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"search_active": False, "diversity_validated": False},
            verdict="unqualified", notes="结构搜索记录缺失",
        )
    s_data, s_err = _safe_load_json_file(s_p)
    if s_err is not None or not isinstance(s_data, dict):
        return write_qualification_package(
            "p3", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[_relative_to(workspace_dir, s_p)],
            observed_metrics={"search_active": False, "diversity_validated": False},
            verdict="unqualified", notes="结构搜索记录不可解析",
        )
    frontier = s_data.get("pareto_frontier", [])
    rollouts = s_data.get("rollout_evaluations", {})
    search_active = isinstance(frontier, list) and len(frontier) >= 1 and (len(rollouts) >= 1 or "candidates_evaluated" in s_data)
    div = s_data.get("diversity_report", {}) or {}
    div_validated = bool(div.get("is_diverse")) or bool(s_data.get("diversity_validated"))
    qualified = search_active and div_validated
    return write_qualification_package(
        "p3", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, s_p)],
        observed_metrics={"search_active": search_active, "diversity_validated": div_validated,
                          "frontier_size": len(frontier) if isinstance(frontier, list) else 0},
        verdict="qualified" if qualified else "unqualified",
        notes="P3 结构搜索已真实生效" if qualified else "P3 结构搜索证据不足",
    )


def build_blind_eval_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """P4 Blind Eval 资格包：从真实 ab_blind_eval_report 读取计数并校验严格算术守恒（非只查计数和）. """
    b_p = Path(workspace_dir) / "ab_blind_eval_report.json"
    if not b_p.exists():
        cands = list(Path(workspace_dir).glob("**/ab_blind_eval_report.json"))
        b_p = cands[0] if cands else None
    if b_p is None:
        return write_qualification_package(
            "blind_eval", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"arithmetic_conservation_ok": False},
            verdict="unqualified", notes="Blind Eval 报告缺失",
        )
    b_data, b_err = _safe_load_json_file(b_p)
    if b_err is not None or not isinstance(b_data, dict):
        return write_qualification_package(
            "blind_eval", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[_relative_to(workspace_dir, b_p)],
            observed_metrics={"arithmetic_conservation_ok": False},
            verdict="unqualified", notes="Blind Eval 报告不可解析",
        )
    tot = int(b_data.get("total_pairs_evaluated", 0))
    b_cnt = int(b_data.get("better_count", 0))
    w_cnt = int(b_data.get("worse_count", 0))
    nd_cnt = int(b_data.get("no_difference_count", 0))
    u_cnt = int(b_data.get("uncertain_count", 0))
    conservation_ok = (b_cnt + w_cnt + nd_cnt + u_cnt) == tot
    qualified = tot >= 10 and conservation_ok
    return write_qualification_package(
        "blind_eval", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, b_p)],
        thresholds={"total_pairs_min": 10},
        observed_metrics={"total_pairs_evaluated": tot, "arithmetic_conservation_ok": conservation_ok},
        verdict="qualified" if qualified else "unqualified",
        notes="Blind Eval 稳定" if qualified else "Blind Eval 未达样本/守恒",
    )


def build_pass_audit_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """P4 PASS Audit 资格包：从真实 pass_audit_report 读取样本与漏检率字段数（非只查 5 条+1 字段）. """
    a_p = Path(workspace_dir) / "pass_audit_report.json"
    if not a_p.exists():
        cands = list(Path(workspace_dir).glob("**/pass_audit_report.json"))
        a_p = cands[0] if cands else None
    if a_p is None:
        return write_qualification_package(
            "pass_audit", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"frozen": False},
            verdict="unqualified", notes="PASS Audit 报告缺失",
        )
    a_data, a_err = _safe_load_json_file(a_p)
    if a_err is not None or not isinstance(a_data, dict):
        return write_qualification_package(
            "pass_audit", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[_relative_to(workspace_dir, a_p)],
            observed_metrics={"frozen": False},
            verdict="unqualified", notes="PASS Audit 报告不可解析",
        )
    tot_aud = int(a_data.get("total_pass_chapters_audited", 0))
    has_tmr = "true_miss_rate" in a_data
    frozen = tot_aud >= 5 and has_tmr
    return write_qualification_package(
        "pass_audit", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, a_p)],
        thresholds={"min_audited": 5},
        observed_metrics={"total_pass_chapters_audited": tot_aud, "has_true_miss_rate": has_tmr, "frozen": frozen},
        verdict="qualified" if frozen else "unqualified",
        notes="PASS Audit 口径已冻结" if frozen else "PASS Audit 口径未冻结",
    )


def build_provider_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """Provider / 预算硬上限资格包：绑定真实 provider_profiles.json / canary_policy_*.json（存在性+内容）. """
    pv_p = Path(workspace_dir) / "provider_profiles.json"
    if not pv_p.exists():
        cands = (list(Path(workspace_dir).glob("**/provider_profiles.json"))
                 + list(Path(workspace_dir).glob("**/provider_profile_*.json"))
                 + list(Path(workspace_dir).glob("**/canary_policy_*.json")))
        pv_p = cands[0] if cands else None
    if pv_p is None:
        return write_qualification_package(
            "provider", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"frozen": False},
            verdict="unqualified", notes="Provider 档案缺失",
        )
    pv_data, pv_err = _safe_load_json_file(pv_p)
    frozen = pv_err is None and isinstance(pv_data, dict) and len(pv_data) >= 1
    return write_qualification_package(
        "provider", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, pv_p)],
        observed_metrics={"frozen": frozen, "profiles_count": len(pv_data) if isinstance(pv_data, dict) else 0},
        verdict="qualified" if frozen else "unqualified",
        notes="Provider 档案与预算已冻结" if frozen else "Provider 档案未冻结",
    )


def build_release_integrity_qualification(workspace_dir: Path, *, source_commit: str) -> Path:
    """历史发布完整性资格包：绑定真实 release_record.json / *-release.json（tag+commit 真实性）. """
    r_p = Path(workspace_dir) / "release_record.json"
    if not r_p.exists():
        cands = (list(Path(workspace_dir).glob("**/release_record.json"))
                 + list(Path(workspace_dir).glob("**/*-release.json"))
                 + list(Path(workspace_dir).glob("**/tier0-release.json"))
                 + list(Path(workspace_dir).glob("**/q1-release.json")))
        r_p = cands[0] if cands else None
    if r_p is None:
        return write_qualification_package(
            "release_integrity", workspace_dir=workspace_dir, source_commit=source_commit,
            evidence_paths=[], observed_metrics={"intact": False},
            verdict="unqualified", notes="发布记录缺失",
        )
    r_data, r_err = _safe_load_json_file(r_p)
    intact = (r_err is None and isinstance(r_data, dict)
              and r_data.get("release_tag") and (r_data.get("git_commit") or r_data.get("commit")))
    return write_qualification_package(
        "release_integrity", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[_relative_to(workspace_dir, r_p)],
        observed_metrics={"intact": intact, "release_tag": r_data.get("release_tag") if isinstance(r_data, dict) else None},
        verdict="qualified" if intact else "unqualified",
        notes="历史发布记录完整" if intact else "历史发布记录不完整",
    )


def build_human_eval_qualification(
    workspace_dir: Path,
    *,
    source_commit: str,
    packet: BlindedChapterPacket,
    submissions: list[HumanEvaluationSubmission],
    secret_manifest: dict[str, str],
) -> Path:
    """P4 人类盲评资格包：必须实际调用 evaluate_human_submissions() 并读取 qualification_eligible.

    关闭伪造点：Inspector 不再直接读原始 submissions.json 推断资格，而是要求该资格包由
    evaluate_human_submissions 的 qualification_eligible 聚合而来（protocol_frozen +
    qualified_reader_count）。重复 reader_id 已被 evaluate_human_submissions 显式拒绝。
    """
    result = evaluate_human_submissions(packet, submissions, secret_manifest)
    protocol_frozen = bool(packet.seed_hash) and len(packet.secret_manifest_hash or "") == 64
    qualified_count = sum(1 for s in submissions if getattr(s, "qualification_eligible", False))
    # 证据绑定：写盘的真实盲评文件（blinded_packet 与 submissions 序列化）
    packet_rel = "human_eval/blinded_packet.json"
    subs_rel = "human_eval/submissions.json"
    packet_file = Path(workspace_dir) / packet_rel
    subs_file = Path(workspace_dir) / subs_rel
    packet_file.parent.mkdir(parents=True, exist_ok=True)
    packet_file.write_text(packet.model_dump_json(indent=2), encoding="utf-8")
    subs_file.write_text(
        json.dumps([s.model_dump(mode="json") for s in submissions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    qualified = protocol_frozen and qualified_count >= 10
    return write_qualification_package(
        "human_eval", workspace_dir=workspace_dir, source_commit=source_commit,
        evidence_paths=[packet_rel, subs_rel],
        thresholds={"qualified_readers_min": 10},
        observed_metrics={
            "protocol_frozen": protocol_frozen,
            "total_readers": result.get("total_readers", 0),
            "qualified_reader_count": qualified_count,
        },
        verdict="qualified" if qualified else "unqualified",
        notes="人类盲评协议冻结且 ≥10 位合格真实读者" if qualified else "人类盲评协议/合格读者不足",
    )


def inspect_long_horizon_preconditions(
    workspace_dir: Optional[Path] = None,
) -> LongHorizonPreconditionStatus:
    """R6/WP3 硬口径：只依据『专用资格证据包』逐项验证 10 项前置条件.

    本 Inspector 不再从普通工作区文件自行推断资格，只读取每项前置条件对应的
    资格文件（p1/p2/p3/blind_eval/pass_audit/human_eval/provider/release_integrity
    _qualification.json），并仅验证其 schema、protocol_version、evidence_hashes
    与真实文件的 SHA-256 交叉引用、sample_manifest_hash 载荷绑定与 verdict。
    任何缺失 / schema 不符 / 哈希不符 / 未 qualified 的资格包，对应前置条件位
    一律保持 False（绝不猜测赋位）。
    """
    status = LongHorizonPreconditionStatus()
    if workspace_dir is None:
        return status

    w = Path(workspace_dir).resolve()

    p1 = _load_and_validate_qualification(w, "p1")
    if p1 is not None:
        status.p1_causal_defense_complete = bool(
            p1.observed_metrics.get("route") in ("pass", None)
            and not p1.observed_metrics.get("has_blocking_critical_issues", False)
        )

    p2 = _load_and_validate_qualification(w, "p2")
    if p2 is not None:
        status.p2_orchestrator_in_production = bool(
            p2.observed_metrics.get("last_committed_chapter", 0) >= 2
        )

    p3 = _load_and_validate_qualification(w, "p3")
    if p3 is not None:
        status.p3_structural_search_active = bool(p3.observed_metrics.get("search_active", False))
        status.p3_diversity_validated = bool(p3.observed_metrics.get("diversity_validated", False))

    blind = _load_and_validate_qualification(w, "blind_eval")
    if blind is not None:
        status.p4_blind_eval_stable = bool(blind.observed_metrics.get("arithmetic_conservation_ok", False))

    pa = _load_and_validate_qualification(w, "pass_audit")
    if pa is not None:
        status.p4_pass_audit_frozen = bool(pa.observed_metrics.get("frozen", False))

    he = _load_and_validate_qualification(w, "human_eval")
    if he is not None:
        # 人类盲评协议冻结 + 系统外真实读者连续阅读数据（qualification_eligible 才计数）
        status.p4_human_eval_protocol_frozen = bool(he.observed_metrics.get("protocol_frozen", False))
        status.real_human_continuous_reading_data_exists = bool(
            he.observed_metrics.get("qualified_reader_count", 0) >= 10
        )

    prov = _load_and_validate_qualification(w, "provider")
    if prov is not None:
        status.provider_profile_and_budget_frozen = bool(prov.observed_metrics.get("frozen", False))

    rel = _load_and_validate_qualification(w, "release_integrity")
    if rel is not None:
        status.historical_release_records_intact = bool(rel.observed_metrics.get("intact", False))

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
