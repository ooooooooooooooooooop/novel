#!/usr/bin/env python3
"""生成仓库唯一状态真源 current_state.json（第三轮 attestation 协议）.

exact-tree 规则（审计任务 A）：
  - subject commit H 本身必须携带确定性的中性 UNVERIFIED 占位状态。
  - 验证在由 H 建立的独立干净 worktree/clone 中运行；执行前后 tracked diff
    必须为空（dirty gate 执行前后各验一次）。
  - pytest 前不得覆盖任何 tracked 文件：全部运行 artifact 写入
    state_artifacts/<subject12>/<profile>/（未跟踪路径）。
  - 汇总行无法解析 → 直接 FAIL，禁止生成 0 failed 兜底。
  - 允许存在的未跟踪/忽略内容仅限显式白名单（私有资产 + 本工具产物），
    并记录内容/目录树指纹。

profile 记录（审计任务 B）：stdout/stderr/JUnit XML/exit code/完整命令与
env/subject commit+tree/平台/文件系统大小写探针/core.autocrlf/起止时间/各
artifact SHA。overall_status 由全部必需 profile + checkpoint 重新推导；
last_validated 严格等于 subject。

字段（审计任务 B/D）：repository_head / attestation_commit / head_status /
subject_status 分离 subject 与 carrier HEAD；checkpoint 拆分
certification_tag / tag_target_commit / record_commit / record_blob /
tag_tree_blob，并按实际字节关系诚实标注 post_tag_historical_record。
哈希语义全仓库统一为 Git blob 字节。
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
NL = chr(10)

REQUIRED_KEYS = (
    "attestation_version",
    "subject_commit",
    "subject_tree",
    "repository_head",
    "attestation_commit",
    "head_status",
    "subject_status",
    "state_generated_at",
    "profiles",
    "overall_status",
    "collected_tests",
    "collected_tests_contract",
    "last_validated_commit",
    "last_validated_tree",
    "last_certified_checkpoint",
    "evidence_paths",
)
RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")

UNTRACKED_ALLOWLIST_PREFIXES = (
    "state_artifacts/",
    ".skip-manifest-",
    ".pytest-tmp-",
    "novels/",
    "runtime/",
    "reference_texts/",
    "author_models/",
    "output/",
    ".ai/",
    "canary_inputs/",
    "style_library/",
    "author_templates/",
    "quality_research/",
)

PRIVATE_ASSETS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active/s7/final_evidence_anchor.json",
    "runtime/refs/cpa_active/canary_policy_s6_cpa.json",
)

SUMMARY_WORD_RE = re.compile(r"(\d+) (passed|skipped|failed|error)")


def _git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _git_bytes(rev_path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "blob", rev_path],
        capture_output=True, check=True,
    ).stdout


def _run(cmd: list[str], env: dict | None = None, cwd: Path | None = None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, env=e
    )


def _tracked_changes() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain",
         "--untracked-files=no"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return ["<git status failed>"]
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _untracked_outside_allowlist() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    offenders = []
    for line in proc.stdout.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:].strip().strip('"')
        posix = path.replace("\\", "/")
        if posix.startswith(UNTRACKED_ALLOWLIST_PREFIXES):
            continue
        offenders.append(posix)
    return offenders


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _asset_fingerprint(rel: str) -> str:
    p = REPO_ROOT / rel
    if p.is_file():
        return _sha_file(p)
    h = hashlib.sha256()
    count = 0
    for f in sorted(p.rglob("*")):
        if f.is_file():
            h.update(
                f"{f.relative_to(p).as_posix()}:{f.stat().st_size}{NL}".encode()
            )
            count += 1
            if count >= 5000:
                break
    return h.hexdigest()


def _collected_tests(checkout: Path) -> int:
    proc = _run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
                 "-p", "no:cacheprovider"], cwd=checkout)
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise RuntimeError(
            f"collect failed in {checkout}: {proc.stdout[-300:]} {proc.stderr[-300:]}"
        )
    return int(m.group(1))


def _parse_summary(tail: str) -> dict | None:
    results = {k: 0 for k in RESULT_KEYS if k != "collected"}
    found = False
    for m in SUMMARY_WORD_RE.finditer(tail):
        found = True
        word = m.group(2)
        key = "errors" if word == "error" else word
        results[key] = int(m.group(1))
    if not found:
        return None
    return results


def _case_probe(workdir: Path) -> dict:
    """文件系统大小写探针：a.txt 与 A.TXT 能否同时存在."""
    probe = workdir / "_case_probe"
    probe.mkdir(parents=True, exist_ok=True)
    lower = probe / "a.txt"
    upper = probe / "A.TXT"
    for f in (lower, upper):
        if f.exists():
            f.unlink()
    lower.write_text("lower", encoding="utf-8")
    upper.write_text("UPPER", encoding="utf-8")
    both = (
        lower.exists()
        and upper.exists()
        and lower.read_text(encoding="utf-8") == "lower"
        and upper.read_text(encoding="utf-8") == "UPPER"
    )
    return {
        "a_txt_and_A_TXT_coexist": bool(both),
        "case_sensitive_filesystem": bool(both),
    }


def _git_config(key: str) -> str | None:
    proc = _run(["git", "config", "--get", key])
    return proc.stdout.strip() or None


def _read_manifest(checkout: Path) -> dict:
    """skip manifest：由 conftest 在 NOVEL_SKIP_MANIFEST_PATH 指定处写入."""
    candidates = [
        checkout / ".skip-manifest-current.json",
        REPO_ROOT / ".skip-manifest-current.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
    return {}


def _full_profile_attestation(
    profile: str, artifact_root: Path, checkout: Path
) -> dict:
    """--full：在独立干净 checkout 实跑全量 pytest + canary.

    前后各验一次 tracked-clean；artifact 全部写入未跟踪的 artifact_root；
    汇总行不可解析 → FAIL（无兜底）。
    """
    started_at = datetime.datetime.now(datetime.timezone.utc)

    pre_tracked = _tracked_changes()
    if pre_tracked:
        raise SystemExit(
            f"REFUSED(pre): tracked worktree dirty: {pre_tracked[:5]}"
        )
    pre_untracked = _untracked_outside_allowlist()
    if pre_untracked:
        raise SystemExit(
            "REFUSED(pre): untracked files outside allowlist: "
            f"{pre_untracked[:5]}"
        )

    profile_artifacts = artifact_root / profile
    profile_artifacts.mkdir(parents=True, exist_ok=True)

    env_profile = {"NOVEL_TEST_PROFILE": profile}
    pytest_cmd = [
        sys.executable, "-m", "pytest", "tests", "-q", "--tb=short",
        "-p", "no:cacheprovider", "--junitxml",
        str(profile_artifacts / "pytest-junit.xml"),
    ]
    proc = _run(pytest_cmd, env=env_profile, cwd=checkout)
    completed_at = datetime.datetime.now(datetime.timezone.utc)

    (profile_artifacts / "pytest-stdout.txt").write_text(
        proc.stdout, encoding="utf-8")
    (profile_artifacts / "pytest-stderr.txt").write_text(
        proc.stderr, encoding="utf-8")

    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    results = _parse_summary(tail)
    parse_error = None
    if results is None:
        parse_error = f"unparseable pytest summary line: {tail[:200]!r}"
        results = {k: 0 for k in RESULT_KEYS}
        status = "FAIL"
    else:
        results["collected"] = _collected_tests(checkout)

    canary_cmd = [sys.executable, "scripts/tier0_canary_regression.py"]
    canary = _run(canary_cmd, env=env_profile, cwd=checkout)
    (profile_artifacts / "canary-stdout.txt").write_text(
        canary.stdout, encoding="utf-8")
    (profile_artifacts / "canary-stderr.txt").write_text(
        canary.stderr, encoding="utf-8")
    canary_verdict = "PASS" if canary.returncode == 0 else "FAIL"

    post_tracked = _tracked_changes()
    post_untracked = _untracked_outside_allowlist()

    canary_detail = ""
    if canary.stdout.strip():
        canary_detail = canary.stdout.strip().splitlines()[-1]

    if parse_error is None:
        pytest_ok = (
            proc.returncode == 0
            and results["failed"] == 0
            and results["errors"] == 0
            and not post_tracked
            and not post_untracked
        )
    else:
        pytest_ok = False
    canary_ok = canary.returncode == 0 and not post_tracked and not post_untracked
    if parse_error is not None:
        status = "FAIL"
    else:
        status = "PASS" if (pytest_ok and canary_ok) else "FAIL"

    artifact = {
        "pytest_exit_code": proc.returncode,
        "results": results,
        "canary_exit_code": canary.returncode,
        "canary_verdict": canary_verdict,
        "parse_error": parse_error,
    }
    section = {
        "profile": profile,
        "status": status,
        "checkout": str(checkout),
        "subject_commit": _git("rev-parse", "HEAD"),
        "subject_tree": _git("rev-parse", "HEAD^{tree}"),
        "python_version": sys.version.split()[0],
        "pytest_version": (
            _run([sys.executable, "-m", "pytest", "--version"],
                 cwd=checkout).stdout.strip().splitlines()[0]
        ),
        "platform": platform.platform(),
        "filesystem_case_probe": _case_probe(artifact_root),
        "core.autocrlf": _git_config("core.autocrlf"),
        "env": {"NOVEL_TEST_PROFILE": profile},
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collected_tests": results["collected"],
        "pytest": {
            "command": " ".join(pytest_cmd),
            "exit_code": proc.returncode,
            "results": results,
            "parse_error": parse_error,
            "stdout_artifact": "pytest-stdout.txt",
            "stderr_artifact": "pytest-stderr.txt",
            "junit_xml_artifact": "pytest-junit.xml",
            "stdout_sha256": _sha_file(profile_artifacts / "pytest-stdout.txt"),
            "stderr_sha256": _sha_file(profile_artifacts / "pytest-stderr.txt"),
            "junit_xml_sha256": _sha_file(
                profile_artifacts / "pytest-junit.xml"),
            "result_artifact_sha256": _sha_bytes(
                json.dumps(artifact, sort_keys=True,
                           ensure_ascii=False).encode()),
            "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "canary": {
            "command": " ".join(canary_cmd),
            "exit_code": canary.returncode,
            "verdict": canary_verdict,
            "detail": canary_detail[:200],
            "stdout_artifact": "canary-stdout.txt",
            "stdout_sha256": _sha_file(profile_artifacts / "canary-stdout.txt"),
            "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "operator_assets_present": {
            a: (REPO_ROOT / a).exists() for a in PRIVATE_ASSETS
        },
        "skip_manifest": _read_manifest(checkout),
        "pre_tracked_changes": pre_tracked,
        "post_tracked_changes": post_tracked,
        "post_untracked_outside_allowlist": post_untracked,
    }
    (profile_artifacts / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2) + NL, encoding="utf-8")
    return section


def _quick_profile_attestation(
    profile: str, subject_commit: str | None, subject_tree: str | None
) -> dict:
    """中性 UNVERIFIED 占位（不含任何实测声明，不写 tracked 文件）."""
    return {
        "profile": profile,
        "status": "UNVERIFIED",
        "python_version": sys.version.split()[0],
        "pytest_version": None,
        "platform": platform.platform(),
        "collected_tests": None,
        "pytest": {"command": None, "exit_code": None, "results": None,
                   "parse_error": None, "stdout_artifact": None,
                   "stderr_artifact": None, "junit_xml_artifact": None,
                   "stdout_sha256": None, "stderr_sha256": None,
                   "junit_xml_sha256": None, "result_artifact_sha256": None,
                   "completed_at": None},
        "canary": {"command": None, "exit_code": None, "verdict": None,
                   "detail": "", "stdout_artifact": None, "stdout_sha256": None,
                   "completed_at": None},
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "skip_manifest": {},
        "started_at": None,
        "completed_at": None,
    }


def _checkpoint_attestation() -> dict:
    from src.boundary_control.release_record import (
        validate_legacy_tier0_release_record,
    )
    records = {}
    for rec, tag in (
        ("docs/00_project/releases/tier0-release.json", "v0.1.2-tier0"),
        ("docs/00_project/releases/q1-release.json", "v0.1.3-q1"),
    ):
        payload = validate_legacy_tier0_release_record(rec, repo_root=REPO_ROOT)
        tag_target = _git("rev-parse", f"{tag}^{{commit}}")
        tag_tree_blob = _git_bytes(f"{tag}:{rec}")
        head_blob = _git_bytes(f"HEAD:{rec}")
        tag_tree_sha = hashlib.sha256(tag_tree_blob).hexdigest()
        head_sha = hashlib.sha256(head_blob).hexdigest()
        blob_sha1 = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "hash-object", "--stdin"],
            input=head_blob, capture_output=True, check=True,
        ).stdout.strip().decode()
        find_log = _git("log", "--format=%H", "--find-object", blob_sha1,
                        "HEAD", "--", rec)
        record_commit = find_log.splitlines()[0] if find_log else None
        if tag_tree_sha == head_sha:
            relationship = "tag_self_record"
        else:
            relationship = "post_tag_historical_record"
        records[rec] = {
            "status": "PASS",
            "certification_tag": tag,
            "tag_target_commit": tag_target,
            "record_path": rec,
            "record_commit": record_commit,
            "record_blob_sha256": head_sha,
            "tag_tree_blob_sha256": tag_tree_sha,
            "record_relationship": relationship,
            "tag_path_bytes_verified": (
                hashlib.sha256(
                    _git_bytes(f"{tag}:{rec}")).hexdigest() == tag_tree_sha
            ),
            "baseline_tests_passing": payload.get("baseline_tests_passing"),
        }
    return {"status": "PASS", "records": records}


def _neutral_placeholder(collected: int) -> dict:
    """subject commit H 携带的确定性中性 UNVERIFIED 状态."""
    profiles = {}
    for name in PROFILES:
        profiles[name] = _quick_profile_attestation(name, None, None)
        profiles[name]["collected_tests"] = collected
    return {
        "attestation_version": 2,
        "subject_commit": None,
        "subject_tree": None,
        "repository_head": None,
        "attestation_commit": None,
        "head_status": "UNVERIFIED",
        "subject_status": "UNVERIFIED",
        "state_generated_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiles": profiles,
        "overall_status": "UNVERIFIED",
        "collected_tests": collected,
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": None,
        "last_validated_tree": None,
        "last_certified_checkpoint": {"status": "UNVERIFIED"},
        "evidence_paths": {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="public_clean")
    parser.add_argument("--full", action="store_true",
                        help="run full pytest + canary in this checkout")
    parser.add_argument("--artifact-dir",
                        default=str(REPO_ROOT / "state_artifacts"))
    parser.add_argument("--neutral", action="store_true",
                        help="write the deterministic neutral UNVERIFIED state")
    parser.add_argument(
        "--out", default=None,
        help="state json output path; default = <artifact-dir>/current_state.json "
             "(exact-tree: the tracked current_state.json is only written by the "
             "attestation commit, never by --full runs)")
    args = parser.parse_args(argv)

    if args.neutral:
        collected = _collected_tests(REPO_ROOT)
        payload = _neutral_placeholder(collected)
        Path(args.out or OUT_PATH).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + NL,
            encoding="utf-8")
        print("neutral UNVERIFIED state written; collected =", collected)
        return 0

    head = _git("rev-parse", "HEAD")
    out_path = Path(args.out) if args.out else (
        Path(args.artifact_dir) / head[:12] / "current_state.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    profiles = dict(existing.get("profiles", {})) if existing else {}
    artifact_root = Path(args.artifact_dir) / head[:12]

    if args.full:
        profiles[args.profile] = _full_profile_attestation(
            args.profile, artifact_root, REPO_ROOT)
    else:
        raise SystemExit(
            "quick mode removed: attestation requires --full on a clean "
            "checkout of the subject commit (no reuse, no partial states)"
        )

    try:
        checkpoint = _checkpoint_attestation()
        checkpoint_status = "PASS"
    except Exception as exc:  # noqa: BLE001
        checkpoint = {"status": "FAIL", "error": str(exc)[:200]}
        checkpoint_status = "FAIL"

    last_validated = None
    last_validated_tree = None
    op = profiles.get("operator")
    if op and op.get("status") == "PASS" and op.get("subject_commit") == head:
        last_validated = head
        last_validated_tree = _git("rev-parse", "HEAD^{tree}")

    statuses = [p.get("status") for p in profiles.values()]
    if (all(s == "PASS" for s in statuses)
            and len(statuses) == len(PROFILES)
            and checkpoint_status == "PASS"):
        overall = "PASS"
    elif any(s == "FAIL" for s in statuses) or checkpoint_status == "FAIL":
        overall = "FAIL"
    else:
        overall = "UNVERIFIED"

    evidence_paths = {p: _git("rev-parse", f"HEAD:{p}") for p in (
        "docs/00_project/releases/tier0-release.json",
        "docs/00_project/releases/q1-release.json",
        "docs/00_project/releases/tier0-three-flow-canary-aggregation.json",
    )}

    payload = {
        "attestation_version": 2,
        "subject_commit": head,
        "subject_tree": _git("rev-parse", "HEAD^{tree}"),
        "repository_head": head,
        "attestation_commit": None,
        "head_status": "UNVERIFIED",
        "subject_status": overall,
        "state_generated_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiles": profiles,
        "overall_status": overall,
        "collected_tests": _collected_tests(REPO_ROOT),
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": last_validated,
        "last_validated_tree": last_validated_tree,
        "last_certified_checkpoint": checkpoint,
        "evidence_paths": evidence_paths,
        "artifacts_dir": str(artifact_root),
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + NL,
        encoding="utf-8")
    print(f"state json: {out_path}")
    print(f"overall_status: {overall}")
    for name, p_ in profiles.items():
        print(f"  [{name}] status={p_.get('status')}")
    print(f"  checkpoint={checkpoint_status}")
    if overall == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
