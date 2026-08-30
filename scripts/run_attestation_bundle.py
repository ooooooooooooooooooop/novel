#!/usr/bin/env python3
"""单 profile attestation bundle runner（第五轮，审计任务 A/B/C/D/E）.

exact-tree 与字节规则：
  - 一次调用只生成一个全新 profile bundle；bundle 目录必须是 checkout 内
    仓库相对路径，resolve 后不得逃逸；先写临时兄弟目录，全部成功后原子
    rename，不得覆盖旧 bundle。
  - artifact 一律 LF 原始字节（bytes 写入，NL=chr(10)），配合 .gitattributes
    的 state_artifacts/** -text：Windows 生成→Git 提交→Linux clone 重算一致。
  - tracked worktree 干净在 pytest 前后各验一次；未跟踪文件只允许 bundle
    目录自身；外部输入清单（完整内容 sha256 + Merkle）前后各算一次且必须
    完全一致（不提供 identical 布尔捷径）。
  - 汇总行不可解析 → status=FAIL（无 0 failed 兜底）；JUnit testcase 数与
    passed+skipped+failed+errors=collected 强制。
  - 环境净化：清除 PYTEST_ADDOPTS / PYTEST_PLUGINS / PYTHONPATH。
  - public_clean 硬门禁：platform=Linux、checkout 文件系统大小写敏感
    （探针位于 checkout 内）、core.autocrlf 精确等于 "false"、六个私有输入
    根全部缺席。operator：六个根全部在场且指纹记录。
  - 所有 subprocess/collect/checkpoint/artifact 写入结束后，再执行最终
    HEAD/tree/tracked-clean/未跟踪白名单/外部输入 Merkle 复核。
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
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NL = chr(10)
RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")
SUMMARY_WORD_RE = re.compile(r"(\d+) (passed|skipped|failed|error)")

EXTERNAL_INPUT_ROOTS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active",
    "novels/s6-canary-offdom/output",
    "novels/s6-canary-mythic/output",
    "novels/s6-canary-hist/output",
)
REQUIRED_OPERATOR_ASSETS = EXTERNAL_INPUT_ROOTS

KNOWN_INTERNAL_SKIPS = {
    "tests.test_auto_calibrate::test_load_frozen_bench_splits_and_disjoint_prompt_ids": {
        "reason_code": "missing_private_asset",
        "required_asset": [
            "reference_texts/a1_benchmark/sources/"
            "writing_preference_bench/split_manifest.json",
        ],
    },
    "tests.test_state_source_contract::test_attestation_protocol_diff_only_state_files": {
        "reason_code": "state_neutral_placeholder",
        "required_asset": [],
    },
    "tests.test_state_source_contract::test_profiles_rederived_from_raw_artifacts": {
        "reason_code": "state_neutral_placeholder",
        "required_asset": [],
    },
    "tests.test_state_source_contract_v5::test_operator_artifact_shas_match_git_blobs": {
        "reason_code": "state_neutral_placeholder",
        "required_asset": [],
    },
    "tests.test_state_source_contract_v5::test_canary_artifact_sha_matches_git_blob": {
        "reason_code": "state_neutral_placeholder",
        "required_asset": [],
    },
}

SANITIZED_ENV_KEYS = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH")


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd or REPO_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _run(cmd: list[str], env: dict | None = None, cwd: Path | None = None):
    e = {k: v for k, v in os.environ.items() if k not in SANITIZED_ENV_KEYS}
    if env:
        e.update(env)
    return subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, env=e
    )


def _tracked_changes(checkout: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain",
         "--untracked-files=no"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return ["<git status failed>"]
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _untracked_stray(checkout: Path, bundle_rel: str) -> list[str]:
    # --untracked-files=all：逐文件列出未跟踪文件，避免 git 把整个
    # state_artifacts/<subject>/ 目录折叠为一个 "??" 条目而误判 bundle 自身
    # 为杂散（第五轮反例：staging 目录被当成 stray）。
    proc = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain",
         "--untracked-files=all"],
        capture_output=True, text=True,
    )
    stray = []
    for line in proc.stdout.splitlines():
        if not line.startswith("??"):
            continue
        path = line[3:].strip().strip('"').replace("\\", "/").rstrip("/")
        rel = path
        checkout_prefix = str(checkout).replace("\\", "/").rstrip("/") + "/"
        if rel.startswith(checkout_prefix):
            rel = rel[len(checkout_prefix):]
        if rel == bundle_rel or rel.startswith(bundle_rel + "/"):
            continue
        stray.append(rel)
    return stray


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_lf(path: Path, text: str) -> str:
    data = text.replace("\r\n", NL).encode("utf-8")
    path.write_bytes(data)
    return _sha_bytes(data)


def external_inputs_inventory() -> dict:
    files = {}
    roots = {}
    for root in EXTERNAL_INPUT_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            roots[root] = {"present": False, "merkle": None, "file_count": 0}
            continue
        entries = []
        for f in sorted(base.rglob("*")):
            if f.is_file():
                rel = f.relative_to(REPO_ROOT).as_posix()
                sha = hashlib.sha256(f.read_bytes()).hexdigest()
                files[rel] = {"type": "file", "size": f.stat().st_size,
                              "sha256": sha}
                entries.append(f"{rel}:{sha}")
        merkle = hashlib.sha256(
            NL.join(sorted(entries)).encode("utf-8")).hexdigest()
        roots[root] = {"present": True, "merkle": merkle,
                       "file_count": len(entries)}
    return {"roots": roots, "files": files}


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


def _case_probe(checkout: Path) -> dict:
    """大小写探针：位于 checkout 同一文件系统内."""
    probe = checkout / "_case_probe_attest"
    probe.mkdir(parents=True, exist_ok=True)
    lower = probe / "a.txt"
    upper = probe / "A.TXT"
    for f in (lower, upper):
        if f.exists():
            f.unlink()
    lower.write_bytes(b"lower")
    upper.write_bytes(b"UPPER")
    both = (
        lower.exists() and upper.exists()
        and lower.read_bytes() == b"lower"
        and upper.read_bytes() == b"UPPER"
    )
    for f in (lower, upper):
        if f.exists():
            f.unlink()
    probe.rmdir()
    return {
        "a_txt_and_A_TXT_coexist": bool(both),
        "case_sensitive_filesystem": bool(both),
        "probe_directory": str(probe),
    }


def _collected_tests(checkout: Path) -> int:
    proc = _run([sys.executable, "-m", "pytest", "tests", "--collect-only",
                 "-q", "-p", "no:cacheprovider"], cwd=checkout)
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise RuntimeError(
            f"collect failed in {checkout}: {proc.stdout[-300:]} "
            f"{proc.stderr[-300:]}")
    return int(m.group(1))


def _known_skip_whitelist() -> tuple[dict, dict]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests import conftest as c
    gated = {}
    for nodeid, assets in c._TEST_GATED.items():
        path_part, _, name_part = nodeid.partition("::")
        dotted = path_part.replace("/", ".")[:-3]
        gated[f"{dotted}::{name_part}"] = assets
    return gated, dict(KNOWN_INTERNAL_SKIPS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("public_clean", "operator"),
                        required=True)
    parser.add_argument("--bundle-rel", required=True,
                        help="bundle 目录（checkout 内仓库相对路径，不得已存在）")
    parser.add_argument("--expected-collected-tests", type=int, required=True)
    args = parser.parse_args(argv)

    checkout = REPO_ROOT
    subject_commit = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")

    bundle_rel = args.bundle_rel.replace("\\", "/")
    if (bundle_rel.startswith("/") or ".." in bundle_rel.split("/")
            or ":" in bundle_rel):
        print(f"REFUSED: bundle-rel must be repo-relative without escape: "
              f"{bundle_rel}", file=sys.stderr)
        return 2
    resolved_bundle = (checkout / bundle_rel).resolve()
    checkout_resolved = checkout.resolve()
    if checkout_resolved not in resolved_bundle.parents:
        print(f"REFUSED: bundle dir escapes checkout: {resolved_bundle}",
              file=sys.stderr)
        return 2
    if resolved_bundle.exists():
        print(f"REFUSED: bundle dir already exists: {resolved_bundle}",
              file=sys.stderr)
        return 2

    # ---- 前置门 ----
    pre_tracked = _tracked_changes(checkout)
    if pre_tracked:
        print(f"REFUSED(pre): tracked worktree dirty: {pre_tracked[:5]}",
              file=sys.stderr)
        return 3
    pre_inventory = external_inputs_inventory()
    missing_roots = [r for r, v in pre_inventory["roots"].items()
                     if not v["present"]]

    platform_name = platform.system()
    autocrlf = _git("config", "--get", "core.autocrlf")
    case_probe = _case_probe(checkout)

    if args.profile == "public_clean":
        hard = []
        if platform_name != "Linux":
            hard.append(f"platform={platform_name} (requires real Linux)")
        if not case_probe["case_sensitive_filesystem"]:
            hard.append("checkout filesystem is not case-sensitive")
        if autocrlf != "false":
            hard.append(f"core.autocrlf={autocrlf!r} (requires exactly 'false')")
        present_roots = [r for r, v in pre_inventory["roots"].items()
                         if v["present"]]
        if present_roots:
            hard.append(f"private input roots present on public_clean: "
                        f"{present_roots}")
        if hard:
            print("public_clean REFUSED: " + "; ".join(hard), file=sys.stderr)
            return 3
    else:
        if missing_roots:
            print("operator FAIL: required external inputs missing (never "
                  f"downgrade to skip): {missing_roots}", file=sys.stderr)
            return 3

    # ---- 临时兄弟目录 → 原子 rename ----
    staging = resolved_bundle.parent / (
        resolved_bundle.name + ".staging-" + subject_commit[:8])
    if staging.exists():
        print(f"REFUSED: staging dir exists: {staging}", file=sys.stderr)
        return 2
    staging.mkdir(parents=True)
    started_at = datetime.datetime.now(datetime.timezone.utc)

    manifest_path = staging / "skip-manifest.json"
    pytest_cmd = [
        sys.executable, "-m", "pytest", "tests", "-q", "--tb=short",
        "-p", "no:cacheprovider", "--junitxml",
        str(staging / "pytest-junit.xml"),
    ]
    proc = _run(pytest_cmd, env={
        "NOVEL_TEST_PROFILE": args.profile,
        "NOVEL_SKIP_MANIFEST_PATH": str(manifest_path),
    }, cwd=checkout)
    completed_at = datetime.datetime.now(datetime.timezone.utc)

    stdout_sha = _write_lf(staging / "pytest-stdout.txt", proc.stdout)
    stderr_sha = _write_lf(staging / "pytest-stderr.txt", proc.stderr)

    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    results = _parse_summary(tail)
    parse_error = None
    if results is None:
        parse_error = f"unparseable pytest summary line: {tail[:200]!r}"
        results = {k: 0 for k in RESULT_KEYS}
    else:
        results["collected"] = _collected_tests(checkout)
        if results["collected"] != args.expected_collected_tests:
            parse_error = (f"collected {results['collected']} != contract "
                           f"{args.expected_collected_tests}")

    junit_cases = junit_failures = junit_errors = junit_skipped = 0
    junit_skips: list[str] = []
    junit_path = staging / "pytest-junit.xml"
    if junit_path.exists():
        jroot = ET.parse(junit_path).getroot()
        jsuite = jroot if jroot.tag == "testsuite" else jroot.find("testsuite")
        junit_cases = int(jsuite.get("tests", "0"))
        junit_failures = int(jsuite.get("failures", "0"))
        junit_errors = int(jsuite.get("errors", "0"))
        junit_skipped = int(jsuite.get("skipped", "0"))
        junit_skips = [
            (tc.get("classname", "") + "::" + tc.get("name", ""))
            for tc in jsuite.iter("testcase")
            if tc.find("skipped") is not None
        ]
    identity_ok = (
        junit_cases == results["collected"]
        and results["passed"] + results["skipped"] + results["failed"]
        + results["errors"] == results["collected"]
        and junit_failures == results["failed"]
        and junit_errors == results["errors"]
        and junit_skipped == results["skipped"]
    )
    if not identity_ok:
        parse_error = (parse_error or "") + "; junit/summary identity violated"

    canary_cmd = [sys.executable, "scripts/tier0_canary_regression.py"]
    canary = _run(canary_cmd, env={"NOVEL_TEST_PROFILE": args.profile},
                  cwd=checkout)
    canary_completed = datetime.datetime.now(datetime.timezone.utc)
    canary_stdout_sha = _write_lf(staging / "canary-stdout.txt", canary.stdout)
    _write_lf(staging / "canary-stderr.txt", canary.stderr)
    canary_verdict = "PASS" if canary.returncode == 0 else "FAIL"
    canary_detail = (
        canary.stdout.strip().splitlines()[-1] if canary.stdout.strip() else ""
    )

    # skip 证据：JUnit skipped 逐项分类
    gated_map, self_ref_map = _known_skip_whitelist()
    skip_entries = []
    unexplained = []
    for nid in junit_skips:
        missing = [a for a in gated_map.get(nid, ())
                   if not (checkout / a).exists()]
        if args.profile == "public_clean" and nid in gated_map and missing:
            skip_entries.append({"nodeid": nid,
                                 "reason_code": "missing_private_asset",
                                 "required_asset": list(missing)})
        elif nid in self_ref_map:
            entry = dict(self_ref_map[nid])
            entry["nodeid"] = nid
            skip_entries.append(entry)
        else:
            unexplained.append(nid)
    skip_manifest = {
        "profile": args.profile,
        "generated_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skips": skip_entries,
        "unexplained": unexplained,
    }
    manifest_sha = _write_lf(
        manifest_path,
        json.dumps(skip_manifest, ensure_ascii=False, indent=2))

    # ---- 后置清单 ----
    post_inventory = external_inputs_inventory()
    inventory_identical = pre_inventory == post_inventory

    # ---- 最终复核（所有 subprocess/写入完成后）----
    post_tracked = _tracked_changes(checkout)
    stray = _untracked_stray(checkout, bundle_rel)
    head_now = _git("rev-parse", "HEAD")
    tree_now = _git("rev-parse", "HEAD^{tree}")

    pytest_ok = (
        proc.returncode == 0
        and parse_error is None
        and results["failed"] == 0
        and results["errors"] == 0
        and not post_tracked
        and inventory_identical
        and not stray
        and head_now == subject_commit
        and tree_now == subject_tree
    )
    canary_ok = (canary.returncode == 0 and not post_tracked
                 and inventory_identical and head_now == subject_commit)
    if parse_error is not None or unexplained:
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
        "profile": args.profile,
        "status": status,
        "bundle_rel": bundle_rel,
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "checkout": str(checkout),
        "python_version": sys.version.split()[0],
        "pytest_version": (
            _run([sys.executable, "-m", "pytest", "--version"],
                 cwd=checkout).stdout.strip().splitlines()[0]),
        "platform": platform.platform(),
        "platform_system": platform_name,
        "filesystem_case_probe": case_probe,
        "core.autocrlf": autocrlf,
        "env_sanitized": list(SANITIZED_ENV_KEYS),
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collected_tests": results["collected"],
        "expected_collected_tests": args.expected_collected_tests,
        "pytest": {
            "command": " ".join(pytest_cmd),
            "exit_code": proc.returncode,
            "results": results,
            "parse_error": parse_error,
            "stdout": "pytest-stdout.txt",
            "stderr": "pytest-stderr.txt",
            "junit_xml": "pytest-junit.xml",
            "stdout_sha256": stdout_sha,
            "stderr_sha256": stderr_sha,
            "junit_xml_sha256": _sha_file(staging / "pytest-junit.xml"),
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
            "stdout": "canary-stdout.txt",
            "stdout_sha256": canary_stdout_sha,
            "completed_at": canary_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "skip_manifest": skip_manifest,
        "skip_manifest_sha256": manifest_sha,
        "external_inputs": {
            "pre": pre_inventory,
            "post": post_inventory,
            "identical": inventory_identical,
            "merkle_root": pre_inventory["roots"],
            "missing_roots": missing_roots,
        },
        "gates": {
            "pre_tracked_changes": pre_tracked,
            "post_tracked_changes": post_tracked,
            "untracked_stray": stray,
            "head_unchanged": head_now == subject_commit,
            "tree_unchanged": tree_now == subject_tree,
        },
    }
    (staging / "profile-attestation.json").write_bytes(
        json.dumps(section, ensure_ascii=False, indent=2).encode("utf-8"))

    resolved_bundle.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(resolved_bundle)  # 原子发布
    print(f"bundle: {bundle_rel}")
    print(f"[{args.profile}] status={status} | results={results}")
    if unexplained:
        print(f"  unexplained skips: {unexplained}", file=sys.stderr)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
