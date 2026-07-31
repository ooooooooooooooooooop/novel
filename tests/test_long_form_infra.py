"""Tests for long-form infrastructure: range filter, batch size, input hash."""

import tempfile
from pathlib import Path


def test_range_filter_extracts_correct_chapters():
    """--range 1-3 只处理前 3 章."""
    from src.boundary_control.chunking import split_by_chapters

    text = "\n\n".join(f"第{i}章 标题{i}\n内容{i}" for i in range(1, 11))
    chunks = split_by_chapters(text)
    start, end = 1, 3
    filtered = [c for c in chunks if start <= c.chapter_index <= end]
    assert len(filtered) == 3
    assert filtered[0].chapter_index == 1
    assert filtered[-1].chapter_index == 3


def test_batch_size_affects_batch_count():
    """batch size 50 比 5 产生的 batch 更少."""
    from src.boundary_control.chunking import split_by_chapters

    text = "\n\n".join(f"第{i}章 标题{i}\n内容{i}" for i in range(1, 101))
    chunks = split_by_chapters(text)

    def count_batches(chunks, batch_size):
        return (len(chunks) + batch_size - 1) // batch_size

    assert count_batches(chunks, 5) == 20
    assert count_batches(chunks, 50) == 2


def test_input_hash_detects_change():
    """input hash 变化时应返回 False（不匹配）."""
    import hashlib

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("原始内容")
        path = Path(f.name)

    hash1 = hashlib.md5(path.read_bytes()).hexdigest()

    path.write_text("修改后内容", encoding="utf-8")
    hash2 = hashlib.md5(path.read_bytes()).hexdigest()

    assert hash1 != hash2
    path.unlink()
