"""SceneExperience — 场景体验中间层（核心2：读者体验的生成侧先验）.

对应方向文档第四节：补从抽象情节结构到具体场景体验之间的连接。
PlotUnit 描述「发生了什么/改变了什么/释放了什么/产生了什么后果」；
读者实际感受到的是「主角看见了什么/遇到什么阻碍/为什么选择/结果如何/情绪认知怎么变」。

SceneExperience 把结构「翻译」成读者体验的五个具体维度，作为正文展开的先验。
与 StyleProfile 同类：是规格（spec）不是叙事状态，不进状态机。

用法：作为 PlotUnit 的可选字段 scene_experience（空=不渲染，与旧版逐字节一致）。
Continue 生成 PlotUnit 时同时生成 SceneExperience；Prose 展开时注入，
让结构扩写带现场感（避免「解释充分但缺乏现场感的正文」）。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class SceneExperience(BaseModel):
    """单一场景的读者体验中间层."""

    model_config = ConfigDict(extra="forbid")

    protagonist_sees: str = Field(
        description="主角看见了什么——本场景的感官焦点（一个决定性物象/场景），"
        "不是概述，是能落在读者眼里的具体画面"
    )
    obstacles: list[str] = Field(
        default_factory=list,
        description="遇到了什么阻碍——本场景挡在目标前的具体阻力（人/规则/信息差/环境）",
    )
    choice_grounding: str = Field(
        description="为什么作出选择——主角决策的身份/信念/压力依据，"
        "避免『剧情需要』式无依据选择（决策依据轴落地）"
    )
    outcome: str = Field(
        description="选择产生了什么结果——本场景的可见后果/反馈（读者知道成/败/变）",
    )
    cognition_shift: str = Field(
        description="情绪和认知如何变化——从『之前怎么想』到『现在怎么想』，"
        "读者看到思考链条而非结论",
    )

    @field_validator("protagonist_sees", "choice_grounding", "outcome", "cognition_shift")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("obstacles")
    @classmethod
    def _obstacles_must_be_non_blank(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def to_prompt_context(self, unit_id: str = "") -> str:
        """生成给 LLM 的上下文描述（Prose 展开时注入）."""
        header = f"【场景体验: {unit_id}】" if unit_id else "【场景体验】"
        lines = [header]
        lines.append(f"主角看见: {self.protagonist_sees}")
        if self.obstacles:
            lines.append(f"阻碍: {'; '.join(self.obstacles)}")
        lines.append(f"选择依据: {self.choice_grounding}")
        lines.append(f"结果: {self.outcome}")
        lines.append(f"认知变化: {self.cognition_shift}")
        return "\n".join(lines)
