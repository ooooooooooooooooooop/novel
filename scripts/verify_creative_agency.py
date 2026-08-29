"""Run all three creative-agency mechanism selftests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


MODULES = (
    "src.research_agency.experience_ledger",
    "src.research_agency.reflective_override",
    "src.research_agency.experience_ablation",
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    for module in MODULES:
        command = [sys.executable, "-m", module, "--selftest"]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        if completed.returncode != 0:
            print(f"FAIL: {module} (exit {completed.returncode})")
            if output:
                print(output)
            return 1
        if output:
            print(output)

    print("PASS: verify_creative_agency (3/3 selftests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
