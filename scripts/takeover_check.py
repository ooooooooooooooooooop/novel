#!/usr/bin/env python
"""Takeover / handoff consistency gate (read-only).

Prevents recurrence of the consistency failures found during handoff review
(A1 baseline mismatch, A2 taskflow index drift, C4 stale pytest cache,
privacy-tracked files, oversized tracked files). It NEVER modifies any file:
it only runs read-only probes and reports.

Checks:
  1. baseline-lock   : pytest collected count vs the count locked by contract
                       tests (EXPECTED_TEST_BASELINE / EXPECTED_BASELINE).
  2. lastfailed-stale: nodeids in .pytest_cache/v/cache/lastfailed that no
                       longer exist in the current collection.
  3. taskflow-index  : .taskflow/active dirs with recent activity that are not
                       registered in .taskflow/index.json. Dirs older than
                       STALE_DIR_DAYS are reported as INFO (historical residue),
                       not FAIL.
  4. privacy-tracked : git-tracked paths that must never be committed
                       (novels/, reference_texts/, .private_backup/,
                       canary_inputs/ except tier0_* allowlisted by .gitignore).
  5. oversized-tracked: git-tracked files above MAX_TRACKED_BYTES.
  6. workspace-hygiene: informational summary only (untracked files, branches,
                       stale active taskflow dirs). Never fails.

Exit code 0 = no FAIL; 1 = at least one FAIL (a handoff gate, not a fix).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_DIR = os.path.join(REPO_ROOT, ".taskflow")
INDEX_JSON = os.path.join(TASKS_DIR, "index.json")
ACTIVE_DIR = os.path.join(TASKS_DIR, "active")
PYTEST_CACHE = os.path.join(REPO_ROOT, ".pytest_cache", "v", "cache", "lastfailed")
MAX_TRACKED_BYTES = 1_000_000  # current largest tracked file is ~240KB
STALE_DIR_DAYS = 14  # taskflow dirs untouched for this long are "historical residue";
                     # the project-inception dirs (2026-07-31, >14d old) are residue,
                     # while genuinely recent unregistered dirs (<=14d) are FAIL.

# Paths that must never be tracked, mirroring the .gitignore privacy red lines.
# `novels/tier0-*-canary/` and `canary_inputs/tier0_*` are the documented exceptions.
PRIVACY_PATTERNS = [
    (re.compile(r"^novels/"), re.compile(r"^novels/tier0-")),
    (re.compile(r"^reference_texts/"), None),
    (re.compile(r"^\.private_backup/"), None),
    (re.compile(r"^canary_inputs/"), re.compile(r"^canary_inputs/tier0_")),
]

# Scan for the locked baseline constants in the contract tests.
BASELINE_RE = re.compile(r"EXPECTED(?:_TEST)?_BASELINE\s*=\s*[\"']?(\d+)[\"']?")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env, encoding="utf-8",
        errors="replace",
    )


def collect_test_ids() -> tuple[set[str], int | None]:
    """Return (collected nodeids, collected count) via pytest --collect-only."""
    proc = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"])
    if proc.returncode != 0:
        return set(), None
    nodeids: set[str] = set()
    count: int | None = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(\d+)\s+tests?\s+collected", line)
        if m:
            count = int(m.group(1))
        elif not line.startswith(("=", "<", "-")):
            # --collect-only -q prints one nodeid per line
            nodeids.add(line)
    return nodeids, count


def locked_baseline() -> int | None:
    """Read EXPECTED(_TEST)_BASELINE from the contract tests."""
    locked: list[int] = []
    for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "tests")):
        for fn in files:
            if not fn.startswith("test_") or not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = BASELINE_RE.search(line)
                        if m:
                            locked.append(int(m.group(1)))
            except OSError:
                continue
    return max(locked) if locked else None


def git_tracked_paths() -> list[str]:
    proc = run(["git", "ls-files"])
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.splitlines() if p]


def taskflow_status() -> list[dict]:
    """Return per active-dir status: registered?, activity age days."""
    rows: list[dict] = []
    try:
        with open(INDEX_JSON, "r", encoding="utf-8") as fh:
            indexed = {t.get("name") for t in json.load(fh).get("tasks", [])}
    except (OSError, ValueError, AttributeError):
        indexed = set()
    if not os.path.isdir(ACTIVE_DIR):
        return rows
    now = datetime.now().astimezone()
    for name in sorted(os.listdir(ACTIVE_DIR)):
        d = os.path.join(ACTIVE_DIR, name)
        if not os.path.isdir(d):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(d)).astimezone()
        except OSError:
            continue
        rows.append({
            "name": name,
            "registered": name in indexed,
            "age_days": max(0, (now - mtime).days),
        })
    return rows


def lastfailed_stale(lastfailed_path: str, nodeids: set[str]) -> list[str]:
    try:
        with open(lastfailed_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(cached, dict):
        return []
    return [nid for nid in cached if nid not in nodeids]


def check_baseline() -> tuple[str, str]:
    collected, count = collect_test_ids()
    locked = locked_baseline()
    if count is None:
        return "FAIL", "pytest --collect-only could not run (returncode != 0)"
    if locked is None:
        return "FAIL", f"collected {count} but no EXPECTED(_TEST)_BASELINE lock found in tests/"
    if count == locked:
        return "PASS", f"collected {count} == locked {locked}"
    return "FAIL", f"collected {count} != locked {locked} (contract test drift)"


def check_lastfailed() -> tuple[str, str]:
    collected, _count = collect_test_ids()
    if not collected:
        return "SKIP", "collection unavailable; cannot validate cache"
    stale = lastfailed_stale(PYTEST_CACHE, collected)
    if stale:
        return "FAIL", f"{len(stale)} stale nodeid(s): {', '.join(sorted(stale)[:5])}"
    return "PASS", "lastfailed cache contains only live nodeids (or is absent)"


def check_privacy() -> tuple[str, str]:
    bad: list[str] = []
    for path in git_tracked_paths():
        # .gitkeep is a git placeholder convention (no content, no PII).
        if os.path.basename(path) == ".gitkeep":
            continue
        # 0-byte placeholders (e.g. .gitkeep) carry no PII content.
        try:
            if os.path.getsize(os.path.join(REPO_ROOT, path)) == 0:
                continue
        except OSError:
            continue
        for prefix_re, exception_re in PRIVACY_PATTERNS:
            if prefix_re.match(path) and not (exception_re and exception_re.match(path)):
                bad.append(path)
                break
    if bad:
        return "FAIL", f"{len(bad)} privacy-tracked path(s): {', '.join(sorted(bad)[:5])}"
    return "PASS", "no privacy-red-line paths are tracked"


def check_oversized() -> tuple[str, str]:
    big: list[str] = []
    for path in git_tracked_paths():
        try:
            if os.path.getsize(os.path.join(REPO_ROOT, path)) > MAX_TRACKED_BYTES:
                big.append(path)
        except OSError:
            continue
    if big:
        return "FAIL", f"{len(big)} tracked file(s) > {MAX_TRACKED_BYTES} bytes: {', '.join(sorted(big)[:5])}"
    return "PASS", f"no tracked file exceeds {MAX_TRACKED_BYTES} bytes"


def check_taskflow() -> tuple[str, str]:
    rows = taskflow_status()
    if not rows:
        return "SKIP", ".taskflow/active is absent"
    recent_unregistered = [
        r for r in rows if not r["registered"] and r["age_days"] <= STALE_DIR_DAYS
    ]
    stale_count = sum(1 for r in rows if not r["registered"] and r["age_days"] > STALE_DIR_DAYS)
    if recent_unregistered:
        names = ", ".join(f"{r['name']} ({r['age_days']}d)" for r in recent_unregistered)
        return "FAIL", f"recent active dir not in index.json: {names}"
    return "PASS", (
        f"all {len(rows)} active dirs consistent; "
        f"{stale_count} stale unregistered dir(s) (residue, INFO)"
    )


def check_hygiene() -> tuple[str, str]:
    proc = run(["git", "status", "--porcelain"])
    untracked = sum(1 for line in proc.stdout.splitlines() if line.startswith("??"))
    branch_proc = run(["git", "branch", "-a"])
    branches = [b.strip() for b in branch_proc.stdout.splitlines() if b.strip()]
    return "INFO", f"untracked={untracked}, branches={len(branches)}: {', '.join(branches[:8])}"


def main() -> int:
    checks = [
        ("baseline-lock", check_baseline),
        ("lastfailed-stale", check_lastfailed),
        ("taskflow-index", check_taskflow),
        ("privacy-tracked", check_privacy),
        ("oversized-tracked", check_oversized),
        ("workspace-hygiene", check_hygiene),
    ]
    fails = 0
    print(f"repo root : {REPO_ROOT}")
    print("-" * 70)
    for name, fn in checks:
        try:
            status, detail = fn()
        except Exception as exc:  # a gate must never crash the caller silently
            status, detail = "FAIL", f"check raised {type(exc).__name__}: {exc}"
        if status == "FAIL":
            fails += 1
        print(f"[{status:4s}] {name:<18s} {detail}")
    print("-" * 70)
    if fails:
        print(f"TAKEOVER CHECK: {fails} FAILING — investigate root cause before handoff.")
        return 1
    print("TAKEOVER CHECK: all gates PASS (read-only; nothing was modified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
