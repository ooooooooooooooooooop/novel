"""ChoiceRecord / ChoiceLedgerEntry schema tests — 作者性 2B.

验证：必须保存被拒候选（禁止 4）；tradeoff 必填；hindsight 五态；
全字段 extra=forbid；JSON-safe round-trip。
"""

import pytest
from pydantic import ValidationError

from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)


def _pu(candidate_id: str, summary: str, state_ref: str = "ns_out") -> dict:
    return {
        "unit_id": f"pu_{candidate_id}",
        "level": "scene",
        "goal": "推进局势",
        "participants": ["c001"],
        "conflict": "核心冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": state_ref,
        "consequences": ["后果"],
        "is_effective": True,
    }


def _candidate(candidate_id: str, summary: str) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=candidate_id,
        summary=summary,
        plotunit=_pu(candidate_id, summary),
        new_state_ref="ns_out",
    )


def _record(**overrides) -> ChoiceRecord:
    base = dict(
        decision_id="d_001",
        decision_timestamp="2026-08-07T12:00:00",
        plot_context="主角面临坦白或隐瞒的抉择",
        state_ref="ns_in",
        character_refs=["c001"],
        style_profile_id="克制-官商-001",
        candidates=[_candidate("A", "直接摊牌"), _candidate("B", "隐瞒继续调查")],
        selected_candidate="B",
        rejected=[RejectedRecord(candidate_id="A", reason="A 更戏剧化但人物当前不会这样")],
        tradeoff="放弃 A 的直接摊牌爽感，换取 B 的长期人物因果一致性",
        value_conflicts=["character_causality_over_plot_convenience"],
    )
    base.update(overrides)
    return ChoiceRecord(**base)


def test_record_roundtrip_preserves_rejected():
    rec = _record()
    assert rec.selected_candidate == "B"
    assert [r.candidate_id for r in rec.rejected] == ["A"]
    assert len(rec.candidates) == 2


def test_record_requires_tradeoff():
    with pytest.raises(ValidationError):
        _record(tradeoff="")


def test_record_extra_forbid():
    with pytest.raises(ValidationError):
        _record(bogus_key=True)


def test_hindsight_five_states():
    for state in ("still_supported", "partial_regret", "overturned", "complex", "unclear"):
        rec = _record(hindsight=state)
        assert rec.hindsight == state
    with pytest.raises(ValidationError):
        _record(hindsight="maybe")


def test_consequence_and_hindsight_optional():
    rec = _record()
    assert rec.consequence is None
    assert rec.hindsight is None
    assert rec.hindsight_note is None


def test_blank_fields_rejected():
    with pytest.raises(ValidationError):
        _record(plot_context="  ")
    with pytest.raises(ValidationError):
        _record(tradeoff="   ")


def test_character_refs_must_be_non_blank():
    with pytest.raises(ValidationError):
        _record(character_refs=[""])


def test_candidate_requires_plotunit_dict():
    with pytest.raises(ValidationError):
        CandidateRecord(candidate_id="A", summary="x", plotunit=[], new_state_ref="ns")


def test_ledger_entry_accumulates():
    entry = ChoiceLedgerEntry(choices=[_record()])
    entry.choices.append(_record(decision_id="d_002"))
    assert len(entry.choices) == 2


def test_ledger_entry_default_empty():
    entry = ChoiceLedgerEntry()
    assert entry.choices == []
    assert entry.schema_version == 1


def test_ledger_json_roundtrip(tmp_path):
    entry = ChoiceLedgerEntry(choices=[_record()])
    path = tmp_path / "choice_ledger.json"
    path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
    loaded = ChoiceLedgerEntry.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.choices[0].decision_id == "d_001"
    assert loaded.choices[0].rejected[0].candidate_id == "A"


def test_record_missing_required_fields():
    with pytest.raises(ValidationError):
        ChoiceRecord(decision_id="d_x")  # 缺 tradeoff/plot_context/state_ref/...


def test_rejected_extra_forbid():
    with pytest.raises(ValidationError):
        RejectedRecord(candidate_id="A", reason="x", why_else=True)
