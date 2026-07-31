"""AuditReport — audit 流最终合并产物."""

from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .charactermodel import CharacterModel
from .factledger import FactLedger
from .foreshadowgraph import ForeshadowGraph
from .narrativestate import NarrativeState
from .reviewissue import ReviewIssue, ReviewReminder
from .workspec import WorkSpec
from .worldmodel import WorldModel


VALID_REWRITE_TARGET_TYPES = {
    "CharacterModel",
    "FactLedger",
    "NarrativeState",
    "PlotUnit",
    "WorldModel",
    "ForeshadowGraph",
}


class RewriteFix(BaseModel):
    """Applied rewrite fix recorded in the final audit artifact."""

    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(description="Target object model name")
    target_id: Optional[str] = Field(default=None, description="Stable target object ID")
    field: str = Field(description="Target field or dotted path")
    action: Literal["add", "remove", "replace"] = Field(description="Fix action")
    old_value: Any = Field(default=None, description="Expected old value")
    new_value: Any = Field(default=None, description="Replacement or added value")
    reason: Optional[str] = Field(default=None, description="Fix rationale")

    @field_validator("target_type", "field")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("target_type")
    @classmethod
    def _target_type_must_be_supported(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if value not in VALID_REWRITE_TARGET_TYPES:
            raise ValueError(f"{info.field_name} must be a supported object type")
        return value


class AuditReport(BaseModel):
    """作者看到的 audit 最终结果。

    将 rebuild_package + review_result 合并为单一视图。
    """

    model_config = ConfigDict(extra="forbid")

    source_text_ref: str = Field(description="源文本路径")
    route: Literal["pass", "rewrite", "block"] = Field(
        description="最终路由: pass / rewrite / block"
    )

    # 重建对象层
    workspec: Optional[WorkSpec] = Field(default=None, description="作品规格")
    worldmodel: Optional[WorldModel] = Field(default=None, description="世界模型")
    characters: list[CharacterModel] = Field(
        default_factory=list, description="角色模型列表"
    )
    narrative_state: Optional[NarrativeState] = Field(default=None, description="叙事状态")
    fact_ledger: Optional[FactLedger] = Field(default=None, description="事实账本")
    foreshadow_graph: Optional[ForeshadowGraph] = Field(default=None, description="伏笔图")
    outline_used: StrictBool = Field(
        default=False, description="是否在 Rebuild 中注入了 outline 先验"
    )
    outline_arcs_count: StrictInt = Field(
        default=0,
        ge=0,
        description="outline 中的 arc 数量",
    )

    # 审查结果
    issues: list[ReviewIssue] = Field(default_factory=list, description="审查问题列表")
    reminders: list[ReviewReminder] = Field(default_factory=list, description="审查提醒列表")
    confidence_gaps: list[str] = Field(default_factory=list, description="置信缺口")

    # rewrite 记录（如有）
    rewrite_applied: StrictBool = Field(default=False, description="是否应用了修复")
    applied_fixes: list[RewriteFix] = Field(
        default_factory=list, description="应用的修复列表"
    )
    original_route: Optional[str] = Field(default=None, description="rewrite 前的原始路由")

    @field_validator("source_text_ref")
    @classmethod
    def _source_text_ref_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("confidence_gaps")
    @classmethod
    def _confidence_gaps_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @model_validator(mode="after")
    def _rewrite_history_must_be_consistent(self) -> "AuditReport":
        if self.rewrite_applied:
            if not self.applied_fixes:
                raise ValueError("rewrite_applied requires non-empty applied_fixes")
            if self.original_route != "rewrite":
                raise ValueError("rewrite_applied requires original_route='rewrite'")
            return self

        if self.applied_fixes:
            raise ValueError("applied_fixes require rewrite_applied=true")
        if self.original_route is not None:
            raise ValueError("original_route requires rewrite_applied=true")
        return self
