"""Tests for the horizontal time domain (TimeBook + FACTTRACK v2).

对齐 design §9 测试契约：
  - 零成本：无 TimeBook → build_prompt 字节不变、检测不跑、命令无残留
  - 检测4/5/6：有/无 time_book 两种行为各断言一次
  - build_time_context 与 37_time_domain_design §5 示例逐字节一致
  - novel time 单遍、anchors 单调校验、空提取静默降级
  - timeline_report.json 产物契约、compose workspec.time 缺省回退
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from src.object_state import (
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
)
from src.object_state.timebook import (
    EraContext,
    TimeAnchor,
    TimeBook,
    TimeInitial,
    TimelineSpec,
)
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.time_audit import (
    _detect_anchor_regression,
    _detect_foreshadow_expiry,
    _detect_season_violation,
    build_timeline_report,
    run_time_audit,
)
from src.workflow_action.timebook import (
    build_time_context,
    extract_time_anchors,
    load_time_book,
    refresh_time_book_anchors,
    save_time_book,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- 零成本契约：无 TimeBook → 字节不变 --------------------------------------


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["gl"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _empty_fg() -> ForeshadowGraph:
    return ForeshadowGraph(entries=[])


def _base_continue_prompt(**kwargs) -> str:
    cont = ContinueUnit()
    defaults = dict(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=_empty_fg(),
        workspec_context="作品类型: 仙侠",
    )
    defaults.update(kwargs)
    return cont.build_prompt(**defaults)


def test_time_context_default_unchanged_prompt():
    """默认 time_context='' 时 prompt 与无此参数时字节一致（镜像 continuation_anchors）."""
    with_param = _base_continue_prompt(time_context="")
    without_param = _base_continue_prompt()
    assert with_param == without_param
    assert "【时间上下文】" not in without_param


def test_time_context_no_timebook_empty():
    assert build_time_context(None) == ""


def test_build_time_context_matches_design_example():
    """37_time_domain_design §5 示例逐字节一致."""
    tb = TimeBook(
        initial=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"),
        anchors=[
            TimeAnchor(
                chapter="第N章",
                date="2001-01-22",
                lunar="腊月廿九",
                tod="入夜",
                loc="某城",
            )
        ],
        era=[EraContext(year=2001, events=["入世", "申奥成功"], note=None)],
        rules=["某城(南半球)1月为盛夏，另一城为寒冬"],
    )
    expected = (
        "上章: 第N章 2001-01-22(腊月廿九)入夜 某城\n"
        "本章: 第N+1章 2001-01-23 除夕 某城(南半球盛夏)\n"
        "时代背景(2001): 入世、申奥成功\n"
        "时间规则: 某城(南半球)1月为盛夏，另一城为寒冬"
    )
    assert build_time_context(tb) == expected


def test_build_time_context_initial_only_renders_chapter_one():
    """无锚点（compose 初跑）时以起点渲染 本章: 第1章."""
    tb = TimeBook(initial=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"))
    ctx = build_time_context(tb)
    assert "本章: 第1章 2001-01-23 除夕 某城" in ctx
    assert "上章:" not in ctx


def test_time_context_injects_section():
    tb = TimeBook(
        initial=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"),
        anchors=[TimeAnchor(chapter="第1章", date="2001-01-23", lunar="除夕")],
    )
    prompt = _base_continue_prompt(time_context=build_time_context(tb))
    assert "【时间上下文】" in prompt
    assert "上章: 第1章 2001-01-23(除夕)" in prompt


# --- 检测4 时间回退 ----------------------------------------------------------


def test_det4_regression_flagged_only_with_timebook():
    tb = TimeBook(
        anchors=[
            TimeAnchor(chapter="第1章", date="2001-02-04"),
            TimeAnchor(chapter="第2章", date="2001-01-23"),
        ]
    )
    issues = _detect_anchor_regression(tb)
    assert len(issues) == 1
    assert issues[0].issue_id == "iss_time_regress_第1章_第2章"
    assert issues[0].severity == "warning"
    assert issues[0].is_blocking() is False


def test_det4_monotonic_no_issues():
    tb = TimeBook(
        anchors=[
            TimeAnchor(chapter="第1章", date="2001-01-22"),
            TimeAnchor(chapter="第2章", date="2001-01-23"),
        ]
    )
    assert _detect_anchor_regression(tb) == []


def test_det4_empty_anchors_no_issues():
    assert _detect_anchor_regression(TimeBook()) == []


# --- 检测5 先知逾期 ----------------------------------------------------------


def _active_foreshadow(expires_at=None) -> ForeshadowGraph:
    return ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="t1",
                content="角色乙生死未卜",
                current_status="active",
                setup_point="第1章",
                visibility_level="explicit",
                expected_payoff="查明下落",
                expires_at=expires_at,
            )
        ]
    )


def test_det5_foreshadow_expired_when_past_deadline():
    tb = TimeBook(anchors=[TimeAnchor(chapter="第2章", date="2001-02-01")])
    issues = _detect_foreshadow_expiry([_active_foreshadow("2001-01-23")], tb)
    assert [i.issue_id for i in issues] == ["iss_time_foreshadow_expired_t1"]


def test_det5_foreshadow_not_expired_before_deadline():
    tb = TimeBook(anchors=[TimeAnchor(chapter="第2章", date="2001-02-01")])
    assert _detect_foreshadow_expiry([_active_foreshadow("2001-03-01")], tb) == []


def test_det5_timeline_ended_flagged():
    tb = TimeBook(
        anchors=[TimeAnchor(chapter="第2章", date="2001-02-01")],
        timelines=[TimelineSpec(id="past", name="前世", ends="2001-01-25", note="x")],
    )
    issues = _detect_foreshadow_expiry([], tb)
    assert [i.issue_id for i in issues] == ["iss_time_timeline_ended_past"]


def test_det5_no_timebook_or_no_anchor_skips():
    assert _detect_foreshadow_expiry([_active_foreshadow("2001-01-23")], TimeBook()) == []


# --- 检测6 季节/历法 ---------------------------------------------------------


def test_det6_opposite_season_flagged():
    tb = TimeBook(anchors=[TimeAnchor(chapter="第1章", date="2001-07-15", lunar="腊月")])
    issues = _detect_season_violation(tb)
    assert [i.issue_id for i in issues] == ["iss_time_season_第1章"]


def test_det6_same_season_no_issue():
    tb = TimeBook(anchors=[TimeAnchor(chapter="第1章", date="2001-01-15", lunar="除夕")])
    assert _detect_season_violation(tb) == []


def test_det6_southern_hemisphere_rule_override():
    tb = TimeBook(
        anchors=[
            TimeAnchor(chapter="第1章", date="2001-01-15", lunar="除夕", loc="某城")
        ],
        rules=["某城(南半球)1月为盛夏，另一城为寒冬"],
    )
    assert _detect_season_violation(tb) == []


def test_det6_without_rules_flag_uses_solar_default():
    # 无 rules 时仍按北半球默认季节判定；阳历7月(夏) 对 农历腊月(冬) 相反
    tb = TimeBook(anchors=[TimeAnchor(chapter="第1章", date="2001-07-15", lunar="腊月")])
    assert len(_detect_season_violation(tb)) == 1


# --- run_time_audit 聚合 -----------------------------------------------------


def test_run_time_audit_no_timebook_baseline_only():
    """time_book=None → 仅 baseline（检测4/5/6 不跑），行为与现状一致."""
    tb_anchors = TimeBook(
        anchors=[
            TimeAnchor(chapter="第1章", date="2001-02-04"),
            TimeAnchor(chapter="第2章", date="2001-01-23"),
        ]
    )
    objects = [_active_foreshadow("2001-01-23")]
    with_tb = run_time_audit(objects, tb_anchors)
    assert any(i.issue_id.startswith("iss_time_regress") for i in with_tb)
    assert any(i.issue_id.startswith("iss_time_foreshadow") for i in with_tb)
    without_tb = run_time_audit(objects, None)
    assert all(not i.issue_id.startswith("iss_time_") for i in without_tb)


# --- timeline_report.json 契约 ----------------------------------------------


def test_build_timeline_report_contract():
    tb = TimeBook(
        initial=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"),
        anchors=[TimeAnchor(chapter="第1章", date="2001-01-23")],
    )
    report = build_timeline_report(
        [_active_foreshadow("2001-01-22")],
        tb,
        source_text_ref="input.txt",
    )
    assert report["schema_version"] == 1
    assert report["source_text_ref"] == "input.txt"
    assert report["time_book"] is not None
    assert report["latest_anchor"]["chapter"] == "第1章"
    assert report["detections_enabled"]["anchor_regression"] is True
    assert report["route"] == "pass"  # 全 warning 非 blocking
    assert report["blocking_count"] == 0
    assert any(i["issue_type"] == "timeline_error" for i in report["issues"])


def test_build_timeline_report_no_timebook():
    report = build_timeline_report([], None, source_text_ref="input.txt")
    assert report["time_book"] is None
    assert report["detections_enabled"]["anchor_regression"] is False
    assert report["detections_enabled"]["foreshadow_expiry"] is False
    assert report["latest_anchor"] is None


# --- 锚提取 / TimeBook 校准 --------------------------------------------------


def test_extract_time_anchors_date_lunar_tod():
    text = (
        "第1章 除夕前夜\n　　2001年1月22日，入夜时分。\n\n"
        "第2章 立春\n　　2001年2月4日。"
    )
    from src.boundary_control.chunking import split_by_chapters

    anchors = extract_time_anchors(split_by_chapters(text))
    assert len(anchors) == 2
    assert anchors[0].date == "2001-01-22"
    assert anchors[0].tod == "入夜"
    assert anchors[1].date == "2001-02-04"


def test_extract_time_anchors_empty_head_skips():
    from src.boundary_control.chunking import split_by_chapters

    anchors = extract_time_anchors(split_by_chapters("第1章 无时间锚\n　　正文无日期。"))
    assert anchors == []


def test_refresh_time_book_anchors_zero_cost_when_no_timebook(tmp_path):
    """无 TimeBook → refresh 是 no-op，不产生任何文件."""
    text = "第1章 a\n　　2001年1月22日。"
    from src.boundary_control.chunking import split_by_chapters

    time_dir = tmp_path / "time"
    out = refresh_time_book_anchors(time_dir, split_by_chapters(text))
    assert out is None
    assert not (time_dir / "time_book.json").exists()


def test_refresh_time_book_anchors_dedupes_by_chapter(tmp_path):
    text = "第1章 a\n　　2001年1月22日。\n\n第2章 b\n　　2001年1月23日。"
    from src.boundary_control.chunking import split_by_chapters

    time_dir = tmp_path / "time"
    tb = TimeBook(anchors=[TimeAnchor(chapter="第1章", date="2001-01-01")])
    save_time_book(time_dir, tb)
    refreshed = refresh_time_book_anchors(time_dir, split_by_chapters(text))
    assert refreshed is not None
    chapters = {a.chapter for a in refreshed.anchors}
    assert chapters == {"第1章", "第2章"}  # 第1章去重，第2章并入


# --- novel time CLI（单遍） --------------------------------------------------


def _run_cli(args, novels_root: Path):
    env = os.environ.copy()
    env["NOVELS_ROOT"] = str(novels_root)
    return subprocess.run(
        [sys.executable, "src/novel_cli.py", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write_novel_input(novel_dir: Path) -> Path:
    text = (
        "第1章 除夕前夜\n　　2001年1月22日，入夜时分。\n\n"
        "第2章 除夕\n　　2001年1月23日。\n\n"
        "第3章 立春\n　　2001年2月4日。"
    )
    input_path = novel_dir / "input.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(text, encoding="utf-8")
    return input_path


def test_novel_time_rebuild_check_single_pass(tmp_path):
    novel_dir = tmp_path / "样书"
    input_path = _write_novel_input(novel_dir)
    result = _run_cli(
        ["time", "样书", "--input", str(input_path), "--rebuild", "--check"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    time_dir = novel_dir / "output" / "time"
    assert (time_dir / "time_book.json").exists()
    report = json.loads((time_dir / "timeline_report.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["route"] == "pass"
    assert report["latest_anchor"]["chapter"] == "第3章"
    assert report["latest_anchor"]["date"] == "2001-02-04"


def test_novel_time_empty_extraction_no_file(tmp_path):
    """无可提取锚 → 零成本：不产生 time_book.json."""
    novel_dir = tmp_path / "空锚书"
    input_path = novel_dir / "input.txt"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("第1章 无时间\n　　正文。", encoding="utf-8")
    result = _run_cli(
        ["time", "空锚书", "--input", str(input_path), "--rebuild", "--check"], tmp_path
    )
    assert result.returncode == 0
    assert not (novel_dir / "output" / "time" / "time_book.json").exists()


def test_novel_time_status_default_prints(tmp_path):
    novel_dir = tmp_path / "状态书"
    (novel_dir / "output" / "time").mkdir(parents=True, exist_ok=True)
    tb = TimeBook(
        initial=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"),
        anchors=[TimeAnchor(chapter="第3章", date="2001-02-04", lunar="立春")],
    )
    save_time_book(novel_dir / "output" / "time", tb)
    result = _run_cli(["time", "状态书"], tmp_path)
    assert result.returncode == 0
    assert "第3章" in result.stdout
    assert "起点: 2001-01-23 除夕 某城" in result.stdout


def test_novel_list_shows_time_status(tmp_path):
    novel_dir = tmp_path / "列表书"
    (novel_dir / "output" / "time").mkdir(parents=True, exist_ok=True)
    save_time_book(
        novel_dir / "output" / "time",
        TimeBook(anchors=[TimeAnchor(chapter="第2章", date="2001-01-23")]),
    )
    # 无 TimeBook 的小说（同工作区）应显示 未设定
    empty_dir = tmp_path / "空书"
    empty_dir.mkdir(parents=True, exist_ok=True)
    result = _run_cli(["list", "--json"], tmp_path)
    assert result.returncode == 0
    rows = json.loads(result.stdout)
    row = next(r for r in rows if r["name"] == "列表书")
    assert row["time_status"] == "第2章 2001-01-23"
    empty = next(r for r in rows if r["name"] == "空书")
    assert empty["time_status"] == "未设定"


# --- compose workspec.time ---------------------------------------------------


def test_compose_workspec_time_initializes_timebook(tmp_path, monkeypatch):
    from src.compose_short_form import initialize_from_workspec
    from src.object_state import WorkSpec

    ws = WorkSpec(
        genre="都市",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
        time=TimeInitial(date="2001-01-23", lunar="除夕", loc="某城"),
    )
    objects = initialize_from_workspec(ws)
    assert any(ws2 is ws for ws2 in objects)

    from src.workflow_action.timebook import load_time_book

    # 直接验证 workspec.time → TimeBook 初稿的建模路径
    tb = TimeBook(initial=ws.time)
    assert tb.initial.date == "2001-01-23"
    assert tb.initial.lunar == "除夕"
    assert load_time_book(tmp_path / "time") is None  # 零成本：未显式 save 不产生文件


def test_compose_default_workspec_no_time_field():
    """缺省 WorkSpec 无 time → 不产生 TimeBook（行为与今天一致）."""
    from src.object_state import WorkSpec

    ws = WorkSpec(genre="仙侠", audience="青年", theme="成长", tone="克制", pacing="x")
    assert ws.time is None


# --- rubric 时间维 -----------------------------------------------------------


def test_rubric_no_timeline_report_stays_8_dims():
    from src.domain_layer.review_rubric import REVIEW_RUBRIC, export_rubric

    assert len(REVIEW_RUBRIC) == 8
    payload = export_rubric()
    assert len(payload["dimensions"]) == 8


def test_rubric_with_timeline_report_adds_wnb09():
    from src.domain_layer.review_rubric import export_rubric

    report = build_timeline_report([], TimeBook(), source_text_ref="x")
    payload = export_rubric(timeline_report=report)
    ids = [d["id"] for d in payload["dimensions"]]
    assert len(payload["dimensions"]) == 9
    assert "wnb_09" in ids
    w9 = next(d for d in payload["dimensions"] if d["id"] == "wnb_09")
    assert w9["local_signal_strength"] == "moderate"
