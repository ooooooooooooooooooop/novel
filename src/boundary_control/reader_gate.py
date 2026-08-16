"""ReaderQualityGatePolicy — Q1 Phase 4 提交点读者门禁策略.

消费三类输入 → 路由决策（pass / rewrite / block / manual）：
- 跨章 Reconcile issues（Phase 1 `reconcile_prose_evidence` 产出，确定性）；
- 单章 ReaderExperienceReport（操作者 `novel reader` 产，LLM，7 维）；
- 连续章 SerialReaderReport（操作者 `novel reader --window 3|5` 产，LLM，窗口）。

策略（对齐规格 45 §3.4 门禁策略）：
- 客观连续性错误 → block（跨章硬一致性 / 重复闭环第二次 / 契约禁止漂移 / 窗口客观硬错误）
- 正文层可修 → rewrite（单章读者关键维 weak——可经 prose_revise 修订）
- 主观审美分歧 → manual（明确人工决定点，不静默放行）
- 其余 → pass

零成本：无 prev_chapters → 窗口轴 unarmed；无报告 → 对应 LLM 轴 unarmed；
门禁只对「有输入」的轴作判断，且把 armed/unarmed 如实记录进 verdict（诚实报告）。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from src.object_state.readercontract import ReaderContract
from src.object_state.readerreport import ReaderExperienceReport
from src.object_state.reviewissue import ReviewIssue
from src.object_state.serialreader import SerialReaderReport
from src.workflow_action.prose_evidence import extract_prose_evidence
from src.workflow_action.prose_reconcile import (
    _conclusion_core,
    build_trusted_snapshot,
    conclusion_sentences,
    reconcile_prose_evidence,
)

# 单章报告的关键读者维度（weak 不得提交，可经 prose revise 修订）
KEY_READER_DIMENSIONS = frozenset({"hook", "payoff", "presence", "emotion"})

# 窗口报告 objective 维（客观硬错误 → block）
OBJECTIVE_SERIAL_DIMENSIONS = frozenset(
    {"process_text", "reset_without_event", "scene_replay", "mechanical_recap"}
)
# 窗口报告 aesthetic 维（主观审美 → manual 人工决定点）
# repeated_insight 由确定性「重复闭环第二次」覆盖；contract_drift 由确定性契约漂移覆盖，
# 故不在此列（LLM 若报这两维，仍按 objective 处理）。
AESTHETIC_SERIAL_DIMENSIONS = frozenset(
    {
        "repeated_ending",
        "narrowing_methods",
        "pleasure_dilution",
        "expectation_stall",
        "psych_summary_only",
    }
)


@dataclass
class ReaderGateVerdict:
    """门禁决策：route + 关联 issue + 人工可读原因 + 各轴武装状态."""

    route: Literal["pass", "rewrite", "block", "manual"]
    issues: list[ReviewIssue] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    axes_armed: dict[str, bool] = field(default_factory=dict)


def _repeated_loop_second_issues(
    draft_text: str, prev_chapters: list[str], chapter_ref: str
) -> list[ReviewIssue]:
    """重复闭环第二次即阻断：draft 顿悟核心 == 上一章顿悟核心（连续第 2 次）.

    比 reconcile f07（窗口内 ≥3 次）更严：同一顿悟核心在**紧邻上一章**重复出现
    即视为重新完成同一闭环，阻断。
    """
    if not prev_chapters:
        return []
    draft_cores = {_conclusion_core(c) for c in conclusion_sentences(draft_text)}
    if not draft_cores:
        return []
    prev_cores = {
        _conclusion_core(c) for c in conclusion_sentences(prev_chapters[-1])
    }
    if not prev_cores:
        return []
    overlap = sorted(draft_cores & prev_cores)
    if not overlap:
        return []
    return [
        ReviewIssue(
            issue_id="iss_q4_repeat_loop_2nd",
            issue_type="redundancy",
            severity="blocking",
            location=f"{chapter_ref} 中段",
            scope_of_impact="跨章进展感知/顿悟闭环",
            violated_rule="同一顿悟闭环不得连续两章重复完成（第二次即阻断）",
            description=(
                f"本章顿悟核心『{overlap[0][:24]}…』与上一章完全相同——"
                f"同一闭环连续第二次被重新完成，读者感到原地踏步"
            ),
            suggested_fix="保留一次，其余改为行为/后果落地，或让角色真正行动",
        )
    ]


def _contract_drift_issues(
    draft_text: str, contract: Optional[ReaderContract], chapter_ref: str
) -> list[ReviewIssue]:
    """正文层契约漂移：draft 含 ReaderContract.forbidden_drifts 任一项子串 → block.

    Selector 在候选期已用 contract_violations 阻断 PlotUnit；本闸在提交点
    对**正文**做最终确认（写作意图 ≠ 正文最终事实）。
    """
    if contract is None or not contract.forbidden_drifts:
        return []
    hits = [d for d in contract.forbidden_drifts if d and d in draft_text]
    if not hits:
        return []
    return [
        ReviewIssue(
            issue_id="iss_q4_contract_drift",
            issue_type="weak_progression",
            severity="blocking",
            location=f"{chapter_ref} 全章",
            scope_of_impact="读者契约一致性",
            violated_rule="正文不得出现读者契约 forbidden_drifts",
            description=(
                f"正文命中读者契约禁止漂移: {hits}——读者选择这本书的契约被破坏"
            ),
            suggested_fix="改写命中片段，回到契约声明的核心阅读机制",
        )
    ]


def _key_reader_dim_weak_issues(
    report: Optional[ReaderExperienceReport], chapter_ref: str
) -> tuple[list[ReviewIssue], list[str]]:
    """单章报告关键维 weak → 不得提交（正文层可修 → rewrite）."""
    if report is None:
        return [], []
    weak_dims = [
        d for d in report.dimensions
        if d.dimension in KEY_READER_DIMENSIONS and d.grade == "weak"
    ]
    if not weak_dims:
        return [], []
    issues = [
        ReviewIssue(
            issue_id=f"iss_q4_reader_{d.dimension}",
            issue_type="weak_progression",
            severity="warning",  # 正文层可修 → rewrite（非客观阻断）
            location=f"{chapter_ref} {d.anchor or '全章'}",
            scope_of_impact="读者体验关键维",
            violated_rule="关键读者维度（hook/payoff/presence/emotion）weak 不得提交",
            description=f"单章读者审查 {d.dimension}({d.name}) 为 weak: {d.diagnosis}",
            suggested_fix=d.fix_direction or "按 7 维诊断做正文层修订后复核",
        )
        for d in weak_dims
    ]
    return issues, [f"单章读者关键维 weak: {', '.join(d.dimension for d in weak_dims)}"]


def _serial_finding_issues(
    report: Optional[SerialReaderReport],
    chapter_ref: str,
) -> tuple[list[ReviewIssue], list[ReviewIssue], list[str]]:
    """窗口报告 → (objective issues, aesthetic issues, reasons).

    objective 维 → block；aesthetic 维 → manual（人工决定点）。
    repeated_insight 若被 LLM 报（objective），并入 objective（确定性已兜底）。
    contract_drift 若被 LLM 报，并入 objective（确定性契约漂移已兜底）。
    """
    if report is None:
        return [], [], []
    objective: list[ReviewIssue] = []
    aesthetic: list[ReviewIssue] = []
    for f in report.findings:
        is_aesthetic = (
            f.dimension in AESTHETIC_SERIAL_DIMENSIONS and f.severity == "aesthetic"
        )
        issue = ReviewIssue(
            issue_id=f"iss_q4_ser_{f.finding_id}",
            issue_type=f.issue_type,
            severity="warning" if is_aesthetic else "blocking",
            location=f"{chapter_ref} {f.location}".strip(),
            scope_of_impact="连续阅读体验",
            violated_rule={
                "process_text": "生成/编辑过程文字不得进入正文",
                "reset_without_event": "状态不得无事件重置",
                "scene_replay": "已完成场景不得重演",
                "mechanical_recap": "开头不得机械复述上一章结尾",
            }.get(f.dimension, "连续阅读窗口出现客观连续性错误"),
            description=f"连续阅读审查 {f.dimension}: {f.diagnosis}（证据: {f.evidence}）",
            suggested_fix=f.fix_direction or "按窗口诊断修订连续阅读问题",
        )
        if f.dimension in AESTHETIC_SERIAL_DIMENSIONS and f.severity == "aesthetic":
            aesthetic.append(issue)
        else:
            objective.append(issue)
    reasons = []
    if objective:
        reasons.append(
            f"连续阅读窗口客观硬错误 {len(objective)} 项"
        )
    if aesthetic:
        reasons.append(
            f"连续阅读窗口审美分歧 {len(aesthetic)} 项 → 需人工决定"
        )
    return objective, aesthetic, reasons


class ReaderQualityGatePolicy:
    """提交点读者门禁策略：输入 → 路由决策（确定性，零 LLM）."""

    def evaluate(
        self,
        *,
        draft_text: str,
        reconcile_issues: Optional[list[ReviewIssue]] = None,
        prev_chapters: Optional[list[str]] = None,
        reader_report: Optional[ReaderExperienceReport] = None,
        serial_report: Optional[SerialReaderReport] = None,
        reader_contract: Optional[ReaderContract] = None,
        chapter_ref: str = "",
    ) -> ReaderGateVerdict:
        reconcile_issues = reconcile_issues or []
        prev_chapters = prev_chapters or []

        axes_armed = {
            "hard_consistency": True,  # 单章 reconcile 恒跑（时间/元文本/纯氛围等）
            "window": bool(prev_chapters),  # 有前章才查窗口维度
            "single_reader": reader_report is not None,
            "serial_reader": serial_report is not None,
            "contract": reader_contract is not None,
        }

        issues: list[ReviewIssue] = []
        reasons: list[str] = []

        # a) 跨章硬一致性与因果防线（硬一致性阻断 + 质量缺陷预警）
        blocking_reconcile = [i for i in reconcile_issues if i.is_blocking()]
        warning_reconcile = [i for i in reconcile_issues if not i.is_blocking()]
        if blocking_reconcile:
            issues.extend(blocking_reconcile)
            reasons.append(
                f"跨章硬一致性阻断 {len(blocking_reconcile)} 项"
            )
        if warning_reconcile:
            issues.extend(warning_reconcile)
            reasons.append(
                f"跨章/因果质量缺陷预警 {len(warning_reconcile)} 项 → 需修订"
            )

        # b) 重复闭环第二次即阻断（确定性，比 f07 更严）
        loop_issues = _repeated_loop_second_issues(draft_text, prev_chapters, chapter_ref)
        if loop_issues:
            issues.extend(loop_issues)
            reasons.append("重复闭环第二次出现（与上一章同一顿悟核心）")

        # c) 契约漂移（正文层子串，确定性）
        drift_issues = _contract_drift_issues(draft_text, reader_contract, chapter_ref)
        if drift_issues:
            issues.extend(drift_issues)
            reasons.append("正文命中读者契约禁止漂移")

        # d) 单章读者关键维 weak（报告武装；正文层可修 → rewrite）
        key_weak, key_reasons = _key_reader_dim_weak_issues(reader_report, chapter_ref)
        issues.extend(key_weak)
        reasons.extend(key_reasons)

        # e) 窗口报告（报告武装；objective → block，aesthetic → manual）
        ser_objective, ser_aesthetic, ser_reasons = _serial_finding_issues(
            serial_report, chapter_ref
        )
        issues.extend(ser_objective)
        issues.extend(ser_aesthetic)
        reasons.extend(ser_reasons)

        # 路由解析：block > manual > rewrite > pass (硬冲突 -> block，质量缺陷 -> rewrite，禁止直接 pass)
        blocking = [i for i in issues if i.is_blocking()]
        warnings = [i for i in issues if i.severity == "warning"]
        if blocking:
            route = "block"
        elif ser_aesthetic:
            route = "manual"  # 主观审美分歧 → 明确人工决定点
        elif key_weak or warnings:
            route = "rewrite"  # 正文层可修 / 质量缺陷
        else:
            route = "pass"

        return ReaderGateVerdict(
            route=route,
            issues=issues,
            reasons=reasons,
            axes_armed=axes_armed,
        )


# --------------------------------------------------------------------------
# flow v3 提交点门禁链（extract → reconcile → policy）
# --------------------------------------------------------------------------


def _chapter_num(path: Path) -> int:
    try:
        return int(path.stem[len("chapter_"):])
    except (ValueError, IndexError):
        return 1 << 30


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return ""


def load_recent_chapters(chapters_dir: Path, n: int) -> list[str]:
    """取最近 n 个已提交章节正文（从旧到新）；目录不存在/为空返回 []."""
    if not chapters_dir.exists():
        return []
    files = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    return [_read_text(p) for p in files[-n:]]


def _labels_from_characters(characters: list) -> dict[str, list[str]]:
    """从 CharacterModel 列表推导实体注册表 {id: [name, id]}; 空列表返回 {}."""
    labels: dict[str, list[str]] = {}
    for cm in characters or []:
        cid = getattr(cm, "character_id", None)
        name = getattr(cm, "name", None)
        if cid:
            labels[cid] = [label for label in (name, cid) if label]
    return labels


def _report_matches_chapter(report, chapter_ref: str) -> bool:
    """报告是否对应当前章（避免用别的章的旧报告误武装门禁）."""
    if chapter_ref:
        target = getattr(report, "chapter_id", None) or getattr(
            report, "review_target", None
        )
        if target:
            return str(target) == chapter_ref
    # 无 chapter_ref 或报告无标识 → 保守按不匹配处理（unarmed）
    return False


def _serial_report_matches_chapter(report: SerialReaderReport, chapter_ref: str) -> bool:
    """serial 报告窗口是否以当前章结尾."""
    if not chapter_ref:
        return False
    refs = getattr(report, "chapter_refs", None) or []
    return bool(refs) and refs[-1] == chapter_ref


def load_reader_reports(
    reader_experience_dir: Path,
    chapter_ref: str,
) -> tuple[Optional[ReaderExperienceReport], Optional[SerialReaderReport]]:
    """加载单章/窗口读者报告（仅当报告对应当前章才武装）.

    报告在 novels/<name>/output/reader_experience/（与 flow 的 output/<mode> 分目录）。
    不存在或不对应当前章 → None（对应轴 unarmed）。
    """
    reader_report: Optional[ReaderExperienceReport] = None
    serial_report: Optional[SerialReaderReport] = None
    if reader_experience_dir.exists():
        rp = reader_experience_dir / "reader_report.json"
        if rp.exists():
            try:
                report = ReaderExperienceReport.model_validate_json(
                    rp.read_text(encoding="utf-8")
                )
                if _report_matches_chapter(report, chapter_ref):
                    reader_report = report
            except Exception:
                reader_report = None
        sp = reader_experience_dir / "serial_reader_report.json"
        if sp.exists():
            try:
                report = SerialReaderReport.model_validate_json(
                    sp.read_text(encoding="utf-8")
                )
                if _serial_report_matches_chapter(report, chapter_ref):
                    serial_report = report
            except Exception:
                serial_report = None
    return reader_report, serial_report


def evaluate_commit_reader_gate(
    *,
    output_dir: Path,
    chapters_dir: Path,
    draft_text: str,
    facts=None,
    characters: Optional[list] = None,
    time_book=None,
    reader_contract: Optional[ReaderContract] = None,
    chapter_ref: str = "",
    causal_objects: Optional[list] = None,
) -> tuple[ReaderGateVerdict, Optional[object], list[ReviewIssue]]:
    """提交点门禁链：ProseEvidence 提取 → 跨章 Reconcile → 长程因果防线 → 门禁策略.

    返回 (verdict, package, reconcile_issues)。flow v3 在 Review PASS 后、
    事务提交前调用；block/manual → 拒绝提交（不写 chapters/、不推进 Frame）。
    零成本：报告缺失/不对应当前章 → 对应轴 unarmed；首章无前章 → 窗口轴 unarmed。

    causal_objects：可选对象列表（含 FactLedger/CharacterModel/WorldModel/
    PlotUnit/NarrativeState）。非空时运行长程因果防线（P1）——已完成事件被抹除、
    代价失效、成长重置、制度后果不传播、选择无未来差异——其 blocking issue
    并入门禁阻断；缺省 None 时因果防线不运行，行为与旧版完全一致（零成本契约）。
    """
    # 1. ProseEvidence 提取（无法断言就不核对：空 entities 跳过实体/道具类）
    labels = _labels_from_characters(characters)
    package = extract_prose_evidence(
        draft_text,
        package_id=f"pe_{chapter_ref or 'chapter'}",
        chapter_ref=chapter_ref,
        entities=labels or None,
    )

    # 2. 跨章 Reconcile（单章硬一致性 + 窗口核对）
    prev_chapters = load_recent_chapters(chapters_dir, n=4)
    trusted = build_trusted_snapshot(
        fact_ledger=facts,
        character_model=(characters[0] if characters else None),
        labels=labels or None,
        time_book=time_book,
    )
    reconcile_issues = reconcile_prose_evidence(
        draft_text,
        package,
        prev_chapters=prev_chapters or None,
        trusted=trusted,
        chapter_ref=chapter_ref,
    )

    # 2b. 长程因果防线（P1）：已提交状态 vs 新草案的对象层检测（可选）
    if causal_objects:
        from src.domain_layer.causal_defense import run_causal_defense

        causal_issues = run_causal_defense(causal_objects)
        if causal_issues:
            reconcile_issues = list(reconcile_issues) + causal_issues

    # 3. 门禁策略（加载操作者武装的读者报告）
    reader_report, serial_report = load_reader_reports(
        output_dir.parent / "reader_experience", chapter_ref
    )
    verdict = ReaderQualityGatePolicy().evaluate(
        draft_text=draft_text,
        reconcile_issues=reconcile_issues,
        prev_chapters=prev_chapters,
        reader_report=reader_report,
        serial_report=serial_report,
        reader_contract=reader_contract,
        chapter_ref=chapter_ref,
    )
    return verdict, package, reconcile_issues


def write_reader_gate_report(
    output_dir: Path,
    verdict: ReaderGateVerdict,
    *,
    chapter_ref: str = "",
    package_hash: str = "",
    reconcile_count: int = 0,
) -> Path:
    """把门禁决策落盘为 reader_gate_report.json（供人工/巡检）。"""
    payload = {
        "schema_version": 1,
        "chapter_ref": chapter_ref,
        "route": verdict.route,
        "axes_armed": dict(verdict.axes_armed),
        "reasons": verdict.reasons,
        "issues": [i.model_dump(mode="json") for i in verdict.issues],
        "reconcile_issue_count": reconcile_count,
        "facts_package_hash": package_hash,
    }
    path = output_dir / "reader_gate_report.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
