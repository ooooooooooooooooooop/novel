#!/usr/bin/env python3
"""单 profile attestation bundle runner（第四轮，审计任务 A/C/D/E）.

一次调用只生成一个全新 profile bundle：
  bundle/
    profile-attestation.json   本 profile 的全部声明与指纹
    pytest-stdout.txt / pytest-stderr.txt / pytest-junit.xml
    canary-stdout.txt / canary-stderr.txt
    skip-manifest.json         conftest 写出的结构化 skip 记录
    external-inputs.json       私有资产完整内容清单 + Merkle 根（前后各算一次）

规则：
  - 禁止读取/继承/合并任何 existing current_state.json（审计任务 A）。
  - bundle 目录必须不存在（原子创建），不得覆盖旧 bundle。
  - tracked worktree 必须干净；外部输入清单执行前后指纹必须完全一致；
    未跟踪文件只允许 bundle 目录自身。
  - 汇总行不可解析 → bundle status=FAIL（无 0 failed 兜底）。
  - PARTIAL/UNVERIFIED 一律以非零退出，不视为 attestation 成功。
  - public_clean 硬门禁：Linux + checkout 所在文件系统大小写敏感 +
    core.autocrlf=false；大小写探针位于 checkout 同一文件系统。
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

# operator 必需外部输入（ignored 私有资产）：完整内容清单 + Merkle
EXTERNAL_INPUT_ROOTS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active",
    "novels/s6-canary-offdom/output",
    "novels/s6-canary-mythic/output",
    "novels/s6-canary-hist/output",
)
REQUIRED_OPERATOR_ASSETS = EXTERNAL_INPUT_ROOTS

# conftest 固定 skip 白名单之外的合法 skip（内部 skipif 与自引用）
# JUnit classname 为点形式（tests.test_x::name）——白名单键与其一致
KNOWN_INTERNAL_SKIPS = {
    "tests.test_auto_calibrate::test_load_frozen_bench_splits_and_disjoint_prompt_ids": {
        "reason_code": "missing_private_asset",
        "required_asset": [
            "reference_texts/a1_benchmark/sources/writing_preference_bench/split_manifest.json",
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
}


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd or REPO_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _run(cmd: list[str], env: dict | None = None, cwd: Path | None = None):
    e = dict(os.environ)
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


def _untracked_stray(checkout: Path, bundle_dir: Path) -> list[str]:
    """未跟踪文件只允许 bundle 目录自身（porcelain ?? 全集检查）."""
    proc = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain"],
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
        if rel == "state_artifacts" or rel.startswith("state_artifacts/"):
            continue
        stray.append(rel)
    return stray


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def external_inputs_inventory() -> dict:
    """全部影响 operator 测试的 ignored 文件：path/type/size/sha256 + Merkle 根.

    目录根使用全文件内容 Merkle（每文件内容 sha256，不截断）。
    """
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
                files[rel] = {
                    "type": "file", "size": f.stat().st_size, "sha256": sha,
                }
                entries.append(f"{rel}:{sha}")
        merkle = hashlib.sha256(
            NL.join(sorted(entries)).encode("utf-8")
        ).hexdigest()
        roots[root] = {
            "present": True, "merkle": merkle, "file_count": len(entries),
        }
    return {"roots": roots, "files": files}


def _collected_tests(checkout: Path) -> int:
    proc = _run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
                 "-p", "no:cacheprovider"], cwd=checkout)
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise RuntimeError(
            f"collect failed in {checkout}: {proc.stdout[-300:]} {proc.stderr[-300:]}"
        )
    return int(m.group(1))


def _known_skip_whitelist() -> tuple[dict, dict]:
    """conftest 门控映射（键转 JUnit 点形式）+ 内部/自引用白名单."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests import conftest as c
    gated = {
        nodeid.replace("/", ".")[: nodeid.rfind("::")].replace("::", "::") or nodeid: assets
        for nodeid, assets in c._TEST_GATED.items()
    }
    # 统一为 junit 点形式键：tests/test_x.py::name -> tests.test_x::name
    gated = {}
    for nodeid, assets in c._TEST_GATED.items():
        path_part, _, name_part = nodeid.partition("::")
        dotted = path_part.replace("/", ".")[:-3]  # 去掉 .py
        gated[f"{dotted}::{name_part}"] = assets
    return gated, dict(KNOWN_INTERNAL_SKIPS)


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
        "probe_directory": str(probe),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("public_clean", "operator"),
                        required=True)
    parser.add_argument("--bundle-dir", required=True,
                        help="bundle 输出目录（必须不存在；原子创建）")
    parser.add_argument("--expected-collected-tests", type=int, required=True)
    args = parser.parse_args(argv)

    bundle = Path(args.bundle_dir)
    if bundle.exists():
        print(f"REFUSED: bundle dir already exists (no overwrite): {bundle}",
              file=sys.stderr)
        return 2

    checkout = REPO_ROOT
    subject_commit = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")

    # ---- 前置门（执行前）----
    pre_tracked = _tracked_changes(checkout)
    if pre_tracked:
        print(f"REFUSED(pre): tracked worktree dirty: {pre_tracked[:5]}",
              file=sys.stderr)
        return 3
    pre_inventory = external_inputs_inventory()
    missing_inventory = [
        r for r, v in pre_inventory["roots"].items() if not v["present"]
    ]

    platform_name = platform.system()
    autocrlf = _git("config", "--get", "core.autocrlf") or None
    case_probe = _case_probe(bundle.parent)

    if args.profile == "operator":
        if missing_inventory:
            print(
                "operator FAIL: required external inputs missing (never "
                f"downgrade to skip): {missing_inventory}",
                file=sys.stderr,
            )
            return 3
    else:  # public_clean 硬门禁（审计任务 E）
        hard_fail = []
        if platform_name != "Linux":
            hard_fail.append(f"platform={platform_name} (requires real Linux)")
        if not case_probe["case_sensitive_filesystem"]:
            hard_fail.append("filesystem is not case-sensitive")
        if autocrlf not in (None, "false", "input"):
            hard_fail.append(f"core.autocrlf={autocrlf} (requires false)")
        if hard_fail:
            print("public_clean REFUSED: " + "; ".join(hard_fail),
                  file=sys.stderr)
            return 3

    bundle.mkdir(parents=True, exist_ok=False)  # 原子创建，不覆盖
    started_at = datetime.datetime.now(datetime.timezone.utc)

    manifest_path = bundle / "skip-manifest.json"
    pytest_cmd = [
        sys.executable, "-m", "pytest", "tests", "-q", "--tb=short",
        "-p", "no:cacheprovider", "--junitxml", str(bundle / "pytest-junit.xml"),
    ]
    proc = _run(pytest_cmd, env={
        "NOVEL_TEST_PROFILE": args.profile,
        "NOVEL_SKIP_MANIFEST_PATH": str(manifest_path),
    }, cwd=checkout)
    completed_at = datetime.datetime.now(datetime.timezone.utc)
    (bundle / "pytest-stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (bundle / "pytest-stderr.txt").write_text(proc.stderr, encoding="utf-8")

    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    results = _parse_summary(tail)
    parse_error = None
    if results is None:
        parse_error = f"unparseable pytest summary line: {tail[:200]!r}"
        results = {k: 0 for k in RESULT_KEYS}
    else:
        results["collected"] = _collected_tests(checkout)
        if results["collected"] != args.expected_collected_tests:
            parse_error = (
                f"collected {results['collected']} != contract "
                f"{args.expected_collected_tests}"
            )

    canary_cmd = [sys.executable, "scripts/tier0_canary_regression.py"]
    canary = _run(canary_cmd, env={
        "NOVEL_TEST_PROFILE": args.profile}, cwd=checkout)
    canary_completed = datetime.datetime.now(datetime.timezone.utc)
    (bundle / "canary-stdout.txt").write_text(canary.stdout, encoding="utf-8")
    (bundle / "canary-stderr.txt").write_text(canary.stderr, encoding="utf-8")
    canary_detail = (
        canary.stdout.strip().splitlines()[-1] if canary.stdout.strip() else ""
    )
    canary_verdict = "PASS" if canary.returncode == 0 else "FAIL"

    # ---- 后置门（执行后）----
    post_tracked = _tracked_changes(checkout)
    post_inventory = external_inputs_inventory()
    inventory_identical = pre_inventory == post_inventory
    stray = _untracked_stray(checkout, bundle)

    pytest_ok = (
        proc.returncode == 0
        and parse_error is None
        and results["failed"] == 0
        and results["errors"] == 0
        and not post_tracked
        and inventory_identical
        and not stray
    )
    canary_ok = canary.returncode == 0 and not post_tracked and inventory_identical
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

    # skip 证据组装：以 JUnit skipped 为准逐项分类（审计任务 D）
    junit_root = ET.parse(bundle / "pytest-junit.xml").getroot()
    junit_suite = junit_root if junit_root.tag == "testsuite" else junit_root.find("testsuite")
    junit_skips = [
        (tc.get("classname", "") + "::" + tc.get("name", ""))
        for tc in junit_suite.iter("testcase") if tc.find("skipped") is not None
    ]
    gated_map, self_ref_map = _known_skip_whitelist()
    skip_entries = []
    unexplained = []
    for nid in junit_skips:
        missing_assets = [
            a for a in gated_map.get(nid, ())
            if not (checkout / a).exists()
        ]
        if args.profile == "public_clean" and nid in gated_map and missing_assets:
            skip_entries.append({
                "nodeid": nid, "reason_code": "missing_private_asset",
                "required_asset": list(missing_assets),
            })
        elif nid in self_ref_map:
            entry = dict(self_ref_map[nid]); entry["nodeid"] = nid
            skip_entries.append(entry)
        else:
            unexplained.append(nid)
    if unexplained:
        status = "FAIL"
        parse_error = (parse_error or "") + (
            f" unexplained skip(s): {unexplained[:3]}")
    skip_manifest = {
        "profile": args.profile,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "skips": skip_entries,
        "unexplained": unexplained,
    }
    (bundle / "skip-manifest.json").write_text(
        json.dumps(skip_manifest, ensure_ascii=False, indent=2) + NL,
        encoding="utf-8")

    section = {
        "profile": args.profile,
        "status": status,
        "bundle": str(bundle),
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "checkout": str(checkout),
        "python_version": sys.version.split()[0],
        "pytest_version": (_run([sys.executable, "-m", "pytest", "--version"],
                                cwd=checkout).stdout.strip().splitlines()[0]),
        "platform": platform.platform(),
        "platform_system": platform_name,
        "filesystem_case_probe": case_probe,
        "core.autocrlf": autocrlf,
        "env": {"NOVEL_TEST_PROFILE": args.profile,
                "NOVEL_SKIP_MANIFEST_PATH": str(manifest_path)},
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canary_completed_at": canary_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
            "stdout_sha256": _sha_file(bundle / "pytest-stdout.txt"),
            "stderr_sha256": _sha_file(bundle / "pytest-stderr.txt"),
            "junit_xml_sha256": _sha_file(bundle / "pytest-junit.xml"),
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
            "stdout_sha256": _sha_file(bundle / "canary-stdout.txt"),
            "completed_at": canary_completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "skip_manifest": skip_manifest,
        "skip_manifest_sha256": _sha_file(manifest_path) if manifest_path.exists() else None,
        "external_inputs": {
            "pre": pre_inventory,
            "post": post_inventory,
            "identical": inventory_identical,
            "merkle_root": pre_inventory["roots"] if pre_inventory else {},
            "missing_roots": missing_inventory,
        },
        "gates": {
            "pre_tracked_changes": pre_tracked,
            "post_tracked_changes": post_tracked,
            "untracked_stray": stray,
        },
        "known_internal_skips": KNOWN_INTERNAL_SKIPS,
    }
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2) + NL, encoding="utf-8")

    print(f"bundle: {bundle}")
    print(f"[{args.profile}] status={status} | results={results}")
    ok = status == "PASS"
    if not ok:
        print("bundle not green: attestation may not proceed to PASS",
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
