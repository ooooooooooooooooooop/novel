"""LongHorizon — 长程对账对象（design §9）.

并行维护两类状态：
- 细节账本：FactLedger / 知识 / 道具 / 时间 / 关系 / 承诺（已有状态机）；
- 滚动结构摘要：事件因果链、人物弧、未决承诺、类型/阅读机制。

在 1/3/5/10/20/30 章检查点从正文重建摘要并与滚动摘要对账；旧摘要不能无限自我继承
——每次检查点后滚动摘要以正文重建为准刷新（reconcile），未在正文落地的承诺/人物
成为漂移证据。

- `ProseSummary`：从正文重建的摘要（结构节点 / 人物提及 / 承诺提及）；
- `RollingLongHorizonSummary`：跨检查点持久化的滚动摘要；
- `LongHorizonCheckpoint`：单检查点判定（pass / block + 漂移指标）。

定位：验证/门禁产物，不进 NarrativeState 状态机。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ProseSummary(BaseModel):
    """从正文重建的结构/人物/承诺摘要（纯代码确定性提取，零 LLM）."""

    model_config = ConfigDict(extra="forbid")

    chapter_count: int = Field(ge=0, description="参与重建的章节数")
    character_mentions: dict[str, int] = Field(
        default_factory=dict, description="注册角色 {label: 全文提及次数}"
    )
    promise_mentions: dict[str, int] = Field(
        default_factory=dict, description="开放承诺 {thread_id: 全文提及次数}"
    )
    structural_nodes: list[str] = Field(
        default_factory=list, description="各章结构节点标签（可空）"
    )


class RollingLongHorizonSummary(BaseModel):
    """跨检查点持久化的滚动摘要（旧摘要不能无限自我继承：每次检查点以正文刷新）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    last_checkpoint: int = Field(ge=0, description="上次检查点章号（0=尚未检查）")
    summary: ProseSummary = Field(description="滚动摘要（正文重建 + 计划线索融合）")


class LongHorizonCheckpoint(BaseModel):
    """单检查点长程对账判定."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    checkpoint: int = Field(ge=1, description="检查点章号")
    route: Literal["pass", "block"] = Field(
        description="pass=摘要与正文一致；block=漂移超阈值（阻断继续生产）"
    )
    drift_score: float = Field(
        ge=0.0, le=1.0, description="承诺漂移占比（未在正文落地的开放承诺 / 全部开放承诺）"
    )
    drift_threshold: float = Field(
        ge=0.0, le=1.0, description="本次判定使用的冻结漂移阈值"
    )
    stale_promises: list[str] = Field(
        default_factory=list, description="滚动摘要认为开放但全文从未提及的承诺"
    )
    stale_characters: list[str] = Field(
        default_factory=list, description="滚动摘要认为活跃但全文从未提及的角色"
    )
    rebuilt_chapter_count: int = Field(ge=0, description="正文重建覆盖章数")
    rolling_chapter_count: int = Field(ge=0, description="滚动摘要覆盖章数")
    reason: str = Field(description="判定理由（block 时含漂移明细）")

    @field_validator("reason")
    @classmethod
    def _reason_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)
