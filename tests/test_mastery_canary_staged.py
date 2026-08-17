"""Tests for 2-Chapter Staged CLI Canary Regression (R9)."""

from pathlib import Path
import pytest

from scripts.mastery_canary_staged import (
    run_mastery_canary_staged,
    run_mastery_canary_subprocess,
)


def test_mastery_canary_staged_e2e(tmp_path: Path):
    workspace = tmp_path / "canary_staged_novel"
    workspace.mkdir(parents=True, exist_ok=True)

    summary = run_mastery_canary_staged(workspace)

    assert summary["status"] == "success"
    assert summary["chapter_1_committed"] is True
    assert summary["chapter_2_committed"] is True
    assert summary["taste_stack_layer1_passed"] is True
    assert summary["long_run_authorization_verdict"] == "long_run_not_authorized"
    assert any("缺少系统外真实人类连续阅读实验数据" in p for p in summary["unmet_preconditions"])

    # 验证关键提交产物落盘与 run_manifest.json 结构
    output_dir = workspace / "output" / "compose"
    manifest_file = output_dir / "run_manifest.json"
    assert manifest_file.exists()

    chapters_dir = workspace / "chapters"
    assert (chapters_dir / "chapter_1.txt").exists()
    assert (chapters_dir / "chapter_2.txt").exists()

    # 验证历史提交目录
    history_dir = output_dir / "run_history"
    assert history_dir.exists()
    history_files = list(history_dir.glob("*.json"))
    assert len(history_files) >= 1


def test_mastery_canary_cli_subprocess_e2e(tmp_path: Path):
    novels_root = tmp_path / "novels"
    novels_root.mkdir(parents=True, exist_ok=True)

    summary = run_mastery_canary_subprocess(novels_root, novel_name="canary_cli_novel")

    assert summary["status"] == "success"
    assert summary["chapter_1_committed"] is True
    assert summary["chapter_2_committed"] is True
    assert summary["taste_stack_layer1_passed"] is True
    assert summary["long_run_authorization_verdict"] == "long_run_not_authorized"
    assert any("缺少系统外真实人类连续阅读实验数据" in p for p in summary["unmet_preconditions"])

    novel_dir = novels_root / "canary_cli_novel"
    output_dir = novel_dir / "output" / "compose"
    assert (output_dir / "run_manifest.json").exists()
    assert (novel_dir / "chapters" / "chapter_1.txt").exists()
    assert (novel_dir / "chapters" / "chapter_2.txt").exists()
