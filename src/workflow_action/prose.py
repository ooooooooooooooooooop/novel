"""ProseUnit — 章节正文生成（ProseUnit 概念落地）。

compose/extend 的 PlotUnit 只产出结构，不产出正文（frame.py 明确
"does not generate PlotUnit prose"）。本模块在 review 通过后新增独立
[WAITING] 步骤：渲染成文 prompt，要求 LLM 产出纯文本章节正文，
落盘到 novels/<小说名>/chapters/chapter_<N>.txt。

零成本契约：`--no-prose` 时流程与旧版一致（不新增 prose_prompt/response、
不写 chapters/），prompt 字节不变。
"""

from pathlib import Path

from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit

# 章节正文去空白后的下限（字符）：过短视为未成文。
MIN_PROSE_CHARS = 200

# 续写衔接时取原文末尾片段长度（字符）。
PREV_CHAPTER_TAIL_CHARS = 600


def next_chapter_number(chapters_dir: Path) -> int:
    """扫描 chapters/ 下 chapter_<N>.txt，返回 max(N)+1；目录为空返回 1。

    无前导零，对齐现有 chapter_1197.txt 命名。忽略非 chapter_<整数>.txt 的文件。
    """
    max_num = 0
    if chapters_dir.exists():
        for path in chapters_dir.glob("chapter_*.txt"):
            try:
                num = int(path.stem[len("chapter_"):])
            except ValueError:
                continue
            if num > max_num:
                max_num = num
    return max_num + 1


def chapter_path(chapters_dir: Path, n: int) -> Path:
    """生成第 n 章路径：chapters_dir / f"chapter_{n}.txt"（无前导零）。"""
    return chapters_dir / f"chapter_{n}.txt"


def prev_chapter_tail(text: str, max_chars: int = PREV_CHAPTER_TAIL_CHARS) -> str:
    """取文本末尾片段作续写衔接（extend 用；无原文则空串）。"""
    if not text:
        return ""
    return text[-max_chars:]


def build_prompt(
    plotunit: PlotUnit,
    new_state: NarrativeState,
    *,
    workspec_context: str = "",
    style_context: str = "",
    excerpt_context: str = "",
    timeline_context: str = "",
    time_context: str = "",
    prev_chapter_end: str = "",
) -> str:
    """渲染成文 prompt。

    要求 LLM 忠于 PlotUnit 结构成文，衔接前章结尾，不引入 PlotUnit 外新事实。
    【输出格式】为纯文本正文（非 JSON）。
    """
    lines = [
        "你是一位小说续写作者。请将下列 PlotUnit 结构展开为章节正文。",
        "",
        "【硬性约束】",
        "1. 只使用 PlotUnit 中明确出现的参与者、事件、后果与释放信息；"
        "不得引入 PlotUnit 之外的新事实、新角色、新设定。",
        "2. 忠于 PlotUnit 的 goal 与 conflict，确保 consequence 在正文中落地。",
        "3. 衔接前章结尾的自然语感与事件细节，不要重复前章内容。",
        "4. 篇幅与上下文风格匹配，不得明显偏短，也不得注水。",
        "",
        "【PlotUnit】",
        plotunit.to_prompt_context(),
    ]
    if workspec_context:
        lines += ["", "【作品约束】", workspec_context]
    if style_context:
        lines += ["", "【写作风格】", style_context]
    if excerpt_context:
        lines += ["", "【上下文摘录】", excerpt_context]
    if timeline_context:
        lines += ["", "【时间线】", timeline_context]
    if time_context:
        lines += ["", "【时间上下文】", time_context]
    if prev_chapter_end:
        lines += ["", "【前章结尾】", prev_chapter_end]
    lines += [
        "",
        "【输出格式】直接输出章节正文（纯文本，不要 JSON、不要前后缀说明）。",
    ]
    return "\n".join(lines)


def parse_response(text: str) -> str:
    """校验并提取章节正文。

    Raises:
        ValueError: 正文为空或去空白后低于 MIN_PROSE_CHARS。
    """
    body = text.strip()
    if not body:
        raise ValueError("prose response is empty")
    compact_len = len("".join(body.split()))
    if compact_len < MIN_PROSE_CHARS:
        raise ValueError(
            f"prose response too short: {compact_len} chars (min {MIN_PROSE_CHARS})"
        )
    return body
