"""Tests for compliance_short_form.py + novel_cli compliance mode — 端到端."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DIRTY_TEXT = """第一章 赌局

他走进地下赌场，一晚上赌博输光了全部家当。
庄家笑眯眯地看着他，让他再下注翻本。
"""

CLEAN_TEXT = """第一章 修炼

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
"""


def _run_script(input_path: Path, output_dir: Path, *extra_args):
    return subprocess.run(
        [
            sys.executable,
            "src/compliance_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
            *extra_args,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _run_cli(args, novels_root):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "src.novel_cli",
            *args,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"NOVELS_ROOT": str(novels_root), **dict(__import__("os").environ)},
    )


# --- compliance_short_form.py e2e ---


def test_scan_produces_report(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(DIRTY_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = output_dir / "compliance_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["sensitive_scan"] is True
    assert report["hit_count"] > 0
    assert report["route"] == "pass"
    assert report["hits"][0]["line_number"] >= 1


def test_sensitive_off_flag(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(DIRTY_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir, "--sensitive", "off")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "compliance_report.json").read_text(encoding="utf-8")
    )
    assert report["sensitive_scan"] is False
    assert report["hit_count"] == 0


def test_platform_flag(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(CLEAN_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir, "--platform", "番茄")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "compliance_report.json").read_text(encoding="utf-8")
    )
    assert report["platform"] == "番茄"


def test_custom_lexicon(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("正文里有一个自定义测试词。", encoding="utf-8")
    lexicon_path = tmp_path / "lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            {"entries": [{"word": "自定义测试词", "category": "涉政", "severity": "block", "note": "测试"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir, "--lexicon", str(lexicon_path))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "compliance_report.json").read_text(encoding="utf-8")
    )
    assert any(h["word"] == "自定义测试词" for h in report["hits"])
    assert report["risk_level"] == "critical"


def test_hash_mismatch_returns_1(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(DIRTY_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    _run_script(input_path, output_dir)

    # 修改输入文件，hash 不匹配
    input_path.write_text(DIRTY_TEXT + "多出来的内容", encoding="utf-8")
    result = _run_script(input_path, output_dir)
    assert result.returncode == 1
    assert "hash mismatch" in result.stdout


# --- novel_cli compliance mode ---


def test_cli_compliance_mode_contract_maps():
    from src.novel_cli import (
        VALID_MODES,
        _expected_final_result_name,
        _expected_gate_package_name,
    )

    assert "compliance" in VALID_MODES
    assert _expected_gate_package_name("compliance") == "compliance_report.json"
    assert _expected_final_result_name("compliance") == "compliance_report.json"


def test_cli_compliance_run_and_list(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(DIRTY_TEXT, encoding="utf-8")

    first = _run_cli(["compliance", "合规样书", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    result = _run_cli(["list"], novels_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "合规样书" in result.stdout
    assert "compliance" in result.stdout
    assert "completed" in result.stdout
    assert "route=pass" in result.stdout


def test_cli_compliance_resume(tmp_path):
    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text(CLEAN_TEXT, encoding="utf-8")

    first = _run_cli(["compliance", "合规续跑", "--input", str(source)], novels_root)
    assert first.returncode == 0, first.stdout + first.stderr

    # resume 应重跑同一扫描（纯代码，无 response 阶段）
    resume = _run_cli(["resume", "合规续跑"], novels_root)
    assert resume.returncode == 0, resume.stdout + resume.stderr
    report = json.loads(
        (novels_root / "合规续跑" / "output" / "compliance" / "compliance_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["route"] == "pass"


# --- 章节字数下限（平台政策并入，e2e） ---

SHORT_TEXT = """第一章 修炼

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
第二章 突破

顾临翻开那本书，第一页只有一行字。
"""


def test_report_includes_chapter_length_issues(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SHORT_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "compliance_report.json").read_text(encoding="utf-8")
    )
    length_ids = [
        issue["issue_id"]
        for issue in report["issues"]
        if issue["issue_id"].startswith("compliance_chapter_length_")
    ]
    assert length_ids  # 短章被标记
    assert report["route"] == "pass"  # warning 不阻断
    assert report["issue_count"] >= len(length_ids)


def test_chapter_length_issues_have_anchors(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text(SHORT_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"

    result = _run_script(input_path, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (output_dir / "compliance_report.json").read_text(encoding="utf-8")
    )
    length_issues = [
        issue for issue in report["issues"]
        if issue["issue_id"].startswith("compliance_chapter_length_")
    ]
    for issue in length_issues:
        assert issue["location"].startswith("第")
        assert issue["severity"] == "warning"
        assert "低于平台下限" in issue["description"]
        assert "补充本章内容" in issue["suggested_fix"]
