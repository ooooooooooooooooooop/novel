"""章节切分工具 — 按小说章节边界切分长文本."""

import re
from dataclasses import dataclass

@dataclass
class ChapterChunk:
    """单个章节块."""
    chapter_index: int  # 从 1 开始
    chapter_title: str
    text: str

_CHAPTER_PATTERN = re.compile(
    r"(?:^|\n)\s*第\s*([一二三四五六七八九十百千零\d]+)\s*章(?:[：:·]\s*|\s+)(.+?)(?=\n|$)",
    re.MULTILINE,
)

def split_by_chapters(text: str) -> list[ChapterChunk]:
    """按'第X章 标题'格式切分文本，自动去重（保留正文最长的块）."""
    matches = list(_CHAPTER_PATTERN.finditer(text))
    if not matches:
        return [ChapterChunk(chapter_index=1, chapter_title="全文", text=text.strip())]

    # 先收集所有候选块
    candidates: list[ChapterChunk] = []
    for i, match in enumerate(matches):
        chapter_num = match.group(1)
        title = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapter_text = text[start:end].strip()
        candidates.append(
            ChapterChunk(
                chapter_index=_parse_chapter_number(chapter_num),
                chapter_title=title,
                text=chapter_text,
            )
        )

    # 去重：同一 chapter_index 保留文本最长的（正文优先于目录引用）
    by_index: dict[int, ChapterChunk] = {}
    for chunk in candidates:
        if chunk.chapter_index not in by_index:
            by_index[chunk.chapter_index] = chunk
        elif len(chunk.text) > len(by_index[chunk.chapter_index].text):
            by_index[chunk.chapter_index] = chunk

    # 按章节号排序
    return [by_index[idx] for idx in sorted(by_index.keys())]

def _parse_chapter_number(s: str) -> int:
    """将中文/阿拉伯数字章节号转为整数."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    chinese_digits = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    chinese_units = {"十": 10, "百": 100, "千": 1000}
    result = 0
    current = 0
    for char in s:
        if char in chinese_digits:
            current = chinese_digits[char]
        elif char in chinese_units:
            if current == 0:
                current = 1
            result += current * chinese_units[char]
            current = 0
        else:
            continue
    result += current
    return result

def count_non_whitespace(text: str) -> int:
    """去空白后的字符数（含标点，不含空白）."""
    return sum(1 for ch in text if not ch.isspace())


def get_total_stats(chunks: list[ChapterChunk]) -> dict:
    """返回切分统计."""
    return {
        "chapter_count": len(chunks),
        "total_chars": sum(len(c.text) for c in chunks),
        "avg_chars_per_chapter": sum(len(c.text) for c in chunks) // max(len(chunks), 1),
        "max_chars": max(len(c.text) for c in chunks) if chunks else 0,
        "min_chars": min(len(c.text) for c in chunks) if chunks else 0,
    }
