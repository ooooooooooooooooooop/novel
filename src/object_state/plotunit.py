"""PlotUnit — 情节单元定义."""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
)


class PlotUnit(BaseModel):
    """最小有效叙事推进单元.

    定义"这次推进改变了什么".
    不是单纯的事件记录或文本段落.
    必须导致至少一个关键状态字段发生有意义变化.
    """

    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(description="单元唯一标识")
    level: Literal["book", "arc", "chapter", "scene"] = Field(
        description="层级: book / arc / chapter / scene"
    )
    goal: str = Field(description="本单元目标")

    # 参与者与冲突
    participants: list[str] = Field(
        default_factory=list, description="参与角色ID列表"
    )
    conflict: str = Field(description="核心冲突")

    # 状态引用(轻量引用, 不嵌套完整对象)
    input_state_ref: str = Field(description="输入状态 NarrativeState.state_id")
    output_state_ref: str = Field(description="输出状态 NarrativeState.state_id")

    # 推进内容
    released_information: list[str] = Field(
        default_factory=list, description="本单元释放给读者的新信息"
    )
    emotional_shift: Optional[str] = Field(
        default=None, description="情绪变化, 如从压抑到爆发"
    )
    hook: Optional[str] = Field(default=None, description="钩子, 如悬念铺垫")
    formula_node: Optional[str] = Field(
        default=None, description="关联的结构模板节点名，如 opener_hook / climax"
    )

    # 后果
    consequences: list[str] = Field(
        default_factory=list, description="本单元导致的后果清单"
    )

    # 状态变化摘要（弱推进检查依据）
    state_change_summary: Optional[str] = Field(
        default=None,
        description="状态变化摘要：本单元改变了什么（目标/信息/关系/风险/冲突），"
        "weak_progression 判定依据",
    )
    removable_without_loss: Optional[bool] = Field(
        default=None,
        description="删除本单元后主线是否几乎不受损（冗余度判定依据）",
    )

    # 有效性标记(运行时判断)
    is_effective: StrictBool = Field(
        default=False,
        description="是否导致有意义状态变化. 运行时由 Review 确认后标记.",
    )

    @field_validator(
        "unit_id", "goal", "conflict", "input_state_ref", "output_state_ref"
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("participants")
    @classmethod
    def _participant_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("released_information", "consequences")
    @classmethod
    def _progression_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = [
            f"【PlotUnit: {self.unit_id} | {self.level}】",
            f"目标: {self.goal}",
            f"冲突: {self.conflict}",
            f"参与者: {', '.join(self.participants)}",
        ]
        if self.released_information:
            lines.append(f"释放信息: {'; '.join(self.released_information)}")
        if self.emotional_shift:
            lines.append(f"情绪变化: {self.emotional_shift}")
        if self.hook:
            lines.append(f"钩子: {self.hook}")
        if self.formula_node:
            lines.append(f"结构节点: {self.formula_node}")
        if self.consequences:
            lines.append(f"后果: {'; '.join(self.consequences)}")
        if self.state_change_summary:
            lines.append(f"状态变化: {self.state_change_summary}")
        if self.removable_without_loss is not None:
            lines.append(f"可删无损: {'是' if self.removable_without_loss else '否'}")
        lines.append(f"有效推进: {'是' if self.is_effective else '待确认'}")
        return "\n".join(lines)
