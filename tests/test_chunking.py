"""测试章节切分."""

from src.boundary_control.chunking import (
    ChapterChunk,
    get_total_stats,
    split_by_chapters,
)


def test_split_by_chapters_arabic():
    text = "\n第1章 开场\n这是第一章内容。\n\n第2章 发展\n这是第二章内容，更多文字。"
    chunks = split_by_chapters(text)

    assert len(chunks) == 2
    assert chunks[0].chapter_index == 1
    assert chunks[0].chapter_title == "开场"
    assert "第一章内容" in chunks[0].text
    assert chunks[1].chapter_index == 2
    assert chunks[1].chapter_title == "发展"
    assert "第二章内容" in chunks[1].text


def test_split_by_chapters_chinese():
    text = "第十一章 终章\n这是第十一章。\n第十二章 尾声\n这是第十二章。"
    chunks = split_by_chapters(text)

    assert len(chunks) == 2
    assert chunks[0].chapter_index == 11
    assert chunks[0].chapter_title == "终章"
    assert chunks[1].chapter_index == 12


def test_no_chapters_returns_single_chunk():
    text = "没有章节标题的纯文本。"
    chunks = split_by_chapters(text)

    assert len(chunks) == 1
    assert chunks[0].chapter_index == 1
    assert chunks[0].chapter_title == "全文"


def test_stats():
    chunks = [
        ChapterChunk(1, "A", "a" * 100),
        ChapterChunk(2, "B", "b" * 200),
    ]
    stats = get_total_stats(chunks)

    assert stats["chapter_count"] == 2
    assert stats["total_chars"] == 300
    assert stats["avg_chars_per_chapter"] == 150
    assert stats["max_chars"] == 200
    assert stats["min_chars"] == 100