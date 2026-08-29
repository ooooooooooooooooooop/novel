"""S6 90 章 Canary 驱动——分段跑（每 run 1 章，run 级重试）。

A1 是 M1 单次调用契约（零重试、零回退），但 api.b.ai 上游偶发不稳定
（429/RemoteDisconnected/ProviderSchemaError）。直接跑 30 章单 run 的
成功率极低。分段跑策略：
- 每 run 只跑 1 章（max_chapters_per_run=1）
- 成功：自动提交 chapters/ + 持久化 state_package.json
- 失败：保留 chapters/（已提交章不丢失），新 run 从最后提交的 state 续跑
- 每章最多重试 max_attempts 次

用法：
  powershell> cd <repo>
  powershell> $env:ANTHROPIC_AUTH_TOKEN="sk-..."
  powershell> python scripts/s6_canary_driver.py --genre offdom --chapters 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.boundary_control.chapter_commit import ChapterCommitBoundary
from src.object_state.autonomous import (
    AutonomousPolicy,
    ProviderProfile,
    canonical_model_sha256,
)
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
BASE_POLICY = REPO / "runtime/refs/cpa_active/canary_policy_s6_cpa.json"
PROFILE = REPO / "runtime/refs/cpa_active/provider_profile_cpa.json"

GENRES = {
    "offdom": ("s6-canary-offdom", "base_state_contemporary_officialdom.json"),
    "mythic": ("s6-canary-mythic", "base_state_mythic_fantasy.json"),
    "hist": ("s6-canary-hist", "base_state_historical_strategy.json"),
}

# 每章需要的最多调用数（35 为上界，给 60 余量）
CHAPTER_POLICY_OVERRIDES = {
    "budget": {
        "max_canary_chapters_total": 3,
        "max_canary_runs": 3,
        "max_chapters_per_run": 1,
        "max_total_calls": 60,
        "max_total_cost_usd": "1.0",
        "max_total_input_tokens": 500000,
        "max_total_output_tokens": 300000,
        "max_wall_clock_seconds": 3600,
    },
    "canary": {
        "chapters_per_genre": 1,
        "genres": ["contemporary_officialdom", "mythic_fantasy", "historical_strategy"],
        "long_horizon_checkpoints": [1],
    },
    "chapter": {"judge_max_output_tokens": 20000, "prose_max_output_tokens": 20000, "planner_max_output_tokens": 20000},
}


def _make_chapter_policy(base: dict) -> dict:
    """生成 1 章 policy（保留原 policy 结构，只覆盖 budget/canary/chapter）。"""
    d = dict(base)
    for k, v in CHAPTER_POLICY_OVERRIDES.items():
        if isinstance(v, dict):
            d[k] = {**d.get(k, {}), **v}
        else:
            d[k] = v
    return d


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


MECHANISM_FILES = (
    "src/auto_short_form.py",
    "src/workflow_action/autonomous_runner.py",
    "src/workflow_action/judge_council.py",
    "src/workflow_action/preference_review.py",
    "src/workflow_action/pareto_tournament.py",
    "src/workflow_action/review.py",
    "src/workflow_action/serial_reader.py",
    "src/workflow_action/prose.py",
    "src/boundary_control/reader_gate.py",
    "src/boundary_control/chapter_commit.py",
    "src/object_state/autonomous.py",
    "src/object_state/run_manifest.py",
    "src/object_state/reviewissue.py",
)


def _mechanism_source_sha256() -> str:
    rows = [
        f"{relative}:{_sha256_file(REPO / relative)}" for relative in MECHANISM_FILES
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _campaign_identity(
    novel: str, genre: str, base_state: Path
) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "campaign": novel,
        "genre": genre,
        "base_state_sha256": _sha256_file(base_state),
        "policy_sha256": canonical_model_sha256(
            AutonomousPolicy.model_validate(
                _make_chapter_policy(
                    json.loads(BASE_POLICY.read_text(encoding="utf-8"))
                )
            )
        ),
        "profile_sha256": canonical_model_sha256(
            ProviderProfile.model_validate_json(PROFILE.read_text(encoding="utf-8"))
        ),
        "mechanism_source_sha256": _mechanism_source_sha256(),
    }


def _ensure_campaign_identity(
    novel_dir: Path, expected: dict[str, str | int]
) -> None:
    path = novel_dir / "output" / "campaign_identity.json"
    existing_artifacts = (
        (novel_dir / "chapters").exists()
        and any((novel_dir / "chapters").glob("chapter_*.txt"))
    ) or (
        (novel_dir / "output").exists()
        and any(p.is_dir() and _run_order(p) != (-1, -1) for p in (novel_dir / "output").iterdir())
    )
    if not path.exists():
        if existing_artifacts:
            raise ValueError(
                "campaign workspace contains chapters/runs but no campaign_identity.json"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return
    actual = json.loads(path.read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("campaign identity mismatch; refusing workspace reuse")


def _committed_chapters(novel_dir: Path) -> int:
    ch_dir = novel_dir / "chapters"
    if not ch_dir.exists():
        return 0
    numbers = sorted(
        int(path.stem.split("_", 1)[1]) for path in ch_dir.glob("chapter_*.txt")
    )
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("committed chapters must be exactly continuous from chapter_1")
    return len(numbers)


def _run_order(path: Path) -> tuple[int, int]:
    """chN-tryM 按数值排序；未知目录排在所有合法 run 之前。"""
    match = re.fullmatch(r"ch(\d+)-try(\d+)", path.name)
    return tuple(map(int, match.groups())) if match else (-1, -1)


def _last_committed_baseline(
    novel_dir: Path, run_dir: Path
) -> tuple[Path, Path] | None:
    """返回同一最后已提交 run 的 state package 与 frames，禁止混源续写。"""
    if not run_dir.exists():
        return None
    runs = sorted(
        (path for path in run_dir.iterdir() if path.is_dir()),
        key=_run_order,
        reverse=True,
    )
    for run in runs:
        manifest = run / "manifest.json"
        run_manifest = run / "run_manifest.json"
        if not manifest.exists() or not run_manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recovery = ChapterCommitBoundary(run, novel_dir / "chapters").recover()
        lineage = recovery.manifest
        state_path = run / "state" / "state_package.json"
        frames_path = run / "state" / "frames.json"
        expected_chapter = _committed_chapters(novel_dir)
        if (
            int(data.get("committed_chapters", 0) or 0) >= 1
            and recovery.recognized
            and lineage is not None
            and lineage.review_route == "pass"
            and lineage.chapter_number == expected_chapter
            and state_path.exists()
            and frames_path.exists()
        ):
            return state_path, frames_path
    return None


def _validate_committed_run(
    run_dir: Path, *, chapter_number: int, input_state: Path
) -> tuple[bool, str]:
    novel_dir = run_dir.parent.parent
    recovery = ChapterCommitBoundary(run_dir, novel_dir / "chapters").recover()
    manifest = recovery.manifest
    if not recovery.recognized or manifest is None:
        return False, f"recover rejected committed run: {recovery.reason}"
    state_path = run_dir / "state" / "state_package.json"
    frames_path = run_dir / "state" / "frames.json"
    chapter_path = novel_dir / "chapters" / f"chapter_{chapter_number}.txt"
    identity_path = novel_dir / "output" / "campaign_identity.json"
    required_paths = {
        chapter_path,
        run_dir / "prose_history" / f"draft_chapter_{chapter_number}.txt",
        run_dir / "chapter_provenance.json",
        state_path,
        frames_path,
        run_dir / "reader_gate_report.json",
        identity_path,
    }
    if chapter_number >= 3:
        required_paths.add(run_dir / "serial_reader_report.json")
    artifact_paths = set(manifest.artifacts)
    missing_artifacts = [
        str(path)
        for path in required_paths
        if ChapterCommitBoundary(run_dir, novel_dir / "chapters")._rel(path)
        not in artifact_paths
    ]
    checks = {
        "review_route": manifest.review_route == "pass",
        "chapter_number": manifest.chapter_number == chapter_number,
        "draft_hash": manifest.draft_hash == _sha256_file(chapter_path),
        "facts_package_hash": bool(manifest.facts_package_hash),
        "state_before_hash": manifest.state_before_hash == _sha256_file(input_state),
        "state_after_hash": manifest.state_after_hash == _sha256_file(state_path),
        "frame_hash": manifest.frame_hash == _sha256_file(frames_path),
        "campaign_identity_hash": (
            manifest.campaign_identity_hash == _sha256_file(identity_path)
        ),
        "required_artifacts": not missing_artifacts,
    }
    if chapter_number > 1:
        prev = novel_dir / "chapters" / f"chapter_{chapter_number - 1}.txt"
        checks["prev_chapter_ref"] = (
            manifest.prev_chapter_ref == f"chapter_{chapter_number - 1}"
        )
        checks["prev_chapter_hash"] = manifest.prev_chapter_hash == _sha256_file(prev)
    failed = [name for name, passed in checks.items() if not passed]
    return (not failed, "ok" if not failed else "lineage mismatch: " + ", ".join(failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--genre", choices=list(GENRES), required=True)
    parser.add_argument("--chapters", type=int, default=30)
    parser.add_argument(
        "--campaign-name",
        default="",
        help="全新隔离 workspace 名；缺省沿用该类型的 s6-canary-* 名称",
    )
    parser.add_argument(
        "--min-interval", type=float, default=60.0, help="provider 调用最小间隔秒数"
    )
    parser.add_argument("--max-attempts", type=int, default=10, help="每章重试上限")
    parser.add_argument("--cooldown", type=int, default=180, help="失败后冷却秒数")
    parser.add_argument(
        "--skip-ch",
        type=str,
        default="",
        help="逗号分隔的章节号，直接跳过（如 --skip-ch 7,12）",
    )
    parser.add_argument(
        "--max-attempts-override",
        type=str,
        default="",
        help="逗号分隔 章:次数（如 --max-attempts-override 7:30）",
    )
    args = parser.parse_args(argv)

    skip_ch = {int(x) for x in args.skip_ch.split(",") if x.strip()}
    attempts_override = {}
    for pair in args.max_attempts_override.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            attempts_override[int(k)] = int(v)

    default_novel, base_name = GENRES[args.genre]
    novel = args.campaign_name or default_novel
    novel_dir = REPO / "novels" / novel
    base_state = REPO / "runtime/refs/bai_active" / base_name
    base_policy = json.loads(BASE_POLICY.read_text(encoding="utf-8"))
    try:
        _ensure_campaign_identity(
            novel_dir, _campaign_identity(novel, args.genre, base_state)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: campaign identity validation failed: {exc}")
        return 1

    env = dict(os.environ)
    env["CPA_BASE_URL"] = "http://127.0.0.1:8317"
    env["CPA_AUTH_TOKEN"] = "123456"
    env["NOVEL_PROVIDER_MIN_INTERVAL"] = str(args.min_interval)

    skipped: list[int] = []
    for ch in range(1, args.chapters + 1):
        committed = _committed_chapters(novel_dir)
        if committed >= ch:
            print(f"章节 {ch} 已提交，跳过")
            continue
        if ch in skip_ch:
            print(f"章节 {ch} 已由 --skip-ch 显式跳过，记录缺口")
            skipped.append(ch)
            continue

        max_attempts = attempts_override.get(ch, args.max_attempts)

        chapter_policy = _make_chapter_policy(base_policy)
        policy_path = novel_dir / "output" / f"_policy_ch{ch}.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps(chapter_policy, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        baseline = _last_committed_baseline(novel_dir, novel_dir / "output")
        if committed > 0 and baseline is None:
            print("Error: committed chapters exist but no hash-bound continuous baseline")
            return 1
        state_arg = str(baseline[0]) if baseline else str(base_state)
        frames_arg = str(baseline[1]) if baseline else ""

        success = False
        for attempt in range(1, max_attempts + 1):
            run_name = f"ch{ch}-try{attempt}"
            run_dir = novel_dir / "output" / run_name
            if run_dir.exists():
                shutil.rmtree(run_dir)

            cmd = [
                PY, "-m", "src.novel_cli", "auto", novel,
                "--policy", str(policy_path),
                "--profile", str(PROFILE),
                "--campaign-identity", str(novel_dir / "output" / "campaign_identity.json"),
                "--flow-mode", "compose",
                "--run-name", run_name,
                "--base-state", state_arg,
            ]
            if frames_arg:
                cmd.extend(["--base-frames", frames_arg])
            print(f"\n【章 {ch}/尝试 {attempt}/{max_attempts}】")
            result = subprocess.run(cmd, cwd=str(REPO), env=env, capture_output=True, text=True)
            tail = (result.stdout or "") + (result.stderr or "")
            print(tail[-1500:])

            if result.returncode == 0:
                new_committed = _committed_chapters(novel_dir)
                if new_committed > committed:
                    lineage_ok, lineage_reason = _validate_committed_run(
                        run_dir, chapter_number=ch, input_state=Path(state_arg)
                    )
                    if not lineage_ok:
                        print(f"Error: committed chapter failed lineage validation: {lineage_reason}")
                        return 1
                    print(f"  成功！已提交 {new_committed} 章；lineage=verified")
                    success = True
                    break
                else:
                    print(f"  返回码 0 但未提交新章（quality_exhausted/无进展），继续重试")
            else:
                print(f"  失败；冷却 {args.cooldown}s...")
                time.sleep(args.cooldown)

        if not success:
            print(f"章节 {ch} 在 {max_attempts} 次尝试后失败；严格连续 campaign 立即终止")
            skipped.append(ch)
            return 1

    print(f"\n=== {novel} 完成 {args.chapters} 章 ===")
    if skipped:
        print(f"缺口章（尝试耗尽后跳过）: {skipped}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())