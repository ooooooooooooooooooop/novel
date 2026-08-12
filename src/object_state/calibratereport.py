"""CalibrationReport — 人类读者校准（隐藏来源连续阅读）报告对象.

Q1 Phase 6 产物（docs/00_project/45 §7）：不展示系统自评，读者只回答 6 问
（是否愿意翻下一页／人物是否还是同一个人／何处开始走神／是否有读不懂或不相信的
事实／本章真正发生了什么／最期待的下一件事是什么）；硬标准由现有零 LLM 门禁链
自动判定，聚合为 calibration_report.json。

定位：不是叙事状态（不进 NarrativeState/Frame/FactLedger 状态机），是 Phase 6
验证/校准的独立产物，供操作者与后续正式校准参考。首轮阈值作为试运行数据，
不预先伪造精确科学指标（is_pilot=True 显式标注）。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# 来源类别：材料包每章来自原始可信正文 / AI 生成正文（对读者隐藏）
SOURCE_ORIGINAL = "original"
SOURCE_AI = "ai_generated"

# 读者 6 问选项
TURN_PAGE_OPTIONS: tuple[str, ...] = ("yes", "hesitating", "no")
SAME_CHARACTER_OPTIONS: tuple[str, ...] = ("yes", "slight_change", "no")
GENRE_CHANGE_OPTIONS: tuple[str, ...] = ("no", "changed", "obvious")


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class CalibrationIssue(BaseModel):
    """硬标准自动判定产出的阻塞问题摘要（不耦合完整 ReviewIssue）."""

    model_config = ConfigDict(extra="forbid")

    issue_type: str = Field(description="问题类型（fact_conflict/generative_indicia/...）")
    severity: str = Field(description="严重级（critical/blocking）")
    location: str = Field(description="位置/锚点")
    description: str = Field(description="问题描述")

    @field_validator("issue_type", "severity", "location", "description")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class CalibrationHardStandard(BaseModel):
    """单章硬标准自动判定（零 LLM；路由与阻塞问题摘要）."""

    model_config = ConfigDict(extra="forbid")

    chapter_ref: str = Field(description="章节标识（如 chapter_22）")
    route: Literal["pass", "rewrite", "block", "manual"] = Field(
        description="提交点门禁路由（reconcile + 契约 + 重复闭环）"
    )
    axes_armed: dict[str, bool] = Field(
        description="实际武装的轴（时间/实体/道具轴缺 trusted 时显式 unarmed）"
    )
    blocking_issues: list[CalibrationIssue] = Field(
        default_factory=list, description="阻塞问题（critical/blocking severity）"
    )

    @field_validator("chapter_ref")
    @classmethod
    def _ref_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class CalibrationChapterAnswer(BaseModel):
    """读者对单章的 6 问回答."""

    model_config = ConfigDict(extra="forbid")

    chapter_ref: str = Field(description="章节标识")
    turn_page: Literal["yes", "hesitating", "no"] = Field(
        description="是否愿意翻下一页继续读"
    )
    same_character: Literal["yes", "slight_change", "no"] = Field(
        description="人物是否还是同一个人"
    )
    wander: str = Field(default="无", description="何处开始走神（无=没走神）")
    disbelieved: list[str] = Field(
        default_factory=list, description="读不懂或不相信的事实（可空）"
    )
    what_happened: str = Field(description="本章真正发生了什么（一句话）")
    anticipated: str = Field(description="最期待接下来发生什么（一句话）")

    @field_validator("chapter_ref", "what_happened", "anticipated")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class CalibrationReaderResponse(BaseModel):
    """读者整包回答（逐章 6 问 + 整体题）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, description="Schema 版本")
    reader_id: str = Field(default="reader_1", description="读者标识")
    chapters: list[CalibrationChapterAnswer] = Field(
        description="逐章回答（须覆盖材料包全部章节）"
    )
    overall_genre_change: Literal["no", "changed", "obvious"] = Field(
        description="整体：核心人物或作品类型是否改变"
    )

    @field_validator("reader_id")
    @classmethod
    def _reader_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("chapters")
    @classmethod
    def _chapters_must_not_be_empty(
        cls, values: list[CalibrationChapterAnswer], info: ValidationInfo
    ) -> list[CalibrationChapterAnswer]:
        if not values:
            raise ValueError("chapters must not be empty")
        return values


class CalibrationAggregate(BaseModel):
    """跨章聚合口径（首轮试运行数据，不冒充精确科学指标）."""

    model_config = ConfigDict(extra="forbid")

    continue_ratio: float = Field(
        description="turn_page=yes 的章数占比（愿意继续读的比例）"
    )
    same_character_ratio: float = Field(
        description="same_character=yes 的章数占比（人物仍是同一人的比例）"
    )
    genre_change: Literal["no", "changed", "obvious"] = Field(
        description="整体：核心人物/作品类型是否改变"
    )
    wander_anchors: list[dict[str, str]] = Field(
        default_factory=list, description="走神锚点 [{chapter_ref, anchor}]"
    )
    disbelieved_facts: list[dict[str, str]] = Field(
        default_factory=list, description="不可信/没读懂的事实 [{chapter_ref, fact}]"
    )
    what_happened: list[dict[str, str]] = Field(
        default_factory=list, description="每章真正发生 [{chapter_ref, summary}]"
    )
    anticipated: list[dict[str, str]] = Field(
        default_factory=list, description="每章最期待 [{chapter_ref, text}]"
    )


class CalibrationVerdict(BaseModel):
    """Q1 硬标准 + 读者口径判定（pilot 口径，不预先伪造科学指标）."""

    model_config = ConfigDict(extra="forbid")

    original_clean: bool = Field(
        description="原始章硬标准全干净（无阻塞问题）"
    )
    generated_clean: bool = Field(
        description="生成章硬标准全干净（无阻塞问题）"
    )
    reader_continue: bool = Field(
        description="多数目标读者愿意继续（continue_ratio > 0.5）"
    )
    reader_genre_stable: bool = Field(
        description="没有多数读者认为核心人物/作品类型改变（overall=no）"
    )
    is_pilot: bool = Field(
        default=True, description="True=首轮试运行数据，非科学指标"
    )


class CalibrationReport(BaseModel):
    """人类读者校准报告（操作者可见；source_map/hard_standards 对读者隐藏）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, description="Schema 版本")
    packet_id: str = Field(description="材料包标识（如 wanwu_pilot_01）")
    created_at_utc: str = Field(description="报告生成时间（ISO UTC）")
    source_map: dict[str, str] = Field(
        description="章号 → original/ai_generated（读者不可见，仅操作者/聚合用）"
    )
    hard_standards: list[CalibrationHardStandard] = Field(
        description="逐章硬标准自动判定（读者不可见）"
    )
    reader: CalibrationReaderResponse = Field(description="读者逐章回答")
    aggregate: CalibrationAggregate = Field(description="跨章聚合")
    verdicts: CalibrationVerdict = Field(description="Q1 判定（pilot 口径）")

    @field_validator("packet_id")
    @classmethod
    def _packet_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)
