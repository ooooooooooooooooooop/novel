"""WorkSpec — 作品规格定义."""

from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    ValidationInfo,
    field_validator,
)

from .timebook import TimeInitial


class WorkSpec(BaseModel):
    """顶层作品规格。

    定义"这部作品要成为什么"。
    不存储故事内容，不存储场景级规划。
    """

    model_config = ConfigDict(extra="forbid")

    genre: str = Field(description="作品类型，如仙侠、科幻、都市")
    subgenre: Optional[str] = Field(default=None, description="子类型，如宗门成长、赛博朋克")
    audience: str = Field(description="目标读者群体")
    theme: str = Field(description="核心主题，如成长、代价、命运")
    tone: str = Field(description="叙事调性，如克制、热血、暗黑")
    pacing: str = Field(description="节奏策略，如前快中稳后爆")
    structure_template: Optional[str] = Field(
        default=None,
        description="结构模板名称，如 eight_node / three_act / compressed_three_act",
    )
    platform: Optional[str] = Field(
        default=None,
        description="目标平台标识，如 web_novel_daily / web_novel_serial / short_form_burst",
    )
    temperament: Optional[str] = Field(
        default=None,
        description="叙事气质（散文型/戏剧型/信息型/氛围型）；compose 用它作为风格先验，无 StyleProfile 时注入气质桶指导",
    )
    length_target: Optional[StrictInt] = Field(
        default=None,
        ge=0,
        description="目标字数或章节数",
    )
    constraints: list[str] = Field(default_factory=list, description="内容约束列表")
    time: Optional[TimeInitial] = Field(
        default=None,
        description="时间域起点设定（可选；compose 用它初始化 TimeBook 初稿）",
    )
    romance_weight: Optional[StrictFloat] = Field(
        default=None, ge=0.0, le=1.0, description="浪漫元素权重 0-1"
    )
    mystery_weight: Optional[StrictFloat] = Field(
        default=None, ge=0.0, le=1.0, description="悬疑元素权重 0-1"
    )
    action_weight: Optional[StrictFloat] = Field(
        default=None, ge=0.0, le=1.0, description="动作元素权重 0-1"
    )

    @field_validator("genre", "audience", "theme", "tone", "pacing")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("constraints")
    @classmethod
    def _constraint_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = [
            f"作品类型: {self.genre}",
            f"子类型: {self.subgenre or '未指定'}",
            f"目标读者: {self.audience}",
            f"核心主题: {self.theme}",
            f"叙事调性: {self.tone}",
            f"节奏策略: {self.pacing}",
        ]
        if self.structure_template:
            lines.append(f"结构模板: {self.structure_template}")
        if self.platform:
            lines.append(f"目标平台: {self.platform}")
        if self.temperament:
            lines.append(f"叙事气质: {self.temperament}")
        if self.length_target:
            lines.append(f"目标长度: {self.length_target}")
        if self.constraints:
            lines.append(f"内容约束: {', '.join(self.constraints)}")
        weights = []
        if self.romance_weight is not None:
            weights.append(f"浪漫{self.romance_weight:.0%}")
        if self.mystery_weight is not None:
            weights.append(f"悬疑{self.mystery_weight:.0%}")
        if self.action_weight is not None:
            weights.append(f"动作{self.action_weight:.0%}")
        if weights:
            lines.append(f"元素权重: {', '.join(weights)}")
        return "\n".join(lines)
