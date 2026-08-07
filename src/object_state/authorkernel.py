"""AuthorKernel — 作者长期选择结构 / 价值边界（作者性第四工作包 §24-26）.

定位：与 TimeBook 同类——sidecar spec，不进 serialization.py 状态机层。
**必须从 ChoiceLedger 压缩出来，禁止人工创建（禁止 3）**——「你是一个克制、
真实、深刻的作者」只是 Persona Prompt，没有行为价值。

schema 六部（§25）：
- Values            : 长期反复支持的选择（character_causality_over_plot_convenience）
- Prohibitions      : 长期反复拒绝的（不允许角色突然知道不该知道的 / 不允许一次道歉
                      修复长期创伤 / 不允许为煽情替人物总结人生 / 不允许解释场景已能
                      表达的情绪）
- Commitments       : 过去创作已制造的长期承诺（A与B的关系修复必须靠持续行动）
- Tensions          : 内部未解决的冲突（克制 vs 高潮需要释放）——不能强行解决，显式保留
- Attention Biases  : 习惯首先注意什么（权力关系变化 / 普通物品里的时间痕迹）
- Interpretive Biases: 通常怎么解释事件（冲突先从利益结构理解而非善恶）

每条原则（§26）：principle_id / description / strength / plasticity /
supporting_choices / counterexamples / first_formed_at / last_reinforced /
last_challenged / confidence / status（candidate→weak→stable→contested→deprecated，
不是 true/false）。

防编造（禁止 10）：原则必须（a）映射到受限价值词汇表（VALUE_VOCAB），
（b）附 supporting_choices 引用，（c）必须产出 counterexamples，
（d）反例过多自动降级 contested。不能模型说一句「我相信……」就当它真形成了价值
——行为证据优先。

Drift / Growth 区分（§27/§43）：Drift=没有相关新经历/没有明确 tradeoff/没有新价值
冲突但输出突然大变（要防）；Growth=旧原则遭遇长期反例→产生 tension→多次选择开始
改变→形成新稳定边界（要允许）。

隐私：含作品语境（supporting_choices 引作品内 decision_id），sidecar 存本地
gitignored；风格库可入库但只放中性方法论。
"""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

KernelStatus = Literal["candidate", "weak", "stable", "contested", "deprecated"]
PrincipleCategory = Literal[
    "value",
    "prohibition",
    "commitment",
    "tension",
    "attention_bias",
    "interpretive_bias",
]

# ---------------------------------------------------------------------------
# 受限价值词汇表（禁止 10 防编造的锚点）
# 原则的 vocab_key 必须命中此表；词汇来自纲领 §1/§25/§26 的核心例子，
# 中性方法论语义（不绑定任何具体作品）。
# ---------------------------------------------------------------------------
VALUE_VOCAB: tuple[str, ...] = (
    # 价值 / 禁忌类（Value / Prohibition）
    "character_causality_over_plot_convenience",  # 角色因果 > 剧情便利（§23 核心教训）
    "trust_earned_over_time",                      # 信任靠持续行动，不靠一次坦白
    "no_instant_forgiveness",                      # 不相信一次道歉能修复长期创伤
    "no_unearned_sudden_competence",               # 宁可降爽感也不让人物突然变聪明
    "no_externalized_summary_of_pain",             # 拒绝替人物总结痛苦
    "no_unresolved_then_ignore",                   # 不制造 unresolved 却不接住
    "information_permission",                      # 人物只能知道该知道的（信息权限）
    "power_relations_sensitive",                   # 对权力关系变化极度敏感
    "autonomy_over_coercion",                      # 尊重自主 > 强迫/操纵
    "consequence_visible",                         # 选择必须有可见后果（含代价）
    "reader_handholding_prohibited",               # 不替读者总结主题/不点破象征
    "costly_taste_tolerated",                      # 愿为内部选择牺牲外部即时奖励
    # 承诺类（Commitment）
    "commitment_consistency",                      # 已制造的长期承诺不能下章想改就改
    # 张力类（Tension）
    "restraint_vs_release",                        # 克制 vs 高潮需要释放
    "character_realism_vs_density",                # 人物真实 vs 平台高密度爽点
    # 注意偏置类（Attention Bias）
    "attend_power_dynamics",                       # 注意权力/地位关系变化
    "attend_objects_in_time",                      # 注意普通物品里的时间痕迹
    "attend_avoidance_in_expression",              # 注意角色如何逃避直接表达
    "attend_action_behavior_gap",                  # 注意言行不一致
    # 解释偏置类（Interpretive Bias）
    "interpret_via_interest_structure",            # 冲突先从利益结构理解而非善恶
    "interpret_silence_as_behavior",               # 沉默首先理解为行为而非缺对白
    "interpret_change_with_history",               # 变化必须从选择史理解，不能凭空突变
)

# 类别 → 词汇子集（Consolidation 归纳时按类别限定候选词汇，防串类）
_CATEGORY_VOCAB: dict[PrincipleCategory, tuple[str, ...]] = {
    "value": (
        "character_causality_over_plot_convenience",
        "trust_earned_over_time",
        "autonomy_over_coercion",
        "consequence_visible",
        "costly_taste_tolerated",
    ),
    "prohibition": (
        "no_instant_forgiveness",
        "no_unearned_sudden_competence",
        "no_externalized_summary_of_pain",
        "no_unresolved_then_ignore",
        "information_permission",
        "reader_handholding_prohibited",
    ),
    "commitment": ("commitment_consistency",),
    "tension": ("restraint_vs_release", "character_realism_vs_density"),
    "attention_bias": (
        "attend_power_dynamics",
        "attend_objects_in_time",
        "attend_avoidance_in_expression",
        "attend_action_behavior_gap",
    ),
    "interpretive_bias": (
        "interpret_via_interest_structure",
        "interpret_silence_as_behavior",
        "interpret_change_with_history",
    ),
}

# 每个词汇键的一句话中性描述（渲染/报告用；不含作品语境）
VALUE_VOCAB_DESCRIPTIONS: dict[str, str] = {
    "character_causality_over_plot_convenience": "角色因果优先于剧情便利",
    "trust_earned_over_time": "信任靠持续行动建立，不靠一次坦白",
    "no_instant_forgiveness": "不允许一次道歉修复长期创伤",
    "no_unearned_sudden_competence": "宁可降爽感也不让人物突然变聪明",
    "no_externalized_summary_of_pain": "拒绝替人物总结痛苦",
    "no_unresolved_then_ignore": "不制造未决却不接住",
    "information_permission": "人物只能知道该知道的",
    "power_relations_sensitive": "对权力关系变化敏感",
    "autonomy_over_coercion": "尊重自主优先于强迫",
    "consequence_visible": "选择必须有可见后果与代价",
    "reader_handholding_prohibited": "不替读者总结主题",
    "costly_taste_tolerated": "愿为内部选择牺牲外部即时奖励",
    "commitment_consistency": "已制造的承诺不随意推翻",
    "restraint_vs_release": "克制与高潮释放的张力",
    "character_realism_vs_density": "人物真实与平台爽点密度的张力",
    "attend_power_dynamics": "注意权力与地位关系变化",
    "attend_objects_in_time": "注意普通物品里的时间痕迹",
    "attend_avoidance_in_expression": "注意角色如何逃避直接表达",
    "attend_action_behavior_gap": "注意言行不一致",
    "interpret_via_interest_structure": "冲突先从利益结构理解",
    "interpret_silence_as_behavior": "沉默首先理解为行为",
    "interpret_change_with_history": "变化必须从选择史理解",
}

# 每个词汇键的典型正/反关键词（离线代理：从 ChoiceRecord tradeoff/理由文本
# 做确定性映射，供 Consolidation 归纳与检索；非 LLM，诚实标注是启发式代理）。
# 映射到受限词汇表本身已是防编造的第一道闸：模型输出必须先落到这些键。
VALUE_VOCAB_KEYWORDS: dict[str, tuple[str, ...]] = {
    "character_causality_over_plot_convenience": ("角色因果", "人物因果", "剧情便利", "强行"),
    "trust_earned_over_time": ("信任", "坦白", "托付", "持续行动"),
    "no_instant_forgiveness": ("道歉", "原谅", "创伤", "修复"),
    "no_unearned_sudden_competence": ("突然变聪明", "开窍", "顿悟", "能力跃升"),
    "no_externalized_summary_of_pain": ("总结痛苦", "替人物总结", "煽情"),
    "no_unresolved_then_ignore": ("未决", "悬而未决", "unresolved"),
    "information_permission": ("信息权限", "不该知道", "越权知情", "信息差"),
    "power_relations_sensitive": ("权力", "地位", "权势", "从属"),
    "autonomy_over_coercion": ("强迫", "自主", "操纵", "绑架", "替人决定"),
    "consequence_visible": ("代价", "后果", "责任", "反噬"),
    "reader_handholding_prohibited": ("总结主题", "点破", "象征解释", "说教"),
    "costly_taste_tolerated": ("放弃", "牺牲", "损失", "换取", "性价比"),
    "commitment_consistency": ("承诺", "背弃", "食言", "坚持"),
    "restraint_vs_release": ("克制", "释放", "压抑", "爆发"),
    "character_realism_vs_density": ("真实", "密度", "爽点", "节奏"),
    "attend_power_dynamics": ("上位", "下位", "翻身", "仰视", "掌控"),
    "attend_objects_in_time": ("物件", "信物", "旧物", "痕迹", "时光"),
    "attend_avoidance_in_expression": ("回避", "逃避", "转移话题", "不接话"),
    "attend_action_behavior_gap": ("言行不一", "说一套做一套", "表里不一"),
    "interpret_via_interest_structure": ("利益", "立场", "利害", "结构"),
    "interpret_silence_as_behavior": ("沉默", "不语", "缄默", "没说话"),
    "interpret_change_with_history": ("铺垫", "由头", "经历", "转变", "来由"),
}

# 方向关键词（§23 教训：归纳必须挖到方向层，不能只命中关键词）。
# 「剧情便利优先」和「角色因果优先」都含 character_causality 相关字面，
# 但方向相反。PRO = 文本表达了「符合/保护该价值」；CONTRA = 表达了
# 「违反/牺牲该价值」。tension / attention_bias / interpretive_bias 是方向
# 无关键（注意什么/怎么解释，没有正反之分），只做触及判断（触及即 pro）。
VALUE_VOCAB_PRO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "character_causality_over_plot_convenience": (
        "角色因果优先", "人物因果优先", "忠于人物", "人物一致性", "按自己的执念", "人物会这样",
    ),
    "trust_earned_over_time": (
        "持续行动", "一次次证明", "日积月累", "长期行动", "慢慢赢得",
    ),
    "no_instant_forgiveness": (
        "不肯原谅", "无法原谅", "没有原谅", "伤口还在", "信任已经碎了",
    ),
    "no_unearned_sudden_competence": (
        "能力是练出来的", "慢慢成长", "吃过亏才懂", "不让他突然变聪明",
    ),
    "no_externalized_summary_of_pain": (
        "不总结痛苦", "只写动作", "不点破", "让痛苦自己说话",
    ),
    "no_unresolved_then_ignore": (
        "接住", "回头处理", "给出交代", "不回避",
    ),
    "information_permission": (
        "信息权限", "只能知道", "不该知道", "守口如瓶", "不知情",
    ),
    "power_relations_sensitive": (
        "权力关系", "上位", "下位", "地位变化", "掌控关系",
    ),
    "autonomy_over_coercion": (
        "尊重自主", "给对方选择", "不强迫", "允许拒绝", "尊重决定",
    ),
    "consequence_visible": (
        "代价", "反噬", "承担责任", "付出代价", "看见后果",
    ),
    "reader_handholding_prohibited": (
        "不点破", "留给读者", "不解释象征", "留白",
    ),
    "costly_taste_tolerated": (
        "放弃", "牺牲", "损失", "换取", "宁可",
    ),
    "commitment_consistency": (
        "坚持承诺", "守约", "兑现", "不背弃",
    ),
}

VALUE_VOCAB_CONTRA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "character_causality_over_plot_convenience": (
        "剧情便利优先", "剧情需要", "强行推进", "为剧情服务", "方便起见",
    ),
    "trust_earned_over_time": (
        "一次坦白", "一句承诺", "三言两语", "当场信任", "立即信任",
    ),
    "no_instant_forgiveness": (
        "当场原谅", "一次道歉", "道歉就修复", "瞬间原谅", "马上原谅", "原谅一切",
    ),
    "no_unearned_sudden_competence": (
        "突然变聪明", "开窍", "顿悟", "能力跃升", "一下就会了", "无师自通",
    ),
    "no_externalized_summary_of_pain": (
        "总结痛苦", "替人物总结", "煽情", "总结人生",
    ),
    "no_unresolved_then_ignore": (
        "悬而未决", "未决", "不了了之", "一笔带过",
    ),
    "information_permission": (
        "越权知情", "突然知道", "偷听到一切", "全知全能",
    ),
    "power_relations_sensitive": (
        "无视地位", "人人平等无差别",
    ),
    "autonomy_over_coercion": (
        "强迫", "操纵", "绑架", "替人决定", "逼着",
    ),
    "consequence_visible": (
        "没有后果", "毫无代价", "不了了之",
    ),
    "reader_handholding_prohibited": (
        "总结主题", "点破", "象征解释", "说教", "替读者总结",
    ),
    "costly_taste_tolerated": (
        "求稳", "性价比", "全都要", "两全其美",
    ),
    "commitment_consistency": (
        "背弃", "食言", "说改就改", "推翻承诺",
    ),
}


def value_direction(text: str, vocab_key: str) -> Optional[str]:
    """判断文本相对某价值键的方向：pro=符合/保护，contra=违反/牺牲，None=未触及.

    方向无关键（tension/attention_bias/interpretive_bias）无正反之分：
    命中 PRO 或合并关键词即视为 pro（表达了该注意/解释倾向）。
    """
    if not text:
        return None
    pro = VALUE_VOCAB_PRO_KEYWORDS.get(vocab_key, ())
    contra = VALUE_VOCAB_CONTRA_KEYWORDS.get(vocab_key, ())
    pro_hit = any(kw in text for kw in pro if kw)
    contra_hit = any(kw in text for kw in contra if kw)
    if contra_hit and not pro_hit:
        return "contra"
    if pro_hit or any(kw in text for kw in VALUE_VOCAB_KEYWORDS.get(vocab_key, ()) if kw):
        return "pro"
    return None


class AuthorPrinciple(BaseModel):
    """一条作者原则（§26）——必须映射受限词汇表 + 行为证据引用."""

    model_config = ConfigDict(extra="forbid")

    principle_id: str = Field(description="原则唯一标识（如 val_char_causality_001）")
    category: PrincipleCategory = Field(description="六部之一")
    vocab_key: str = Field(
        description="映射到受限价值词汇表（禁止 10 防编造第一道闸）"
    )
    description: str = Field(description="原则描述（中性方法论语义）")
    strength: float = Field(
        default=0.5, ge=0, le=1, description="强度 0-1（支持证据占比）"
    )
    plasticity: float = Field(
        default=0.5, ge=0, le=1, description="可塑性 0-1（越大越易被反例改变）"
    )
    supporting_choices: list[str] = Field(
        default_factory=list,
        description="支撑本原则的 ChoiceRecord.decision_id 列表（行为证据，禁止 10）",
    )
    counterexamples: list[str] = Field(
        default_factory=list,
        description="反例 decision_id 列表（反例过多自动降级 contested）",
    )
    first_formed_at: str = Field(description="首次形成时刻（ISO）")
    last_reinforced: Optional[str] = Field(default=None, description="最近一次被支持")
    last_challenged: Optional[str] = Field(default=None, description="最近一次被挑战")
    confidence: float = Field(
        default=0.5, ge=0, le=1, description="置信度 0-1（行为证据量）"
    )
    status: KernelStatus = Field(
        default="candidate",
        description="candidate→weak→stable→contested→deprecated（不是 true/false）",
    )

    @field_validator("principle_id", "description", "first_formed_at")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("vocab_key")
    @classmethod
    def _vocab_key_must_be_known(cls, value: str, info: ValidationInfo) -> str:
        if value not in VALUE_VOCAB:
            raise ValueError(
                f"vocab_key must map to the restricted value vocabulary, got {value!r}"
            )
        return value

    @field_validator("supporting_choices", "counterexamples")
    @classmethod
    def _refs_must_be_non_blank(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


class AuthorKernel(BaseModel):
    """作者长期选择结构（§25 六部）——必须从 ChoiceLedger 压缩出来（禁止 3）."""

    model_config = ConfigDict(extra="forbid")

    kernel_id: str = Field(description="内核唯一标识")
    schema_version: int = Field(default=1, ge=1)
    style_profile_id: Optional[str] = Field(
        default=None,
        description="关联的风格档案 id（内核是『这个作者』的选择层，与文风层并列）",
    )
    values: list[AuthorPrinciple] = Field(default_factory=list)
    prohibitions: list[AuthorPrinciple] = Field(default_factory=list)
    commitments: list[AuthorPrinciple] = Field(default_factory=list)
    tensions: list[AuthorPrinciple] = Field(default_factory=list)
    attention_biases: list[AuthorPrinciple] = Field(default_factory=list)
    interpretive_biases: list[AuthorPrinciple] = Field(default_factory=list)
    last_consolidation: Optional[str] = Field(
        default=None, description="最近一次 Consolidation 时刻"
    )
    status: Literal["empty", "forming", "formed"] = Field(
        default="empty",
        description="empty：无原则；forming：有候选；formed：有稳定/弱原则",
    )

    def all_principles(self) -> list[AuthorPrinciple]:
        """六部平铺（渲染/打分用）."""
        return (
            self.values
            + self.prohibitions
            + self.commitments
            + self.tensions
            + self.attention_biases
            + self.interpretive_biases
        )

    def principles_by_category(self, category: PrincipleCategory) -> list[AuthorPrinciple]:
        return list(getattr(self, _CATEGORY_FIELD[category]))

    @model_validator(mode="after")
    def _derive_status_from_content(self) -> "AuthorKernel":
        """status 由内容派生：无原则=empty；有 stable/weak=formed；否则 forming."""
        principles = self.all_principles()
        if not principles:
            self.status = "empty"
        elif any(p.status in ("stable", "weak") for p in principles):
            self.status = "formed"
        else:
            self.status = "forming"
        return self


_CATEGORY_FIELD: dict[PrincipleCategory, str] = {
    "value": "values",
    "prohibition": "prohibitions",
    "commitment": "commitments",
    "tension": "tensions",
    "attention_bias": "attention_biases",
    "interpretive_bias": "interpretive_biases",
}


def principle_id_for(category: PrincipleCategory, vocab_key: str, seq: int) -> str:
    """生成中性原则 id：类别前缀 + 词汇键 + 序号."""
    prefix = {
        "value": "val",
        "prohibition": "pro",
        "commitment": "com",
        "tension": "ten",
        "attention_bias": "att",
        "interpretive_bias": "int",
    }[category]
    slug = vocab_key.replace("_", "")
    return f"{prefix}_{slug}_{seq:03d}"
