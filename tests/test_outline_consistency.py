"""Tests for ReconcileUnit outline consistency checks."""

from src.object_state import CharacterModel, WorkSpec
from src.workflow_action.outline import BookOutline
from src.workflow_action.reconcile import ReconcileUnit


def _outline(character_ids: list[str], genre: str = "科幻") -> BookOutline:
    return BookOutline.model_validate(
        {
            "arcs": [
                {
                    "arc_id": "arc_001",
                    "name": "测试 arc",
                    "chapter_range": "1-30",
                    "purpose": "测试目的",
                    "key_characters": character_ids,
                    "key_events": ["测试事件"],
                }
            ],
            "characters": [
                {
                    "character_id": character_id,
                    "name": f"角色{character_id}",
                    "identity": "测试身份",
                    "first_appearance": "第1章",
                }
                for character_id in character_ids
            ],
            "world": {
                "genre": genre,
                "power_system": "测试体系",
                "time_period": "测试时期",
                "key_rules": ["测试规则"],
            },
            "timeline": [],
        }
    )


def _character(character_id: str) -> CharacterModel:
    return CharacterModel(
        character_id=character_id,
        name=f"角色{character_id}",
        identity="测试身份",
        outer_goal="测试目标",
        inner_need="测试需求",
        fear="测试恐惧",
        flaw="测试缺陷",
        strength="测试优势",
        stance="测试立场",
    )


def _workspec(genre: str) -> WorkSpec:
    return WorkSpec(
        genre=genre,
        audience="测试读者",
        theme="测试主题",
        tone="测试调性",
        pacing="测试节奏",
    )


def test_outline_consistency_skipped_when_no_outline():
    issues = ReconcileUnit().check_outline_consistency([_character("c001")], None)
    assert issues == []


def test_outline_character_missing():
    issues = ReconcileUnit().check_outline_consistency([], _outline(["c001"]))
    assert len(issues) == 1
    assert issues[0].issue_id == "iss_outline_char_missing_c001"
    assert issues[0].severity == "warning"
    assert issues[0].issue_type == "character_distortion"


def test_outline_character_extra():
    issues = ReconcileUnit().check_outline_consistency(
        [_character("c002")], _outline([])
    )
    assert len(issues) == 1
    assert issues[0].issue_id == "iss_outline_char_extra_c002"
    assert issues[0].severity == "low"
    assert issues[0].issue_type == "character_distortion"


def test_outline_genre_mismatch():
    issues = ReconcileUnit().check_outline_consistency(
        [_workspec("奇幻")], _outline([], genre="科幻")
    )
    assert len(issues) == 1
    assert issues[0].issue_id == "iss_outline_genre_mismatch"
    assert issues[0].severity == "warning"
    assert issues[0].issue_type == "world_violation"


def test_outline_genre_consistent():
    issues = ReconcileUnit().check_outline_consistency(
        [_workspec("科幻")], _outline([], genre="科幻")
    )
    assert issues == []


def test_outline_fully_consistent():
    issues = ReconcileUnit().check_outline_consistency(
        [_workspec("科幻"), _character("c001")], _outline(["c001"], genre="科幻")
    )
    assert issues == []
