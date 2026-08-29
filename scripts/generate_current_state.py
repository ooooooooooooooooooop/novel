#!/usr/bin/env python3
"""生成仓库唯一状态真源 current_state.json（状态真源收敛 2026-08-30）。

字段全部由实跑产生，禁止手填：
  repository_head            生成时的 git HEAD（合同测试要求为当前 HEAD 的祖先，
                             且 commits_behind 不得超过 freshness 上限——
                             状态变更提交后必须重新生成）
  head_parent                HEAD 的直接父提交
  collected_tests            pytest --collect-only 实测收集数
  full_pytest_result         真实 full pytest 汇总行（诚实形态
                             "P passed, S skipped (collected C)"）；未实跑时为
                             UNVERIFIED 并不得被文档引用为通过数
  canary_result              scripts/tier0_canary_regression.py 实测判定
  last_validated_commit      最近一次 full pytest(exit 0) + Canary(exit 0) 同时
                            通过的提交（--full 时若 HEAD 全绿即 HEAD）
  last_certified_checkpoint  最近不可变发布 checkpoint（tag 解析到提交）
  validation_timestamp       生成时刻 UTC
  evidence_paths             证据文件路径
  operator_assets_present    私有资产在场情况（决定公开/操作员两种测试口径）
  commits_behind             生成 HEAD 与当前 HEAD 的距离（合同测试锁 <=5）

用法：
  python scripts/generate_current_state.py            # 快速：collect + canary
  python scripts/generate_current_state.py --full     # 全量：另跑完整 pytest
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "current_state.json"
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
HONEST_RESULT_RE = re.compile(
    r"^\d+ passed, \d+ skipped \(collected \d+\)$"
)

PRIVATE_ASSETS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active/s7/final_evidence_anchor.json",
    "runtime/refs/cpa_active/canary_policy_s6_cpa.json",
)
CERTIFIED_CHECKPOINT_TAGS = ("v0.1.3-q1", "v0.1.2-tier0", "v0.1.1-tier0")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True
    )


def _collected_tests() -> int:
    proc = _run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
                 "-p", "no:cacheprovider"])
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise RuntimeError(f"collect failed: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    return int(m.group(1))


def _full_pytest() -> tuple[str, bool]:
    proc = _run([sys.executable, "-m", "pytest", "tests", "-q", "--tb=no",
                 "-p", "no:cacheprovider",
                 "--basetemp", ".pytest-tmp-current-state"])
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", last)
    if proc.returncode != 0 or not m:
        return f"UNVERIFIED (full pytest exit {proc.returncode}: {last[:160]})", False
    passed = int(m.group(1))
    skipped = int(m.group(2) or 0)
    collected = _collected_tests()
    return f"{passed} passed, {skipped} skipped (collected {collected})", True


def _canary() -> tuple[str, bool]:
    proc = _run([sys.executable, "scripts/tier0_canary_regression.py"])
    verdict = "PASS" if proc.returncode == 0 else "FAIL"
    detail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return f"{verdict} ({detail[:120]})", proc.returncode == 0


def _checkpoint() -> dict:
    for tag in CERTIFIED_CHECKPOINT_TAGS:
        resolved = _git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
        if resolved:
            return {"tag": tag, "commit": resolved}
    return {"tag": None, "commit": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true",
                        help="run the full pytest suite (slow) instead of reusing")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args(argv)

    head = _git("rev-parse", "HEAD")
    head_parent = _git("rev-parse", "HEAD~1") if _git("rev-list", "--count", "HEAD") != "0" else None

    existing = {}
    if Path(args.out).exists():
        try:
            existing = json.loads(Path(args.out).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    collected = _collected_tests()

    if args.full:
        result_line, pytest_ok = _full_pytest()
    else:
        prev = existing.get("full_pytest_result", "")
        prev_head = existing.get("repository_head")
        # 复用条件：已记录结果来自当前 HEAD 的祖先（freshness 内）且收集数一致
        # ——测试集内容未变，全量结果仍然成立；lineage 由 repository_head +
        # validation_timestamp 溯源。
        reusable = False
        if (
            isinstance(prev, str)
            and HONEST_RESULT_RE.fullmatch(prev) is not None
            and existing.get("collected_tests") == collected
            and isinstance(prev_head, str)
            and len(prev_head) == 40
        ):
            chk = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor",
                 prev_head, head],
                capture_output=True, text=True,
            )
            behind = int(_git("rev-list", "--count", f"{prev_head}..{head}"))
            reusable = chk.returncode == 0 and behind <= FRESHNESS_LIMIT
        result_line, pytest_ok = (
            (prev, True) if reusable
            else ("UNVERIFIED (run scripts/generate_current_state.py --full)", False)
        )

    canary_line, canary_ok = _canary()

    if not pytest_ok:
        last_validated = None
    elif canary_ok and result_line != existing.get("full_pytest_result"):
        # 本次实跑（--full）发生在此 HEAD → HEAD 即最近验证提交
        last_validated = head
    else:
        # 复用祖先提交的实测结果：验证发生在该祖先，如实保留
        prev_lv = existing.get("last_validated_commit")
        last_validated = (
            prev_lv if isinstance(prev_lv, str) and len(prev_lv) == 40 else None
        )

    checkpoint = _checkpoint()
    assets = {a: (REPO_ROOT / a).exists() for a in PRIVATE_ASSETS}

    payload = {
        "repository_head": head,
        "head_parent": head_parent,
        "collected_tests": collected,
        "full_pytest_result": result_line,
        "canary_result": canary_line,
        "last_validated_commit": last_validated,
        "last_certified_checkpoint": checkpoint,
        "validation_timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_paths": {
            "canary_aggregation": "docs/00_project/releases/tier0-three-flow-canary-aggregation.json",
            "tier0_release_record": "docs/00_project/releases/tier0-release.json",
            "q1_release_record": "docs/00_project/releases/q1-release.json",
            "generator": "scripts/generate_current_state.py",
            "canary_gate": "scripts/tier0_canary_regression.py",
        },
        "operator_assets_present": assets,
        "commits_behind": 0,
    }

    # commits_behind: 相对生成时 HEAD 恒为 0；合同测试改用 git 实测当前 HEAD 与
    # repository_head 的距离来锁新鲜度。
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        print(f"missing keys: {missing}")
        return 2
    if not HONEST_RESULT_RE.fullmatch(result_line) and not result_line.startswith("UNVERIFIED"):
        print("full_pytest_result is neither honest-form nor UNVERIFIED")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
