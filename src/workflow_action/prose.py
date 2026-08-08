"""ProseUnit — 章节正文生成（ProseUnit 概念落地）。

compose/extend 的 PlotUnit 只产出结构，不产出正文（frame.py 明确
"does not generate PlotUnit prose"）。本模块在 review 通过后新增独立
[WAITING] 步骤：渲染成文 prompt，要求 LLM 产出纯文本章节正文，
落盘到 novels/<小说名>/chapters/chapter_<N>.txt。

零成本契约：`--no-prose` 时流程与旧版一致（不新增 prose_prompt/response、
不写 chapters/），prompt 字节不变。
"""

import json
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


def is_duplicate_of_last(
    chapter_text: str,
    chapters_dir: Path,
    threshold: float = 0.7,
) -> bool:
    """新正文与最后一章几乎逐句相同 → 判定为重复章（staged 响应被复用/陈旧）.

    用句集重叠率（按 。！？ 切句，跳过 <8 字短句）判断：新章句子中 ≥threshold
    的比例出现在上一章 → 视为把当前章逐字重渲染成新文件（真实出现的复发：
    ch5 整章复制 ch4）。在落盘点兜底——无论 staged 响应为何被复用都拒绝写盘。
    """
    import re

    def _sentence_set(text: str) -> set[str]:
        return {
            s.strip()
            for s in re.split(r"[。！？]", text)
            if len(s.strip()) > 8
        }

    n = next_chapter_number(chapters_dir)
    if n <= 1:
        return False
    last_path = chapter_path(chapters_dir, n - 1)
    if not last_path.exists():
        return False
    current = _sentence_set(chapter_text)
    if not current:
        return False
    previous = _sentence_set(last_path.read_text(encoding="utf-8"))
    overlap = len(current & previous)
    return overlap / len(current) >= threshold


def is_same_as_last(chapter_text: str, chapters_dir: Path) -> bool:
    """候选正文是否与最后一章逐字相同（同一 prose_response 的重复读入，非重复章）.

    新时序（先成文、后审查）下，正文已落盘后 operator 重跑以提供 review_response，
    prose_response 尚未被 reset 消费——本步会再次读入同一正文。若与最后一章逐字
    相同，说明是同一章的重读（应复用既有章节，跳过落盘），而非重复章。
    """
    n = next_chapter_number(chapters_dir)
    if n <= 1:
        return False
    last_path = chapter_path(chapters_dir, n - 1)
    if not last_path.exists():
        return False
    return last_path.read_text(encoding="utf-8").strip() == chapter_text.strip()


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
    original_style_context: str = "",
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
    if original_style_context:
        lines += ["", "【原文文风参考】", original_style_context]
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


def build_revision_prompt(
    blocking_issues: list,
    chapter_text: str,
    *,
    plotunit: PlotUnit | None = None,
    target_chapter_chars: int | None = None,
) -> str:
    """正文修订 prompt（post-prose Review 的 rewrite 路径）.

    Review 移到成文后，若正文层审查发现阻断性问题，正文已存在——不再重走
    PlotUnit→Prose，而是带阻断 issue 直接修订已有章节正文（正文层修复，
    不重建对象层）。LLM 返回修订后的完整章节正文（纯文本）。
    """
    lines = [
        "你是一位小说改写作者。以下章节正文在审查中发现阻断性问题，"
        "请修订正文以解决这些问题（保持情节结构、人物与既有事件一致）。",
        "",
        "【阻断性问题】",
    ]
    for issue in blocking_issues:
        desc = getattr(issue, "description", str(issue))
        issue_type = getattr(issue, "issue_type", "issue")
        severity = getattr(issue, "severity", "warning")
        lines.append(f"- [{severity}] {issue_type}: {desc}")
        suggested = getattr(issue, "suggested_fix", None)
        if suggested:
            lines.append(f"  建议: {suggested}")
    if plotunit is not None:
        lines += ["", "【PlotUnit（结构依据）】", plotunit.to_prompt_context()]
    lines += ["", "【当前章节正文】", chapter_text]
    if target_chapter_chars:
        lines.append(
            f"篇幅保持约 {target_chapter_chars} 字符（去空白），"
            f"允许 ±{int(CHAPTER_LEN_TOLERANCE * 100)}% 浮动。"
        )
    lines += [
        "",
        "【输出格式】直接输出修订后的完整章节正文（纯文本，不要 JSON、不要前后缀说明）。",
    ]
    return "\n".join(lines)


def record_chapter_provenance(
    output_dir: Path,
    chapter_number: int,
    *,
    prose_review_enabled: bool = True,
    draft_commit_enabled: bool = True,
    review_version: str = "post-prose-v1",
    review_issues: list | None = None,
    final_draft_chars: int | None = None,
    first_draft_chars: int | None = None,
    expansion_required: bool | None = None,
    active_frame_id: str | None = None,
    active_formula_node: str | None = None,
) -> Path:
    """记录已提交章节的审核世代 + 原始 Review issues + 篇幅/Frame 观测.

    用途：所有测量（PASS Audit / A/B / Drift / Draft-Committed / 篇幅）都必须
    version-aware + 人工介入可溯源。**操作者扩写也是 provenance**——否则几章后
    分不清 Committed 质量来自 Prose / Review / 人工扩写。

    `review_issues`：该章 Review 报出的 issues（O）。PASS ≠ Review 没发现 issue。

    `final_draft_chars` / `first_draft_chars` / `expansion_required`：篇幅观测。
    初稿是否偏短、是否需操作者主动扩写，连续几章可判断『偏短』是偶发还是
    Prose Generator 的稳定 attractor。

    `active_frame_id` / `active_formula_node`：生成该章时 frame_context 注入的
    当前帧——用于观测终止型节点（resolution 等）在多少个新 committed chapter
    后仍被消费（Frame 生命周期频率证据）。
    """
    path = output_dir / "chapter_provenance.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"schema_version": 1, "chapters": {}}

    flow_version_path = output_dir / ".flow_version"
    flow_version = "2"
    if flow_version_path.exists():
        flow_version = flow_version_path.read_text(encoding="utf-8").strip() or "2"

    issues = []
    for i in review_issues or []:
        d = i.model_dump(mode="json") if hasattr(i, "model_dump") else i
        issues.append({
            "issue_id": d.get("issue_id"),
            "issue_type": d.get("issue_type"),
            "severity": d.get("severity"),
            "location": d.get("location"),
            "description": d.get("description"),
        })

    data["chapters"][f"chapter_{chapter_number}"] = {
        "chapter_number": chapter_number,
        "flow_version": flow_version,
        "review_version": review_version,
        "prose_review_enabled": bool(prose_review_enabled),
        "draft_commit_enabled": bool(draft_commit_enabled),
        "review_issues": issues,
        # 篇幅观测（操作者扩写也如实记录）
        "first_draft_chars": first_draft_chars,
        "final_draft_chars": final_draft_chars,
        "expansion_required": expansion_required,
        "expansion_delta": (
            (final_draft_chars - first_draft_chars)
            if (final_draft_chars is not None and first_draft_chars is not None)
            else None
        ),
        # Frame 生命周期观测
        "active_frame_id": active_frame_id,
        "active_formula_node": active_formula_node,
        "committed_at_utc": None,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def archive_draft(output_dir: Path, chapter_number: int, draft_text: str) -> Path:
    """归档已提交章的 draft（output/prose_history/draft_chapter_<N>.txt）.

    用途：Style Drift 测量比较 Draft vs Committed——若 Draft 有变化、Review 一修就
    统一，罪魁祸首是 Review（homogenization），而不是 Prose。draft 在提交后仍保留
    于此（prose_draft.txt 会被下一章覆盖，归档留史）。
    """
    hist = output_dir / "prose_history"
    hist.mkdir(parents=True, exist_ok=True)
    path = hist / f"draft_chapter_{chapter_number}.txt"
    path.write_text(draft_text, encoding="utf-8")
    return path


def archive_raw_prose(output_dir: Path, chapter_number: int, raw_text: str) -> Path:
    """归档首次解析的 raw prose（output/prose_history/raw_chapter_<N>.txt）.

    用途：Operator Expansion 入 provenance——文本阶段拆清：
        raw →（操作者扩写）→ draft →（Review 修订）→ committed
    Style Drift / Draft quality / Review Gain 比较时能区分功劳来自 Prose / 人工扩写
    / Review。只在首次解析时写（后续重跑不覆盖已归档的 raw）。
    """
    hist = output_dir / "prose_history"
    hist.mkdir(parents=True, exist_ok=True)
    path = hist / f"raw_chapter_{chapter_number}.txt"
    if not path.exists():
        path.write_text(raw_text, encoding="utf-8")
    return path


def record_prose_revision(
    output_dir: Path,
    *,
    cycle_id: str,
    issues: list,
    original: str,
    revision: str,
) -> Path:
    """把一次正文层修订记入 A/B 台账（output/prose_revision_ledger.json，schema v2）.

    目的：测量 Post-Prose Review 的 **Detection Precision**（说有问题时真有问题吗）
    vs **Revision Gain**（按它改真的更好吗），而不是默认「Review 成功」。为防
    **评审自证**（Review 生成修订、又自己偏好自己的写法），台账只存无标注的
    A/B 对 + 哪个是原文（`which_is_original` 随机，盲评时隐藏），并记录 issue
    类型/严重度供分层统计。

    Args:
        output_dir: 工作区 output 目录。
        cycle_id: 本轮 PlotUnit unit_id。
        issues: 触发修订的阻断性 ReviewIssue 列表。
        original: 修订前 draft。
        revision: 修订后 draft。
    """
    import random

    issue_types = sorted({getattr(i, "issue_type", "unknown") for i in issues})
    severities = [getattr(i, "severity", "warning") for i in issues]
    issue_severity = "blocking" if "blocking" in severities or "critical" in severities else (
        "critical" if "critical" in severities else "warning"
    )
    # 随机化 A/B 顺序：Judge 不知道『哪个是原文』
    which_is_original = random.choice(("a", "b"))
    if which_is_original == "a":
        version_a, version_b = original, revision
    else:
        version_a, version_b = revision, original

    ledger_path = output_dir / "prose_revision_ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = {"schema_version": 1, "revisions": []}
    ledger["schema_version"] = 2
    flow_version_path = output_dir / ".flow_version"
    flow_version = "2"
    if flow_version_path.exists():
        flow_version = flow_version_path.read_text(encoding="utf-8").strip() or "2"
    entry = {
        "cycle_id": cycle_id,
        "issue_types": issue_types,
        "issue_severity": issue_severity,
        "flow_version": flow_version,
        "version_a": version_a,
        "version_b": version_b,
        "which_is_original": which_is_original,  # 盲评时隐藏
        # Detection Precision：原文是否确实存在被标记的缺陷（separate pass，多 Judge）
        "detection": {"judgments": [], "original_has_flaw": None},
        # Revision Gain：A/B 偏好（judge 独立于 Revision Agent，多 Judge 可区分 3/3、2/3、split）
        "revision_gain": {"judgments": [], "preference": None, "confidence": None},
    }
    ledger["revisions"].append(entry)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ledger_path


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
