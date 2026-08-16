"""独立人类双盲评估 (Human Blind Eval) 与长程授权裁决数据模型 (P7 / R6 整改).

根据 docs/00_project/52_mastery_upgrade_plan.md §8:
1. 材料包与双盲协议：
   - 显式随机种子与 seed_hash，打乱版本顺序与读者分配 (BlindedChapterPacket)。
   - 严格公私目录物理隔离 (--public-output-dir vs --secret-output-dir)。
   - 按版本独立统计追读意愿 (continuation_willingness_by_version) 与弃读位置 (abandonment_by_version)。
2. 90 章长程无人生产授权前置条件 (LongHorizonAuthorizationVerdict):
   - 10 项前置条件默认全为 False / unverified，必须从真实证据逐项推导。
   - 缺少系统外真实人类连续阅读实验数据时，强制输出 long_run_not_authorized。
"""

from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BlindedChapterPacket(BaseModel):
    """人类读者双盲盲评材料包."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(description="材料包唯一标识")
    novel_name: str = Field(description="小说或评测项目名")
    chapter_range: str = Field(description="包含的章节范围（如 1-10 或 21-30）")
    random_seed: int = Field(default=42, description="用于版本打乱与分配的显式随机种子")
    seed_hash: str = Field(default="", description="随机种子与参数的 SHA256 哈希")
    created_at_utc: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    # 隐藏来源混排版本（如 {"cand_alpha": text_a, "cand_beta": text_b}）
    blinded_versions: dict[str, list[dict]] = Field(
        description="各盲测版本章节序列（已抹去 AI/人类/基线标记）"
    )
    secret_manifest_hash: str = Field(
        description="封存真实版本映射表的 SHA256 哈希（防评审提前揭盲）"
    )


class HumanEvaluationSubmission(BaseModel):
    """单个真实读者提交的评测结果 (R6 整改支持多版本独立追读与弃读记录)."""

    model_config = ConfigDict(extra="forbid")

    submission_id: str = Field(description="提交唯一标识")
    packet_id: str = Field(description="评测材料包 ID")
    reader_id: str = Field(description="匿名读者编号")
    reader_group: Literal["professional_editor", "veteran_reader", "casual_reader"] = (
        Field(description="读者群体划分")
    )
    preferred_version: str = Field(
        description="相对偏好的盲测版本 key（或 'no_difference' 允许弃权/无显著差异）"
    )
    # 按版本分别记录追读意愿与弃读信息
    continuation_willingness_by_version: dict[str, bool] = Field(
        default_factory=dict,
        description="每个候选版本独立的追读意愿（如 {'cand_alpha': True, 'cand_beta': False}）",
    )
    abandonment_by_version: dict[str, Optional[int]] = Field(
        default_factory=dict,
        description="每个候选版本发生弃读的具体章节号（若弃读）",
    )
    abandonment_reasons_by_version: dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="每个候选版本弃读的核心原因",
    )
    continuation_willingness: Optional[bool] = Field(
        default=None, description="整体/首选版本的追读意愿（兼容旧字段）"
    )
    abandonment_point_chapter: Optional[int] = Field(
        default=None, description="整体弃读发生章节号（兼容旧字段）"
    )
    abandonment_reason: Optional[str] = Field(
        default=None, description="整体弃读原因（兼容旧字段）"
    )
    qualitative_feedback: str = Field(
        default="", description="读者自由定性评价与细节反馈"
    )


class LongHorizonPreconditionStatus(BaseModel):
    """90 章无人生产 10 项前置条件检查清单 (默认全为 False，杜绝无证据假阳性)."""

    model_config = ConfigDict(extra="forbid")

    p1_causal_defense_complete: bool = Field(
        default=False, description="1. P1 长程因果防线 5 类检测器全部就绪且接入门禁"
    )
    p2_orchestrator_in_production: bool = Field(
        default=False, description="2. P2 叙事编排器进入 compose/extend 生产调用链"
    )
    p3_structural_search_active: bool = Field(
        default=False, description="3. P3 章节级多尺度搜索真实改变候选优先级"
    )
    p3_diversity_validated: bool = Field(
        default=False, description="4. P3 结构异质性门禁有效阻断近重复"
    )
    p4_blind_eval_stable: bool = Field(
        default=False, description="5. P4 Blind Eval 稳定输出分轴相对改善与置信区间"
    )
    p4_pass_audit_frozen: bool = Field(
        default=False, description="6. P4 PASS Audit 漏检率口径冻结"
    )
    p4_human_eval_protocol_frozen: bool = Field(
        default=False, description="7. P4 人类盲评双盲协议与材料包格式冻结"
    )
    real_human_continuous_reading_data_exists: bool = Field(
        default=False,
        description="8. 至少一轮系统外真实人类读者连续阅读双盲实验数据（硬红线）",
    )
    provider_profile_and_budget_frozen: bool = Field(
        default=False, description="9. Provider 档案与 token 预算硬上限已冻结"
    )
    historical_release_records_intact: bool = Field(
        default=False, description="10. 历史发布证据、基线统计与 Release 记录完好无损"
    )


class LongHorizonAuthorizationVerdict(BaseModel):
    """90 章无人全自动长程生产授权裁决 (Plan §8)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["long_run_authorized", "long_run_not_authorized"] = Field(
        description="最终授权裁决"
    )
    evaluated_at_utc: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    preconditions: LongHorizonPreconditionStatus = Field(
        description="10 项前置条件检查结果"
    )
    unmet_preconditions: list[str] = Field(
        default_factory=list, description="未满足的前置条件列表"
    )
    notes: str = Field(description="裁决依据说明")
    boundary_statement: str = Field(
        default=(
            "根据 Plan §8，系统外真实人类连续阅读实验数据为不可逾越的硬性红线。"
            "在未接入真人盲评数据前，系统严禁声称已获全自动长程生产资格，"
            "必须诚实保持 long_run_not_authorized。"
        )
    )
