"""AuthorModel V3 数据模型 (P5).

根据 docs/00_project/52_mastery_upgrade_plan.md §6:
1. 四层清晰分离：
   - StyleProfile (怎么表达，修辞/句法/词汇)
   - AuthorModel (作者如何跨作品选择，决策先验)
   - WorkModel (本作品如何组织，类型/调性/设定)
   - TasteModel (哪些偏离常规的创新值得保留)
2. AuthorPrincipleV3:
   - 支撑样本 (supporting_samples)
   - 反例 (counterexamples，来自 Hindsight 回看结果)
   - 适用边界 (applicable_boundary)
   - 置信度与状态演化 (confidence / status)
   - 作用域 (scope: author_global / work_local / genre_local)
3. 跨作品验证契约 (CrossWorkValidationContract):
   - 留一作品验证 (Leave-One-Work-Out)
   - 词汇泄漏检测 (防止把作品专有名词当作作者全局原则)
"""

from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupportingSample(BaseModel):
    """支持该原则的真实决策样本."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(description="决策 ID")
    work_name: str = Field(description="所属作品名")
    chapter_number: Optional[int] = Field(default=None, description="章节编号")
    context_summary: str = Field(description="决策情境摘要")
    chosen_action: str = Field(description="选中的行动方案")
    rejected_actions: list[str] = Field(default_factory=list, description="被否决的方案")
    tradeoff_rationale: str = Field(description="放弃即时便利换取长期价值的理由")


class CounterexampleSample(BaseModel):
    """违反或挑战该原则的反例样本（来自 Hindsight 判定）."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(description="决策 ID")
    work_name: str = Field(description="所属作品名")
    chapter_number: Optional[int] = Field(default=None, description="章节编号")
    hindsight_status: Literal["overturned", "partial_regret", "complex"] = Field(
        description="回看判定"
    )
    observed_consequence: str = Field(description="几章后观察到的真实不良后果或代价失衡")
    deviation_reason: str = Field(description="为何在此情境下旧原则不再适用或需要修正边界")


class AuthorPrincipleV3(BaseModel):
    """动态作者决策原则 (V3)."""

    model_config = ConfigDict(extra="forbid")

    principle_id: str = Field(description="原则唯一标识（如 ap_character_causality_01）")
    statement: str = Field(description="原则陈述（一句话中性方法论）")
    value_vocab_key: str = Field(description="映射的受限价值词汇表键")
    scope: Literal["author_global", "work_local", "genre_local"] = Field(
        default="author_global",
        description="作用域：作者全局（跨作品稳定）/ 作品局部（单书组织习惯）/ 题材局部",
    )
    applicable_boundary: str = Field(
        default="通用", description="适用边界与例外条件（何时生效、何时退让）"
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="置信度（随反例与支持样本动态校准）"
    )
    status: Literal["candidate", "weak", "stable", "contested", "deprecated"] = Field(
        default="candidate", description="原则生命周期状态"
    )
    supporting_samples: list[SupportingSample] = Field(
        default_factory=list, description="支持该原则的历史选择证据"
    )
    counterexamples: list[CounterexampleSample] = Field(
        default_factory=list, description="反例与挑战证据"
    )
    first_formed_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    last_updated: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def update_status_from_evidence(self) -> None:
        """根据支持样本与反例数量及比例自动校准置信度与状态."""
        n_sup = len(self.supporting_samples)
        n_contra = len(self.counterexamples)
        total = n_sup + n_contra

        if total == 0:
            self.confidence = 0.5
            self.status = "candidate"
            return

        ratio = n_sup / total
        self.confidence = round(ratio * min(1.0, total / 3.0), 3)

        if n_contra >= 3 and ratio < 0.5:
            self.status = "deprecated"
        elif n_contra >= 1 and ratio <= 0.8:
            self.status = "contested"
        elif n_sup >= 3 and ratio >= 0.8:
            self.status = "stable"
        elif n_sup >= 1:
            self.status = "weak"
        else:
            self.status = "candidate"


class AuthorModelV3(BaseModel):
    """作者决策先验模型 V3（跨作品决策先验，不含修辞文风与作品设定）."""

    model_config = ConfigDict(extra="forbid")

    author_id: str = Field(description="作者唯一标识")
    author_name: str = Field(default="", description="作者名或代号")
    version: str = Field(default="v3_mastery_p5")
    principles: list[AuthorPrincipleV3] = Field(
        default_factory=list, description="作者决策原则集合"
    )
    known_works: list[str] = Field(
        default_factory=list, description="已纳入训练/观察的作品列表"
    )
    work_separation_audited: bool = Field(
        default=False, description="是否已完成作者与单作品分离审计"
    )
    notes: list[str] = Field(default_factory=list)


class CrossWorkValidationResult(BaseModel):
    """跨作品留一验证 (L1WO) 审计结果."""

    model_config = ConfigDict(extra="forbid")

    author_id: str = Field(description="作者 ID")
    holdout_work: str = Field(description="留出验证作品名")
    training_works: list[str] = Field(description="训练/归纳作品名")
    choice_prediction_accuracy: float = Field(
        ge=0.0, le=1.0, description="在留出作品决策点上的选择预测准确率"
    )
    baseline_accuracy: float = Field(
        default=0.5, description="随机/基线选择准确率"
    )
    lexical_leakage_detected: bool = Field(
        default=False, description="是否检出作品特有名词泄漏至全局原则"
    )
    leaked_terms: list[str] = Field(
        default_factory=list, description="泄漏的专有名词列表"
    )
    is_valid_author_prior: bool = Field(
        default=False, description="是否通过作者跨作品先验资格认定"
    )
