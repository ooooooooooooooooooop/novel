"""LongHorizonUnit 测试（design §9 / T7.1–T7.2）.

正文重建摘要 / 滚动摘要对账 / 漂移判定 / 首个检查点基线 / 持久化.
"""

from pathlib import Path

import pytest

from src.object_state.longhorizon import (
    LongHorizonCheckpoint,
    ProseSummary,
    RollingLongHorizonSummary,
)
from src.workflow_action.long_horizon import (
    DEFAULT_DRIFT_THRESHOLD,
    build_rolling_from_plan,
    detect_drift,
    evaluate_long_horizon_checkpoint,
    load_rolling_summary,
    reconcile,
    save_rolling_summary,
    summarize_prose,
)


def _prose_with_promise() -> list[str]:
    return [
        "第一章。神秘来信在桌上。主角拆开了信。",
        "第二章。主角前往案发现场调查。",
    ]


def _prose_without_promise() -> list[str]:
    return ["第一章。主角在街角等雨。", "第二章。主角回屋煮茶。"]


def test_summarize_prose_counts_labels_and_promise_tokens():
    summary = summarize_prose(
        _prose_with_promise(),
        labels={"c001": ["主角"]},
        promise_tokens={"rem_001": "神秘来信"},
        structural_nodes=["opening"],
    )
    assert summary.chapter_count == 2
    assert summary.character_mentions["c001"] == 2
    assert summary.promise_mentions["rem_001"] == 1
    assert summary.structural_nodes == ["opening"]


def test_summarize_prose_omits_zero_mention_labels():
    summary = summarize_prose(
        _prose_without_promise(),
        labels={"c001": ["主角"]},
        promise_tokens={"rem_001": "神秘来信"},
    )
    assert summary.character_mentions == {"c001": 2}
    assert summary.promise_mentions == {}  # 未落地承诺不计入重建


def test_build_rolling_from_plan_places_zero_counts():
    rolling = build_rolling_from_plan(
        {"rem_001": "神秘来信"}, ["c001"], structural_node="opening"
    )
    assert rolling.last_checkpoint == 0
    assert rolling.summary.promise_mentions == {"rem_001": 0}
    assert rolling.summary.character_mentions == {"c001": 0}
    assert rolling.summary.structural_nodes == ["opening"]


def test_detect_drift_blocks_on_ungrounded_open_promise():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"}, ["c001"])
    rebuilt = summarize_prose(_prose_without_promise())
    drift = detect_drift(rebuilt, rolling)
    assert drift["stale_promises"] == ["rem_001"]
    assert drift["blocking"] is True
    assert drift["drift_score"] == 1.0


def test_detect_drift_passes_when_promise_grounded():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"}, ["c001"])
    rebuilt = summarize_prose(
        _prose_with_promise(), promise_tokens={"rem_001": "神秘来信"}
    )
    drift = detect_drift(rebuilt, rolling)
    assert drift["stale_promises"] == []
    assert drift["blocking"] is False
    assert drift["drift_score"] == 0.0


def test_detect_drift_characters_are_evidence_only():
    rolling = build_rolling_from_plan({}, ["ghost"])
    rebuilt = summarize_prose(_prose_without_promise())
    drift = detect_drift(rebuilt, rolling)
    assert drift["stale_characters"] == ["ghost"]
    assert drift["blocking"] is False  # 人物漂移不参与打分


def test_evaluate_first_checkpoint_passes_and_establishes_no_block():
    result = evaluate_long_horizon_checkpoint(
        1, _prose_without_promise(), None,
        promise_tokens={"rem_001": "神秘来信"},
    )
    assert isinstance(result, LongHorizonCheckpoint)
    assert result.route == "pass"
    assert result.rebuilt_chapter_count == 2


def test_evaluate_drift_block_at_later_checkpoint():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"}, ["c001"])
    result = evaluate_long_horizon_checkpoint(
        3, _prose_without_promise(), rolling,
        promise_tokens={"rem_001": "神秘来信"},
    )
    assert result.route == "block"
    assert result.stale_promises == ["rem_001"]
    assert result.drift_score > DEFAULT_DRIFT_THRESHOLD
    assert "long-horizon drift" in result.reason


def test_evaluate_pass_when_grounded_at_later_checkpoint():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"}, ["c001"])
    result = evaluate_long_horizon_checkpoint(
        3, _prose_with_promise(), rolling,
        promise_tokens={"rem_001": "神秘来信"},
    )
    assert result.route == "pass"
    assert result.stale_promises == []


def test_reconcile_merges_grounded_and_still_open_promises():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信", "rem_002": "未落线索"})
    rebuilt = summarize_prose(
        _prose_with_promise(), promise_tokens={"rem_001": "神秘来信"}
    )
    merged = reconcile(
        rolling, rebuilt, checkpoint=5,
        open_promises={"rem_001": "神秘来信", "rem_002": "未落线索"},
        active_characters=["c001"],
    )
    assert merged.last_checkpoint == 5
    assert merged.summary.promise_mentions["rem_001"] == 1  # 落地
    assert merged.summary.promise_mentions["rem_002"] == 0  # 仍开放占位
    assert merged.summary.chapter_count == 2


def test_reconcile_drops_closed_promises():
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"})
    rebuilt = summarize_prose(_prose_with_promise(), promise_tokens={"rem_001": "神秘来信"})
    merged = reconcile(rolling, rebuilt, checkpoint=5, open_promises={})
    assert "rem_001" not in merged.summary.promise_mentions  # 已关闭不继承


def test_save_and_load_rolling_summary_roundtrip(tmp_path):
    rolling = build_rolling_from_plan({"rem_001": "神秘来信"}, ["c001"])
    path = save_rolling_summary(tmp_path, rolling)
    assert path.name == "rolling_summary.json"
    assert path.parent.name == "gates"
    loaded = load_rolling_summary(tmp_path)
    assert loaded is not None
    assert loaded.summary.promise_mentions == {"rem_001": 0}
    assert loaded.model_dump() == rolling.model_dump()


def test_load_rolling_summary_missing_returns_none(tmp_path):
    assert load_rolling_summary(tmp_path / "nope") is None


def test_checkpoint_object_validates_shape():
    result = LongHorizonCheckpoint(
        checkpoint=5,
        route="pass",
        drift_score=0.0,
        drift_threshold=0.5,
        stale_promises=[],
        stale_characters=["ghost"],
        rebuilt_chapter_count=5,
        rolling_chapter_count=3,
        reason="reconciled",
    )
    assert result.route == "pass"
    with pytest.raises(Exception):
        LongHorizonCheckpoint(
            checkpoint=5,
            route="mystery",
            drift_score=0.0,
            drift_threshold=0.5,
            stale_promises=[],
            stale_characters=[],
            rebuilt_chapter_count=5,
            rolling_chapter_count=3,
            reason="x",
        )


def test_prose_summary_object_validates_extra_forbidden():
    with pytest.raises(Exception):
        ProseSummary(
            chapter_count=1,
            character_mentions={},
            promise_mentions={},
            structural_nodes=[],
            unexpected=True,
        )
