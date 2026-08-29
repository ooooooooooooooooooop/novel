#!/usr/bin/env python3
"""生成仓库唯一状态真源 current_state.json（attestation 协议，审计任务 D）.

双提交协议：
  1. 全部代码/测试/文档修复提交为 subject commit H（tracked worktree clean）。
  2. 在干净 checkout 的 H 上完成验证（--full），生成 attestation。
  3. attestation 提交只允许新增/更新 current_state.json；
     合同测试强制 H..HEAD 的差异只能是该文件。

规则：
  - 禁止任何"复用祖先结果"逻辑：不带 --full 时 full_pytest_result 恒为 UNVERIFIED。
  - --full 前置条件：tracked worktree clean（git status --porcelain -uno 为空），
    否则拒绝运行（exit 3）。
  - 每次结果绑定精确 subject_commit 与 subject_tree。
  - --full 且 pytest/canary 全绿时才更新 last_validated_commit=subject_commit，
    并写 attestation status=PASS；任一失败写 FAIL/UNVERIFIED 并以非零退出。
  - profile 显式选择（--profile public_clean|operator），分 profile 记录，禁止
    跨 profile 复用；operator 是 canonical 全绿口径。
  - 分开记录 state_generated_at / pytest.completed_at / canary.completed_at。
  - 记录命令、Python/pytest 版本、平台、结果 artifact SHA、skip manifest SHA。
  - checkpoint 必须通过其自身 release contract（字节级白名单校验），不是仅 tag 可解析。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "current_state.json"
PROFILES = ("public_clean", "operator")
HONEST_RE = re.compile(
    r"^((?:\d+ (?:passed|skipped|failed|error)(?:, )?)+)"
)


def _parse_summary(tail: str) -> dict | None:
    """从 pytest 汇总行解析四元组（顺序无关，failed 可在最前）."""
    m = HONEST_RE.match(tail.strip())
    if not m:
        return None
    text = m.group(1)
    results = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0, "collected": 0}
    for word, key in (("passed", "passed"), ("skipped", "skipped"),
                      ("failed", "failed"), ("error", "errors")):
        mm = re.search(rf"(\d+) {word}", text)
        if mm:
            results[key] = int(mm.group(1))
    return results

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
EVIDENCE_FILES = (
    "docs/00_project/releases/tier0-release.json",
    "docs/00_project/releases/q1-release.json",
    "docs/00_project/releases/tier0-three-flow-canary-aggregation.json",
)


def _git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=e)


def _tracked_clean() -> bool:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain",
         "--untracked-files=no"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == ""


def _collected_tests() -> int:
    proc = _run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
                 "-p", "no:cacheprovider"])
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise RuntimeError(f"collect failed: {proc.stdout[-300:]} {proc.stderr[-300:]}")
    return int(m.group(1))


def _pytest_version() -> str:
    proc = _run([sys.executable, "-m", "pytest", "--version"])
    return proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_placeholder(
    subject_commit: str, subject_tree: str, profiles: dict[str, dict]
) -> None:
    try:
        checkpoint = _checkpoint_attestation()
    except Exception:  # noqa: BLE001
        checkpoint = {"status": "PENDING"}
    payload = {
        "attestation_version": 1,
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "state_generated_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "profiles": profiles,
        "overall_status": "UNVERIFIED",
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": None,
        "last_validated_tree": None,
        "last_certified_checkpoint": checkpoint,
        "evidence_paths": {},
    }
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _full_profile_attestation(profile: str) -> dict:
    """--full：在当前 checkout 实跑全量 pytest + canary，产出 profile attestation."""
    if not _tracked_clean():
        print(
            "REFUSED: tracked worktree is dirty — commit everything as subject "
            "commit H first (git status --porcelain -uno must be empty)",
            file=sys.stderr,
        )
        raise SystemExit(3)

    subject_commit = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")

    # 占位状态文件：让 attestation 期间的套件内状态合同测试在 H 上自洽
    # （双 profile 快速段齐全 + 真实 checkpoint 校验），套件本身才可运行。
    placeholder_profiles = {}
    for p_name in PROFILES:
        placeholder_profiles[p_name] = _quick_profile_attestation(
            p_name, subject_commit, subject_tree)
    _write_placeholder(subject_commit, subject_tree, placeholder_profiles)

    pytest_cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=no",
                  "-p", "no:cacheprovider",
                  "--basetemp", f".pytest-tmp-attest-{profile}"]
    manifest_path = REPO_ROOT / f".skip-manifest-{profile}.json"
    proc = _run(pytest_cmd, env={
        "NOVEL_TEST_PROFILE": profile,
        "NOVEL_SKIP_MANIFEST_PATH": str(manifest_path),
    })
    pytest_completed = datetime.datetime.now(datetime.timezone.utc)
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    parsed = _parse_summary(tail)
    if parsed is None:
        results = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0,
                   "collected": _collected_tests()}
    else:
        parsed["collected"] = _collected_tests()
        results = parsed

    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else b"{}"
    manifest = json.loads(manifest_bytes.decode("utf-8") or "{}")
    manifest_sha = _sha_bytes(manifest_bytes)

    canary_cmd = [sys.executable, "scripts/tier0_canary_regression.py"]
    canary = _run(canary_cmd)
    canary_completed = datetime.datetime.now(datetime.timezone.utc)
    canary_verdict = "PASS" if canary.returncode == 0 else "FAIL"
    canary_detail = canary.stdout.strip().splitlines()[-1] if canary.stdout.strip() else ""

    pytest_ok = proc.returncode == 0 and results["failed"] == 0 and results["errors"] == 0
    canary_ok = canary.returncode == 0
    status = "PASS" if (pytest_ok and canary_ok) else "FAIL"

    artifact = {
        "pytest_exit_code": proc.returncode,
        "results": results,
        "canary_exit_code": canary.returncode,
        "canary_verdict": canary_verdict,
    }
    return {
        "profile": profile,
        "status": status,
        "python_version": sys.version.split()[0],
        "pytest_version": _pytest_version(),
        "platform": platform.platform(),
        "collected_tests": results["collected"],
        "pytest": {
            "command": " ".join(pytest_cmd),
            "exit_code": proc.returncode,
            "results": results,
            "completed_at": pytest_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result_artifact_sha256": _sha_bytes(
                json.dumps(artifact, sort_keys=True, ensure_ascii=False).encode()
            ),
        },
        "canary": {
            "command": " ".join(canary_cmd),
            "exit_code": canary.returncode,
            "verdict": canary_verdict,
            "detail": canary_detail[:160],
            "completed_at": canary_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "skip_manifest": manifest,
        "skip_manifest_sha256": manifest_sha,
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "output_tail": tail[-200:],
    }


def _quick_profile_attestation(profile: str, subject_commit: str, subject_tree: str) -> dict:
    """无 --full：不做任何复用，full_pytest_result 恒为 UNVERIFIED."""
    collected = _collected_tests()
    canary_cmd = [sys.executable, "scripts/tier0_canary_regression.py"]
    canary = _run(canary_cmd)
    canary_verdict = "PASS" if canary.returncode == 0 else "FAIL"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "profile": profile,
        "status": "UNVERIFIED",
        "python_version": sys.version.split()[0],
        "pytest_version": _pytest_version(),
        "platform": platform.platform(),
        "collected_tests": collected,
        "pytest": {
            "command": "not run (quick mode never reuses prior results)",
            "exit_code": None,
            "results": None,
            "completed_at": None,
            "result_artifact_sha256": None,
        },
        "canary": {
            "command": " ".join(canary_cmd),
            "exit_code": canary.returncode,
            "verdict": canary_verdict,
            "detail": "",
            "completed_at": now,
        },
        "skip_manifest": {},
        "skip_manifest_sha256": _sha_bytes(b"{}"),
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "output_tail": "",
    }


def _checkpoint_attestation() -> dict:
    from src.boundary_control.release_record import (
        validate_legacy_tier0_release_record,
    )
    records = {}
    for rec in ("docs/00_project/releases/tier0-release.json",
                "docs/00_project/releases/q1-release.json"):
        payload = validate_legacy_tier0_release_record(rec, repo_root=REPO_ROOT)
        records[rec] = {
            "status": "PASS",
            "baseline_tests_passing": payload.get("baseline_tests_passing"),
            "tag": payload.get("release_tag_or_checkpoint", payload.get("git_tag")),
        }
    return {"status": "PASS", "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="public_clean")
    parser.add_argument("--full", action="store_true",
                        help="run full pytest + canary; requires clean tracked worktree")
    parser.add_argument("--merge-profile-from",
                        help="merge profiles.<profile> from another state json "
                             "(same subject_commit and subject_tree required)")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args(argv)

    subject_commit = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    existing = {}
    if Path(args.out).exists():
        try:
            existing = json.loads(Path(args.out).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    profiles = dict(existing.get("profiles", {})) if existing else {}

    if args.merge_profile_from:
        other = json.loads(Path(args.merge_profile_from).read_text(encoding="utf-8"))
        if (other.get("subject_commit") != subject_commit
                or other.get("subject_tree") != subject_tree):
            print("REFUSED: merge source subject does not match current HEAD/tree",
                  file=sys.stderr)
            return 2
        src_profile = other.get("profiles", {}).get(args.profile)
        if not src_profile:
            print(f"REFUSED: merge source has no profile {args.profile}",
                  file=sys.stderr)
            return 2
        profiles[args.profile] = src_profile
        generated_at = existing.get("state_generated_at", generated_at)
    elif args.full:
        profiles[args.profile] = _full_profile_attestation(args.profile)
    else:
        profiles[args.profile] = _quick_profile_attestation(
            args.profile, subject_commit, subject_tree)

    # checkpoint：必须通过其自身 release contract（字节级白名单），而非仅 tag 可解析
    try:
        checkpoint = _checkpoint_attestation()
        checkpoint_status = "PASS"
    except Exception as exc:  # noqa: BLE001
        checkpoint = {"status": "FAIL", "error": str(exc)[:200]}
        checkpoint_status = "FAIL"

    # last_validated_commit：仅 operator profile --full 全绿时显式更新；
    # quick/merge 模式绝不继承旧值（禁止无实测的资格继承）。
    last_validated = None
    last_validated_tree = None
    op = profiles.get("operator")
    if op and op.get("profile") == "operator" and op.get("status") == "PASS" and (
            op.get("subject_commit") == subject_commit):
        last_validated = subject_commit
        last_validated_tree = subject_tree
    if not (isinstance(last_validated, str) and len(last_validated) == 40):
        last_validated = None
        last_validated_tree = None
    else:
        last_validated_tree = _git("rev-parse", f"{last_validated}^{{tree}}")

    overall = "UNVERIFIED"
    statuses = [p.get("status") for p in profiles.values()]
    if statuses and all(s == "PASS" for s in statuses) and checkpoint_status == "PASS":
        overall = "PASS"
    elif any(s == "FAIL" for s in statuses) or checkpoint_status == "FAIL":
        overall = "FAIL"

    evidence_paths = {p: _git("rev-parse", f"HEAD:{p}") for p in EVIDENCE_FILES}

    payload = {
        "attestation_version": 1,
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "state_generated_at": generated_at,
        "profiles": profiles,
        "overall_status": overall,
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": last_validated,
        "last_validated_tree": last_validated_tree,
        "last_certified_checkpoint": checkpoint,
        "evidence_paths": evidence_paths,
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"overall_status: {overall}")
    for name, p_ in profiles.items():
        print(f"  [{name}] status={p_.get('status')}")
    print(f"  checkpoint={checkpoint_status}")
    if overall == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
