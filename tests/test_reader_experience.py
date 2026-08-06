"""Reader experience review tests — 读者体验审查.

覆盖：
- 对象层：ReaderDimension/ReaderExperienceReport 构造、7 维完整性校验
- 规则层：7 维判定标准渲染、量化代理渲染
- 单元：build_prompt 含正文+量化+7维标准；parse_response 字段校验
- overall 兜底计算（钩子优先 tie-break）
"""

import json

import pytest

from src.domain_layer.reader_experience_rules import (
    build_reader_dimension_guidance,
    build_reader_quantitative_guidance,
)
from src.object_state.readerreport import (
    READER_DIMENSIONS,
    READER_GRADES,
    ReaderDimension,
    ReaderExperienceReport,
)
from src.workflow_action.reader_experience import ReaderExperienceUnit


def _mk_report(dimensions=None, overall="good"):
    dims = dimensions or [
        ReaderDimension(dimension=d, name=n, grade="good", anchor="x", diagnosis="y")
        for d, n in READER_DIMENSIONS
    ]
    return ReaderExperienceReport(
        review_target="chapters/chapter_1.txt",
        chapter_id="chapter_1",
        dimensions=dims,
        overall=overall,
    )


def test_seven_dimensions_defined():
    assert [d for d, _ in READER_DIMENSIONS] == [
        "open", "presence", "info", "dialogue", "emotion", "payoff", "hook",
    ]


def test_grades_valid():
    assert set(READER_GRADES) == {"good", "needs_work", "weak"}


def test_report_construction():
    r = _mk_report()
    assert r.route == "none"
    assert len(r.dimensions) == 7
    assert r.overall == "good"


def test_report_rejects_missing_dimensions():
    with pytest.raises(ValueError, match="missing required dimension"):
        ReaderExperienceReport(
            review_target="x",
            dimensions=[
                ReaderDimension(dimension="open", name="开头", grade="good",
                                anchor="x", diagnosis="y")
            ],
            overall="good",
        )


def test_report_rejects_empty_dimensions():
    with pytest.raises(ValueError, match="must not be empty"):
        ReaderExperienceReport(
            review_target="x", dimensions=[], overall="good",
        )


def test_dimension_validates_grade():
    with pytest.raises(ValueError):
        ReaderDimension(
            dimension="open", name="开头", grade="bad",
            anchor="x", diagnosis="y",
        )


def test_dimension_validates_name():
    with pytest.raises(ValueError):
        ReaderDimension(
            dimension="open", name="", grade="good",
            anchor="x", diagnosis="y",
        )


def test_guidance_renders_all_seven():
    g = build_reader_dimension_guidance()
    assert "## open 开头是否拖沓" in g
    assert "## hook 章末钩子是否有足够信息量" in g
    assert "判定问题" in g
    assert "达标信号" in g
    assert "不达标信号" in g
    assert "good: 前 2 段进入事件" in g


def test_quantitative_guidance_renders():
    g = build_reader_quantitative_guidance()
    assert "量化代理信号" in g
    assert "emotion 情绪落地" in g
    assert "hook 章末钩子" in g


def test_build_prompt_contains_essentials():
    unit = ReaderExperienceUnit()
    prompt = unit.build_prompt(
        prose_text="青云州的秋天。\n林烬把第七块碑的最后一笔誊进册子。",
        chapter_id="chapter_1",
        style_context="调性: 克制",
    )
    assert "【审查章节】chapter_1" in prompt
    assert "【正文全文】" in prompt
    assert "【量化代理分析" in prompt
    assert "【七维判定标准】" in prompt
    assert "【写作风格画像】" in prompt
    assert "【输出格式】" in prompt
    assert "青云州的秋天" in prompt


def test_parse_response_valid():
    unit = ReaderExperienceUnit()
    response = json.dumps({
        "dimensions": [
            {"dimension": d, "name": n, "grade": "good",
             "anchor": "第1段", "diagnosis": "ok"}
            for d, n in READER_DIMENSIONS
        ],
        "overall": "good",
    }, ensure_ascii=False)
    data = unit.parse_response(response)
    assert len(data["dimensions"]) == 7
    assert data["overall"] == "good"


def test_parse_response_rejects_missing_overall():
    unit = ReaderExperienceUnit()
    response = json.dumps({"dimensions": []}, ensure_ascii=False)
    with pytest.raises(ValueError, match="overall"):
        unit.parse_response(response)


def test_parse_response_accepts_bad_grade_then_merge_rejects():
    # parse_response 只查顶层字段；每维 grade 合法性由 merge 的 pydantic 校验兜底。
    unit = ReaderExperienceUnit()
    response = json.dumps({
        "dimensions": [
            {"dimension": "open", "name": "开头", "grade": "bad",
             "anchor": "x", "diagnosis": "y"}
        ],
        "overall": "good",
    }, ensure_ascii=False)
    data = unit.parse_response(response)
    assert data["overall"] == "good"
    with pytest.raises(ValueError):
        unit.merge(data, review_target="c1")


def test_parse_response_rejects_unexpected_field():
    unit = ReaderExperienceUnit()
    response = json.dumps({
        "dimensions": [],
        "overall": "good",
        "extra": 1,
    }, ensure_ascii=False)
    with pytest.raises(ValueError, match="unexpected field"):
        unit.parse_response(response)


def test_merge_creates_report():
    unit = ReaderExperienceUnit()
    qualitative = {
        "dimensions": [
            {"dimension": d, "name": n, "grade": "needs_work",
             "anchor": "x", "diagnosis": "y", "fix_direction": "z"}
            for d, n in READER_DIMENSIONS
        ],
        "overall": "needs_work",
    }
    report = unit.merge(qualitative, review_target="c1", chapter_id="chapter_1")
    assert report.overall == "needs_work"
    assert report.route == "none"
    assert report.chapter_id == "chapter_1"
    assert all(dim.fix_direction == "z" for dim in report.dimensions)


def test_overall_tiebreak_hook_wins():
    # 5 good + 2 needs_work，其中 hook=needs_work → overall 应取 needs_work
    dims = [
        ReaderDimension(dimension=d, name=n, grade="good", anchor="x", diagnosis="y")
        for d, n in READER_DIMENSIONS
        if d != "hook"
    ]
    dims.append(
        ReaderDimension(dimension="hook", name="章末钩子", grade="needs_work",
                        anchor="x", diagnosis="y")
    )
    assert ReaderExperienceUnit._overall_from_dimensions(dims) == "needs_work"


def test_overall_tiebreak_hook_not_worst():
    # 5 good + open=needs_work + hook=good → overall 应取 needs_work（非 hook 的最差）
    dims = [
        ReaderDimension(dimension=d, name=n, grade="good", anchor="x", diagnosis="y")
        for d, n in READER_DIMENSIONS
        if d not in ("open", "hook")
    ]
    dims.append(ReaderDimension(dimension="open", name="开头", grade="needs_work",
                                anchor="x", diagnosis="y"))
    dims.append(ReaderDimension(dimension="hook", name="章末钩子", grade="good",
                                anchor="x", diagnosis="y"))
    assert ReaderExperienceUnit._overall_from_dimensions(dims) == "needs_work"
