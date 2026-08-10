"""SerialReaderReport — 连续章/窗口读者审查报告对象.

Q1 Phase 4（单章与滑动窗口读者门禁）的窗口层产物。对应
docs/03_rules/10_reader_experience_rules.md 的相邻章/窗口审查维度。

与 ReaderExperienceReport（单章 7 维）平行：
- 单章报告回答「这一章好不看好」；
- 本报告回答「连续几章读起来是否连续可信、是否在重复」。

定位：与 ReaderExperienceReport 一致——**不是叙事状态**（不进
NarrativeState/Frame/FactLedger 状态机），是正文层连续阅读审查的独立产物。
route 恒为 "none"（报告是原始证据，路由由 ReaderQualityGatePolicy 决定，
不静默放行也不自封阻断）。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from src.object_state.reviewissue import ReviewIssueType

# 连续章/窗口审查维度（docs/03_rules/10_reader_experience_rules.md §3.4 扩展）
SERIAL_READER_DIMENSIONS: tuple[tuple[str, str], ...] = (
    # --- 相邻章门禁 ---
    ("reask_resolved", "上一章已回答的问题是否被重新提问"),
    ("reset_without_event", "人物/道具/时间/地点是否被无事件重置"),
    ("scene_replay", "是否重演上一章已完成的场景"),
    ("process_text", "是否出现「上一章末」「本章」等编辑/生成过程文字"),
    ("mechanical_recap", "开头是否在机械复述上一章结尾"),
    # --- 三至五章窗口门禁 ---
    ("repeated_insight", "是否连续反复使用同一顿悟"),
    ("psych_summary_only", "是否多章只推进心理总结而无外部变化"),
    ("repeated_ending", "是否反复使用同一种结尾结构"),
    ("expectation_stall", "ReaderExpectation 是否真正推进"),
    ("narrowing_methods", "主角解决问题方式是否越来越单一"),
    ("pleasure_dilution", "原作阅读快感是否被生成文本自身逐步稀释"),
    ("contract_drift", "是否偏离 ReaderContract 声明的核心阅读机制"),
)

SerialReaderDimension = Literal[
    "reask_resolved",
    "reset_without_event",
    "scene_replay",
    "process_text",
    "mechanical_recap",
    "repeated_insight",
    "psych_summary_only",
    "repeated_ending",
    "expectation_stall",
    "narrowing_methods",
    "pleasure_dilution",
    "contract_drift",
]

# 相邻章维度（objective 级硬错误候选）与窗口维度（审美级候选）分组
ADJACENT_DIMENSIONS = frozenset(
    {
        "reask_resolved",
        "reset_without_event",
        "scene_replay",
        "process_text",
        "mechanical_recap",
    }
)
WINDOW_DIMENSIONS = frozenset(
    {
        "repeated_insight",
        "psych_summary_only",
        "repeated_ending",
        "expectation_stall",
        "narrowing_methods",
        "pleasure_dilution",
        "contract_drift",
    }
)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class SerialReaderFinding(BaseModel):
    """一条连续阅读审查发现（问题维：needs_work/weak 才入 findings）.

    grade：问题档位（needs_work/weak）。
    severity=objective：客观连续性/生成痕迹硬错误（门禁策略映射 block）；
    severity=aesthetic：审美/节奏分歧（门禁策略映射 rewrite 或人工决定点）。
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(description="发现标识")
    dimension: SerialReaderDimension = Field(description="维度标识")
    grade: Literal["needs_work", "weak"] = Field(
        description="问题档位（good 维不入 findings）"
    )
    severity: Literal["objective", "aesthetic"] = Field(
        description="objective=硬错误可阻断；aesthetic=审美分歧可修/人工"
    )
    issue_type: ReviewIssueType = Field(description="映射到现有 ReviewIssueType")
    evidence: str = Field(description="正文证据片段/位置锚点")
    location: str = Field(description="位置（如 第2章 中段）")
    diagnosis: str = Field(description="诊断（为什么是问题）")
    fix_direction: str = Field(
        default="", description="改法方向（空串=无需修改）"
    )

    @field_validator("finding_id", "evidence", "location", "diagnosis")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class SerialReaderReport(BaseModel):
    """连续章/窗口读者审查报告."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, description="Schema 版本")
    window: int = Field(ge=1, description="窗口大小（1/3/5）")
    review_target: str = Field(description="审查目标（最后章节路径/标识）")
    chapter_refs: list[str] = Field(
        description="窗口内章节标识列表（从旧到新）"
    )
    findings: list[SerialReaderFinding] = Field(
        description="连续阅读审查发现列表"
    )
    overall: Literal["good", "needs_work", "weak"] = Field(
        description="窗口总体档位（发现越严重越差）"
    )
    route: Literal["none"] = Field(
        default="none",
        description="恒 none——报告是原始证据，路由由 ReaderQualityGatePolicy 决定",
    )

    @field_validator("window")
    @classmethod
    def _window_is_supported(cls, value: int, info: ValidationInfo) -> int:
        if value not in (1, 3, 5):
            raise ValueError(f"window must be one of 1/3/5, got {value}")
        return value

    @field_validator("review_target")
    @classmethod
    def _target_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("chapter_refs")
    @classmethod
    def _refs_cover_window(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if not values:
            raise ValueError("chapter_refs must not be empty")
        if info.data.get("window", 1) > 1 and len(values) < 2:
            raise ValueError(
                "chapter_refs must list all chapters in the window (>=2 for window>1)"
            )
        return values

    @field_validator("findings")
    @classmethod
    def _findings_dimensions_valid(
        cls, values: list[SerialReaderFinding], info: ValidationInfo
    ) -> list[SerialReaderFinding]:
        valid = {dim for dim, _ in SERIAL_READER_DIMENSIONS}
        for finding in values:
            if finding.dimension not in valid:
                raise ValueError(
                    f"finding {finding.finding_id} dimension "
                    f"'{finding.dimension}' not in {sorted(valid)}"
                )
        return values
