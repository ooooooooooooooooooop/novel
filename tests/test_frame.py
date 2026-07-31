"""Tests for NarrativeFrameUnit planning behavior."""

import pytest

from src.domain_layer.rules import get_structure_template
from src.workflow_action.frame import FrameNode, NarrativeFrameUnit


def _sample_frames() -> list[FrameNode]:
    return NarrativeFrameUnit().build_frame(
        workspec_context="mock workspec",
        structure_template=get_structure_template("compressed_three_act"),
    )


def test_build_frame_returns_hierarchy():
    frames = _sample_frames()

    assert [frame["level"] for frame in frames[:3]] == ["book", "arc", "chapter"]
    assert [frame["level"] for frame in frames[3:]] == ["scene", "scene", "scene"]
    assert frames[1]["parent_id"] == frames[0]["frame_id"]
    assert frames[2]["parent_id"] == frames[1]["frame_id"]
    assert all(frame["parent_id"] == frames[2]["frame_id"] for frame in frames[3:])


def test_build_frame_rejects_empty_structure_template():
    with pytest.raises(ValueError, match="structure_template"):
        NarrativeFrameUnit().build_frame("", [])


def test_build_frame_rejects_blank_workspec_context():
    with pytest.raises(ValueError, match="workspec_context"):
        NarrativeFrameUnit().build_frame(" ", get_structure_template("eight_node"))


def test_get_parent_chain():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    scene_id = frames[3]["frame_id"]

    chain = unit.get_parent_chain(frames, scene_id)

    assert [frame["level"] for frame in chain] == ["book", "arc", "chapter"]


def test_get_sibling_context():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    scene_id = frames[3]["frame_id"]

    siblings = unit.get_sibling_context(frames, scene_id)

    assert len(siblings) == 2
    assert all(frame["level"] == "scene" for frame in siblings)
    assert scene_id not in {frame["frame_id"] for frame in siblings}


def test_set_cursor_and_get_cursor():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    target_scene_id = frames[4]["frame_id"]

    set_cursor = unit.set_cursor(frames, target_scene_id)
    get_cursor = unit.get_cursor(frames)

    assert set_cursor == get_cursor
    assert get_cursor["current_frame_id"] == target_scene_id
    assert get_cursor["current_level"] == "scene"
    assert get_cursor["scene_id"] == target_scene_id


def test_build_continue_context():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    scene_id = frames[3]["frame_id"]
    frames[0]["active_thread_ids"] = ["thread_book"]
    frames[3]["active_thread_ids"] = ["thread_scene"]
    cursor = unit.set_cursor(frames, scene_id)

    context = unit.build_continue_context(frames, cursor)

    assert context["cursor"] == cursor
    assert context["current_frame"]["frame_id"] == scene_id
    assert [frame["level"] for frame in context["parent_chain"]] == [
        "book",
        "arc",
        "chapter",
    ]
    assert context["active_threads"] == ["thread_book", "thread_scene"]


def test_link_plotunit_rejects_blank_plotunit_id():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()

    with pytest.raises(ValueError, match="plotunit_id"):
        unit.link_plotunit(frames, frames[3]["frame_id"], " ")


@pytest.mark.parametrize("field_name", ["level", "title", "purpose", "position", "status"])
def test_validate_frame_state_rejects_blank_required_fields(field_name):
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    frames[3][field_name] = " "

    issues = unit.validate_frame_state(frames)

    assert any(issue["issue_type"] == "blank_frame_field" for issue in issues)
    assert any(field_name in issue["description"] for issue in issues)


@pytest.mark.parametrize("field_name", ["formula_node", "input_state_ref", "output_state_ref"])
def test_validate_frame_state_rejects_blank_optional_text_fields(field_name):
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    frames[3][field_name] = " "

    issues = unit.validate_frame_state(frames)

    assert any(issue["issue_type"] == "blank_frame_field" for issue in issues)
    assert any(field_name in issue["description"] for issue in issues)


def test_validate_hierarchy_catches_orphan():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    frames.append(
        {
            "frame_id": "scene_orphan",
            "level": "scene",
            "title": "Orphan scene",
            "purpose": "Invalid hierarchy",
            "position": "middle",
            "status": "planned",
        }
    )

    issues = unit.validate_hierarchy(frames)

    assert any(issue["issue_type"] == "missing_parent" for issue in issues)


def test_validate_cross_level_consistency():
    unit = NarrativeFrameUnit()
    frames = _sample_frames()
    arc = next(frame for frame in frames if frame["level"] == "arc")
    chapter = next(frame for frame in frames if frame["level"] == "chapter")
    arc["status"] = "completed"
    chapter["status"] = "active"

    issues = unit.validate_cross_level_consistency(frames)

    assert any(
        issue["issue_type"] == "completed_parent_has_active_child"
        for issue in issues
    )


def test_build_frame_eight_node_has_eight_scenes():
    unit = NarrativeFrameUnit()
    frames = unit.build_frame(
        workspec_context="mock",
        structure_template=get_structure_template("eight_node"),
    )
    scenes = [f for f in frames if f["level"] == "scene"]

    assert len(scenes) == 8
    assert scenes[0]["formula_node"] == "opener_hook"
    assert scenes[-1]["formula_node"] == "resolution"
    assert scenes[0]["position"] == "start"
    assert scenes[3]["position"] == "middle"
    assert scenes[-1]["position"] == "end"


def test_build_frame_three_act_scene_positions():
    unit = NarrativeFrameUnit()
    frames = unit.build_frame(
        workspec_context="mock",
        structure_template=get_structure_template("three_act"),
    )
    scenes = [f for f in frames if f["level"] == "scene"]

    assert len(scenes) == 3
    assert [s["position"] for s in scenes] == ["start", "middle", "end"]


def test_scene_parent_chain_has_three_ancestors():
    unit = NarrativeFrameUnit()
    frames = unit.build_frame(
        workspec_context="mock",
        structure_template=get_structure_template("compressed_three_act"),
    )
    scene = next(f for f in frames if f["level"] == "scene")

    chain = unit.get_parent_chain(frames, scene["frame_id"])

    assert [f["level"] for f in chain] == ["book", "arc", "chapter"]


def test_active_threads_exclude_non_ancestor_arc():
    unit = NarrativeFrameUnit()
    frames: list = [
        {
            "frame_id": "book_001",
            "level": "book",
            "title": "B",
            "purpose": "p",
            "position": "full",
            "status": "active",
            "active_thread_ids": ["t_book"],
        },
        {
            "frame_id": "arc_001",
            "level": "arc",
            "title": "A1",
            "purpose": "p",
            "position": "full",
            "status": "active",
            "parent_id": "book_001",
            "active_thread_ids": ["t_arc1"],
        },
        {
            "frame_id": "ch_001",
            "level": "chapter",
            "title": "C1",
            "purpose": "p",
            "position": "full",
            "status": "active",
            "parent_id": "arc_001",
        },
        {
            "frame_id": "sc_001",
            "level": "scene",
            "title": "S1",
            "purpose": "p",
            "position": "start",
            "status": "active",
            "parent_id": "ch_001",
        },
        {
            "frame_id": "arc_002",
            "level": "arc",
            "title": "A2",
            "purpose": "p",
            "position": "full",
            "status": "planned",
            "parent_id": "book_001",
            "active_thread_ids": ["t_arc2"],
        },
    ]
    cursor = unit.set_cursor(frames, "sc_001")
    context = unit.build_continue_context(frames, cursor)

    assert "t_book" in context["active_threads"]
    assert "t_arc1" in context["active_threads"]
    assert "t_arc2" not in context["active_threads"]


def test_advance_cursor_moves_to_next_scene():
    from src.domain_layer.rules import get_structure_template
    from src.workflow_action.frame import NarrativeFrameUnit

    unit = NarrativeFrameUnit()
    frames = unit.build_frame("mock workspec", get_structure_template("eight_node"))
    cursor = unit.get_cursor(frames)

    assert cursor["current_frame_id"] == "scene_001"
    assert frames[3]["status"] == "active"

    new_cursor = unit.advance_cursor(frames)
    assert new_cursor is not None
    assert new_cursor["current_frame_id"] == "scene_002"
    assert frames[3]["status"] == "completed"
    assert frames[4]["status"] == "active"


def test_advance_cursor_at_last_scene_returns_none():
    from src.domain_layer.rules import get_structure_template
    from src.workflow_action.frame import NarrativeFrameUnit

    unit = NarrativeFrameUnit()
    frames = unit.build_frame("mock workspec", get_structure_template("eight_node"))
    unit.set_cursor(frames, "scene_008")

    result = unit.advance_cursor(frames)
    assert result is None
    assert frames[-1]["status"] == "active"
