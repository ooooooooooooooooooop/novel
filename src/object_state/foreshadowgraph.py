"""ForeshadowGraph — 伏笔图定义."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class ForeshadowEntry(BaseModel):
    """单条伏笔/承诺/误导."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(description="线索唯一标识")
    setup_point: str = Field(description="埋设点, 如'第3章末尾神秘人影'")
    content: str = Field(description="内容, 如'主角身世之谜'")
    visibility_level: Literal["explicit", "implicit"] = Field(
        description="显性(读者明显感知)或隐性(细节暗示)"
    )
    expected_payoff: str = Field(description="预期回收方式")
    current_status: Literal["active", "resolved", "abandoned", "transformed"] = Field(
        default="active", description="当前状态"
    )
    expiry_risk: Optional[str] = Field(
        default=None, description="过期风险, 如'若5章内未回收则失效'"
    )

    # 轻量引用
    linked_characters: list[str] = Field(
        default_factory=list, description="关联角色ID"
    )
    linked_facts: list[str] = Field(
        default_factory=list, description="关联 FactLedger.fact_id"
    )
    linked_plotunits: list[str] = Field(
        default_factory=list, description="关联 PlotUnit.unit_id"
    )

    @field_validator("thread_id", "setup_point", "content", "expected_payoff")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("linked_characters", "linked_facts", "linked_plotunits")
    @classmethod
    def _linked_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


class ForeshadowGraph(BaseModel):
    """伏笔与承诺追踪图.

    记录"系统答应过读者什么".
    不是松散备注列表.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[ForeshadowEntry] = Field(
        default_factory=list, description="伏笔条目列表"
    )

    def get_active(self) -> list[ForeshadowEntry]:
        """获取未回收的活跃承诺."""
        return [e for e in self.entries if e.current_status == "active"]

    def get_expired_risk(self) -> list[ForeshadowEntry]:
        """获取有过期风险的条目."""
        return [e for e in self.entries if e.expiry_risk is not None]

    def resolve(self, thread_id: str) -> bool:
        """标记为已回收."""
        for e in self.entries:
            if e.thread_id == thread_id:
                e.current_status = "resolved"
                return True
        return False

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        active = self.get_active()
        if not active:
            return "【伏笔图】无活跃承诺"
        lines = ["【活跃承诺/伏笔】"]
        for e in active:
            vis = "显性" if e.visibility_level == "explicit" else "隐性"
            lines.append(f"- [{vis}] {e.content} (埋设: {e.setup_point})")
            if e.expiry_risk:
                lines.append(f"  风险: {e.expiry_risk}")
        return "\n".join(lines)
