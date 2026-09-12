"""InferenceHandoff — 认知交接点（Reader Cognition Control V1 规划层）.

对应 RCC 设计：Continue 不只规划「发生什么」，还规划「读者什么时候获得什么认知」。
每个场景最多 1–3 个高价值交接点，三个语义层必须分离：
证据是什么 → 读者应该自己完成什么 → 什么情况下才值得显式说出来。

与 SceneExperience 同类：是规格（spec）不是叙事状态，不进状态机。
用法：作为 PlotUnit 的可选字段 reader_handoffs（空=不渲染，与旧版逐字节一致）。
Continue 生成 PlotUnit 时可选产出；Prose 展开时注入为停止条件。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

Explicitness = Literal["leave_implicit", "explicit_when_condition", "must_explain"]

EvidenceSufficiency = Literal[
    "sufficient", "needs_more_evidence", "must_explicit"
]


class InferenceHandoff(BaseModel):
    """单个认知交接点：把一部分叙事工作交还给读者."""

    model_config = ConfigDict(extra="forbid")

    evidence: str = Field(
        description="证据是什么——正文将给出的动作/对白/细节，"
        "足以让读者自行完成下面的推断"
    )
    reader_inference: str = Field(
        description="读者应自己完成什么——希望读者从证据中得出的判断/理解"
    )
    explicitness: Explicitness = Field(
        default="leave_implicit",
        description="leave_implicit=保持隐式（默认）；"
        "explicit_when_condition=条件满足时才允许显式；"
        "must_explain=读者无法可靠推断、必须显式（规则关键因果/不可见信息）",
    )
    evidence_sufficiency: EvidenceSufficiency = Field(
        default="sufficient",
        description="证据充分性下界：sufficient=已计划足够可见证据，"
        "Prose 可留下推断；needs_more_evidence=想让读者推但当前计划还少一个"
        "必要前提，Prose 必须先补证据再 STOP；must_explicit=信息无法从当前"
        "视角/事件合理推出（新规则/必须让读者知道的隐藏事实/决策依赖的"
        "特殊因果），允许直接明确",
    )
    explicit_when: Optional[str] = Field(
        default=None,
        description="什么情况下才值得显式说出——如『只有当人物意识到这一点"
        "并因此改变下一步行动时』；explicitness=leave_implicit 时可为 None",
    )
    payoff: Optional[str] = Field(
        default=None,
        description="预期回报——这个交接点在后续要兑现什么（可空）",
    )

    @field_validator("evidence", "reader_inference")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述（Prose 展开时注入为停止条件）."""
        lines = [
            f"- 证据: {self.evidence}",
            f"  读者自推: {self.reader_inference}",
            f"  显式条件: {self.explicitness}",
            f"  证据充分性: {self.evidence_sufficiency}",
        ]
        if self.explicit_when:
            lines.append(f"  何时可说: {self.explicit_when}")
        if self.payoff:
            lines.append(f"  回报: {self.payoff}")
        return "\n".join(lines)
