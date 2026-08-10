"""ReaderContract — 读者契约（Q1 R3）.

逐作品的总体规格：读者为什么选择这本书，而不是另一本书。它回答的是「读者可信连续
叙事」的正面定义——不是逐条的禁止清单，而是可观察的阅读机制与禁例。

写成中性机制而非作者模仿（如：伤感必须被粗粝笑料和具体生活细节抵消；商业主角必须
通过具体判断和行动展现聪明；「代价」必须由人物选择触发，不能只作为设定说明）。

不进 serialization.py 状态机层（sidecar 模型，同 choicerecord/authorkernel/
readerexpectation）。构建/注入/合规检查在 src/workflow_action/reader_contract.py。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReaderContractSchemaVersion = 1


class ReaderContract(BaseModel):
    """逐作品读者契约."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    contract_id: str = Field(description="契约标识")
    audience: str = Field(description="目标读者（人群/阅读口味）")
    core_pleasures: list[str] = Field(
        description="核心阅读快感（2–4 项）——读者为什么愿意继续读"
    )
    follow_reason: str = Field(description="主角值得持续跟随的理由")
    core_tension: str = Field(description="作品核心张力（驱动每章的底层矛盾）")
    chapter_pacing: str = Field(description="合理的章节推进速度（每章应发生什么量级的事件）")
    must_keep: list[str] = Field(
        default_factory=list, description="必须保留的叙事声音和关系动力"
    )
    forbidden_drifts: list[str] = Field(
        default_factory=list, description="禁止出现的漂移（会破坏作品类型的改动）"
    )
    valid_hooks: list[str] = Field(
        default_factory=list, description="哪类结尾算有效钩子"
    )
    ending_conditions: list[str] = Field(
        default_factory=list, description="哪些情形意味着故事应结束"
    )
    opening_minimum_promise: str = Field(
        description="新开首章必须交付的最小承诺（选择/代价/独特跟随理由）"
    )
    established_at_utc: Optional[str] = Field(
        default=None, description="契约建立时间（操作者批准时间）"
    )

    @field_validator("core_pleasures")
    @classmethod
    def _core_pleasures_bounded(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("core_pleasures must not be empty")
        if len(cleaned) > 4:
            raise ValueError("core_pleasures limited to 2–4 items")
        return cleaned

    @field_validator(
        "audience", "follow_reason", "core_tension", "chapter_pacing",
        "opening_minimum_promise",
    )
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("ReaderContract text fields must not be blank")
        return value.strip()

    @field_validator(
        "must_keep", "forbidden_drifts", "valid_hooks", "ending_conditions"
    )
    @classmethod
    def _list_non_blank(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    def to_prompt_context(self) -> str:
        """渲染【读者契约】段（注入 Continue/Prose prompt 用）。"""
        lines = [
            f"目标读者: {self.audience}",
            f"核心阅读快感: {' / '.join(self.core_pleasures)}",
            f"主角值得跟随: {self.follow_reason}",
            f"核心张力: {self.core_tension}",
            f"章节推进: {self.chapter_pacing}",
        ]
        if self.must_keep:
            lines.append("必须保留: " + "；".join(self.must_keep))
        if self.forbidden_drifts:
            lines.append("禁止漂移: " + "；".join(self.forbidden_drifts))
        if self.valid_hooks:
            lines.append("有效钩子: " + "；".join(self.valid_hooks))
        if self.opening_minimum_promise:
            lines.append(f"首章最小承诺: {self.opening_minimum_promise}")
        return "\n".join(lines)
