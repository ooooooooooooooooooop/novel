"""Causal Defense 数据模型定义 (R4 整改).

定义强类型因果规则 CausalRule 与时间线解析状态 TimelineResolution.
"""

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo


class CausalRule(BaseModel):
    """强类型因果规则 (WorldModel 规则与代价机制的结构化定义)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="规则唯一标识, 如 'hard_rule_01', 'rule_cost_soul'")
    rule_type: Literal[
        "hard_rule",
        "consequence_logic",
        "prohibition",
        "forbidden_action",
        "death_rule",
        "resource_system",
        "custom",
    ] = Field(description="规则类型")
    statement: str = Field(description="规则正文陈述")
    applies_to: list[str] = Field(
        default_factory=list, description="适用实体ID或概念范畴 (如 ['林尘', '禁术', '元婴'])"
    )
    cost_type: Literal[
        "life",
        "cultivation",
        "resource",
        "social_status",
        "body",
        "soul",
        "general",
    ] = Field(default="general", description="代价类型")
    reversibility: Literal[
        "irreversible",
        "strict_irreversible",
        "conditional",
        "forbidden",
        "conservation_of_cost",
    ] = Field(default="irreversible", description="代价/结果可逆性")
    reversal_requirements: list[str] = Field(
        default_factory=list, description="逆转或恢复的前置条件"
    )

    @field_validator("rule_id", "statement")
    @classmethod
    def _required_text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value.strip()


class TimelineResolution(BaseModel):
    """事实与情节单元的时间线判定结果."""

    model_config = ConfigDict(extra="forbid")

    established: Optional[bool] = Field(
        default=None,
        description="事实是否在当前情节单元发生前或发生时已成立. True=已成立, False=未成立/未来事实/已失效, None=时间线未决(unreviewable)",
    )
    status: Literal["resolved", "future_fact", "expired", "unreviewable"] = Field(
        default="resolved", description="时间线判定状态"
    )
    fact_chapter: Optional[int] = Field(default=None, description="事实生效章节号")
    pu_chapter: Optional[int] = Field(default=None, description="情节单元发生章节号")
    notes: list[str] = Field(default_factory=list, description="判定依据或降级说明")
