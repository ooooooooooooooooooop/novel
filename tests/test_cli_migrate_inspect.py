"""Q1 Phase 2 — CLI：`novel migrate` / `novel inspect-run`（合成工作区）.

审批点②：真实小说工作区不得迁移。本测试只用合成临时工作区验证命令契约：
migrate 显式、需 --preserve-old、从不删旧产物；inspect-run 只读巡检。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], novels_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["NOVELS_ROOT"] = str(novels_root)
    return subprocess.run(
        [sys.executable, "src/novel_cli.py", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_v2_workspace(novels_root: Path, name: str = "synth"):
    """合成 flow v2 compose 工作区：3 章旧正文 + mode.txt + .flow_version=2."""
    novel = novels_root / name
    chapters = novel / "chapters"
    output = novel / "output" / "compose"
    chapters.mkdir(parents=True)
    output.mkdir(parents=True)
    (novel / "mode.txt").write_text("compose", encoding="utf-8")
    (output / ".flow_version").write_text("2", encoding="utf-8")
    for n in range(1, 4):
        (chapters / f"chapter_{n}.txt").write_text(
            f"第{n}章正文。\n" * 20, encoding="utf-8"
        )
    return novel, chapters, output


def test_migrate_requires_preserve_old(tmp_path):
    novels_root = tmp_path / "novels"
    _make_v2_workspace(novels_root)
    result = _run(["migrate", "synth", "--to-flow", "3"], novels_root)
    assert result.returncode == 1
    assert "--preserve-old" in result.stdout


def test_migrate_v2_to_v3_seeds_manifest(tmp_path):
    novels_root = tmp_path / "novels"
    novel, chapters, output = _make_v2_workspace(novels_root)

    result = _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root)
    assert result.returncode == 0, result.stdout
    assert "Migrated synth" in result.stdout
    assert (output / ".flow_version").read_text(encoding="utf-8").strip() == "3"
    manifest_path = output / "run_manifest.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["kind"] == "seed"
    assert data["status"] == "committed"
    assert data["chapter_number"] == 3  # v2 链头
    assert data["seeded"] is True
    assert data["seeded_from_flow"] == "2"

    # 旧产物原封不动
    assert (chapters / "chapter_1.txt").read_text(encoding="utf-8").startswith("第1章正文")
    assert (chapters / "chapter_3.txt").exists()


def test_migrate_idempotent_when_already_flow3(tmp_path):
    novels_root = tmp_path / "novels"
    _make_v2_workspace(novels_root)
    assert _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root).returncode == 0
    again = _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root)
    assert again.returncode == 0
    assert "already at flow 3" in again.stdout


def test_migrate_missing_novel_errors(tmp_path):
    novels_root = tmp_path / "novels"
    result = _run(["migrate", "ghost", "--to-flow", "3", "--preserve-old"], novels_root)
    assert result.returncode == 1
    assert "no such novel workspace" in result.stdout


def test_inspect_run_committed_after_migration(tmp_path):
    novels_root = tmp_path / "novels"
    _make_v2_workspace(novels_root)
    _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root)

    result = _run(["inspect-run", "synth"], novels_root)
    assert result.returncode == 0, result.stdout
    assert "COMMITTED" in result.stdout
    assert "migrate-v2-compose" in result.stdout
    assert "3" in result.stdout  # chain head chapter_3


def test_inspect_run_json_contract(tmp_path):
    novels_root = tmp_path / "novels"
    _make_v2_workspace(novels_root)
    _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root)

    result = _run(["inspect-run", "synth", "--json"], novels_root)
    assert result.returncode == 0
    info = json.loads(result.stdout)
    assert info["flow_version"] == "3"
    assert info["recovery"]["recognized"] is True
    assert info["recovery"]["reason"] == "committed"
    assert info["manifest"]["chapter_number"] == 3


def test_inspect_run_v2_unmigrated_reports_not_committed(tmp_path):
    novels_root = tmp_path / "novels"
    _make_v2_workspace(novels_root)
    result = _run(["inspect-run", "synth", "--json"], novels_root)
    assert result.returncode == 0
    info = json.loads(result.stdout)
    assert info["flow_version"] == "2"
    assert info["recovery"]["recognized"] is False
    assert info["recovery"]["reason"] == "no_manifest"


def test_inspect_run_orphan_detected(tmp_path):
    novels_root = tmp_path / "novels"
    novel, chapters, output = _make_v2_workspace(novels_root)
    _run(["migrate", "synth", "--to-flow", "3", "--preserve-old"], novels_root)
    # 崩溃遗留孤儿：编号超出链头 3
    (chapters / "chapter_4.txt").write_text("孤儿。\n", encoding="utf-8")

    result = _run(["inspect-run", "synth"], novels_root)
    assert result.returncode == 0
    assert "orphan" in result.stdout
    assert "chapter_4.txt" in result.stdout
