"""Tests for the style library feature (repo-root style_library/)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.object_state.styleprofile import StyleProfile
from src.workflow_action.style import (
    STYLE_DEDUP_THRESHOLD,
    StyleLintUnit,
    auto_style_id,
    find_most_similar,
    load_style_context,
    load_style_manifest,
    profile_similarity,
    resolve_style_library_path,
    search_style_manifest,
    style_library_dir,
    style_library_profile_path,
    upsert_style_manifest,
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
    # 用 tests 里的孤立 novels 根，避免读真实仓库的 style_library
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
    # 风格库固定在 novels 的父目录（仓库根）/style_library，独立于小说工作区
    assert style_library_dir(tmp_path / "novels") == tmp_path / "style_library"


def test_style_library_profile_path_validates_name(tmp_path):
    path = style_library_profile_path("克制风", tmp_path / "novels")
    assert path == tmp_path / "style_library" / "克制风.json"
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


# --- 风格库 v2：中性 id / 相似度 / manifest / 检索 ---


def _make_profile(**overrides) -> StyleProfile:
    """基于 LIB_RESPONSE 构造可独立调整字段的 StyleProfile."""
    data = json.loads(_full_profile_json())
    data.update(overrides)
    return StyleProfile.model_validate(data)


def test_auto_style_id_neutral_naming():
    profile = _make_profile(tone_labels=["克制"], genre_guess="都市官商重生")
    assert auto_style_id(profile, {"profiles": []}) == "克制-官商-001"


def test_auto_style_id_increments_seq():
    profile = _make_profile(tone_labels=["克制"], genre_guess="都市官商重生")
    manifest = {"profiles": [{"id": "克制-官商-001"}, {"id": "克制-官商-002"}]}
    assert auto_style_id(profile, manifest) == "克制-官商-003"


def test_auto_style_id_genre_slug_fallback():
    # 未知 genre 落 DEFAULT slug（杂）
    profile = _make_profile(tone_labels=["克制"], genre_guess="跨界流")
    assert auto_style_id(profile, {"profiles": []}) == "克制-杂-001"


def test_profile_similarity_identical_is_1():
    a = _make_profile()
    b = _make_profile()
    assert profile_similarity(a, b) == pytest.approx(1.0)


def test_profile_similarity_different_is_lower():
    base = json.loads(_full_profile_json())
    stats = dict(base["stats"])
    stats["avg_sentence_len"] = 8.0
    b = _make_profile(
        tone_labels=["热血"],
        genre_guess="仙侠",
        narrative_pov="第三人称全知",
        sentence_habits=["短句直给"],
        stats=stats,
    )
    score = profile_similarity(_make_profile(), b)
    assert 0.0 <= score < STYLE_DEDUP_THRESHOLD


def test_manifest_upsert_idempotent(tmp_path):
    novels_root = tmp_path / "novels"
    profile = _make_profile(tone_labels=["克制"], genre_guess="仙侠")
    upsert_style_manifest(profile, "克制-仙侠-001", "克制-仙侠-001.json", novels_root)
    upsert_style_manifest(profile, "克制-仙侠-001", "克制-仙侠-001.json", novels_root)
    manifest = load_style_manifest(novels_root)
    assert len(manifest["profiles"]) == 1
    assert manifest["profiles"][0]["id"] == "克制-仙侠-001"


def test_find_most_similar_returns_top(tmp_path):
    novels_root = tmp_path / "novels"
    lib_dir = style_library_dir(novels_root)
    lib_dir.mkdir(parents=True)
    profile_a = _make_profile(tone_labels=["克制"], genre_guess="都市官商重生")
    (lib_dir / "克制-官商-001.json").write_text(
        profile_a.model_dump_json(), encoding="utf-8"
    )
    upsert_style_manifest(profile_a, "克制-官商-001", "克制-官商-001.json", novels_root)
    new = _make_profile(tone_labels=["克制"], genre_guess="都市官商重生")
    top_id, score = find_most_similar(new, novels_root=novels_root)
    assert top_id == "克制-官商-001"
    assert score >= STYLE_DEDUP_THRESHOLD


def test_search_style_manifest():
    manifest = {
        "profiles": [
            {
                "id": "克制-官商-001",
                "tone_labels": ["克制"],
                "genre_guess": "都市官商重生",
                "narrative_pov": "第三人称有限",
                "key_signatures": ["长句叙述", "分号并列"],
            },
            {
                "id": "仙侠-001",
                "tone_labels": ["热血"],
                "genre_guess": "仙侠",
                "narrative_pov": "第三人称",
                "key_signatures": ["打斗动作"],
            },
        ]
    }
    assert [h["id"] for h in search_style_manifest(manifest, "官商")] == [
        "克制-官商-001"
    ]
    assert [h["id"] for h in search_style_manifest(manifest, "仙侠")] == ["仙侠-001"]
    assert search_style_manifest(manifest, "不存在") == []


def test_resolve_style_library_path_via_manifest(tmp_path, monkeypatch):
    """manifest.id 优先解析；物理文件名仍可直接解析（迁移场景）."""
    novels_root = tmp_path / "novels"
    lib_dir = style_library_dir(novels_root)
    lib_dir.mkdir(parents=True)
    profile = _make_profile(tone_labels=["克制"], genre_guess="都市官商重生")
    (lib_dir / "style_001.json").write_text(
        profile.model_dump_json(), encoding="utf-8"
    )
    upsert_style_manifest(profile, "克制-官商-001", "style_001.json", novels_root)
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    assert resolve_style_library_path("克制-官商-001") == lib_dir / "style_001.json"
    assert resolve_style_library_path("style_001") == lib_dir / "style_001.json"


# --- CLI：自动入库 / 去重拦截 / --force / --no-library / --style-search ---


def test_auto_save_first_entry(tmp_path):
    novels_root = tmp_path / "novels"
    input_path = tmp_path / "input.txt"
    input_path.write_text("第一章 测试\n\n顾临蹲在藏经阁。", encoding="utf-8")
    output_dir = tmp_path / "output"
    first = _run_style(input_path, output_dir)
    assert first.returncode == 0, first.stdout + first.stderr
    (output_dir / "style_extract_response.txt").write_text(
        json.dumps(LIB_RESPONSE, ensure_ascii=False), encoding="utf-8"
    )
    second = _run_style(input_path, output_dir)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "first entry" in second.stdout
    assert "Saved to style library" in second.stdout
    lib_dir = tmp_path / "style_library"
    # LIB_RESPONSE: tone=克制, genre_guess=古典仙侠 → slug 先命中"仙侠"→ id 克制-仙侠-001
    assert (lib_dir / "克制-仙侠-001.json").exists()
    manifest = load_style_manifest(novels_root)
    assert manifest["profiles"][0]["id"] == "克制-仙侠-001"


def test_auto_save_dedup_blocks_and_force(tmp_path):
    novels_root = tmp_path / "novels"
    input_path = tmp_path / "input.txt"
    input_path.write_text("第一章 测试\n\n顾临蹲在藏经阁。", encoding="utf-8")
    output_dir = tmp_path / "output"
    # run 1: 写 prompt
    first = _run_style(input_path, output_dir)
    assert first.returncode == 0, first.stdout + first.stderr
    response = json.dumps(LIB_RESPONSE, ensure_ascii=False)
    (output_dir / "style_extract_response.txt").write_text(response, encoding="utf-8")
    # run 2: 入库
    second = _run_style(input_path, output_dir)
    assert second.returncode == 0, second.stdout + second.stderr
    # run 3: 相同 input/response → 相似 100% → 拦截，不新建
    third = _run_style(input_path, output_dir)
    assert third.returncode == 0, third.stdout + third.stderr
    assert "similar to" in third.stdout
    lib_dir = tmp_path / "style_library"
    profiles = [f for f in lib_dir.glob("*.json") if f.name != "manifest.json"]
    assert len(profiles) == 1
    # run 4: --force 强制新建 → seq 自增为 002
    forced = _run_style(input_path, output_dir, "--force")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert "saving 克制-仙侠-002" in forced.stdout
    assert (lib_dir / "克制-仙侠-002.json").exists()


def test_no_library_skips_auto_save(tmp_path):
    novels_root = tmp_path / "novels"
    input_path = tmp_path / "input.txt"
    input_path.write_text("第一章 测试\n\n顾临蹲在藏经阁。", encoding="utf-8")
    output_dir = tmp_path / "output"
    first = _run_style(input_path, output_dir, "--no-library")
    assert first.returncode == 0, first.stdout + first.stderr
    (output_dir / "style_extract_response.txt").write_text(
        json.dumps(LIB_RESPONSE, ensure_ascii=False), encoding="utf-8"
    )
    second = _run_style(input_path, output_dir, "--no-library")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "skipped (--no-library)" in second.stdout
    assert not (tmp_path / "style_library" / "manifest.json").exists()


def test_style_search_cli(tmp_path):
    novels_root = tmp_path / "novels"
    input_path = tmp_path / "input.txt"
    input_path.write_text("第一章 测试\n\n顾临蹲在藏经阁。", encoding="utf-8")
    output_dir = tmp_path / "output"
    # 先入库一个档案
    first = _run_style(input_path, output_dir)
    assert first.returncode == 0, first.stdout + first.stderr
    (output_dir / "style_extract_response.txt").write_text(
        json.dumps(LIB_RESPONSE, ensure_ascii=False), encoding="utf-8"
    )
    second = _run_style(input_path, output_dir)
    assert second.returncode == 0, second.stdout + second.stderr
    # --style-search 检索
    search = _run_style(input_path, output_dir, "--style-search", "仙侠")
    assert search.returncode == 0, search.stdout + search.stderr
    assert "克制-仙侠-001" in search.stdout
    miss = _run_style(input_path, output_dir, "--style-search", "不存在")
    assert miss.returncode == 1
