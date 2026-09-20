"""ExpectationUpdateIntent — 读者预期更新意图（隐藏规划对象，dim7）.

描述本场景计划对读者预期做什么操作：开启/收窄/强化/动摇/翻转/兑现。
与 DialogueStrategy/DetailContract 同构：生成于 Continue、编译为
writer-facing 最小执行契约作用于 Prose、完整对象仅供 post-prose
Review/grounding 对照。

防火墙：`intended_prediction`（作者想让读者形成的预测，如『凶手是A』）
是作者侧意图，永远不进 writer-facing prompt——否则 writer 会把
「让读者以为X」文学化成显性误导叙述。writer 只见行为契约。

纪律：ExpectationUpdateIntent 是计划不是事实——正文若未实现，
post-prose grounding 不得更新 ReaderExpectation（plan→fact 不混）。
"""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

ExpectationIntentKind = Literal[
    "OPEN",        # 开启新预期：建立一个读者将等待的问题/结果空间
    "NARROW",      # 收窄：让已有证据可见，缩小读者可能性空间（不解释指向）
    "STRENGTHEN",  # 强化：呈现已有证据让读者更倾向当前预测方向
    "WEAKEN",      # 动摇：呈现已有反证让读者对当前预测生疑
    "FLIP",        # 翻转：结果违反读者已建立的 dominant_prediction
    "RESOLVE",     # 兑现：回答/行动真实发生，关闭预期
]


class ExpectationUpdateIntent(BaseModel):
    """对一条读者预期的计划操作（≤2 个/PlotUnit，只动关键信息缺口）."""

    model_config = ConfigDict(extra="forbid")

    expectation_id: str = Field(
        description="目标预期 id（ReaderExpectation.expectation_id；"
        "OPEN 新预期时用新 id）"
    )
    reader_question: str = Field(
        description="目标预期的读者视角问题（渲染快照，供执行契约定位对象）"
    )
    intent: ExpectationIntentKind = Field(description="计划操作类型")
    intended_prediction: Optional[str] = Field(
        default=None,
        description="【隐藏】作者意图形成的读者预测（如误导目标）；"
        "仅供 Review/grounding 对照，永不进 writer-facing 契约",
    )
    evidence_to_surface: list[str] = Field(
        default_factory=list,
        description="计划呈现给读者的已有证据/线索（必须引用已存在事实，"
        "不得凭空造 clue）",
    )
    answer_due_now: bool = Field(
        default=False,
        description="当前因果链是否已要求兑现（True=本场必须发生回答/行动，"
        "不得用停顿/打断/欲言又止推迟）",
    )

    @field_validator("expectation_id", "reader_question")
    @classmethod
    def _non_blank(cls, v: str, info: ValidationInfo) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return v

    @field_validator("intended_prediction")
    @classmethod
    def _opt_non_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("intended_prediction must be non-empty when provided")
        return v

    @field_validator("evidence_to_surface")
    @classmethod
    def _list_non_blank(cls, vs: list[str]) -> list[str]:
        if any(not v.strip() for v in vs):
            raise ValueError("evidence_to_surface entries must be non-empty")
        return vs

    def to_prompt_context(self) -> str:
        """完整对象——仅供 Continue 自检 / post-prose Review / grounding."""
        lines = [
            f"- expectation: {self.expectation_id} | 操作: {self.intent}",
            f"  问题: {self.reader_question}",
        ]
        if self.intended_prediction:
            lines.append(f"  意图预测(hidden): {self.intended_prediction}")
        if self.evidence_to_surface:
            lines.append(f"  计划呈现证据: {'；'.join(self.evidence_to_surface)}")
        if self.answer_due_now:
            lines.append("  到期: 是（本场必须兑现）")
        return "\n".join(lines)

    def to_execution_context(self) -> str:
        """writer-facing 编译产物：行为约束，不含 intended_prediction.

        契约语义（裁决冻结）：
        - 合法悬念=问题未解但读者可能性/风险/代价/预测有变化
        - 非法拖延=问题未解+本应发生未发生+读者状态无有效更新
        """
        q = self.reader_question
        lines = []
        if self.intent == "OPEN":
            lines.append(
                f"- 本场建立读者将等待的问题『{q}』：让缺口可见，"
                "但不在本场给答案"
            )
        elif self.intent == "NARROW":
            lines.append(
                f"- 让读者对『{q}』的可能性空间收窄：把已有线索"
                "写进可见层，不解释它指向什么"
            )
        elif self.intent == "STRENGTHEN":
            lines.append(
                f"- 让读者对『{q}』更倾向某个判断：呈现已有证据，"
                "不明说结论"
            )
        elif self.intent == "WEAKEN":
            lines.append(
                f"- 让读者对『{q}』的当前判断产生动摇：呈现已有反证，"
                "不直接否定"
            )
        elif self.intent == "FLIP":
            lines.append(
                f"- 本场发生与读者对『{q}』当前预期相反的结果；"
                "结果须与此前已有事实相容，能让读者回溯认出证据基础"
                "（不得天降）"
            )
        elif self.intent == "RESOLVE":
            lines.append(f"- 本场兑现『{q}』：回答/行动真实发生，关闭问题")
        for ev in self.evidence_to_surface:
            lines.append(f"  · 已有证据须进入可见层: {ev}")
        if self.answer_due_now:
            lines.append(
                "- 当前因果链已经要求回答/行动：本场必须发生兑现；"
                "不得用新的停顿、打断、欲言又止把它推到下一场"
            )
        elif self.intent in ("OPEN", "NARROW", "STRENGTHEN", "WEAKEN"):
            lines.append("- 当前答案尚未到期：可保持开放，但读者状态须有有效更新")
        return "\n".join(lines)
