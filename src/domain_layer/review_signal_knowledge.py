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
    # RCC V1：认知劳动分配——证据已完成但后挂解释尾巴（解释过满）。
    # 反向（该说没说）由信息凭证/兑现维度覆盖，不在此类重复。
    ("reader_cognitive_allocation", "medium", "条件性阻断"),
    # CCR V1：人物通过选择显形——独立 family，固定判定序见 Review 维度。
    ("fake_alternative", "medium/high", "条件性阻断"),
    ("cost_free_choice", "medium/high", "条件性阻断"),
    ("agency_outsourced", "medium/high", "条件性阻断"),
    ("choice_not_enacted", "medium/high", "条件性阻断"),
    ("trait_gloss_after_choice", "medium", "通常不阻断"),
    # V1 warning-only：最易主观滥报，不参与 blocking。
    ("generic_protagonist_choice", "low", "仅诊断不阻断"),
    # Dialogue V1：对白作为社会行动——独立 family。
    ("unearned_directness", "medium/high", "条件性阻断"),
    ("objective_unpursued", "medium/high", "条件性阻断"),
    ("flat_tactic", "medium", "条件性阻断"),
    ("no_response_pressure", "medium/high", "条件性阻断"),
    ("subtext_glossed", "medium", "通常不阻断"),
    # V1 warning-only：主观性高，抓"聪明对白但剧情静止"。
    ("no_turn_delta", "low", "仅诊断不阻断"),
    # V1.4：同一已确立命题被多轮复读确认、零新 delta 且阻滞场景推进。
    # 与 no_turn_delta 的边界：主要 delta 已完成后的尾部复述=warning；
    # 循环确认本身阻滞推进=blocking。
    ("dialogue_loop_stasis", "medium/high", "条件性阻断"),
    # V1.5：objective 已完成、确认功能已耗尽后仍继续重复确认同一社会状态。
    # 与 no_turn_delta 的边界：允许一次有功能的确认(warning)；
    # 确认完成后继续重复=blocking。
    ("excessive_redundant_tail", "medium/high", "条件性阻断"),
    # V1.6：命题已获实质确认后，以逐字/高度近似措辞再次重述；
    # 重复形式本身无功能证据（宣读/程序记录/引用纠正/仪式施压/新受众）
    # 即判 blocking——形式性复述损伤独立于语义冗余。
    ("formal_echo_after_ack", "medium/high", "条件性阻断"),
    # V1 warning-only 反向风格哨兵：人人绕说/该问不问/为神秘牺牲清晰度。
    ("subtext_overengineering", "low", "仅诊断不阻断"),
    # --- DFD V1：细节功能密度（dim4 环境/细节） ---
    # 成簇无功能细节枚举（装修清单）：连续多处环境细节均不承担
    # 当前读者任务（定位/行动约束/感官/关系/氛围）= blocking。
    # 判定须满足 realized_current_effect——功能标签不得自证；
    # 共享功能簇（如空间建立镜头共享定位+行动约束）不算无功能。
    ("decorative_inventory", "medium/high", "条件性阻断"),
    # V1.1：功能成立但表达失配——细节确实传达了定位/约束/感官信息，
    # 但以「物件被声明存在」/装修清单式写法落地。与 decorative_inventory
    # 的边界：后者无功能可删，本类有功能但需重写承载方式（rewrite 只改
    # 表达形态，不重选细节对象）。
    ("functional_but_detached", "medium/high", "条件性阻断"),
    # 孤立无功能细节：单个细节删掉读者无损失，但未成簇——warning。
    ("functionless_detail", "low", "仅诊断不阻断"),
    # 细节过载：密度稀释当前读者任务——warning，V1 不硬拦。
    ("detail_overload", "low", "仅诊断不阻断"),
    # --- MN V1：比喻必要性（dim4 显式类比构式） ---
    # 显式比喻（明喻/类比构式）经最强直述替换验证后无任何实质损失——
    # 替换无损 = 比喻不承担必需功能 = blocking。前置 literal_adequacy
    # gate：替换稿不合格（命题/对象丢失、偷换为另一比喻、加新信息、
    # 语境不合）→ not_evaluable，不算必要也不算无必要，不干预。
    # 功能标签（含 affective_load）不拥有保留否决权。
    ("gratuitous_metaphor", "medium/high", "条件性阻断"),
    # 比喻密度过载：仅遥测/warning，MN V1 明确不作阻断依据——密度
    # 不是必要性的替代指标，防以数量代判断。
    ("metaphor_overload", "low", "仅诊断不阻断"),
    # --- dim6a：语义节奏（event-state cadence） ---
    # 事件链（连续动作/位移/程序小句）走完后 narrative_state_delta 八轴
    # 无一实际变化，且链本身不承担 suspense/ritual/characterization/
    # spatial_causality/sensory_buildup/timing 功能，压缩基本无损 → blocking。
    # 与 weak_progression 边界：后者管单元级整体推进，本类管 span 级
    # 「写了很多事但状态没动」。纯空间坐标改变不自动算 state delta。
    ("event_chain_without_state_delta", "medium/high", "条件性阻断"),
    # --- dim7：信息缺口/预测管理（Expectation progression + prediction baseline） ---
    # OPEN 预期的回答/行动已因果到期（当面问到/物证到场/deadline/前置完成/
    # 承诺到点），正文未兑现、无正文真实阻碍、且读者状态未获有效更新
    # （可能性/风险/预测无变化）→ blocking。合法悬念=问题未解但读者
    # 状态有变化；本类=为留悬念推迟本应发生的回答/行动/兑现。
    ("suspense_by_withholding", "medium/high", "条件性阻断"),
    # 发生 reveal/FLIP 但此前读者无 grounded dominant_prediction——
    # 无基线的反转不算 earned surprise。仅报告不自动改写（规划缺陷）。
    ("surprise_without_prediction_baseline", "low", "仅诊断不阻断"),
    # 反转成立依赖 POV/场景逻辑本应可见却被一直藏住的关键前提——
    # 另一种 withholding。仅报告不自动改写。
    ("surprise_requires_hidden_premise", "low", "仅诊断不阻断"),
    # --- dim8a：计划性留白（对已声明 InferenceHandoff 的定向核验） ---
    # 声明留白（explicitness != must_explain）的推断被正文直接陈述/
    # 等价解释——读者预定的推理劳动被取消（太满侧）。只核验 Continue
    # 已声明的交接点；review 不得事后补造留白意图。
    ("blank_inference_made_explicit", "medium/high", "条件性阻断"),
    # 声明留白但正文未交付足以支撑该推断的可见证据——留下的不是
    # 留白而是信息缺失（太少侧）。target 非唯一答案：判合理读者
    # 能否完成 inferential step，不要求唯一解。
    ("blank_under_evidenced", "medium/high", "条件性阻断"),
    # --- dim8b：白描意图（对已声明 DepictionIntent 的定向核验） ---
    # 声明的体验质感被抽象词直接命名且无可观察载体——读者被告知而非
    # 感受到。只核验 Continue 已声明的意图；review 不得事后补造意图。
    ("depiction_named_only", "medium/high", "条件性阻断"),
    # 声明的体验质感在责任 beat 内既未命名也无任何可观察载体——
    # 质感缺席静默通过。owning beat 不在场（合法转线）不误拦。
    ("depiction_absent", "medium/high", "条件性阻断"),
)

# --- 失败类型四层分类（docs/03_rules/08_failure_types.md §4） ---

FAILURE_LAYERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("hard_error", frozenset({
        "fact_conflict", "world_violation", "timeline_error", "information_leak",
    })),
    ("progression_character", frozenset({
        "weak_progression", "character_distortion",
        "motivation_gap", "relationship_jump", "missing_cost",
        "event_chain_without_state_delta",
    })),
    ("structure_promise", frozenset({
        "promise_loss", "abrupt_payoff", "missing_consequence",
        "duplication_of_threads", "suspense_by_withholding",
        "surprise_without_prediction_baseline",
        "surprise_requires_hidden_premise",
    })),
    ("expression_surface", frozenset({
        "redundancy", "style_drift", "generative_indicia",
        "emotion_landing", "interpretive_space", "scene_presence", "dialogue_flat",
        "decorative_inventory", "functionless_detail", "detail_overload",
        "gratuitous_metaphor", "metaphor_overload",
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
