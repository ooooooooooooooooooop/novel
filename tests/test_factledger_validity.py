"""测试 FactLedger 时间有效性字段 (ValidityInterval / validity_interval)."""

import pytest

from src.object_state import FactEntry, FactLedger, ValidityInterval


def test_validity_interval_default_none_means_always_valid():
    entry = FactEntry(
        fact_id="f1", statement="令牌归c001所有", fact_type="relation"
    )
    assert entry.validity_interval is None


def test_validity_interval_with_both_bounds():
    entry = FactEntry(
        fact_id="f1",
        statement="令牌归c001所有",
        fact_type="relation",
        validity_interval=ValidityInterval(
            valid_from="第三章", valid_until="第五章"
        ),
    )
    assert entry.validity_interval.valid_from == "第三章"
    assert entry.validity_interval.valid_until == "第五章"


def test_validity_interval_open_ended_bounds():
    # 只设起点 = 开放终点
    interval = ValidityInterval(valid_from="第一章")
    assert interval.valid_from == "第一章"
    assert interval.valid_until is None
    # 只设终点 = 开放起点
    interval2 = ValidityInterval(valid_until="第七章")
    assert interval2.valid_from is None
    assert interval2.valid_until == "第七章"


def test_validity_interval_rejects_blank_bound():
    with pytest.raises(ValueError):
        ValidityInterval(valid_from="  ")


def test_validity_interval_rejects_extra_fields():
    with pytest.raises(ValueError):
        ValidityInterval(valid_from="第三章", invalid="x")  # type: ignore


def test_to_prompt_suffix_both_bounds():
    interval = ValidityInterval(valid_from="第三章", valid_until="第五章")
    assert interval.to_prompt_suffix() == "(第三章~第五章)"


def test_to_prompt_suffix_open_from():
    interval = ValidityInterval(valid_until="第五章")
    assert interval.to_prompt_suffix() == "(~第五章)"


def test_to_prompt_suffix_open_until():
    interval = ValidityInterval(valid_from="第三章")
    assert interval.to_prompt_suffix() == "(第三章~)"


def test_to_prompt_suffix_none_returns_empty():
    interval = ValidityInterval()
    assert interval.to_prompt_suffix() == ""


def test_to_prompt_line_with_validity():
    entry = FactEntry(
        fact_id="f1",
        statement="令牌归c001所有",
        fact_type="relation",
        confirmed=True,
        validity_interval=ValidityInterval(
            valid_from="第三章", valid_until="第五章"
        ),
    )
    assert entry.to_prompt_line() == "✓ [relation](第三章~第五章) 令牌归c001所有"


def test_to_prompt_line_without_validity_unchanged():
    entry = FactEntry(
        fact_id="f1",
        statement="令牌归c001所有",
        fact_type="relation",
        confirmed=True,
    )
    assert entry.to_prompt_line() == "✓ [relation] 令牌归c001所有"


def test_fact_ledger_add_with_validity():
    ledger = FactLedger()
    ledger.add_fact(
        FactEntry(
            fact_id="f1",
            statement="主角加入宗门",
            fact_type="event",
            validity_interval=ValidityInterval(valid_from="第二章"),
        )
    )
    assert ledger.entries[0].validity_interval is not None


def test_fact_entry_serializes_validity_interval():
    entry = FactEntry(
        fact_id="f1",
        statement="令牌归c001所有",
        fact_type="relation",
        validity_interval=ValidityInterval(
            valid_from="第三章", valid_until="第五章"
        ),
    )
    dumped = entry.model_dump(mode="json")
    assert dumped["validity_interval"] == {
        "valid_from": "第三章",
        "valid_until": "第五章",
    }
    # round-trip
    restored = FactEntry.model_validate(dumped)
    assert restored.validity_interval == entry.validity_interval


def test_fact_entry_old_serialized_state_round_trips():
    # 旧 state (无 validity_interval 字段) 反序列化时默认 None
    old_dump = {
        "fact_id": "f1",
        "statement": "令牌归c001所有",
        "fact_type": "relation",
        "involved_entities": [],
        "confirmed": False,
        "timestamp": None,
    }
    restored = FactEntry.model_validate(old_dump)
    assert restored.validity_interval is None
