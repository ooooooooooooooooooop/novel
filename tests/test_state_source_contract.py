"""状态真源合同（状态真源收敛 2026-08-30，审计任务 D/E）.

current_state.json 是唯一机器真源（attestation 协议）；状态承载文档只允许引用
它，不得各自维护测试数字或"当前 commit"声明。

强制点：
- attestation 结构完整；subject_commit 是当前 HEAD 祖先，且
  subject_commit..HEAD 的差异只能是 current_state.json（双提交协议）。
- 双 profile（public_clean / operator）分册记录，禁止跨 profile 复用；
  results 五项合计自洽、failed/errors=0（PASS 时）、collected 等于唯一
  collected 合同且等于实时收集数。
- canary 与实时回归一致；last_validated_commit/tree 可解析且互绑。
- checkpoint 必须通过其自身 release contract（字节级白名单）。
- evidence paths 在 HEAD 存在且 blob SHA 与记录一致。
- 门面文档：current 区块只引用状态文件、默认标记 CURRENT_HEAD_UNVERIFIED、
  不得含数字声明；历史资格行必须带日期。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "current_state.json"

REQUIRED_KEYS = (
    "attestation_version",
    "subject_commit",
    "subject_tree",
    "state_generated_at",
    "profiles",
    "overall_status",
    "last_validated_commit",
    "last_validated_tree",
    "last_certified_checkpoint",
    "evidence_paths",
)
PROFILE_NAMES = ("public_clean", "operator")
RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")
FRESHNESS_LIMIT = 5

FACADE_DOCS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/00_project/00_project_brief.md",
    "docs/00_project/01_scope_and_boundaries.md",
    "docs/00_project/02_agent_quickstart.md",
    "docs/00_project/03_current_status.md",
)
STATE_BEARING_DOCS = FACADE_DOCS + (
    "docs/00_project/04_agent_operating_model.md",
    "docs/00_project/30_production_readiness_checklist.md",
    "docs/00_project/32_tier0_release_record_contract.md",
    "docs/00_project/54_master_goal_execution_plan.md",
)

CURRENT_BLOCK_RE = re.compile(
    r"<!--\s*state:current\s*-->(.*?)<!--\s*/state:current\s*-->", re.S
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _collect_count() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    m = re.search(r"(\d+) tests collected", proc.stdout)
    assert m, proc.stdout[-400:] + proc.stderr[-400:]
    return int(m.group(1))


def _canary_verdict() -> str:
    proc = subprocess.run(
        [sys.executable, "scripts/tier0_canary_regression.py"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    return "PASS" if proc.returncode == 0 else "FAIL"


def _load_state() -> dict:
    assert STATE_PATH.exists(), (
        "current_state.json missing — run scripts/generate_current_state.py"
    )
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def test_state_file_exists_and_is_complete():
    state = _load_state()
    missing = [k for k in REQUIRED_KEYS if k not in state]
    assert not missing, missing


def test_subject_commit_protocol_diff_only_state_file():
    state = _load_state()
    subject = state["subject_commit"]
    assert len(subject) == 40
    current = _git("rev-parse", "HEAD")
    proc = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor",
         subject, current],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, "subject_commit is not an ancestor of HEAD"
    behind = int(_git("rev-list", "--count", f"{subject}..{current}"))
    assert behind <= FRESHNESS_LIMIT, (
        f"current_state.json stale: {behind} commits behind (limit {FRESHNESS_LIMIT})"
    )
    changed = [f for f in _git(
        "diff", "--name-only", f"{subject}..{current}").splitlines() if f]
    allowed = {"current_state.json"}
    violations = [f for f in changed if f not in allowed]
    assert not violations, (
        f"attestation protocol violated — {subject}..{current} must only touch "
        f"current_state.json, found: {violations}"
    )


def test_subject_tree_resolves():
    state = _load_state()
    resolved = _git("rev-parse", f"{state['subject_commit']}^{{tree}}")
    assert resolved == state["subject_tree"]


def test_profiles_complete_and_consistent():
    state = _load_state()
    profiles = state["profiles"]
    assert "public_clean" in profiles, "public_clean attestation is mandatory"
    if "operator" not in profiles:
        # attestation 提交前的过渡态：operator 尚未跑 --full → 整体必须 UNVERIFIED
        assert state["overall_status"] == "UNVERIFIED", (
            "overall PASS requires an operator-profile attestation"
        )
        return
    for name in PROFILE_NAMES:
        p = profiles[name]
        assert p["status"] in ("PASS", "FAIL", "UNVERIFIED")
        assert p["profile"] == name
        assert p["python_version"] and p["pytest_version"] and p["platform"]
        if p["status"] in ("PASS", "FAIL"):
            results = p["pytest"]["results"]
            assert tuple(results) == RESULT_KEYS
            total = (results["passed"] + results["skipped"]
                     + results["failed"] + results["errors"])
            assert total == results["collected"], name
            if p["status"] == "PASS":
                assert results["failed"] == 0 and results["errors"] == 0
        assert p["subject_commit"] == state["subject_commit"]
        assert p["subject_tree"] == state["subject_tree"]


def test_profile_results_match_single_collected_contract():
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    state = _load_state()
    assert state["collected_tests_contract"].endswith("EXPECTED_COLLECTED_TESTS")
    live = _collect_count()
    assert int(EXPECTED_COLLECTED_TESTS) == live, (
        "collected contract drift — update EXPECTED_COLLECTED_TESTS to the "
        "live collected count"
    )
    for name, p in state["profiles"].items():
        if p["pytest"]["results"] is not None:
            assert p["pytest"]["results"]["collected"] == live, name


def test_profile_canary_matches_live_regression():
    state = _load_state()
    live = _canary_verdict()
    for name, p in state["profiles"].items():
        verdict = p["canary"]["verdict"]
        assert verdict == live, f"{name}: recorded canary {verdict} vs live {live}"


def test_last_validated_commit_and_tree_resolvable():
    state = _load_state()
    lv = state["last_validated_commit"]
    lt = state["last_validated_tree"]
    if lv is None:
        assert lt is None
        return
    assert len(lv) == 40
    assert _git("rev-parse", f"{lv}^{{tree}}") == lt


def test_checkpoint_passes_its_own_release_contract():
    from src.boundary_control.release_record import (
        validate_legacy_tier0_release_record,
    )

    state = _load_state()
    cp = state["last_certified_checkpoint"]
    assert cp.get("status") == "PASS", cp
    for rec in ("docs/00_project/releases/tier0-release.json",
                "docs/00_project/releases/q1-release.json"):
        payload = validate_legacy_tier0_release_record(rec, repo_root=PROJECT_ROOT)
        assert payload
    assert set(cp["records"]) >= {
        "docs/00_project/releases/tier0-release.json",
        "docs/00_project/releases/q1-release.json",
    }


def test_evidence_paths_exist_with_matching_blob_sha():
    state = _load_state()
    for path, recorded_sha in state["evidence_paths"].items():
        live = _git("rev-parse", f"HEAD:{path}")
        assert live == recorded_sha, f"evidence blob drift: {path}"


def test_facade_docs_have_current_blocks_and_no_number_claims():
    for name in FACADE_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "current_state.json" in text, name
        assert "tests passing" not in text, name
        m = CURRENT_BLOCK_RE.search(text)
        assert m, f"{name} missing <!-- state:current --> block"
        block = m.group(1)
        assert "CURRENT_HEAD_UNVERIFIED" in block, name
        assert not re.search(r"\d+ passed", block), name
        assert not re.search(r"\d+ tests passing", block), name


def test_state_bearing_docs_historical_claims_must_be_dated():
    for name in STATE_BEARING_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        blocks = CURRENT_BLOCK_RE.split(text)
        outside = "".join(blocks[::2])  # current blocks are the odd slices
        for line in outside.splitlines():
            if re.search(r"production[- ]ready|end_to_end_validated", line, re.I):
                assert DATE_RE.search(line), (
                    f"{name}: undated certification claim outside current block: "
                    f"{line.strip()[:120]}"
                )


def test_facade_docs_free_of_stale_truth_hashes():
    for name in FACADE_DOCS:
        if name == "docs/00_project/03_current_status.md":
            continue  # 03 的日期化 R0 历史条目允许出现祖先哈希
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for stale in ("b464a8a", "157914ed"):
            assert stale not in text, f"{name}: stale truth hash {stale}"
    text = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8")
    assert "当前 commit：" not in text
    assert "validated_parent" not in text


def test_master_plan_current_pointers_cleaned():
    text = (PROJECT_ROOT / "docs/00_project/54_master_goal_execution_plan.md").read_text(
        encoding="utf-8")
    assert "当前 commit 真源" not in text
    assert not re.search(r"当前（[^）]*）?真实状态.*3024 passed", text)
