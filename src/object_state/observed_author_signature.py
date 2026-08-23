"""Observed Decision Signature v1 — 数据模型（研究性，WP4/WP5 核心）。

根据 .taskflow/active/published-text-author-signature-v2/observed-decision-author-signature-v1.plan.md
§七（新验证器设计）、§八（nested-CV 与统计协议）、§十二（文件规划）：

- `ObservedDecisionEventV1`：人工/LLM 预标注的 observed-realization 决策事件，
  严格遵循 WP1 代码本 v1.0 事件 schema（决策点五判据、六维情境、2–4 冻结候选、
  gold_action、标签来源、pre-context 只存哈希——正文不入模型）。
- `ObservedSignatureConfig`：预注册冻结参数（MDE +0.05、α≥0.80、coverage、power≥80%、
  bootstrap/置换次数、seed、最小作者/作品数）。
- `ObservedSignatureV1Result`：确认性报告；state 遵循计划 §7.3 状态机
  （INVALID / NOT_ESTIMABLE / FAIL / PARTIAL / PASS），部署状态独立。

边界：
- `label_source="cue_count"` 或任何 cue 派生标签 → 必须 INVALID（计划 §十.6、§十四）。
- 正文/作者名/书名/路径一律不进本模块；pre-context 只保留哈希与长度。
- 本模块不是生产资格、不开书、不写 AuthorKernel；只作研究验证。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ObservedDecisionEventV1(BaseModel):
    """人工/LLM 预标注的 observed-realization 决策事件（WP1 代码本 v1.0）。

    六维情境用 ``situation`` dict 无损保存；编码方式由调用方预注册并保持一致。
    ``annotator_labels`` 保存双标子集的各标注员原始标签（用于 Krippendorff α 与仲裁留痕）。
    """

    model_config = ConfigDict(extra="forbid")

    author_id: str = Field(description="中性作者 ID")
    work_id: str = Field(description="作品 ID（作品级分区，同一作品的所有事件必须同分区）")
    topic_stratum: str = Field(description="受控题材层")
    split: Literal["support", "holdout"] = Field(description="作品分区：support=训练/留出前可见；holdout=最终评分")
    event_id: Optional[str] = Field(default=None, description="可选事件行标识")
    situation: dict[str, object] = Field(default_factory=dict, description="六维情境（high/low/none 等，无损）")
    candidates: list[str] = Field(default_factory=list, description="冻结候选动作全集（2–4 个互斥候选）")
    gold_action: str = Field(default="", description="真实动作（金标准）")
    label_source: Literal["human_gold", "llm_prelabel", "cue_count"] = Field(
        default="human_gold",
        description="标签来源；cue_count 为旧 cue 派生标签，任何出现都必须 INVALID",
    )
    pre_context_hash: Optional[str] = Field(default=None, description="决策前窗口文本哈希（正文不入模型）")
    pre_context_len: Optional[int] = Field(default=None, ge=0, description="决策前窗口字符数（审计用）")
    outcome_evidence_hash: Optional[str] = Field(default=None, description="结果证据哈希（仅审计；不允许等于 pre_context_hash）")
    annotator_labels: dict[str, str] = Field(default_factory=dict, description="双标子集：标注员→原始标签")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="标注置信度（0-1）")
    cue_hits: dict[str, float] = Field(default_factory=dict, description="负控专用 cue 命中特征（与标签独立）")


class ObservedSignatureConfig(BaseModel):
    """预注册冻结配置（outer-test 前冻结，之后不得修改）。"""

    model_config = ConfigDict(extra="forbid")

    mde: float = Field(default=0.05, description="最小有意义效应（绝对优势），outer-test 前冻结")
    min_alpha: float = Field(default=0.80, description="Krippendorff α 确认性阈值")
    operating_coverage: float = Field(default=0.80, ge=0.0, le=1.0, description="目标 operating coverage")
    power_target: float = Field(default=0.80, ge=0.0, le=1.0, description="功效目标")
    bootstrap_reps: int = Field(default=2000, ge=100, description="作者级 cluster bootstrap 次数")
    permutation_reps: int = Field(default=5000, ge=100, description="题材 strata 内作者标签置换次数")
    seed: int = Field(default=20260823)
    min_authors_per_topic: int = Field(default=4, ge=2, description="每题材最少作者数（防 author/topic 一一别名）")
    min_support_works: int = Field(default=2, ge=1, description="每作者最少 support 作品数")
    min_holdout_works: int = Field(default=1, ge=1, description="每作者最少 holdout 作品数")
    min_events_per_author_support: int = Field(default=2, ge=1, description="每作者 support 侧最少事件数")
    min_present_events: int = Field(default=10, ge=1, description="全场最少 present 事件数（产率门禁）")
    alpha_smoothing: float = Field(default=0.5, ge=0.0, description="Dirichlet-multinomial 平滑参数")
    assumed_effect_sd: Optional[float] = Field(default=None, ge=0.001, description="可选显式效应方差估计（覆盖数据经验估计）")


class ObservedSignatureV1Result(BaseModel):
    """Observed Decision Signature v1 离线验证报告。

    ``state`` 遵循计划 §7.3：
    - INVALID：结构违规、泄漏、标签来源违规。
    - NOT_ESTIMABLE：可靠性不足、样本不足、inner 全失败、功效不足。
    - FAIL：实验有效但预注册终点未达成。
    - PARTIAL：仅探索性可靠性或 coverage。
    - PASS：所有确认性门禁通过。

    数值字段在无效输入时使用 0，不使用 0.5 中性回退。
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="observed_signature_v1")
    state: Literal["INVALID", "NOT_ESTIMABLE", "FAIL", "PARTIAL", "PASS"] = Field(default="INVALID")
    full_coverage_deployment_state: Optional[Literal["PASS", "FAIL"]] = Field(
        default=None, description="full-coverage 部署状态（独立报告，不并入 state）"
    )

    # 主终点（计划 §8.2）
    author_advantage: float = Field(default=0.0, description="作者级平均 advantage（vs 最强题材条件基线）")
    cluster_bootstrap_ci: list[float] = Field(default_factory=lambda: [0.0, 0.0], description="作者级 cluster bootstrap 95% CI")
    permutation_p_value: Optional[float] = Field(default=None, description="题材 strata 内作者标签置换 p 值")
    mde_frozen: float = Field(default=0.05, description="冻结的 MDE（绝对优势）")

    # 可靠性与功效
    reliability_alpha: Optional[float] = Field(default=None, description="双标子集 Krippendorff α")
    reliability_verdict: Optional[str] = Field(default=None, description="CONFIRMATORY_OK/EXPLORATORY_ONLY/REWORK_CODEBOOK/NO_DOUBLE_SUBSET")
    power_estimate: Optional[float] = Field(default=None, description="作者级功效模拟估计")

    # coverage / selective 指标（计划 §九）
    coverage: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    selective_risk: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    aurc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    c_at_1: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    f_half_u: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # 负控（计划 §十）
    negative_controls: dict[str, object] = Field(
        default_factory=dict,
        description="cue-only / topic-only / future-text / 标签源消融 的独立报告",
    )
    cue_only_advantage: Optional[float] = Field(default=None)
    topic_only_advantage: Optional[float] = Field(default=None)

    # 诊断与审计
    per_author: list[dict[str, object]] = Field(default_factory=list, description="每作者 advantage/score/baseline")
    invalid_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_event_count: int = Field(default=0, ge=0)
    support_event_count: int = Field(default=0, ge=0)
    holdout_event_count: int = Field(default=0, ge=0)
    author_count: int = Field(default=0, ge=0)
    inner_config_count: int = Field(default=0, ge=0)
    inner_success_count: int = Field(default=0, ge=0)
    outer_test_run: bool = Field(default=False, description="outer-test 是否已运行（必须只跑一次）")
    holdout_leakage_detected: bool = Field(default=False)
    topic_alias_detected: bool = Field(default=False)
    cue_label_source_detected: bool = Field(default=False)
