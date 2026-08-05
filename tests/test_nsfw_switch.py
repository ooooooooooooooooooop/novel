"""Tests for the NSFW (成人向) switch — 生成侧注入 + 合规侧扫描联动.

镜像 test_retrieval_injection / test_continuation_anchors 的"空串静默降级 + 字节不变"范式：
- build_prompt 的 nsfw_context 缺省（空串）时不得产生任何注入字节；
- 显式 --nsfw on|off 时注入对应内容分级；
- 合规侧 nsfw_on=True 只跳过「涉黄」分类，其余分类仍扫。
"""

import subprocess
import sys
from pathlib import Path

from src.domain_layer.compliance_knowledge import NSFW_CATEGORY
from src.domain_layer.compliance_rules import (
    build_lexicon_nsfw_aware,
    build_nsfw_context,
    get_sensitive_categories,
)
from src.object_state import (
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.workflow_action.compliance import ComplianceUnit
from src.workflow_action.continuation import ContinueUnit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["gl"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _base_prompt(nsfw_context: str = "") -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        platform=None,
        genre=None,
        nsfw_context=nsfw_context,
    )


# --- 生成侧：内容分级文案 ---


def test_build_nsfw_context_off_is_safe_policy():
    policy = build_nsfw_context(False)
    assert "正常向" in policy
    assert "禁止" in policy
    assert "已显式开启" not in policy


def test_build_nsfw_context_on_is_allow_policy():
    policy = build_nsfw_context(True)
    assert "NSFW" in policy
    assert "已显式开启" in policy
    assert "禁止出现任何色情" not in policy


def test_build_nsfw_context_off_and_on_differ():
    assert build_nsfw_context(False) != build_nsfw_context(True)


# --- 合规侧：词库分类过滤 ---


def test_lexicon_nsfw_aware_sensitive_off_is_empty():
    assert build_lexicon_nsfw_aware(sensitive_on=False, nsfw_on=False) == []
    assert build_lexicon_nsfw_aware(sensitive_on=False, nsfw_on=True) == []


def test_lexicon_nsfw_aware_on_excludes_porn_keeps_others():
    entries = build_lexicon_nsfw_aware(sensitive_on=True, nsfw_on=True)
    cats = {entry["category"] for entry in entries}
    assert NSFW_CATEGORY not in cats
    assert "涉政" in cats  # 非涉黄分类仍扫
    assert all(entry["category"] != NSFW_CATEGORY for entry in entries)


def test_lexicon_nsfw_aware_off_includes_porn():
    entries = build_lexicon_nsfw_aware(sensitive_on=True, nsfw_on=False)
    cats = {entry["category"] for entry in entries}
    assert NSFW_CATEGORY in cats
    assert cats == set(get_sensitive_categories())


# --- 生成侧：prompt 注入（零成本契约） ---


def test_continue_prompt_nsfw_context_injected_when_present():
    prompt = _base_prompt(nsfw_context=build_nsfw_context(False))
    assert "【内容分级】" in prompt
    assert "禁止出现任何色情" in prompt


def test_continue_prompt_nsfw_default_empty_is_zero_cost():
    default = _base_prompt()
    explicit_empty = _base_prompt(nsfw_context="")
    assert default == explicit_empty
    assert "【内容分级】" not in default


def test_continue_prompt_nsfw_on_injects_allow_policy():
    prompt = _base_prompt(nsfw_context=build_nsfw_context(True))
    assert "【内容分级】" in prompt
    assert "已显式开启成人向" in prompt


# --- 合规侧：scan_prose 涉黄过滤 ---


def _scan(text: str, *, nsfw_on: bool, sensitive_on: bool = True):
    return ComplianceUnit().scan_prose(
        text,
        platform="通用",
        sensitive_on=sensitive_on,
        nsfw_on=nsfw_on,
    )


def test_scan_prose_nsfw_off_reports_porn_hit():
    report = _scan("夜深了，两人相拥而眠，性交场景不宜展开。", nsfw_on=False)
    porn = [hit for hit in report.hits if hit.category == NSFW_CATEGORY]
    assert porn  # 涉黄词命中
    assert report.to_dict()["nsfw_scan"] is True


def test_scan_prose_nsfw_on_skips_porn_keeps_political():
    text = "性交描写是成年人的事，六四没有讨论的必要。"
    report = _scan(text, nsfw_on=True)
    porn = [hit for hit in report.hits if hit.category == NSFW_CATEGORY]
    political = [hit for hit in report.hits if hit.category == "涉政"]
    assert not porn  # 涉黄被跳过
    assert political  # 涉政仍命中
    assert report.to_dict()["nsfw_scan"] is False


def test_scan_prose_sensitive_off_no_hits():
    report = _scan("性交与六四都出现了。", nsfw_on=False, sensitive_on=False)
    assert report.hits == []


def test_scan_prose_nsfw_on_keeps_custom_entries():
    custom = [
        {"word": "自定义涉黄词", "category": "涉黄", "severity": "high", "note": "t"}
    ]
    report = ComplianceUnit().scan_prose(
        "自定义涉黄词出现。",
        platform="通用",
        sensitive_on=True,
        nsfw_on=True,
        custom_entries=custom,
    )
    porn = [hit for hit in report.hits if hit.category == NSFW_CATEGORY]
    assert not porn  # 自定义涉黄条目同样被跳过


# --- CLI 端到端 ---


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _write_input(tmp_path: Path) -> Path:
    path = tmp_path / "input.txt"
    path.write_text("性交描写出现了。六四不存在。\n", encoding="utf-8")
    return path


def test_compliance_cli_nsfw_off_reports_porn(tmp_path):
    src = PROJECT_ROOT / "src" / "compliance_short_form.py"
    input_path = _write_input(tmp_path)
    out = tmp_path / "out_off"
    result = _run_cli(
        [str(src), str(input_path), "--output-dir", str(out), "--nsfw", "off"],
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = (out / "compliance_report.json").read_text(encoding="utf-8")
    assert "性交" in report  # 涉黄命中


def test_compliance_cli_nsfw_on_skips_porn(tmp_path):
    import json as _json

    src = PROJECT_ROOT / "src" / "compliance_short_form.py"
    input_path = _write_input(tmp_path)
    out = tmp_path / "out_on"
    result = _run_cli(
        [str(src), str(input_path), "--output-dir", str(out), "--nsfw", "on"],
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = _json.loads((out / "compliance_report.json").read_text(encoding="utf-8"))
    porn = [h for h in report["hits"] if h["category"] == "涉黄"]
    political = [h for h in report["hits"] if h["category"] == "涉政"]
    assert not porn  # 涉黄被跳过
    assert political  # 涉政仍命中
    assert report["nsfw_scan"] is False


def test_compose_cli_help_accepts_nsfw():
    result = _run_cli(
        [str(PROJECT_ROOT / "src" / "compose_short_form.py"), "--help"],
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0
    assert "--nsfw" in result.stdout


def test_extend_cli_help_accepts_nsfw():
    result = _run_cli(
        [str(PROJECT_ROOT / "src" / "extend_short_form.py"), "--help"],
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0
    assert "--nsfw" in result.stdout


def test_novel_cli_subcommands_accept_nsfw():
    for sub in ("compose", "extend", "compliance"):
        result = _run_cli(
            [str(PROJECT_ROOT / "src" / "novel_cli.py"), sub, "--help"],
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, (sub, result.stdout + result.stderr)
        assert "--nsfw" in result.stdout, sub
