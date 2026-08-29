"""受控测试 profile（状态真源收敛 2026-08-30）。

公开 checkout 缺少 gitignored 的运营侧私有资产（reference_texts/a1_benchmark、
runtime/refs/**），直接跑默认 pytest 会出现 15 个环境性失败——这不是代码缺陷，
而是"依赖私有资产的测试"与"公开仓库可复现性"的边界问题。

本 conftest 建立显式门控：
- FILE_GATED：整个测试文件依赖的私有资产（缺任一 → 整文件跳过）；
- TEST_GATED：单个测试依赖的私有资产（缺失 → 该测试跳过）。

跳过原因是机器可读的字符串（含缺失资产路径），缺省 pytest 的结果因此是
"全绿 + 显式私有资产跳过"，而不是静默的假全绿或环境性红。
operator checkout（资产齐全）不受影响，全部照常执行。
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_FILE_GATED: dict[str, tuple[str, ...]] = {
    # 依赖 deepseek 运营侧 live DB 与 a1_benchmark 冻结基准（均 gitignored）
    "tests/test_build_deepseek_active_bundle.py": (
        "runtime/refs/deepseek_active",
        "reference_texts/a1_benchmark",
    ),
}

_TEST_GATED: dict[tuple[str, str], tuple[str, ...]] = {
    (
        "tests/test_auto_calibrate.py",
        "test_load_frozen_bench_rejects_sha256_mismatch",
    ): ("reference_texts/a1_benchmark",),
    (
        "tests/test_s7_long_run_judgment.py",
        "test_green_report_excludes_gaps",
    ): ("runtime/refs/cpa_active/s7/final_evidence_anchor.json",),
    (
        "tests/test_a1_release_validation.py",
        "test_g8_zero_committed_chapters_withholds",
    ): ("runtime/refs/cpa_active/canary_policy_s6_cpa.json",),
}


def _missing_assets(assets: tuple[str, ...]) -> list[str]:
    return [a for a in assets if not (PROJECT_ROOT / a).exists()]


def pytest_collection_modifyitems(config, items):  # noqa: ANN001, ANN201
    for item in items:
        rel = (
            Path(str(item.fspath)).resolve().relative_to(PROJECT_ROOT)
            .as_posix()
        )
        file_missing = _missing_assets(_FILE_GATED.get(rel, ()))
        if file_missing:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "requires private operator assets missing on public "
                        f"checkout: {', '.join(file_missing)}"
                    )
                )
            )
            continue
        test_missing = _missing_assets(
            _TEST_GATED.get((rel, item.name), ()),
        )
        if test_missing:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "requires private operator assets missing on public "
                        f"checkout: {', '.join(test_missing)}"
                    )
                )
            )
