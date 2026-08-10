"""Q1 Phase 5 — ProseRecovery 可恢复备份/移出单测.

验证三条现有内容的恢复纪律：
- 旧正文先哈希 + 可恢复备份，再移出活动 chapters/，不原地修改；
- restore 按 manifest 逐章校验哈希还原（防错配/损坏/静默丢弃）。
"""

import json
from pathlib import Path

from src.boundary_control.prose_recovery import (
    backup_and_archive_chapters,
    hash_chapters,
    restore_chapters,
)
from src.object_state.run_manifest import sha256_text


def _make_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "novel"
    chapters = novel / "chapters"
    chapters.mkdir(parents=True)
    (chapters / "chapter_1.txt").write_text("第一章正文。", encoding="utf-8")
    (chapters / "chapter_2.txt").write_text("第二章正文。", encoding="utf-8")
    return novel


def test_hash_chapters(tmp_path):
    novel = _make_novel(tmp_path)
    hashes = hash_chapters(novel / "chapters")
    assert set(hashes) == {"chapter_1.txt", "chapter_2.txt"}
    assert hashes["chapter_1.txt"] == sha256_text("第一章正文。")


def test_backup_moves_and_records_hashes(tmp_path):
    novel = _make_novel(tmp_path)
    chapters = novel / "chapters"
    result = backup_and_archive_chapters(novel)
    assert result.ok, result.errors
    assert result.moved == 2
    assert not list(chapters.glob("chapter_*.txt")), "活动 chapters/ 应已移出清空"

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["chapters"]) == {"chapter_1.txt", "chapter_2.txt"}
    # 备份目录内容与哈希一致
    for name, entry in manifest["chapters"].items():
        bp = Path(entry["backup_path"])
        assert bp.exists()
        from src.object_state.run_manifest import sha256_file

        assert sha256_file(bp) == entry["sha256"]


def test_backup_does_not_modify_content(tmp_path):
    novel = _make_novel(tmp_path)
    original = (novel / "chapters" / "chapter_1.txt").read_bytes()
    backup_and_archive_chapters(novel)
    # 备份的文件字节与原文一致（只移动，不修改）
    backup = next((novel / "output" / "recovery" / "chapters_backup_1").glob("chapter_1.txt"))
    assert backup.read_bytes() == original


def test_restore_round_trip(tmp_path):
    novel = _make_novel(tmp_path)
    backup_and_archive_chapters(novel)
    restored = restore_chapters(novel)
    assert restored.ok, restored.errors
    assert restored.restored == 2
    chapters = novel / "chapters"
    assert (chapters / "chapter_1.txt").read_text(encoding="utf-8") == "第一章正文。"
    assert (chapters / "chapter_2.txt").read_text(encoding="utf-8") == "第二章正文。"


def test_restore_is_idempotent(tmp_path):
    novel = _make_novel(tmp_path)
    backup_and_archive_chapters(novel)
    restore_chapters(novel)
    # 再 restore 一次：目标已存在且哈希匹配 → 幂等跳过，无错误
    second = restore_chapters(novel)
    assert second.ok, second.errors
    assert second.restored == 2


def test_restore_refuses_corrupt_backup(tmp_path):
    novel = _make_novel(tmp_path)
    backup_and_archive_chapters(novel)
    # 篡改一个备份文件 → restore 报哈希不符，不还原
    backup_dir = novel / "output" / "recovery" / "chapters_backup_1"
    target = next(backup_dir.glob("chapter_1.txt"))
    target.write_text("被篡改的内容", encoding="utf-8")
    result = restore_chapters(novel)
    assert not result.ok
    assert any("hash mismatch" in e for e in result.errors)
    assert not (novel / "chapters" / "chapter_1.txt").exists(), "哈希不符不得还原"


def test_restore_refuses_overwrite_different_content(tmp_path):
    novel = _make_novel(tmp_path)
    backup_and_archive_chapters(novel)
    # 活动目录里放了不同内容的同名文件 → 拒绝覆盖
    (novel / "chapters" / "chapter_1.txt").write_text("新生成的不同内容", encoding="utf-8")
    result = restore_chapters(novel)
    assert not result.ok
    assert any("refuse overwrite" in e for e in result.errors)
    # 未篡改的 chapter_2 仍正常还原
    assert (novel / "chapters" / "chapter_2.txt").read_text(encoding="utf-8") == "第二章正文。"
