#!/usr/bin/env python3
"""contract_short_form — 读者契约（Q1 R3）建立/编辑/检查入口.

用法:
    python src/contract_short_form.py --output-dir <dir> --mode extend|compose [--default]

- 首次运行：写 contract_prompt.txt（初始确定性草稿 + 作品约束 + 输出格式）
  → [WAITING] → 操作者填 contract_response.txt（严格 JSON）→ 重跑解析保存
  `output/<mode>/reader_contract.json`。
- 已存在契约且未指定 --edit/--default：直接打印当前契约摘要（检查模式）。
- --default：跳过 LLM，用确定性默认（build_initial_contract）直接保存契约。
- --edit：已存在契约时重新打开 staged 编辑（草稿=当前契约）。
- 契约只写中性机制，禁止作品名/作者笔名/机器路径（隐私纪律）。

sidecar 位置与 extend/compose 的 flow v3 读取点一致：output/<mode>/reader_contract.json。
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.runtime_state import require_continue_runtime_state
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state import WorkSpec
from src.workflow_action.reader_contract import (
    ReaderContractUnit,
    build_initial_contract,
    load_reader_contract,
    save_reader_contract,
)

CONTRACT_FILENAME = "reader_contract.json"
PROMPT_FILENAME = "contract_prompt.txt"
RESPONSE_FILENAME = "contract_response.txt"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _load_workspec_context(output_dir: Path, mode: str) -> str:
    """从 extend/compose 的工作区重建作品约束上下文（零成本：缺失返回空串）."""
    if mode == "extend":
        package_path = output_dir / "extend_rebuild_package.json"
        if package_path.exists():
            try:
                serializer = SerializationBoundaryUnit()
                package = serializer.load(package_path)
                objects = serializer.deserialize_package(package)
                workspec, _wm, _ns, _chars, _facts, _fg = require_continue_runtime_state(
                    objects
                )
                return workspec.to_prompt_context()
            except Exception:
                return ""
        return ""
    # compose
    novel_dir = output_dir.parent.parent
    workspec_path = novel_dir / "workspec.json"
    if workspec_path.exists():
        try:
            workspec = WorkSpec.model_validate_json(_read_text(workspec_path))
            return workspec.to_prompt_context()
        except Exception:
            return ""
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="读者契约建立/编辑/检查")
    parser.add_argument("--output-dir", default="output", help="输出目录（output/<mode>）")
    parser.add_argument("--mode", choices=["extend", "compose"], default="extend")
    parser.add_argument("--default", action="store_true", help="用确定性默认直接保存（零 LLM）")
    parser.add_argument("--edit", action="store_true", help="已存在契约时重新打开 staged 编辑")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    contract_path = output_dir / CONTRACT_FILENAME
    existing = load_reader_contract(output_dir)

    # 检查模式：已有契约且未要求编辑/重建 → 打印摘要退出。
    if existing is not None and not args.edit and not args.default:
        print(f"ReaderContract: {existing.contract_id}（{args.mode}）")
        print(f"  目标读者: {existing.audience}")
        print(f"  核心阅读快感: {' / '.join(existing.core_pleasures)}")
        print(f"  核心张力: {existing.core_tension}")
        print(f"  禁止漂移: {' / '.join(existing.forbidden_drifts) or '(无)'}")
        print(f"  有效钩子: {' / '.join(existing.valid_hooks) or '(未指定)'}")
        print(f"  contract: {contract_path}")
        return 0

    response_path = output_dir / RESPONSE_FILENAME
    if args.default:
        contract = build_initial_contract(contract_id="default", workspec=None)
        saved = save_reader_contract(output_dir, contract)
        print(f"Saved deterministic ReaderContract (--default): {saved}")
        return 0

    workspec_context = _load_workspec_context(output_dir, args.mode)
    unit = ReaderContractUnit()
    if response_path.exists():
        response = _read_text(response_path)
        contract = unit.parse_response(response)
        saved = save_reader_contract(output_dir, contract)
        print(f"Saved ReaderContract: {saved}")
        print(f"  contract_id: {contract.contract_id}")
        print(f"  目标读者: {contract.audience}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = output_dir / PROMPT_FILENAME
    prompt_path.write_text(
        unit.build_prompt(
            mode=args.mode,
            workspec_context=workspec_context,
            original_style_context="",
            initial_contract=existing if args.edit else None,
        ),
        encoding="utf-8",
    )
    print(f"[STEP: CONTRACT] Prompt saved: {prompt_path}")
    print(f"[WAITING] Generate response to: {response_path}")
    print("[RESUME] Re-run this script after saving response")
    return 0


if __name__ == "__main__":
    sys.exit(main())
