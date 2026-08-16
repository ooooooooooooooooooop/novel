"""P3 章节级多尺度叙事搜索与短程 Rollout 数据模型.

定义章节级结构候选（StructuralProposal）、结构异质性多样性报告（StructuralDiversityReport）、
3-5 章状态级 Rollout（RolloutEvaluation）、候选选择预承诺（CandidatePrecommit）、
多维独立帕累托前沿（ParetoDimensionScores）与搜索全量结果（StructuralSearchResult）。

设计约束（docs/00_project/52_mastery_upgrade_plan.md §4）：
- 候选表示：主要行动者 / 核心选择 / 阻力来源 / 代价 / 状态变化 / 关系变化 / 信息揭示 / 读者预期变化 / 对未来 3-5 章影响 / 主要风险。
- 结构异质性门禁：近重复不得伪装多样性。
- Pareto 选择：至少独立保留因果价值/人物价值/读者动力/作品契合度/原创性/长期可持续性/风险，禁止加权单总分。
- Candidate Precommit：看候选正文前冻结本轮选择依据（本章最重要问题/必须看到的后果/哪种漂亮表达不能掩盖结构失败/什么情况推翻当前偏好）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StructuralProposal(BaseModel):
    """章节级结构候选方案（非正文，聚焦因果与决策结构）."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(description="候选唯一标识，如 prop_001")
    primary_actor: str = Field(description="主要行动者")
    core_choice: str = Field(description="核心选择")
    resistance_source: str = Field(description="阻力来源")
    cost: str = Field(description="付出的具体代价")
    state_change: str = Field(description="状态变化")
    relationship_change: str = Field(default="", description="关系变化")
    information_reveal: str = Field(default="", description="信息揭示与时机")
    reader_expectation_delta: str = Field(default="", description="读者预期变化")
    impact_next_3_to_5_chapters: str = Field(default="", description="对未来 3-5 章影响")
    primary_risk: str = Field(default="", description="主要风险")
    chapter_function: str = Field(
        default="推进",
        description="章节功能：蓄力/推进/兑现/转向/选择/后果/关系变化/信息重构/留白",
    )
    summary: str = Field(default="", description="方案一句话概要")

    def structural_signature(self) -> str:
        """结构特征指纹（用于近重复检测）."""
        elements = [
            self.primary_actor.strip(),
            self.core_choice.strip(),
            self.resistance_source.strip(),
            self.cost.strip(),
            self.state_change.strip(),
            self.chapter_function.strip(),
        ]
        return " | ".join(elements)

    def to_prompt_block(self) -> str:
        """格式化为 Prompt 说明块."""
        lines = [
            f"【方案 {self.proposal_id}】",
            f"- 主要行动者: {self.primary_actor}",
            f"- 核心选择: {self.core_choice}",
            f"- 阻力来源: {self.resistance_source}",
            f"- 付出代价: {self.cost}",
            f"- 状态变化: {self.state_change}",
            f"- 章节功能: {self.chapter_function}",
        ]
        if self.relationship_change:
            lines.append(f"- 关系变化: {self.relationship_change}")
        if self.information_reveal:
            lines.append(f"- 信息揭示: {self.information_reveal}")
        if self.reader_expectation_delta:
            lines.append(f"- 读者预期变化: {self.reader_expectation_delta}")
        if self.impact_next_3_to_5_chapters:
            lines.append(f"- 未来3-5章影响: {self.impact_next_3_to_5_chapters}")
        if self.primary_risk:
            lines.append(f"- 主要风险: {self.primary_risk}")
        return "\n".join(lines)


class NearDuplicatePair(BaseModel):
    """结构近重复判定对."""

    model_config = ConfigDict(extra="forbid")

    proposal_a: str
    proposal_b: str
    similarity_score: float = Field(ge=0, le=1, description="结构相似度")
    shared_dimensions: list[str] = Field(default_factory=list, description="相同或近重复的结构维度")
    reason: str = Field(description="近重复判定理由")


class StructuralDiversityReport(BaseModel):
    """结构异质性与多样性门禁报告."""

    model_config = ConfigDict(extra="forbid")

    is_diverse: bool = Field(description="候选池是否具备实质结构异质性")
    diversity_score: float = Field(ge=0, le=1, description="整体异质性得分")
    near_duplicates: list[NearDuplicatePair] = Field(
        default_factory=list, description="检出的结构近重复候选对"
    )
    valid_proposals: list[str] = Field(
        default_factory=list, description="通过异质性门禁的有效候选 ID 列表"
    )
    reasons: list[str] = Field(default_factory=list, description="多样性诊断说明")


class RolloutStep(BaseModel):
    """短程状态演化单步（模拟无 prose 的状态推进）."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=1, description="未来第 N 章 (1-5)")
    projected_situation: str = Field(description="推演情境与世界状态")
    fatigue_index: float = Field(ge=0, le=1, description="读者疲劳与同质化风险 (越低越好)")
    escalation_debt: float = Field(ge=0, le=1, description="战力/冲突升级透支度 (越低越稳)")
    delayed_payoff_yield: float = Field(ge=0, le=1, description="长程伏笔与期待兑现产出 (越高越好)")
    rule_break_risk: float = Field(ge=0, le=1, description="世界规则破坏风险 (越低越安全)")
    sustainability: float = Field(ge=0, le=1, description="本步叙事可持续性 (越高越好)")
    notes: list[str] = Field(default_factory=list)


class RolloutEvaluation(BaseModel):
    """3-5 章短程状态 Rollout 综合评估."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    steps: list[RolloutStep] = Field(default_factory=list, description="3-5 章状态演化步")
    overall_sustainability: float = Field(
        ge=0, le=1, description="3-5 章综合可持续性得分"
    )
    immediate_stimulus_vs_longterm_risk: float = Field(
        ge=0, le=1, description="即时刺激 vs 长期破坏平衡度（低=高即时刺激但长期破坏）"
    )
    delayed_payoff_potential: float = Field(
        ge=0, le=1, description="中长期伏笔与情绪收益潜力"
    )
    risk_flags: list[str] = Field(default_factory=list, description="识别出的长期破坏风险")
    summary: str = Field(default="", description="Rollout 推演摘要")


class CandidatePrecommit(BaseModel):
    """正文生成前冻结的选择基准与证伪依据（复用 EvaluatorPrecommit 哲学）."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    precommit_id: str = Field(description="预承诺唯一标识")
    target_chapter: int = Field(ge=1, description="目标章节号")
    core_question: str = Field(description="本章最重要解决的问题")
    mandatory_consequences: tuple[str, ...] = Field(
        description="必须看到的因果后果"
    )
    superficial_pitfalls: tuple[str, ...] = Field(
        description="哪种华丽表达不能掩盖结构失败"
    )
    overturn_conditions: tuple[str, ...] = Field(
        description="什么情况下推翻当前偏好"
    )
    trusted_state_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="冻结时可信状态哈希"
    )


class ParetoDimensionScores(BaseModel):
    """独立多维 Pareto 评估分数（禁止加权单总分）."""

    model_config = ConfigDict(extra="forbid")

    causal_value: float = Field(ge=0, le=1, description="因果价值：状态改变实质性与逻辑强度")
    character_value: float = Field(ge=0, le=1, description="人物价值：选择符合驱动力与代价自洽")
    reader_momentum: float = Field(ge=0, le=1, description="读者动力：认知张力与期待推进")
    work_alignment: float = Field(ge=0, le=1, description="作品契合度：符合 WorkSpec 与叙事纲领")
    originality: float = Field(ge=0, le=1, description="原创性与结构分叉度：避开陈词滥调")
    sustainability: float = Field(ge=0, le=1, description="长期可持续性：来自 3-5 章 Rollout")
    risk_penalty: float = Field(ge=0, le=1, description="风险惩罚：破坏世界或战力崩塌风险（越低越安全）")

    def to_dimension_dict(self) -> dict[str, float]:
        """转为多目标最大化字典（risk_penalty 转化为 safety_score = 1.0 - risk_penalty）."""
        return {
            "causal_value": self.causal_value,
            "character_value": self.character_value,
            "reader_momentum": self.reader_momentum,
            "work_alignment": self.work_alignment,
            "originality": self.originality,
            "sustainability": self.sustainability,
            "safety": 1.0 - self.risk_penalty,
        }


class StructuralSearchResult(BaseModel):
    """章节级叙事搜索全流程结果."""

    model_config = ConfigDict(extra="forbid")

    selected_proposal_id: str
    pareto_frontier: list[str] = Field(description="帕累托前沿候选 ID 列表")
    diversity_report: StructuralDiversityReport
    rollout_evaluations: dict[str, RolloutEvaluation]
    pareto_scores: dict[str, ParetoDimensionScores]
    precommit: CandidatePrecommit
    selection_rationale: str
    incomparable_candidates_preserved: list[str] = Field(
        default_factory=list, description="帕累托前沿中独立保留的其他非支配候选"
    )
