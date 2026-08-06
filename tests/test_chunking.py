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

    # 全角冒号章节格式（如「第一章：开篇」）也应识别
    text2 = "第一章：开篇\n这是第一章的正文内容。\n第二章：发展\n这是第二章的正文内容。"
    chunks2 = split_by_chapters(text2)

    assert len(chunks2) == 2
    assert chunks2[0].chapter_index == 1
    assert chunks2[0].chapter_title == "开篇"
    assert "第一章的正文内容" in chunks2[0].text
    assert chunks2[1].chapter_index == 2
    assert chunks2[1].chapter_title == "发展"

    # 无分隔符的正文行（"第一章的内容"）不得误判为章节标题
    text3 = "第一章的内容我们后面再谈。\n这只是一段正文，不是标题。"
    chunks3 = split_by_chapters(text3)
    assert len(chunks3) == 1
    assert chunks3[0].chapter_title == "全文"


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