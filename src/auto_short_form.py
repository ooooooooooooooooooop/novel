#!/usr/bin/env python3
"""auto_short_form — A1 自动叙事生产 CLI 入口（doc 48 §6 step 2，T3）.

无 [WAITING]、无 staged response、无人工选稿：policy/profile 显式传入，
run 目录由 <novel>/output/<run-name> 派生（run_dir.parent.parent 必须是小说的
novels/ 工作目录，正文落盘到该小说 chapters/）。resume 只识别完整提交；
失败运行不会进入后续上下文。

用法:
    python src/auto_short_form.py --run-dir novels/<名>/output/<run> \
        --policy .taskflow/.../runtime/autonomous_policy.json \
        --profile .taskflow/.../runtime/provider_profile.json \
        --base-state <state_package.json> [--base-frames <frames.json>] \
        [--source-text <原文.txt>] [--reader-contract <reader_contract.json>] \
        [--time-book <time_book.json>] [--style <style_profile.json>] \
        [--nsfw on|off] [--flow-mode extend|compose] [--candidates N]

policy/profile 是 A1 冻结证据；policy.provider_profile_id 必须等于
profile.profile_id。本脚本只消费一次运行即冻结的上限，不使用运行时默认值。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state.autonomous import (
    TERMINAL_STATUSES,
    AutonomousPolicy,
    ProviderProfile,
)
from src.object_state.readercontract import ReaderContract
from src.object_state.timebook import TimeBook
from src.workflow_action.autonomous_runner import AutonomousRunner, AutonomousRunnerError
from src.workflow_action.style import StyleProfile


def _load_json_model(path: str, model):
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _load_style_context(path: str) -> str:
    """把风格档案渲染为注入文本（与 load_style_context 同渲染，include_header=False）."""
    profile = StyleProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return profile.to_prompt_context(include_header=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A1 自动叙事生产：闭环章节生成直至终态（无人工干预）"
    )
    parser.add_argument("--run-dir", required=True, help="A1 运行目录（<novel>/output/<run>）")
    parser.add_argument("--policy", required=True, help="冻结策略 JSON（AutonomousPolicy）")
    parser.add_argument("--profile", required=True, help="冻结 Provider 档案 JSON（ProviderProfile）")
    parser.add_argument("--base-state", default="", help="起始 SerializationPackage JSON（全新 run 必需）")
    parser.add_argument("--base-frames", default="", help="起始 Frame 状态 JSON（缺省从 workspec 构建）")
    parser.add_argument("--source-text", default="", help="原书文本文件（extend 锚点/文风/去重用；空=compose）")
    parser.add_argument("--reader-contract", default="", help="ReaderContract JSON（可选）")
    parser.add_argument("--time-book", default="", help="TimeBook JSON（可选）")
    parser.add_argument("--style", default="", help="StyleProfile JSON（可选）")
    parser.add_argument("--nsfw", choices=["on", "off"], default="off", help="内容分级（默认 off=正常向）")
    parser.add_argument("--flow-mode", choices=["compose", "extend"], default="extend")
    parser.add_argument("--candidates", type=int, default=1, help="每章生成轮数上限（章节内多候选由 policy.search.plot_candidates 决定，T5）")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    policy = _load_json_model(args.policy, AutonomousPolicy)
    profile = _load_json_model(args.profile, ProviderProfile)
    if policy.provider_profile_id != profile.profile_id:
        print(
            f"Error: policy.provider_profile_id ({policy.provider_profile_id}) "
            f"!= profile.profile_id ({profile.profile_id})"
        )
        return 1

    serializer = SerializationBoundaryUnit()
    objects: list | None = None
    frames: list | None = None
    fresh = not (run_dir / "manifest.json").is_file()
    if fresh:
        if not args.base_state:
            print("Error: 全新 run 需要 --base-state（起始 SerializationPackage JSON）")
            return 1
        if not Path(args.base_state).is_file():
            print(f"Error: base state not found: {args.base_state}")
            return 1
        package = serializer.load(Path(args.base_state))
        objects = serializer.deserialize_package(package)
        if args.base_frames:
            frames = json.loads(
                Path(args.base_frames).read_text(encoding="utf-8")
            )
    else:
        if args.base_state or args.base_frames:
            print("注意: run 已存在 manifest.json，忽略 --base-state/--base-frames（resume 以磁盘 state 为准）")

    source_text = ""
    if args.source_text:
        if not Path(args.source_text).is_file():
            print(f"Error: source text not found: {args.source_text}")
            return 1
        source_text = Path(args.source_text).read_text(encoding="utf-8-sig")

    reader_contract = (
        _load_json_model(args.reader_contract, ReaderContract)
        if args.reader_contract
        else None
    )
    time_book = (
        _load_json_model(args.time_book, TimeBook) if args.time_book else None
    )
    style_context = _load_style_context(args.style) if args.style else ""

    try:
        runner = AutonomousRunner(
            run_dir=run_dir,
            policy=policy,
            profile=profile,
            objects=objects,
            frames=frames,
            source_text=source_text,
            reader_contract=reader_contract,
            time_book=time_book,
            style_context=style_context,
            nsfw_on=(args.nsfw == "on"),
            initial_candidates_remaining=args.candidates,
            flow_mode=args.flow_mode,
        )
    except AutonomousRunnerError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"A1 run: {run_dir}")
    print(f"  status start: {runner.status}  committed_chapters: "
          f"{runner._run.committed_chapters}")
    try:
        terminal = runner.run_until_terminal()
    except AutonomousRunnerError as exc:
        print(f"Error: {exc}")
        return 1

    usage = terminal.usage
    print("\n" + "=" * 50)
    print("A1 terminal report")
    print("=" * 50)
    print(f"  status:            {terminal.status}")
    print(f"  terminal_reason:   {terminal.terminal_reason}")
    print(f"  committed_chapters:{terminal.committed_chapters}")
    print(f"  usage:             {usage.calls} calls / {usage.input_tokens} in / "
          f"{usage.output_tokens} out / ${usage.cost_usd}")
    print(f"  manifest:          {run_dir / 'manifest.json'}")
    if (run_dir / "terminal.json").exists():
        print(f"  terminal snapshot: {run_dir / 'terminal.json'}")
    if terminal.status == "execution_failed":
        print("\nExecution failed: run did not reach a legitimate stop; "
              "check the failure reason (error type only, no details).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
