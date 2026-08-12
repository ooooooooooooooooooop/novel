"""ReaderResponses — 多读者/多评审原始响应逐份留存（design §10 / T7.3）.

`responses/<reader_id>.json` 逐份保存，**禁止覆盖**：同 reader_id 已存在记录时，
除非显式 force 否则拒绝写（防误覆盖原始评审响应）。每份记录 prompt hash、模型、
版本、采样、运行 ID 和正文包 hash，使响应可追溯。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.object_state.readerresponse import ReaderResponseRecord


class ReaderResponseAlreadyExists(ValueError):
    """同 reader_id 响应已存在，拒绝覆盖."""


def responses_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "responses"


def store_reader_response(
    run_dir: Path,
    record: ReaderResponseRecord,
    *,
    force: bool = False,
) -> Path:
    """把读者/评审原始响应写入 run_dir/responses/<reader_id>.json.

    已存在且非 force → ReaderResponseAlreadyExists（不静默覆盖）。落盘只写元数据
    + 原始响应，不写来源小说名/正文之外的隐私内容（response 本身是评审原始输出）。
    """
    target = responses_dir(run_dir) / f"{record.reader_id}.json"
    if target.exists() and not force:
        raise ReaderResponseAlreadyExists(
            f"reader response already exists (refusing to overwrite): {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_reader_response(run_dir: Path, reader_id: str) -> ReaderResponseRecord | None:
    """载入单份响应；缺失返回 None."""
    target = responses_dir(run_dir) / f"{reader_id}.json"
    if not target.is_file():
        return None
    return ReaderResponseRecord.model_validate_json(target.read_text(encoding="utf-8"))
