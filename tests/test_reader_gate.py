"""Q1 Phase 4 — ReaderQualityGatePolicy 门禁策略单测.

验证提交点读者门禁：
- 确定性硬门禁（reconcile 阻断 / 重复闭环第二次 / 契约漂移）
- 报告武装门禁（单章关键维 weak → rewrite；窗口 objective → block；aesthetic → manual）
- 零成本（无前章/无报告 → 对应轴 unarmed 不阻断）
- flow 级门禁链（extract → reconcile → policy）集成
"""

import pytest
from pathlib import Path

from src.boundary_control.reader_gate import (
    ReaderQualityGatePolicy,
    evaluate_commit_reader_gate,
    load_reader_reports,
    load_recent_chapters,
    _repeated_loop_second_issues,
)
from src.object_state.readercontract import ReaderContract
from src.object_state.readerreport import ReaderExperienceReport, ReaderDimension
from src.object_state.reviewissue import ReviewIssue
from src.object_state.serialreader import SerialReaderFinding, SerialReaderReport


def _review_issue(issue_type: str = "timeline_error", severity: str = "blocking") -> ReviewIssue:
    return ReviewIssue(
        issue_id="iss_test",
        issue_type=issue_type,
        severity=severity,
        location="正文",
        scope_of_impact="测试",
        violated_rule="r",
        description="d",
        suggested_fix="f",
    )


def _contract() -> ReaderContract:
    return ReaderContract(
        contract_id="c1",
        audience="读者",
        core_pleasures=["真相推进"],
        follow_reason="代价下做选择",
        core_tension="真相对抗",
        chapter_pacing="每章推进",
        must_keep=["克制"],
        forbidden_drifts=["穿越", "失忆"],
        valid_hooks=["reveal"],
        ending_conditions=["全部回收"],
        opening_minimum_promise="首章选择",
    )


def _reader_report(dim: str = "hook", grade: str = "weak") -> ReaderExperienceReport:
    all_dims = [
        ReaderDimension(
            dimension=d, name=n, grade="good",
            anchor="全章", diagnosis="ok",
        )
        for d, n in (
            ("open", "开头"),
            ("presence", "现场"),
            ("info", "解释"),
            ("dialogue", "对白"),
            ("emotion", "情绪"),
            ("payoff", "反馈"),
            ("hook", "钩子"),
        )
    ]
    for d in all_dims:
        if d.dimension == dim:
            d.grade = grade
            d.diagnosis = f"{dim} 维度问题"
    return ReaderExperienceReport(
        review_target="chapter_2", chapter_id="chapter_2",
        dimensions=all_dims, overall=grade,
    )


def _serial_report(
    dimension: str = "process_text", severity: str = "objective", grade: str = "weak"
) -> SerialReaderReport:
    return SerialReaderReport(
        window=3,
        review_target="chapter_3",
        chapter_refs=["chapter_1", "chapter_2", "chapter_3"],
        findings=[
            SerialReaderFinding(
                finding_id="f1",
                dimension=dimension,
                grade=grade,
                severity=severity,
                issue_type="redundancy",
                evidence="证据",
                location="第3章",
                diagnosis="诊断",
                fix_direction="改法",
            )
        ],
        overall=grade,
    )


class TestDeterministicRules:
    def test_clean_draft_passes(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="主角决定追查，结果发现了新证据。",
            reconcile_issues=[],
            prev_chapters=["上一章有推进。"],
        )
        assert v.route == "pass"
        assert v.axes_armed["window"] is True
        assert v.axes_armed["single_reader"] is False
        assert v.axes_armed["contract"] is False

    def test_reconcile_blocking_blocks(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[_review_issue("timeline_error", "blocking")],
            prev_chapters=["前章。"],
        )
        assert v.route == "block"
        assert any(i.issue_type == "timeline_error" for i in v.issues)

    def test_reconcile_warning_does_not_block(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[_review_issue("weak_progression", "warning")],
            prev_chapters=["前章。"],
        )
        assert v.route == "pass"

    def test_repeated_loop_second_blocks(self):
        prev = "上一章他终于明白一切真相。"
        draft = "本章他又终于明白一切真相。"
        issues = _repeated_loop_second_issues(draft, [prev], "chapter_2")
        assert issues and issues[0].is_blocking()
        assert issues[0].issue_type == "redundancy"

    def test_repeated_loop_different_core_passes(self):
        prev = "上一章他终于明白一切真相。"
        draft = "本章他终于明白凶手另有其人。"
        assert _repeated_loop_second_issues(draft, [prev], "chapter_2") == []

    def test_contract_drift_blocks(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="他居然穿越了。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            reader_contract=_contract(),
        )
        assert v.route == "block"
        assert any("穿越" in i.description for i in v.issues)

    def test_contract_clean_draft_passes_with_contract(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="他决定继续追查真相。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            reader_contract=_contract(),
        )
        assert v.route == "pass"
        assert v.axes_armed["contract"] is True


class TestReportArmedRules:
    def test_key_reader_dim_weak_rewrites(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            reader_report=_reader_report("hook", "weak"),
        )
        assert v.route == "rewrite"
        assert any(i.issue_id == "iss_q4_reader_hook" for i in v.issues)

    def test_key_reader_dim_needs_work_passes(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            reader_report=_reader_report("hook", "needs_work"),
        )
        assert v.route == "pass"

    def test_serial_objective_blocks(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            serial_report=_serial_report("process_text", "objective", "weak"),
        )
        assert v.route == "block"

    def test_serial_aesthetic_manual(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。",
            reconcile_issues=[],
            prev_chapters=["前章。"],
            serial_report=_serial_report("repeated_ending", "aesthetic", "needs_work"),
        )
        assert v.route == "manual"

    def test_serial_objective_beats_aesthetic(self):
        # objective 硬错误优先于 aesthetic（block > manual）
        report = _serial_report("process_text", "objective", "weak")
        report.findings.append(
            SerialReaderFinding(
                finding_id="f2", dimension="repeated_ending", grade="needs_work",
                severity="aesthetic", issue_type="weak_progression",
                evidence="e", location="l", diagnosis="d",
            )
        )
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。", reconcile_issues=[], prev_chapters=["前章。"],
            serial_report=report,
        )
        assert v.route == "block"


class TestZeroCost:
    def test_first_chapter_window_unarmed(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="首章正文。", reconcile_issues=[], prev_chapters=None
        )
        assert v.route == "pass"
        assert v.axes_armed["window"] is False

    def test_no_reports_axes_unarmed(self):
        v = ReaderQualityGatePolicy().evaluate(
            draft_text="正文。", reconcile_issues=[], prev_chapters=["前章。"]
        )
        assert v.route == "pass"
        assert v.axes_armed["single_reader"] is False
        assert v.axes_armed["serial_reader"] is False


class TestCommitGateChain:
    def test_clean_draft_passes_chain(self, tmp_path):
        base = Path(tmp_path)
        out = base / "output" / "extend"
        chapters = base / "chapters"
        out.mkdir(parents=True)
        chapters.mkdir()
        verdict, package, reconcile = evaluate_commit_reader_gate(
            output_dir=out, chapters_dir=chapters,
            draft_text="主角决定追查，结果发现了新证据。",
            facts=None, characters=None, chapter_ref="chapter_1",
        )
        assert verdict.route == "pass"
        assert package is not None
        assert package.source_text_hash

    def test_ambient_draft_blocked_by_chain(self, tmp_path):
        base = Path(tmp_path)
        out = base / "output" / "extend"
        chapters = base / "chapters"
        out.mkdir(parents=True)
        chapters.mkdir()
        verdict, package, reconcile = evaluate_commit_reader_gate(
            output_dir=out, chapters_dir=chapters,
            draft_text="他坐着，看着窗外，喝了一口水。",
            facts=None, characters=None, chapter_ref="chapter_1",
        )
        assert verdict.route == "block"
        assert any(i.issue_type == "weak_progression" for i in verdict.issues)

    def test_reports_wrong_chapter_are_unarmed(self, tmp_path):
        # 报告对应当前章才武装；别的章的旧报告不误伤
        base = Path(tmp_path)
        reader_dir = base / "output" / "reader_experience"
        reader_dir.mkdir(parents=True)
        # 报告是 chapter_2 的（_reader_report 固定 chapter_id="chapter_2"）
        rp = _reader_report("hook", "weak")
        reader_dir.joinpath("reader_report.json").write_text(
            rp.model_dump_json(), encoding="utf-8"
        )
        # 查询 chapter_1 → 报告不匹配 → unarmed
        report_mismatch, _ = load_reader_reports(reader_dir, "chapter_1")
        assert report_mismatch is None
        # 查询 chapter_2 → 报告匹配 → armed
        report_match, _ = load_reader_reports(reader_dir, "chapter_2")
        assert report_match is not None


class TestCausalDefenseInGateChain:
    """P1 长程因果防线接入提交点：causal_objects 提供时运行，缺省零成本."""

    def _chain(self, tmp_path, causal_objects=None, draft_text="主角继续调查。"):
        base = Path(tmp_path)
        out = base / "output" / "extend"
        chapters = base / "chapters"
        out.mkdir(parents=True)
        chapters.mkdir()
        return evaluate_commit_reader_gate(
            output_dir=out,
            chapters_dir=chapters,
            draft_text=draft_text,
            facts=None,
            characters=None,
            chapter_ref="chapter_1",
            causal_objects=causal_objects,
        )

    def test_erased_event_blocks_with_causal_objects(self, tmp_path):
        from src.object_state import FactEntry, FactLedger, PlotUnit

        ledger = FactLedger(entries=[
            FactEntry(
                fact_id="f_d", statement="古堡已被焚毁", fact_type="event",
                involved_entities=["古堡"], confirmed=True,
            )
        ])
        pu = PlotUnit(
            unit_id="pu_a", level="scene", goal="探查", conflict="寻找线索",
            participants=["c001"], input_state_ref="s_in", output_state_ref="s_out",
            released_information=["古堡竟完好如初"],
        )
        verdict, _, _ = self._chain(
            tmp_path,
            causal_objects=[ledger, pu],
            draft_text="主角重访古堡，发现它完好如初。",
        )
        assert verdict.route == "block"
        assert any(i.issue_type == "fact_conflict" for i in verdict.issues)

    def test_clean_causal_objects_still_pass(self, tmp_path):
        from src.object_state import FactEntry, FactLedger, PlotUnit

        ledger = FactLedger(entries=[
            FactEntry(
                fact_id="f_ok", statement="主角到达王城", fact_type="event",
                involved_entities=["主角"], confirmed=True,
            )
        ])
        pu = PlotUnit(
            unit_id="pu_b", level="scene", goal="拜会", conflict="投帖",
            participants=["c001"], input_state_ref="s_in", output_state_ref="s_out",
            released_information=["他递上拜帖"],
            consequences=["通报"],
        )
        verdict, _, _ = self._chain(
            tmp_path,
            causal_objects=[ledger, pu],
            draft_text="主角抵达王城，递上拜帖等待接见。",
        )
        assert verdict.route == "pass"

    def test_no_causal_objects_zero_cost(self, tmp_path):
        # 缺省 causal_objects=None → 不运行因果防线，行为与旧版一致
        verdict, _, _ = self._chain(
            tmp_path, draft_text="主角决定追查，结果发现了新证据。"
        )
        assert verdict.route == "pass"


class TestLoadHelpers:
    def test_load_recent_chapters_order(self, tmp_path):
        d = Path(tmp_path)
        d.joinpath("chapter_2.txt").write_text("二", encoding="utf-8")
        d.joinpath("chapter_1.txt").write_text("一", encoding="utf-8")
        d.joinpath("chapter_10.txt").write_text("十", encoding="utf-8")
        assert load_recent_chapters(d, 2) == ["二", "十"]
        assert load_recent_chapters(d, 5) == ["一", "二", "十"]
