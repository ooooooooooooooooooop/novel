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
    ], "skipped_messages": {
        (tc.get("classname", "") + "::" + tc.get("name", "")):
        (tc.find("skipped").get("message") or "")[:200]
        for tc in suite.iter("testcase") if tc.find("skipped") is not None
    }}


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
    gates = section.get("gates") or {}
    if "post_worktree" in gates:
        w = gates["post_worktree"]
        if w.get("tracked") or w.get("untracked") or w.get("ignored"):
            raise Reject("PASS with dirty worktree after run")
    else:
        # 第五轮旧结构（synthetic/历史）：tracked/untracked 兼容路径
        if gates.get("post_tracked_changes"):
            raise Reject("PASS with dirty tracked worktree after run")
        if gates.get("untracked_stray"):
            raise Reject("PASS with untracked strays")
    if not gates.get("head_unchanged"):
        raise Reject("PASS with HEAD drift during run")
    if not gates.get("tree_unchanged"):
        raise Reject("PASS with tree drift during run")
    if section["external_inputs"]["pre"] != section["external_inputs"]["post"]:
        raise Reject("PASS with external-input drift")


EXTERNAL_INPUT_ROOTS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active",
    "novels/s6-canary-offdom/output",
    "novels/s6-canary-mythic/output",
    "novels/s6-canary-hist/output",
)


def verify_merkle_inventory(inventory: dict,
                            expected_roots: tuple[str, ...] = EXTERNAL_INPUT_ROOTS
                            ) -> None:
    """六根键集合精确相等 + 逐项 file_count/type/size/SHA/Merkle 重算（第六轮 C）：
    拒绝未知根、缺失根、absent 根下残留文件、清单内自相矛盾."""
    roots = inventory["roots"]
    files = inventory["files"]
    got_keys = set(roots)
    if got_keys != set(expected_roots):
        raise Reject(
            f"external-input roots set mismatch: got {sorted(got_keys)} "
            f"expected {list(expected_roots)}"
        )
    for rel in files:
        if not any(rel.startswith(root + "/") for root in expected_roots):
            raise Reject(f"external-input file outside any known root: {rel}")
    for root_name, meta in roots.items():
        if not meta["present"]:
            # absent 根下不得残留文件条目（第六轮反例 3/6）
            if any(rel.startswith(root_name + "/") for rel in files):
                raise Reject(
                    f"{root_name}: files present under absent root")
            if meta.get("file_count", 0) != 0 or meta.get("merkle") is not None:
                raise Reject(f"{root_name}: absent root must have "
                             f"file_count=0 and merkle=null")
            continue
        entries = []
        for rel, info in files.items():
            if not rel.startswith(root_name + "/"):
                continue
            if not isinstance(info, dict):
                raise Reject(f"{root_name}: malformed file entry {rel}")
            if info.get("type") != "file":
                raise Reject(f"{root_name}: unknown file type {rel}: "
                             f"{info.get('type')!r}")
            size = info.get("size")
            sha = info.get("sha256")
            if not isinstance(size, int) or size < 0:
                raise Reject(f"{root_name}: bad size {rel}: {size!r}")
            if not isinstance(sha, str) or len(sha) != 64:
                raise Reject(f"{root_name}: bad sha {rel}: {sha!r}")
            entries.append(f"{rel}:{sha}:{size}:file")
        if len(entries) != meta.get("file_count"):
            raise Reject(
                f"{root_name}: file_count {meta.get('file_count')} != "
                f"inventory {len(entries)}")
        recomputed = hashlib.sha256(
            NL.join(sorted(entries)).encode("utf-8")).hexdigest()
        if recomputed != meta.get("merkle"):
            raise Reject(
                f"Merkle recompute mismatch ({root_name}): "
                f"{str(meta.get('merkle'))[:12]} vs {recomputed[:12]}"
            )


def _resolve_bundle_path(raw: str | Path, label: str, repo_root: Path) -> Path:
    """bundle 路径必须仓库相对 posix、resolve 后位于仓库内、且不得经 symlink
    指向仓库外（第六轮 C：路径锚定 REPO_ROOT + 拒绝 symlink）。"""
    p_str = str(raw).replace("\\", "/")
    p = Path(p_str)
    if p.is_absolute() or p_str.startswith("/") or re.match(
            r"^[A-Za-z]:", p_str):
        raise Reject(f"{label} bundle path must be repo-relative: {raw!r}")
    segs = p_str.split("/")
    if any(seg in ("", ".", "..") for seg in segs):
        raise Reject(
            f"{label} bundle path must not contain empty/escape segments: "
            f"{raw!r}")
    base = repo_root.resolve()
    naive = base / p
    exploded = naive.resolve()
    if base not in exploded.parents:
        raise Reject(
            f"{label} bundle path escapes repository: {raw!r} -> {exploded}")
    # resolve 改变了路径形态 => 存在 symlink 环节：一律拒绝（可指向仓库外）
    if str(exploded) != str(naive.absolute()):
        raise Reject(
            f"{label} bundle path must not traverse symlinks: {raw!r}")
    return exploded


def _load_bundle(path: str | Path, expected_profile: str,
                 repo_root: Path | None = None) -> dict:
    base = repo_root or REPO_ROOT
    path = _resolve_bundle_path(str(path), expected_profile, base)
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
                    checkout: Path,
                    expected_subject: str | None = None,
                    expected_tree: str | None = None) -> dict:
    section = bundle["section"]
    files = bundle["files"]
    name = section["profile"]

    # 0) subject_commit/tree：bundle 必须等于显式 subject（carrier 重演时用
    #    current_state.json 声明值；聚合时等于 HEAD）。禁止自比或空跑。
    if expected_subject is None:
        expected_subject = _git("rev-parse", "HEAD")
        expected_tree = _git("rev-parse", "HEAD^{tree}")
    if section.get("subject_commit") != expected_subject:
        raise Reject(f"{name}: bundle subject_commit != expected subject")
    if section.get("subject_tree") != expected_tree:
        raise Reject(f"{name}: bundle subject_tree != expected tree")

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

    # 0c) 可携带路径字段（第六轮 F）：仓库相对 POSIX，无反斜杠、非绝对
    for field in ("bundle_rel", "checkout_rel", "artifacts_rel"):
        value = section.get(field) or ""
        if "\\" in value or value.startswith(("/", "C:", "c:")):
            raise Reject(f"{name}: non-portable path {field}={value!r}")
    probe_dir = section["filesystem_case_probe"].get("probe_directory", "")
    if "\\" in str(probe_dir) or str(probe_dir).startswith("/"):
        raise Reject(f"{name}: non-portable probe_directory {probe_dir!r}")
    for key in ("stdout", "stderr", "junit_xml"):
        fname = section["pytest"].get(key, "")
        if fname and ("/" in fname or "\\" in fname):
            raise Reject(f"{name}: artifact name must be bare: {fname!r}")
    for key in ("stdout", "stderr"):
        fname = section["canary"].get(key, "")
        if fname and ("/" in fname or "\\" in fname):
            raise Reject(f"{name}: canary artifact name must be bare: {fname!r}")

    # 0d) 时间戳（第六轮 F）：动作真实时序，pytest/canary 各自 start<=done
    for tag in ("pytest", "canary"):
        s = section[tag]
        if s.get("started_at") and s.get("completed_at"):
            if s["started_at"] > s["completed_at"]:
                raise Reject(f"{name}: {tag} timestamps inverted")

    # 1) 提交的 profile-attestation.json 与内嵌 profile 段规范 JSON 完全比较
    committed = json.loads((bundle["path"] / "profile-attestation.json").read_text(
        encoding="utf-8"))
    if json.dumps(committed, sort_keys=True) != json.dumps(
            section, sort_keys=True):
        raise Reject(
            f"{name}: committed profile-attestation.json differs from embedded "
            "profile section"
        )

    # 2) artifact SHA 重算（含 canary stderr，第六轮 F）
    for key, fname in (
        ("stdout_sha256", "pytest-stdout.txt"),
        ("stderr_sha256", "pytest-stderr.txt"),
        ("junit_xml_sha256", "pytest-junit.xml"),
    ):
        if files[fname] != section["pytest"][key]:
            raise Reject(f"{name}: {fname} SHA mismatch")
    if files["canary-stdout.txt"] != section["canary"].get("stdout_sha256"):
        raise Reject(f"{name}: canary-stdout.txt SHA mismatch")
    if files["canary-stderr.txt"] != section["canary"].get("stderr_sha256"):
        raise Reject(f"{name}: canary-stderr.txt SHA mismatch")

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

    # 3) JUnit 解析 + 交叉核对（含 skipped message，第六轮 E）
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

    # 5b) 外部输入六根精确集合 + Merkle/逐项重算（第六轮 C）：不信 identical
    for stage in ("pre", "post"):
        verify_merkle_inventory(
            section["external_inputs"][stage], EXTERNAL_INPUT_ROOTS)
    if section["external_inputs"]["pre"] != section["external_inputs"]["post"]:
        raise Reject(f"{name}: external-input inventory drifted pre->post")

    # 5) PASS 语义（共用校验器）
    verify_pass_semantics(section)

    # 6) skip 证据（第六轮 E）：pytest 原生 manifest 不覆盖；raw SHA +
    #    规范 JSON + gated 映射 + JUnit skip message/reason 交叉核对
    raw_manifest = bundle["path"] / "skip-manifest.json"
    sec_skip = section.get("skip_manifest") or {}
    if sec_skip.get("native_manifest_sha256") != _sha_file(raw_manifest):
        raise Reject(f"{name}: skip-manifest.json SHA mismatch")
    raw_obj = json.loads(raw_manifest.read_text(encoding="utf-8"))
    if raw_obj.get("profile") != name:
        raise Reject(f"{name}: native manifest profile mismatch")
    if raw_obj.get("generated_at") != sec_skip.get("native_generated_at"):
        raise Reject(f"{name}: native manifest generated_at drift")
    expected_skips = {_norm_nodeid(s["nodeid"]) for s in
                      raw_obj.get("skips", [])}
    raw_skip_norm = [json.dumps(s, sort_keys=True)
                     for s in raw_obj.get("skips", [])]
    sec_skip_norm = [json.dumps(s, sort_keys=True)
                     for s in sec_skip.get("native_skips", [])]
    if raw_skip_norm != sec_skip_norm:
        raise Reject(f"{name}: native manifest skips drift vs section")
    gated_norm = _gated_asset_map()
    selfref_norm = {_norm_nodeid(g) for g in SELF_REF_SKIPS}
    for s in raw_obj.get("skips", []):
        nid_norm = _norm_nodeid(s["nodeid"])
        code = s.get("reason_code")
        if code == "missing_private_asset":
            if nid_norm not in gated_norm:
                raise Reject(
                    f"{name}: gated skip not in whitelist: {s['nodeid']}")
            if set(s.get("required_asset", [])) != gated_norm[nid_norm]:
                raise Reject(
                    f"{name}: required_asset mismatch for {s['nodeid']}: "
                    f"{sorted(s.get('required_asset', []))}")
        else:
            raise Reject(f"{name}: unexpected native skip reason {code!r}")
    if name == "operator" and raw_obj.get("skips"):
        raise Reject(f"{name}: operator native manifest must carry no gated "
                     f"skips (assets present): {raw_obj.get('skips')[:2]}")
    if name == "public_clean":
        # pytest 原生 manifest 只含 conftest._TEST_GATED 条目；internal
        # gated（KNOWN_INTERNAL_SKIPS）不在原生 manifest，由 JUnit 层核对。
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from tests import conftest as c
        conftest_gated = {_norm_nodeid(nid)
                          for nid in c._TEST_GATED}
        native_ids = {_norm_nodeid(s["nodeid"])
                      for s in raw_obj.get("skips", [])}
        for nid in conftest_gated:
            if nid not in native_ids:
                raise Reject(f"{name}: gated skip missing from native "
                             f"manifest: {nid}")

    # JUnit skipped：nodeid ∈ 固定映射；message/reason 按同规则重算并与
    # section 声明逐项一致（聚合器独立重演，不信 section 丢来的 bool）
    junit_classified = sec_skip.get("junit_classified") or []
    junit_skip_map = {_norm_nodeid(c.get("nodeid")): c for c in junit_classified}
    junit_skips = junit["skipped_nodeids"]
    if len(junit_classified) != len(junit_skips):
        raise Reject(
            f"{name}: junit_classified count({len(junit_classified)}) != "
            f"junit skipped({len(junit_skips)})")
    expected_set = (expected_skips | selfref_norm
                    | {_norm_nodeid(g) for g in INTERNAL_GATED_ASSETS})
    for nid in junit_skips:
        nid_norm = _norm_nodeid(nid)
        if nid_norm not in KNOWN_SKIP_NODEIDS:
            raise Reject(f"{name}: unexplained junit skip: {nid}")
        if nid_norm not in expected_set:
            raise Reject(f"{name}: junit skip not in expected mapping: {nid}")
        c = junit_skip_map.get(nid_norm)
        if c is None:
            raise Reject(f"{name}: junit skip missing from classified: {nid}")
        message = junit["skipped_messages"].get(nid, "")
        expected_reason = ("state_neutral_placeholder"
                           if nid_norm in selfref_norm
                           else "missing_private_asset")
        if c.get("expected_reason_code") != expected_reason:
            raise Reject(f"{name}: classified reason mismatch: {nid}")
        if c.get("message", "")[:200] != message[:200]:
            raise Reject(f"{name}: classified message mismatch: {nid}")
        if expected_reason == "state_neutral_placeholder":
            msg_ok = "neutral" in message.lower() or not message
        else:
            msg_ok = "missing" in message.lower() or "absent" in message.lower()
        if not msg_ok or not c.get("message_ok"):
            raise Reject(f"{name}: skip message semantics mismatch: {nid} "
                         f"{message[:120]!r}")
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


NEUTRAL_STATE_GENERATED_AT = "1970-01-01T00:00:00Z"

# 五份历史证据（第六轮 G）：HEAD 字节 sha256 与（存在时）tag:path 字节
# sha256、tag object 与 peeled commit 全部冻结；禁止自比。
# 语义：tier0-release 在 v0.1.2-tier0 之后被改写（post_tag_historical_record）；
# q1 与其三份 canary 证据的 tag 树字节 == HEAD 字节（tag_self_record）。
FROZEN_EVIDENCE = {
    "docs/00_project/releases/tier0-release.json": {
        "certification_tag": "v0.1.2-tier0",
        "tag_object": "4b148c98b4a5931349a2af4f7f70248b28961101",
        "tag_peeled_commit": "3287e0feb20691a0add37d1eec7173664beb3172",
        "tag_path_blob_sha256": (
            "a02bb1aaf8c22d7ed16d5931c4f51b3691ff68e25417e2150f4f7733f1199097"),
        "head_record_blob_sha256": (
            "7f0a48b6f740e142e546553f8d37dc82ded1f379e4fe31510453407cf60809ca"),
        "expected_relationship": "post_tag_historical_record",
        "authoritative_bytes": "tag:path",
    },
    "docs/00_project/releases/q1-release.json": {
        "certification_tag": "v0.1.3-q1",
        "tag_object": "dae52cecac9a5beb2b5e9f8d1291fd02ceed9c9f",
        "tag_peeled_commit": "ff66b9b24e8fb5099ab3c1b2bfda3b6e60e46fa2",
        "tag_path_blob_sha256": (
            "dd1f5de570564dddd9a459326c874bf52daf09a75ff87fce92426d0f1269d14e"),
        "head_record_blob_sha256": (
            "dd1f5de570564dddd9a459326c874bf52daf09a75ff87fce92426d0f1269d14e"),
        "expected_relationship": "tag_self_record",
        "payload_git_commit": "9777087",
        "authoritative_bytes": "tag:path",
    },
    "docs/00_project/releases/tier0-canary-evidence.json": {
        "certification_tag": "v0.1.2-tier0",
        "tag_path_blob_sha256": (
            "14c9ca0abf386fc97621f4ba152a1e5975553514a6201d4c0c0a9c913ed713d6"),
        "head_record_blob_sha256": (
            "14c9ca0abf386fc97621f4ba152a1e5975553514a6201d4c0c0a9c913ed713d6"),
        "expected_relationship": "tag_self_record",
        "authoritative_bytes": "tag:path",
    },
    "docs/00_project/releases/tier0-canary-gate.json": {
        "certification_tag": "v0.1.2-tier0",
        "tag_path_blob_sha256": (
            "1f07e3a9b766cfcee7d67ccb9b3c13e66ecb8ed51bc84fdf4c9f6499f1d6d644"),
        "head_record_blob_sha256": (
            "1f07e3a9b766cfcee7d67ccb9b3c13e66ecb8ed51bc84fdf4c9f6499f1d6d644"),
        "expected_relationship": "tag_self_record",
        "authoritative_bytes": "tag:path",
    },
    "docs/00_project/releases/tier0-three-flow-canary-aggregation.json": {
        "certification_tag": "v0.1.2-tier0",
        "tag_path_blob_sha256": (
            "c2c4b3ecdb385a3a907dc32d5b8bee76afda2252c8efab2bb5f136392c37ae7f"),
        "head_record_blob_sha256": (
            "c2c4b3ecdb385a3a907dc32d5b8bee76afda2252c8efab2bb5f136392c37ae7f"),
        "expected_relationship": "tag_self_record",
        "authoritative_bytes": "tag:path",
    },
}

EVIDENCE_PATHS = tuple(FROZEN_EVIDENCE)


def _neutral_payload(collected: int) -> dict:
    """subject commit 携带的确定性中性 UNVERIFIED 状态（第六轮 I）：
    commit/tree/时间字段一律 null 或确定性占位，禁止写父提交 tree 后冒充
    subject tree；时间戳固定，同输入两次生成字节一致。"""
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
        "subject_tree": None,
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
        "state_generated_at": NEUTRAL_STATE_GENERATED_AT,
        "profiles": profiles,
        "collected_tests": collected,
        "collected_tests_contract": (
            "tests/test_cli_runtime_contract.py::EXPECTED_COLLECTED_TESTS"
        ),
        "last_validated_commit": None,
        "last_validated_tree": None,
        "last_certified_checkpoint": {"status": "UNVERIFIED"},
        "evidence_paths": {
            p: _git("rev-parse", f"HEAD:{p}") for p in EVIDENCE_PATHS
        },
        "artifacts_dir": "state_artifacts",
        "bundles": {},
    }


def verify_committed_bundle(state: dict, repo_root: Path | None = None) -> dict:
    """（第六轮 D）在 carrier 上直接重演聚合器的 committed-bundle 校验：
    从 current_state.json 读 subject/artifacts/collected，锚定 REPO_ROOT 后
    重算全部 SHA/JUnit/stdout/result/raw manifest/skip/Merkle/平台/根集合。
    供 fresh clone 的后推验证与状态合同直接调用（不做 synthetic helper）。"""
    base = repo_root or REPO_ROOT
    expected_subject = state.get("subject_commit")
    expected_tree = state.get("subject_tree")
    collected = int(state["collected_tests"])
    sections = {}
    for name in PROFILE_NAMES:
        p = state.get("profiles", {}).get(name)
        if p is None:
            raise Reject(f"state missing profile {name}")
        if p.get("status") == "UNVERIFIED":
            continue
        rel = state.get("bundles", {}).get(name)
        if not rel:
            raise Reject(f"state missing bundles path for {name}")
        bundle = _load_bundle(rel, name, base)
        sections[name] = _verify_profile(
            bundle, collected, base,
            expected_subject=expected_subject,
            expected_tree=expected_tree)
    return {
        "subject": expected_subject,
        "tree": expected_tree,
        "profiles": sections,
        "collected_tests": collected,
    }


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
        payload = _neutral_payload(collected)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + NL,
            encoding="utf-8")
        print("neutral UNVERIFIED state written; collected =", collected)
        return 0

    head = _git("rev-parse", "HEAD")
    subject_tree = _git("rev-parse", "HEAD^{tree}")

    op = _load_bundle(args.operator_bundle, "operator", REPO_ROOT)
    pub = _load_bundle(args.public_clean_bundle, "public_clean", REPO_ROOT)

    if op["section"].get("subject_commit") != pub["section"].get(
            "subject_commit"):
        raise Reject("bundles disagree on subject_commit")
    if op["section"].get("subject_tree") != pub["section"].get("subject_tree"):
        raise Reject("bundles disagree on subject_tree")
    subject_commit = op["section"]["subject_commit"]
    if subject_commit != head:
        raise Reject(
            f"bundle subject {subject_commit[:12]} != repository HEAD {head[:12]}"
        )

    sections = {
        "operator": _verify_profile(op, args.expected_collected_tests,
                                    REPO_ROOT),
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

    # checkpoint：冻结常量验证 tag object/peeled/tag:path/HEAD record（第六轮 G）
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
            p: _git("rev-parse", f"HEAD:{p}") for p in EVIDENCE_PATHS
        },
        "artifacts_dir": f"state_artifacts/{subject_commit[:12]}",
        "bundles": {
            "operator": _portable_rel(args.operator_bundle),
            "public_clean": _portable_rel(args.public_clean_bundle),
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


def _portable_rel(raw: str) -> str:
    """bundle 参数入库的仓库相对 posix 形态（第六轮 C/F）。"""
    return str(raw).replace("\\", "/")


def _checkpoint_attestation(repo_root: Path | None = None) -> dict:
    """五份历史证据的冻结校验（第六轮 G）：tag object / peeled commit /
    tag:path 字节 / HEAD record 字节全部与冻结常量比对（禁止自比）；
    Tier0 恒为 post_tag_historical_record，Q1 区分 payload 9777087 与
    record/tag ff66b9b。"""
    root = repo_root or REPO_ROOT

    def _g(a: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *a.split()],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def _gbytes(rev_path: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", rev_path],
            capture_output=True, check=True,
        ).stdout

    failures = []
    records = {}
    for rec, frozen in FROZEN_EVIDENCE.items():
        tag = frozen["certification_tag"]
        rec_entry = {"status": "PASS", "certification_tag": tag,
                     "record_path": rec}
        try:
            tag_object = _g(f"rev-parse {tag}")
            tag_peeled = _g(f"rev-parse {tag}^{{commit}}")
            if frozen.get("tag_object") and tag_object != frozen["tag_object"]:
                failures.append(f"{rec}: tag object moved "
                                f"{frozen['tag_object'][:12]} -> "
                                f"{tag_object[:12]}")
            if frozen.get("tag_peeled_commit") and tag_peeled != frozen[
                    "tag_peeled_commit"]:
                failures.append(f"{rec}: tag peeled commit moved "
                                f"{frozen['tag_peeled_commit'][:12]} -> "
                                f"{tag_peeled[:12]}")
            rec_entry["tag_object"] = tag_object
            rec_entry["tag_target_commit"] = tag_peeled

            tag_path_blob = _gbytes(f"{tag}:{rec}")
            tag_path_sha = hashlib.sha256(tag_path_blob).hexdigest()
            head_blob = _gbytes(f"HEAD:{rec}")
            head_sha = hashlib.sha256(head_blob).hexdigest()
            if tag_path_sha != frozen["tag_path_blob_sha256"]:
                failures.append(
                    f"{rec}: tag:path bytes drifted vs frozen "
                    f"{frozen['tag_path_blob_sha256'][:12]} -> "
                    f"{tag_path_sha[:12]}")
            if head_sha != frozen["head_record_blob_sha256"]:
                failures.append(
                    f"{rec}: HEAD record bytes drifted vs frozen "
                    f"{frozen['head_record_blob_sha256'][:12]} -> "
                    f"{head_sha[:12]}")
            relationship = ("tag_self_record" if tag_path_sha == head_sha
                            else "post_tag_historical_record")
            if relationship != frozen["expected_relationship"]:
                failures.append(
                    f"{rec}: relationship {relationship} != frozen "
                    f"{frozen['expected_relationship']}")
            rec_entry["record_blob_sha256"] = head_sha
            rec_entry["tag_tree_blob_sha256"] = tag_path_sha
            rec_entry["record_relationship"] = relationship
            rec_entry["tag_path_bytes_verified"] = (
                tag_path_sha == frozen["tag_path_blob_sha256"])
            if frozen.get("authoritative_bytes") == "tag:path":
                pass  # 冻结值即权威字节，上面已比对

            blob_sha1 = subprocess.run(
                ["git", "-C", str(root), "hash-object", "--stdin"],
                input=head_blob, capture_output=True, check=True,
            ).stdout.strip().decode()
            find_log = _g(f"log --format=%H --find-object {blob_sha1} "
                          f"HEAD -- {rec}")
            rec_entry["record_commit"] = (find_log.splitlines()[0]
                                          if find_log else None)

            if frozen.get("payload_git_commit"):
                payload = json.loads(head_blob.decode("utf-8"))
                if payload.get("git_commit") != frozen["payload_git_commit"]:
                    failures.append(
                        f"{rec}: payload git_commit "
                        f"{payload.get('git_commit')!r} != frozen "
                        f"{frozen['payload_git_commit']!r}")
                rec_entry["payload_git_commit"] = payload.get("git_commit")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{rec}: checkpoint failure: {exc}")
            rec_entry["status"] = "FAIL"
        records[rec] = rec_entry
    return {"status": "PASS" if not failures else "FAIL",
            "records": records, "failures": failures}


if __name__ == "__main__":
    raise SystemExit(main())
