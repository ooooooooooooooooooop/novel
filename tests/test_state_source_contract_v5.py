"""第五轮对抗负测与 blob 完整性合同（审计任务 A/C/D/G/H）."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.aggregate_current_state import (  # noqa: E402
    Reject,
    verify_merkle_inventory,
    verify_pass_semantics,
    verify_results_identity,
)


def _result(collected: int = 3106, **over) -> dict:
    r = {"passed": collected - 1, "skipped": 1, "failed": 0, "errors": 0,
         "collected": collected}
    r.update(over)
    return r


# ---- 反例负测（审计任务 C/B）----

def test_neg_results_sum_identity():
    with pytest.raises(Reject, match="!="):
        verify_results_identity(
            {"passed": 3099, "skipped": 1, "failed": 0, "errors": 0,
             "collected": 3106}, 3106)


def test_neg_results_collected_contract():
    with pytest.raises(Reject, match="!= contract"):
        verify_results_identity(
            {"passed": 3104, "skipped": 1, "failed": 0, "errors": 0,
             "collected": 3105}, 3106)


def test_neg_pass_with_failed_canary():
    section = {
        "status": "PASS",
        "pytest": {"exit_code": 0,
                   "results": {"passed": 3105, "skipped": 1, "failed": 0,
                               "errors": 0, "collected": 3106}},
        "canary": {"exit_code": 1, "verdict": "FAIL"},
        "gates": {"post_tracked_changes": [], "untracked_stray": [],
                  "head_unchanged": True, "tree_unchanged": True},
        "external_inputs": {"pre": {"roots": {}, "files": {}},
                            "post": {"roots": {}, "files": {}}},
    }
    with pytest.raises(Reject, match="failed canary"):
        verify_pass_semantics(section)


def test_neg_pass_with_head_drift():
    section = {
        "status": "PASS",
        "pytest": {"exit_code": 0,
                   "results": {"passed": 3105, "skipped": 1, "failed": 0,
                               "errors": 0, "collected": 3106}},
        "canary": {"exit_code": 0, "verdict": "PASS"},
        "gates": {"post_tracked_changes": [], "untracked_stray": [],
                  "head_unchanged": False, "tree_unchanged": True},
        "external_inputs": {"pre": {"roots": {}, "files": {}},
                            "post": {"roots": {}, "files": {}}},
    }
    with pytest.raises(Reject, match="HEAD drift"):
        verify_pass_semantics(section)


def test_neg_merkle_recompute_catches_same_size_tamper():
    """同大小改写（反例 2）：内容 sha 变化 → Merkle 重算必不一致."""
    inv = {
        "roots": {"runtime/refs/deepseek_active": {
            "present": True, "merkle": None, "file_count": 1}},
        "files": {"runtime/refs/deepseek_active/live.db": {
            "type": "file", "size": 8, "sha256": hashlib.sha256(
                b"AAAAAAAA").hexdigest()}},
    }
    # 先按清单算出 Merkle 并写入（模拟 runner 记录）
    entries = [f"{rel}:{info['sha256']}" for rel, info in inv["files"].items()]
    inv["roots"]["runtime/refs/deepseek_active"]["merkle"] = hashlib.sha256(
        chr(10).join(sorted(entries)).encode()).hexdigest()
    verify_merkle_inventory(inv)  # 一致 → 通过
    # 同大小篡改：内容 AAAAAAAA -> AAAAAAAB（size 不变 8）
    inv["files"]["runtime/refs/deepseek_active/live.db"]["sha256"] = (
        hashlib.sha256(b"AAAAAAAB").hexdigest())
    with pytest.raises(Reject, match="Merkle recompute mismatch"):
        verify_merkle_inventory(inv)


# ---- A1 冻结记录负测（审计任务 G）----

@pytest.fixture()
def a1_module():
    import importlib
    mod = importlib.import_module("scripts.a1_release_validation")
    return mod


def test_a1_frozen_constants_are_used(a1_module):
    """冻结预期值必须真实参与断言（第五轮：禁止定义后不使用）."""
    spec = a1_module.FROZEN_RELEASES["tier0"]
    assert spec["record_sha256"].startswith("7f0a48b6"), (
        "tier0 anchor must be the git-blob semantic value"
    )
    assert spec["tag"] == "v0.1.2-tier0"
    assert spec["tag_commit"].startswith("3287e0f")


def test_a1_detects_self_reported_sha_drift(a1_module, tmp_path):
    """自报新 SHA 的记录必须失败（负测：record_sha256 与实际不符）."""
    rec = tmp_path / "tier0-release.json"
    rec.write_bytes(b'{"baseline_tests_passing": 2301}\n')
    spec = {"record": rec, "record_sha256": "0" * 64,
            "tag": "v0.1.2-tier0", "tag_commit": "0" * 40}
    errors = a1_module.verify_frozen_releases.__wrapped__(  # type: ignore
        [spec]) if hasattr(a1_module.verify_frozen_releases, "__wrapped__") else None
    # 直接走内部逻辑：monkeypatch FROZEN_RELEASES 后调用
    import types
    saved = a1_module.FROZEN_RELEASES
    a1_module.FROZEN_RELEASES = {"tier0": spec}
    try:
        errors = a1_module.verify_frozen_releases()
    finally:
        a1_module.FROZEN_RELEASES = saved
    assert any("record sha256 changed" in e for e in errors), errors


def test_a1_detects_moved_tag(a1_module, tmp_path, monkeypatch):
    """tag 目标被移动/不存在必须失败（负测：移动 tag）."""
    rec = tmp_path / "tier0-release.json"
    rec.write_bytes(b"{}\n")
    spec = {"record": rec, "record_sha256": hashlib.sha256(
        rec.read_bytes()).hexdigest(),
        "tag": "v0.0.0-nonexistent", "tag_commit": "0" * 40}
    saved = a1_module.FROZEN_RELEASES
    a1_module.FROZEN_RELEASES = {"tier0": spec}
    try:
        errors = a1_module.verify_frozen_releases()
    finally:
        a1_module.FROZEN_RELEASES = saved
    assert any("moved/absent" in e for e in errors), errors


def test_a1_detects_dirty_frozen_worktree(a1_module):
    """工作树篡改（不提交）必须硬失败（负测：dirty tracked record）."""
    rec = PROJECT_ROOT / "docs/00_project/releases/tier0-release.json"
    orig = rec.read_bytes()
    try:
        rec.write_bytes(orig[:-1] + b" ")
        errors = a1_module.verify_frozen_releases()
        assert any("uncommitted worktree changes" in e for e in errors), errors
    finally:
        rec.write_bytes(orig)


# ---- 第五轮：Git blob 字节完整性（反例 1 的永久回归锁定）----

def test_operator_artifact_shas_match_git_blobs():
    """Windows 生成→Git 提交→Linux clone 重算必须一致（反例 1 回归锁定）."""
    state = json.loads((PROJECT_ROOT / "current_state.json").read_text(
        encoding="utf-8"))
    if state.get("subject_commit") is None:
        pytest.skip("neutral placeholder carries no attested bundles")
    subject12 = state["subject_commit"][:12]
    for name in ("operator", "public_clean"):
        p = state["profiles"][name]
        if p["status"] == "UNVERIFIED":
            continue
        base = f"state_artifacts/{subject12}/{name}"
        for field in ("stdout_sha256", "stderr_sha256", "junit_xml_sha256"):
            fname = {"stdout_sha256": "pytest-stdout.txt",
                     "stderr_sha256": "pytest-stderr.txt",
                     "junit_xml_sha256": "pytest-junit.xml"}[field]
            recorded = p["pytest"][field]
            blob = subprocess.run(
                ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
                 f"HEAD:{base}/{fname}"],
                capture_output=True, check=True).stdout
            assert hashlib.sha256(blob).hexdigest() == recorded, (
                f"{name}/{fname}: git blob sha != declared (CRLF integrity "
                "violation)"
            )
            disk = Path(PROJECT_ROOT / base / fname)
            if disk.exists():
                assert _disk_sha_matches_git(disk, recorded), (
                    f"{name}/{fname}: worktree bytes != git blob"
                )


def _disk_sha_matches_git(path: Path, recorded: str) -> bool:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() == recorded:
        return True
    return hashlib.sha256(
        data.replace(b"\r\n", b"\n")).hexdigest() == recorded


def test_canary_artifact_sha_matches_git_blob():
    state = json.loads((PROJECT_ROOT / "current_state.json").read_text(
        encoding="utf-8"))
    if state.get("subject_commit") is None:
        pytest.skip("neutral placeholder carries no attested bundles")
    subject12 = state["subject_commit"][:12]
    for name in ("operator", "public_clean"):
        p = state["profiles"][name]
        if p["status"] == "UNVERIFIED":
            continue
        blob = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
             f"HEAD:state_artifacts/{subject12}/{name}/canary-stdout.txt"],
            capture_output=True, check=True).stdout
        assert hashlib.sha256(blob).hexdigest() == p["canary"]["stdout_sha256"]


# ---- 聚合器 bundle 路径回归（第五轮：曾有 manifest/_conftest_gated_items
#      NameError，bundle 聚合从未端到端跑通）----

def _synthetic_public_clean_bundle(tmp_path: Path) -> tuple[Path, dict]:
    """构造与真实 runner 输出同构的 public_clean 合成 bundle，返回 (bundle, section).

    固定契约：JUnit 20 skips（16 gated + 4 self-ref）、其余 passed，
    collected == EXPECTED_COLLECTED_TESTS，artifact SHA/结果恒等/Merkle/
    PASS 语义全部自洽，平台为 Linux、大小写敏感、autocrlf=false、私有根缺席。
    """
    import xml.etree.ElementTree as XET
    from scripts import aggregate_current_state as agg
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS

    gated_map = agg._gated_asset_map()
    collected = int(EXPECTED_COLLECTED_TESTS)
    selfref = {agg._norm_nodeid(g) for g in agg.SELF_REF_SKIPS}
    skip_nodeids = sorted(gated_map) + sorted(selfref)
    skips = [
        {"nodeid": nid,
         "reason_code": ("state_neutral_placeholder" if nid in selfref
                         else "missing_private_asset"),
         "required_asset": ([] if nid in selfref
                            else sorted(gated_map[nid]))}
        for nid in skip_nodeids
    ]
    n_skipped = len(skips)
    n_passed = collected - n_skipped

    bundle = tmp_path / "public_clean"
    bundle.mkdir()

    # JUnit XML：collected 个 testcase，其中 20 个 skipped
    suite = XET.Element("testsuite", {
        "tests": str(collected), "failures": "0", "errors": "0",
        "skipped": str(n_skipped), "name": "pytest", "time": "1.0"})
    seen = set()
    for nid in skip_nodeids:
        cls, _, name = nid.partition("::")
        tc = XET.SubElement(suite, "testcase", {
            "classname": cls, "name": name, "time": "0.01"})
        XET.SubElement(tc, "skipped", {
            "message": "synthetic skip", "type": "pytest.skip"})
        seen.add(f"{cls}::{name}")
    i = 0
    while len(seen) < collected:
        cls = f"synthetic.module.{i // 100}"
        name = f"test_filler_{i}"
        nodeid = f"{cls}::{name}"
        if nodeid in seen:
            i += 1
            continue
        XET.SubElement(suite, "testcase", {
            "classname": cls, "name": name, "time": "0.01"})
        seen.add(nodeid)
        i += 1
    junit_path = bundle / "pytest-junit.xml"
    junit_path.write_bytes(
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        + XET.tostring(suite, encoding="utf-8"))

    head = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD^{tree}"],
        capture_output=True, text=True, check=True).stdout.strip()

    def _lf(path: Path, text: str) -> str:
        data = text.replace("\r\n", "\n").encode("utf-8")
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    stdout_sha = _lf(bundle / "pytest-stdout.txt",
                     f"{n_passed} passed, {n_skipped} skipped in 1.00s\n")
    stderr_sha = _lf(bundle / "pytest-stderr.txt", "")
    junit_sha = hashlib.sha256(junit_path.read_bytes()).hexdigest()
    canary_sha = _lf(bundle / "canary-stdout.txt",
                     "Tier 0 three-flow canary regression: PASS\n")
    _lf(bundle / "canary-stderr.txt", "")

    results = {"passed": n_passed, "skipped": n_skipped, "failed": 0,
               "errors": 0, "collected": collected}
    artifact = {"pytest_exit_code": 0, "results": results,
                "canary_exit_code": 0, "canary_verdict": "PASS",
                "parse_error": None}
    manifest = {"profile": "public_clean",
                "generated_at": "2026-08-30T00:00:00Z",
                "skips": skips, "unexplained": []}
    roots = {
        r: {"present": False, "merkle": None, "file_count": 0}
        for r in ("reference_texts/a1_benchmark",
                  "runtime/refs/deepseek_active",
                  "runtime/refs/cpa_active",
                  "novels/s6-canary-offdom/output",
                  "novels/s6-canary-mythic/output",
                  "novels/s6-canary-hist/output")
    }
    empty_inventory = {"roots": roots, "files": {}}
    section = {
        "profile": "public_clean", "status": "PASS",
        "bundle_rel": "state_artifacts/synthetic/public_clean",
        "subject_commit": head, "subject_tree": tree,
        "checkout": str(tmp_path), "python_version": "3.11",
        "pytest_version": "pytest 9.1.1",
        "platform": "Linux-6.6-x86_64", "platform_system": "Linux",
        "filesystem_case_probe": {
            "a_txt_and_A_TXT_coexist": True,
            "case_sensitive_filesystem": True,
            "probe_directory": str(tmp_path / "probe")},
        "core.autocrlf": "false",
        "env_sanitized": ["PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"],
        "started_at": "2026-08-30T00:00:00Z",
        "completed_at": "2026-08-30T00:00:01Z",
        "collected_tests": collected,
        "expected_collected_tests": collected,
        "pytest": {
            "command": "python -m pytest tests -q", "exit_code": 0,
            "results": results, "parse_error": None,
            "stdout": "pytest-stdout.txt", "stderr": "pytest-stderr.txt",
            "junit_xml": "pytest-junit.xml",
            "stdout_sha256": stdout_sha, "stderr_sha256": stderr_sha,
            "junit_xml_sha256": junit_sha,
            "result_artifact_sha256": hashlib.sha256(
                json.dumps(artifact, sort_keys=True,
                           ensure_ascii=False).encode()).hexdigest(),
            "completed_at": "2026-08-30T00:00:01Z",
        },
        "canary": {
            "command": "python scripts/tier0_canary_regression.py",
            "exit_code": 0, "verdict": "PASS", "detail": "PASS",
            "stdout": "canary-stdout.txt", "stdout_sha256": canary_sha,
            "completed_at": "2026-08-30T00:00:01Z",
        },
        "skip_manifest": manifest,
        "skip_manifest_sha256": _lf(
            bundle / "skip-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2)),
        "external_inputs": {
            "pre": empty_inventory, "post": empty_inventory,
            "identical": True, "merkle_root": roots,
            "missing_roots": sorted(roots),
        },
        "gates": {
            "pre_tracked_changes": [], "post_tracked_changes": [],
            "untracked_stray": [], "head_unchanged": True,
            "tree_unchanged": True,
        },
    }
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle, section


def test_aggregator_verify_profile_synthetic_bundle_accepts(tmp_path):
    """聚合器 bundle 路径必须端到端通过（回归：第五轮曾 NameError 崩溃）."""
    from scripts import aggregate_current_state as agg
    bundle, _ = _synthetic_public_clean_bundle(tmp_path)
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    loaded = agg._load_bundle(bundle, "public_clean")
    out = agg._verify_profile(loaded, int(EXPECTED_COLLECTED_TESTS),
                              PROJECT_ROOT)
    assert out["status"] == "PASS"


def test_aggregator_verify_profile_rejects_tampered_raw_manifest(tmp_path):
    """raw skip-manifest 与内嵌 section 不一致（非规范 JSON 复制）必须拒绝."""
    from scripts import aggregate_current_state as agg
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    # 篡改 raw manifest：内容与 section 的 skip_manifest 不同（同键值、不同
    # 列表顺序），并把 section 声明的 skip_manifest_sha256 同步成篡改后文件
    # 的 SHA，使 SHA 检查通过、规范 JSON 完全比较失败。
    tampered = dict(section["skip_manifest"])
    tampered["skips"] = list(reversed(tampered["skips"]))
    data = json.dumps(tampered, ensure_ascii=False, indent=2) + "\n"
    (bundle / "skip-manifest.json").write_bytes(data.encode("utf-8"))
    section["skip_manifest_sha256"] = hashlib.sha256(data.encode()).hexdigest()
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = agg._load_bundle(bundle, "public_clean")
    with pytest.raises(agg.Reject, match="differs from embedded"):
        agg._verify_profile(loaded, int(EXPECTED_COLLECTED_TESTS),
                            PROJECT_ROOT)
