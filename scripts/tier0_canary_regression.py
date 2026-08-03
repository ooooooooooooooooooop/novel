#!/usr/bin/env python
"""Tier 0 three-flow canary regression gate.

Read-only regression check over the three pinned canary workspaces
(novels/tier0-canary, novels/tier0-extend-canary, novels/tier0-compose-canary).

What this covers:
  1. `novel gate <name> --json` for each of audit / extend / compose still returns
     ok=true / review_route=pass / next_workflow=ContinueUnit / blocking_pending_count=0.
  2. Each flow's final-artifact sha256 matches the values pinned in
     docs/00_project/releases/tier0-three-flow-canary-aggregation.json (drift detection).

What this does NOT cover (by design, documented here so it is not silently assumed):
  - Re-running `novel respond` materialization from a clean workspace. That path is
    covered by tests/test_novel_cli.py within the 1540-test pytest baseline.
    The audit canary workspace is an immutable evidence baseline (doc 32 binds its
    sha256) and must not be mutated by regression, so we do not replay writes here.
  - Response content quality (that is the Review unit's job, not the regression gate).
  - The long-form --range/--batch-size path (pass --long-form to opt in, not yet wired).

Exit code 0 = all flows pass; non-zero = at least one flow failed or drifted.

This script performs NO LLM/API calls and does not advance any workflow.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGGREGATION = REPO_ROOT / "docs" / "00_project" / "releases" / "tier0-three-flow-canary-aggregation.json"

FLOWS = [
    ("audit", "tier0-canary"),
    ("extend", "tier0-extend-canary"),
    ("compose", "tier0-compose-canary"),
]

GATE_REQUIRED = {
    "ok": True,
    "review_route": "pass",
    "next_workflow": "ContinueUnit",
    "blocking_pending_count": 0,
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_gate(novel: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "src.novel_cli", "gate", novel, "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"  [gate] command failed rc={proc.returncode}")
        print(proc.stderr.strip())
        return {}
    return json.loads(proc.stdout)


def _check_gate(name: str, gate: dict) -> list[str]:
    failures = []
    if not gate:
        failures.append("gate produced no JSON output")
        return failures
    for field, expected in GATE_REQUIRED.items():
        actual = gate.get(field)
        if actual != expected:
            failures.append(f"gate.{field}={actual!r} expected {expected!r}")
    return failures


def _check_artifacts(flow: str, workspace_artifacts: dict) -> list[str]:
    failures = []
    for rel_path, expected_hash in workspace_artifacts.items():
        p = REPO_ROOT / rel_path
        if not p.exists():
            failures.append(f"missing artifact {rel_path}")
            continue
        actual = _sha256(p)
        if actual != expected_hash:
            failures.append(f"drift {rel_path}: expected {expected_hash} got {actual}")
    return failures


def main() -> int:
    if not AGGREGATION.exists():
        print(f"FATAL: aggregation evidence not found: {AGGREGATION}")
        return 2
    agg = json.loads(AGGREGATION.read_text(encoding="utf-8"))

    overall_ok = True
    for flow, novel in FLOWS:
        print(f"[{flow}] novel gate {novel} --json")
        gate = _run_gate(novel)
        gate_failures = _check_gate(flow, gate)
        artifact_failures = _check_artifacts(flow, agg["flows"][flow]["final_artifact_sha256"])
        # also verify gate file itself matches aggregation sha256
        gate_path = REPO_ROOT / agg["flows"][flow]["gate_result_path"]
        if not gate_path.exists():
            artifact_failures.append(f"missing gate file {agg['flows'][flow]['gate_result_path']}")
        else:
            gate_disk = _sha256(gate_path)
            if gate_disk != agg["flows"][flow]["gate_result_sha256"]:
                artifact_failures.append(
                    f"drift gate file {agg['flows'][flow]['gate_result_path']}: "
                    f"expected {agg['flows'][flow]['gate_result_sha256']} got {gate_disk}"
                )

        failures = gate_failures + artifact_failures
        if failures:
            overall_ok = False
            print(f"  FAIL ({len(failures)}):")
            for fmsg in failures:
                print(f"    - {fmsg}")
        else:
            print(f"  PASS (ok={gate.get('ok')} route={gate.get('review_route')} "
                  f"next={gate.get('next_workflow')} blocking={gate.get('blocking_pending_count')})")

    print()
    if overall_ok:
        print("Tier 0 three-flow canary regression: PASS")
        return 0
    print("Tier 0 three-flow canary regression: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
