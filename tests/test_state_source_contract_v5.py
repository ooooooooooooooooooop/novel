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
