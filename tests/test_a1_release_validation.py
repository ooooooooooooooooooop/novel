"""Tests for the A1/Q2A single-command release validator (scripts/a1_release_validation.py).

Locks the deterministic gate decision against frozen thresholds:
  * all gates pass -> certified (would emit release record + tag)
  * G7 judge-position-bias fails -> withheld (release record/tag NOT emitted)
  * G8 canary not certified -> withheld
  * privacy scan flags a tracked real-novel path
No provider/LLM calls; gate evaluation is pure evidence aggregation.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "a1_release_validation", REPO_ROOT / "scripts" / "a1_release_validation.py"
)
arv = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(arv)


def _g0_pass() -> dict:
    return {"status": "pass", "provider": {"policy_sha256": "p" * 64, "profile_sha256": "q" * 64}}


def _g3_pass() -> dict:
    return {"status": "pass", "evidence": {"terminal": {"status": "narrative_stopped"}}}


def _holdout(position: float, met: bool | None = None) -> dict:
    position_met = position >= 0.9
    met_flag = met if met is not None else (position_met and True)
    return {
        "overall_accuracy": 0.8837,
        "position_consistency": position,
        "dimension_met": {
            "overall": True,
            "per_tag": True,
            "position_consistency": position_met,
        },
        "violations": [] if position_met else [f"position consistency {position} < 0.9"],
        "thresholds_id": "7e94bc8e0644b225",
        "met": met_flag,
    }


def _canary(total_committed: int) -> dict:
    expected = 90
    return {
        "genres": {
            "g1": {
                "expected_chapters": 30,
                "committed_chapters": total_committed // 3,
                "run_attempts": [],
            },
            "g2": {
                "expected_chapters": 30,
                "committed_chapters": total_committed // 3,
                "run_attempts": [],
            },
            "g3": {
                "expected_chapters": 30,
                "committed_chapters": total_committed // 3,
                "run_attempts": [],
            },
        },
        "total_expected": expected,
        "total_committed": total_committed,
        "certified": total_committed == expected,
    }


def _evaluate(**overrides) -> dict:
    args = dict(
        g0=_g0_pass(),
        g3=_g3_pass(),
        holdout=_holdout(0.9),
        canary=_canary(90),
        pytest_ok=True,
        pytest_summary="2724 passed",
        frozen_errors=[],
        privacy_errors=[],
    )
    args.update(overrides)
    return arv.evaluate_gates(**args)


def test_certified_when_all_gates_pass():
    gate = _evaluate()
    assert gate["all_pass"] is True
    assert all(g["pass"] for g in gate["gates"].values())


def test_g7_position_bias_0_5_withholds():
    gate = _evaluate(holdout=_holdout(0.5))
    assert gate["all_pass"] is False
    assert gate["gates"]["G7"]["pass"] is False
    assert gate["gates"]["G7"]["detail"]["position_consistency"] == 0.5


def test_g7_overall_below_threshold_withholds():
    holdout = _holdout(0.9)
    holdout["dimension_met"]["overall"] = False
    holdout["overall_accuracy"] = 0.4
    gate = _evaluate(holdout=holdout)
    assert gate["all_pass"] is False
    assert gate["gates"]["G7"]["pass"] is False


def test_g8_zero_committed_chapters_withholds():
    gate = _evaluate(canary=_canary(0))
    assert gate["all_pass"] is False
    assert gate["gates"]["G8"]["pass"] is False
    assert gate["gates"]["G8"]["detail"]["total_committed"] == 0


def test_g9_frozen_release_drift_withholds():
    gate = _evaluate(frozen_errors=["[Tier0/Q1] tier0 record sha256 changed"])
    assert gate["all_pass"] is False
    assert gate["gates"]["G9"]["pass"] is False


def test_privacy_error_withholds():
    gate = _evaluate(privacy_errors=["[privacy] tracked real-novel path: novels/某作/x.txt"])
    assert gate["all_pass"] is False
    assert gate["gates"]["G9"]["pass"] is False


def test_build_release_record_shape():
    rec = arv.build_release_record(
        g0=_g0_pass(),
        canary=_canary(90),
        pytest_summary="2724 passed in 4s",
        head="a" * 40,
    )
    assert rec["type"] == "q2a_a1_release_record"
    assert rec["canary_result"] == "pass"
    assert rec["gates_passed"] == ["G0", "G3", "G7", "G8", "G9"]
    assert rec["baseline_tests_passing"] == 2724
    assert "prompt" not in json.dumps(rec)
    assert "prose" not in json.dumps(rec)


def test_privacy_clean_summary_reduces_full_reports():
    """Aggregate must carry only SHA/model/tokens/cost/booleans, never full evidence.

    Regression: the g0/g3/holdout reports embed machine paths, the real novel
    workspace name, and credential markers; the aggregate must reduce them to
    privacy-clean scalars before emission.
    """
    leaky_g0 = {
        "status": "pass",
        "provider": {"policy_sha256": "p" * 64, "profile_sha256": "q" * 64},
        "credential": "present_not_recorded",
        "endpoint": "loopback_from_credential_source",
        "smoke_audit_backing": r"D:\Desktop\novel\.taskflow\active\autonomous-high-quality-production\runtime",
    }
    leaky_g3 = {
        "status": "pass",
        "evidence": {
            "run_dir": r"D:\Desktop\novel\novels\real-novel\output\a1-g3-stop-canary",
            "terminal": {"status": "narrative_stopped", "committed_chapters": 0},
        },
    }
    leaky_holdout = {
        "met": False,
        "overall_accuracy": 0.8837,
        "position_consistency": 0.5,
        "dimension_met": {"overall": True, "per_tag": True, "position_consistency": False},
        "thresholds_id": "7e94bc8e0644b225",
    }
    summary = {
        "g0": arv._privacy_clean_summary("g0", leaky_g0),
        "g3": arv._privacy_clean_summary("g3", leaky_g3),
        "holdout": arv._privacy_clean_summary("holdout", leaky_holdout),
    }
    emitted = json.dumps(summary)
    assert "credential" not in emitted
    assert "endpoint" not in emitted
    assert "smoke_audit_backing" not in emitted
    assert "real-novel" not in emitted
    assert "D:" not in emitted
    assert arv._scan_aggregate_forbidden(emitted) == []
    # summaries keep the decision-relevant scalars
    assert summary["holdout"]["position_consistency"] == 0.5
    assert summary["g0"]["policy_sha256"] == "p" * 64


def test_scan_aggregate_forbidden_allows_marker_flags_only():
    """The safe markers present_not_recorded / loopback_from_credential_source pass."""
    safe = json.dumps(
        {
            "g0": {"status": "pass"},
            "g3": {"status": "pass"},
            "holdout": {"met": False, "position_consistency": 0.5},
            "credential": "present_not_recorded",
            "endpoint": "loopback_from_credential_source",
        }
    )
    assert arv._scan_aggregate_forbidden(safe) == []
    # a real credential value trips
    leaky = safe.replace("present_not_recorded", "sk-sk-real-secret-value")
    assert arv._scan_aggregate_forbidden(leaky) != []
