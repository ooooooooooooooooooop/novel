"""状态真源合同（状态真源收敛 2026-08-30）。

current_state.json 是唯一状态真源；四份门面文档只允许引用它，不得各自维护
测试数字或"当前 commit"声明。本合同机器可执行：
- current_state.json 存在、键完整、诚实形态、freshness 受限；
- collected_tests 与实时收集数一致；
- canary_result 与实时 Canary 回归一致；
- repository_head 是当前 HEAD 的祖先且落后不超过 FRESHNESS_LIMIT；
- 四文档不得出现 "N tests passing"、陈旧哈希真源声明（b464a8a/157914ed）或
  "当前 commit：" / "validated_parent=" 这类会被时间击败的表述。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "current_state.json"

REQUIRED_KEYS = (
    "repository_head",
    "head_parent",
    "collected_tests",
    "full_pytest_result",
    "canary_result",
    "last_validated_commit",
    "last_certified_checkpoint",
    "validation_timestamp",
    "evidence_paths",
    "operator_assets_present",
    "commits_behind",
)
FRESHNESS_LIMIT = 5
HONEST_RESULT_RE = re.compile(r"^\d+ passed, \d+ skipped \(collected \d+\)$")

# 这些字符串曾以"当前真源"自居，只允许出现在带日期的历史叙述中且不得再有
# 当前态歧义——四门面文档与状态文件一律禁止（历史细节在 docs 的 dated 小节）。
FORBIDDEN_TRUTH_CLAIMS = (
    "validated_parent",
    "当前 commit：",
    "当前 commit:",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _facade_docs() -> dict[str, str]:
    files = (
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/00_project/03_current_status.md",
    )
    return {f: (PROJECT_ROOT / f).read_text(encoding="utf-8") for f in files}


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor",
         ancestor, descendant],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


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


def test_state_file_exists_and_is_complete():
    assert STATE_PATH.exists(), (
        "current_state.json missing — run scripts/generate_current_state.py"
    )
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in state]
    assert not missing, missing


def test_state_file_full_pytest_result_is_honest():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    result = state["full_pytest_result"]
    assert isinstance(result, str) and result, result
    if not result.startswith("UNVERIFIED"):
        assert HONEST_RESULT_RE.fullmatch(result), (
            f"full_pytest_result must be honest form 'P passed, S skipped "
            f"(collected C)', got: {result!r}"
        )


def test_state_collected_matches_live_collection():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    assert state["collected_tests"] == _collect_count()


def test_state_canary_matches_live_regression():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    live = _canary_verdict()
    recorded = state["canary_result"]
    assert recorded.startswith(live), (
        f"canary_result {recorded!r} disagrees with live regression ({live})"
    )


def test_state_head_is_ancestor_within_freshness_limit():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    head = state["repository_head"]
    current = _git("rev-parse", "HEAD")
    assert _is_ancestor(head, current), "recorded head is not an ancestor of HEAD"
    behind = int(_git("rev-list", "--count", f"{head}..{current}"))
    assert behind <= FRESHNESS_LIMIT, (
        f"current_state.json is stale: {behind} commits behind (limit "
        f"{FRESHNESS_LIMIT}) — regenerate with scripts/generate_current_state.py"
    )
    assert state.get("commits_behind") == behind or behind == 0


def test_state_head_parent_matches_git():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    head = state["repository_head"]
    if head == _git("rev-parse", "HEAD"):
        assert state["head_parent"] == _git("rev-parse", "HEAD~1")


def test_state_checkpoint_tag_resolves():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    cp = state["last_certified_checkpoint"]
    assert cp["tag"], "no certified checkpoint recorded"
    resolved = _git("rev-parse", "--verify", f"refs/tags/{cp['tag']}^{{commit}}")
    assert resolved == cp["commit"]


def test_facade_docs_reference_state_source_only():
    for name, text in _facade_docs().items():
        assert "current_state.json" in text, f"{name} must reference the state source"
        assert not re.search(r"\d+ tests passing", text), name
        for claim in FORBIDDEN_TRUTH_CLAIMS:
            assert claim not in text, f"{name}: stale truth claim {claim!r}"
        for stale in ("b464a8a", "157914ed"):
            if name != "docs/00_project/03_current_status.md":
                assert stale not in text, f"{name}: stale hash {stale}"


def test_facade_docs_do_not_inherit_certification():
    for name, text in _facade_docs().items():
        assert not re.search(r"currently \*\*end_to_end_validated\*\*", text), name
        assert "Tier 0 production ready\n" not in text, name
