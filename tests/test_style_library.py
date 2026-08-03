"""Tests for the style library feature (novels/_style_library)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.object_state.styleprofile import StyleProfile
from src.workflow_action.style import (
    StyleLintUnit,
    load_style_context,
    style_library_dir,
    style_library_profile_path,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LIB_RESPONSE = {
    "tone_labels": ["克制"],
    "genre_guess": "古典仙侠",
    "narrative_pov": "第三人称有限",
    "pacing_description": "叙述长句，爆点短句",
    "sentence_habits": ["长句叙述"],
    "rhetorical_preferences": ["具象比喻"],
    "show_dont_tell_notes": ["身体反应"],
    "closed_loop_objects": ["那本书"],
    "chapter_end_hook_notes": ["疑问钩"],
    "taboo_words": ["轻轻", "淡淡"],
    "style_references": ["克制:节奏"],
    "confidence_gaps": [],
}


def _full_profile_json() -> str:
    """完整的 StyleProfile JSON（库档案形状，含 stats/ai_flavor_risks）."""
    stats = json.loads(
        '{"total_chars": 10, "sentence_count": 2, "avg_sentence_len": 5.0, '
        '"short_sentence_ratio": 0.5, "long_sentence_ratio": 0.0, '
        '"dialogue_ratio": 0.0, "weak_adverb_density_per_1000": 0.0, '
        '"weak_adverb_counts": {}, "metaphor_repeats": [], '
        '"explanatory_phrase_count": 0, "shell_counts": {}, '
        '"dialogue_tag_density_per_1000": 0.0, "emotion_announcement_count": 0, '
        '"dash_colon_density_per_1000": 0.0}'
    )
    return json.dumps(
        {
            "profile_id": "style_001",
            "source_text_ref": "样书.txt",
            **LIB_RESPONSE,
            "stats": stats,
            "ai_flavor_risks": [],
        },
        ensure_ascii=False,
    )


def _write_library(novels_root: Path, name: str = "克制风") -> Path:
    lib_dir = style_library_dir(novels_root)
    lib_dir.mkdir(parents=True, exist_ok=True)
    path = lib_dir / f"{name}.json"
    path.write_text(_full_profile_json(), encoding="utf-8")
    return path


def _run_style(input_path: Path, output_dir: Path, *extra_args) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # 用 tests 里的孤立 novels 根，避免读真实仓库的 _style_library
    env["NOVELS_ROOT"] = str(input_path.parent / "novels")
    return subprocess.run(
        [
            sys.executable,
            "src/style_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
            *extra_args,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# --- 库路径解析 ---


def test_style_library_dir_under_novels_root(tmp_path):
    assert style_library_dir(tmp_path / "novels") == tmp_path / "novels" / "_style_library"


def test_style_library_profile_path_validates_name(tmp_path):
    path = style_library_profile_path("克制风", tmp_path / "novels")
    assert path == tmp_path / "novels" / "_style_library" / "克制风.json"
    for bad in ("", "a/b", "a\\b", " a"):
        with pytest.raises(ValueError):
            style_library_profile_path(bad, tmp_path / "novels")


# --- load_style_context 引用 ---


def test_load_style_context_reference_style_name(tmp_path, monkeypatch):
    novels_root = tmp_path / "novels"
    _write_library(novels_root)
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    ctx = load_style_context(tmp_path / "output", style_name="克制风")
    assert "调性: 克制" in ctx


def test_load_style_context_reference_missing_returns_empty(tmp_path):
    ctx = load_style_context(tmp_path / "output", style_name="不存在的风格")
    assert ctx == ""


def test_load_style_context_local_resolves_parent_style(tmp_path):
    """无 style_name 时读 <output_dir 上级>/style/style_profile.json.

    novel style 写到 <book>/output/style/；compose/extend 的 output_dir 分别是
    <book>/output/compose 与 <book>/output/extend，都需回到 output/style/。
    """
    local_dir = tmp_path / "output" / "style"
    local_dir.mkdir(parents=True)
    local_profile = json.loads(_full_profile_json())
    local_profile["taboo_words"] = ["本地词"]
    (local_dir / "style_profile.json").write_text(
        json.dumps(local_profile, ensure_ascii=False), encoding="utf-8"
    )
    # compose 模式：output_dir = <book>/output/compose
    ctx = load_style_context(tmp_path / "output" / "compose")
    assert "调性: 克制" in ctx
    assert "禁忌词: 本地词" in ctx
    # extend 模式：output_dir = <book>/output/extend
    ctx_extend = load_style_context(tmp_path / "output" / "extend")
    assert "调性: 克制" in ctx_extend
    # 内层【写作风格画像】头已被 loader 去掉（双层段头修复），只剩正文
    assert "【写作风格画像】" not in ctx


def test_load_style_context_reference_prefers_library_over_local(tmp_path, monkeypatch):
    """指定 style_name 时读风格库，不读 output/style/ 本地档案."""
    novels_root = tmp_path / "novels"
    _write_library(novels_root, name="克制风")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    # 本地档案存在但不一致
    local_dir = tmp_path / "output" / "style"
    local_dir.mkdir(parents=True)
    local_profile = json.loads(_full_profile_json())
    local_profile["taboo_words"] = ["本地词"]
    (local_dir / "style_profile.json").write_text(
        json.dumps(local_profile, ensure_ascii=False), encoding="utf-8"
    )
    ctx = load_style_context(tmp_path / "output", style_name="克制风")
    assert "本地词" not in ctx
    assert "调性: 克制" in ctx


# --- StyleLintUnit.lint_taboo_words ---


def test_lint_taboo_words_reports_hits():
    text = "他轻轻说道，微微点头。" * 3
    issues = StyleLintUnit().lint_taboo_words(text, ["轻轻", "淡淡"])
    assert len(issues) == 1
    assert issues[0].issue_type == "style_drift"
    assert issues[0].violated_rule == "禁忌词: 轻轻"
    assert "3" in issues[0].description


def test_lint_taboo_words_clean_no_issues():
    issues = StyleLintUnit().lint_taboo_words("干净的文本", ["轻轻"])
    assert issues == []


def test_lint_taboo_words_empty_list():
    assert StyleLintUnit().lint_taboo_words("任何文本", []) == []


# --- style_short_form --style 引用模式 ---


def test_reference_mode_skips_extraction_and_lints(tmp_path):
    novels_root = tmp_path / "novels"
    _write_library(novels_root)
    input_path = tmp_path / "input.txt"
    input_path.write_text("他轻轻说道。", encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_style(input_path, output_dir, "--style", "克制风")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Loaded style library profile" in result.stdout
    # 引用模式不写提取 prompt（跳过提炼）
    assert not (output_dir / "style_extract_prompt.txt").exists()
    assert not (output_dir / ".input_hash").exists()

    # --lint 时写禁忌词 report
    result = _run_style(input_path, output_dir, "--style", "克制风", "--lint")
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = output_dir / "style_lint_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["style_reference"] == "克制风"
    assert report["issue_count"] == 1
    assert report["issues"][0]["issue_type"] == "style_drift"


def test_reference_mode_missing_library_returns_1(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("文本", encoding="utf-8")
    result = _run_style(input_path, tmp_path / "output", "--style", "不存在的风格")
    assert result.returncode == 1
    assert "not found" in result.stdout


# --- style_short_form --name 另存库 ---


def test_name_saves_profile_to_library(tmp_path):
    novels_root = tmp_path / "novels"
    input_path = tmp_path / "input.txt"
    input_path.write_text("第一章 测试\n\n顾临蹲在藏经阁。", encoding="utf-8")
    output_dir = tmp_path / "output"

    # run 1: 写 prompt
    first = _run_style(input_path, output_dir, "--name", "测试风")
    assert first.returncode == 0, first.stdout + first.stderr
    assert (output_dir / "style_extract_prompt.txt").exists()

    # run 2: 填 response（12 质性字段，parse_response 严格 schema 不接受多余字段）
    response = json.dumps(LIB_RESPONSE, ensure_ascii=False)
    (output_dir / "style_extract_response.txt").write_text(response, encoding="utf-8")
    second = _run_style(input_path, output_dir, "--name", "测试风")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Saved to style library" in second.stdout
    library_path = style_library_profile_path("测试风", novels_root)
    assert library_path.exists()
    profile = StyleProfile.model_validate_json(library_path.read_text(encoding="utf-8"))
    assert profile.tone_labels == ["克制"]


# --- 库档案跨小说引用（compose 注入） ---


def test_library_profile_round_trip(tmp_path):
    """库档案可被 StyleProfile 校验并渲染注入文本（跨小说复用的前提）."""
    novels_root = tmp_path / "novels"
    _write_library(novels_root)
    path = style_library_profile_path("克制风", novels_root)
    profile = StyleProfile.model_validate_json(path.read_text(encoding="utf-8"))
    ctx = profile.to_prompt_context()
    assert "【写作风格画像】" in ctx
    assert "禁忌词: 轻轻, 淡淡" in ctx
