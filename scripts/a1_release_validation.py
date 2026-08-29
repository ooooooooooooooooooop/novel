#!/usr/bin/env python3
"""A1/Q2A single-command release validation (docs/00_project/48 §6 step 9).

One command aggregates every A1 evidence stream and decides whether a new
Q2A/A1 release record + immutable tag may be emitted:

  * full pytest regression
  * Tier 0 / Q1 release records + immutable tags byte-unchanged
  * privacy red lines (novels/, runtime/, .taskflow/ evidence never tracked)
  * A1 canary evidence aggregation
      - G0 provider/policy load-bearing walls   (g0_report.json)
      - G3 trustworthy-stop canary              (g3_report.json)
      - G7 frozen-holdout judge eligibility     (auto-calibrate holdout_report.json)
      - three-genre 30-chapter canary terminals (novels/canary-*/output/*/terminal.json)
  * gate decision G6/G7/G8/G9

Only when every gate passes does it build the Q2A/A1 release record and create a
new immutable tag (old tags are never moved or rewritten).  Otherwise it reports
the honest withheld status and exits 1.

Privacy: the aggregate result carries only SHA-256 / model identity / token
counts / cost / gate booleans — never prompt text, prose, thinking, or
credentials.  The real canary evidence stays in the gitignored evidence dirs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Evidence dirs (all gitignored — see .gitignore: runtime/, .taskflow/, novels/*/)
TASKFLOW_RUNTIME = (
    REPO_ROOT
    / ".taskflow"
    / "active"
    / "autonomous-high-quality-production"
    / "runtime"
)
CALIBRATE_EVIDENCE = REPO_ROOT / "novels" / "a1-calibrate" / "output" / "calibrate-auto"

# Frozen-release anchors (re-anchored 2026-08-29 to the sanctioned 2026-08-06
# re-certification state: v0.1.2-tier0 is an annotated tag rebuilt onto the
# rewritten checkpoint 3287e0f — see commit a05b978 "release 记录 git_commit
# 重定位至重写后 checkpoint 3287e0f" and 03_current_status.md §1; the
# pre-rewrite anchor 91ab4e6 is an orphaned object).  From now on these bytes
# and tag targets are the frozen baseline: any further change fails G9.
FROZEN_RELEASES = {
    "tier0": {
        "record": REPO_ROOT / "docs" / "00_project" / "releases" / "tier0-release.json",
        "record_sha256": "7e76ae341bb3c4b85d89d792e80f157493d51f2b19a3122bed49298fbc658fbb",
        "tag": "v0.1.2-tier0",
        "tag_commit": "3287e0feb20691a0add37d1eec7173664beb3172",
    },
    "q1": {
        "record": REPO_ROOT / "docs" / "00_project" / "releases" / "q1-release.json",
        "record_sha256": "dd1f5de570564dddd9a459326c874bf52daf09a75ff87fce92426d0f1269d14e",
        "tag": "v0.1.3-q1",
        "tag_commit": "ff66b9b24e8fb5099ab3c1b2bfda3b6e60e46fa2",
    },
}

FULL_PYTEST_COMMAND = [
    sys.executable,
    "-m",
    "pytest",
    "tests",
    "-q",
    "-p",
    "no:cacheprovider",
    "--basetemp",
    ".pytest-tmp-a1-release-evidence",
]

GATE_RESULT_PATH = TASKFLOW_RUNTIME / "a1_gate_result.json"


# ---------------------------------------------------------------- helpers


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing evidence: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


# ---------------------------------------------------------------- gates


def verify_frozen_releases() -> list[str]:
    """Requirement §8: existing Tier 0 tag and record bytes unchanged."""
    errors: list[str] = []
    for name, spec in FROZEN_RELEASES.items():
        record = spec["record"]
        if not record.exists():
            errors.append(f"[Tier0/Q1] {name} release record missing: {record}")
            continue
        actual_sha = _sha256(record)
        if actual_sha != spec["record_sha256"]:
            errors.append(
                f"[Tier0/Q1] {name} record sha256 changed "
                f"{spec['record_sha256'][:12]} -> {actual_sha[:12]}"
            )
        resolved = _git(["rev-parse", "--verify", f"refs/tags/{spec['tag']}^{{commit}}"])
        if resolved != spec["tag_commit"]:
            errors.append(
                f"[Tier0/Q1] {name} tag {spec['tag']} moved/absent "
                f"(expected {spec['tag_commit'][:12]}, got {resolved[:12] or 'none'})"
            )
    return errors


def _scan_aggregate_forbidden(raw: str) -> list[str]:
    """Check a serialized aggregate for prose/thinking/credential-like fields.

    Only flags real (non-marker, non-empty) credential values.  The g0 evidence
    embeds the safe existence marker `"credential": "present_not_recorded"` and
    the redacted endpoint `loopback_from_credential_source`; those are not
    secrets and must not trip.
    """
    hits: list[str] = []
    hard_forbidden = ["prompt", "prose_text", "thinking", "api_key", "auth_token"]
    hits = [t for t in hard_forbidden if re.search(rf'"{t}"', raw)]
    # credential-like keys with a real (non-marker, non-empty) value
    for m in re.finditer(r'"(\w*(?:credential|token|secret|password)\w*)"\s*:\s*"([^"]*)"', raw):
        key, value = m.group(1), m.group(2)
        if value and value not in {"present_not_recorded", "loopback_from_credential_source"}:
            hits.append(f"{key}={value[:12]}")
    return sorted(set(hits))


def privacy_scan() -> list[str]:
    """Privacy red line: real-novel evidence dirs must never be tracked.

    `.gitignore` deliberately force-tracks the *synthetic* tier0 canary evidence
    (`!novels/tier0-*-canary/`, `!canary_inputs/tier0_*`); those are allowed.
    Everything else under novels/, canary_inputs/, runtime/, .taskflow/,
    reference_texts/ and .private_backup/ must not be tracked.

    The persisted aggregate is checked separately (see `_scan_aggregate_forbidden`)
    against the exact bytes this run emits.
    """
    errors: list[str] = []
    tracked = _git(["ls-files"]).splitlines()
    allowed_novel_prefixes = ("novels/tier0-", "novels/.gitkeep")
    allowed_canary_prefixes = ("canary_inputs/tier0_",)
    for path in tracked:
        if path.startswith("novels/") and not path.startswith(allowed_novel_prefixes):
            errors.append(f"[privacy] tracked real-novel path: {path}")
        if path.startswith("canary_inputs/") and not path.startswith(allowed_canary_prefixes):
            errors.append(f"[privacy] tracked real canary input: {path}")
        if path.startswith(("runtime/", ".taskflow/", "reference_texts/", ".private_backup/")):
            errors.append(f"[privacy] tracked evidence path: {path}")
    return errors


def aggregate_canary() -> dict[str, Any]:
    """Aggregate three-genre 30-chapter canary evidence + run terminals."""
    cpa_policy = REPO_ROOT / "runtime" / "refs" / "cpa_active" / "canary_policy_s6_cpa.json"
    if cpa_policy.exists():
        policy = _load_json(cpa_policy)
        canary_spec = dict(policy.get("canary", {}))
        expected_each = int(canary_spec.get("chapters_per_genre", 0))
        genres = {
            str(genre_key): {"scenes": expected_each}
            for genre_key in canary_spec.get("genres", [])
        }
    else:
        setup_manifest = _load_json(
            REPO_ROOT / "runtime" / "refs" / "t8_canary" / "setup_manifest.json"
        )
        genres = dict(setup_manifest.get("genres", {}))

    current_dirs = {
        "contemporary_officialdom": "s6-canary-offdom",
        "mythic_fantasy": "s6-canary-mythic",
        "historical_strategy": "s6-canary-hist",
    }
    per_genre: dict[str, Any] = {}
    for genre_key, spec in genres.items():
        expected = int(spec.get("scenes", 0))
        runs: list[dict[str, Any]] = []
        novel_dir = current_dirs.get(
            genre_key, f"canary-{genre_key.replace('_', '-')}"
        )
        run_root = REPO_ROOT / "novels" / novel_dir / "output"
        if run_root.exists():
            for run_dir in sorted(p for p in run_root.iterdir() if p.is_dir()):
                terminal = run_dir / "terminal.json"
                if not terminal.exists():
                    continue
                data = _load_json(terminal)
                runs.append(
                    {
                        "run_dir": run_dir.name,
                        "status": data.get("status"),
                        "terminal_reason": data.get("terminal_reason"),
                        "committed_chapters": int(data.get("committed_chapters") or 0),
                        "usage": data.get("usage"),
                    }
                )
        committed = sum(int(r["committed_chapters"]) for r in runs)
        per_genre[genre_key] = {
            "expected_chapters": expected,
            "committed_chapters": committed,
            "run_attempts": runs,
            "certified": committed == expected,
        }
    total_expected = sum(int(g.get("expected_chapters", 0)) for g in per_genre.values())
    total_committed = sum(int(g.get("committed_chapters", 0)) for g in per_genre.values())
    return {
        "genres": per_genre,
        "total_expected": total_expected,
        "total_committed": total_committed,
        "certified": total_committed == total_expected,
    }


def evaluate_gates(
    *,
    g0: dict[str, Any],
    g3: dict[str, Any],
    holdout: dict[str, Any],
    canary: dict[str, Any],
    pytest_ok: bool,
    pytest_summary: str,
    frozen_errors: list[str],
    privacy_errors: list[str],
) -> dict[str, Any]:
    """Deterministic gate evaluation against frozen thresholds (never lowered)."""
    gates: dict[str, Any] = {}

    gates["G0"] = {
        "label": "Provider/policy load-bearing walls (profile/policy frozen, G0 report pass)",
        "pass": g0.get("status") == "pass",
        "detail": {
            "status": g0.get("status"),
            "policy_sha256": g0.get("provider", {}).get("policy_sha256"),
            "profile_sha256": g0.get("provider", {}).get("profile_sha256"),
        },
    }

    gates["G3"] = {
        "label": "Trustworthy stop canary (zero generation calls after stop)",
        "pass": g3.get("status") == "pass",
        "detail": {"status": g3.get("status"), "terminal": g3.get("evidence", {}).get("terminal")},
    }

    overall = bool(holdout.get("dimension_met", {}).get("overall", False))
    per_tag = bool(holdout.get("dimension_met", {}).get("per_tag", False))
    position = bool(holdout.get("dimension_met", {}).get("position_consistency", False))
    gates["G7"] = {
        "label": "Judge eligibility: frozen holdout overall/per-tag/position consistency",
        "pass": bool(holdout.get("met")) and overall and per_tag and position,
        "detail": {
            "overall_accuracy": holdout.get("overall_accuracy"),
            "position_consistency": holdout.get("position_consistency"),
            "dimension_met": holdout.get("dimension_met"),
            "violations": holdout.get("violations"),
            "thresholds_id": holdout.get("thresholds_id"),
        },
    }

    gates["G8"] = {
        "label": "Three frozen genres x 30 chapters unattended canary",
        "pass": canary.get("certified", False),
        "detail": {
            "total_expected": canary.get("total_expected"),
            "total_committed": canary.get("total_committed"),
            "per_genre": {
                k: {
                    "committed": v["committed_chapters"],
                    "expected": v["expected_chapters"],
                    "attempts": len(v["run_attempts"]),
                }
                for k, v in canary.get("genres", {}).items()
            },
        },
    }

    gates["G9"] = {
        "label": "Full regression + privacy + frozen old tags + single command",
        "pass": pytest_ok and not privacy_errors and not frozen_errors,
        "detail": {
            "pytest_summary": pytest_summary,
            "privacy_errors": privacy_errors,
            "frozen_release_errors": frozen_errors,
        },
    }

    all_pass = all(g["pass"] for g in gates.values())
    return {"gates": gates, "all_pass": all_pass}


def _privacy_clean_summary(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full evidence report to privacy-clean scalars.

    The aggregate gate result must carry only SHA-256 / model identity / token
    counts / cost / gate booleans — never prompt text, prose, thinking,
    credentials, machine paths, or real novel names.
    """
    if not raw:
        return {"status": "missing"}
    if name == "g0":
        provider = raw.get("provider", {}) or {}
        return {
            "status": raw.get("status"),
            "policy_sha256": provider.get("policy_sha256"),
            "profile_sha256": provider.get("profile_sha256"),
            "checked_at": raw.get("checked_at") or raw.get("checked_at_utc"),
        }
    if name == "g3":
        return {"status": raw.get("status")}
    if name == "holdout":
        return {
            "met": raw.get("met"),
            "overall_accuracy": raw.get("overall_accuracy"),
            "position_consistency": raw.get("position_consistency"),
            "dimension_met": raw.get("dimension_met"),
            "thresholds_id": raw.get("thresholds_id"),
        }
    return {"status": raw.get("status")}


def build_release_record(
    *,
    g0: dict[str, Any],
    canary: dict[str, Any],
    pytest_summary: str,
    head: str,
) -> dict[str, Any]:
    """Q2A/A1 release record payload (only invoked on the all-pass path)."""
    import datetime

    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    release_id = f"q2a-a1-{created[:10].replace('-', '')}"
    return {
        "schema_version": 1,
        "type": "q2a_a1_release_record",
        "production_tier": "a1_autonomous",
        "release_id": release_id,
        "created_at_utc": created,
        "git_commit": head,
        "baseline_tests_passing": int(re.search(r"(\d+) passed", pytest_summary).group(1)),
        "full_pytest_result": pytest_summary,
        "canary_result": "pass",
        "canary_committed_chapters": canary["total_committed"],
        "gates_passed": ["G0", "G3", "G7", "G8", "G9"],
        "privacy_verified": True,
        "frozen_releases_verified": True,
        "evidence": {
            "g0_report": "runtime/g0_report.json",
            "g3_report": "runtime/g3_report.json",
            "holdout_report": "novels/a1-calibrate/output/calibrate-auto/holdout_report.json",
            "canary_setup_manifest": "runtime/refs/t8_canary/setup_manifest.json",
            "release_validator": "scripts/a1_release_validation.py",
        },
    }


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-full-pytest",
        action="store_true",
        help="skip running the full pytest suite (use --full-pytest-result)",
    )
    parser.add_argument(
        "--full-pytest-result",
        default="",
        help="saved full pytest summary line, e.g. '2724 passed' (with --skip-full-pytest)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="do not write a1_gate_result.json (dry run)",
    )
    args = parser.parse_args(argv)

    result: dict[str, Any] = {"schema_version": "1.0", "command": "a1_release_validation"}
    hard_errors: list[str] = []

    # --- evidence load -------------------------------------------------
    evidence: dict[str, Any] = {}
    for name, path in [
        ("g0", TASKFLOW_RUNTIME / "g0_report.json"),
        ("g3", TASKFLOW_RUNTIME / "g3_report.json"),
        ("holdout", CALIBRATE_EVIDENCE / "holdout_report.json"),
    ]:
        try:
            evidence[name] = _load_json(path)
        except Exception as exc:
            hard_errors.append(str(exc))
            evidence[name] = {}
    canary = aggregate_canary() if (REPO_ROOT / "runtime").exists() else {}

    # --- full pytest ---------------------------------------------------
    pytest_summary = args.full_pytest_result
    if not args.skip_full_pytest:
        proc = subprocess.run(
            FULL_PYTEST_COMMAND,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        summary = proc.stdout.strip().splitlines()
        last = summary[-1] if summary else ""
        pytest_summary = last
        if proc.returncode != 0:
            hard_errors.append(f"full pytest failed (exit {proc.returncode}): {last}")

    head = _git(["rev-parse", "HEAD"])
    frozen_errors = verify_frozen_releases()
    privacy_errors = privacy_scan()

    gate = evaluate_gates(
        g0=evidence.get("g0", {}),
        g3=evidence.get("g3", {}),
        holdout=evidence.get("holdout", {}),
        canary=canary,
        pytest_ok=not hard_errors,
        pytest_summary=pytest_summary,
        frozen_errors=frozen_errors,
        privacy_errors=privacy_errors,
    )

    result.update(
        {
            "checked_at_utc": None,  # stamped by caller / not needed for decision
            "head": head,
            "evidence": {
                "g0": _privacy_clean_summary("g0", evidence.get("g0", {})),
                "g3": _privacy_clean_summary("g3", evidence.get("g3", {})),
                "holdout": _privacy_clean_summary("holdout", evidence.get("holdout", {})),
                "canary": canary,
            },
            "pytest_summary": pytest_summary,
            "frozen_release_errors": frozen_errors,
            "privacy_errors": privacy_errors,
            "hard_errors": hard_errors,
            **gate,
        }
    )

    # Privacy red line: the aggregate bytes we are about to emit must not carry
    # prose/prompt/thinking or real credential values.  Scan the exact payload.
    forbidden = _scan_aggregate_forbidden(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    if forbidden:
        privacy_errors.append(
            f"[privacy] aggregate carries forbidden fields: {forbidden}"
        )
        result["privacy_errors"] = privacy_errors
        result["gates"]["G9"]["pass"] = False
        result["gates"]["G9"]["detail"]["privacy_errors"] = privacy_errors
        if "all_pass" in result:
            result["all_pass"] = all(g["pass"] for g in result["gates"].values())

    honest_status = "合同和 Provider 承重墙已完成，自动生产系统未完成"
    if gate["all_pass"] and not hard_errors and not forbidden:
        result["verdict"] = "certified"
        result["honest_status"] = "A1 自动生产系统已通过全部验收"
        if not args.no_write and not args.skip_full_pytest:
            release = build_release_record(
                g0=evidence["g0"], canary=canary, pytest_summary=pytest_summary, head=head
            )
            result["release_record"] = release
    else:
        result["verdict"] = "withheld"
        result["honest_status"] = honest_status
        result["failed_gates"] = [name for name, g in result["gates"].items() if not g["pass"]]

    emitted = json.dumps(result, ensure_ascii=False, indent=2)
    if not args.no_write:
        GATE_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        GATE_RESULT_PATH.write_text(emitted, encoding="utf-8")

    print(emitted)
    print(f"\n== verdict: {result['verdict']} :: {result['honest_status']} ==")
    return 0 if (result.get("all_pass") and not hard_errors and not forbidden) else 1


if __name__ == "__main__":
    raise SystemExit(main())
