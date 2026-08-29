"""Release-record 语义对抗测试（状态真源收敛 2026-08-30，审计任务 C）.

封死 legacy "N passed" 语义：只有 TIER0_LEGACY_FROZEN_RECORDS 字节级白名单内的
不可变历史记录可以通过专用通道；任何新造、复制、改名、倒灌都被拒绝。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.boundary_control.release_record import (
    build_tier0_release_record,
    validate_legacy_tier0_release_record,
    validate_tier0_release_record,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 单一来源：与 test_release_record 相同的合同命令模式
from tests.test_release_record import FULL_PYTEST_COMMAND


def _v2_result(collected: int = 3090, passed: int | None = None) -> dict:
    passed = passed if passed is not None else collected - 1
    return {
        "passed": passed,
        "skipped": 1,
        "failed": 0,
        "errors": 0,
        "collected": collected,
    }


def _v2_payload(collected: int = 3090) -> dict:
    result = _v2_result(collected)
    return {
        "schema_version": 2,
        "type": "tier0_release_record",
        "production_tier": "local_staged_cli_v0",
        "release_id": "tier0-canary-20260830",
        "created_at_utc": "2026-08-30T00:00:00Z",
        "release_tag_or_checkpoint": "tier0-v0.1.0",
        "git_commit": "0123456789abcdef0123456789abcdef01234567",
        "baseline_tests_passing": result["passed"],
        "full_pytest_command": FULL_PYTEST_COMMAND,
        "full_pytest_result": result,
        "canary_runbook": "docs/00_project/31_tier0_canary_runbook.md",
        "canary_result": "pass",
        "canary_commands": ["novel gate tier0-canary --json"],
        "staged_runtime": "FileExchangeInterface",
        "directapi_provider_calling": False,
        "provider_calls_implemented": False,
        "closed_loop_allowed": False,
        "provider_call_performed": False,
        "closed_loop_advanced": False,
        "known_limitations": [],
        "evidence_paths": ["docs/00_project/releases/tier0-release.json"],
    }


def _legacy_string_payload() -> dict:
    """字段自洽、路径/日期全新，但 full_pytest_result 仍是遗留 "N passed" 字符串."""
    payload = _v2_payload()
    payload["full_pytest_result"] = "3089 passed"
    payload["baseline_tests_passing"] = 3089
    return payload


def test_adversarial_new_record_with_legacy_string_rejected(tmp_path):
    """反例 1：新路径、新日期、字段自洽的 "N passed" 必须拒绝（标准通道）."""
    payload = _legacy_string_payload()
    with pytest.raises(ValueError, match="full_pytest_result must be a structured"):
        validate_tier0_release_record(payload, expected_collected_tests=3090)
    # legacy 专用通道同样拒绝未白名单路径
    path = tmp_path / "new-legacy-record.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="not whitelisted"):
        validate_legacy_tier0_release_record(str(path), repo_root=PROJECT_ROOT)


def test_adversarial_copied_or_renamed_legacy_record_rejected(tmp_path):
    """反例 2：复制或改名历史记录必须拒绝（字节相同也不行——路径不在白名单）."""
    src = PROJECT_ROOT / "docs/00_project/releases/tier0-release.json"
    copy = tmp_path / "renamed-tier0-release.json"
    copy.write_bytes(src.read_bytes())
    with pytest.raises(ValueError, match="not whitelisted"):
        validate_legacy_tier0_release_record(str(copy), repo_root=PROJECT_ROOT)
    # 同理：白名单路径之外的任何调用都被拒绝
    with pytest.raises(ValueError, match="not whitelisted"):
        validate_legacy_tier0_release_record(
            "docs/00_project/releases/tier0-release-copy.json",
            repo_root=PROJECT_ROOT,
        )


def test_adversarial_collected_mismatch_with_contract_rejected():
    """反例 3：诚实形态 collected != 仓库 collected 合同必须拒绝."""
    payload = _v2_payload(collected=2500)
    with pytest.raises(ValueError, match="must equal the repository collected contract"):
        validate_tier0_release_record(payload, expected_collected_tests=3090)


def test_adversarial_baseline_and_result_both_faked_to_collected_rejected():
    """反例 4：baseline 与 result 同时伪装成 collected（无 skip）也必须拒绝."""
    payload = _v2_payload(collected=2500)
    payload["full_pytest_result"] = {
        "passed": 2500, "skipped": 0, "failed": 0, "errors": 0, "collected": 2500,
    }
    payload["baseline_tests_passing"] = 2500
    with pytest.raises(ValueError, match="must equal the repository collected contract"):
        validate_tier0_release_record(payload, expected_collected_tests=3090)


def test_adversarial_record_missing_from_checkpoint_tree_rejected(tmp_path):
    """反例 5：checkpoint 存在但记录未存在于该 checkpoint tree 时必须拒绝."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True
    ).stdout.strip()
    payload = _v2_payload()
    payload["release_tag_or_checkpoint"] = head
    payload["git_commit"] = head
    payload["evidence_paths"] = ["docs/00_project/releases/tier0-release.json"]
    record_path = tmp_path / "post-hoc-record.json"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    # 记录在仓库内的逻辑路径不可能存在于该 checkpoint tree（它是 tmp 新文件）
    logical_path = "docs/00_project/releases/post-hoc-record.json"
    # 直接以 git-checkpoint 校验器验证回填伪造拒绝
    from src.boundary_control.release_record import (
        validate_tier0_release_record_git_checkpoint,
    )

    with pytest.raises(ValueError, match="must exist in the checkpoint tree"):
        validate_tier0_release_record_git_checkpoint(
            payload,
            repo_root=PROJECT_ROOT,
            record_path=logical_path,
            require_record_in_checkpoint=True,
        )


def test_legacy_whitelist_accepts_committed_tier0_record_only():
    """白名单正例：提交在案的 tier0-release.json 经专用通道通过；Q1 亦然."""
    payload = validate_legacy_tier0_release_record(
        "docs/00_project/releases/tier0-release.json",
        repo_root=PROJECT_ROOT,
    )
    assert payload["baseline_tests_passing"] == 2301
    q1 = validate_legacy_tier0_release_record(
        "docs/00_project/releases/q1-release.json",
        repo_root=PROJECT_ROOT,
    )
    assert q1["baseline_tests_passing"] == 2460


def test_builder_enforces_collected_contract():
    """builder 必须接收 expected_collected_tests 并强制一致."""
    with pytest.raises(ValueError, match="must equal the repository collected contract"):
        build_tier0_release_record(
            release_id="tier0-canary-20260830",
            created_at_utc="2026-08-30T00:00:00Z",
            release_tag_or_checkpoint="tier0-v0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
            full_pytest_result=_v2_result(collected=2500),
            expected_collected_tests=3090,
            full_pytest_command=FULL_PYTEST_COMMAND,
            record_path="docs/00_project/releases/tier0-release.json",
        )
