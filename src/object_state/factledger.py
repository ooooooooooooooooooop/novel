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


class ValidityInterval(BaseModel):
    """事实的有效时间区间.

    可选字段, None 表示开放边界(未声明起点或终点).
    """

    model_config = ConfigDict(extra="forbid")

    valid_from: Optional[str] = Field(
        default=None, description="有效起点(叙事时间), 如'第三章'"
    )
    valid_until: Optional[str] = Field(
        default=None, description="有效终点(叙事时间), 如'第五章'"
    )

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _bound_must_be_non_blank_when_provided(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value

    def to_prompt_suffix(self) -> str:
        """渲染有效性后缀, 如 '(第三章~第五章)'. 开放边界用 '~' 表示, 无边界省略."""
        if self.valid_from is None and self.valid_until is None:
            return ""
        if self.valid_from is not None and self.valid_until is not None:
            return f"({self.valid_from}~{self.valid_until})"
        if self.valid_from is not None:
            return f"({self.valid_from}~)"
        return f"(~{self.valid_until})"


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
    validity_interval: Optional[ValidityInterval] = Field(
        default=None, description="有效时间区间, None=始终有效"
    )
    known_by: list[str] = Field(
        default_factory=list,
        description="事实知情角色ID（事实层信息凭证 P3：谁知晓该事实）",
    )
    chronological_order: Optional[str] = Field(
        default=None, description="时间顺序标记, 如'发生于令牌转移之前'"
    )

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

    @field_validator("involved_entities", "known_by")
    @classmethod
    def _entity_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("chronological_order")
    @classmethod
    def _optional_chrono_must_be_non_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("chronological_order must be non-empty when provided")
        return value

    def to_prompt_line(self) -> str:
        status = "✓" if self.confirmed else "?"
        suffix = (
            self.validity_interval.to_prompt_suffix()
            if self.validity_interval is not None
            else ""
        )
        line = f"{status} [{self.fact_type}]{suffix} {self.statement}"
        if self.known_by:
            line += f" [知: {','.join(self.known_by)}]"
        if self.chronological_order:
            line += f" [{self.chronological_order}]"
        return line


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

    def to_timeline_context(self, include_header: bool = True) -> str:
        """渲染【已发生事件时间线】— 按叙事时间序排列的已确认事件.

        零 LLM 纯代码：只取 confirmed 的 event/time_order/relation 事实，
        按 timestamp / validity_interval.valid_from / 原序 排序。
        空账本或无事件事实时返回 ""（静默降级，不产生注入字节）。
        include_header=False 时跳过【已发生事件时间线】首行（双层段头修复：
        消费方 continuation.py 独占外层段头，loader 只产正文）。
        """
        ordered = [
            e
            for e in self.entries
            if e.confirmed and e.fact_type in ("event", "time_order", "relation")
        ]
        if not ordered:
            return ""

        def _sort_key(e: FactEntry):
            if e.timestamp:
                return (0, e.timestamp)
            if e.validity_interval is not None and e.validity_interval.valid_from:
                return (1, e.validity_interval.valid_from)
            return (2, "")

        ordered = sorted(ordered, key=_sort_key)
        lines: list[str] = []
        if include_header:
            lines.append("【已发生事件时间线】")
        for i, e in enumerate(ordered, 1):
            suffix = (
                e.validity_interval.to_prompt_suffix()
                if e.validity_interval is not None
                else ""
            )
            ts = f"({e.timestamp})" if e.timestamp else ""
            lines.append(f"{i}. {e.statement}{suffix}{ts}")
        return "\n".join(lines)
