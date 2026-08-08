"""Blind A/B 盲评工具 tests — 测量 Post-Prose Review 的 Detection Precision / Revision Gain.

覆盖：
- BlindEvalUnit 的 prompt 构建：Revision Gain 不透露 which_is_original、不展示 issue；
  Detection 只呈现原文 + issue_type。
- parse 严格性（preference/flaw_present 枚举）。
- run_revision_gain / run_detection：独立 Judge 写回台账。
- summarize：按 issue_type 分层 + net_rate + better_rate + Wilson CI + detection_precision。
- 关键语义：Revision Agent ≠ Judge；no_difference/uncertain 是合法 Abstain。
"""

import json

import pytest

from src.experiment.blind_eval import (
    BlindEvalUnit,
    run_detection,
    run_revision_gain,
    summarize,
)


def _entry(*, which="a", issue_type="redundancy", orig="原文不错。", rev="修订更顺。"):
    if which == "a":
        return {
            "cycle_id": "pu_1", "issue_types": [issue_type],
            "issue_severity": "blocking",
            "version_a": orig, "version_b": rev, "which_is_original": "a",
            "detection": {"original_has_flaw": None},
            "revision_gain": {"preference": None, "confidence": None},
        }
    return {
        "cycle_id": "pu_1", "issue_types": [issue_type],
        "issue_severity": "blocking",
        "version_a": rev, "version_b": orig, "which_is_original": "b",
        "detection": {"original_has_flaw": None},
        "revision_gain": {"preference": None, "confidence": None},
    }


# ---- Revision Gain prompt：隐藏原文身份，不展示 issue ----


def test_revision_prompt_hides_original_and_issues():
    p = BlindEvalUnit().build_revision_gain_prompt(_entry(which="b"))
    assert "版本 A" in p and "版本 B" in p
    assert "修订更顺" in p and "原文不错" in p
    # 不透露哪个是原文 / 不展示 issue
    assert "which_is_original" not in p
    assert "redundancy" not in p
    assert "issue" not in p
    # 提示语不引导判断哪个是修改版（只让 Judge 凭文本质量判断）
    assert "修改版" not in p and "修订版" not in p and "原稿" not in p


def test_revision_prompt_presents_abstain_options():
    p = BlindEvalUnit().build_revision_gain_prompt(_entry())
    assert "no_difference" in p
    assert "uncertain" in p


def test_parse_revision_gain_valid():
    r = BlindEvalUnit().parse_revision_gain(
        json.dumps({"preference": "version_b", "confidence": 0.8})
    )
    assert r == {"preference": "version_b", "confidence": 0.8}


def test_parse_revision_gain_rejects_invalid_preference():
    with pytest.raises(ValueError):
        BlindEvalUnit().parse_revision_gain(json.dumps({"preference": "both"}))


def test_parse_revision_gain_default_confidence():
    r = BlindEvalUnit().parse_revision_gain(json.dumps({"preference": "no_difference"}))
    assert r["confidence"] == 0.5


# ---- Detection prompt：只呈现原文 + issue_type ----


def test_detection_prompt_only_original_and_type():
    p = BlindEvalUnit().build_detection_prompt(_entry(which="a"))
    assert "redundancy" in p
    assert "原文不错" in p
    assert "修订更顺" not in p  # 不展示 revision
    assert "同章对白重复" not in p  # 不展示 issue 描述


def test_parse_detection_valid():
    r = BlindEvalUnit().parse_detection(json.dumps({"flaw_present": True}))
    assert r["flaw_present"] is True


def test_parse_detection_uncertain():
    r = BlindEvalUnit().parse_detection(json.dumps({"flaw_present": "uncertain"}))
    assert r["flaw_present"] == "uncertain"


def test_parse_detection_rejects_invalid():
    with pytest.raises(ValueError):
        BlindEvalUnit().parse_detection(json.dumps({"flaw_present": "maybe"}))


# ---- Judge 写回 ----


def test_run_revision_gain_records_preference():
    def fake_judge(prompt: str) -> str:
        return json.dumps({"preference": "no_difference", "confidence": 0.6})

    entries = [_entry(which="a"), _entry(which="b")]
    run_revision_gain(entries, fake_judge)
    assert all(e["revision_gain"]["preference"] == "no_difference" for e in entries)


def test_run_detection_records_flaw():
    def fake_judge(prompt: str) -> str:
        return json.dumps({"flaw_present": True})

    entries = [_entry()]
    run_detection(entries, fake_judge)
    assert entries[0]["detection"]["original_has_flaw"] is True


# ---- 分层统计 + Wilson CI + net rate + abstain ----


def test_summarize_respects_which_is_original():
    """preference 是 version_b，但 which_is_original 决定 better/worse."""
    # A 版是原文，Judge 偏好 version_b → 修订赢
    entries = [
        {**_entry(which="a"), "revision_gain": {"preference": "version_b", "confidence": 0.8}},
        {**_entry(which="b"), "revision_gain": {"preference": "version_a", "confidence": 0.8}},
        {**_entry(which="a"), "revision_gain": {"preference": "version_a", "confidence": 0.7}},
    ]
    s = summarize(entries)["overall"]
    assert s["better"] == 2
    assert s["worse"] == 1
    assert s["n"] == 3
    assert s["net_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert s["better_rate"] == pytest.approx(0.6667, abs=0.0001)


def test_summarize_counts_abstain_separately():
    """no_difference / uncertain 不计入 better_rate（Abstain 是合法结果）."""
    entries = [
        {**_entry(), "revision_gain": {"preference": "no_difference", "confidence": 0.9}},
        {**_entry(), "revision_gain": {"preference": "uncertain", "confidence": 0.5}},
        {**_entry(which="b"), "revision_gain": {"preference": "version_a", "confidence": 0.8}},
    ]
    s = summarize(entries)["overall"]
    assert s["better"] == 1
    assert s["no_diff"] == 1
    assert s["uncertain"] == 1
    assert s["better_rate"] == pytest.approx(1.0, abs=0.001)  # 只在有判断的样本上


def test_summarize_by_issue_type_stratifies():
    entries = [
        {**_entry(issue_type="redundancy", which="a"), "revision_gain": {"preference": "version_b"}},
        {**_entry(issue_type="redundancy", which="a"), "revision_gain": {"preference": "version_b"}},
        {**_entry(issue_type="interpretive_space", which="a"), "revision_gain": {"preference": "version_a"}},
        {**_entry(issue_type="interpretive_space", which="a"), "revision_gain": {"preference": "no_difference"}},
    ]
    s = summarize(entries)["by_issue_type"]
    assert s["redundancy"]["better"] == 2 and s["redundancy"]["worse"] == 0
    assert s["interpretive_space"]["better"] == 0 and s["interpretive_space"]["worse"] == 1
    assert s["interpretive_space"]["net_rate"] == pytest.approx(-0.5)
    # 混合不混成单一胜率——分层可见
    assert s["redundancy"]["better_rate"] != s["interpretive_space"]["better_rate"]


def test_summarize_wilson_ci_well_formed():
    entries = [
        {**_entry(which="a"), "revision_gain": {"preference": "version_b"}}
        for _ in range(8)
    ] + [
        {**_entry(which="a"), "revision_gain": {"preference": "version_a"}}
        for _ in range(2)
    ]
    s = summarize(entries)["overall"]
    lo, hi = s["better_rate_ci"]
    assert 0.0 < lo < hi <= 1.0
    assert lo <= s["better_rate"] <= hi


def test_summarize_detection_precision():
    entries = [
        {**_entry(), "detection": {"original_has_flaw": True}},
        {**_entry(), "detection": {"original_has_flaw": True}},
        {**_entry(), "detection": {"original_has_flaw": False}},
        {**_entry(), "detection": {"original_has_flaw": "uncertain"}},
    ]
    s = summarize(entries)["overall"]
    assert s["detection_n"] == 3
    assert s["detection_precision"] == pytest.approx(0.6667, abs=0.0001)
