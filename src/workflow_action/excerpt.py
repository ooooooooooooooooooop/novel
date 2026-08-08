"""原文锚点加载器 — 接续连续性 vs 文风参考的职责拆分.

方向文档第六节：最近生成章节不应同时承担『续写连续性』与『文风模仿』——
AI102 模仿 AI101 生成章、AI103 再模仿 AI101/102，会造成 Self-Imitation Drift。
职责拆分：

- 接续连续性（刚发生了什么）→ `load_recent_excerpts(原书 + 已生成章)`：
  越新越好，供衔接上文事件与语感，不作为文风基准。
- 文风参考（这部作品应该怎样表达）→ `load_original_style_sample(只取原书)`：
  原始人类参考文本 + StyleProfile（【写作风格】），已生成章只用于 drift 检测，
  不逐渐替代原始风格基准。

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
    """把已续写章节追加到源文本后，供接续锚点/前章结尾使用.

    source_text 是原书文本；chapters_dir 里可能已有续写生成的 chapter_N.txt。
    续写多章后，『最近章节』应是最后生成的章，而不是原书首章——否则：
    - 【上文锚点】永远锁死在原书第一章，接续不随故事演进（自我模仿/停滞）；
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
    """从续写输入文本抽取最近 K 章逐字原文，渲染为【接续锚点】.

    供『刚发生了什么』的衔接：取最近几章（含已生成章）让模型知道上文与语感。
    **不作为文风基准**——文风由 load_original_style_sample（只取原书）+
    StyleProfile 承担，避免 Self-Imitation Drift。

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
        f"以下为续写点之前最近 {len(recent)} 章原文（逐字摘录，供接续：衔接前文事件与语感，"
        "不作为文风基准——文风以原书文风参考与风格档案为准）："
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


def load_original_style_sample(
    source_text: str,
    tail_chapters: int = 2,
    max_chars_per_excerpt: int = 1200,
) -> str:
    """从『原始人类参考文本』抽取最近 K 章原文作为【文风参考】.

    与 load_recent_excerpts 分工：本函数**只取原书**（不包含已生成章），
    回答『这部作品应该怎样表达』。已生成章只用于 drift 检测，不进入文风基准。

    Args:
        source_text: 原始人类参考文本（extend 的 input 原书；compose 无原书传空）。
        tail_chapters: 取原书最近几章（接续点之前的人类语感）。
        max_chars_per_excerpt: 每章最多注入字符数。

    Returns:
        渲染文本；空输入 / 无可切分章节返回 ""（静默降级）。
    """
    if not source_text or not source_text.strip():
        return ""
    from src.boundary_control.chunking import split_by_chapters

    chunks = split_by_chapters(source_text)
    if not chunks:
        return ""
    recent = chunks[-tail_chapters:]
    lines = [
        f"以下为原书最近 {len(recent)} 章原文（逐字摘录，作为本作品的文风基准，"
        "仅模仿这里的表达方式、意象系统与语感）："
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
