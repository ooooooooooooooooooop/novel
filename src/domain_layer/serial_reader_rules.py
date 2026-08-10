"""连续章/窗口读者审查 — 相邻章 + 窗口判定标准的纯数据表 + 渲染.

对齐 reader_experience_rules.py（单章 7 维）的模式：纯函数访问 + 渲染为
LLM 可理解的指导文本。数据对应 docs/03_rules/10_reader_experience_rules.md
§3.4 的相邻章门禁与三至五章窗口门禁维度。

定位：Q1 Phase 4（单章与滑动窗口读者门禁）的审查标准。与单章 7 维并行——
单章回答「这一章好不看好」，本表回答「连续几章是否连续可信、是否在重复」。

每个维度的判定标准是**可观察机制**而非个人品味：
- good 信号 = 连续阅读感到新鲜/推进/可信；
- weak 信号 = 读者可一眼看出的重复、回退、空转或生成痕迹。
"""

from typing import TypedDict


class SerialReaderDimensionEntry(TypedDict):
    dimension: str  # 维度标识
    name: str  # 维度名
    scope: str  # adjacent（相邻章）/ window（三至五章窗口）
    definition: str  # 定义
    questions: list[str]  # 判定问题
    good_signals: list[str]  # 达标信号
    weak_signals: list[str]  # 不达标信号
    grade_anchors: dict[str, str]  # good/needs_work/weak 分级锚点


# --- 连续阅读判定维度（docs/03_rules/10_reader_experience_rules.md §3.4） ---

SERIAL_READER_DIMENSION_RULES: list[SerialReaderDimensionEntry] = [
    # ------------------------- 相邻章门禁 -------------------------
    {
        "dimension": "reask_resolved",
        "name": "上一章已回答的问题是否被重新提问",
        "scope": "adjacent",
        "definition": "上一章已经给出答案或推进过的问题，是否在下一章又被当作未知重新提问，制造虚假悬念",
        "questions": [
            "上一章揭晓/解决的事实，下一章是否仍被当成未知讨论",
            "角色是否再次为已解决的事感到困惑/惊讶",
            "连续章是否用同一个问题收尾",
        ],
        "good_signals": [
            "上一章已回答的问题在后续作为已知前提被引用",
            "新问题承接已推进的事实，而非回到原点",
        ],
        "weak_signals": [
            "同一个问题连续两章被提问/解答/再提问",
            "角色表现「上一章刚知道的事这一章又不知道」",
        ],
        "grade_anchors": {
            "good": "问题逐章推进，不重复提问",
            "needs_work": "个别处轻微重复，整体在推进",
            "weak": "同一问题被重新提问，读者感到原地踏步",
        },
    },
    {
        "dimension": "reset_without_event",
        "name": "人物/道具/时间/地点是否被无事件重置",
        "scope": "adjacent",
        "definition": "上一章已确立的人物状态、道具身份、时间、地点，是否在没有新事件支撑的情况下被悄悄重置回旧状态",
        "questions": [
            "上一章已找到/已改变状态的人物，下一章是否无事件回到失踪/旧状态",
            "道具（票根/信物/文书）身份是否被无转换地改变",
            "时间/地点是否无标记地回退",
        ],
        "good_signals": [
            "状态变化都有对应的事件与因果",
            "人物/道具状态在连续章间连续",
        ],
        "weak_signals": [
            "已确立的状态被静默回退，无事件解释",
            "连续章读起来像不同时间的片段被拼在一起",
        ],
        "grade_anchors": {
            "good": "状态逐章连续，变化有事件支撑",
            "needs_work": "小处重置但可接受",
            "weak": "无事件状态重置，读者感到时间断裂",
        },
    },
    {
        "dimension": "scene_replay",
        "name": "是否重演上一章已完成的场景",
        "scope": "adjacent",
        "definition": "下一章是否把上一章已经完成/收束的场景（同一地点、同一事件、同一对话）几乎原样再演一遍",
        "questions": [
            "同一场景（同一人物同一对话同一动作）是否连续两章出现",
            "上一章已完成的场景是否有新进展",
            "连续章是否用相同的动作/对话开场",
        ],
        "good_signals": [
            "场景逐章换新落点或从上一场景的余波推进",
            "重复出现的是意象呼应而非事件重演",
        ],
        "weak_signals": [
            "同一事件被连演两遍（电话/顿悟/对峙）",
            "读者能整段跳过下一章开头而不损失信息",
        ],
        "grade_anchors": {
            "good": "场景不重演，承接推进",
            "needs_work": "有呼应但不过度",
            "weak": "场景整体重演，读者感到重复",
        },
    },
    {
        "dimension": "process_text",
        "name": "是否出现「上一章末」「本章」等编辑/生成过程文字",
        "scope": "adjacent",
        "definition": "正文中是否混入编辑/生成过程性文字（章节编号说明、『上一章末』『本章』『接着上一章』等），打破叙事幻觉",
        "questions": [
            "正文是否出现『上一章末』『本章』『上回说到』等元文本",
            "是否出现『第 N 章』等章节编号被当作正文叙述",
            "是否有明显的生成器自我指涉语言",
        ],
        "good_signals": [
            "章节间衔接用叙事内容完成，无元文本",
            "读者不会在正文中读到写作过程的字眼",
        ],
        "weak_signals": [
            "正文出现『上一章末』『本章』等过程文字",
            "出现『接上文』『如前所述』式编辑口吻",
        ],
        "grade_anchors": {
            "good": "无元文本泄漏",
            "needs_work": "个别擦边但非读者可见",
            "weak": "元文本直接进入正文，打断沉浸",
        },
    },
    {
        "dimension": "mechanical_recap",
        "name": "开头是否在机械复述上一章结尾",
        "scope": "adjacent",
        "definition": "本章开头是否逐字/逐场景复述上一章结尾，而非从上一章落点的余波自然续写",
        "questions": [
            "本章开头与上一章结尾是否高度重叠",
            "复述是否带新信息（视角/补充），还是纯机械回放",
            "读者是否必须读完全章才感到有新内容",
        ],
        "good_signals": [
            "开头从上一章落点的余波切入，而非回放",
            "即使提上一章结尾也是带新视角的补充",
        ],
        "weak_signals": [
            "开头整段与上一章结尾重复",
            "纯回放上一章最后场景，无信息增量",
        ],
        "grade_anchors": {
            "good": "开头承接不重复",
            "needs_work": "轻微回放但很快进入新内容",
            "weak": "开头机械复述，读者感到时间没推进",
        },
    },
    # ------------------------- 三至五章窗口门禁 -------------------------
    {
        "dimension": "repeated_insight",
        "name": "是否连续反复使用同一顿悟",
        "scope": "window",
        "definition": "同一条顿悟/认知（『他忽然明白X』）是否在多章反复『重新完成』，而非一次性认知跃迁后转为行动",
        "questions": [
            "同一句顿悟核心（明白/意识到/恍然大悟）是否在窗口内多次出现",
            "同一认知每次都以『顿悟』而非『行为落地』呈现",
            "窗口内是否有一条真正的认知新进展",
        ],
        "good_signals": [
            "认知跃迁一次性发生，后续章节把它当已知前提",
            "顿悟后角色立刻行动，行为承载新认知",
        ],
        "weak_signals": [
            "同一顿悟连续多章重复表述",
            "每章结尾都用『明白了』收束却没有行为推进",
        ],
        "grade_anchors": {
            "good": "顿悟唯一且落地为行为",
            "needs_work": "有呼应但非机械重复",
            "weak": "同一顿悟反复『完成』，读者觉得角色没成长",
        },
    },
    {
        "dimension": "psych_summary_only",
        "name": "是否多章只推进心理总结而无外部变化",
        "scope": "window",
        "definition": "窗口内章节是否只在心理层总结/反思，而外部世界（人物关系、地点、事件、道具）没有任何可见变化",
        "questions": [
            "窗口内是否有至少一处可核对的外部状态变化",
            "章节是否主要是内心独白/总结而非事件",
            "人物是否只『想通了』而没有『做成了什么』",
        ],
        "good_signals": [
            "每章至少推进一个外部可见状态（事件/关系/道具/地点）",
            "心理总结伴随具体行为后果",
        ],
        "weak_signals": [
            "连续多章只有心理活动，外部世界静止",
            "读者能合并多章为一章而不损失事件",
        ],
        "grade_anchors": {
            "good": "心理与外部变化并行",
            "needs_work": "外部推进偏弱但存在",
            "weak": "多章纯心理总结，叙事空转",
        },
    },
    {
        "dimension": "repeated_ending",
        "name": "是否反复使用同一种结尾结构",
        "scope": "window",
        "definition": "窗口内章节是否用同一种结尾结构收束（同样的悬念句式、同样的『有人找上门』、同样的决定式收尾），造成节奏单一",
        "questions": [
            "多章结尾是否用同一种结构（如都在决定后停笔）",
            "结尾悬念是否只是换皮（换个名字/地点）的同一招",
            "窗口内结尾结构的多样性如何",
        ],
        "good_signals": [
            "结尾结构多样化（悬念/揭示/危险/余波交替）",
            "同类结尾之间间隔足够，不显重复",
        ],
        "weak_signals": [
            "窗口内每章都用同一结构收尾",
            "读者能预测下一章结尾形式",
        ],
        "grade_anchors": {
            "good": "结尾结构多样",
            "needs_work": "有偏好但非机械重复",
            "weak": "反复同一结尾结构，节奏僵化",
        },
    },
    {
        "dimension": "expectation_stall",
        "name": "ReaderExpectation 是否真正推进",
        "scope": "window",
        "definition": "读者正在等的关键问题（伏笔对应的读者预期）在窗口内是否有实质推进，还是长期搁置只吊不答",
        "questions": [
            "窗口内读者最关心的悬念是否被推进（新线索/新进展/部分揭示）",
            "高优先读者预期是否长期无推进而变拖延/陈旧",
            "窗口是否只在边缘问题打转而不碰主线",
        ],
        "good_signals": [
            "窗口内至少一条高优先读者预期被推进",
            "悬念推进与外部变化绑定",
        ],
        "weak_signals": [
            "窗口内主线悬念零推进",
            "高优先预期进入拖延/失去吸引力但仍不处理",
        ],
        "grade_anchors": {
            "good": "主线悬念窗口内有实质推进",
            "needs_work": "推进偏慢但存在",
            "weak": "悬念只吊不答，读者耐心流失",
        },
    },
    {
        "dimension": "narrowing_methods",
        "name": "主角解决问题方式是否越来越单一",
        "scope": "window",
        "definition": "窗口内主角解决冲突的方式是否越来越依赖同一种手段（都靠嘴炮/都靠能力硬解/都靠求助），办法空间在收窄",
        "questions": [
            "窗口内主角解决冲突的方式是否趋同",
            "同一种解法（说服/硬闯/求助/隐忍）是否被反复使用",
            "是否每次难题都碰巧用同一种手段解决",
        ],
        "good_signals": [
            "解法随情境变化，动用不同资源",
            "同一手段被使用时有新代价或反制",
        ],
        "weak_signals": [
            "所有冲突都靠同一种手段解决",
            "解法没有变化也没有代价，读者失去紧张感",
        ],
        "grade_anchors": {
            "good": "解法随情境多样",
            "needs_work": "有偏好但未被看穿",
            "weak": "办法单一，冲突失去张力",
        },
    },
    {
        "dimension": "pleasure_dilution",
        "name": "原作阅读快感是否被生成文本自身逐步稀释",
        "scope": "window",
        "definition": "窗口内生成文本是否逐步把原作的核心阅读快感（紧凑对抗/克制留白/细节质感）稀释成平均化文本，而不是保持或推进",
        "questions": [
            "窗口内文本是否越来越『套路化』（通用词/通用场景/通用节奏）",
            "原作的核心快感机制（对抗张力/细节质感/潜文本）是否在衰减",
            "生成文本是否自身在制造同质化，而非维持原作味道",
        ],
        "good_signals": [
            "窗口内保持原作的核心快感机制",
            "新章与原作在节奏/质感上同源",
        ],
        "weak_signals": [
            "文本越来越像通用网文模板",
            "核心快感（张力/细节/潜文本）逐步消失",
        ],
        "grade_anchors": {
            "good": "快感机制保持",
            "needs_work": "轻微稀释但可感知到原作",
            "weak": "已稀释成平均文本，与原作快感脱节",
        },
    },
    {
        "dimension": "contract_drift",
        "name": "是否偏离 ReaderContract 声明的核心阅读机制",
        "scope": "window",
        "definition": "窗口内文本是否偏离该作品读者契约声明的核心阅读快感/禁止漂移（如『商业主角必须通过具体判断和行动展现聪明』却被写成靠运气/靠设定），或触发 forbidden_drifts",
        "questions": [
            "窗口内是否触发了读者契约禁止的漂移",
            "核心阅读快感是否被偏离（如克制感被写成煽情）",
            "主角的表现方式是否符合契约声明的方式",
        ],
        "good_signals": [
            "文本符合契约的核心阅读机制",
            "禁止漂移未被触发",
        ],
        "weak_signals": [
            "契约禁止的漂移出现",
            "核心快感被换成另一种更省力的写法",
        ],
        "grade_anchors": {
            "good": "契合契约核心机制",
            "needs_work": "小处偏离但整体契合",
            "weak": "明显偏离契约，读者选的『这本书』被写成别的东西",
        },
    },
]


# --- 渲染函数（LLM prompt 注入） ---


def build_serial_reader_dimension_guidance(scope: str | None = None) -> str:
    """渲染相邻章/窗口判定标准为 LLM 可理解的指导文本.

    scope 限定为 "adjacent"（只渲染相邻章维度）或 "window"（只渲染窗口维度）；
    缺省渲染全部 12 维。
    """
    lines: list[str] = []
    for entry in SERIAL_READER_DIMENSION_RULES:
        if scope is not None and entry["scope"] != scope:
            continue
        lines.append(f"## {entry['dimension']} {entry['name']}（{entry['scope']}）")
        lines.append(f"- 定义: {entry['definition']}")
        lines.append("- 判定问题:")
        lines.extend(f"  - {q}" for q in entry["questions"])
        lines.append("- 达标信号:")
        lines.extend(f"  - {s}" for s in entry["good_signals"])
        lines.append("- 不达标信号:")
        lines.extend(f"  - {s}" for s in entry["weak_signals"])
        lines.append("- 分级锚点:")
        for grade, anchor in entry["grade_anchors"].items():
            lines.append(f"  - {grade}: {anchor}")
    return "\n".join(lines)
