"""Hindsight Reconciliation tests — 作者性闭环 Gate 1.

验证：开放性选择判定（滞后/已回填/无章号）；prompt 只含选择+证据、不含预期；
解析严格；两遍式回填写入 ChoiceLedger 的 consequence/hindsight；无证据 no-op。
"""

import json

import pytest

from src.object_state.choicerecord import ChoiceRecord
from src.workflow_action.hindsight import (
    build_hindsight_prompt,
    open_choices,
    parse_hindsight_response,
    reconcile_hindsight,
)


def _choice(decision_id: str, chapter_number: int, consequence=None) -> ChoiceRecord:
    return ChoiceRecord(
        decision_id=decision_id,
        decision_timestamp="2026-08-09T00:00:00",
        plot_context="场景局势",
        state_ref="ns_in",
        chapter_number=chapter_number,
        candidates=[
            {
                "candidate_id": "A",
                "summary": "摊牌",
                "plotunit": {
                    "unit_id": "pu_x",
                    "level": "scene",
                    "goal": "直接摊牌",
                    "conflict": "旧伤未愈",
                    "input_state_ref": "ns_in",
                    "output_state_ref": "ns_out",
                    "consequences": [],
                    "released_information": [],
                    "is_effective": True,
                },
                "new_state_ref": "ns_out",
            },
            {
                "candidate_id": "B",
                "summary": "隐瞒",
                "plotunit": {
                    "unit_id": "pu_y",
                    "level": "scene",
                    "goal": "继续隐瞒",
                    "conflict": "信息权限",
                    "input_state_ref": "ns_in",
                    "output_state_ref": "ns_out",
                    "consequences": [],
                    "released_information": [],
                    "is_effective": True,
                },
                "new_state_ref": "ns_out",
            },
        ],
        selected_candidate="A",
        rejected=[{"candidate_id": "B", "reason": "会提前兑现冲突"}],
        tradeoff="放弃即时戏剧性换取人物长期因果",
        value_conflicts=["character_causality_over_plot_convenience"],
        consequence=consequence,
    )


def test_open_choices_lag_and_already_filled():
    from src.object_state.choicerecord import ChoiceLedgerEntry

    c1 = _choice("d_01", 1)               # 滞后满足（当前 5 → 1<=3）
    c2 = _choice("d_02", 4)               # 滞后不足（4 > 5-2=3）
    c3 = _choice("d_03", 2, consequence="已回填")
    c4 = _choice("d_04", None)            # 无章号
    ledger = ChoiceLedgerEntry(choices=[c1, c2, c3, c4])
    opened = open_choices(ledger, current_chapter=5)
    assert [c.decision_id for c in opened] == ["d_01"]


def test_build_prompt_has_evidence_not_expected_direction():
    choices = [_choice("d_01", 1)]
    prompt = build_hindsight_prompt(choices, [(2, "他选择了沉默，旧伤没有解开"), (3, "关系彻底破裂")])
    assert "d_01" in prompt
    assert "第2章" in prompt or "第2章" in prompt
    assert "他选择了沉默" in prompt  # 证据在
    assert "预期" not in prompt  # 不给预期方向
    assert "actually" not in prompt


def test_parse_hindsight_response_strict():
    resp = json.dumps(
        [
            {"decision_id": "d_01", "consequence": "关系破裂", "hindsight": "overturned", "note": "代价被低估"},
        ],
        ensure_ascii=False,
    )
    parsed = parse_hindsight_response(resp)
    assert parsed[0]["hindsight"] == "overturned"
    assert parsed[0]["note"]

    with pytest.raises(ValueError, match="unexpected field"):
        parse_hindsight_response(json.dumps([{"decision_id": "d_01", "consequence": "x", "hindsight": "unclear", "junk": 1}], ensure_ascii=False))
    with pytest.raises(ValueError, match="must be one of"):
        parse_hindsight_response(json.dumps([{"decision_id": "d_01", "consequence": "x", "hindsight": "maybe"}], ensure_ascii=False))


def test_reconcile_two_phase_roundtrip(tmp_path):
    from src.object_state.choicerecord import ChoiceLedgerEntry
    from src.workflow_action.choiceledger import _ledger_path, load_choice_ledger

    output_dir = tmp_path / "output"
    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir()
    (chapters_dir / "chapter_3.txt").write_text("他最终没有摊牌，旧伤在沉默里化脓。", encoding="utf-8")

    ledger = ChoiceLedgerEntry(choices=[_choice("d_01", 1)])
    _ledger_path(output_dir).parent.mkdir(parents=True, exist_ok=True)
    _ledger_path(output_dir).write_text(ledger.model_dump_json(indent=2), encoding="utf-8")

    # 第一遍：prompt
    r1 = reconcile_hindsight(output_dir, chapters_dir)
    assert r1["status"] == "prompt"
    assert (output_dir / "hindsight" / "hindsight_prompt.txt").exists()

    # 填响应
    resp = json.dumps(
        [{"decision_id": "d_01", "consequence": "没有摊牌，关系在沉默里僵死", "hindsight": "partial_regret", "note": "保守了"}],
        ensure_ascii=False,
    )
    (output_dir / "hindsight" / "hindsight_response.txt").write_text(resp, encoding="utf-8")

    # 第二遍：回填
    r2 = reconcile_hindsight(output_dir, chapters_dir)
    assert r2["status"] == "done"
    assert r2["updated"] == 1

    loaded = load_choice_ledger(output_dir)
    c = loaded.choices[0]
    assert c.consequence == "没有摊牌，关系在沉默里僵死"
    assert c.hindsight == "partial_regret"
    assert c.hindsight_note == "保守了"


def test_reconcile_noop_when_no_open(tmp_path):
    from src.object_state.choicerecord import ChoiceLedgerEntry
    from src.workflow_action.choiceledger import _ledger_path

    output_dir = tmp_path / "output"
    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir()
    ledger = ChoiceLedgerEntry(choices=[_choice("d_01", 1, consequence="已填")])
    _ledger_path(output_dir).parent.mkdir(parents=True, exist_ok=True)
    _ledger_path(output_dir).write_text(ledger.model_dump_json(indent=2), encoding="utf-8")

    r = reconcile_hindsight(output_dir, chapters_dir)
    assert r["status"] == "noop"


def test_reconcile_missing_decision_id_rejected(tmp_path):
    from src.object_state.choicerecord import ChoiceLedgerEntry
    from src.workflow_action.choiceledger import _ledger_path

    output_dir = tmp_path / "output"
    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir()
    (chapters_dir / "chapter_3.txt").write_text("证据", encoding="utf-8")
    ledger = ChoiceLedgerEntry(choices=[_choice("d_01", 1)])
    _ledger_path(output_dir).parent.mkdir(parents=True, exist_ok=True)
    _ledger_path(output_dir).write_text(ledger.model_dump_json(indent=2), encoding="utf-8")

    reconcile_hindsight(output_dir, chapters_dir)  # prompt 阶段
    resp = json.dumps([{"decision_id": "WRONG", "consequence": "x", "hindsight": "unclear"}], ensure_ascii=False)
    (output_dir / "hindsight" / "hindsight_response.txt").write_text(resp, encoding="utf-8")
    with pytest.raises(ValueError, match="missing decision_id"):
        reconcile_hindsight(output_dir, chapters_dir)
