"""测试 ReconcileUnit.check_temporal_contradictions (FACTTRACK 时间矛盾检测)."""

from src.object_state import (
    FactEntry,
    FactLedger,
    ReviewIssue,
    ValidityInterval,
)
from src.workflow_action.reconcile import ReconcileUnit


def _ledger(*entries: FactEntry) -> FactLedger:
    return FactLedger(entries=list(entries))


def test_death_after_still_active_detected():
    death = FactEntry(
        fact_id="f_death",
        statement="c001 陨落",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )
    alive = FactEntry(
        fact_id="f_alive",
        statement="c001 活跃",
        fact_type="relation",
        involved_entities=["c001"],
        timestamp="第五章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(death, alive)])

    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, ReviewIssue)
    assert issue.issue_type == "timeline_error"
    assert issue.severity == "blocking"


def test_death_before_activity_no_issue():
    death = FactEntry(
        fact_id="f_death",
        statement="c001 陨落",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )
    alive = FactEntry(
        fact_id="f_alive",
        statement="c001 活跃",
        fact_type="relation",
        involved_entities=["c001"],
        timestamp="第一章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(death, alive)])

    assert issues == []


def test_death_unparseable_time_no_false_positive():
    # 时间不可比时保守不报 (避免误报)
    death = FactEntry(
        fact_id="f_death",
        statement="c001 陨落",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="某年某月",
    )
    alive = FactEntry(
        fact_id="f_alive",
        statement="c001 活跃",
        fact_type="relation",
        involved_entities=["c001"],
        timestamp="另一些时候",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(death, alive)])

    assert issues == []


def test_expired_fact_still_held_detected():
    expired = FactEntry(
        fact_id="f_item",
        statement="令牌归 c001 所有",
        fact_type="object",
        involved_entities=["c001", "tok_1"],
        validity_interval=ValidityInterval(valid_until="第五章"),
    )
    still_held = FactEntry(
        fact_id="f_hold",
        statement="c001 持有令牌",
        fact_type="relation",
        involved_entities=["c001", "tok_1"],
        timestamp="第七章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(expired, still_held)])

    assert len(issues) == 1
    assert issues[0].issue_type == "timeline_error"
    assert issues[0].severity == "warning"


def test_expired_fact_no_still_held_contradiction():
    expired = FactEntry(
        fact_id="f_item",
        statement="令牌归 c001 所有",
        fact_type="object",
        involved_entities=["c001", "tok_1"],
        validity_interval=ValidityInterval(valid_until="第五章"),
    )
    # 无持有/归属/位于 当前状态事实 → 不报
    unrelated = FactEntry(
        fact_id="f_other",
        statement="c001 前往秘境",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第七章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(expired, unrelated)])

    assert issues == []


def test_overlapping_negation_detected():
    positive = FactEntry(
        fact_id="f_pos",
        statement="c001 在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )
    negative = FactEntry(
        fact_id="f_neg",
        statement="c001 不在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(positive, negative)])

    assert len(issues) == 1
    assert issues[0].issue_type == "timeline_error"
    assert issues[0].severity == "blocking"


def test_non_overlapping_negation_no_issue():
    # 先在山门(第三章), 后不在山门(第五章) → 不矛盾
    positive = FactEntry(
        fact_id="f_pos",
        statement="c001 在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )
    negative = FactEntry(
        fact_id="f_neg",
        statement="c001 不在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第五章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(positive, negative)])

    assert issues == []


def test_overlapping_negation_with_validity_intervals():
    positive = FactEntry(
        fact_id="f_pos",
        statement="c001 在山门",
        fact_type="event",
        involved_entities=["c001"],
        validity_interval=ValidityInterval(
            valid_from="第二章", valid_until="第四章"
        ),
    )
    negative = FactEntry(
        fact_id="f_neg",
        statement="c001 不在山门",
        fact_type="event",
        involved_entities=["c001"],
        validity_interval=ValidityInterval(
            valid_from="第三章", valid_until="第五章"
        ),
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(positive, negative)])

    assert len(issues) == 1
    assert "iss_temp_neg_" in issues[0].issue_id


def test_disjoint_validity_intervals_no_issue():
    positive = FactEntry(
        fact_id="f_pos",
        statement="c001 在山门",
        fact_type="event",
        involved_entities=["c001"],
        validity_interval=ValidityInterval(
            valid_from="第二章", valid_until="第三章"
        ),
    )
    negative = FactEntry(
        fact_id="f_neg",
        statement="c001 不在山门",
        fact_type="event",
        involved_entities=["c001"],
        validity_interval=ValidityInterval(
            valid_from="第五章", valid_until="第六章"
        ),
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(positive, negative)])

    assert issues == []


def test_no_ledger_returns_empty():
    unit = ReconcileUnit()
    assert unit.check_temporal_contradictions([]) == []
    assert unit.check_temporal_contradictions([object()]) == []


def test_issues_are_review_issues_with_location():
    positive = FactEntry(
        fact_id="f_pos",
        statement="c001 在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )
    negative = FactEntry(
        fact_id="f_neg",
        statement="c001 不在山门",
        fact_type="event",
        involved_entities=["c001"],
        timestamp="第三章",
    )

    unit = ReconcileUnit()
    issues = unit.check_temporal_contradictions([_ledger(positive, negative)])

    assert issues[0].scope_of_impact == "时间线一致性"
    assert issues[0].violated_rule == "同一时间区间内事实不得互相否定"
    assert "FactLedger" in issues[0].location


def test_narrative_position_helpers():
    from src.workflow_action.reconcile import (
        _narrative_position,
        _position_after,
    )

    assert _narrative_position("第三章") == 3
    assert _narrative_position("第3章") == 3
    assert _narrative_position("第 12 回") == 12
    assert _narrative_position("5") == 5
    assert _narrative_position("某年") is None
    assert _narrative_position(None) is None

    assert _position_after("第五章", "第三章") is True
    assert _position_after("第三章", "第五章") is False
    assert _position_after("某年", "第三章") is None
