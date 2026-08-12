#!/usr/bin/env python3
"""a1_g3_stop_canary_setup — 为 G3 门「可信停止 Canary → narrative_stopped 且零生成调用」
构造 A1 可信停止 Canary 的起始状态（derived base state）。

用法： python scripts/a1_g3_stop_canary_setup.py <novel_name>

不修改任何真实小说产物：从权威 artifacts 派生一份「确认停止」状态，供 `novel auto`
全新 run 使用（run 目录按惯例为 novels/<novel_name>/output/a1-g3-stop-canary/）。

派生依据（都不是本脚本凭空制造的）：
- 真实状态包： novels/<novel_name>/output/extend/extend_rebuild_package.json
  （Q1 续写到可信边界后的可信状态）。
- 真实帧：     novels/<novel_name>/output/recovery/failed_run_backup/extend_frames.json
  （真实运行的帧序列，最后一幕 resolution）。
- Q1 确认的停止裁决： novels/<novel_name>/output/extend/viability_report.json
  —— verdict=stop，理由明确「活跃承诺转为有意文学留白」；读者契约 forbidden_drifts
  亦规定「不消除开放式结局的文学歧义，不应被强行解释干净」。
- Frame 生命周期终态消费： advance_cursor 对最后 scene 无 successor 时标记 completed
  并完成父链（docs/00_project/44_state_lifecycle_audit.md Frame/Cursor 行）。

因此本脚本只做两处确定性状态投影：
1. ForeshadowGraph 中 2 条 active 承诺置为 `abandoned`（=叙事决策不再推进，有意留白）。
2. 对真实帧序列应用 advance_cursor 直至 get_cursor()==None（resolution 已消费，整个
   结构 completed）。

投影后 viability 将确定性返回 stop（无活跃帧 + 零活跃承诺 + 契约结束条件全触发），
这正是 G3 要求 narrative_stopped 的前置。原始状态与派生状态均保留，哈希记录在案。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.workflow_action.frame import NarrativeFrameUnit

RUNTIME = PROJECT_ROOT / ".taskflow" / "active" / "autonomous-high-quality-production" / "runtime"

OUT_DIR = RUNTIME / "refs" / "g3_stop_canary"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("Usage: python scripts/a1_g3_stop_canary_setup.py <novel_name>")
        return 2
    novel_name = argv[0]
    novel = PROJECT_ROOT / "novels" / novel_name
    extend = novel / "output" / "extend"

    # 0. 输入权威路径校验（全部必须存在，绝不凭空构造）。
    package_path = extend / "extend_rebuild_package.json"
    frames_path = novel / "output" / "recovery" / "failed_run_backup" / "extend_frames.json"
    stop_authority = extend / "viability_report.json"
    for p in (package_path, frames_path, stop_authority):
        if not p.is_file():
            print(f"Error: authoritative input missing: {p}")
            return 1

    serializer = SerializationBoundaryUnit()
    package = serializer.load(package_path)

    # 1. 投影 ForeshadowGraph：2 条 active 承诺 → abandoned（有意留白，不再推进）。
    fg_raw = dict(package.stable_memory["ForeshadowGraph"][0])
    projected_fg = json.loads(json.dumps(fg_raw))
    closed = []
    for entry in projected_fg["entries"]:
        if entry["current_status"] == "active":
            entry["current_status"] = "abandoned"
            entry.setdefault("payoff_nodes", []).append(
                "q1_confirmed_stop: 有意文学留白（不强行解释干净）"
            )
            closed.append(entry["thread_id"])
    if len(closed) != 2:
        print(
            f"Error: expected exactly 2 active promises to project, got {len(closed)}: "
            + ", ".join(closed)
        )
        return 1
    stable = dict(package.stable_memory)
    stable["ForeshadowGraph"] = [projected_fg]
    package = package.model_copy(update={"stable_memory": stable})

    # 2. 投影帧：advance_cursor 直至结构全部 completed（resolution 无 successor → 消费）。
    frames = json.loads(frames_path.read_text(encoding="utf-8"))
    frame_unit = NarrativeFrameUnit()
    steps = 0
    while frame_unit.get_cursor(frames) is not None:
        if steps > len(frames) + 4:
            print("Error: frame consumption did not terminate")
            return 1
        frame_unit.advance_cursor(frames)
        steps += 1
    cursor = frame_unit.get_cursor(frames)
    if cursor is not None:
        print(f"Error: frame state still has an active cursor: {cursor}")
        return 1

    # 3. 写入派生状态 + 帧，并记录输入/输出哈希。
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state_out = OUT_DIR / "base_state_package.json"
    frames_out = OUT_DIR / "base_frames.json"
    state_out.write_text(
        json.dumps(package.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    frames_out.write_text(
        json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "schema_version": "1.0",
        "gate": "G3",
        "kind": "stop_canary_base_state",
        "novel": novel_name,
        "trusted_boundary": "chapter_23",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_hashes": {
            "extend_rebuild_package.json": _file_sha256(package_path),
            "extend_frames.json": _file_sha256(frames_path),
            "viability_report.json": _file_sha256(stop_authority),
        },
        "projection": {
            "promises_closed": closed,
            "authority": "viability_report.json verdict=stop：活跃承诺转为有意文学留白",
            "frames_consumed_steps": steps,
            "authority_2": "advance_cursor 终止帧消费（44_state_lifecycle_audit Frame/Cursor）",
        },
        "output_hashes": {
            "base_state_package.json": _file_sha256(state_out),
            "base_frames.json": _file_sha256(frames_out),
        },
    }
    (OUT_DIR / "setup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("G3 stop-canary base state projected:")
    print(f"  base_state_package.json -> {state_out}")
    print(f"  base_frames.json        -> {frames_out}")
    print(f"  promises closed        -> {closed}")
    print(f"  frame consumption steps-> {steps}")
    print("原始状态与帧未修改；哈希见 setup_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
