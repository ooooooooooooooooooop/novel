"""ChoiceLedger — 选择台账（作者性第二工作包 §11-13，零 LLM）.

由 Selector 落盘（禁止 4：必须保存被拒候选）；hindsight/consequence 由后续
阶段补写（§12：不能只记当时理由）。关联到当前生效的 style 档案 id，给
「这个作者」攒选择证据。

Level 3 Choice Memory（§28）：过去做过什么创作选择 → ChoiceLedger。
检索（§30 Value-Mediated Retrieval）：先推断决策触及哪些 Value Conflict →
再检索相关 Choice History；不做语义相似度 top-k。

隐私：含作品语境，sidecar 存 novels/<名>/output/<mode>/choice_ledger.json
（gitignored），不入风格库。
"""

import json
from pathlib import Path
from typing import Optional

from src.object_state.choicerecord import ChoiceLedgerEntry, ChoiceRecord, HindsightStatus

LEDGER_FILE = "choice_ledger.json"
LEDGER_SCHEMA_VERSION = 1


def _ledger_path(output_dir: Path) -> Path:
    return Path(output_dir) / LEDGER_FILE


def load_choice_ledger(output_dir: Path) -> ChoiceLedgerEntry:
    """读台账；缺失返回空骨架（主流程 no-op，仿 TimeBook 契约）."""
    path = _ledger_path(output_dir)
    if not path.exists():
        return ChoiceLedgerEntry()
    try:
        return ChoiceLedgerEntry.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        # 损坏的台账应暴露而非静默吞（stale/corrupt 文件契约），但调用方
        # 需要能区分「无台账」与「坏台账」，这里抛出让调用方决定。
        raise


def _empty_ledger() -> ChoiceLedgerEntry:
    return ChoiceLedgerEntry(schema_version=LEDGER_SCHEMA_VERSION)


def append_choice_record(output_dir: Path, record: ChoiceRecord) -> Path:
    """追加一条选择记录，返回台账路径."""
    ledger = load_choice_ledger(output_dir)
    existing_ids = {c.decision_id for c in ledger.choices}
    if record.decision_id in existing_ids:
        raise ValueError(f"duplicate decision_id in choice ledger: {record.decision_id}")
    ledger.choices.append(record)
    path = _ledger_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return path


def record_hindsight(
    output_dir: Path,
    decision_id: str,
    hindsight: HindsightStatus,
    note: Optional[str] = None,
) -> bool:
    """几章后补写回看（§12）——不能只记当时理由.

    Returns: True 找到并更新；False 无此 decision_id（不报错，容许滞后补写）.
    """
    ledger = load_choice_ledger(output_dir)
    updated = False
    for choice in ledger.choices:
        if choice.decision_id == decision_id:
            choice.hindsight = hindsight
            choice.hindsight_note = note
            updated = True
            break
    if updated:
        path = _ledger_path(output_dir)
        path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return updated


def record_consequence(output_dir: Path, decision_id: str, consequence: str) -> bool:
    """几章后补写后果（§11 consequence——不能只记当时理由）."""
    ledger = load_choice_ledger(output_dir)
    updated = False
    for choice in ledger.choices:
        if choice.decision_id == decision_id:
            choice.consequence = consequence
            updated = True
            break
    if updated:
        path = _ledger_path(output_dir)
        path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return updated


def choice_records(ledger: ChoiceLedgerEntry) -> list[ChoiceRecord]:
    """平铺全部选择记录（按写入顺序）."""
    return list(ledger.choices)


def get_choice(ledger: ChoiceLedgerEntry, decision_id: str) -> Optional[ChoiceRecord]:
    for choice in ledger.choices:
        if choice.decision_id == decision_id:
            return choice
    return None
