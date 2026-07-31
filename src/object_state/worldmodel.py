"""WorldModel — 世界模型定义."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class WorldModel(BaseModel):
    """世界规则与约束模型。

    定义"这个世界允许什么发生"。
    不是装饰性设定堆砌，而是可约束叙事的规则集合。
    """

    model_config = ConfigDict(extra="forbid")

    world_facts: list[str] = Field(
        default_factory=list, description="已确认的世界事实"
    )
    social_structure: Optional[str] = Field(
        default=None, description="社会结构，如宗门-王城-世家三方制衡"
    )
    power_system: Optional[str] = Field(
        default=None, description="力量体系，如灵根等级、禁术系统"
    )
    resource_system: Optional[str] = Field(
        default=None, description="资源与代价机制"
    )
    geography: Optional[str] = Field(default=None, description="地理概况")
    factions: list[str] = Field(default_factory=list, description="势力/派系列表")
    time_rules: list[str] = Field(
        default_factory=list, description="时间规则，如试炼周期、宗门纪年"
    )
    prohibitions: list[str] = Field(
        default_factory=list, description="禁止事项，如王城内公开斗法"
    )
    consequence_logic: list[str] = Field(
        default_factory=list, description="后果逻辑，如禁术使用留下可追踪痕迹"
    )

    @field_validator(
        "world_facts",
        "factions",
        "time_rules",
        "prohibitions",
        "consequence_logic",
    )
    @classmethod
    def _rule_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def validate_event(self, event_description: str) -> tuple[bool, list[str]]:
        """验证事件是否符合世界规则.

        Returns:
            (是否合法, 违规原因列表). 空列表表示合法.
        """
        violations = []
        for prohibition in self.prohibitions:
            if prohibition in event_description or self._matches_prohibition(
                prohibition, event_description
            ):
                violations.append(f"违反禁止项: {prohibition}")
        return len(violations) == 0, violations

    def _matches_prohibition(self, prohibition: str, event_description: str) -> bool:
        """匹配常见的“地点/条件 + 禁止 + 行为”规则."""
        if "禁止" not in prohibition:
            return False
        context, action = prohibition.split("禁止", 1)
        return bool(
            context
            and action
            and context in event_description
            and action in event_description
        )

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = ["【世界规则】"]
        if self.power_system:
            lines.append(f"力量体系: {self.power_system}")
        if self.resource_system:
            lines.append(f"资源机制: {self.resource_system}")
        if self.social_structure:
            lines.append(f"社会结构: {self.social_structure}")
        if self.geography:
            lines.append(f"地理环境: {self.geography}")
        if self.factions:
            lines.append(f"主要势力: {', '.join(self.factions)}")
        if self.time_rules:
            lines.append(f"时间规则: {'; '.join(self.time_rules)}")
        if self.prohibitions:
            lines.append(f"禁止事项: {'; '.join(self.prohibitions)}")
        if self.consequence_logic:
            lines.append(f"后果逻辑: {'; '.join(self.consequence_logic)}")
        if self.world_facts:
            lines.append(f"已知事实: {'; '.join(self.world_facts)}")
        return "\n".join(lines)
