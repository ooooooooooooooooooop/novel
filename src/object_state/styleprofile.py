"""StyleProfile — 写作风格档案定义.

StyleProfile 是"作品要成为什么"的风格规格（与 WorkSpec 同类），
不是叙事状态。它不进入 NarrativeState/Frame/FactLedger 状态机。

由 style_short_form 从已有小说文本提炼（量化 + LLM 质性合并），
持久化为 style_profile.json，以 to_prompt_context() 注入续写 prompt。
"""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_non_blank_items(values: list[str], field_name: str) -> list[str]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} entries must be non-empty")
    return values


class MetaphorHit(BaseModel):
    """单一喻体的重复命中."""

    model_config = ConfigDict(extra="forbid")

    vehicle: str = Field(description="喻体, 如'潮水'")
    count: int = Field(ge=1, description="出现次数")
    sample_snippets: list[str] = Field(
        default_factory=list, description="2-3 条出现样例, 供人工复核"
    )

    @field_validator("vehicle")
    @classmethod
    def _vehicle_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("sample_snippets")
    @classmethod
    def _snippets_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        return _require_non_blank_items(values, info.field_name)


class StyleRisk(BaseModel):
    """AI 味或风格漂移风险."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="命中规则标识, 如 ai_weak_adverb_density")
    category: Literal["ai_flavor", "style_drift"] = Field(
        description="风险类别: ai_flavor=AI味, style_drift=风格漂移"
    )
    measure: str = Field(description="指标描述, 如'弱化副词密度'")
    value: float = Field(description="实测值")
    threshold: float = Field(description="阈值")
    severity: Literal["low", "warning", "blocking"] = Field(
        description="严重等级"
    )
    description: str = Field(description="风险描述")

    @field_validator("rule_id", "measure", "description")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class StyleQuantitativeStats(BaseModel):
    """纯代码量化统计（无需 LLM）."""

    model_config = ConfigDict(extra="forbid")

    total_chars: int = Field(ge=0, description="总字数")
    sentence_count: int = Field(ge=0, description="句子总数")
    avg_sentence_len: float = Field(ge=0, description="平均句长（字符/句）")
    short_sentence_ratio: float = Field(
        ge=0, le=1, description="短句占比（≤8字）"
    )
    long_sentence_ratio: float = Field(
        ge=0, le=1, description="长句占比（≥30字）"
    )
    dialogue_ratio: float = Field(ge=0, le=1, description="含引号句子占比")
    weak_adverb_density_per_1000: float = Field(
        ge=0, description="弱化副词密度（每千字）"
    )
    weak_adverb_counts: dict[str, int] = Field(
        default_factory=dict, description="各弱化副词计数"
    )
    metaphor_repeats: list[MetaphorHit] = Field(
        default_factory=list, description="重复喻体命中"
    )
    explanatory_phrase_count: int = Field(
        ge=0, description="解释腔句式计数（他忽然明白/这意味着等）"
    )
    shell_counts: dict[str, int] = Field(
        default_factory=dict, description="壳句式计数, 如 not_a_but_b / parallel4"
    )
    dialogue_tag_density_per_1000: float = Field(
        ge=0, description="对话标签密度（说道/道，每千字）"
    )
    emotion_announcement_count: int = Field(
        ge=0, description="情绪宣布词计数（涌起一股/深吸一口气/眼眶一热）"
    )
    dash_colon_density_per_1000: float = Field(
        ge=0, description="破折号+冒号密度（每千字）"
    )
    connective_abuse_count: int = Field(
        default=0, ge=0, description="句首固定连接词计数（此外/同时/然而/综上所述等）"
    )
    colon_enumeration_count: int = Field(
        default=0, ge=0, description="'一是…二是…三是' 整齐枚举计数"
    )

    # ---- v2: 叙事维度量化（纯代码，词典规则引擎） ----
    # 密度口径 per_1000_chars，占比口径 per 句子（均对齐既有字段）。
    scenery_density_per_1000: float = Field(
        default=0.0, ge=0, description="景物名词密度（每千字）"
    )
    sensory_density_per_1000: float = Field(
        default=0.0, ge=0, description="感官动词密度（每千字）"
    )
    scenery_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="景物描写句子占比"
    )
    scene_transition_count: int = Field(
        default=0, ge=0, description="场景转换计数（显式转场 + 段落首时间标记）"
    )
    time_marker_density_per_1000: float = Field(
        default=0.0, ge=0, description="时间标记密度（每千字）"
    )
    psych_verb_density_per_1000: float = Field(
        default=0.0, ge=0, description="心理动词密度（每千字）"
    )
    psych_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="心理描写句子占比"
    )
    inner_monologue_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="直接内独白句子占比"
    )
    action_verb_density_per_1000: float = Field(
        default=0.0, ge=0, description="动作动词密度（每千字）"
    )
    action_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="动作描写句子占比"
    )
    narration_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="叙述句子占比（无引号∧无动作∧无景物∧无心理词）"
    )

    # ---- v3: 写作手法世界观量化（代理指标，全零默认） ----
    # 每条是"文笔手法的代理信号"，诚实标注：只捕捉显式可量化的侧面，
    # 真正的正向文笔鉴赏仍在正文层，这里不冒充全文鉴赏。
    modifier_load_density: float = Field(
        default=0.0, ge=0, description="修饰词负载（白描负代理：白描文本负载低，每千字）"
    )
    bystander_reaction_density: float = Field(
        default=0.0, ge=0, description="旁观者反应句密度（衬托/侧面描写代理，每千字）"
    )
    foil_sentence_ratio: float = Field(
        default=0.0, ge=0, le=1, description="旁观/侧面句占比（侧面描写代理）"
    )
    omission_marker_count: int = Field(
        default=0, ge=0, description="显式省略标记计数（省略号/未完句；只捕捉显式留白，隐式留白不可量化）"
    )
    decision_grounding_marker_density: float = Field(
        default=0.0, ge=0, description="显式决策依据信号密度（不得不/因为/基于+身份词共现，每千字）"
    )
    key_segment_len_ratio: float = Field(
        default=0.0, ge=0, description="高潮段与过渡段字数比（密疏详略代理）"
    )


class StyleProfile(BaseModel):
    """顶层写作风格档案.

    定义"这部作品以什么风格写成"。与 WorkSpec 同类，是规格不是状态。
    """

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(description="档案唯一标识")
    source_text_ref: str = Field(description="来源文本路径")
    schema_version: int = Field(
        default=1, ge=1, description="Schema 版本；v2 起=2（旧 v1 档案缺省标为 1）"
    )

    # 质性（LLM 提炼）
    tone_labels: list[str] = Field(
        default_factory=list, description="叙事调性标签, 命中 TONE_STYLE_TRAITS 键"
    )
    genre_guess: Optional[str] = Field(default=None, description="类型倾向判断")
    narrative_pov: str = Field(description="叙事视角, 如'第三人称有限'")
    pacing_description: str = Field(description="节奏策略描述")
    sentence_habits: list[str] = Field(
        default_factory=list, description="句式习惯清单"
    )
    rhetorical_preferences: list[str] = Field(
        default_factory=list, description="修辞偏好清单"
    )
    show_dont_tell_notes: list[str] = Field(
        default_factory=list, description="show-don't-tell 表现手法清单"
    )
    closed_loop_objects: list[str] = Field(
        default_factory=list, description="闭环物象清单（开头出现、结局回归）"
    )
    chapter_end_hook_notes: list[str] = Field(
        default_factory=list, description="章末钩子手法清单"
    )
    # ---- v2: 叙事维度质性（LLM 提炼，可选；空列表时静默不渲染） ----
    environment_notes: list[str] = Field(
        default_factory=list, description="环境/景物描写手法与功能（白描/借景抒情/交代时空/烘托情绪/转场）"
    )
    scene_transition_notes: list[str] = Field(
        default_factory=list, description="场景转换与过渡手法（显式标记/无痕切换/时间跳转/段落衔接）"
    )
    psychology_notes: list[str] = Field(
        default_factory=list, description="心理与内视角表现（密度判断/直接与间接内独白/show-don't-tell 深化）"
    )
    rhythm_notes: list[str] = Field(
        default_factory=list, description="叙事节奏与结构（叙述/对话/动作/描写配比/事件推进方式）"
    )
    # ---- v3: 写作手法世界观质性（LLM 提炼，可选；空字段时静默不渲染） ----
    temperament: Optional[str] = Field(
        default=None, description="叙事气质（散文型/戏剧型/信息型/氛围型）"
    )
    description_layering_notes: list[str] = Field(
        default_factory=list, description="描写手法选择与配比（白描/细描/渲染/衬托/侧面/动静/点面）"
    )
    omission_notes: list[str] = Field(
        default_factory=list, description="留白策略（什么细写、什么带过、不点破处；Art of Omission）"
    )
    subtle_technique_notes: list[str] = Field(
        default_factory=list, description="含蓄手法使用（象征/暗示/用典/双关）"
    )
    character_method_notes: list[str] = Field(
        default_factory=list, description="人物五法使用（肖像/动作/语言/心理/神态）"
    )
    dialogue_technique_notes: list[str] = Field(
        default_factory=list, description="对白技巧（潜文本/性格化/言外之意）"
    )
    decision_grounding_notes: list[str] = Field(
        default_factory=list, description="决策依据（选择由身份/信念/恐惧/利益驱动）"
    )
    taboo_words: list[str] = Field(
        default_factory=list, description="作者自查禁忌词（删/避用词）"
    )
    style_references: list[str] = Field(
        default_factory=list, description="命中的规则 key, 如 tone_kz_01"
    )

    # 量化（纯代码）
    stats: StyleQuantitativeStats = Field(description="量化统计")
    ai_flavor_risks: list[StyleRisk] = Field(
        default_factory=list, description="AI 味风险清单"
    )
    confidence_gaps: list[str] = Field(
        default_factory=list, description="不确定的信息"
    )

    @field_validator("profile_id", "source_text_ref", "narrative_pov", "pacing_description")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("genre_guess", "temperament")
    @classmethod
    def _optional_text_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None:
            _require_non_blank(value, info.field_name)
        return value

    @field_validator(
        "tone_labels",
        "sentence_habits",
        "rhetorical_preferences",
        "show_dont_tell_notes",
        "closed_loop_objects",
        "chapter_end_hook_notes",
        "environment_notes",
        "scene_transition_notes",
        "psychology_notes",
        "rhythm_notes",
        "description_layering_notes",
        "omission_notes",
        "subtle_technique_notes",
        "character_method_notes",
        "dialogue_technique_notes",
        "decision_grounding_notes",
        "taboo_words",
        "style_references",
        "confidence_gaps",
    )
    @classmethod
    def _list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        return _require_non_blank_items(values, info.field_name)

    def to_prompt_context(self, include_header: bool = True) -> str:
        """渲染【写作风格画像】块, 供续写 prompt 注入.

        include_header=False 时跳过【写作风格画像】首行（双层段头修复：
        消费方 continuation.py 独占外层段头，loader 只产正文）。
        """
        lines: list[str] = []
        if include_header:
            lines.append("【写作风格画像】")
        lines.append(
            f"调性: {' / '.join(self.tone_labels) if self.tone_labels else '未标注'}"
        )
        lines.append(f"视角: {self.narrative_pov}")
        if self.genre_guess:
            lines.append(f"类型倾向: {self.genre_guess}")
        if self.pacing_description:
            lines.append(f"节奏: {self.pacing_description}")
        if self.sentence_habits:
            lines.append("句式习惯:")
            lines.extend(f"- {item}" for item in self.sentence_habits)
        if self.rhetorical_preferences:
            lines.append("修辞偏好:")
            lines.extend(f"- {item}" for item in self.rhetorical_preferences)
        if self.show_dont_tell_notes:
            lines.append("情绪呈现:")
            lines.extend(f"- {item}" for item in self.show_dont_tell_notes)
        if self.closed_loop_objects:
            lines.append(f"闭环物象: {', '.join(self.closed_loop_objects)}")
        if self.chapter_end_hook_notes:
            lines.append("章末钩子:")
            lines.extend(f"- {item}" for item in self.chapter_end_hook_notes)
        # ---- v2: 叙事维度质性（空字段不渲染） ----
        if self.environment_notes:
            lines.append("环境/景物描写:")
            lines.extend(f"- {item}" for item in self.environment_notes)
        if self.scene_transition_notes:
            lines.append("场景转换与过渡:")
            lines.extend(f"- {item}" for item in self.scene_transition_notes)
        if self.psychology_notes:
            lines.append("心理与内视角:")
            lines.extend(f"- {item}" for item in self.psychology_notes)
        if self.rhythm_notes:
            lines.append("叙事节奏与结构:")
            lines.extend(f"- {item}" for item in self.rhythm_notes)
        # ---- v3: 写作手法世界观质性（空字段不渲染） ----
        if self.temperament:
            lines.append(f"叙事气质: {self.temperament}")
        if self.description_layering_notes:
            lines.append("描写手法:")
            lines.extend(f"- {item}" for item in self.description_layering_notes)
        if self.omission_notes:
            lines.append("留白与详略:")
            lines.extend(f"- {item}" for item in self.omission_notes)
        if self.subtle_technique_notes:
            lines.append("含蓄手法:")
            lines.extend(f"- {item}" for item in self.subtle_technique_notes)
        if self.character_method_notes:
            lines.append("人物刻画手法:")
            lines.extend(f"- {item}" for item in self.character_method_notes)
        if self.dialogue_technique_notes:
            lines.append("对白技巧:")
            lines.extend(f"- {item}" for item in self.dialogue_technique_notes)
        if self.decision_grounding_notes:
            lines.append("决策依据:")
            lines.extend(f"- {item}" for item in self.decision_grounding_notes)
        if self.taboo_words:
            lines.append(f"禁忌词: {', '.join(self.taboo_words)}")
        stats = self.stats
        baseline = (
            f"量化基线: 弱化副词 {stats.weak_adverb_density_per_1000:.1f}/千字"
            f"（阈值3）｜ 同喻体≤2 处 ｜ 短句占比 {stats.short_sentence_ratio:.2f}"
            f"｜ 对话占比 {stats.dialogue_ratio:.2f}"
        )
        lines.append(baseline)
        # v2 叙事维度量化行：仅当任一新统计非零时渲染。
        # （纯数据门控，不用 schema_version：v2 但全零 → 不渲染 → 与 v1 逐字节相同，
        #   保持「空新维度 = 静默」的注入静默降级契约。）
        v2_stats_nonzero = any(
            getattr(stats, field, 0.0) not in (0, 0.0)
            for field in (
                "scenery_density_per_1000",
                "sensory_density_per_1000",
                "scenery_sentence_ratio",
                "scene_transition_count",
                "time_marker_density_per_1000",
                "psych_verb_density_per_1000",
                "psych_sentence_ratio",
                "inner_monologue_sentence_ratio",
                "action_verb_density_per_1000",
                "action_sentence_ratio",
                "narration_sentence_ratio",
            )
        )
        if v2_stats_nonzero:
            lines.append(
                f"叙事维度量化: 景物句占比 {stats.scenery_sentence_ratio:.2f}"
                f"｜ 心理动词 {stats.psych_verb_density_per_1000:.1f}/千字"
                f"｜ 动作动词 {stats.action_verb_density_per_1000:.1f}/千字"
                f"｜ 时间标记 {stats.time_marker_density_per_1000:.1f}/千字"
                f"｜ 叙述句占比 {stats.narration_sentence_ratio:.2f}"
            )
        # v3 世界观量化行：仅当任一新统计非零时渲染（对齐 v2 门控 → 零成本契约）。
        v3_stats_nonzero = any(
            getattr(stats, field, 0.0) not in (0, 0.0)
            for field in (
                "modifier_load_density",
                "bystander_reaction_density",
                "foil_sentence_ratio",
                "omission_marker_count",
                "decision_grounding_marker_density",
                "key_segment_len_ratio",
            )
        )
        if v3_stats_nonzero:
            lines.append(
                f"世界观量化: 修饰词负载 {stats.modifier_load_density:.1f}/千字"
                f"（白描负代理）｜ 旁观者反应 {stats.bystander_reaction_density:.1f}/千字"
                f"（衬托代理）｜ 显式留白 {stats.omission_marker_count} 处"
                f"｜ 显式决策依据 {stats.decision_grounding_marker_density:.1f}/千字"
            )
        if self.ai_flavor_risks:
            lines.append("AI 味风险:")
            for risk in self.ai_flavor_risks:
                lines.append(
                    f"- [{risk.rule_id}] {risk.measure}: {risk.value:.1f}"
                    f"（阈值{risk.threshold:.1f}）"
                )
        if self.confidence_gaps:
            lines.append(f"不确定: {'; '.join(self.confidence_gaps)}")
        return "\n".join(lines)
