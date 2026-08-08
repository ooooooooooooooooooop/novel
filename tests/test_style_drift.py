"""Style Drift 测量 tests（measurement-only，不自动纠正）.

覆盖：
- measure_text：表层（句长/段长/对白/破折号）与 AI 化指标（他意识到/身体反应/
  不是而是/解释性收尾）每千字密度。
- drift_report：baseline（人类原文）vs 各 AI 章，逐章 delta。
- compare_draft_committed：Draft vs Committed，检测 Review 是否在制造 homogenization。
"""

import pytest

from src.experiment.style_drift import compare_draft_committed, drift_report, measure_text


def test_measure_text_surface_metrics():
    text = (
        "第一章 测试。\n"
        "他推开门，屋里的光线斜斜落在桌上。杯子里剩下半口冷水。\n"
        "「你来了。」他说。\n"
        "他忽然明白，这件事没有那么简单。"
    )
    m = measure_text(text)
    assert "empty" not in m
    assert m["surface"]["sentence_count"] >= 3
    assert m["surface"]["dialogue_ratio"] > 0
    assert m["surface"]["dash_ellipsis_per_1k"] >= 0
    assert m["ai"]["realization_per_1k"] > 0  # 『忽然明白』被检出


def test_measure_text_empty():
    assert measure_text("")["empty"] is True
    assert measure_text("   \n ")["empty"] is True


def test_measure_text_ai_realization_density():
    ai_text = (
        "他忽然明白了一切。他意识到这不是偶然。他终于明白，命运早已注定。"
        "他意识到，自己一直在等这一刻。"
    )
    human_text = "他站了很久，才转身。风从门缝里灌进来。"
    assert measure_text(ai_text)["ai"]["realization_per_1k"] > measure_text(human_text)["ai"]["realization_per_1k"]


def test_measure_text_body_reaction_density():
    ai_text = "他攥紧拳头，冷汗顺着脊背淌下来，心口一滞，指尖发白。他咬牙，瞳孔微缩。"
    human_text = "他放下杯子，望向窗外。"
    assert measure_text(ai_text)["ai"]["body_reaction_per_1k"] > measure_text(human_text)["ai"]["body_reaction_per_1k"]


def test_drift_report_compares_chapters_to_baseline():
    baseline = "他放下杯子，望向窗外。风从门缝里灌进来。"
    ch1 = baseline + "他忽然明白，这件事不简单。他意识到自己该走了。"
    ch2 = baseline + "他忽然明白一切。他意识到这是宿命。他终于明白，没有别的路。"
    report = drift_report([("ch1", ch1), ("ch2", ch2)], baseline)
    assert report["baseline"]["surface"]["sentence_count"] > 0
    assert len(report["chapters"]) == 2
    # AI 章比 baseline 更『他意识到/明白』（AI 化 drift 信号上升）
    d1 = report["chapters"][0]["delta"]["realization_per_1k"]
    d2 = report["chapters"][1]["delta"]["realization_per_1k"]
    assert d1 > 0 and d2 > d1


def test_compare_draft_committed_detects_homogenization():
    """Draft 有变化，Committed 更统一 → homogenization 信号为正."""
    draft = (
        "他推开门，屋里的光线斜斜落在桌上。杯子剩下半口冷水。\n"
        "窗缝里有风，纸被掀起一角，又落下。\n"
        "「你来了。」他说，声音哑。\n"
        "他站了很久，没有动。\n"
        "外头的雨，下得正好。"
    )
    committed = (
        "他推开门，屋里的光线斜斜落在桌上。\n"
        "他忽然明白，这件事并不简单。\n"
        "他意识到自己不能再等了。\n"
        "他咬牙，攥紧拳头。"
    )
    r = compare_draft_committed(draft, committed)
    assert r["draft"]["surface"]["dialogue_ratio"] > r["committed"]["surface"]["dialogue_ratio"]
    # Committed 的 AI 化信号比 Draft 高（realization / body reaction 上升）
    assert r["homogenization_signals"]["realization_delta"] > 0
    assert r["homogenization_signals"]["body_reaction_delta"] > 0


def test_compare_draft_committed_no_signal_when_similar():
    text = "他放下杯子，望向窗外。风从门缝里灌进来。"
    r = compare_draft_committed(text, text)
    assert r["committed"] == r["draft"]
