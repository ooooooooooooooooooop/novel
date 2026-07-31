"""CharacterModel — 角色模型定义."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class CharacterModel(BaseModel):
    """角色决策模型.

    定义"这个人为什么会这样做".
    不是只有外貌和性格标签的人设卡.
    字段本体只保留压缩的长期结论, 支撑证据留在 PlotUnit / NarrativeState / handoff / review context.
    """

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(description="角色唯一标识")
    name: str = Field(description="角色名")
    identity: str = Field(description="身份定位, 如'被逐出宗门的少女'")

    # 驱动力
    outer_goal: str = Field(description="外在目标, 角色明确追求什么")
    inner_need: str = Field(description="内在需求, 角色真正需要什么")
    fear: str = Field(description="恐惧, 角色最怕发生什么")
    flaw: str = Field(description="缺陷, 限制角色决策的弱点")
    strength: str = Field(description="优势, 角色能依赖的能力")

    # 隐藏层
    secret: Optional[str] = Field(default=None, description="秘密, 未公开的核心信息")
    stance: str = Field(description="当前立场, 如中立/敌对/合作")

    # 成长
    arc_stage: Optional[str] = Field(
        default=None, description="弧线阶段, 如否认→挣扎→接受"
    )
    self_image: Optional[str] = Field(
        default=None, description="自我认知, 如'我必须独自承担'"
    )

    # 认知状态(硬事实 vs 错误信念分离, Track 3)
    knowledge_state: list[str] = Field(
        default_factory=list,
        description="已确认的已知信息(硬事实)",
    )
    misinformation: list[str] = Field(
        default_factory=list,
        description="角色持有的错误信念(不是推导字段, 是已稳定的角色属性)",
    )

    # 关系(只存结论, 不存依据)
    relations: dict[str, str] = Field(
        default_factory=dict,
        description="与其他角色的关系结论. key=角色ID, value=关系描述",
    )

    @field_validator(
        "character_id",
        "name",
        "identity",
        "outer_goal",
        "inner_need",
        "fear",
        "flaw",
        "strength",
        "stance",
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("knowledge_state", "misinformation")
    @classmethod
    def _knowledge_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("relations")
    @classmethod
    def _relation_entries_must_be_non_blank(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not value.strip() for key, value in values.items()):
            raise ValueError("relations entries must be non-empty")
        return values

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = [
            f"【角色: {self.name}】",
            f"角色ID: {self.character_id}",
            f"身份: {self.identity}",
            f"外在目标: {self.outer_goal}",
            f"内在需求: {self.inner_need}",
            f"恐惧: {self.fear}",
            f"缺陷: {self.flaw}",
            f"优势: {self.strength}",
            f"立场: {self.stance}",
        ]
        if self.secret:
            lines.append(f"秘密: {self.secret}")
        if self.arc_stage:
            lines.append(f"成长阶段: {self.arc_stage}")
        if self.self_image:
            lines.append(f"自我认知: {self.self_image}")
        if self.knowledge_state:
            lines.append(f"已知信息: {'; '.join(self.knowledge_state)}")
        if self.misinformation:
            lines.append(f"错误信念: {'; '.join(self.misinformation)}")
        if self.relations:
            rels = [f"{k}: {v}" for k, v in self.relations.items()]
            lines.append(f"关系: {'; '.join(rels)}")
        return "\n".join(lines)
