"""ProseUnit — 章节正文生成（ProseUnit 概念落地）。

compose/extend 的 PlotUnit 只产出结构，不产出正文（frame.py 明确
"does not generate PlotUnit prose"）。本模块在 review 通过后新增独立
[WAITING] 步骤：渲染成文 prompt，要求 LLM 产出纯文本章节正文，
落盘到 novels/<小说名>/chapters/chapter_<N>.txt。

零成本契约：`--no-prose` 时流程与旧版一致（不新增 prose_prompt/response、
不写 chapters/），prompt 字节不变。
"""

import hashlib
import json
from pathlib import Path

from src.object_state.narrativestate import INFORMATION_LAYER_GUIDANCE, NarrativeState
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
    可选约束缺省时不注入相应段落；不渲染完整 new_state，避免绕过上下文隔离。
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
    lines += [
        "", INFORMATION_LAYER_GUIDANCE,
        "released_information 面向读者；角色说出或据此行动仍须符合其知情范围。"
        "只展开本章允许揭示的内容，不补写未提供的秘密或擅自解释隐藏动机。",
        "", "【读者认知分配】",
        "连接可以留给读者，前提不能藏在作者脑子里。"
        "当动作、对白、细节已足以让读者完成目标推断时，该叙事 beat 已完成："
        "不要替读者翻译证据的含义、讲解刚演完的博弈/策略、或用比喻重述已实现的效果。"
        "但 STOP 有下界——先自查：该推断需要的每个关键前提是否都已进入读者可见文本？"
        "缺前提不得要求读者凭空补，此时只二选一：补一个动作/对白/事实让推断成立，"
        "或直接说出那个正文无法自行提供、但理解所必需的最小信息；不得恢复整段解释。"
        "仅三种情况允许显式说明：(a) 角色不可见、读者无从推断的关键信息；"
        "(b) 读者无法可靠推断的规则或关键因果；(c) 认知本身改变人物的选择、"
        "关系或行动——此时写『意识到』带来的决定，不再补『所以刚才其实意味着……』。"
        "PlotUnit 中的【认知交接点】若存在，是本场景的停止条件：证据给出后即停手，"
        "在 explicit_when 条件满足前不点破；evidence_sufficiency=needs_more_evidence "
        "时先补证据再停。",
        "", "【人物选择显形】",
        "PlotUnit 中的【选择执行契约】若存在：本场必须让人物经行动/对白/不行动/"
        "资源分配完成一个真实取舍——不是旁白宣布。至少一个代价要在选择发生前或"
        "当下让读者可感知，但不得把备选方案和利弊逐项搬进内心独白；选择落地后"
        "禁止再写『这说明他其实是……』『他终究还是把X看得比Y重要』这类性格答案。"
        "不存在的场景禁止硬造戏剧化决断。",
    ]
    if plotunit.dialogue_strategy:
        lines += [
            "", "【对白作为社会行动】",
            "PlotUnit 中的【对白执行契约】若存在：人物通过实际说法推进目的，"
            "而不是解释目的；对方须对刚形成的压力作有效回应，不得无视后换话题；"
            "至少一次交换须改变信息、承诺、杠杆或行动空间；不得让读者明白而把"
            "不能直说的事说破；对白后不得用旁白翻译潜台词。"
            "沉默/克制不能替代本来必须发生的追问、拒绝或表态——只有当沉默本身"
            "改变局面时，它才算有效回应。"
            "不存在的场景正常说话——寒暄、交代、确认不需要潜台词。",
        ]
    lines += [
        "", "【PlotUnit】", plotunit.to_prompt_context(writer_facing=True),
    ]
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
        f"正文去空白后不得少于 {MIN_PROSE_CHARS} 字符（硬下限，低于此值将被拒绝）。",
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
        INFORMATION_LAYER_GUIDANCE,
        "修订不得把读者得知改成所有角色知情，也不得用补写秘密来掩盖状态字段放置错误。",
        "",
        "【阻断性问题】",
    ]
    has_rcc_issue = any(
        getattr(issue, "issue_type", "") == "reader_cognitive_allocation"
        for issue in blocking_issues
    )
    has_dlg_issue = any(
        getattr(issue, "issue_type", "") in {
            "unearned_directness", "objective_unpursued", "flat_tactic",
            "no_response_pressure", "subtext_glossed", "no_turn_delta",
            "dialogue_loop_stasis", "excessive_redundant_tail",
            "formal_echo_after_ack", "subtext_overengineering",
            "redundancy",
        }
        for issue in blocking_issues
    )
    has_detail_issue = any(
        getattr(issue, "issue_type", "") in {
            "decorative_inventory", "functionless_detail", "detail_overload",
            "functional_but_detached",
        }
        for issue in blocking_issues
    )
    has_metaphor_issue = any(
        getattr(issue, "issue_type", "") == "gratuitous_metaphor"
        for issue in blocking_issues
    )
    has_pacing_issue = any(
        getattr(issue, "issue_type", "")
        == "event_chain_without_state_delta"
        for issue in blocking_issues
    )
    has_expectation_issue = any(
        getattr(issue, "issue_type", "") == "suspense_by_withholding"
        for issue in blocking_issues
    )
    has_blank_issue = any(
        getattr(issue, "issue_type", "") in {
            "blank_inference_made_explicit", "blank_under_evidenced",
        }
        for issue in blocking_issues
    )
    has_depiction_issue = any(
        getattr(issue, "issue_type", "") in {
            "depiction_named_only", "depiction_absent",
        }
        for issue in blocking_issues
    )
    for issue in blocking_issues:
        desc = getattr(issue, "description", str(issue))
        issue_type = getattr(issue, "issue_type", "issue")
        severity = getattr(issue, "severity", "warning")
        lines.append(f"- [{severity}] {issue_type}: {desc}")
        suggested = getattr(issue, "suggested_fix", None)
        if suggested:
            lines.append(f"  建议: {suggested}")
    if has_rcc_issue:
        lines += [
            "",
            "【认知劳动分配修订操作】（局部手术，不重写整章）",
            "对每个 reader_cognitive_allocation issue 只执行以下一种操作：",
            "- DELETE_REDUNDANT_GLOSS：解释段无独有贡献，直接删除解释尾巴",
            "- KEEP_UNIQUE_DELTA：解释中只有一处新增信息有价值，只保留该 delta",
            "- CONVERT_GLOSS_TO_EVIDENCE：把『他是在施压』换成真正产生压力的动作/对白"
            "（不是换个漂亮说法）",
            "- MOVE_REALIZATION_TO_DECISION：认知有用但位置错——不在证据后立即讲解，"
            "等它真正改变人物动作时再以决定形式出现",
            "- RESTORE_MISSING_PREMISE：推断缺必要前提——优先补动作/对白反应/"
            "场景事实让推断可完成；实在无法自然表现才保留最小明确句"
            "（补 premise，不是补讲解）",
            "- RESTORE_MEANINGFUL_ALTERNATIVE：让被写成单选题的另一选项重新真正可行",
            "- SURFACE_COST：把已存在但读者看不到的代价显形",
            "- MOVE_COST_BEFORE_CHOICE：代价先可感知，人物再选择，结果再落地",
            "- RETURN_AGENCY：把由巧合/他人替代完成的决定还给人物",
            "- ENACT_CHOICE：把讨论、犹豫、计划落成实际行动",
            "- CONVERT_TRAIT_TO_DIAGNOSTIC_BEHAVIOR：把『他很谨慎/重情/野心大』"
            "换成压力下的行为",
            "- REMOVE_TRAIT_GLOSS：保留行为，删掉重复性格答案",
            "- KEEP_EXPLICIT：规则关键/不可推断/认知本身造成状态变化时保留原文",
            "- NO_CHANGE：误判，原文本就正确",
            "禁止以『选择不够鲜明』为由把人物改得更极端或降智——目标是恢复真实取舍",
            "每个修改必须带 protected_function：该段原本承担的叙事功能，"
            "修改后功能必须仍在（悬念方向、人物判断、因果、情绪基调不得因删解释而丢失）。"
            "不得把『需要读者自己推断』误改成『故作含蓄』——若删除解释后读者缺少必要证据，"
            "选择 KEEP_EXPLICIT 或 CONVERT_GLOSS_TO_EVIDENCE。",
        ]
    if has_dlg_issue:
        lines += [
            "",
            "【对白社会行动修订操作】（仅针对对白族 issue，局部手术）",
            "- RESTORE_SOCIAL_CONSTRAINT：把被无故说破的信息重新放回合理边界",
            "- TURN_INFORMATION_INTO_MOVE：把纯信息台词变成推进目的的社会行动",
            "- RESTORE_RESPONSE_PRESSURE：让下一轮实际回应刚形成的压力",
            "- PURSUE_INTERACTION_OBJECTIVE：让人物通过说法真正争取需要的结果",
            "- REMOVE_SUBTEXT_GLOSS：潜台词已成立，删除旁白翻译",
            "- CREATE_TURN_DELTA：让无效交锋真正改变信息/承诺/杠杆/行动空间",
            "- COLLAPSE_REDUNDANT_EXCHANGE：保留已确立的条款/边界/风险条件与"
            "最后一个有效动作，把零新增 delta 的重复确认轮次压掉或转入下一行动——"
            "不得改写成另一套更漂亮的车轱辘",
            "- COMPRESS_FORMAL_ECHO：保留第一次完整表达与后续轮次真正新增的"
            "社会动作，把逐字/近逐字重述改为指代、确认、动作或直接进入下一步——"
            "微功能保留，正文不再整段重说同一措辞",
            "- COLLAPSE_NARRATIVE_RESTATEMENT：叙述段落复述已确立的计划/事实/"
            "情绪且零新增状态时，保留首次完整陈述，后续同命题段落压成"
            "指代/一句带过/或转入行动——不得第三遍原样重说",
            "折叠保留约束（折叠类操作必须遵守）：第一次实质回应（首次回答/"
            "承诺/拒绝的完整表达）不得删除或压成谜语；尚未获得实质回应的"
            "追问/压力不得被沉默或省略吞掉——这些不是冗余，删了等同制造"
            " no_response_pressure；被压掉的只能是『已确认命题的重复确认轮次』。",
            "沉默/克制不能替代本来必须发生的追问、拒绝或表态——只有当沉默本身"
            "改变局面时，它才算有效回应；否则必须让该交换真实发生。",
        ]
    if has_detail_issue:
        lines += [
            "",
            "【细节功能修订操作】（仅针对细节族 issue，局部手术）",
            "- FUNCTIONALIZE_DETAIL：给被判无功能的细节接上当前用途——让它"
            "帮读者定位空间、约束/使能行动、提供感官在场、标记关系或投射"
            "氛围；接功能靠改写法（细节如何被使用/被注意/改变局面），"
            "不是补一句「这很有用」式声明",
            "- CUT_INVENTORY_LIST：删掉成簇无功能的枚举物体，保留其中确有"
            "功能的项并让其承担功能",
            "- REINTEGRATE_DETAIL：细节功能成立但表达为声明/罗列式插入——"
            "只改承载方式：把该细节改写为附着在具体动作/感知/判断/空间阻碍"
            "上并使其改变当前状态；细节对象本身不重选、不删除",
            "- THIN_DETAIL_DENSITY：在关键交锋/动作段落中移除打断节奏的"
            "无关环境描写，让当前读者任务不被稀释",
            "细节保留约束（必须遵守）：不得删除空间定位信息、行动约束"
            "（距离/掩体/出口/工具）、连续性物件、线索伏笔、关系标记物，"
            "以及已在后文/当前行动中兑现的累积氛围；不得把「细节多」治成"
            "「场景真空」——删后读者必须仍能定位与追踪行动。",
        ]
    if has_metaphor_issue:
        lines += [
            "",
            "【比喻必要性修订操作】（仅针对 gratuitous_metaphor issue，局部手术）",
            "- REPLACE_WITH_LITERAL：该显式比喻经最强直述替换验证无任何实质"
            "损失——移除整个类比构式（标记词+喻体+呼应尾），用 issue 描述中"
            "给出的直述替换稿落地。约束：替换稿必须保留原命题与全部对象/关系"
            "指涉、保持语法角色与上下文衔接、不引入新事实；严禁把该比喻"
            "改写成另一个比喻/类比（替换后再次出现 像/如/仿佛/宛如/如同 "
            "构式即视为未完成本操作）；不得顺手重写整段或删除比喻之外仍"
            "承担功能的句子。",
            "比喻保留约束（必须遵守）：issue 未列出的比喻一律不动；"
            "被列比喻若其实承担了压缩结构关系/映射/人物认知立场（视点 delta)/"
            "意象承接等不可直述功能，是仲裁误判——但该判断已在仲裁层完成，"
            "此处不得自行发明新功能来保留它，只可执行 REPLACE_WITH_LITERAL。",
        ]
    if has_pacing_issue:
        lines += [
            "",
            "【语义节奏修订操作】（仅针对 event_chain_without_state_delta issue，局部手术）",
            "- COMPRESS_EVENT_CHAIN：删除/合并无功能的中间步骤——"
            "如「开门，进屋，脱鞋，放下钥匙，走到厨房」→「他进屋径直去了厨房」。"
            "硬约束：不改变事件最终结果；不改变必要因果顺序；不删除后文依赖的"
            "物件/位置/动作；不引入新事实；保持视角；只动 issue 定位的链。"
            "边界（PC-BEAT-COLLAPSE-01 / PC-DIALOGUE-COLLAPSE-01 冻结）："
            "①不得跨越既有段落/空行边界合并——段界本身是节拍结构，只允许在"
            "同一自然段内删并中间步骤；②对白发言轮（引号行/应答轮）不属于"
            "可压缩节点，严禁把 shown dialogue 转成叙述摘要仅为提速——对白"
            "冗余由对白机制负责。",
            "- SURFACE_EXISTING_STATE_DELTA：仅当状态变化已存在于下游正文/"
            "场景计划/细节契约中、但被机械动作链隔开时，把它提前或并接到动作"
            "结果处。严禁为「更有推进感」现场发明后果、情绪或信息——没有已存在"
            "的 delta 时只可压缩。",
            "节奏保留约束（必须遵守）：承担悬念时序/仪式感/人物刻画/空间因果/"
            "感官铺垫/喜剧或戏剧节拍的动作链不得压缩；压缩后读者必须仍能追踪"
            "位置与动作连续性。",
        ]
    if has_expectation_issue:
        lines += [
            "",
            "【读者预期修订操作】（仅针对 suspense_by_withholding issue，局部手术）",
            "- DELIVER_DUE_ANSWER：该回答/行动/兑现在当前因果链已到期——"
            "让它在本场真实发生（人物给出回答、采取行动、承诺兑现）。"
            "是「发生」不是「解释」：不得用一段说明代替事件发生；"
            "兑现内容须与已有事实/承诺相容，不得发明新答案。",
            "- REMOVE_ARTIFICIAL_DELAY：删除仅为推迟到期事件而存在的人为"
            "延迟手段——突然打断、欲言又止、无理由转场、「以后再告诉你」、"
            "人到场却反复拖。删除后因果链继续走，不补新障碍。",
            "- SURFACE_EXISTING_EVIDENCE：把世界状态/当前事件中已存在的"
            "证据写进读者可见层（让已有线索被看到）。严禁凭空造新线索/"
            "新事实——只能呈现已存在者。",
            "预期保留约束（必须遵守）：不得为延期再开新悬念；"
            "未列 issue 的开放预期不动；合法悬念（问题未解但读者可能性/"
            "风险/预测已有变化）不是拖延，不得强行兑现。",
        ]
    if has_blank_issue:
        lines += [
            "",
            "【留白修订操作】（仅针对 blank_* issue，局部手术）",
            "- SUPPRESS_STATED_INFERENCE：已声明留给读者的推断被正文说破——"
            "删去陈述/总结/解释该结论的句子（旁白、内心总结、对白点破都算），"
            "让已呈现的证据自己闭合。只删说破的部分，不动证据本身。",
            "- RESTORE_BLANK_EVIDENCE：声明留白但证据不足——把计划中缺失的"
            "证据以读者可见的动作/对白/细节补出（补证据，不是补讲解）；"
            "补不出足够证据则不保留此留白，改为最小明说或删除该推断设计。",
            "留白保留约束（必须遵守）：留白的目标推断不得改写进正文任何"
            "显式形式；证据补足后正文仍不得替读者说出最后一步；"
            "不得为解决留白再开新解释段落。",
        ]
    if has_depiction_issue:
        lines += [
            "",
            "【白描修订操作】（仅针对 depiction_* issue，局部手术）",
            "- GROUND_DEPICTION：已声明的体验质感只剩抽象命名或整体缺席——"
            "在责任 beat 内把质感落成可观察的动作/神态/语气/器物/空间/节奏，"
            "让读者【感受到】而非【被告知】。载体不限于计划清单，任何有效"
            "可观察呈现都算；但稀薄到可替换的痕迹不算承载。",
            "白描保留约束（必须遵守）：目标质感不得用抽象词直接命名兑现"
            "（「他很烦躁」「气氛压抑」类句子不是载体）；补载体时不得顺手"
            "把质感再说破一遍；责任 beat 外的段落不承担该意图——若场景已"
            "合法转线不在该 beat，则不强行塞回。",
        ]
    if plotunit is not None:
        lines += ["", "【PlotUnit（结构依据）】", plotunit.to_prompt_context(writer_facing=True)]
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


def build_chapter_provenance_entry(
    chapter_number: int,
    *,
    flow_version: str,
    prose_review_enabled: bool = True,
    draft_commit_enabled: bool = True,
    review_version: str = "post-prose-v1",
    review_issues: list | None = None,
    final_draft_chars: int | None = None,
    first_draft_chars: int | None = None,
    expansion_required: bool | None = None,
    active_frame_id: str | None = None,
    active_formula_node: str | None = None,
    next_active_frame_id: str | None = None,
    next_active_formula_node: str | None = None,
    review_evidence_hash: str | None = None,
) -> dict:
    """纯函数：构建单章 provenance 条目（不落盘）。

    Phase 2 提取共用 Commit 边界——v3 提交边界需要「内存中构造 provenance +
    随 commit 一起原子落盘」；v2 的 record_chapter_provenance 也复用同一构造，
    保证两路条目字节一致（测量/盲审 version-aware 语义不变）。
    """
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
    if review_evidence_hash is None:
        review_evidence_hash = hashlib.sha256(
            json.dumps(
                issues, ensure_ascii=False, sort_keys=True
            ).encode("utf-8")
        ).hexdigest()
    return {
        "chapter_number": chapter_number,
        "flow_version": flow_version,
        "review_version": review_version,
        "prose_review_enabled": bool(prose_review_enabled),
        "draft_commit_enabled": bool(draft_commit_enabled),
        "review_issues": issues,
        "review_evidence_hash": review_evidence_hash,
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
        "next_active_frame_id": next_active_frame_id,
        "next_active_formula_node": next_active_formula_node,
        "committed_at_utc": None,
    }


def merge_chapter_provenance(existing: dict, entry: dict) -> dict:
    """纯函数：把单章条目并入已有 provenance 数据（返回新 dict，不写盘）。

    与原 record_chapter_provenance 的合并语义逐字节一致（保留既有顶层键）。
    """
    data = dict(existing)
    data.setdefault("chapters", {})
    data["chapters"][f"chapter_{entry['chapter_number']}"] = entry
    return data


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

    entry = build_chapter_provenance_entry(
        chapter_number,
        flow_version=flow_version,
        prose_review_enabled=prose_review_enabled,
        draft_commit_enabled=draft_commit_enabled,
        review_version=review_version,
        review_issues=review_issues,
        final_draft_chars=final_draft_chars,
        first_draft_chars=first_draft_chars,
        expansion_required=expansion_required,
        active_frame_id=active_frame_id,
        active_formula_node=active_formula_node,
    )
    data = merge_chapter_provenance(data, entry)
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
