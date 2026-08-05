"""NarrativeState — 叙事状态定义."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class NarrativeState(BaseModel):
    """当前叙事运行态.

    定义"故事现在进行到哪里".
    不是静态设定文件, 是随 PlotUnit 推进而更新的运行快照.
    """

    model_config = ConfigDict(extra="forbid")

    state_id: str = Field(description="状态唯一标识")
    current_time: str = Field(description="当前叙事时间")
    current_location: str = Field(description="当前地点")

    # 角色
    active_characters: list[str] = Field(
        default_factory=list, description="当前出场角色ID列表"
    )

    # 局势
    current_situation: str = Field(description="当前局势概述")
    primary_goal: Optional[str] = Field(default=None, description="当前首要目标")
    active_conflicts: list[str] = Field(
        default_factory=list, description="当前活跃冲突"
    )
    emotional_temperature: Optional[str] = Field(
        default=None, description="当前情绪温度, 如压抑/紧张/释放"
    )

    # 信息分层
    public_information: list[str] = Field(
        default_factory=list, description="当前公开信息"
    )
    hidden_information: list[str] = Field(
        default_factory=list, description="当前隐藏信息(读者不知但系统追踪)"
    )
    private_information_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="秘密→知情角色ID列表（叙事层信息分配：谁知晓某秘密）。"
        "与 FactEntry.known_by（事实层）和 CharacterModel.knowledge_state（角色层）分工互补",
    )
    open_questions: list[str] = Field(
        default_factory=list, description="当前未回答的开放问题（结构性悬念）"
    )

    # 悬念
    active_suspense_items: list[str] = Field(
        default_factory=list, description="当前未关闭悬念项"
    )
    current_goals: list[str] = Field(
        default_factory=list, description="当前各角色目标汇总"
    )

    # 追踪引用
    linked_open_threads: list[str] = Field(
        default_factory=list, description="关联的 ForeshadowGraph thread_id 列表"
    )
    current_facts_in_scope: list[str] = Field(
        default_factory=list, description="当前范围内 FactLedger fact_id 列表"
    )

    @field_validator("state_id", "current_time", "current_location", "current_situation")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator(
        "active_characters",
        "active_conflicts",
        "public_information",
        "hidden_information",
        "active_suspense_items",
        "current_goals",
        "linked_open_threads",
        "current_facts_in_scope",
        "open_questions",
    )
    @classmethod
    def _list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("private_information_map")
    @classmethod
    def _private_info_map_entries_must_be_non_blank(
        cls, values: dict[str, list[str]], info: ValidationInfo
    ) -> dict[str, list[str]]:
        for secret, knowers in values.items():
            if not secret.strip():
                raise ValueError("private_information_map keys must be non-empty")
            if any(not k.strip() for k in knowers):
                raise ValueError(
                    "private_information_map values must be lists of non-empty strings"
                )
        return values

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = [
            "【当前叙事状态】",
            f"时间: {self.current_time}",
            f"地点: {self.current_location}",
            f"局势: {self.current_situation}",
        ]
        if self.primary_goal:
            lines.append(f"首要目标: {self.primary_goal}")
        if self.active_characters:
            lines.append(f"出场角色: {', '.join(self.active_characters)}")
        if self.active_conflicts:
            lines.append(f"活跃冲突: {'; '.join(self.active_conflicts)}")
        if self.emotional_temperature:
            lines.append(f"情绪温度: {self.emotional_temperature}")
        if self.public_information:
            lines.append(f"公开信息: {'; '.join(self.public_information)}")
        if self.hidden_information:
            lines.append(f"隐藏信息: {'; '.join(self.hidden_information)}")
        if self.private_information_map:
            secret_lines = "；".join(
                f"{secret}→{','.join(knowers)}"
                for secret, knowers in self.private_information_map.items()
            )
            lines.append(f"秘密知情分布: {secret_lines}")
        if self.open_questions:
            lines.append(f"开放问题: {'; '.join(self.open_questions)}")
        if self.active_suspense_items:
            lines.append(f"未关闭悬念: {'; '.join(self.active_suspense_items)}")
        return "\n".join(lines)
