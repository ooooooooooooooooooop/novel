"""Tests for OutlineUnit injection into long-form extend."""

import json
import subprocess
import sys
from pathlib import Path

from src.boundary_control.runtime_identity import file_content_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]

_OUTLINE_RESPONSE = json.dumps(
    {
        "arcs": [
            {
                "arc_id": "arc_001",
                "name": "续写主线",
                "chapter_range": "1-30",
                "purpose": "建立续写上下文",
                "key_characters": ["c001"],
                "key_events": ["主角进入续写压力"],
            }
        ],
        "characters": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试身份",
                "first_appearance": "第1章",
            }
        ],
        "world": {
            "genre": "测试类型",
            "power_system": "测试资源",
            "time_period": "测试时期",
            "key_rules": ["测试规则"],
        },
        "timeline": [
            {
                "timestamp": "测试时间",
                "event": "测试事件",
                "chapters": "1-30",
            }
        ],
    },
    ensure_ascii=False,
)

_MIN_REBUILD_RESPONSE = json.dumps(
    {
        "workspec": {
            "genre": "测试类型",
            "audience": "测试读者",
            "theme": "测试主题",
            "tone": "测试调性",
            "pacing": "测试节奏",
        },
        "worldmodel": {"world_facts": ["测试世界成立"], "prohibitions": []},
        "charactermodels": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试身份",
                "outer_goal": "完成续写",
                "inner_need": "保持一致",
                "fear": "链路中断",
                "flaw": "信息不足",
                "strength": "稳定执行",
                "stance": "主动",
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "第30章",
            "current_location": "测试地点",
            "current_situation": "长文 extend 重建完成",
            "active_characters": ["c001"],
        },
        "factledger": {
            "entries": [
                {
                    "fact_id": "f001",
                    "statement": "测试主角完成长文 extend 输入解析",
                    "fact_type": "event",
                    "involved_entities": ["c001"],
                    "confirmed": True,
                }
            ]
        },
        "foreshadowgraph": {"entries": []},
        "confidence_gaps": [],
    },
    ensure_ascii=False,
)

_MIN_CONTINUE_RESPONSE = json.dumps(
    {
        "plotunit": {
            "unit_id": "pu_001",
            "level": "scene",
            "goal": "推进测试续写",
            "participants": ["c001"],
            "conflict": "测试冲突",
            "input_state_ref": "ns_001",
            "output_state_ref": "ns_002",
            "released_information": ["测试信息"],
            "emotional_shift": "从紧张到明确",
            "hook": "reveal",
            "consequences": ["测试后果"],
            "is_effective": True,
        },
        "new_state": {
            "state_id": "ns_002",
            "current_time": "第31章",
            "current_location": "测试地点",
            "active_characters": ["c001"],
            "current_situation": "续写测试完成",
            "active_conflicts": ["测试冲突"],
            "public_information": ["测试信息"],
            "hidden_information": [],
        },
        "new_facts": [
            {
                "fact_id": "f_extend_001",
                "statement": "测试事实",
                "fact_type": "event",
                "involved_entities": ["c001"],
                "confirmed": True,
            }
        ],
        "confidence_gaps": [],
    },
    ensure_ascii=False,
)

_MIN_REVIEW_PASS_RESPONSE = json.dumps(
    {"issues": [], "reminders": [], "route": "pass"},
    ensure_ascii=False,
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _chapter_text(chapter_count: int, repeat: int = 100) -> str:
    return "\n\n".join(
        f"第{i}章 标题{i}\n" + ("正文" * repeat)
        for i in range(1, chapter_count + 1)
    )


def _base_args(input_path: Path, output_dir: Path) -> list[str]:
    return [
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--chapter-wise",
    ]


def _write_input_hash(output_dir: Path, input_path: Path) -> None:
    (output_dir / ".input_hash").write_text(
        file_content_hash(input_path),
        encoding="utf-8",
    )


def test_extend_long_form_triggers_outline_stage(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "extend_run"

    result = _run(_base_args(input_path, output_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[STEP: OUTLINE]" in result.stdout
    assert "[WAITING]" in result.stdout
    assert (output_dir / "outline_prompt.txt").exists()
    assert not list(output_dir.glob("extend_batch_*_rebuild_prompt.txt"))


def test_extend_short_form_skips_outline_stage(tmp_path):
    input_path = tmp_path / "short_long.txt"
    input_path.write_text(_chapter_text(5, repeat=1200), encoding="utf-8")
    output_dir = tmp_path / "extend_run"

    result = _run(_base_args(input_path, output_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (output_dir / "outline_prompt.txt").exists()
    assert len(list(output_dir.glob("extend_batch_*_rebuild_prompt.txt"))) == 1


def test_extend_outline_parse_failure_fails_fast(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "extend_run"
    output_dir.mkdir()
    _write_input_hash(output_dir, input_path)
    (output_dir / "outline_response.txt").write_text("not json", encoding="utf-8")

    result = _run(_base_args(input_path, output_dir))

    assert result.returncode != 0
    assert "failed to parse outline response" in result.stdout
    assert not list(output_dir.glob("extend_batch_*_rebuild_prompt.txt"))


def test_extend_resume_mode_skips_outline_stage(tmp_path):
    from src.boundary_control.serialization import SerializationBoundaryUnit
    from src.domain_layer.rules import get_structure_template
    from src.object_state import FactLedger, ForeshadowGraph, NarrativeState, WorkSpec, WorldModel
    from src.workflow_action.frame import NarrativeFrameUnit

    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "extend_run"
    output_dir.mkdir()
    _write_input_hash(output_dir, input_path)

    serializer = SerializationBoundaryUnit()
    package = serializer.build_package(
        WorkSpec(
            genre="测试类型",
            audience="测试读者",
            theme="测试主题",
            tone="测试调性",
            pacing="测试节奏",
        ),
        WorldModel(world_facts=["测试世界成立"]),
        NarrativeState(
            state_id="ns_001",
            current_time="测试时间",
            current_location="测试地点",
            current_situation="测试局势",
        ),
        FactLedger(),
        ForeshadowGraph(),
    )
    serializer.save(package, output_dir / "extend_rebuild_package.json")
    frames = NarrativeFrameUnit().build_frame(
        workspec_context="mock workspec",
        structure_template=get_structure_template("eight_node"),
    )
    (output_dir / "extend_frames.json").write_text(
        json.dumps(frames, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _run([*_base_args(input_path, output_dir), "--resume"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Resume mode" in result.stdout
    assert not (output_dir / "outline_prompt.txt").exists()


def test_extend_long_form_outline_in_batch_prompt(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "extend_run"
    args = _base_args(input_path, output_dir)

    r1 = _run(args)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    (output_dir / "outline_response.txt").write_text(
        _OUTLINE_RESPONSE, encoding="utf-8"
    )

    r2 = _run(args)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    prompt_files = sorted(output_dir.glob("extend_batch_*_rebuild_prompt.txt"))
    assert len(prompt_files) == 1
    assert "arc_001" in prompt_files[0].read_text(encoding="utf-8")
    prompt_files[0].with_name(
        prompt_files[0].name.replace("_prompt.txt", "_response.txt")
    ).write_text(_MIN_REBUILD_RESPONSE, encoding="utf-8")

    r3 = _run(args)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert (output_dir / "continue_prompt.txt").exists()
    (output_dir / "continue_response.txt").write_text(
        _MIN_CONTINUE_RESPONSE, encoding="utf-8"
    )

    r4 = _run(args)
    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert (output_dir / "review_prompt.txt").exists()
    (output_dir / "review_response.txt").write_text(
        _MIN_REVIEW_PASS_RESPONSE, encoding="utf-8"
    )

    r5 = _run(args)
    assert r5.returncode == 0, r5.stdout + r5.stderr
    result = json.loads((output_dir / "extend_result.json").read_text(encoding="utf-8"))
    assert result["outline_used"] is True
    assert result["outline_arcs_count"] > 0
