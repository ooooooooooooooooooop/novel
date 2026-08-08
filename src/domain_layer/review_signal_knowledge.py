"""审查信号知识 — 弱信号检测的纯数据表.

对齐 info_warrant_knowledge.py 的模式：纯数据表，不包含任何检测逻辑，
供 review_signals.py（检测器）消费。

内容迁移自原 src/workflow_action/review.py 顶部的触发词表与失败类型字典
（重构解耦：review.py 只做编排，弱信号检测拆到 domain_layer）。
迁移时逐字保留，不改任何字符串——保证 issue_id / severity / description
与解耦前完全一致（零回归契约）。
"""

from typing import TypedDict


class GenerativeMarkerSet(TypedDict):
    sudden_transitions: frozenset[str]
    over_modifiers: frozenset[str]
    emotional_stacking: frozenset[str]


# --- 决策依据检查的"决策动作触发词"（出现在 goal/conflict 才检查回溯性） ---

AGENCY_TRIGGERS: frozenset[str] = frozenset({
    "答应", "拒绝", "决定", "选择", "放弃", "背叛", "归顺", "妥协",
    "出手", "收手", "立誓", "投靠", "反叛", "认罪", "放过", "杀掉",
    "救下", "改投", "投降", "屈服", "反击",
})

# --- 信息凭证检查（iss_info_*）——
# 亲历前提豁免词：命中表示该处已补上"确实有人到过场"的亲历前提，
# 转述+亲历细节共现不再视为凭证断裂（诚实区分"事故"与"已补前提"）。 ---

FIRSTHAND_WITNESS_MARKERS: frozenset[str] = frozenset({
    "亲眼", "亲耳", "亲口", "亲眼所见", "远远看过", "去看过", "见过一面",
    "到场", "见过", "当面", "在面前", "当场",
})

# --- B 档（08_failure_types 弱信号）：8 个失败类型的触发词表（对象层代理信号）。
# 命中仅是"可能"，正式判断由 review prompt 的 LLM 承担；词表按语义分组，
# 与文档定义的失败类型一一对应，语义细节见各规则注释。 ---

MOTIVATION_JUMP_MARKERS: frozenset[str] = frozenset({
    # 态度/立场突然转向，缺决策依据 → motivation_gap
    "突然信任", "突然坦白", "突然合作", "突然原谅", "突然投靠", "突然归顺",
    "放下戒备", "吐露心声", "开始信任", "接受道歉", "欣然同意", "一口答应",
})

RELATIONSHIP_JUMP_MARKERS: frozenset[str] = frozenset({
    # 关系性质跃迁，缺桥接 → relationship_jump
    "宿敌和解", "托付秘密", "确认关系", "结为同盟", "生死之交", "化敌为友",
    "放下仇恨", "义结金兰", "以身相许", "冰释前嫌", "握手言和", "推心置腹",
})

HIGH_RISK_MARKERS: frozenset[str] = frozenset({
    # 高风险/越界行为，缺代价 → missing_cost
    "越阶", "越级", "动用禁术", "强行突破", "强行越界", "违逆", "违背禁令",
    "闯禁区", "以命相搏", "透支", "燃烧寿元", "孤注一掷",
})

COST_MARKERS: frozenset[str] = frozenset({
    "代价", "付出", "损失", "惩罚", "反噬", "反扑", "耗尽", "重伤", "折寿",
    "受罚", "牺牲", "失去", "付出代价",
})

PAYOFF_MARKERS: frozenset[str] = frozenset({
    # 揭晓/反转触发词 → abrupt_payoff
    "真相大白", "终于明白", "恍然大悟", "水落石出", "揭晓", "真相是",
    "原来如此", "真凶", "谜底",
})

# --- B 档：失败类型字典（源自 docs/03_rules/08_failure_types.md §10 默认严重度 /
# §11 阻断倾向），注入审查 prompt 供 LLM 对齐 issue_type 词汇。 ---

FAILURE_TYPE_LEXICON: tuple[tuple[str, str, str], ...] = (
    ("fact_conflict", "high/critical", "默认阻断"),
    ("world_violation", "high/critical", "默认阻断"),
    ("timeline_error", "high/critical", "默认阻断"),
    ("character_distortion", "high", "条件性阻断"),
    ("information_leak", "high", "条件性阻断"),
    ("abrupt_payoff", "medium/high", "条件性阻断"),
    ("motivation_gap", "medium/high", "通常不阻断"),
    ("relationship_jump", "medium/high", "通常不阻断"),
    ("weak_progression", "medium", "通常不阻断"),
    ("missing_cost", "medium/high", "通常不阻断"),
    ("promise_loss", "medium/high", "通常不阻断"),
    ("missing_consequence", "medium", "通常不阻断"),
    ("duplication_of_threads", "medium", "通常不阻断"),
    ("redundancy", "low/medium", "通常不阻断"),
    ("style_drift", "low/medium", "通常不阻断"),
    ("generative_indicia", "low/medium", "通常不阻断"),
    # 正文层（post-prose Review 有【本章正文】可读时新增的判定维度）：
    # 方向文档第五节的 7 维正文审查（兑现/人物/情绪/解读空间/在场/对白/AI味）。
    ("emotion_landing", "low/medium", "通常不阻断"),
    ("interpretive_space", "low/medium", "通常不阻断"),
    ("scene_presence", "low/medium", "通常不阻断"),
    ("dialogue_flat", "low/medium", "通常不阻断"),
)

# --- 失败类型四层分类（docs/03_rules/08_failure_types.md §4） ---

FAILURE_LAYERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("hard_error", frozenset({
        "fact_conflict", "world_violation", "timeline_error", "information_leak",
    })),
    ("progression_character", frozenset({
        "weak_progression", "character_distortion",
        "motivation_gap", "relationship_jump", "missing_cost",
    })),
    ("structure_promise", frozenset({
        "promise_loss", "abrupt_payoff", "missing_consequence",
        "duplication_of_threads",
    })),
    ("expression_surface", frozenset({
        "redundancy", "style_drift", "generative_indicia",
        "emotion_landing", "interpretive_space", "scene_presence", "dialogue_flat",
    })),
)

# --- 伏笔关键词提取停用词（_foreshadow_keywords 用） ---

FORESHADOW_STOPWORDS: frozenset[str] = frozenset(
    (
        "的", "了", "是", "说", "在", "有", "和", "与", "就", "都", "也",
        "不", "没", "会", "要", "能", "把", "被", "让", "那", "这",
        "他", "她", "你", "我", "们", "一个", "什么", "怎么", "为什么",
        "它", "上", "下", "里", "时", "后", "前", "再", "又", "还", "只",
    )
)

# --- generative_indicia 启发式检测词（iss_genind_*） ---

GENERATIVE_MARKERS: GenerativeMarkerSet = {
    "sudden_transitions": frozenset({"突然", "瞬间", "猛然", "骤然", "蓦地"}),
    "over_modifiers": frozenset({
        "不可置信地", "难以置信地", "不由自主地", "下意识地",
    }),
    "emotional_stacking": frozenset({
        "崩溃", "绝望", "疯狂", "撕心裂肺", "肝肠寸断",
    }),
}
