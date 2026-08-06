"""读者体验审查 — 7 维判定标准的纯数据表 + 渲染.

对齐 info_warrant_rules.py 的模式：纯函数访问 + 渲染为 LLM 可理解的指导文本。
数据对应 docs/03_rules/10_reader_experience_rules.md §3（七维判定标准）
与 §4（分级标注体系）。

定位：核心2（读者体验）的审查标准。与核心1（一致性）的失败类型字典
（08_failure_types.md / review_signal_knowledge.py）并行互补——
一致性回答「故事对不对」，本模块回答「好不好看」。
"""

from typing import TypedDict


class ReaderDimensionEntry(TypedDict):
    dimension: str  # 维度标识
    name: str  # 维度名
    definition: str  # 定义
    questions: list[str]  # 判定问题
    good_signals: list[str]  # 达标信号
    weak_signals: list[str]  # 不达标信号
    grade_anchors: dict[str, str]  # good/needs_work/weak 分级锚点


# --- 七维判定标准（docs/03_rules/10_reader_experience_rules.md §3） ---

READER_DIMENSION_RULES: list[ReaderDimensionEntry] = [
    {
        "dimension": "open",
        "name": "开头是否拖沓",
        "definition": "正文开头是否在合理篇幅内让读者进入事件，而非长期停留在环境介绍、人物背景、设定说明",
        "questions": [
            "开头前几段有没有『正在发生、必须马上解决』的事",
            "读者是否已经知道『主角要面对什么』",
            "环境/背景介绍是否被压缩进事件推进中",
        ],
        "good_signals": [
            "前三段内出现一个具体的行动/矛盾/异常",
            "背景信息以『事件中自然暴露』的方式释放",
            "读者第一时间知道：谁、要面对什么、时间紧不紧",
        ],
        "weak_signals": [
            "前三段全是环境描写/人物背景/世界观说明",
            "主角只是『在观察』，没有『在行动』",
            "读者读完开头仍不知道主角要解决什么问题",
        ],
        "grade_anchors": {
            "good": "前 2 段进入事件，背景穿插",
            "needs_work": "前 4-5 段铺垫，事件在中段出现",
            "weak": "前半章都在介绍环境/背景，事件迟迟不来",
        },
    },
    {
        "dimension": "presence",
        "name": "场景是否具有现场感",
        "definition": "读者是否『身临其境』，能通过感官细节、具体动作、人物反应感知场景，而非读一段概述",
        "questions": [
            "关键场景有没有可感知的细节（声音/光线/气味/触感）",
            "人物是否在做具体的事，而不是被抽象描述",
            "叙述是否落在『可体验的瞬间』而非『概括的处境』",
        ],
        "good_signals": [
            "关键动作有感官细节（『那册子砸在桌上，墨汁溅进裂开的指缝』）",
            "情绪通过动作/环境/对白带出",
            "场景有『一个决定性物象』承载氛围（白描/渲染交替）",
        ],
        "weak_signals": [
            "大量『他地位最低』『他过得很不好』式的概述",
            "无感官细节、无具体动作",
            "场景像总结报告而非可体验的画面",
        ],
        "grade_anchors": {
            "good": "关键场景感官细节充分，读者可想象画面",
            "needs_work": "部分场景有细节，关键场景反而概述",
            "weak": "全章以概述为主，无现场感",
        },
    },
    {
        "dimension": "info",
        "name": "解释是否过多",
        "definition": "设定、能力原理、世界观说明是否中断叙事，还是穿插在事件/对话/行动中释放",
        "questions": [
            "有没有『故事停下来解释』的段落",
            "能力/规则说明是否集中在『读者最想看到结果』的时刻",
            "设定信息是否通过角色推演/对白自然带出",
        ],
        "good_signals": [
            "设定信息穿插在冲突推进中释放",
            "关键规则在『需要时』才解释，不提前倾泻",
            "读者最想知道『结果如何』时，不被设定说明打断",
        ],
        "weak_signals": [
            "高潮前插入大段能力原理/世界观说明",
            "同一设定被重复解释两遍以上",
            "事件推进被打断去解释规则",
        ],
        "grade_anchors": {
            "good": "设定自然穿插，不打断关键节奏",
            "needs_work": "有 1-2 处解释打断了节奏，但可接受",
            "weak": "多处集中解释，关键节点被设定说明拖住",
        },
    },
    {
        "dimension": "dialogue",
        "name": "对白是否自然",
        "definition": "对白是否符合人物身份/性格/处境，是否带潜文本，是否承担推进/塑造/冲突之一，字数节奏是否合理",
        "questions": [
            "不同人物的说话方式能否区分",
            "对白是否有潜文本（表面一层、底下另有意图）",
            "对白是否承担塑造人物/推动剧情/制造冲突之一",
            "是否所有人物同一种腔调",
        ],
        "good_signals": [
            "对白贴合身份/性格/处境（贵族、平民、老者、少年各有腔调）",
            "关键对白带潜文本或言外之意",
            "对白有信息量或情绪张力，不只是客套",
        ],
        "weak_signals": [
            "所有人物同一腔调，隐藏人名无法分辨说话者",
            "对白只是解释剧情（『如你所知……』式）",
            "对白全是寒暄客套，无信息无张力",
        ],
        "grade_anchors": {
            "good": "人物可区分，关键对白有潜文本",
            "needs_work": "部分对白性格化，部分模糊",
            "weak": "全章人物腔调统一，对白无张力",
        },
    },
    {
        "dimension": "emotion",
        "name": "情绪是否真正落地",
        "definition": "情绪是否通过身体反应、动作、意象、言外之意呈现，而非『他感到』『他恐惧』式的直白声明",
        "questions": [
            "恐惧/紧张/震惊是否靠身体反应呈现",
            "情绪爆点是否用短句/独立段落硬切",
            "是否避免了『他感到』『涌起一股』等情绪宣布词",
        ],
        "good_signals": [
            "情绪靠动作/身体反应带出（『指节捏得发白』『瞳孔猛地一缩』）",
            "关键情绪用短句独立成段，形成节奏势能",
            "情绪与动作/环境/对白共同呈现，不只靠心理直述",
        ],
        "weak_signals": [
            "大量『他感到恐惧』『他心中涌起怒火』",
            "情绪只靠形容词堆砌，无动作支撑",
            "情绪宣布词密集（深吸一口气/眼眶一热）",
        ],
        "grade_anchors": {
            "good": "情绪靠动作/意象落地，读者可感",
            "needs_work": "部分情绪靠动作，部分直白声明",
            "weak": "情绪主要靠『他感到』式声明，无具象支撑",
        },
    },
    {
        "dimension": "payoff",
        "name": "高潮是否得到反馈",
        "definition": "关键动作/抉择/改写之后，是否给出明确、可感知的结果反馈——读者知道『这事成了/败了/变了』，且后果可见",
        "questions": [
            "主角做了关键选择后，读者是否得到结果反馈",
            "反馈是否具体可感知（文书变字/钟声/异象/代价显现）",
            "是否出现『改完像什么都没发生』的模糊泄劲",
        ],
        "good_signals": [
            "关键动作后有可见反馈（文书上的字变了/墨迹显现/他人口中证实）",
            "结果反馈让读者明确『能力是真的、代价是真的』",
            "反馈同时制造新的悬念或风险（反馈≠彻底了结）",
        ],
        "weak_signals": [
            "关键动作后无任何可感知结果",
            "读者只能猜测『到底成功没有』",
            "悬念不揭晓也没给满足感，爽点被泄掉",
        ],
        "grade_anchors": {
            "good": "关键动作后有明确可感反馈，且带新张力",
            "needs_work": "有反馈但模糊/延迟，读者不确定结果",
            "weak": "关键动作无反馈，读者不知道成败",
        },
    },
    {
        "dimension": "hook",
        "name": "章末钩子是否有足够信息量",
        "definition": "章节末尾是否给读者一个『必须翻页』的理由——悬念半露、信息差、身份揭示、危险迫近，且信息量足以驱动追读",
        "questions": [
            "章末是否扣住一个未解的关键问题",
            "钩子是否传递了『角色知道而读者不知道』或『读者知道危险而角色不知』的信息差",
            "钩子是否只是常规的『有人找上门』而没有信息增量",
        ],
        "good_signals": [
            "章末给出一个发现/转折，但不揭示全貌，留读者自推",
            "用一句神秘话语/异常现象收束，暗示背后更大的存在",
            "钩子传递的信息量足以让读者猜测『接下来会怎样』",
        ],
        "weak_signals": [
            "章末是常规的『调查者出现』『明天见』式收尾",
            "钩子无信息差，读者对下一步没有好奇",
            "章末停在『主角做了一个决定』，但决定不指向未知",
        ],
        "grade_anchors": {
            "good": "钩子含信息差/身份揭示/危险迫近，追读驱动强",
            "needs_work": "有钩子但信息量一般，读者有基本好奇",
            "weak": "章末无钩子或钩子无信息增量",
        },
    },
]


# --- 量化代理信号（docs/03_rules/10_reader_experience_rules.md §5） ---
# 对齐 StyleProfile 量化基线：诚实标注为代理，最终判断结合正文阅读。

QUANTITATIVE_PROXIES: list[dict] = [
    {
        "dimension": "emotion",
        "name": "情绪落地",
        "proxy": "弱化副词密度 / 情绪宣布词计数",
        "source": "style_metrics: weak_adverb_density_per_1000 / emotion_announcement_count",
        "note": "高密度提示情绪靠直白声明而非动作落地（代理，需正文阅读确认）",
    },
    {
        "dimension": "presence",
        "name": "场景现场感",
        "proxy": "景物句占比 / 感官动词密度 / 修饰词负载",
        "source": "style_metrics: scenery_sentence_ratio / sensory_density_per_1000 / modifier_load_density",
        "note": "景物句占比低 + 修饰词负载高 = 白描少、概述多（代理）",
    },
    {
        "dimension": "dialogue",
        "name": "对白自然度",
        "proxy": "对话占比 / 对话标签密度",
        "source": "style_metrics: dialogue_ratio / dialogue_tag_density_per_1000",
        "note": "对话占比高 + 标签密度高 = 对白承担推进但可能标签僵硬（代理）",
    },
    {
        "dimension": "info",
        "name": "解释过多",
        "proxy": "解释腔计数",
        "source": "style_metrics: explanatory_phrase_count",
        "note": "解释腔高（他忽然明白/这意味着）提示设定直给（代理）",
    },
    {
        "dimension": "hook",
        "name": "章末钩子",
        "proxy": "章末段落长度 / 结尾疑问密度",
        "source": "正文末段统计",
        "note": "章末段短促且含疑问/未竟之语 = 钩子信息量可能足（代理）",
    },
]


# --- 渲染函数（LLM prompt 注入） ---


def build_reader_dimension_guidance() -> str:
    """渲染七维判定标准为 LLM 可理解的指导文本（审查 prompt 注入用）."""
    lines: list[str] = []
    for entry in READER_DIMENSION_RULES:
        lines.append(f"## {entry['dimension']} {entry['name']}")
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


def build_reader_quantitative_guidance() -> str:
    """渲染量化代理信号说明（诚实标注为代理，不替代正文阅读）."""
    lines = ["【量化代理信号（仅供辅助证据，需结合正文阅读确认）】"]
    for entry in QUANTITATIVE_PROXIES:
        lines.append(
            f"- {entry['dimension']} {entry['name']}: {entry['proxy']}"
            f"（{entry['note']}）"
        )
    return "\n".join(lines)
