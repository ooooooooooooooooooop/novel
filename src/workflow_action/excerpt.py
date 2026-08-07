"""原文锚点与文风样例加载器 — 从续写输入文本抽取最近 K 章逐字原文.

给 Continue prompt 注入【原文锚点与文风样例】：
- 最近 K 章逐字原文（连续接续锚点）——让模型知道它要接续的上文，
  并能从原文直接模仿作者的句式节奏（保留原始断句/段落，不压扁）。
- 额外 N 段场景匹配片段可选（档 1 只做最近 K 章，语义检索留待档 2）。

对齐 style.py load_style_context / retrieval.py load_retrieval_context：
静默降级 loader —— 空输入 / 无可切分章节返回 ""，不产生注入字节。
"""

from pathlib import Path


def _chapter_num(path: Path) -> int:
    """chapter_N.txt → N；解析失败返回大数（排最后）。"""
    try:
        return int(path.stem[len("chapter_"):])
    except ValueError:
        return 10**9


def append_generated_chapters(source_text: str, chapters_dir: Path) -> str:
    """把已续写章节追加到源文本后，供文风锚点/前章结尾使用.

    source_text 是原书文本；chapters_dir 里可能已有续写生成的 chapter_N.txt。
    续写多章后，『最近章节』应是最后生成的章，而不是原书首章——否则：
    - 【原文锚点与文风样例】永远锁死在原书第一章，文风不随故事演进（自我模仿/停滞）；
    - 【前章结尾】永远取原书尾段，续写衔接点错误。
    若生成章内容已在 source_text 中（如 input 即 chapter_1），不重复追加。
    """
    if not chapters_dir.exists():
        return source_text
    parts = [source_text]
    for path in sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num):
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            continue
        if txt in source_text:
            continue
        parts.append(txt)
    return "\n\n".join(p for p in parts if p)


def load_recent_excerpts(
    source_text: str,
    tail_chapters: int = 2,
    max_chars_per_excerpt: int = 1800,
) -> str:
    """从续写输入文本抽取最近 K 章逐字原文，渲染注入文本.

    Args:
        source_text: 续写输入文本（原书 + 已续写章节）。
        tail_chapters: 取最近几章原文。
        max_chars_per_excerpt: 每章最多注入字符数（防 prompt 过长）。

    Returns:
        渲染文本；空输入或无法切分时返回 ""（静默降级）。
    """
    if not source_text or not source_text.strip():
        return ""
    from src.boundary_control.chunking import split_by_chapters

    chunks = split_by_chapters(source_text)
    if not chunks:
        return ""
    recent = chunks[-tail_chapters:]
    lines = [
        f"以下为续写点之前最近 {len(recent)} 章原文（逐字摘录，供接续与文风模仿）："
    ]
    for chunk in recent:
        text = chunk.text.strip()
        if not text:
            continue
        if len(text) > max_chars_per_excerpt:
            text = text[:max_chars_per_excerpt] + "……（截断）"
        lines.append(f"\n【第{chunk.chapter_index}章 {chunk.chapter_title}】\n{text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
