#!/usr/bin/env python3
"""独立 attestation 聚合器（第四轮，审计任务 B/F）.

只接受恰好两个 bundle（operator / public_clean），全部从 bundle 原始文件
重推导最终状态，绝不信任任何 JSON 里的 PASS 布尔：

  - 两 bundle subject_commit / subject_tree 完全一致，且等于当前 HEAD；
    profile 名互异且固定。
  - 重新计算全部 artifact SHA（stdout/stderr/junit/canary）。
  - 解析 JUnit XML 与 pytest stdout 汇总行，交叉核对
    passed/skipped/failed/errors/collected、exit code、collected 合同。
  - 提交的 profile-attestation.json 与内嵌 profile 段做规范 JSON 完全比较。
  - skip manifest：skip 数 == JUnit skipped 数；nodeid/reason_code/
    required_asset 严格匹配固定白名单（门控 15 + 内部 skipif + 自引用）。
  - 任一缺失/重复/额外 profile、FAIL、UNVERIFIED、字段冲突 → 拒绝（exit 1）。

输出 current_state.json（schema v3）：repository_head 改名
subject_checkout_head；overall_status 改名 subject_overall_status；
artifacts_dir 必须仓库相对且 resolve 后位于仓库内；carrier 身份以
subject..HEAD 协议差异 + head_status=UNVERIFIED 表达，不伪造自包含哈希。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NL = chr(10)

PROFILE_NAMES = ("operator", "public_clean")
RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")

# 固定 skip 白名单（与 scripts/run_attestation_bundle.py 保持一致）
GATED_SKIPS = {
    "tests/test_build_deepseek_active_bundle.py::test_build_produces_exactly_four_bundle_files",
    "tests/test_build_deepseek_active_bundle.py::test_build_is_idempotent_byte_stable",
    "tests/test_build_deepseek_active_bundle.py::test_build_output_has_no_forbidden_secrets",
    "tests/test_build_deepseek_active_bundle.py::test_build_requires_base_url_env",
    "tests/test_build_deepseek_active_bundle.py::test_build_derives_provider_identity_from_live_db",
    "tests/test_build_deepseek_active_bundle.py::test_build_refuses_non_deepseek_current_provider",
    "tests/test_build_deepseek_active_bundle.py::test_build_refuses_failover_current_provider",
    "tests/test_build_deepseek_active_bundle.py::test_build_frozen_thresholds_and_uncontaminated_split",
    "tests/test_build_deepseek_active_bundle.py::test_build_profile_passes_provider_profile_validation",
    "tests/test_build_deepseek_active_bundle.py::test_build_policy_passes_autonomous_policy_validation",
    "tests/test_build_deepseek_active_bundle.py::test_build_judge_roles_disable_thinking",
    "tests/test_build_deepseek_active_bundle.py::test_build_active_selector_points_only_deepseek",
    "tests/test_auto_calibrate.py::test_load_frozen_bench_rejects_sha256_mismatch",
    "tests/test_auto_calibrate.py::test_load_frozen_bench_splits_and_disjoint_prompt_ids",
    "tests/test_s7_long_run_judgment.py::test_green_report_excludes_gaps",
    "tests/test_a1_release_validation.py::test_g8_zero_committed_chapters_withholds",
}
SELF_REF_SKIPS = {
    "tests/test_state_source_contract.py::test_attestation_protocol_diff_only_state_files",
    "tests/test_state_source_contract.py::test_profiles_rederived_from_raw_artifacts",
    "tests/test_state_source_contract_v5.py::test_operator_artifact_shas_match_git_blobs",
    "tests/test_state_source_contract_v5.py::test_canary_artifact_sha_matches_git_blob",
}
# runner 的 KNOWN_INTERNAL_SKIPS 中以 missing_private_asset 分类、但不在
# conftest._TEST_GATED 中的内部门控测试；required_asset 以本固定映射为准
# （与 scripts/run_attestation_bundle.py::KNOWN_INTERNAL_SKIPS 一致）。
INTERNAL_GATED_ASSETS = {
    "tests/test_auto_calibrate.py::test_load_frozen_bench_splits_and_disjoint_prompt_ids": (
        "reference_texts/a1_benchmark/sources/"
        "writing_preference_bench/split_manifest.json",
    ),
}
def _norm_nodeid(nid: str) -> str:
    """JUnit 点形式与 pytest 斜杠形式统一为点形式（去 .py 后缀）."""
    path, _, name = nid.partition("::")
    path = path.replace("/", ".")
    if path.endswith(".py"):
        path = path[:-3]
    return f"{path}::{name}" if name else path


KNOWN_SKIP_NODEIDS = {_norm_nodeid(g) for g in (GATED_SKIPS | SELF_REF_SKIPS)}


class Reject(Exception):
    pass




def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _parse_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise Reject("junit xml has no testsuite")
    counts = {
        "tests": int(suite.get("tests", "0")),
        "failures": int(suite.get("failures", "0")),
        "errors": int(suite.get("errors", "0")),
        "skipped": int(suite.get("skipped", "0")),
    }
    nodeids = []
    for tc in suite.iter("testcase"):
        nodeid = (tc.get("classname", "") + "::" + tc.get("name", "")).replace(
            ".py::", ".py::")
        nodeids.append(nodeid)
        if tc.find("failure") is not None:
            counts["failures"] += 0  # already counted by attribute
    return {"counts": counts, "skipped_nodeids": [
        (tc.get("classname", "") + "::" + tc.get("name", ""))
        for tc in suite.iter("testcase") if tc.find("skipped") is not None
    ]}


def _collect_count(checkout: Path) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(checkout), capture_output=True, text=True,
    )
    m = re.search(r"(\d+) tests collected", proc.stdout)
    if proc.returncode != 0 or not m:
        raise Reject(f"collect failed: {proc.stdout[-200:]}")
    return int(m.group(1))


def verify_results_identity(results: dict, collected_contract: int) -> None:
    """结果五元组恒等式 + collected 合同（供聚合器与对抗测试共用）."""
    if tuple(results) != RESULT_KEYS:
        raise Reject(f"results fields must be {RESULT_KEYS}")
    total = (results["passed"] + results["skipped"] + results["failed"]
             + results["errors"])
    if total != results["collected"]:
        raise Reject(
            f"passed({results['passed']}) + skipped({results['skipped']}) + "
            f"failed({results['failed']}) + errors({results['errors']}) != "
            f"collected({results['collected']})"
        )
    if results["collected"] != collected_contract:
        raise Reject(
            f"collected {results['collected']} != contract "
            f"{collected_contract}"
        )


def verify_pass_semantics(section: dict) -> None:
    """status=PASS 的完整语义（供聚合器与对抗测试共用）."""
    if section["status"] != "PASS":
        return
    if section["pytest"]["exit_code"] != 0:
        raise Reject("PASS with nonzero pytest exit")
    r = section["pytest"]["results"]
    if r["failed"] or r["errors"]:
        raise Reject("PASS with failed/errors != 0")
    if section["canary"]["exit_code"] != 0 or section["canary"]["verdict"] != "PASS":
        raise Reject("PASS with failed canary")
    if section["gates"]["post_tracked_changes"]:
        raise Reject("PASS with dirty tracked worktree after run")
    if section["gates"]["untracked_stray"]:
        raise Reject("PASS with untracked strays")
    if not section["gates"].get("head_unchanged"):
        raise Reject("PASS with HEAD drift during run")
    if not section["gates"].get("tree_unchanged"):
        raise Reject("PASS with tree drift during run")
    if section["external_inputs"]["pre"] != section["external_inputs"]["post"]:
        raise Reject("PASS with external-input drift")


def verify_merkle_inventory(inventory: dict) -> None:
    """从 files 清单重算每个根的 Merkle（供聚合器与对抗测试共用）."""
    for root_name, meta in inventory["roots"].items():
        if not meta["present"]:
            continue
        entries = []
        for rel, info in inventory["files"].items():
            if rel.startswith(root_name + "/"):
                entries.append(f"{rel}:{info['sha256']}")
        recomputed = hashlib.sha256(
            NL.join(sorted(entries)).encode("utf-8")).hexdigest()
        if recomputed != meta["merkle"]:
            raise Reject(
                f"Merkle recompute mismatch ({root_name}): "
                f"{meta['merkle'][:12]} vs {recomputed[:12]}"
            )


def _load_bundle(path: Path, expected_profile: str) -> dict:
    path = Path(path)
    att = path / "profile-attestation.json"
    required = (
        "pytest-stdout.txt", "pytest-stderr.txt", "pytest-junit.xml",
        "canary-stdout.txt", "canary-stderr.txt", "skip-manifest.json",
        "profile-attestation.json",
    )
    missing = [f for f in required if not (path / f).exists()]
    if missing:
        raise Reject(f"{expected_profile} bundle missing file(s): {missing}")
    section = json.loads(att.read_text(encoding="utf-8"))
    if section.get("profile") != expected_profile:
        raise Reject(
            f"bundle profile mismatch: expected {expected_profile}, "
            f"got {section.get('profile')!r}"
        )
    return {"section": section, "path": path, "files": {
        f: _sha_file(path / f) for f in required
    }}


def _verify_profile(bundle: dict, expected_collected: int,
                    checkout: Path) -> dict:
    section = bundle["section"]
    files = bundle["files"]
    name = section["profile"]

    # 0) subject_commit/tree 必须等于当前 HEAD 与其 tree（审计任务 B）
    if section.get("subject_commit") != _git("rev-parse", "HEAD"):
        raise Reject(f"{name}: bundle subject_commit != HEAD")
    if section.get("subject_tree") != _git("rev-parse", "HEAD^{tree}"):
        raise Reject(f"{name}: bundle subject_tree != HEAD^{{tree}}")

    # 0b) 平台/autocrlf/大小写探针/私有根在场-缺席 复验（审计任务 C）
    if name == "public_clean":
        if section.get("platform_system") != "Linux":
            raise Reject(f"{name}: platform_system != Linux")
        if not section["filesystem_case_probe"].get(
                "case_sensitive_filesystem"):
            raise Reject(f"{name}: case probe not sensitive")
        if section.get("core.autocrlf") != "false":
            raise Reject(f"{name}: core.autocrlf != false")
        for r, v in section["external_inputs"]["pre"]["roots"].items():
            if v["present"]:
                raise Reject(f"{name}: private root present: {r}")
    else:
        for r, v in section["external_inputs"]["pre"]["roots"].items():
            if not v["present"]:
                raise Reject(f"{name}: operator root missing: {r}")

    # 1) 提交的 profile-attestation.json 与内嵌 profile 段规范 JSON 完全比较
    committed = json.loads((bundle["path"] / "profile-attestation.json").read_text(
        encoding="utf-8"))
    if json.dumps(committed, sort_keys=True) != json.dumps(
            section, sort_keys=True):
        raise Reject(
            f"{name}: committed profile-attestation.json differs from embedded "
            "profile section"
        )

    # 2) artifact SHA 重算
    for key, fname in (
        ("stdout_sha256", "pytest-stdout.txt"),
        ("stderr_sha256", "pytest-stderr.txt"),
        ("junit_xml_sha256", "pytest-junit.xml"),
    ):
        if files[fname] != section["pytest"][key]:
            raise Reject(f"{name}: {fname} SHA mismatch")
    if files["canary-stdout.txt"] != section["canary"]["stdout_sha256"]:
        raise Reject(f"{name}: canary-stdout.txt SHA mismatch")

    # 2b) result_artifact_sha256 重推导（审计任务 C）：由 exit/结果向量独立重算
    artifact = {
        "pytest_exit_code": section["pytest"]["exit_code"],
        "results": section["pytest"]["results"],
        "canary_exit_code": section["canary"]["exit_code"],
        "canary_verdict": section["canary"]["verdict"],
        "parse_error": section["pytest"].get("parse_error"),
    }
    recomputed_artifact = _sha_bytes(
        json.dumps(artifact, sort_keys=True, ensure_ascii=False).encode())
    if recomputed_artifact != section["pytest"].get(
            "result_artifact_sha256"):
        raise Reject(
            f"{name}: result_artifact_sha256 mismatch (recomputed "
            f"{recomputed_artifact[:12]} != declared "
            f"{str(section['pytest'].get('result_artifact_sha256'))[:12]})"
        )

    # 3) JUnit 解析 + 交叉核对
    junit = _parse_junit(bundle["path"] / "pytest-junit.xml")
    results = section["pytest"]["results"]
    verify_results_identity(results, expected_collected)
    if junit["counts"]["tests"] != results["collected"]:
        raise Reject(
            f"{name}: junit tests({junit['counts']['tests']}) != "
            f"collected({results['collected']})"
        )
    if junit["counts"]["failures"] != results["failed"]:
        raise Reject(f"{name}: junit failures != results.failed")
    if junit["counts"]["errors"] != results["errors"]:
        raise Reject(f"{name}: junit errors != results.errors")
    if junit["counts"]["skipped"] != results["skipped"]:
        raise Reject(f"{name}: junit skipped != results.skipped")

    # 4) stdout 汇总行交叉核对
    stdout_tail = (bundle["path"] / "pytest-stdout.txt").read_text(
        encoding="utf-8").strip().splitlines()[-1]
    for word, key in (("passed", "passed"), ("failed", "failed"),
                      ("error", "errors"), ("skipped", "skipped")):
        m = re.search(rf"(\d+) {word}", stdout_tail)
        actual = int(m.group(1)) if m else 0
        if actual != results[key]:
            raise Reject(
                f"{name}: stdout summary {word}={actual} != recorded "
                f"{results[key]}"
            )

    # 5b) 外部输入 Merkle 直算（审计任务 C）：不信 identical 布尔
    verify_merkle_inventory(section["external_inputs"]["pre"])
    verify_merkle_inventory(section["external_inputs"]["post"])
    if section["external_inputs"]["pre"] != section["external_inputs"]["post"]:
        raise Reject(f"{name}: external-input inventory drifted pre->post")

    # 5) PASS 语义（共用校验器）
    verify_pass_semantics(section)

    # 6) skip 证据（审计任务 D）：raw manifest SHA + 规范 JSON 完全一致 +
    #    逐项严格映射
    raw_manifest = bundle["path"] / "skip-manifest.json"
    if section.get("skip_manifest_sha256") != _sha_file(raw_manifest):
        raise Reject(f"{name}: skip-manifest.json SHA mismatch")
    raw_obj = json.loads(raw_manifest.read_text(encoding="utf-8"))
    if raw_obj.get("unexplained"):
        raise Reject(f"{name}: manifest carries unexplained skips")
    manifest = section["skip_manifest"]
    if json.dumps(raw_obj, sort_keys=True) != json.dumps(
            manifest, sort_keys=True):
        raise Reject(
            f"{name}: raw skip-manifest.json differs from embedded section"
        )
    manifest_skips = manifest.get("skips", [])
    junit_skips = junit["skipped_nodeids"]
    if len(manifest_skips) != len(junit_skips):
        raise Reject(
            f"{name}: skip manifest count({len(manifest_skips)}) != "
            f"junit skipped({len(junit_skips)})"
        )
    manifest_ids = {_norm_nodeid(s["nodeid"]) for s in manifest_skips}
    for nid in junit_skips:
        nid_norm = _norm_nodeid(nid)
        if nid_norm not in KNOWN_SKIP_NODEIDS:
            raise Reject(f"{name}: unexplained junit skip: {nid}")
        if nid_norm not in manifest_ids:
            raise Reject(f"{name}: junit skip missing from manifest: {nid}")
    gated_norm = _gated_asset_map()
    selfref_norm = {_norm_nodeid(g) for g in SELF_REF_SKIPS}
    for s in manifest_skips:
        nid_norm = _norm_nodeid(s["nodeid"])
        code = s["reason_code"]
        if code == "missing_private_asset":
            if nid_norm not in gated_norm:
                raise Reject(f"{name}: gated skip not in whitelist: {s['nodeid']}")
            if set(s.get("required_asset", [])) != gated_norm[nid_norm]:
                raise Reject(
                    f"{name}: required_asset mismatch for {s['nodeid']}: "
                    f"{sorted(s.get('required_asset', []))}"
                )
        elif code == "state_neutral_placeholder":
            if nid_norm not in selfref_norm:
                raise Reject(f"{name}: self-ref skip not in whitelist: {s['nodeid']}")
        else:
            raise Reject(f"{name}: unexpected skip reason_code {code!r}")
    return section


def _gated_asset_map() -> dict[str, set[str]]:
    """固定门控资产映射：conftest._TEST_GATED 全量资产 + INTERNAL_GATED_ASSETS
    （规范化点形式 nodeid → 完整资产集），供 required_asset 逐项严格比对."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests import conftest as c
    mapping: dict[str, set[str]] = {
        _norm_nodeid(nid): set(assets)
        for nid, assets in c._TEST_GATED.items()
    }
    for nid, assets in INTERNAL_GATED_ASSETS.items():
        mapping.setdefault(_norm_nodeid(nid), set()).update(assets)
    return mapping


def _neutral_payload(collected: int, subject_tree: str | None) -> dict:
    """subject commit H 携带的确定性中性 UNVERIFIED 状态（无任何实测声明）."""
    profiles = {}
    for name in PROFILE_NAMES:
        profiles[name] = {
            "profile": name, "status": "UNVERIFIED",
            "collected_tests": collected,
            "pytest": {"command": None, "exit_code": None, "results": None},
            "canary": {"command": None, "exit_code": None, "verdict": None},
        }
    return {
        "attestation_version": 3,
        "subject_commit": None,
        "subject_tree": subject_tree,
        "subject_checkout_head": None,
        "attestation_commit": None,
        "carrier_binding": {
            "rule": ("diff subject..HEAD limited to current_state.json and "
                     "state_artifacts/**; carrier HEAD keeps "
                     "head_status=UNVERIFIED (cannot self-attest)"),
            "verified_by": "tests/test_state_source_contract.py",
        },
        "head_status": "UNVERIFIED",
        "subject_status": "UNVERIFIED",
        "subject_overall_status": "UNVERIFIED",
        "state_generated_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiles": profiles,
        "collected_tests": collected,
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": None,
        "last_validated_tree": None,
        "last_certified_checkpoint": {"status": "UNVERIFIED"},
        "evidence_paths": {
            p: _git("rev-parse", f"HEAD:{p}") for p in (
                "docs/00_project/releases/tier0-release.json",
                "docs/00_project/releases/q1-release.json",
                "docs/00_project/releases/tier0-three-flow-canary-aggregation.json",
            )
        },
        "artifacts_dir": "state_artifacts",
        "bundles": {},
    }


def _portable_bundle_rel(raw: str, label: str) -> Path:
    """bundle 参数必须仓库相对且可移植（审计任务 C）：禁止本机绝对路径、
    反斜杠、空段或逃逸段；入库时以 posix 斜杠形式记录."""
    p = raw.replace("\\", "/")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise Reject(
            f"{label} bundle path must be repo-relative and portable: {raw!r}")
    parts = p.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise Reject(
            f"{label} bundle path must not contain empty/escape segments: "
            f"{raw!r}")
    return Path(p)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neutral", action="store_true",
                        help="write the deterministic neutral UNVERIFIED state "
                             "(no bundles; for the subject commit itself)")
    parser.add_argument("--operator-bundle")
    parser.add_argument("--public-clean-bundle")
    parser.add_argument("--expected-collected-tests", type=int)
    parser.add_argument("--out", required=True,
                        help="输出 current_state.json（attestation 提交时拷入仓库根）")
    args = parser.parse_args(argv)

    if args.neutral:
        collected = _collect_count(REPO_ROOT)
        payload = _neutral_payload(collected, _git("rev-parse", "HEAD^{tree}"))
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + NL,
            encoding="utf-8")
        print("neutral UNVERIFIED state written; collected =", collected)
        return 0

    head = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")

    op_rel = _portable_bundle_rel(args.operator_bundle, "operator")
    pub_rel = _portable_bundle_rel(args.public_clean_bundle, "public_clean")
    op = _load_bundle(op_rel, "operator")
    pub = _load_bundle(pub_rel, "public_clean")

    if set(op["section"].get("subject_commit", "") for _ in [0]) and (
            op["section"]["subject_commit"] != pub["section"]["subject_commit"]):
        raise Reject("bundles disagree on subject_commit")
    if op["section"]["subject_tree"] != pub["section"]["subject_tree"]:
        raise Reject("bundles disagree on subject_tree")
    subject_commit = op["section"]["subject_commit"]
    if subject_commit != head:
        raise Reject(
            f"bundle subject {subject_commit[:12]} != repository HEAD {head[:12]}"
        )

    sections = {
        "operator": _verify_profile(op, args.expected_collected_tests, REPO_ROOT),
        "public_clean": _verify_profile(pub, args.expected_collected_tests,
                                        REPO_ROOT),
    }

    live_collected = _collect_count(REPO_ROOT)
    for name, s in sections.items():
        if s["collected_tests"] != args.expected_collected_tests:
            raise Reject(f"{name}: collected {s['collected_tests']} != contract "
                         f"{args.expected_collected_tests}")
    if live_collected != args.expected_collected_tests:
        raise Reject(f"live collected {live_collected} != contract "
                     f"{args.expected_collected_tests}")

    # checkpoint：自身 release contract + tag/tree/blob 拆分（commit:path 字节）
    checkpoint = _checkpoint_attestation()
    checkpoint_status = checkpoint["status"]

    statuses = {name: s["status"] for name, s in sections.items()}
    if (all(v == "PASS" for v in statuses.values())
            and checkpoint_status == "PASS"):
        overall = "PASS"
    elif any(v == "FAIL" for v in statuses.values()) or checkpoint_status == "FAIL":
        overall = "FAIL"
    else:
        overall = "UNVERIFIED"

    last_validated = subject_commit if overall == "PASS" else None
    last_validated_tree = subject_tree if overall == "PASS" else None

    payload = {
        "attestation_version": 3,
        "subject_commit": subject_commit,
        "subject_tree": subject_tree,
        "subject_checkout_head": subject_commit,
        "attestation_commit": None,
        "carrier_binding": {
            "rule": ("diff subject..HEAD limited to current_state.json and "
                     "state_artifacts/**; carrier HEAD keeps "
                     "head_status=UNVERIFIED (cannot self-attest)"),
            "verified_by": "tests/test_state_source_contract.py",
        },
        "head_status": "UNVERIFIED",
        "subject_status": overall,
        "state_generated_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiles": sections,
        "subject_overall_status": overall,
        "collected_tests": live_collected,
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": last_validated,
        "last_validated_tree": last_validated_tree,
        "last_certified_checkpoint": checkpoint,
        "evidence_paths": {
            p: _git("rev-parse", f"HEAD:{p}") for p in (
                "docs/00_project/releases/tier0-release.json",
                "docs/00_project/releases/q1-release.json",
                "docs/00_project/releases/tier0-three-flow-canary-aggregation.json",
            )
        },
        "artifacts_dir": f"state_artifacts/{subject_commit[:12]}",
        "bundles": {
            "operator": op_rel.as_posix(),
            "public_clean": pub_rel.as_posix(),
        },
    }
    out_file = Path(args.out)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + NL,
        encoding="utf-8")
    print(f"subject_overall_status: {overall}")
    for name, s in statuses.items():
        print(f"  [{name}] {s}")
    print(f"  checkpoint={checkpoint_status}")
    return 0 if overall == "PASS" else 1


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
        relationship = ("tag_self_record" if tag_tree_sha == head_sha
                        else "post_tag_historical_record")
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


def _git_bytes(rev_path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "blob", rev_path],
        capture_output=True, check=True,
    ).stdout


if __name__ == "__main__":
    raise SystemExit(main())
