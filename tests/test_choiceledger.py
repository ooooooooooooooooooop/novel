"""ChoiceLedger workflow tests — 作者性 2B.

验证：append 幂等（重复 decision_id 拒绝）；hindsight/consequence 滞后补写；
台账 JSON round-trip；缺失台账返回空骨架；损坏台账抛错。
"""

import json

import pytest

from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    RejectedRecord,
)
from src.workflow_action.choiceledger import (
    LEDGER_FILE,
    append_choice_record,
    choice_records,
    get_choice,
    load_choice_ledger,
    record_consequence,
    record_hindsight,
)


def _pu(candidate_id: str) -> dict:
    return {
        "unit_id": f"pu_{candidate_id}",
        "level": "scene",
        "goal": "推进局势",
        "participants": ["c001"],
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": ["后果"],
        "is_effective": True,
    }


def _record(decision_id: str = "d_001", **overrides) -> ChoiceRecord:
    base = dict(
        decision_id=decision_id,
        decision_timestamp="2026-08-07T12:00:00",
        plot_context="主角面临坦白或隐瞒",
        state_ref="ns_in",
        character_refs=["c001"],
        candidates=[
            CandidateRecord(candidate_id="A", summary="直接摊牌", plotunit=_pu("A"), new_state_ref="ns_out"),
            CandidateRecord(candidate_id="B", summary="隐瞒调查", plotunit=_pu("B"), new_state_ref="ns_out"),
        ],
        selected_candidate="B",
        rejected=[RejectedRecord(candidate_id="A", reason="人物当前不会这样")],
        tradeoff="放弃 A 的摊牌爽感，换取 B 的人物因果",
        value_conflicts=["character_causality_over_plot_convenience"],
    )
    base.update(overrides)
    return ChoiceRecord(**base)


def test_append_and_load(tmp_path):
    append_choice_record(tmp_path, _record())
    ledger = load_choice_ledger(tmp_path)
    assert len(ledger.choices) == 1
    assert ledger.choices[0].decision_id == "d_001"
    assert (tmp_path / LEDGER_FILE).exists()


def test_missing_ledger_returns_empty(tmp_path):
    ledger = load_choice_ledger(tmp_path)
    assert ledger.choices == []


def test_corrupt_ledger_raises(tmp_path):
    (tmp_path / LEDGER_FILE).write_text("{broken json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_choice_ledger(tmp_path)


def test_duplicate_decision_id_rejected(tmp_path):
    append_choice_record(tmp_path, _record("d_001"))
    with pytest.raises(ValueError):
        append_choice_record(tmp_path, _record("d_001"))


def test_accumulate_records(tmp_path):
    for i in range(3):
        append_choice_record(tmp_path, _record(f"d_{i:03d}"))
    ledger = load_choice_ledger(tmp_path)
    assert len(choice_records(ledger)) == 3


def test_hindsight_backfill(tmp_path):
    append_choice_record(tmp_path, _record("d_001"))
    ok = record_hindsight(tmp_path, "d_001", "partial_regret", note="代价被低估")
    assert ok is True
    ledger = load_choice_ledger(tmp_path)
    assert ledger.choices[0].hindsight == "partial_regret"
    assert ledger.choices[0].hindsight_note == "代价被低估"


def test_hindsight_missing_decision_is_false(tmp_path):
    append_choice_record(tmp_path, _record("d_001"))
    assert record_hindsight(tmp_path, "d_999", "overturned") is False


def test_consequence_backfill(tmp_path):
    append_choice_record(tmp_path, _record("d_001"))
    ok = record_consequence(tmp_path, "d_001", "三章后关系彻底破裂")
    assert ok is True
    assert load_choice_ledger(tmp_path).choices[0].consequence == "三章后关系彻底破裂"


def test_get_choice(tmp_path):
    append_choice_record(tmp_path, _record("d_001"))
    ledger = load_choice_ledger(tmp_path)
    assert get_choice(ledger, "d_001").selected_candidate == "B"
    assert get_choice(ledger, "d_999") is None


def test_ledger_json_is_valid_json(tmp_path):
    append_choice_record(tmp_path, _record())
    raw = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert len(raw["choices"]) == 1
