#!/usr/bin/env python3
"""Unified CLI wrapper for staged novel workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.approval_gate import (
    APPROVAL_DECISION_FILE,
    APPROVAL_GATE_EXTRA_FIELDS,
    blocking_review_issue_ids,
    critical_review_issue_ids,
    load_approval_decision,
    resolve_approval_gate_verdict,
)
from src.boundary_control.automation_contracts import (
    AUTOMATION_FORBIDDEN_AUDIT_PAYLOAD_FIELDS,
    AUTOMATION_FORBIDDEN_EXECUTION_CLAIM_FIELDS,
    PENDING_AUTOMATION_METADATA_FIELDS,
    RESPONSE_MATERIALIZATION_METADATA_FIELDS,
    pending_automation_metadata,
    response_materialization_metadata,
    validate_pending_automation_metadata_in_payload,
    validate_response_materialization_metadata_in_payload,
)
from src.boundary_control.handoff import (
    HandoffBoundaryUnit,
    HandoffPacket,
    VALID_REVIEW_ROUTES,
    VALID_WORKFLOW_ROUTES,
)
from src.boundary_control.orchestration import OrchestrationGateUnit
from src.boundary_control.runtime_args import validate_long_runtime_args
from src.boundary_control.runtime_identity import (
    content_evidence_from_bytes,
    expected_staged_response_path,
    file_content_hash,
    file_content_evidence,
    model_content_hash,
    staged_slot_id,
    validate_content_hash,
    validate_run_hash,
)
from src.boundary_control.response_file import (
    PendingResponseSlot,
    ResponseFileBoundaryUnit,
    STAGED_RESPONSE_RESULT_FORBIDDEN_CONTENT_FIELDS,
)
from src.object_state import WorkSpec
from src.boundary_control.serialization import SerializationBoundaryUnit


# ---- F8 split ----
# 常量、校验函数与 gate/route/status 辅助函数已移到 src/cli/validation.py；
# 此处用 __all__ 重导出，保持下方编排代码的裸名引用不变。
from src.cli.validation import *  # noqa: F401,F403


# ===== 编排层：NovelArgumentParser / 各流 dispatch / run_config 恢复 =====（原 2157 行起）
class NovelArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, emit_json_errors: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.emit_json_errors = emit_json_errors

    def error(self, message: str) -> None:
        if self.emit_json_errors:
            payload = _json_error_payload(
                error_stage="argument",
                error_type="ArgumentError",
                error=message,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            self.exit(2)
        super().error(message)


def _novels_root() -> Path:
    root = os.environ.get("NOVELS_ROOT")
    return Path(root).resolve() if root else DEFAULT_NOVELS_ROOT


def _novel_dir(name: str) -> Path:
    _validate_novel_name(name)
    return _novels_root() / name


def _output_dir(novel_dir: Path, mode: str) -> Path:
    return novel_dir / "output" / mode


def _copy_to_workspace(source: str, target: Path) -> Path:
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"input file not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path != target.resolve():
        shutil.copy2(source_path, target)
    return target


def _ensure_input(args: argparse.Namespace, novel_dir: Path) -> Path:
    input_path = novel_dir / "input.txt"
    if args.input:
        return _copy_to_workspace(args.input, input_path)
    if input_path.exists():
        return input_path
    raise FileNotFoundError("missing --input and no existing novels/<name>/input.txt")


def _input_source(args: argparse.Namespace, novel_dir: Path) -> Path:
    if args.input:
        source_path = Path(args.input).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"input file not found: {args.input}")
        return source_path
    input_path = novel_dir / "input.txt"
    if input_path.exists():
        return input_path
    raise FileNotFoundError("missing --input and no existing novels/<name>/input.txt")


def _preflight_run_hash(
    *,
    output_dir: Path,
    hash_filename: str,
    current_hash: str,
    label: str,
) -> bool:
    errors = validate_run_hash(
        hash_path=output_dir / hash_filename,
        current_hash=current_hash,
        output_dir=output_dir,
        label=label,
        write_hash=False,
    )
    if not errors:
        return True
    for error in errors:
        print(error)
    return False


def _decode_text(data: bytes, path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode file: {path}")


def _read_text(path: Path) -> str:
    return _decode_text(Path(path).read_bytes(), Path(path))


def _read_text_with_hash(path: Path) -> tuple[str, str, int]:
    data = Path(path).read_bytes()
    evidence = content_evidence_from_bytes(data)
    return data.decode("utf-8-sig"), evidence.content_hash, evidence.byte_count


def _is_same_existing_file(left: Path, right: Path) -> bool:
    left = Path(left)
    right = Path(right)
    if not left.exists() or not right.exists():
        return False
    return left.samefile(right)


def _default_compose_workspec() -> WorkSpec:
    return WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )


def _write_mode(novel_dir: Path, mode: str) -> None:
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / MODE_FILE).write_text(mode, encoding="utf-8")


def _write_config(novel_dir: Path, data: dict) -> None:
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / CONFIG_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_config(novel_dir: Path) -> dict:
    config_path = novel_dir / CONFIG_FILE
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read run config: {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid run config JSON: {config_path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid run config object: {config_path}")
    unknown = sorted(set(data) - VALID_CONFIG_FIELDS)
    if unknown:
        raise ValueError(
            f"invalid run config field(s): {config_path}: {', '.join(unknown)}"
        )
    return data


def _read_mode(novel_dir: Path) -> str | None:
    config = _read_config(novel_dir)
    if "mode" in config:
        mode = config["mode"]
        if mode not in VALID_MODES:
            raise ValueError(f"invalid saved mode in {novel_dir / CONFIG_FILE}: {mode}")
        return mode
    mode_path = novel_dir / MODE_FILE
    if mode_path.exists():
        mode = mode_path.read_text(encoding="utf-8").strip() or None
        if mode is not None and mode not in VALID_MODES:
            raise ValueError(f"invalid saved mode in {mode_path}: {mode}")
        return mode
    return None


def _append_long_options(command: list[str], args: argparse.Namespace) -> None:
    if getattr(args, "chapter_wise", False):
        command.append("--chapter-wise")
    if getattr(args, "chapter_range", None):
        command.extend(["--range", args.chapter_range])
    if getattr(args, "batch_size", None) is not None:
        command.extend(["--batch-size", str(args.batch_size)])
    if getattr(args, "max_chapters", None) is not None:
        command.extend(["--max-chapters", str(args.max_chapters)])


def _validate_long_options(args: argparse.Namespace) -> None:
    validate_long_runtime_args(
        chapter_range=getattr(args, "chapter_range", None),
        batch_size=(
            getattr(args, "batch_size", None)
            if getattr(args, "batch_size", None) is not None
            else 50
        ),
        max_chapters=(
            getattr(args, "max_chapters", None)
            if getattr(args, "max_chapters", None) is not None
            else 100
        ),
    )


def _validate_configured_long_options(config: dict) -> None:
    validate_long_runtime_args(
        chapter_range=config.get("chapter_range"),
        batch_size=config.get("batch_size") if config.get("batch_size") is not None else 50,
        max_chapters=(
            config.get("max_chapters") if config.get("max_chapters") is not None else 100
        ),
    )


def _append_configured_long_options(command: list[str], config: dict) -> None:
    if config.get("chapter_wise"):
        command.append("--chapter-wise")
    if config.get("chapter_range"):
        command.extend(["--range", config["chapter_range"]])
    if config.get("batch_size") is not None:
        command.extend(["--batch-size", str(config["batch_size"])])
    if config.get("max_chapters") is not None:
        command.extend(["--max-chapters", str(config["max_chapters"])])


def _capture_long_config(args: argparse.Namespace) -> dict:
    return {
        "chapter_wise": getattr(args, "chapter_wise", False),
        "chapter_range": getattr(args, "chapter_range", None),
        "batch_size": getattr(args, "batch_size", None),
        "max_chapters": getattr(args, "max_chapters", None),
    }


def _author_config_fields(args: argparse.Namespace) -> dict:
    """作者感知选择链的 config 字段（--proposals/--author-mode/--kernel/--shadow/--drift-review）."""
    return {
        "proposals": getattr(args, "proposals", 1),
        "author_mode": getattr(args, "author_mode", "off"),
        "kernel": getattr(args, "kernel", "") or "",
        "shadow": getattr(args, "shadow", "off"),
        "drift_review": getattr(args, "drift_review", "off"),
    }


def _append_author_options(command: list[str], args: argparse.Namespace) -> None:
    """把作者感知选择链选项追加到 extend/compose 子命令（默认值不追加，零成本）."""
    proposals = getattr(args, "proposals", 1)
    if proposals > 1:
        command.extend(["--proposals", str(proposals)])
    if getattr(args, "author_mode", "off") == "on":
        command.extend(["--author-mode", "on"])
    if getattr(args, "kernel", ""):
        command.extend(["--kernel", args.kernel])
    if getattr(args, "shadow", "off") == "on":
        command.extend(["--shadow", "on"])
    if getattr(args, "drift_review", "off") == "on":
        command.extend(["--drift-review", "on"])


def _append_configured_author_options(command: list[str], config: dict) -> None:
    """resume 从 config 重建作者感知选择链选项（缺省零成本）."""
    proposals = config.get("proposals") or 1
    if proposals > 1:
        command.extend(["--proposals", str(proposals)])
    if config.get("author_mode") == "on":
        command.extend(["--author-mode", "on"])
    if config.get("kernel"):
        command.extend(["--kernel", config["kernel"]])
    if config.get("shadow") == "on":
        command.extend(["--shadow", "on"])
    if config.get("drift_review") == "on":
        command.extend(["--drift-review", "on"])


def _run_child(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    return completed.returncode


def _script_path(name: str) -> str:
    return str(PROJECT_ROOT / "src" / name)


def _run_audit(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "audit")
    _validate_long_options(args)
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "audit")
    _write_config(
        novel_dir,
        {
            "mode": "audit",
            "format": args.format,
            "outline_only": args.outline_only,
            **_capture_long_config(args),
        },
    )

    command = [
        sys.executable,
        _script_path("audit_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.format:
        command.extend(["--format", args.format])
    if args.outline_only:
        command.append("--outline-only")
    _append_long_options(command, args)
    return _run_child(command)


def _run_extend(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "extend")
    _validate_long_options(args)
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "extend")
    _write_config(
        novel_dir,
        {"mode": "extend", **_capture_long_config(args)}
        | ({"style": args.style} if getattr(args, "style", None) else {})
        | {"retrieval": getattr(args, "retrieval", "on")}
        | {"nsfw": getattr(args, "nsfw", "off")}
        | {"character_update": getattr(args, "character_update", "off")}
        | _author_config_fields(args),
    )

    command = [
        sys.executable,
        _script_path("extend_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    _append_long_options(command, args)
    if getattr(args, "style", None):
        command.extend(["--style", args.style])
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    command.extend(["--retrieval", getattr(args, "retrieval", "on")])
    command.extend(["--nsfw", getattr(args, "nsfw", "off")])
    command.extend(["--character-update", getattr(args, "character_update", "off")])
    _append_author_options(command, args)
    if getattr(args, "no_prose", False):
        command.append("--no-prose")
    return _run_child(command)


def _run_compose(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "compose")
    if args.workspec:
        source_workspec_path = Path(args.workspec).resolve()
        if not source_workspec_path.exists():
            raise FileNotFoundError(f"input file not found: {args.workspec}")
        source_workspec = WorkSpec.model_validate_json(_read_text(source_workspec_path))
    elif (novel_dir / "workspec.json").exists():
        source_workspec_path = novel_dir / "workspec.json"
        source_workspec = WorkSpec.model_validate_json(_read_text(source_workspec_path))
    else:
        source_workspec_path = None
        source_workspec = _default_compose_workspec()
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".workspec_hash",
        current_hash=model_content_hash(source_workspec),
        label="WorkSpec",
    ):
        return 1
    _write_mode(novel_dir, "compose")

    command = [sys.executable, _script_path("compose_short_form.py")]
    if source_workspec_path is not None and args.workspec:
        workspec_path = _copy_to_workspace(args.workspec, novel_dir / "workspec.json")
        command.append(str(workspec_path))
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": "workspec.json"}
            | ({"style": args.style} if getattr(args, "style", None) else {})
            | {"nsfw": getattr(args, "nsfw", "off")}
            | {"character_update": getattr(args, "character_update", "off")}
            | _author_config_fields(args),
        )
    elif source_workspec_path is not None:
        command.append(str(novel_dir / "workspec.json"))
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": "workspec.json"}
            | ({"style": args.style} if getattr(args, "style", None) else {})
            | {"retrieval": getattr(args, "retrieval", "on")}
            | {"nsfw": getattr(args, "nsfw", "off")}
            | {"character_update": getattr(args, "character_update", "off")}
            | _author_config_fields(args),
        )
    else:
        _write_config(
            novel_dir,
            {"mode": "compose", "workspec": None}
            | ({"style": args.style} if getattr(args, "style", None) else {})
            | {"retrieval": getattr(args, "retrieval", "on")}
            | {"nsfw": getattr(args, "nsfw", "off")}
            | {"character_update": getattr(args, "character_update", "off")}
            | _author_config_fields(args),
        )
    command.extend(["--output-dir", str(output_dir)])
    if getattr(args, "style", None):
        command.extend(["--style", args.style])
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    command.extend(["--retrieval", getattr(args, "retrieval", "on")])
    command.extend(["--nsfw", getattr(args, "nsfw", "off")])
    command.extend(["--character-update", getattr(args, "character_update", "off")])
    _append_author_options(command, args)
    if getattr(args, "no_prose", False):
        command.append("--no-prose")
    return _run_child(command)


def _run_style(args: argparse.Namespace) -> int:
    """从已有小说文本提炼写作风格档案（或引用风格库档案做 lint）."""
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "style")
    # --style-search：纯库检索（全局 manifest），无需输入文本 / hash / config
    if getattr(args, "style_search", None):
        command = [
            sys.executable,
            _script_path("style_short_form.py"),
            "--output-dir",
            str(output_dir),
            "--style-search",
            args.style_search,
        ]
        return _run_child(command)
    source_input = _input_source(args, novel_dir)
    # --style 引用模式不做提炼，跳过 hash 校验（输入仅供 lint 用）
    if not args.style and not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "style")
    _write_config(
        novel_dir,
        {
            "mode": "style",
            **({"name": args.name} if args.name else {}),
            **({"style": args.style} if args.style else {}),
        },
    )

    command = [
        sys.executable,
        _script_path("style_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.tone:
        command.extend(["--tone", args.tone])
    if args.genre:
        command.extend(["--genre", args.genre])
    if args.lint:
        command.append("--lint")
    if args.name:
        command.extend(["--name", args.name])
    if args.style:
        command.extend(["--style", args.style])
    if getattr(args, "force", False):
        command.append("--force")
    if getattr(args, "no_library", False):
        command.append("--no-library")
    if getattr(args, "temperament", None):
        command.extend(["--temperament", args.temperament])
    return _run_child(command)


def _run_compliance(args: argparse.Namespace) -> int:
    """内容合规模块：扫敏感词 + 平台政策（纯代码，无 LLM 阶段）."""
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "compliance")
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "compliance")
    _write_config(
        novel_dir,
        {
            "mode": "compliance",
            **({"platform": args.platform} if getattr(args, "platform", None) else {}),
            **({"sensitive": args.sensitive} if getattr(args, "sensitive", None) else {}),
            **({"nsfw": args.nsfw} if getattr(args, "nsfw", None) else {}),
            **({"lexicon": args.lexicon} if getattr(args, "lexicon", None) else {}),
        },
    )

    command = [
        sys.executable,
        _script_path("compliance_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if args.platform:
        command.extend(["--platform", args.platform])
    if args.sensitive:
        command.extend(["--sensitive", args.sensitive])
    if args.nsfw:
        command.extend(["--nsfw", args.nsfw])
    if args.lexicon:
        command.extend(["--lexicon", args.lexicon])
    return _run_child(command)


def _run_reader(args: argparse.Namespace) -> int:
    """读者体验审查：对章节正文做 7 维分级标注（LLM response-file 循环）.

    定位核心2（读者体验），与 compliance（纯代码）/ rubric（静态导出）不同：
    reader 需要 LLM 质性判断，走 style 式 [WAITING] 循环。
    产物 novels/<name>/output/reader_experience/reader_report.json（route=none 不阻断）。
    """
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "reader_experience")
    source_input = _input_source(args, novel_dir)
    if not _preflight_run_hash(
        output_dir=output_dir,
        hash_filename=".input_hash",
        current_hash=file_content_hash(source_input),
        label="input file",
    ):
        return 1
    input_path = _ensure_input(args, novel_dir)
    _write_mode(novel_dir, "reader")
    _write_config(novel_dir, {"mode": "reader"})

    command = [
        sys.executable,
        _script_path("reader_short_form.py"),
        str(input_path),
        "--output-dir",
        str(output_dir),
    ]
    if getattr(args, "style", None):
        command.extend(["--style", args.style])
    if getattr(args, "chapter_id", None):
        command.extend(["--chapter-id", args.chapter_id])
    # 读者预期台账源：优先显式 --expectations-from，否则自动探测该小说的
    # extend rebuild 产物（含 ForeshadowGraph）。可加 --no-expectations 关闭。
    if getattr(args, "no_expectations", False):
        return _run_child(command)
    expectations_from = getattr(args, "expectations_from", None)
    if not expectations_from:
        extend_package = novel_dir / "output" / "extend" / "extend_rebuild_package.json"
        if extend_package.exists():
            expectations_from = str(extend_package)
    if expectations_from:
        command.extend(["--expectations-from", expectations_from])
    return _run_child(command)


def _run_rubric(args: argparse.Namespace) -> int:
    """导出 WebNovelBench 8 维本地评测 rubric（纯代码，无输入文件）.

    rubric 是静态领域知识导出（无 input 文件、无 .input_hash），
    输出到 novels/<name>/output/rubric/rubric.json。
    """
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "rubric")
    _write_mode(novel_dir, "rubric")
    _write_config(novel_dir, {"mode": "rubric"})

    command = [
        sys.executable,
        _script_path("rubric_short_form.py"),
        "--output-dir",
        str(output_dir),
    ]
    return _run_child(command)


def _run_time(args: argparse.Namespace) -> int:
    """时间域模块：TimeBook 管理 + 时间审计（纯代码，无 LLM 阶段）.

    横向域：output/time 同时被 audit/extend/compose 消费；
    时间域产出 time_book.json / timeline_report.json。
    """
    novel_dir = _novel_dir(args.novel)
    output_dir = _output_dir(novel_dir, "time")
    _write_mode(novel_dir, "time")
    _write_config(novel_dir, {"mode": "time"})

    command = [
        sys.executable,
        _script_path("time_short_form.py"),
        "--output-dir",
        str(output_dir),
    ]
    if args.input:
        command.extend(["--input", str(_ensure_input(args, novel_dir))])
    if args.rebuild:
        command.append("--rebuild")
    if args.check:
        command.append("--check")
    return _run_child(command)


def _run_resume(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    config = _read_config(novel_dir)
    if mode is None:
        print(f"Error: no saved mode for novel: {args.novel}")
        return 1

    if mode == "audit":
        output_dir = _output_dir(novel_dir, "audit")
        _validate_configured_long_options(config)
        input_path = novel_dir / "input.txt"
        if not input_path.exists():
            print(f"Error: missing input file: {input_path}")
            return 1
        command = [
            sys.executable,
            _script_path("audit_short_form.py"),
            str(input_path),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("format"):
            command.extend(["--format", config["format"]])
        if config.get("outline_only"):
            command.append("--outline-only")
        _append_configured_long_options(command, config)
        return _run_child(command)
    if mode == "extend":
        output_dir = _output_dir(novel_dir, "extend")
        _validate_configured_long_options(config)
        input_path = novel_dir / "input.txt"
        if not input_path.exists():
            print(f"Error: missing input file: {input_path}")
            return 1
        command = [
            sys.executable,
            _script_path("extend_short_form.py"),
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--resume",
        ]
        _append_configured_long_options(command, config)
        if config.get("style"):
            command.extend(["--style", config["style"]])
        command.extend(["--retrieval", config.get("retrieval", "on")])
        command.extend(["--nsfw", config.get("nsfw", "off")])
        command.extend(["--character-update", config.get("character_update", "off")])
        _append_configured_author_options(command, config)
        return _run_child(command)
    if mode == "compose":
        output_dir = _output_dir(novel_dir, "compose")
        command = [
            sys.executable,
            _script_path("compose_short_form.py"),
            "--output-dir",
            str(output_dir),
            "--resume",
        ]
        if config.get("style"):
            command.extend(["--style", config["style"]])
        command.extend(["--retrieval", config.get("retrieval", "on")])
        command.extend(["--nsfw", config.get("nsfw", "off")])
        command.extend(["--character-update", config.get("character_update", "off")])
        _append_configured_author_options(command, config)
        return _run_child(command)
    if mode == "style":
        output_dir = _output_dir(novel_dir, "style")
        command = [
            sys.executable,
            _script_path("style_short_form.py"),
            str(novel_dir / "input.txt"),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("style"):
            command.extend(["--style", config["style"]])
        if config.get("name"):
            command.extend(["--name", config["name"]])
        return _run_child(command)
    if mode == "compliance":
        output_dir = _output_dir(novel_dir, "compliance")
        command = [
            sys.executable,
            _script_path("compliance_short_form.py"),
            str(novel_dir / "input.txt"),
            "--output-dir",
            str(output_dir),
        ]
        if config.get("platform"):
            command.extend(["--platform", config["platform"]])
        if config.get("sensitive"):
            command.extend(["--sensitive", config["sensitive"]])
        if config.get("nsfw"):
            command.extend(["--nsfw", config["nsfw"]])
        if config.get("lexicon"):
            command.extend(["--lexicon", config["lexicon"]])
        return _run_child(command)
    if mode == "rubric":
        output_dir = _output_dir(novel_dir, "rubric")
        command = [
            sys.executable,
            _script_path("rubric_short_form.py"),
            "--output-dir",
            str(output_dir),
        ]
        return _run_child(command)
    if mode == "time":
        output_dir = _output_dir(novel_dir, "time")
        command = [
            sys.executable,
            _script_path("time_short_form.py"),
            "--output-dir",
            str(output_dir),
        ]
        input_path = novel_dir / "input.txt"
        if input_path.exists():
            command.extend(["--input", str(input_path)])
        if _read_config(novel_dir).get("rebuild"):
            command.append("--rebuild")
        command.append("--check")
        return _run_child(command)

    print(f"Error: unknown saved mode for {args.novel}: {mode}")
    return 1


def _latest_date(novel_dir: Path) -> str:
    return _date_from_mtime(_latest_mtime(novel_dir))


def _read_route(path: Path) -> str:
    return f"route={_read_route_value(path)}"


def _gate_json_payload(
    verdict: dict[str, object],
    args: argparse.Namespace,
    mode: str,
) -> dict[str, object]:
    """Build the 13-field standard gate JSON payload."""
    return {
        "command": "gate",
        "novel": args.novel,
        "mode": mode,
        "ok": verdict["ok"],
        "schema_version": JSON_SCHEMA_VERSION,
        "review_route": verdict["review_route"],
        "next_workflow": verdict["next_workflow"],
        "violations": verdict["violations"],
        "handoff_path": str(verdict["handoff_path"]),
        "package_path": str(verdict["package_path"]),
        "package_present": verdict["package_present"],
        "blocking_pending_count": verdict["blocking_pending_count"],
        "blocking_pending_prompt_files": verdict["blocking_pending_prompt_files"],
    }


def _approval_gate_json_payload(
    verdict: dict[str, object],
    args: argparse.Namespace,
    mode: str,
) -> dict[str, object]:
    """Build the 17-field approval gate JSON payload.

    The 13 standard fields are a verbatim prefix (``_gate_json_payload``);
    the four approval fields are appended. Approve-override verdicts already
    carry approval_required/critical_issue_ids/approval_decision/approval_ok.
    """
    payload = _gate_json_payload(verdict, args, mode)
    payload["approval_required"] = verdict["approval_required"]
    payload["critical_issue_ids"] = verdict["critical_issue_ids"]
    payload["approval_decision"] = verdict["approval_decision"]
    payload["approval_ok"] = verdict["approval_ok"]
    return payload


def _run_gate(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")
    output_dir = _output_dir(novel_dir, mode)
    handoff_path = output_dir / ROUTE_HANDOFF_FILE
    if not handoff_path.exists():
        raise ValueError(f"missing route handoff: {handoff_path}")

    require_approval = bool(getattr(args, "require_approval", False))
    if require_approval:
        verdict = _approval_gate_verdict(
            mode=mode,
            output_dir=output_dir,
            handoff_path=handoff_path,
        )
    else:
        verdict = _route_gate_verdict(
            mode=mode,
            output_dir=output_dir,
            handoff_path=handoff_path,
        )

    if args.json:
        if require_approval:
            payload = _approval_gate_json_payload(verdict, args, mode)
            _validate_approval_gate_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if verdict["ok"] else 1
        else:
            payload = _gate_json_payload(verdict, args, mode)
            _validate_gate_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if verdict["ok"] else 1

    if not verdict["ok"]:
        print("Gate failed:")
        for violation in verdict["violations"]:
            print(f"  - {violation}")
        return 1

    approval_suffix = ""
    if require_approval:
        approval_suffix = f" approval={verdict['approval_decision']}"
    print(
        f"Gate PASS: mode={mode} route={verdict['review_route']} "
        f"next={verdict['next_workflow']}{approval_suffix}"
    )
    return 0


def _gate_metadata(mode: str, output_dir: Path, handoff_path: Path) -> dict[str, object]:
    verdict = _route_gate_verdict(
        mode=mode,
        output_dir=output_dir,
        handoff_path=handoff_path,
    )
    return {
        "gate_ok": verdict["ok"],
        "gate_violations": verdict["violations"],
        "gate_package_file": Path(verdict["package_path"]).name,
        "gate_package_path": str(verdict["package_path"]),
        "gate_package_present": verdict["package_present"],
        "gate_blocking_pending_count": verdict["blocking_pending_count"],
        "gate_blocking_pending_prompt_files": verdict[
            "blocking_pending_prompt_files"
        ],
    }


def _empty_status_metadata() -> dict[str, object]:
    metadata = {
        "route": None,
        "next_workflow": None,
        "gate_ok": None,
        "gate_violations": [],
        "gate_package_file": None,
        "gate_package_path": None,
        "gate_package_present": None,
        "gate_blocking_pending_count": None,
        "gate_blocking_pending_prompt_files": [],
        "pending_count": 0,
        "pending_prompt_file": None,
        "pending_response_file": None,
        "pending_prompt_path": None,
        "pending_response_path": None,
        "pending_prompt_hash": None,
        "pending_prompt_bytes": None,
        "pending_prompt_mtime": None,
        "pending_slot_id": None,
        **pending_automation_metadata(pending_count=0),
        "final_result_file": None,
        "final_result_path": None,
        "route_handoff_file": None,
        "route_handoff_path": None,
    }
    validate_pending_automation_metadata_in_payload(
        metadata,
        pending_count=0,
    )
    return metadata


def _status_for(novel_dir: Path) -> tuple[str, str, str, dict[str, object]]:
    mode = _read_mode(novel_dir) or "unknown"
    output_dir = _output_dir(novel_dir, mode)
    final = _final_route_path(mode, output_dir)
    handoff = _route_handoff_path(output_dir)
    metadata = _empty_status_metadata()
    if output_dir.exists():
        latest_final = _latest_route_artifact_mtime(mode, output_dir)
        slots = _waiting_slots(
            output_dir,
            newer_than=latest_final,
        )
        if slots:
            first_slot = slots[0]
            metadata.update(
                {
                    "pending_count": len(slots),
                    "pending_prompt_file": first_slot.prompt_path.name,
                    "pending_response_file": first_slot.response_path.name,
                    "pending_prompt_path": str(first_slot.prompt_path),
                    "pending_response_path": str(first_slot.response_path),
                    "pending_prompt_hash": first_slot.prompt_hash,
                    "pending_prompt_bytes": first_slot.prompt_bytes,
                    "pending_prompt_mtime": first_slot.prompt_mtime,
                    "pending_slot_id": first_slot.slot_id,
                    **pending_automation_metadata(pending_count=len(slots)),
                }
            )
            validate_pending_automation_metadata_in_payload(
                metadata,
                pending_count=len(slots),
            )
            return (
                mode,
                "waiting",
                f"[WAITING: {first_slot.response_path.name}]",
                metadata,
            )
    if handoff and not final:
        raise ValueError(
            f"route handoff exists without final result: {handoff[0]}"
        )
    if final:
        final_path, _ = final
        route, detail, next_workflow = _route_detail(final_path, handoff)
        metadata["route"] = route
        metadata["next_workflow"] = next_workflow
        metadata["final_result_file"] = final_path.name
        metadata["final_result_path"] = str(final_path)
        if handoff:
            handoff_path, _ = handoff
            metadata["route_handoff_file"] = handoff_path.name
            metadata["route_handoff_path"] = str(handoff_path)
            metadata.update(_gate_metadata(mode, output_dir, handoff_path))
        if mode in {"extend", "compose"} and route != "pass":
            status = "blocked" if route == "block" else "rewrite"
            return mode, status, detail, metadata
        return mode, "completed", detail, metadata
    return mode, "initialized", "-", metadata


def _time_status_detail(novel_dir: Path) -> str:
    """每部小说当前叙事时间状态（无 TimeBook → 未设定）.

    时间域为横向域，独立于 mode.txt；list 行用它展示时间线准星。
    """
    from src.workflow_action.timebook import load_time_book

    tb = load_time_book(_output_dir(novel_dir, "time"))
    if tb is None:
        return "未设定"
    latest = tb.latest_anchor()
    if latest is not None:
        bits = [b for b in (latest.chapter, latest.date, latest.lunar, latest.tod, latest.loc) if b]
        return " ".join(bits)
    if tb.initial is not None and not tb.initial.is_empty():
        bits = [b for b in (tb.initial.date, tb.initial.lunar, tb.initial.loc) if b]
        return "起点 " + " ".join(bits)
    return "存在"


def _run_list(args: argparse.Namespace) -> int:
    root = _novels_root()
    if not root.exists():
        if args.json:
            _validate_list_json_payload([])
            print("[]")
        return 0
    rows = []
    for novel_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        mode, status, detail, metadata = _status_for(novel_dir)
        latest_mtime = _latest_mtime(novel_dir)
        latest_date = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d")
        rows.append(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "command": "list",
                "name": novel_dir.name,
                "mode": mode,
                "status": status,
                "detail": detail,
                "latest_date": latest_date,
                "latest_mtime": latest_mtime,
                **metadata,
                "time_status": _time_status_detail(novel_dir),
            }
        )
    if args.json:
        _validate_list_json_payload(rows)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        print(
            f"{row['name']}\t{row['mode']}\t{row['status']}\t"
            f"{row['detail']}\t{row['latest_date']}"
        )
    return 0


def _effective_pending_newer_than(
    *,
    requested_newer_than: float | None,
    artifact_cutoff: float | None,
) -> float | None:
    if artifact_cutoff is None:
        return requested_newer_than
    if requested_newer_than is None:
        return artifact_cutoff
    return max(requested_newer_than, artifact_cutoff)


def _run_pending(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")

    output_dir = _output_dir(novel_dir, mode)
    boundary = ResponseFileBoundaryUnit()
    artifact_cutoff = _latest_route_artifact_mtime(mode, output_dir)
    effective_newer_than = _effective_pending_newer_than(
        requested_newer_than=args.newer_than,
        artifact_cutoff=artifact_cutoff,
    )
    if args.prompt_hash and not args.slot_id:
        raise ValueError("--prompt-hash requires --slot-id for pending verification")
    if args.slot_id:
        selection_method = "slot_id"
        slots = [
            boundary.require_pending_slot(
                output_dir,
                slot_id=args.slot_id,
                newer_than=effective_newer_than,
                expected_prompt_hash=args.prompt_hash,
            )
        ]
    else:
        selection_method = "all_pending"
        slots = boundary.discover_pending_slots(
            output_dir,
            newer_than=effective_newer_than,
        )
    automation_metadata = pending_automation_metadata(pending_count=len(slots))
    validate_pending_automation_metadata_in_payload(
        automation_metadata,
        pending_count=len(slots),
    )
    pending_entries = [
        {
            "prompt_file": slot.prompt_path.name,
            "response_file": slot.response_path.name,
            "prompt_path": str(slot.prompt_path),
            "response_path": str(slot.response_path),
            "prompt_mtime": slot.prompt_mtime,
            "prompt_hash": slot.prompt_hash,
            "prompt_bytes": slot.prompt_bytes,
            "slot_id": slot.slot_id,
        }
        for slot in slots
    ]
    if args.require_automation_ready and not automation_metadata["automation_ready"]:
        error = (
            "pending slot is not automation ready: "
            f"{automation_metadata['automation_ready_reason']}"
        )
        if args.json:
            payload = {
                "ok": False,
                "schema_version": JSON_SCHEMA_VERSION,
                "command": "pending",
                "novel": args.novel,
                "mode": mode,
                "output_dir": str(output_dir),
                "slot_id": args.slot_id,
                "selection_method": selection_method,
                "newer_than": args.newer_than,
                "effective_newer_than": effective_newer_than,
                "route_artifact_mtime": artifact_cutoff,
                "expected_prompt_hash": args.prompt_hash,
                "prompt_hash_verified": args.prompt_hash is not None,
                "pending_count": len(slots),
                **automation_metadata,
                "pending": pending_entries,
                "error_stage": "runtime",
                "error_type": "ValueError",
                "error": error,
            }
            _validate_pending_json_payload(payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        raise ValueError(error)
    if args.json:
        payload = {
            "ok": True,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": "pending",
            "novel": args.novel,
            "mode": mode,
            "output_dir": str(output_dir),
            "slot_id": args.slot_id,
            "selection_method": selection_method,
            "newer_than": args.newer_than,
            "effective_newer_than": effective_newer_than,
            "route_artifact_mtime": artifact_cutoff,
            "expected_prompt_hash": args.prompt_hash,
            "prompt_hash_verified": args.prompt_hash is not None,
            "pending_count": len(slots),
            **automation_metadata,
            "pending": pending_entries,
        }
        _validate_pending_json_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not slots:
        print(f"No pending response slots: mode={mode}")
        return 0

    for slot in slots:
        print(f"{mode}\t{slot.prompt_path.name}\t{slot.response_path.name}")
    return 0


def _pending_slot_for_prompt(output_dir: Path, prompt_name: str):
    boundary = ResponseFileBoundaryUnit()
    prompt_path = output_dir / _prompt_filename(prompt_name)
    response_path = boundary.expected_response_path(prompt_path)
    boundary.verify_response_slot(prompt_path=prompt_path, response_path=response_path)
    return prompt_path, response_path


def _verify_prompt_after_cutoff(
    prompt_path: Path,
    cutoff: float | None,
) -> None:
    if cutoff is None:
        return
    prompt_mtime = Path(prompt_path).stat().st_mtime
    if prompt_mtime <= cutoff:
        raise ValueError(
            f"pending prompt is older than current route artifact: {prompt_path}"
        )


def _pending_slot_for_slot_id(
    output_dir: Path,
    slot_id: str,
    *,
    newer_than: float | None = None,
):
    boundary = ResponseFileBoundaryUnit()
    if newer_than is None:
        slot = boundary.require_pending_slot(output_dir, slot_id=slot_id)
    else:
        slot = boundary.require_pending_slot(
            output_dir,
            slot_id=slot_id,
            newer_than=newer_than,
        )
    return slot.prompt_path, slot.response_path


def _run_respond(args: argparse.Namespace) -> int:
    novel_dir = _novel_dir(args.novel)
    mode = _read_mode(novel_dir)
    if mode is None:
        raise ValueError(f"missing saved mode for {args.novel}")

    response_source = Path(args.response_file).resolve()
    if not response_source.exists() or not response_source.is_file():
        raise FileNotFoundError(f"response source file not found: {args.response_file}")

    output_dir = _output_dir(novel_dir, mode)
    boundary = ResponseFileBoundaryUnit()
    artifact_cutoff = _latest_route_artifact_mtime(mode, output_dir)
    effective_newer_than = _effective_pending_newer_than(
        requested_newer_than=None,
        artifact_cutoff=artifact_cutoff,
    )
    slot_id = getattr(args, "slot_id", None)
    if args.prompt and slot_id:
        raise ValueError("--prompt and --slot-id cannot be used together")
    if slot_id:
        selection_method = "slot_id"
        prompt_path, response_path = _pending_slot_for_slot_id(
            output_dir,
            slot_id,
            newer_than=effective_newer_than,
        )
    elif args.prompt:
        selection_method = "prompt_file"
        prompt_path, response_path = _pending_slot_for_prompt(output_dir, args.prompt)
        _verify_prompt_after_cutoff(prompt_path, effective_newer_than)
    else:
        selection_method = "single_pending"
        if effective_newer_than is None:
            slot = boundary.require_single_pending_slot(output_dir)
        else:
            slot = boundary.require_single_pending_slot(
                output_dir,
                newer_than=effective_newer_than,
            )
        prompt_path = slot.prompt_path
        response_path = slot.response_path

    if _is_same_existing_file(response_source, prompt_path):
        raise ValueError("response source file must not be the staged prompt file")
    if _is_same_existing_file(response_source, response_path):
        raise ValueError("response source file must not be the staged response file")

    prompt_hash = boundary.verify_prompt_hash(prompt_path, args.prompt_hash)
    response_text, response_source_hash, response_source_bytes = _read_text_with_hash(
        response_source
    )
    boundary.materialize_response(
        prompt_path=prompt_path,
        response_path=response_path,
        response_text=response_text,
        expected_prompt_hash=prompt_hash,
    )
    prompt_evidence = file_content_evidence(prompt_path)
    if prompt_evidence.content_hash != prompt_hash:
        raise ValueError(
            f"prompt hash mismatch for {prompt_path}: "
            f"expected {prompt_hash}, actual {prompt_evidence.content_hash}"
        )
    response_bytes = response_text.encode("utf-8")
    expected_response_hash = hashlib.md5(response_bytes).hexdigest()
    response_hash = file_content_hash(response_path)
    if response_hash != expected_response_hash:
        raise ValueError(
            f"staged response hash mismatch for {response_path}: "
            f"expected {expected_response_hash}, actual {response_hash}"
        )
    if args.json:
        payload = {
            "ok": True,
            "schema_version": JSON_SCHEMA_VERSION,
            "command": "respond",
            "novel": args.novel,
            "mode": mode,
            "prompt_file": prompt_path.name,
            "response_file": response_path.name,
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
            "response_source": str(response_source),
            **response_materialization_metadata(),
            "selection_method": selection_method,
            "route_artifact_mtime": artifact_cutoff,
            "effective_newer_than": effective_newer_than,
            "expected_prompt_hash": args.prompt_hash,
            "prompt_hash_verified": args.prompt_hash is not None,
            "prompt_hash": prompt_hash,
            "prompt_bytes": prompt_evidence.byte_count,
            "slot_id": staged_slot_id(prompt_path),
            "response_source_hash": response_source_hash,
            "response_source_bytes": response_source_bytes,
            "response_hash": response_hash,
            "response_bytes": len(response_bytes),
            "response_chars": len(response_text),
        }
        _validate_respond_json_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Response saved: mode={mode} prompt={prompt_path.name} response={response_path.name}")
    return 0


def _add_input_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", help="原始文本路径；会复制到 novels/<小说名>/input.txt")


def _add_long_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chapter-wise", action="store_true", help="强制启用章节级处理")
    parser.add_argument("--range", dest="chapter_range", metavar="START-END", help="处理指定章节范围")
    parser.add_argument("--batch-size", type=int, help="每批处理章节数")
    parser.add_argument("--max-chapters", type=int, help="无 --range 时的最大允许章节数")


def _add_author_arguments(parser: argparse.ArgumentParser) -> None:
    """extend / compose 共用的作者感知选择链参数（全部默认零成本）."""
    parser.add_argument(
        "--proposals",
        type=int,
        default=1,
        metavar="N",
        help="Continue 多候选生成数（默认 1 零成本；N>=2 启用多候选选择链）",
    )
    parser.add_argument(
        "--author-mode",
        choices=["on", "off"],
        default="off",
        help="生产选择是否作者感知（默认 off 基线；on=Canary 6D 用 AuthorKernel 选择）",
    )
    parser.add_argument(
        "--kernel",
        metavar="PATH",
        help="AuthorKernel JSON 路径（默认读工作区 author_kernel.json）",
    )
    parser.add_argument(
        "--shadow",
        choices=["on", "off"],
        default="off",
        help="影子选择开关（默认 off；on=6C 作者感知影子结果不进正文）",
    )
    parser.add_argument(
        "--drift-review",
        choices=["on", "off"],
        default="off",
        help="作者漂移审查开关（默认 off；on=6E active_break 记 KernelChallenge）",
    )


def build_parser(*, emit_json_errors: bool = False) -> argparse.ArgumentParser:
    parser = NovelArgumentParser(
        description="统一小说工作流入口",
        emit_json_errors=emit_json_errors,
    )
    parser_factory = lambda *args, **kwargs: NovelArgumentParser(
        *args,
        emit_json_errors=emit_json_errors,
        **kwargs,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=parser_factory,
    )

    audit = subparsers.add_parser("audit", help="审核已有小说")
    audit.add_argument("novel", help="小说名")
    _add_input_argument(audit)
    _add_long_arguments(audit)
    audit.add_argument("--format", choices=["json", "markdown"], default="json", help="审核报告格式")
    audit.add_argument("--outline-only", action="store_true", help="只生成结构概览")
    audit.set_defaults(func=_run_audit)

    extend = subparsers.add_parser("extend", help="续写已有小说")
    extend.add_argument("novel", help="小说名")
    _add_input_argument(extend)
    _add_long_arguments(extend)
    extend.add_argument("--style", help="引用风格库中的已有档案 <name>，注入续写 prompt")
    extend.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；无风格档案时注入气质桶指导",
    )
    extend.add_argument(
        "--retrieval",
        choices=["on", "off"],
        default="on",
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
    )
    extend.add_argument(
        "--nsfw",
        choices=["on", "off"],
        default="off",
        help="成人向（NSFW）开关（默认 off 正常向：注入禁成人内容分级；on：允许成人向内容）",
    )
    extend.add_argument(
        "--character-update",
        choices=["on", "off"],
        default="off",
        help="角色变更提案开关（默认 off 零成本；on：Continue 后新增角色更新阶段）",
    )
    _add_author_arguments(extend)
    extend.add_argument(
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构）",
    )
    extend.set_defaults(func=_run_extend)

    compose = subparsers.add_parser("compose", help="从 WorkSpec 创作")
    compose.add_argument("novel", help="小说名")
    compose.add_argument("--workspec", help="WorkSpec JSON 文件路径")
    compose.add_argument("--style", help="引用风格库中的已有档案 <name>，注入续写 prompt")
    compose.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；CLI 优先，缺省回落到 workspec.temperament",
    )
    compose.add_argument(
        "--retrieval",
        choices=["on", "off"],
        default="on",
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
    )
    compose.add_argument(
        "--nsfw",
        choices=["on", "off"],
        default="off",
        help="成人向（NSFW）开关（默认 off 正常向：注入禁成人内容分级；on：允许成人向内容）",
    )
    compose.add_argument(
        "--character-update",
        choices=["on", "off"],
        default="off",
        help="角色变更提案开关（默认 off 零成本；on：Continue 后新增角色更新阶段）",
    )
    _add_author_arguments(compose)
    compose.add_argument(
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构）",
    )
    compose.set_defaults(func=_run_compose)

    style = subparsers.add_parser("style", help="从已有小说文本提炼写作风格档案")
    style.add_argument("novel", help="小说名")
    _add_input_argument(style)
    style.add_argument("--tone", help="调性提示词（如 克制）")
    style.add_argument("--genre", help="类型提示词（如 仙侠）")
    style.add_argument("--lint", action="store_true", help="对全文做 AI 味 lint")
    style.add_argument("--name", help="另存到风格库 style_library/<name>.json（可跨小说复用）")
    style.add_argument("--style", help="引用风格库中的已有档案 <name>，跳过提炼")
    style.add_argument(
        "--force",
        action="store_true",
        help="入库时忽略相似度去重提示，强制新建档案",
    )
    style.add_argument(
        "--no-library",
        action="store_true",
        help="提炼结果不写入风格库（跳过自动入库）",
    )
    style.add_argument(
        "--temperament",
        help="叙事气质（散文型/戏剧型/信息型/氛围型），透传给风格提炼作为先验",
    )
    style.add_argument(
        "--style-search",
        metavar="QUERY",
        help="在风格库 manifest 上检索候选 id（支持 '要素:手法' 如 人物:衬托），列出后退出",
    )
    style.set_defaults(func=_run_style)

    compliance = subparsers.add_parser("compliance", help="内容合规模块：扫敏感词 + 平台政策")
    compliance.add_argument("novel", help="小说名")
    _add_input_argument(compliance)
    compliance.add_argument("--platform", default="通用", help="目标平台（默认 通用）")
    compliance.add_argument(
        "--sensitive",
        default="on",
        choices=["on", "off"],
        help="敏感词扫描开关（默认 on；off 时跳过词库扫描，平台政策检查仍跑）",
    )
    compliance.add_argument(
        "--nsfw",
        default="off",
        choices=["on", "off"],
        help="成人向（NSFW）开关（默认 off 正常向：扫描涉黄分类；on：跳过涉黄分类，其余分类仍扫）",
    )
    compliance.add_argument("--lexicon", help="自定义词库 JSON 文件路径（与内置词库合并）")
    compliance.set_defaults(func=_run_compliance)

    reader_cmd = subparsers.add_parser(
        "reader", help="读者体验审查：对章节正文做 7 维分级标注（好不看好）"
    )
    reader_cmd.add_argument("novel", help="小说名")
    _add_input_argument(reader_cmd)
    reader_cmd.add_argument("--style", help="引用风格库中的已有档案 <name>")
    reader_cmd.add_argument("--chapter-id", help="章节标识（默认取输入文件名的 stem）")
    reader_cmd.add_argument(
        "--expectations-from",
        help="ForeshadowGraph JSON 路径（默认自动探测该小说 extend 产物）",
    )
    reader_cmd.add_argument(
        "--no-expectations",
        action="store_true",
        help="跳过读者预期台账生成",
    )
    reader_cmd.set_defaults(func=_run_reader)

    rubric = subparsers.add_parser("rubric", help="导出 WebNovelBench 8 维本地评测 rubric (离线)")
    rubric.add_argument("novel", help="小说名（rubric 为全局知识，novel 仅作容器）")
    rubric.set_defaults(func=_run_rubric)

    time_cmd = subparsers.add_parser("time", help="时间域模块：TimeBook 管理 + 时间审计")
    time_cmd.add_argument("novel", help="小说名")
    _add_input_argument(time_cmd)
    time_cmd.add_argument("--rebuild", action="store_true", help="从正文提取锚点并校准 TimeBook")
    time_cmd.add_argument("--check", action="store_true", help="运行时间审计，产出 timeline_report.json")
    time_cmd.add_argument("--status", action="store_true", help="打印 TimeBook 状态（默认动作）")
    time_cmd.set_defaults(func=_run_time)

    resume = subparsers.add_parser("resume", help="按上次模式断点续跑")
    resume.add_argument("novel", help="小说名")
    resume.set_defaults(func=_run_resume)

    list_cmd = subparsers.add_parser("list", help="查看所有小说任务")
    list_cmd.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    list_cmd.set_defaults(func=_run_list)

    pending = subparsers.add_parser("pending", help="list pending response slots")
    pending.add_argument("novel", help="novel name")
    pending.add_argument("--slot-id", help="select one pending staged slot id")
    pending.add_argument("--newer-than", type=float, help="only list prompts newer than this timestamp")
    pending.add_argument("--prompt-hash", help="expected pending prompt content hash")
    pending.add_argument("--require-automation-ready", action="store_true", help="fail unless exactly one staged slot is ready for automation preflight")
    pending.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    pending.set_defaults(func=_run_pending)

    respond = subparsers.add_parser("respond", help="materialize a staged response file")
    respond.add_argument("novel", help="novel name")
    respond.add_argument("--response-file", required=True, help="raw response text file")
    respond.add_argument("--prompt", help="pending prompt filename when multiple slots exist")
    respond.add_argument("--slot-id", help="pending staged slot id when multiple slots exist")
    respond.add_argument("--prompt-hash", help="expected pending prompt content hash")
    respond.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    respond.set_defaults(func=_run_respond)

    gate = subparsers.add_parser("gate", help="verify route handoff gate")
    gate.add_argument("novel", help="novel name")
    gate.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    gate.add_argument(
        "--require-approval",
        action="store_true",
        help="fail unless all open critical review issues are operator-approved "
        "(approval_decision.json)",
    )
    gate.set_defaults(func=_run_gate)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(emit_json_errors="--json" in raw_argv)
    args = parser.parse_args(raw_argv)
    try:
        return args.func(args)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        if getattr(args, "json", False):
            payload = _json_error_payload(
                error_stage="runtime",
                error_type=type(exc).__name__,
                error=str(exc),
                command=getattr(args, "command", None),
                novel=getattr(args, "novel", None),
                include_runtime_context=True,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
