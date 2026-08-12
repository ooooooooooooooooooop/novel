"""QualityThresholds — 自动评审校准阈值 / holdout 报告对象.

T7（design §10）：把评审器（fact_judge / character_judge / reader_judge）校准到
冻结的人类偏好基准上，再从 calibration 划分生成不可变阈值，最后在 holdout 划分上
验证——阈值一旦冻结不得根据 holdout 调整（T7.6）。

- `PreferencePair`：基准单行（写作 prompt + 人类偏好 chosen/rejected，来源隐藏）；
- `JudgePreferencePrediction`：评审对单对的预测（A/B/no_difference）与人类标签对照；
- `AccuracyReport`：总体 + 分类型准确率 + Wilson 95% 下界 + 弃权数；
- `QualityThresholds`：holdout 前从 calibration 冻结的阈值（含 calibration 统计）；
- `HoldoutReport`：holdout 验证结果（不得作为阈值调参输入）。

定位：与人类读者校准（CalibrationReport）正交——本模块校准**自动评审器**，
CalibrationReport 校准**人类读者门**。都是验证产物，不进 NarrativeState 状态机。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class PreferencePair(BaseModel):
    """基准单行：写作 prompt + 人类偏好 chosen / rejected（对评审隐藏哪份是偏好）."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(description="基准行 prompt_id（划分单位）")
    tag: str = Field(description="类型标签（如 悬疑-推理故事 / 仙侠小说）")
    prompt: str = Field(description="写作 prompt（评审需要读它才能判断优劣）")
    chosen: str = Field(description="人类偏好响应正文")
    rejected: str = Field(description="人类不偏好响应正文")
    split: Literal["calibration", "holdout"] = Field(
        description="所属划分：calibration 或 holdout（严格分离）"
    )
    bucket: int = Field(ge=0, description="划分桶号（manifest 记录）")

    @field_validator("prompt_id", "tag", "prompt", "chosen", "rejected")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class JudgePreferencePrediction(BaseModel):
    """评审对单对的预测：A/B/no_difference + 人类标签 + 是否命中."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(description="基准行 prompt_id")
    tag: str = Field(description="类型标签")
    role: str = Field(description="评审角色（fact_judge/character_judge/reader_judge）")
    predicted: Literal["A", "B", "no_difference"] = Field(
        description="评审预测：A=选甲，B=选乙，no_difference=无法分辨（弃权）"
    )
    human_label: Literal["chosen", "rejected"] = Field(
        description="人类实际偏好的响应（chosen/rejected），对照基准标签"
    )
    correct: bool = Field(description="预测与人类偏好一致（no_difference 恒 False=弃权）")


class AccuracyReport(BaseModel):
    """总体 + 分类型准确率 + Wilson 95% 置信下界."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=0, description="预测样本数（含弃权）")
    abstain_count: int = Field(ge=0, description="no_difference 弃权数")
    overall_accuracy: float = Field(
        ge=0.0, le=1.0, description="总体准确率（正确 / 非弃权样本）"
    )
    per_tag_accuracy: dict[str, float] = Field(
        description="分类型准确率 {tag: accuracy}"
    )
    per_tag_n: dict[str, int] = Field(description="分类型样本数 {tag: n}")
    wilson_low: float = Field(
        ge=0.0, le=1.0, description="总体准确率的 Wilson 95% 置信下界"
    )


class QualityThresholds(BaseModel):
    """holdout 前从 calibration 冻结的评审阈值（T7.6 禁止据 holdout 调参）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    thresholds_id: str = Field(description="阈值记录标识（含 policy/基准哈希前缀）")
    role: str = Field(
        description="被校准评审角色（fact_judge/character_judge/reader_judge）"
    )
    policy_id: str = Field(description="来源策略 id")
    policy_sha256: str = Field(description="来源策略 canonical SHA-256")
    preference_source_sha256: str = Field(
        description="偏好基准源文件 SHA-256（冻结）"
    )
    preference_split_manifest_sha256: str = Field(
        description="偏好划分 manifest SHA-256（冻结）"
    )
    human_distribution_manifest_sha256: str = Field(
        description="人类作品分布 manifest SHA-256（冻结）"
    )
    generated_from: Literal["calibration_split"] = Field(
        default="calibration_split",
        description="阈值唯一合法来源：calibration 划分（禁止从 holdout 生成）",
    )
    frozen_at: str = Field(description="冻结时间（ISO UTC）")
    frozen_by_run: str = Field(description="冻结操作的 run id")
    overall_accuracy_min: float = Field(
        ge=0.0, le=1.0, description="holdout 总体准确率下界（预注册）"
    )
    per_tag_accuracy_min: float = Field(
        ge=0.0, le=1.0, description="holdout 分类型准确率下界（预注册）"
    )
    position_consistency_min: float = Field(
        ge=0.0, le=1.0, description="holdout A/B 换位稳定率下界（预注册）"
    )
    calibration_stats: AccuracyReport = Field(
        description="calibration 划分观察统计（阈值的证据基础）"
    )
    calibration_span: dict[str, int] = Field(
        description="calibration 覆盖广度 {distinct_prompt_ids, distinct_tags}（"
        "单一读者/模型/作品不得产生生产阈值）"
    )

    @field_validator("thresholds_id", "policy_id", "policy_sha256", "frozen_by_run")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class HoldoutReport(BaseModel):
    """holdout 验证结果（阈值已冻结，报告只判达标与否，不回写阈值）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    run_id: str = Field(description="holdout 运行的 run id")
    thresholds_id: str = Field(description="被验证的冻结阈值 id（只读）")
    split: Literal["holdout"] = Field(default="holdout")
    overall_accuracy: float = Field(ge=0.0, le=1.0)
    per_tag_accuracy: dict[str, float] = Field(description="分类型准确率 {tag: acc}")
    position_consistency: float = Field(ge=0.0, le=1.0)
    met: bool = Field(description="全部维度达标")
    dimension_met: dict[str, bool] = Field(
        description="逐维度达标 {overall, per_tag, position_consistency}"
    )
    violations: list[str] = Field(default_factory=list, description="未达标维度说明")
    run_at: str = Field(description="运行时间（ISO UTC）")
    abstain_count: int = Field(ge=0, default=0, description="弃权样本数")
