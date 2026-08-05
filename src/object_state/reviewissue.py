"""Review issue and reminder models."""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


ReviewIssueType = Literal[
    "fact_conflict",
    "character_distortion",
    "world_violation",
    "weak_progression",
    "promise_loss",
    "style_drift",
    "generative_indicia",
    "missing_consequence",
    "missing_cost",
    "relationship_jump",
    "motivation_gap",
    "information_leak",
    "timeline_error",
    "abrupt_payoff",
    "redundancy",
    "duplication_of_threads",
]
ReminderFamily = Literal[
    "missing_consequence",
    "missing_cost",
    "relationship_bridge_needed",
    "promise_followup_needed",
    "knowledge_check_needed",
]


REMINDER_ESCALATION_MATRIX: dict[str, dict[str, object]] = {
    "missing_consequence": {
        "default_window": "plotunit_count=2",
        "allowed_escalation_issue_types": ("missing_consequence",),
        "default_early_escalation_condition": (
            "two consecutive reviews show no core consequence"
        ),
        "default_closure_condition": (
            "at least one core consequence is paid off within one effective unit"
        ),
    },
    "missing_cost": {
        "default_window": "plotunit_count=1_or_2",
        "allowed_escalation_issue_types": ("missing_cost",),
        "default_early_escalation_condition": (
            "continued zero-cost operation or world legality drift"
        ),
        "default_closure_condition": (
            "cost, loss, accountability, or resource consumption is explicit"
        ),
    },
    "relationship_bridge_needed": {
        "default_window": "plotunit_count=1",
        "allowed_escalation_issue_types": ("relationship_jump", "motivation_gap"),
        "default_early_escalation_condition": (
            "next unit skips relationship stage or violates character logic"
        ),
        "default_closure_condition": (
            "bridge or cost explains the relationship movement"
        ),
    },
    "promise_followup_needed": {
        "default_window": "before_local_arc_turn",
        "allowed_escalation_issue_types": ("promise_loss", "missing_consequence"),
        "default_early_escalation_condition": (
            "core thread is repeatedly obscured or same reminder repeats"
        ),
        "default_closure_condition": (
            "promise is advanced, narrowed, deflected, or delayed with cost"
        ),
    },
    "knowledge_check_needed": {
        "default_window": "plotunit_count=1",
        "allowed_escalation_issue_types": ("information_leak",),
        "default_early_escalation_condition": (
            "next unit keeps knowledge vague and character acts on illegal knowledge"
        ),
        "default_closure_condition": (
            "knowledge ownership is clear and next action matches that boundary"
        ),
    },
}


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ReviewIssue(BaseModel):
    """Actionable review failure.

    Defines where the system is broken and what kind of repair is required.
    It is not general criticism; it must be locatable, classified, and
    repairable.
    """

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(description="问题唯一标识")
    issue_type: ReviewIssueType = Field(description="失败类型")
    severity: Literal["critical", "blocking", "warning", "low"] = Field(
        description="严重等级"
    )
    location: str = Field(description="位置, 如'pu_scene_014, 第三段'")
    scope_of_impact: str = Field(description="影响范围")
    violated_rule: str = Field(description="违反的规则, 如'角色合法性'")
    description: str = Field(description="问题描述")
    suggested_fix: Optional[str] = Field(default=None, description="建议修复方案")
    resolution_status: Literal["open", "resolved", "deferred"] = Field(
        default="open", description="解决状态"
    )

    @field_validator(
        "issue_id",
        "location",
        "scope_of_impact",
        "violated_rule",
        "description",
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("suggested_fix", "plotunit_ref")
    @classmethod
    def _optional_text_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None:
            _require_non_blank(value, info.field_name)
        return value

    plotunit_ref: Optional[str] = Field(
        default=None, description="关联 PlotUnit.unit_id"
    )
    affected_threads: list[str] = Field(
        default_factory=list, description="影响的 ForeshadowGraph.thread_id 列表"
    )
    supporting_facts: list[str] = Field(
        default_factory=list, description="支撑事实 FactLedger.fact_id 列表"
    )
    contradictory_facts: list[str] = Field(
        default_factory=list, description="矛盾事实 FactLedger.fact_id 列表"
    )

    @field_validator("affected_threads", "supporting_facts", "contradictory_facts")
    @classmethod
    def _reference_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def is_blocking(self) -> bool:
        """Whether this issue blocks progression."""
        return self.severity in ("critical", "blocking")

    def to_prompt_context(self) -> str:
        """Render issue context for LLM prompts."""
        lines = [
            f"【ReviewIssue: {self.issue_id}】",
            f"类型: {self.issue_type} | 严重度: {self.severity}",
            f"位置: {self.location}",
            f"违反规则: {self.violated_rule}",
            f"描述: {self.description}",
        ]
        if self.suggested_fix:
            lines.append(f"建议修复: {self.suggested_fix}")
        if self.resolution_status != "open":
            lines.append(f"状态: {self.resolution_status}")
        return "\n".join(lines)


class ReviewReminder(BaseModel):
    """Near-term review warning handoff object.

    It records risks that are not yet formal ReviewIssues, but must be
    tracked across workflows with a window and escalation target.
    """

    model_config = ConfigDict(extra="forbid")

    reminder_id: str = Field(description="提醒唯一标识")
    family: ReminderFamily = Field(description="提醒类型")
    trigger_condition: str = Field(description="触发条件, 如'2个PlotUnit内未回收'")
    window: str = Field(description="处理窗口")
    escalation_issue_type: ReviewIssueType = Field(description="超过窗口后的问题类型")
    early_escalation_condition: str = Field(description="提前升级条件")
    closure_condition: str = Field(description="补偿关闭条件")
    priority: Literal["high", "medium", "low"] = Field(default="medium")
    status: Literal["active", "resolved", "escalated"] = Field(default="active")
    source_review: Optional[str] = Field(
        default=None, description="来源 Review 的标识"
    )

    @field_validator(
        "reminder_id",
        "trigger_condition",
        "window",
        "early_escalation_condition",
        "closure_condition",
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("source_review")
    @classmethod
    def _source_review_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None:
            _require_non_blank(value, info.field_name)
        return value

    @model_validator(mode="after")
    def _escalation_target_must_match_family(self) -> "ReviewReminder":
        allowed = REMINDER_ESCALATION_MATRIX[self.family][
            "allowed_escalation_issue_types"
        ]
        if self.escalation_issue_type not in allowed:
            raise ValueError(
                "escalation_issue_type must match ReviewReminder family matrix"
            )
        return self
