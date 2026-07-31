import pytest

from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    ReviewIssue,
)
from src.workflow_action.rewrite import RewriteUnit


def test_rewrite_build_prompt_includes_issues():
    rewrite = RewriteUnit()
    issue = ReviewIssue(
        issue_id="iss_001",
        issue_type="fact_conflict",
        severity="blocking",
        location="FactLedger",
        scope_of_impact="same-packet",
        violated_rule="fact consistency",
        description="矛盾描述",
        suggested_fix="修正为X",
    )
    prompt = rewrite.build_prompt([issue], [])
    assert "fact_conflict" in prompt
    assert "修正为X" in prompt


def test_rewrite_parse_response():
    rewrite = RewriteUnit()
    response = '[{"target_type": "FactLedger", "field": "entries", "action": "replace", "new_value": "X"}]'
    fixes = rewrite.parse_response(response)
    assert len(fixes) == 1
    assert fixes[0]["action"] == "replace"


def test_rewrite_parse_empty_response():
    rewrite = RewriteUnit()
    assert rewrite.parse_response("[]") == []


def test_rewrite_parse_response_requires_explicit_fixes_field():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="fixes"):
        rewrite.parse_response('{"notes": []}')


def test_rewrite_parse_response_requires_fixes_list():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="fixes must be a list"):
        rewrite.parse_response('{"fixes": {}}')


def test_rewrite_parse_response_rejects_unknown_top_level_fields():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="notes"):
        rewrite.parse_response('{"fixes": [], "notes": []}')


def test_rewrite_parse_response_requires_fix_objects():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="fix 1 must be an object"):
        rewrite.parse_response('["not a fix"]')


def test_rewrite_parse_response_requires_fix_contract_fields():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="target_type"):
        rewrite.parse_response('[{"field": "name", "action": "replace"}]')
    with pytest.raises(ValueError, match="action"):
        rewrite.parse_response('[{"target_type": "CharacterModel", "field": "name"}]')


def test_rewrite_parse_response_rejects_invalid_fix_action_and_unknown_fields():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="invalid rewrite fix action"):
        rewrite.parse_response(
            '[{"target_type": "CharacterModel", "field": "name", "action": "rename"}]'
        )
    with pytest.raises(ValueError, match="invalid rewrite fix target_type"):
        rewrite.parse_response(
            '[{"target_type": "UnknownThing", "field": "name", "action": "replace"}]'
        )
    with pytest.raises(ValueError, match="unexpected"):
        rewrite.parse_response(
            '[{"target_type": "CharacterModel", "field": "name", '
            '"action": "replace", "unexpected": true}]'
        )


def test_apply_fix_replaces_simple_field():
    rewrite = RewriteUnit()
    state = NarrativeState(
        state_id="ns_001",
        current_time="旧时间",
        current_location="旧地点",
        current_situation="旧局势",
    )
    fix = {
        "target_type": "NarrativeState",
        "field": "current_situation",
        "action": "replace",
        "old_value": "旧局势",
        "new_value": "新局势",
    }

    assert rewrite.apply_fix([state], fix) is True
    assert state.current_situation == "新局势"


def test_apply_fix_adds_to_list_field():
    rewrite = RewriteUnit()
    state = NarrativeState(
        state_id="ns_001",
        current_time="旧时间",
        current_location="旧地点",
        current_situation="旧局势",
    )
    fix = {
        "target_type": "NarrativeState",
        "field": "active_conflicts",
        "action": "add",
        "new_value": "新冲突",
    }

    assert rewrite.apply_fix([state], fix) is True
    assert state.active_conflicts == ["新冲突"]


def test_apply_fix_rejects_old_value_mismatch():
    rewrite = RewriteUnit()
    state = NarrativeState(
        state_id="ns_001",
        current_time="旧时间",
        current_location="旧地点",
        current_situation="旧局势",
    )
    fix = {
        "target_type": "NarrativeState",
        "field": "current_situation",
        "action": "replace",
        "old_value": "不匹配",
        "new_value": "新局势",
    }

    assert rewrite.apply_fix([state], fix) is False
    assert state.current_situation == "旧局势"


def test_apply_fix_nested_fact_entry():
    """修复 FactLedger.entries[0].confirmed"""
    rewrite = RewriteUnit()
    ledger = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="令牌归主角",
                fact_type="event",
                confirmed=False,
            )
        ]
    )
    fix = {
        "target_type": "FactLedger",
        "field": "entries.0.confirmed",
        "action": "replace",
        "old_value": False,
        "new_value": True,
    }

    assert rewrite.apply_fix([ledger], fix) is True
    assert ledger.entries[0].confirmed is True


def test_apply_fix_dict_relation():
    """修复 CharacterModel.relations"""
    rewrite = RewriteUnit()
    char = CharacterModel(
        character_id="c1",
        name="主角",
        identity="宗门弟子",
        outer_goal="复仇",
        inner_need="归属",
        fear="孤独",
        flaw="冲动",
        strength="毅力",
        stance="中立",
        relations={"c2": "敌对"},
    )
    fix = {
        "target_type": "CharacterModel",
        "field": "relations.c2",
        "action": "replace",
        "old_value": "敌对",
        "new_value": "盟友",
    }

    assert rewrite.apply_fix([char], fix) is True
    assert char.relations["c2"] == "盟友"


def test_apply_fix_selects_target_by_id():
    rewrite = RewriteUnit()
    first = CharacterModel(
        character_id="c1",
        name="First",
        identity="role",
        outer_goal="goal",
        inner_need="need",
        fear="fear",
        flaw="flaw",
        strength="strength",
        stance="stance",
    )
    second = CharacterModel(
        character_id="c2",
        name="Second",
        identity="role",
        outer_goal="goal",
        inner_need="need",
        fear="fear",
        flaw="flaw",
        strength="strength",
        stance="stance",
    )
    fix = {
        "target_type": "CharacterModel",
        "target_id": "c2",
        "field": "name",
        "action": "replace",
        "old_value": "Second",
        "new_value": "Renamed",
    }

    assert rewrite.apply_fix([first, second], fix) is True
    assert first.name == "First"
    assert second.name == "Renamed"


def test_apply_fix_rejects_ambiguous_target_without_id():
    rewrite = RewriteUnit()
    first = CharacterModel(
        character_id="c1",
        name="First",
        identity="role",
        outer_goal="goal",
        inner_need="need",
        fear="fear",
        flaw="flaw",
        strength="strength",
        stance="stance",
    )
    second = CharacterModel(
        character_id="c2",
        name="Second",
        identity="role",
        outer_goal="goal",
        inner_need="need",
        fear="fear",
        flaw="flaw",
        strength="strength",
        stance="stance",
    )
    fix = {
        "target_type": "CharacterModel",
        "field": "name",
        "action": "replace",
        "new_value": "Renamed",
    }

    assert rewrite.apply_fix([first, second], fix) is False
    assert first.name == "First"
    assert second.name == "Second"


def test_apply_fix_list_index():
    """修复 NarrativeState.active_characters[0]"""
    rewrite = RewriteUnit()
    state = NarrativeState(
        state_id="ns1",
        current_time="白天",
        current_location="宗门",
        current_situation="修炼",
        active_characters=["c1", "c2"],
    )
    fix = {
        "target_type": "NarrativeState",
        "field": "active_characters.0",
        "action": "replace",
        "old_value": "c1",
        "new_value": "c3",
    }

    assert rewrite.apply_fix([state], fix) is True
    assert state.active_characters[0] == "c3"


def test_apply_required_fixes_rejects_empty_fix_list():
    rewrite = RewriteUnit()

    with pytest.raises(ValueError, match="no fixes"):
        rewrite.apply_required_fixes([], [])


def test_apply_required_fixes_rejects_unapplied_fix():
    rewrite = RewriteUnit()
    state = NarrativeState(
        state_id="ns_001",
        current_time="old time",
        current_location="old place",
        current_situation="old situation",
    )
    fix = {
        "target_type": "NarrativeState",
        "field": "current_situation",
        "action": "replace",
        "old_value": "different situation",
        "new_value": "new situation",
    }

    with pytest.raises(ValueError, match="did not apply"):
        rewrite.apply_required_fixes([state], [fix])
    assert state.current_situation == "old situation"
