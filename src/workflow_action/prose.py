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

# 篇幅对齐容忍带：续写章目标章均字符数，允许 ±35% 浮动（先宽后紧）。
CHAPTER_LEN_TOLERANCE = 0.35

# 续写禁止逐字复刻原文的最短连续片段（字符）：≥ 此长度视为大段原文复用。
REUSE_MIN_CHARS = 30


def average_chapter_chars(chunks) -> int:
    """计算原文章均去空白字符数（篇幅对齐参考值）.

    对每个章节块取去空白字符数（与 parse_response 同一口径），返回均值；
    无有效文本返回 0。chunks 为 split_by_chapters 产物（含 .text / .chapter_index）。
    """
    counts = [
        len("".join(getattr(c, "text", "").split()))
        for c in chunks
        if getattr(c, "text", "")
    ]
    if not counts:
        return 0
    return round(sum(counts) / len(counts))


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


def find_overlapping_spans(
    draft: str, source: str, min_chars: int = REUSE_MIN_CHARS
) -> list[dict]:
    """找出 draft 中与 source 逐字相同的连续片段（原文长段去重用）.

    以长度为 min_chars 的原文 n-gram 为种子建倒排索引，在 draft 中定位种子
    后向两侧扩展，得到完整公共子串；合并相邻/重叠片段，按 draft 起点排序。

    返回 [{"start": draft 起始下标, "length": 片段长, "text": 片段}...]。
    无匹配或任一文本不足 min_chars 时返回空列表。
    """
    n = min_chars
    if (
        not draft or not source
        or len(draft) < n or len(source) < n
    ):
        return []

    index: dict[str, list[int]] = {}
    for j in range(len(source) - n + 1):
        index.setdefault(source[j:j + n], []).append(j)

    covered: list[tuple[int, int]] = []
    for i in range(len(draft) - n + 1):
        gram = draft[i:i + n]
        for j in index.get(gram, ()):
            # 向左扩展：draft[i-k] == source[j-k]
            s = i
            while s > 0 and j - (i - s) > 0 and draft[s - 1] == source[j - (i - s) - 1]:
                s -= 1
            # 向右扩展：draft[i+n+k] == source[j+n+k]
            e = i + n
            while (
                e < len(draft)
                and j + (e - i) < len(source)
                and draft[e] == source[j + (e - i)]
            ):
                e += 1
            if e - s >= n:
                covered.append((s, e))

    if not covered:
        return []

    covered.sort()
    merged = [covered[0]]
    for s, e in covered[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    return [
        {"start": s, "length": e - s, "text": draft[s:e]}
        for s, e in merged
    ]


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
    target_chapter_chars: int | None = None,
    reuse_source: str = "",
) -> str:
    """渲染成文 prompt。

    要求 LLM 忠于 PlotUnit 结构成文，衔接前章结尾，不引入 PlotUnit 外新事实。
    【输出格式】为纯文本正文（非 JSON）。

    target_chapter_chars 非空时注入篇幅对齐硬约束（目标章均字符数，±35% 浮动）；
    reuse_source 非空时注入原文去重约束（禁止逐字复刻原文长段）。
    两者缺省时 prompt 字节与旧版一致（零成本契约）。
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
    ]
    if target_chapter_chars:
        lines.append(
            f"5. 本章目标篇幅约 {target_chapter_chars} 字符（去空白），"
            f"允许 ±{int(CHAPTER_LEN_TOLERANCE * 100)}% 浮动，不得明显偏短或注水。"
        )
    if reuse_source:
        lines.append(
            f"6. 参考原文语感与意象，但禁止逐字复刻原文："
            f"连续 ≥{REUSE_MIN_CHARS} 字符与原文相同的片段视为重复，须用自己的话重述。"
        )
    lines += ["", "【PlotUnit】", plotunit.to_prompt_context()]
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


def parse_response(text: str, target_chars: int | None = None) -> str:
    """校验并提取章节正文。

    Args:
        text: LLM 产出的章节正文。
        target_chars: 续写篇幅对齐目标（章均字符数）。正文去空白长度低于
            目标下界（target × (1 - CHAPTER_LEN_TOLERANCE)）时打印 WARNING，
            但不抛错——篇幅不足属质量告警，不应中断 [WAITING] 流程。

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
    if target_chars and compact_len < target_chars * (1 - CHAPTER_LEN_TOLERANCE):
        lower = int(target_chars * (1 - CHAPTER_LEN_TOLERANCE))
        print(
            f"WARNING prose short: {compact_len} chars vs chapter average "
            f"{target_chars} (below {lower}, the ±{int(CHAPTER_LEN_TOLERANCE * 100)}% band)"
        )
    return body
