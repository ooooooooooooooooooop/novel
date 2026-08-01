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


class StyleProfile(BaseModel):
    """顶层写作风格档案.

    定义"这部作品以什么风格写成"。与 WorkSpec 同类，是规格不是状态。
    """

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(description="档案唯一标识")
    source_text_ref: str = Field(description="来源文本路径")

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

    @field_validator("genre_guess")
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
        "taboo_words",
        "style_references",
        "confidence_gaps",
    )
    @classmethod
    def _list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        return _require_non_blank_items(values, info.field_name)

    def to_prompt_context(self) -> str:
        """渲染【写作风格画像】块, 供续写 prompt 注入."""
        lines = [
            "【写作风格画像】",
            f"调性: {' / '.join(self.tone_labels) if self.tone_labels else '未标注'}",
            f"视角: {self.narrative_pov}",
        ]
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
        if self.taboo_words:
            lines.append(f"禁忌词: {', '.join(self.taboo_words)}")
        stats = self.stats
        baseline = (
            f"量化基线: 弱化副词 {stats.weak_adverb_density_per_1000:.1f}/千字"
            f"（阈值3）｜ 同喻体≤2 处 ｜ 短句占比 {stats.short_sentence_ratio:.2f}"
            f"｜ 对话占比 {stats.dialogue_ratio:.2f}"
        )
        lines.append(baseline)
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
