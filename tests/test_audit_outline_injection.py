"""Tests for OutlineUnit injection into long-form audit."""

import json
import subprocess
import sys
from pathlib import Path

from src.boundary_control.runtime_identity import file_content_hash
from src.workflow_action.outline import BookOutline
from src.workflow_action.rebuild import RebuildUnit


PROJECT_ROOT = Path(__file__).resolve().parents[1]

_OUTLINE_RESPONSE = json.dumps(
    {
        "arcs": [
            {
                "arc_id": "arc_001",
                "name": "测试开局",
                "chapter_range": "1-30",
                "purpose": "建立主线与核心冲突",
                "key_characters": ["c001"],
                "key_events": ["主角进入测试场景"],
            }
        ],
        "characters": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试者",
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


def _write_input_hash(output_dir: Path, input_path: Path) -> None:
    (output_dir / ".input_hash").write_text(
        file_content_hash(input_path),
        encoding="utf-8",
    )


def _book_outline() -> BookOutline:
    return BookOutline.model_validate_json(_OUTLINE_RESPONSE)


def test_rebuild_prompt_with_outline():
    outline = _book_outline()
    prompt = RebuildUnit().build_prompt("正文", book_outline=outline)

    assert "【结构先验 — BookOutline】" in prompt
    assert "arc_001" in prompt
    assert "c001" in prompt
    assert "测试规则" in prompt
    assert "如文本局部信息与 outline 冲突，以 outline 为准" in prompt


def test_rebuild_prompt_without_outline_backward_compat():
    unit = RebuildUnit()
    assert unit.build_prompt("正文") == unit.build_prompt("正文", None)


def test_audit_long_form_triggers_outline_stage(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "audit_run"

    result = _run(
        [
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--chapter-wise",
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[STEP: OUTLINE]" in result.stdout
    assert "[WAITING]" in result.stdout
    assert (output_dir / "outline_prompt.txt").exists()
    assert not list(output_dir.glob("batch_*_rebuild_prompt.txt"))


def test_audit_short_form_skips_outline_stage(tmp_path):
    input_path = tmp_path / "short_long.txt"
    input_path.write_text(_chapter_text(5, repeat=1200), encoding="utf-8")
    output_dir = tmp_path / "audit_run"

    result = _run(
        [
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--chapter-wise",
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (output_dir / "outline_prompt.txt").exists()
    assert len(list(output_dir.glob("batch_*_rebuild_prompt.txt"))) == 1


def test_audit_outline_parse_failure_fails_fast(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_chapter_text(30), encoding="utf-8")
    output_dir = tmp_path / "audit_run"
    output_dir.mkdir()
    _write_input_hash(output_dir, input_path)
    (output_dir / "outline_response.txt").write_text("not json", encoding="utf-8")

    result = _run(
        [
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--chapter-wise",
        ]
    )

    assert result.returncode != 0
    assert "failed to parse outline response" in result.stdout
    assert not list(output_dir.glob("batch_*_rebuild_prompt.txt"))
