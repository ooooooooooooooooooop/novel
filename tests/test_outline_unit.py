"""Tests for OutlineUnit."""

import json

import pytest

from src.workflow_action.outline import (
    ArcOutline,
    BookOutline,
    CharacterOutline,
    OutlineUnit,
    TimelineEntry,
    WorldOutline,
)


def test_outline_unit_suggests_arc_count():
    unit = OutlineUnit()
    assert unit._suggest_arc_count(20) == "3-4"
    assert unit._suggest_arc_count(50) == "4-6"
    assert unit._suggest_arc_count(200) == "6-8"


def test_outline_unit_build_prompt_includes_stats():
    unit = OutlineUnit()
    prompt = unit.build_prompt(
        text="dummy",
        chapter_samples=[],
        total_chapters=100,
        total_chars=300000,
    )
    assert "总章节数: 100" in prompt
    assert "300000" in prompt
    assert "采样章节数: 0" in prompt


def test_outline_unit_build_prompt_with_samples():
    unit = OutlineUnit()
    from src.workflow_action.outline import ChapterSample

    samples = [
        ChapterSample(1, "开场", "这是第一章的内容..."),
        ChapterSample(10, "转折", "这是第十章的内容..."),
    ]
    prompt = unit.build_prompt(
        text="dummy",
        chapter_samples=samples,
        total_chapters=20,
        total_chars=50000,
    )
    assert "第1章: 开场" in prompt
    assert "第10章: 转折" in prompt
    assert "这是第一章的内容" in prompt


def test_outline_unit_parses_response():
    unit = OutlineUnit()
    response = json.dumps(
        {
            "arcs": [
                {
                    "arc_id": "arc_001",
                    "name": "重生觉醒",
                    "chapter_range": "1-10",
                    "purpose": "主角重生，重新选择人生",
                    "key_characters": ["c001"],
                    "key_events": ["主角重生回1994"],
                }
            ],
            "characters": [
                {
                    "character_id": "c001",
                    "name": "主角",
                    "identity": "重生者",
                    "first_appearance": "第1章",
                }
            ],
            "world": {
                "genre": "都市重生",
                "power_system": "商业资源+政治人脉",
                "time_period": "1994-2008",
                "key_rules": ["重生者保留前世记忆"],
            },
            "timeline": [
                {
                    "timestamp": "1994年夏",
                    "event": "主角重生",
                    "chapters": "1-3",
                }
            ],
        }
    )

    outline = unit.parse_response(response)
    assert isinstance(outline, BookOutline)
    assert len(outline.arcs) == 1
    assert outline.arcs[0].name == "重生觉醒"
    assert outline.arcs[0].chapter_range == "1-10"
    assert len(outline.characters) == 1
    assert outline.characters[0].name == "主角"
    assert outline.world.genre == "都市重生"
    assert len(outline.timeline) == 1


def test_outline_unit_rejects_unknown_schema_fields():
    unit = OutlineUnit()
    response = json.dumps(
        {
            "arcs": [
                {
                    "arc_id": "arc_001",
                    "name": "test arc",
                    "chapter_range": "1-10",
                    "purpose": "test purpose",
                    "unexpected_arc_field": "must fail",
                }
            ],
            "characters": [],
            "world": {
                "genre": "test",
                "power_system": "test",
                "time_period": "test",
            },
            "timeline": [],
        }
    )

    with pytest.raises(ValueError, match="unexpected_arc_field"):
        unit.parse_response(response)


@pytest.mark.parametrize(
    "field_name", ["arc_id", "name", "chapter_range", "purpose"]
)
def test_arc_outline_rejects_blank_required_text_fields(field_name):
    payload = {
        "arc_id": "arc_001",
        "name": "Opening arc",
        "chapter_range": "1-5",
        "purpose": "setup",
    }
    payload[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        ArcOutline(**payload)


@pytest.mark.parametrize("field_name", ["key_characters", "key_events"])
def test_arc_outline_rejects_blank_list_entries(field_name):
    payload = {
        "arc_id": "arc_001",
        "name": "Opening arc",
        "chapter_range": "1-5",
        "purpose": "setup",
        field_name: [" "],
    }

    with pytest.raises(ValueError, match=field_name):
        ArcOutline(**payload)


@pytest.mark.parametrize(
    "field_name", ["character_id", "name", "identity", "first_appearance"]
)
def test_character_outline_rejects_blank_required_text_fields(field_name):
    payload = {
        "character_id": "c001",
        "name": "Lead",
        "identity": "protagonist",
        "first_appearance": "chapter 1",
    }
    payload[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        CharacterOutline(**payload)


@pytest.mark.parametrize("field_name", ["genre", "power_system", "time_period"])
def test_world_outline_rejects_blank_required_text_fields(field_name):
    payload = {
        "genre": "urban",
        "power_system": "capital",
        "time_period": "1994",
    }
    payload[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        WorldOutline(**payload)


def test_world_outline_rejects_blank_key_rule_entries():
    with pytest.raises(ValueError, match="key_rules"):
        WorldOutline(
            genre="urban",
            power_system="capital",
            time_period="1994",
            key_rules=[" "],
        )


@pytest.mark.parametrize("field_name", ["timestamp", "event", "chapters"])
def test_timeline_entry_rejects_blank_required_text_fields(field_name):
    payload = {
        "timestamp": "1994",
        "event": "return",
        "chapters": "1-3",
    }
    payload[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        TimelineEntry(**payload)


def test_book_outline_rejects_empty_arcs():
    with pytest.raises(ValueError, match="arcs"):
        BookOutline(
            arcs=[],
            world=WorldOutline(
                genre="urban",
                power_system="capital",
                time_period="1994",
            ),
        )


def test_book_outline_validation():
    """验证 BookOutline 模型字段校验."""
    outline = BookOutline(
        arcs=[
            ArcOutline(
                arc_id="arc_001",
                name="测试",
                chapter_range="1-5",
                purpose="测试",
            )
        ],
        world=WorldOutline(genre="测试", power_system="测试", time_period="测试"),
    )
    assert outline.arcs[0].arc_id == "arc_001"
    assert outline.world.genre == "测试"
    assert outline.timeline == []
