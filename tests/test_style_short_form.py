"""Tests for style_short_form.py — end-to-end style extraction flow."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_TEXT = """第一章 缘起

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
他这双手在藏书阁待了六年。今天那扇门是开着的。
他推开了门，看见那本书躺在地窖最深处。

第二章 代价

顾临翻开那本书，第一页只有一行字。
他蹲在灯下，把那行字读了三遍。
他忽然明白了。

第三章 路

沈砚站在灯下，背对着门。
"我沈砚，自认私习禁术，愿领宗门处置。"
顾临没有话说。
"""

VALID_RESPONSE = json.dumps(
    {
        "tone_labels": ["克制"],
        "genre_guess": "古典仙侠",
        "narrative_pov": "第三人称有限",
        "pacing_description": "叙述默认长句，情绪爆点短句独立成段",
        "sentence_habits": ["情绪靠身体反应"],
        "rhetorical_preferences": ["具象物比喻"],
        "show_dont_tell_notes": ["恐惧→冷汗/攥拳"],
        "closed_loop_objects": ["那本书"],
        "chapter_end_hook_notes": ["章末留疑问钩"],
        "taboo_words": ["轻轻", "淡淡"],
        "style_references": ["tone_kz_01"],
        "confidence_gaps": [],
    },
    ensure_ascii=False,
)

# 无任何 AI 味信号（无弱化副词/解释腔/句首连接词/枚举）的干净文本
CLEAN_TEXT = """第一章 缘起

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
他这双手在藏书阁待了六年。今天那扇门是开着的。
他推开了门。

第二章 代价

顾临翻开那本书，第一页只有一行字。
他蹲在灯下，把那行字读了三遍。
他把册子放回原处，合上了门。

第三章 路

沈砚站在灯下，背对着门。
"我沈砚，自认私习禁术，愿领宗门处置。"
顾临没有说话。
"""


def _run_style(input_path: Path, output_dir: Path, *extra_args) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # 隔离到 tmp 的 novels 根：auto-save 会写 style_library/，不得污染真实仓库
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


def test_run1_writes_prompt_and_waits(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_style(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[WAITING]" in result.stdout
    assert (output_dir / "style_extract_prompt.txt").exists()
    assert "【输入文本（章节采样）】" in (output_dir / "style_extract_prompt.txt").read_text(encoding="utf-8")
    assert (output_dir / ".input_hash").exists()


def test_run2_produces_profile(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    _run_style(input_path, output_dir)
    (output_dir / "style_extract_response.txt").write_text(VALID_RESPONSE, encoding="utf-8")

    result = _run_style(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    profile_path = output_dir / "style_profile.json"
    assert profile_path.exists()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["tone_labels"] == ["克制"]
    assert profile["narrative_pov"] == "第三人称有限"
    assert profile["stats"]["total_chars"] == len(SAMPLE_TEXT)
    assert profile["ai_flavor_risks"] is not None


def test_hash_mismatch_returns_1(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    _run_style(input_path, output_dir)

    # 修改输入文件，hash 不匹配
    input_path.write_text(SAMPLE_TEXT + "多出来的内容", encoding="utf-8")
    result = _run_style(input_path, output_dir)
    assert result.returncode == 1
    assert "hash mismatch" in result.stdout


def test_lint_flag_writes_report(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    _run_style(input_path, output_dir)
    (output_dir / "style_extract_response.txt").write_text(VALID_RESPONSE, encoding="utf-8")

    result = _run_style(input_path, output_dir, "--lint")
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = output_dir / "style_lint_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "issues" in report
    assert "source_text_ref" in report


def test_lint_report_byte_shape_unchanged_clean_text(tmp_path):
    # 干净文本：issue_count==0 且不引入任何新 rule_id（字节形状与旧版一致）
    input_path = tmp_path / "input.txt"
    input_path.write_text(CLEAN_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    _run_style(input_path, output_dir)
    (output_dir / "style_extract_response.txt").write_text(VALID_RESPONSE, encoding="utf-8")

    result = _run_style(input_path, output_dir, "--lint")
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = output_dir / "style_lint_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report.keys()) == {"source_text_ref", "issue_count", "issues"}
    assert report["issue_count"] == 0
    assert report["issues"] == []
    ids = {issue["issue_id"] for issue in report["issues"]}
    assert not ids & {"style_lint_ai_connective_abuse", "style_lint_ai_colon_enumeration"}


def test_tone_genre_knowledge_in_prompt(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_style(input_path, output_dir, "--tone", "克制", "--genre", "仙侠")
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "style_extract_prompt.txt").read_text(encoding="utf-8")
    assert "克制" in prompt
    assert "仙侠" in prompt


def test_temperament_injects_knowledge_and_worldview(tmp_path):
    """--temperament 注入气质桶知识 + 完整写作手法世界观分类轴到提炼 prompt."""
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_style(input_path, output_dir, "--temperament", "散文型")
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "style_extract_prompt.txt").read_text(encoding="utf-8")
    assert "叙事气质: 散文型" in prompt
    assert "【写作手法世界观（完整分类轴）】" in prompt
    assert "【描写手法轴】" in prompt
    assert "【人物五法轴】" in prompt


def test_v3_response_fields_parsed_and_saved(tmp_path):
    """response 含 v3 世界观质性字段 → 解析并写入 style_profile.json."""
    input_path = tmp_path / "input.txt"
    input_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    _run_style(input_path, output_dir)
    (output_dir / "style_extract_response.txt").write_text(
        json.dumps(
            {
                **json.loads(VALID_RESPONSE),
                "temperament": "散文型",
                "description_layering_notes": ["白描为本，衬托带情绪"],
                "omission_notes": ["关键动作写细，过渡一笔带过"],
                "decision_grounding_notes": ["选择由身份与信念驱动"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = _run_style(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    profile_path = output_dir / "style_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["schema_version"] == 3
    assert profile["temperament"] == "散文型"
    assert profile["description_layering_notes"] == ["白描为本，衬托带情绪"]
    assert profile["decision_grounding_notes"] == ["选择由身份与信念驱动"]
