"""ReaderReport — 读者体验审查报告对象.

对应 docs/03_rules/10_reader_experience_rules.md 的分级标注产物。
不是叙事状态（不进 NarrativeState/Frame/FactLedger 状态机），
是「正文层读者体验审查」的独立产物，供人工/精修参考，不阻断流程。

定位：核心2（读者体验）的验证对象。与核心1（一致性）的 ReviewIssue 分离——
ReviewIssue 可阻断（route），ReaderReport 恒不阻断（route=none）。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# 7 维判定维度（docs/03_rules/10_reader_experience_rules.md §3）
READER_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("open", "开头是否拖沓"),
    ("presence", "场景是否具有现场感"),
    ("info", "解释是否过多"),
    ("dialogue", "对白是否自然"),
    ("emotion", "情绪是否真正落地"),
    ("payoff", "高潮是否得到反馈"),
    ("hook", "章末钩子是否有足够信息量"),
)

# 分级档位：good / needs_work / weak
READER_GRADES: tuple[str, ...] = ("good", "needs_work", "weak")


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ReaderDimension(BaseModel):
    """单一维度的分级标注."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "open", "presence", "info", "dialogue", "emotion", "payoff", "hook"
    ] = Field(description="维度标识")
    name: str = Field(description="维度名称")
    grade: Literal["good", "needs_work", "weak"] = Field(description="分级档位")
    anchor: str = Field(description="位置锚点（如 第1-2段/改写完成段）")
    diagnosis: str = Field(description="一句诊断（为什么是这个档位）")
    fix_direction: str = Field(
        default="", description="改法方向（空串=无需修改）"
    )

    @field_validator("name", "anchor", "diagnosis")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class ReaderExperienceReport(BaseModel):
    """章节读者体验审查报告."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, description="Schema 版本")
    review_target: str = Field(description="审查目标（章节路径/标识）")
    chapter_id: Optional[str] = Field(
        default=None, description="章节标识（如 chapter_1）"
    )
    dimensions: list[ReaderDimension] = Field(
        description="7 维分级标注列表"
    )
    overall: Literal["good", "needs_work", "weak"] = Field(
        description="总体档位（取 7 维中最差档；钩子权重最高，作为 tie-break）"
    )
    route: Literal["none"] = Field(
        default="none", description="恒 none——不阻断流程，供人工/精修参考"
    )

    @field_validator("review_target")
    @classmethod
    def _target_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("dimensions")
    @classmethod
    def _dimensions_cover_all_seven(
        cls, values: list[ReaderDimension], info: ValidationInfo
    ) -> list[ReaderDimension]:
        if not values:
            raise ValueError("dimensions must not be empty")
        present = {d.dimension for d in values}
        expected = {dim for dim, _ in READER_DIMENSIONS}
        missing = expected - present
        if missing:
            raise ValueError(
                f"dimensions missing required dimension(s): {sorted(missing)}"
            )
        return values
