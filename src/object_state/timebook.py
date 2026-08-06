"""TimeBook — 时间域持久先验（spec，非状态）.

与 StyleProfile 同级：一部小说一个，跨流程共享，持久于
`novels/<名>/output/time/time_book.json`（对齐 style_profile.json）。
全字段可选，缺省即"该功能关闭"，序列化向后兼容。
不进入 serialization.py 层映射（时间域是 spec 先验，不是叙事状态）。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class TimeInitial(BaseModel):
    """起点设定（compose 建立；audit/rebuild 校准）."""

    model_config = ConfigDict(extra="forbid")

    date: Optional[str] = Field(
        default=None, description="起点日期(ISO YYYY-MM-DD), 如'2001-01-23'"
    )
    lunar: Optional[str] = Field(default=None, description="农历/节气, 如'除夕'")
    loc: Optional[str] = Field(default=None, description="起点地点, 如'某城'")

    @field_validator("date", "lunar", "loc")
    @classmethod
    def _opt_text_must_be_non_blank(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value

    def is_empty(self) -> bool:
        return self.date is None and self.lunar is None and self.loc is None


class TimeAnchor(BaseModel):
    """章节时间锚点（续写准星 + 单调校验源）."""

    model_config = ConfigDict(extra="forbid")

    chapter: Optional[str] = Field(default=None, description="章节标识, 如'第N章'")
    date: Optional[str] = Field(default=None, description="锚点日期(ISO YYYY-MM-DD)")
    lunar: Optional[str] = Field(default=None, description="农历/节气, 如'腊月廿九'")
    tod: Optional[str] = Field(default=None, description="时段, 如'入夜'")
    loc: Optional[str] = Field(default=None, description="地点, 如'某城'")
    relative: Optional[str] = Field(
        default=None,
        description="相对时间标记, 如'三个月后/次日/三天后'（无绝对日期章节的覆盖锚）",
    )

    @field_validator("chapter", "date", "lunar", "tod", "loc", "relative")
    @classmethod
    def _opt_text_must_be_non_blank(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value


class EraContext(BaseModel):
    """年度时代背景（参考层，可架空，非硬事实）."""

    model_config = ConfigDict(extra="forbid")

    year: int = Field(description="年份, 如 2001")
    events: list[str] = Field(default_factory=list, description="该年大事件")
    note: Optional[str] = Field(default=None, description="备注, 如'液晶/手机出海窗口'")

    @field_validator("events")
    @classmethod
    def _events_must_be_non_blank(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if any(not v.strip() for v in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


class TimelineSpec(BaseModel):
    """多时间线（前世/今生、闪回段）; ends 是先知时效边界."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="时间线标识, 如'past'")
    name: Optional[str] = Field(default=None, description="名称, 如'前世'")
    ends: Optional[str] = Field(
        default=None, description="先知时效终点(YYYY-MM / YYYY-MM-DD)"
    )
    note: Optional[str] = Field(default=None, description="备注")

    @field_validator("id")
    @classmethod
    def _id_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class TimeBook(BaseModel):
    """时间域持久先验. 全字段可选，缺省即该功能关闭."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, description="schema 版本")
    initial: Optional[TimeInitial] = Field(default=None, description="起点设定")
    anchors: list[TimeAnchor] = Field(default_factory=list, description="章节时间锚表")
    era: list[EraContext] = Field(default_factory=list, description="年度时代背景")
    timelines: list[TimelineSpec] = Field(default_factory=list, description="多时间线")
    rules: list[str] = Field(default_factory=list, description="软时间规则(季节/历法/节气)")

    @field_validator("rules")
    @classmethod
    def _rules_must_be_non_blank(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if any(not v.strip() for v in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("schema_version")
    @classmethod
    def _schema_version_ge_1(cls, value: int, info: ValidationInfo) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1")
        return value

    def latest_anchor(self) -> Optional[TimeAnchor]:
        """按章节位置取最新锚点; 无法解析章节号时取原序最后一个."""
        if not self.anchors:
            return None
        return self.anchors[-1]
