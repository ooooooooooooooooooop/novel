"""Taste Stack 五层评价体系与统一质量报告数据模型 (P4).

对应 docs/00_project/52_mastery_upgrade_plan.md §5:
1. 确定性硬门禁 (Layer 1): 事实/时间/状态/信息权限/世界规则/ReaderContract/已发生现实/已付代价。
2. 专门轴评价 (Layer 2): 可扩展轴接口（通用轴 + 作品特有轴），看候选前冻结标准，允许 unreviewable。
3. Blind Eval (Layer 3): 隐藏版本来源、A/B 与 B/A 换位、允许弃权、Wilson 95% CI。回答「修改后是否相对变好」。
4. PASS Audit (Layer 4): route=pass 独立抽样、不暴露原 Review、区分 any/actionable/blocking miss。回答「Review 漏了多少」。
5. 人类隐藏来源验证 (Layer 5): 隐藏来源混排，无真人数据时显示 not_run，禁止伪造通过。
6. G7 退役状态: 明确标记已退役为研究性子能力，不再作为总发布门。
7. 统一质量报告: 禁止输出单一「最终大神分数」。
"""

from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Layer1HardGatesSummary(BaseModel):
    """第 1 层：确定性硬门禁状态（只证明无已知硬错误，无真实证据为 not_run）."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "blocked", "not_run", "invalid_evidence"] = "not_run"
    checked_gates: list[str] = Field(default_factory=list)
    blocking_issues_count: int = 0
    blocking_issues_details: list[dict] = Field(default_factory=list)
    evidence_count: int = 0
    evidence_paths: list[str] = Field(default_factory=list)
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class Layer2SpecializedAxesSummary(BaseModel):
    """第 2 层：专门轴评价状态（无真实证据为 not_run）."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "pending", "not_run", "unreviewable", "invalid_evidence"] = "not_run"
    evaluated_axes: dict[str, dict] = Field(
        default_factory=dict,
        description="各轴评价结果（人物选择/场景现场感/情绪落地/关系变化/承诺兑现/读者动力/套路风险等）",
    )
    unreviewable_axes: list[str] = Field(
        default_factory=list, description="标记为证据不足无法评审的轴"
    )
    frozen_criteria_hash: Optional[str] = None
    evidence_paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Layer3BlindEvalSummary(BaseModel):
    """第 3 层：Blind A/B 相对改善评估（回答修改后是否相对变好，真实计算 Wilson CI）."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "not_run", "invalid_evidence", "unreviewable"] = "not_run"
    total_pairs_evaluated: int = 0
    better_count: int = 0
    worse_count: int = 0
    no_difference_count: int = 0
    uncertain_count: int = 0
    net_improvement_rate: float = 0.0
    wilson_ci_95: tuple[float, float] = (0.0, 0.0)
    stratified_by_issue_type: dict[str, dict] = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Layer4PassAuditSummary(BaseModel):
    """第 4 层：PASS Audit 漏检率审计（回答 Review 漏了多少）."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "not_run", "invalid_evidence"] = "not_run"
    total_pass_chapters_audited: int = 0
    clean_chapters_count: int = 0
    clean_rate: float = 0.0
    actionable_miss_rate: float = 0.0
    blocking_miss_rate: float = 0.0
    findings_by_type: dict[str, int] = Field(default_factory=dict)
    severity_disagreements: list[dict] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Layer5HumanBlindEvalSummary(BaseModel):
    """第 5 层：独立人类隐藏来源盲评（长期阅读验证）."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_run", "in_progress", "completed", "invalid_evidence"] = "not_run"
    participant_groups: list[str] = Field(
        default_factory=list, description="读者分组（如专业读者组、网文读者组）"
    )
    samples_evaluated: int = 0
    relative_preference: dict[str, float] = Field(
        default_factory=dict, description="相较基线与原版偏好率"
    )
    continuation_willingness: dict[str, float] = Field(
        default_factory=dict, description="各段落/章节追读意愿"
    )
    abandonment_points: list[dict] = Field(
        default_factory=list, description="弃读章节与位置分布"
    )
    evidence_paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: str = Field(default="暂无真人连续阅读实验数据（诚实标记 not_run，禁止伪造结果）")


class StyleDriftSummary(BaseModel):
    """文风漂移与同质化测量."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "not_run", "invalid_evidence"] = "not_run"
    drift_detected: bool = False
    homogenization_index: float = 0.0
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class G7RetirementNotice(BaseModel):
    """G7 自动审美裁决门退役声明."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["decommissioned_research_only"] = "decommissioned_research_only"
    notice: str = (
        "G7 自动审美资格门已退役为研究性子能力，不再作为系统总发布门，"
        "主线生产质量由五层评价体系承接，禁止将其作为最终裁决依据。"
    )
    historical_record_intact: bool = True


class UnifiedQualityReport(BaseModel):
    """全系统五层统一质量报告（禁止输出单一总分）."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(description="报告唯一标识")
    novel_name: str = Field(description="小说或工作区名")
    created_at_utc: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    pipeline_version: str = Field(default="flow_v3_mastery_p4")

    # 五层评价体系
    layer1_hard_gates: Layer1HardGatesSummary = Field(
        default_factory=Layer1HardGatesSummary
    )
    layer2_specialized_axes: Layer2SpecializedAxesSummary = Field(
        default_factory=Layer2SpecializedAxesSummary
    )
    layer3_blind_eval: Layer3BlindEvalSummary = Field(
        default_factory=Layer3BlindEvalSummary
    )
    layer4_pass_audit: Layer4PassAuditSummary = Field(
        default_factory=Layer4PassAuditSummary
    )
    layer5_human_blind_eval: Layer5HumanBlindEvalSummary = Field(
        default_factory=Layer5HumanBlindEvalSummary
    )

    # 侧车测量与退役声明
    style_drift: StyleDriftSummary = Field(default_factory=StyleDriftSummary)
    g7_status: G7RetirementNotice = Field(default_factory=G7RetirementNotice)

    unarmed_capabilities: list[str] = Field(
        default_factory=lambda: [
            "directapi_provider_calling (未武装，遵循 Tier 0 边界)",
            "autonomous_closed_loop (未武装，遵循 Tier 0 边界)",
        ]
    )

    narrative_evaluation_summary: str = Field(
        description="多维结构化定性诊断与证据链总结（禁止单一标量总分）"
    )

    def render_markdown(self) -> str:
        """渲染为 Markdown 质量全景报告."""
        lines = [
            f"# 统一叙事质量报告: {self.novel_name}",
            f"- 报告 ID: `{self.report_id}`",
            f"- 生产版本: `{self.pipeline_version}`",
            f"- 生成时间: `{self.created_at_utc}`",
            "",
            "## 1. 第 1 层：确定性硬门禁",
            f"- 状态: **{self.layer1_hard_gates.status.upper()}**",
            f"- 检查门禁: {', '.join(self.layer1_hard_gates.checked_gates) if self.layer1_hard_gates.checked_gates else '无'}",
            f"- 阻断问题数: {self.layer1_hard_gates.blocking_issues_count}",
            f"- 证据文件: {', '.join(self.layer1_hard_gates.evidence_paths) if self.layer1_hard_gates.evidence_paths else '未读取到'}",
            "",
            "## 2. 第 2 层：专门轴评价",
            f"- 状态: **{self.layer2_specialized_axes.status.upper()}**",
            f"- 评价轴数量: {len(self.layer2_specialized_axes.evaluated_axes)}",
            f"- 证据不足 (Unreviewable) 轴: {self.layer2_specialized_axes.unreviewable_axes or '无'}",
            "",
            "## 3. 第 3 层：Blind A/B 相对改善 (Revision Gain)",
            f"- 状态: **{self.layer3_blind_eval.status.upper()}**",
            f"- 评估样本对数: {self.layer3_blind_eval.total_pairs_evaluated}",
            f"- 净改善率: {self.layer3_blind_eval.net_improvement_rate * 100:.1f}%",
            f"- 95% Wilson 置信区间: [{self.layer3_blind_eval.wilson_ci_95[0]:.2f}, {self.layer3_blind_eval.wilson_ci_95[1]:.2f}]",
            "",
            "## 4. 第 4 层：PASS Audit 漏检率 (False Negative Rate)",
            f"- 状态: **{self.layer4_pass_audit.status.upper()}**",
            f"- 抽检 PASS 章节数: {self.layer4_pass_audit.total_pass_chapters_audited}",
            f"- Clean 率: {self.layer4_pass_audit.clean_rate * 100:.1f}%",
            f"- 漏检阻断缺陷率: {self.layer4_pass_audit.blocking_miss_rate * 100:.1f}%",
            "",
            "## 5. 第 5 层：独立人类隐藏来源盲评 (Long-horizon Truth)",
            f"- 状态: **{self.layer5_human_blind_eval.status.upper()}**",
            f"- 备注: {self.layer5_human_blind_eval.notes}",
            "",
            "## 6. G7 状态与退役说明",
            f"- 状态: `{self.g7_status.status}`",
            f"- 说明: {self.g7_status.notice}",
            "",
            "## 7. 综合叙事质量诊断",
            self.narrative_evaluation_summary,
            "",
            "> 注：本报告严格遵循 P4 契约，杜绝虚假确定性，严禁输出单一加权「大神分」。",
        ]
        return "\n".join(lines)
