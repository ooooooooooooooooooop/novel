"""FactLedger — 事实账本定义."""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
)


class FactEntry(BaseModel):
    """单条已确认事实."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(description="事实唯一标识")
    statement: str = Field(description="事实陈述, 如'令牌归c001所有'")
    fact_type: Literal[
        "event", "relation", "rule", "object", "time_order", "reveal_status"
    ] = Field(description="事实类型")
    involved_entities: list[str] = Field(
        default_factory=list, description="涉及实体ID(角色/地点/组织/物品)"
    )
    source_plotunit: Optional[str] = Field(
        default=None, description="来源 PlotUnit.unit_id"
    )
    confirmed: StrictBool = Field(default=False, description="是否已确认")
    timestamp: Optional[str] = Field(default=None, description="叙事时间戳")

    @field_validator("fact_id", "statement")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("source_plotunit")
    @classmethod
    def _optional_source_ref_must_be_non_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("source_plotunit must be non-empty when provided")
        return value

    @field_validator("involved_entities")
    @classmethod
    def _entity_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def to_prompt_line(self) -> str:
        status = "✓" if self.confirmed else "?"
        return f"{status} [{self.fact_type}] {self.statement}"


class FactLedger(BaseModel):
    """事实账本.

    记录"哪些东西已经算数了".
    只存 hard fact, 不存推断、怀疑或运行时压力.
    Track 1 核心对象.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[FactEntry] = Field(default_factory=list, description="事实条目列表")

    def add_fact(self, entry: FactEntry) -> None:
        """添加事实(不自动确认, 确认需经 Review)."""
        self.entries.append(entry)

    def confirm_fact(self, fact_id: str) -> bool:
        """确认单条事实. 返回是否成功."""
        for e in self.entries:
            if e.fact_id == fact_id:
                e.confirmed = True
                return True
        return False

    def get_confirmed(self) -> list[FactEntry]:
        """获取已确认事实."""
        return [e for e in self.entries if e.confirmed]

    def get_by_type(self, fact_type: str) -> list[FactEntry]:
        """按类型筛选."""
        return [e for e in self.entries if e.fact_type == fact_type]

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        if not self.entries:
            return "【事实账本】空"
        lines = ["【事实账本】"]
        for e in self.entries:
            lines.append(e.to_prompt_line())
        return "\n".join(lines)
