"""显式受控测试 profile（状态真源收敛 2026-08-30，审计任务 B）.

两个且只有两个 profile，由环境变量 NOVEL_TEST_PROFILE 显式选择（默认
public_clean，禁止按目录存在与否静默切换）：

- public_clean（默认）：公开 checkout 口径。真正依赖私有运营资产的 nodeid
  被精确跳过（逐条记录 reason_code / required_asset / asset_fingerprint），
  其余测试全部照常运行。
- operator：运营 checkout 口径。必需资产缺任一 → 立即 FAIL（pytest 退出码 3），
  绝不降级为 skip。

私有资产一律 gitignored；本文件不读取其内容，只做存在性与指纹记录。
skip manifest 结构化输出（NOVEL_SKIP_MANIFEST_PATH 指定时）：
  {"profile", "generated_at", "skips": [{nodeid, reason_code,
    required_asset, asset_fingerprint}]}
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROFILE_ENV = "NOVEL_TEST_PROFILE"
MANIFEST_ENV = "NOVEL_SKIP_MANIFEST_PATH"
REASON_CODE = "missing_private_asset"

# 必需私有资产（operator profile 必须全部在场）
REQUIRED_OPERATOR_ASSETS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active/s7/final_evidence_anchor.json",
    "runtime/refs/cpa_active/canary_policy_s6_cpa.json",
)

# 精确 nodeid 门控：只有这些测试真正依赖私有资产；其余测试在任何 profile 下
# 都照常运行（例如 test_build_template_upstream_url_is_env_name_not_value）。
_TEST_GATED: dict[str, tuple[str, ...]] = {
    "tests/test_build_deepseek_active_bundle.py::test_build_produces_exactly_four_bundle_files": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_is_idempotent_byte_stable": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_output_has_no_forbidden_secrets": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_requires_base_url_env": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_derives_provider_identity_from_live_db": (
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_refuses_non_deepseek_current_provider": (
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_refuses_failover_current_provider": (
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_frozen_thresholds_and_uncontaminated_split": (
        "reference_texts/a1_benchmark",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_profile_passes_provider_profile_validation": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_policy_passes_autonomous_policy_validation": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_judge_roles_disable_thinking": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_build_deepseek_active_bundle.py::test_build_active_selector_points_only_deepseek": (
        "reference_texts/a1_benchmark",
        "runtime/refs/deepseek_active",
    ),
    "tests/test_auto_calibrate.py::test_load_frozen_bench_rejects_sha256_mismatch": (
        "reference_texts/a1_benchmark",
    ),
    "tests/test_s7_long_run_judgment.py::test_green_report_excludes_gaps": (
        "runtime/refs/cpa_active/s7/final_evidence_anchor.json",
    ),
    "tests/test_a1_release_validation.py::test_g8_zero_committed_chapters_withholds": (
        "runtime/refs/cpa_active/canary_policy_s6_cpa.json",
        "novels/s6-canary-offdom/output",
        "novels/s6-canary-mythic/output",
        "novels/s6-canary-hist/output",
    ),
}


def _asset_fingerprint(rel: str) -> str:
    """资产指纹：文件为内容 sha256；目录为有序（相对路径, 大小）清单 sha256."""
    p = PROJECT_ROOT / rel
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    h = hashlib.sha256()
    count = 0
    for f in sorted(p.rglob("*")):
        if f.is_file():
            h.update(f"{f.relative_to(p).as_posix()}:{f.stat().st_size}\n".encode())
            count += 1
            if count >= 2000:
                break
    return h.hexdigest()


def pytest_sessionstart(session):  # noqa: ANN001, ANN201
    profile = os.environ.get(PROFILE_ENV, "public_clean")
    if profile not in ("public_clean", "operator"):
        pytest.exit(
            f"unknown {PROFILE_ENV}={profile!r} (allowed: public_clean, operator)",
            returncode=3,
        )
    if profile == "operator":
        missing = [
            a for a in REQUIRED_OPERATOR_ASSETS if not (PROJECT_ROOT / a).exists()
        ]
        if missing:
            pytest.exit(
                "operator profile FAIL: required private operator assets missing "
                f"(never downgrade to skip): {', '.join(missing)}",
                returncode=3,
            )


def pytest_collection_modifyitems(config, items):  # noqa: ANN001, ANN201
    profile = os.environ.get(PROFILE_ENV, "public_clean")
    if profile == "operator":
        return
    skips = []
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        assets = _TEST_GATED.get(nodeid)
        if not assets:
            continue
        missing = [a for a in assets if not (PROJECT_ROOT / a).exists()]
        if not missing:
            continue
        reason = (
            "requires private operator assets missing on public_clean checkout: "
            + ", ".join(missing)
        )
        item.add_marker(pytest.mark.skip(reason=reason))
        skips.append(
            {
                "nodeid": nodeid,
                "reason_code": REASON_CODE,
                "required_asset": list(missing),
                "asset_fingerprint": {
                    a: _asset_fingerprint(a)
                    for a in assets
                    if (PROJECT_ROOT / a).exists()
                },
            }
        )
    manifest_path = os.environ.get(MANIFEST_ENV)
    if manifest_path:
        manifest = {
            "profile": profile,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "skips": skips,
        }
        Path(manifest_path).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
