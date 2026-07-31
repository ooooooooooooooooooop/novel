"""Tests for compose_short_form resume behavior."""

import json
import subprocess
import sys
from pathlib import Path

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state import CharacterModel, NarrativeState, WorkSpec, WorldModel
from src.workflow_action.frame import NarrativeFrameUnit


def test_compose_argparse_parses_resume():
    """验证 compose 脚本能正确解析 --resume 参数."""
    result = subprocess.run(
        [sys.executable, "src/compose_short_form.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--resume" in result.stdout


def test_compose_resume_loads_saved_state():
    """验证 resume 能加载保存的 compose_state.json."""
    from src.domain_layer.rules import get_structure_template

    state_path = Path("output/compose_state.json")
    frames_path = Path("output/compose_frames.json")
    original_state = state_path.read_bytes() if state_path.exists() else None
    original_frames = frames_path.read_bytes() if frames_path.exists() else None

    try:
        ser = SerializationBoundaryUnit()
        workspec = WorkSpec(
            genre="仙侠",
            audience="青年",
            theme="成长",
            tone="克制",
            pacing="前快中稳后爆",
        )
        state = NarrativeState(
            state_id="ns_test",
            current_time="测试",
            current_location="测试",
            current_situation="测试",
        )
        pkg = ser.build_package(workspec, state)
        ser.save(pkg, state_path)

        frame_unit = NarrativeFrameUnit()
        frames = frame_unit.build_frame("mock workspec", get_structure_template("eight_node"))
        frame_unit.set_cursor(frames, "scene_003")
        frames_path.parent.mkdir(parents=True, exist_ok=True)
        frames_path.write_text(json.dumps(frames), encoding="utf-8")

        assert state_path.exists()
        assert frames_path.exists()

        loaded_pkg = ser.load(state_path)
        loaded_objects = ser.deserialize_package(loaded_pkg)
        assert any(isinstance(o, WorkSpec) for o in loaded_objects)
        assert any(isinstance(o, NarrativeState) for o in loaded_objects)
    finally:
        if original_state is None:
            state_path.unlink(missing_ok=True)
        else:
            state_path.write_bytes(original_state)

        if original_frames is None:
            frames_path.unlink(missing_ok=True)
        else:
            frames_path.write_bytes(original_frames)


def test_initialize_from_workspec_no_pending():
    """验证 compose 初始化不再使用“待定”作为默认值."""
    from src.compose_short_form import initialize_from_workspec

    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )
    objects = initialize_from_workspec(workspec)

    char = next(o for o in objects if isinstance(o, CharacterModel))
    world = next(o for o in objects if isinstance(o, WorldModel))
    state = next(o for o in objects if isinstance(o, NarrativeState))

    assert char.outer_goal != "待定"
    assert char.inner_need != "待定"
    assert state.current_situation != "待定"
    assert "突破" in char.outer_goal or "成长" in char.outer_goal
    assert len(world.consequence_logic) > 0
