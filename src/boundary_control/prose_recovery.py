"""ProseRecovery — Phase 5 三条现有内容的可恢复备份与移出（Q1）.

规格 45 §6 / 交接 46 §5：旧正文**先哈希 + 可恢复备份，再移出活动 chapters/**，
不原地修改。恢复前必须保证：任一旧章都可在哈希校验后还原，绝不静默丢弃。

本模块做三件事：
1. `hash_chapters(chapters_dir)`：给活动 chapters/ 全部旧正文计算 sha256；
2. `backup_and_archive_chapters(...)`：把旧正文**移动**到备份目录，写
   `recovery_manifest.json`（schema / 时间 / 源目录 / 每章 sha256 / 备份目录）；
3. `restore_chapters(...)`：按 manifest 从备份还原到活动 chapters/（逐章校验
   哈希，防错配/损坏）。

零成本契约：不调用 LLM；不改任何正文字节（只移动文件）；manifest 存
`novels/<名>/output/recovery/`（gitignore，真实正文不入库）。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.object_state.run_manifest import sha256_file

RECOVERY_MANIFEST_FILENAME = "recovery_manifest.json"


def _chapter_num(path: Path) -> int:
    try:
        return int(path.stem[len("chapter_"):])
    except (ValueError, IndexError):
        return 1 << 30


def hash_chapters(chapters_dir: Path) -> dict[str, str]:
    """计算活动 chapters/ 内全部 chapter_*.txt 的 sha256（{文件名: hash}）."""
    if not chapters_dir.exists():
        return {}
    files = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    return {p.name: sha256_file(p) for p in files}


@dataclass
class RecoveryResult:
    """一次备份/恢复的结果."""

    ok: bool
    manifest_path: Optional[Path] = None
    moved: int = 0
    restored: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def backup_and_archive_chapters(
    novel_dir: Path,
    *,
    backup_dir: Optional[Path] = None,
) -> RecoveryResult:
    """把活动 chapters/ 的旧正文移动到备份目录，并写 recovery manifest.

    Args:
        novel_dir: 小说工作区（含 chapters/ 与 output/）。
        backup_dir: 备份目录；缺省 `novels/<名>/output/recovery/chapters_backup_<seq>`。

    规则：
    - 每章移动到备份目录，不原地修改（文件内容不变，只是换位置）；
    - manifest 记录每章 sha256 与源/备份路径，供 `restore_chapters` 还原；
    - 活动 chapters/ 清空后保留（下一轮恢复从这里重新生成）。
    """
    chapters_dir = novel_dir / "chapters"
    if not chapters_dir.exists():
        return RecoveryResult(ok=False, errors=["chapters dir missing"])

    files = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    if not files:
        return RecoveryResult(ok=False, errors=["no chapters to archive"])

    # 确定备份目录：<seq> 递增，避免覆盖历史备份
    output_dir = novel_dir / "output"
    recovery_dir = output_dir / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    if backup_dir is None:
        seq = 1
        while (recovery_dir / f"chapters_backup_{seq}").exists():
            seq += 1
        backup_dir = recovery_dir / f"chapters_backup_{seq}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    from datetime import datetime, timezone

    manifest: dict = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(chapters_dir),
        "backup_dir": str(backup_dir),
        "chapters": {},
        "backup_id": uuid.uuid4().hex[:8],
    }
    errors: list[str] = []
    for p in files:
        dst = backup_dir / p.name
        try:
            sha = sha256_file(p)
            p.rename(dst)
            manifest["chapters"][p.name] = {
                "sha256": sha,
                "backup_path": str(dst),
            }
        except OSError as exc:
            errors.append(f"{p.name}: {exc}")

    manifest_path = recovery_dir / RECOVERY_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return RecoveryResult(
        ok=not errors,
        manifest_path=manifest_path,
        moved=len(manifest["chapters"]),
        errors=errors,
    )


def restore_chapters(
    novel_dir: Path,
    *,
    manifest_path: Optional[Path] = None,
) -> RecoveryResult:
    """按 recovery manifest 从备份还原旧正文到活动 chapters/（逐章校验哈希）.

    - 目标文件已存在且哈希匹配 → 跳过（幂等）；
    - 目标文件已存在但哈希不匹配 → 不覆盖（记录错误，防损坏）；
    - 备份缺失 → 记录错误。
    """
    chapters_dir = novel_dir / "chapters"
    recovery_dir = novel_dir / "output" / "recovery"
    if manifest_path is None:
        manifest_path = recovery_dir / RECOVERY_MANIFEST_FILENAME
    if not manifest_path.exists():
        return RecoveryResult(ok=False, errors=["recovery manifest missing"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapters_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    restored = 0
    for name, entry in manifest.get("chapters", {}).items():
        backup_path = Path(entry["backup_path"])
        target = chapters_dir / name
        if not backup_path.exists():
            errors.append(f"{name}: backup missing {backup_path}")
            continue
        sha = sha256_file(backup_path)
        if sha != entry["sha256"]:
            errors.append(f"{name}: backup hash mismatch (corrupt backup)")
            continue
        if target.exists():
            if sha256_file(target) == sha:
                restored += 1  # 已还原，幂等跳过
                continue
            errors.append(f"{name}: target exists with different content (refuse overwrite)")
            continue
        try:
            # 复制而非移动：备份目录保留为安全网（可反复还原/复核）
            target.write_bytes(backup_path.read_bytes())
            restored += 1
        except OSError as exc:
            errors.append(f"{name}: {exc}")

    return RecoveryResult(
        ok=not errors,
        manifest_path=manifest_path,
        restored=restored,
        errors=errors,
    )
