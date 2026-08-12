"""test_calibrate — Q1 Phase 6 人类读者校准（隐藏来源连续阅读）工具测试.

合成夹具（不用真实作品）：材料包组装 / 问卷隐藏来源 / 严格 JSON 解析 /
聚合与 verdict / 硬标准复用分辨力（干净章放行、元文本章阻断）。
"""

import json
import sys
from pathlib import Path

import pytest

from src.object_state.calibratereport import (
    SOURCE_AI,
    SOURCE_ORIGINAL,
    CalibrationChapterAnswer,
    CalibrationHardStandard,
    CalibrationIssue,
    CalibrationReaderResponse,
)
from src.workflow_action.calibrate import (
    CalibrateUnit,
    _parse_range,
    aggregate,
    assemble_packet,
    run_hard_standards,
    verdicts,
)

import src.calibrate_short_form as calibrate_short_form

# 干净章（有对白/事件，可通过零 LLM 门禁）与元文本章（生成过程文字，必被阻断）
CLEAN_TEXT = (
    "九月里，稻子黄了。田埂上有人赶着牛走过，孩子跟在后面拾穗。"
    "父亲蹲在地头抽烟，说：“今年够吃。”"
)
META_TEXT = "上一章末，他挂断了电话，屋里一下子安静下来。"


@pytest.fixture()
def packet_workdir(tmp_path: Path):
    chapters = tmp_path / "chapters"
    generated = tmp_path / "generated"
    chapters.mkdir()
    generated.mkdir()
    (chapters / "chapter_02.txt").write_text("原二章正文。", encoding="utf-8")
    (chapters / "chapter_03.txt").write_text("原三章正文。", encoding="utf-8")
    (generated / "chapter_04.txt").write_text("生成四章正文。", encoding="utf-8")
    (generated / "chapter_05.txt").write_text("生成五章正文。", encoding="utf-8")
    out = tmp_path / "output" / "calibrate"
    out.mkdir(parents=True)
    return chapters, generated, out


def _answer(ref, turn="yes", same="yes", wander="无", disbelieved=(), what="发生了一件事", ant="期待后续"):
    return CalibrationChapterAnswer(
        chapter_ref=ref,
        turn_page=turn,
        same_character=same,
        wander=wander,
        disbelieved=list(disbelieved),
        what_happened=what,
        anticipated=ant,
    )


def _hs(ref, *blocking_issues):
    return CalibrationHardStandard(
        chapter_ref=ref,
        route="block" if blocking_issues else "pass",
        axes_armed={"hard_consistency": True},
        blocking_issues=list(blocking_issues),
    )


def _blocking(issue_type="generative_indicia"):
    return CalibrationIssue(
        issue_type=issue_type,
        severity="blocking",
        location="中段",
        description="测试阻塞问题",
    )


# --------------------------------------------------------------------------
# 章号范围解析
# --------------------------------------------------------------------------

def test_parse_range():
    assert _parse_range("22-23") == [22, 23]
    assert _parse_range("24") == [24]
    assert _parse_range("22-23,25") == [22, 23, 25]
    assert _parse_range("25,22-23") == [22, 23, 25]
    assert _parse_range("") == []


# --------------------------------------------------------------------------
# 材料包组装（隐藏来源）
# --------------------------------------------------------------------------

def test_assemble_packet_source_map_and_reading(packet_workdir):
    chapters_dir, generated_dir, out = packet_workdir
    chapters, reading_path = assemble_packet(
        out, "pkt01", original_spec="2-3", generated_spec="4-5",
        chapters_dir=chapters_dir, generated_dir=generated_dir,
    )
    # 顺序按章号：原2 原3 生成4 生成5（接缝在 03→04）
    assert [c["chapter_ref"] for c in chapters] == [
        "chapter_02", "chapter_03", "chapter_04", "chapter_05",
    ]
    assert [c["source"] for c in chapters] == [
        SOURCE_ORIGINAL, SOURCE_ORIGINAL, SOURCE_AI, SOURCE_AI,
    ]
    # reading.txt 连续文本，章号头存在、顺序正确
    reading = reading_path.read_text(encoding="utf-8")
    assert "## chapter_02" in reading
    assert reading.index("chapter_03") > reading.index("chapter_02")
    assert reading.index("chapter_04") > reading.index("chapter_03")
    # source_map 正确 + 隐私（只含章号与来源类别，无路径/作品名）
    sm = json.loads((out / "pkt01" / "source_map.json").read_text(encoding="utf-8"))
    assert sm == {
        "chapter_02": SOURCE_ORIGINAL,
        "chapter_03": SOURCE_ORIGINAL,
        "chapter_04": SOURCE_AI,
        "chapter_05": SOURCE_AI,
    }
    for ref, source in sm.items():
        assert "/" not in ref and "\\" not in ref
        assert source in (SOURCE_ORIGINAL, SOURCE_AI)


def test_assemble_packet_missing_generated_raises(packet_workdir):
    chapters_dir, generated_dir, out = packet_workdir
    with pytest.raises(ValueError):
        assemble_packet(
            out, "pkt", original_spec="2-3", generated_spec="9",
            chapters_dir=chapters_dir, generated_dir=generated_dir,
        )


# --------------------------------------------------------------------------
# 问卷：隐藏来源 + 覆盖全部章节
# --------------------------------------------------------------------------

def test_prompt_hides_sources_and_lists_chapters(packet_workdir):
    chapters_dir, generated_dir, out = packet_workdir
    chapters, reading_path = assemble_packet(
        out, "pkt01", original_spec="2-3", generated_spec="4-5",
        chapters_dir=chapters_dir, generated_dir=generated_dir,
    )
    refs = [c["chapter_ref"] for c in chapters]
    prompt = CalibrateUnit().build_prompt(refs, reading_path, reader_id="reader_x")
    # 问卷要素
    assert str(reading_path) in prompt
    for ref in refs:
        assert ref in prompt
    assert "turn_page" in prompt and "overall_genre_change" in prompt
    assert "what_happened" in prompt and "anticipated" in prompt
    # 来源类别绝不泄漏给读者
    assert SOURCE_ORIGINAL not in prompt and SOURCE_AI not in prompt


# --------------------------------------------------------------------------
# 严格 JSON 解析
# --------------------------------------------------------------------------

def _full_response(refs, reader_id="reader_1"):
    chapters = [
        _answer(ref).model_dump()
        for ref in refs
    ]
    return json.dumps(
        {"reader_id": reader_id, "chapters": chapters, "overall_genre_change": "no"},
        ensure_ascii=False,
    )


def test_parse_response_valid(packet_workdir):
    chapters_dir, generated_dir, out = packet_workdir
    chapters, _ = assemble_packet(
        out, "pkt01", original_spec="2-3", generated_spec="4-5",
        chapters_dir=chapters_dir, generated_dir=generated_dir,
    )
    refs = [c["chapter_ref"] for c in chapters]
    unit = CalibrateUnit()
    parsed = unit.parse_response(_full_response(refs), refs)
    assert isinstance(parsed, CalibrationReaderResponse)
    assert parsed.reader_id == "reader_1"
    assert [a.chapter_ref for a in parsed.chapters] == refs


def test_parse_response_strict_errors(packet_workdir):
    chapters_dir, generated_dir, out = packet_workdir
    chapters, _ = assemble_packet(
        out, "pkt01", original_spec="2-3", generated_spec="4-5",
        chapters_dir=chapters_dir, generated_dir=generated_dir,
    )
    refs = [c["chapter_ref"] for c in chapters]
    unit = CalibrateUnit()
    # 缺字段
    with pytest.raises(ValueError):
        unit.parse_response('{"chapters": []}', refs)
    # 多余字段
    with pytest.raises(ValueError):
        unit.parse_response(
            json.dumps({"reader_id": "r", "chapters": [_answer(refs[0]).model_dump()],
                        "overall_genre_change": "no", "extra": 1}),
            refs,
        )
    # 非法选项
    bad = [_answer(ref).model_dump() for ref in refs]
    bad[0]["turn_page"] = "maybe"
    with pytest.raises(ValueError):
        unit.parse_response(
            json.dumps({"reader_id": "r", "chapters": bad, "overall_genre_change": "no"},
                       ensure_ascii=False),
            refs,
        )
    # 覆盖不全（缺一章）
    partial = [_answer(ref).model_dump() for ref in refs[:3]]
    with pytest.raises(ValueError):
        unit.parse_response(
            json.dumps({"reader_id": "r", "chapters": partial, "overall_genre_change": "no"},
                       ensure_ascii=False),
            refs,
        )
    # 顺序不符
    reversed_refs = [_answer(ref).model_dump() for ref in list(reversed(refs))]
    with pytest.raises(ValueError):
        unit.parse_response(
            json.dumps({"reader_id": "r", "chapters": reversed_refs, "overall_genre_change": "no"},
                       ensure_ascii=False),
            refs,
        )


# --------------------------------------------------------------------------
# 聚合 + verdict（pilot 口径）
# --------------------------------------------------------------------------

def test_aggregate_and_verdicts():
    source_map = {
        "chapter_02": SOURCE_ORIGINAL,
        "chapter_03": SOURCE_ORIGINAL,
        "chapter_04": SOURCE_AI,
        "chapter_05": SOURCE_AI,
    }
    hard = [
        _hs("chapter_02"),
        _hs("chapter_03"),
        _hs("chapter_04", _blocking("generative_indicia")),
        _hs("chapter_05"),
    ]
    reader = CalibrationReaderResponse(
        schema_version=1,
        reader_id="reader_1",
        chapters=[
            _answer("chapter_02"),
            _answer("chapter_03"),
            _answer("chapter_04", turn="no", same="slight_change",
                    wander="第四章中段", disbelieved=["接电话的男人身份"]),
            _answer("chapter_05", turn="hesitating", same="slight_change"),
        ],
        overall_genre_change="changed",
    )
    agg = aggregate(source_map, hard, reader)
    assert agg.continue_ratio == 0.5  # yes=2/4
    assert agg.same_character_ratio == 0.5  # yes=2/4
    assert agg.genre_change == "changed"
    assert agg.wander_anchors == [{"chapter_ref": "chapter_04", "anchor": "第四章中段"}]
    assert agg.disbelieved_facts == [
        {"chapter_ref": "chapter_04", "fact": "接电话的男人身份"}
    ]
    assert len(agg.what_happened) == 4
    assert len(agg.anticipated) == 4

    ver = verdicts(source_map, hard, reader)
    assert ver.original_clean is True
    assert ver.generated_clean is False
    assert ver.reader_continue is False  # 0.5 不 > 0.5
    assert ver.reader_genre_stable is False
    assert ver.is_pilot is True


def test_aggregate_filters_empty_wander_and_disbelieved():
    source_map = {"chapter_02": SOURCE_ORIGINAL}
    hard = [_hs("chapter_02")]
    reader = CalibrationReaderResponse(
        schema_version=1,
        reader_id="reader_1",
        chapters=[_answer("chapter_02", wander="无", disbelieved=[])],
        overall_genre_change="no",
    )
    agg = aggregate(source_map, hard, reader)
    assert agg.continue_ratio == 1.0
    assert agg.same_character_ratio == 1.0
    assert agg.wander_anchors == []
    assert agg.disbelieved_facts == []
    ver = verdicts(source_map, hard, reader)
    assert ver.reader_continue is True
    assert ver.reader_genre_stable is True


# --------------------------------------------------------------------------
# 硬标准复用分辨力（干净章放行 / 元文本章阻断）
# --------------------------------------------------------------------------

def test_hard_standards_discriminate():
    clean = {"chapter_ref": "chapter_02", "source": SOURCE_ORIGINAL, "text": CLEAN_TEXT}
    bad = {"chapter_ref": "chapter_04", "source": SOURCE_AI, "text": META_TEXT}
    hard = run_hard_standards(
        [clean, bad], facts=None, characters=None, time_book=None, reader_contract=None
    )
    by_ref = {h.chapter_ref: h for h in hard}
    assert by_ref["chapter_02"].blocking_issues == []
    assert by_ref["chapter_02"].route == "pass"
    assert any(i.issue_type == "generative_indicia" for i in by_ref["chapter_04"].blocking_issues)
    assert by_ref["chapter_04"].route == "block"


# --------------------------------------------------------------------------
# CLI 端到端（合成夹具，两阶段 [WAITING]）
# --------------------------------------------------------------------------

def test_calibrate_short_form_end_to_end(packet_workdir, monkeypatch):
    chapters_dir, generated_dir, out = packet_workdir
    # 阶段 1：组装 + 硬标准 → [WAITING]
    monkeypatch.setattr(sys, "argv", [
        "calibrate_short_form.py",
        "--output-dir", str(out),
        "--chapters-dir", str(chapters_dir),
        "--generated-dir", str(generated_dir),
        "--packet", "pkt01",
        "--original", "2-3",
        "--generated", "4-5",
        "--build",
    ])
    assert calibrate_short_form.main() == 0
    prompt_path = out / "pkt01" / "calibrate_prompt.txt"
    response_path = out / "pkt01" / "calibration_response.txt"
    assert prompt_path.exists()
    assert not response_path.exists()
    assert not (out / "pkt01" / "calibration_report.json").exists()
    # 阶段 2：读者填响应 → 聚合
    refs = ["chapter_02", "chapter_03", "chapter_04", "chapter_05"]
    response = json.dumps(
        {
            "reader_id": "operator_1",
            "chapters": [_answer(r).model_dump() for r in refs],
            "overall_genre_change": "no",
        },
        ensure_ascii=False,
    )
    response_path.write_text(response, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "calibrate_short_form.py",
        "--output-dir", str(out),
        "--chapters-dir", str(chapters_dir),
        "--packet", "pkt01",
        "--reader-id", "reader_1",
    ])
    assert calibrate_short_form.main() == 0
    report = json.loads(
        (out / "pkt01" / "calibration_report.json").read_text(encoding="utf-8")
    )
    assert report["packet_id"] == "pkt01"
    assert report["reader"]["reader_id"] == "operator_1"
    assert report["aggregate"]["continue_ratio"] == 1.0
    assert report["verdicts"]["is_pilot"] is True
    # source_map 在报告里对读者隐藏到操作者侧（报告含来源，但问卷 prompt 不含）
    assert set(report["source_map"].values()) == {SOURCE_ORIGINAL, SOURCE_AI}
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert SOURCE_ORIGINAL not in prompt_text and SOURCE_AI not in prompt_text
