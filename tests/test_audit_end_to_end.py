"""Audit 流端到端集成测试."""

import json

import pytest

from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    WorkSpec,
    WorldModel,
)
from src.object_state.audit_report import AuditReport


def test_audit_report_from_complete_rebuild():
    """完整重建后的 AuditReport 包含所有对象层."""
    workspec = WorkSpec(
        genre="悬疑",
        audience="青年",
        theme="真相",
        tone="克制",
        pacing="短弧推进",
    )
    worldmodel = WorldModel(world_facts=["事实"], prohibitions=["禁止"])
    char = CharacterModel(
        character_id="c001",
        name="主角",
        identity="侦探",
        outer_goal="破案",
        inner_need="正义",
        fear="失败",
        flaw="固执",
        strength="观察力",
        stance="中立",
    )
    state = NarrativeState(
        state_id="ns_001",
        current_time="夜晚",
        current_location="案发现场",
        current_situation="调查开始",
    )
    facts = FactLedger()
    foreshadows = ForeshadowGraph()

    objects = [workspec, worldmodel, char, state, facts, foreshadows]

    report = AuditReport(
        source_text_ref="input.txt",
        route="pass",
        workspec=workspec.model_dump(mode="json"),
        worldmodel=worldmodel.model_dump(mode="json"),
        characters=[char.model_dump(mode="json")],
        narrative_state=state.model_dump(mode="json"),
        fact_ledger=facts.model_dump(mode="json"),
        foreshadow_graph=foreshadows.model_dump(mode="json"),
        issues=[],
        reminders=[],
        confidence_gaps=[],
    )

    assert len(objects) == 6
    assert report.route == "pass"
    assert report.source_text_ref == "input.txt"
    assert report.workspec is not None
    assert report.workspec.genre == "悬疑"
    assert len(report.characters) == 1
    assert report.rewrite_applied is False
    assert report.original_route is None


def test_audit_report_with_rewrite_history():
    """含 rewrite 历史的 AuditReport 记录修复信息."""
    report = AuditReport(
        source_text_ref="input.txt",
        route="pass",
        original_route="rewrite",
        rewrite_applied=True,
        applied_fixes=[
            {
                "target_type": "NarrativeState",
                "field": "current_situation",
                "action": "replace",
                "new_value": "修复后局势",
            }
        ],
        issues=[],
        reminders=[],
        confidence_gaps=[],
    )

    assert report.rewrite_applied is True
    assert report.original_route == "rewrite"
    assert len(report.applied_fixes) == 1
    assert report.applied_fixes[0].field == "current_situation"


def test_audit_report_rejects_malformed_applied_fix_history():
    with pytest.raises(ValueError, match="target_type"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            original_route="rewrite",
            rewrite_applied=True,
            applied_fixes=[
                {
                    "field": "current_situation",
                    "action": "replace",
                    "new_value": "fixed",
                }
            ],
        )

    with pytest.raises(ValueError, match="action"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            original_route="rewrite",
            rewrite_applied=True,
            applied_fixes=[
                {
                    "target_type": "NarrativeState",
                    "field": "current_situation",
                    "action": "rename",
                    "new_value": "fixed",
                }
            ],
        )


def test_audit_report_requires_consistent_rewrite_history():
    fix = {
        "target_type": "NarrativeState",
        "field": "current_situation",
        "action": "replace",
        "new_value": "fixed",
    }

    with pytest.raises(ValueError, match="applied_fixes"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            rewrite_applied=False,
            applied_fixes=[fix],
        )

    with pytest.raises(ValueError, match="original_route"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            rewrite_applied=False,
            original_route="rewrite",
        )

    with pytest.raises(ValueError, match="applied_fixes"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            rewrite_applied=True,
            original_route="rewrite",
            applied_fixes=[],
        )

    with pytest.raises(ValueError, match="original_route"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            rewrite_applied=True,
            original_route="block",
            applied_fixes=[fix],
        )


def test_audit_report_json_roundtrip():
    """AuditReport 可序列化/反序列化."""
    report = AuditReport(
        source_text_ref="test.txt",
        route="block",
        issues=[
            {
                "issue_id": "iss_001",
                "issue_type": "fact_conflict",
                "severity": "blocking",
                "location": "FactLedger",
                "scope_of_impact": "后续",
                "violated_rule": "事实一致性",
                "description": "矛盾",
            }
        ],
        reminders=[],
        confidence_gaps=["gap1"],
    )

    json_text = report.model_dump_json(indent=2)
    data = json.loads(json_text)

    assert data["route"] == "block"
    assert data["source_text_ref"] == "test.txt"
    assert len(data["issues"]) == 1
    assert data["issues"][0]["issue_type"] == "fact_conflict"


def test_audit_report_rejects_invalid_route():
    with pytest.raises(ValueError, match="route"):
        AuditReport(source_text_ref="input.txt", route="unknown")


def test_audit_report_rejects_coerced_scalar_state_fields():
    with pytest.raises(ValueError, match="rewrite_applied"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            rewrite_applied="false",
        )

    with pytest.raises(ValueError, match="outline_used"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            outline_used="true",
        )

    with pytest.raises(ValueError, match="outline_arcs_count"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            outline_arcs_count="2",
        )

    with pytest.raises(ValueError, match="outline_arcs_count"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            outline_arcs_count=-1,
        )


def test_audit_report_rejects_malformed_review_issue():
    with pytest.raises(ValueError, match="issue_type"):
        AuditReport(
            source_text_ref="input.txt",
            route="block",
            issues=[{"issue_id": "iss_missing_schema"}],
        )


def test_audit_report_rejects_malformed_core_object_layers():
    with pytest.raises(ValueError, match="audience"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            workspec={"genre": "missing required fields"},
        )

    with pytest.raises(ValueError, match="character_id"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            characters=[{"name": "missing id"}],
        )


def test_audit_report_rejects_malformed_review_reminder():
    with pytest.raises(ValueError, match="trigger_condition"):
        AuditReport(
            source_text_ref="input.txt",
            route="pass",
            reminders=[
                {
                    "reminder_id": "rem_missing_schema",
                    "family": "promise_followup_needed",
                    "window": "plotunit_count=2",
                    "escalation_issue_type": "missing_consequence",
                    "early_escalation_condition": "same thread reminder repeats",
                    "closure_condition": "promise is advanced or delayed with cost",
                }
            ],
        )
