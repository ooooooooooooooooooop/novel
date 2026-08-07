"""CharacterUpdate — 角色受后果而变的中间对象（作者性 Phase A 地基）.

定位：与 TimeBook / ChoiceLedger 同类——sidecar spec，不进 serialization.py
状态机层（不污染 stable serialization）。
不允许每章直接覆盖整个 CharacterModel；而是把 PlotUnit consequence 翻译成一条
「受控的角色变更提案」：默认落 sidecar 只记录，`--character-update on` 时才
apply 到 CharacterModel 的动态字段（current_pressure / change_trajectory /
relation_behaviors，charactermodel.py:57-74），记 before/after。

五种变化（对应纲领 §7，不能只有「事件→成长」）：
- reinforce    : 原有信念被加强（信任朋友后再遭利用 → 「不能信人」更强）
- shift        : 真正方向性变化（只能靠自己 → 开始有限度托付）
- destabilize  : 信念开始动摇但没有新答案
- unresolved   : 事情发生了，人物目前不知道这意味着什么（非常重要的合法状态）
- misinterpret : 人物得出错误结论（错误理解本身可成为后续发展的重要部分）

零成本契约：off 时不调用、不改 prompt、不产文件；本对象全字段默认安全，
旧代码无感知。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

UpdateType = Literal[
    "reinforce", "shift", "destabilize", "unresolved", "misinterpret"
]
AffectedDimension = Literal[
    "fear", "goal", "relation", "self_image", "pressure", "trajectory"
]
Permanence = Literal["transient", "medium", "long"]
Status = Literal["proposed", "applied", "rejected", "archived"]


class CharacterUpdate(BaseModel):
    """单条角色变更提案."""

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(description="目标角色 ID")
    trigger: str = Field(
        description="来源 PlotUnit / 事件（admit 时自动填充来源 unit_id）"
    )
    observed_consequence: str = Field(description="实际发生了什么")
    affected_dimension: AffectedDimension = Field(description="受影响的维度")
    update_type: UpdateType = Field(description="五种变化类型之一")
    proposed_after: str = Field(description="候选新状态")
    before: Optional[str] = Field(default=None, description="原状态（apply 时填充）")
    evidence: Optional[str] = Field(default=None, description="支撑证据")
    permanence: Permanence = Field(
        default="medium",
        description="影响持续性：transient / medium / long",
    )
    confidence: float = Field(
        default=0.5,
        description="置信度 0-1（≥阈值且 permanence=long 才 auto-apply）",
    )
    status: Status = Field(
        default="proposed",
        description="proposed / applied / rejected / archived",
    )

    @field_validator("character_id", "trigger", "observed_consequence", "proposed_after")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("evidence")
    @classmethod
    def _opt_text_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(
        cls, value: float, info: ValidationInfo
    ) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{info.field_name} must be in [0, 1]")
        return value
