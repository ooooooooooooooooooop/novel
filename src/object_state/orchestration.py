"""OrchestrationState — 长程叙事编排状态与跨章持久模型（P2 核心模型）.

覆盖 7 个维度的状态与决策：
1. 读者预期（reader expectation / expectation horizon / cognitive tension）
2. 承诺/回报债务（promise-payoff debt / open thread pressure / payoff urgency）
3. 关系轨迹（relational trajectory / interpersonal leverage / estrangement vs bonding）
4. 情绪模式（emotional pacing pattern / valley-peak rhythm / fatigue prevention）
5. 线程轮换（thread rotation / secondary line starvation / main-sub balance）
6. 章节功能（chapter function allocation / hook placement / transition vs payoff chapter）
7. 信息与场景密度（information budgeting / scene density / exposure pacing）
"""

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class ReaderExpectationHorizon(BaseModel):
    """1. 读者预期与认知张力."""

    model_config = ConfigDict(extra="forbid")

    cognitive_tension: Literal["low", "medium", "high", "critical"] = Field(
        default="medium", description="当前读者认知张力等级"
    )
    expectation_horizon: int = Field(
        default=3, ge=1, description="预期回收视界窗口（章数/单元数）"
    )
    top_questions: list[str] = Field(
        default_factory=list, description="读者当前最急迫的待解问题列表"
    )
    stalled_questions: list[str] = Field(
        default_factory=list, description="长期未推进的停滞预期"
    )

    @field_validator("top_questions", "stalled_questions")
    @classmethod
    def _validate_non_blank_items(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not v.strip() for v in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


class PromisePayoffDebt(BaseModel):
    """2. 承诺/回报债务与兑现紧迫性."""

    model_config = ConfigDict(extra="forbid")

    open_threads_count: int = Field(default=0, ge=0, description="活跃未回收承诺数")
    resolved_threads_count: int = Field(default=0, ge=0, description="已回收承诺数")
    overdue_threads_count: int = Field(default=0, ge=0, description="逾期未推进承诺数")
    debt_level: Literal["low", "moderate", "high", "critical"] = Field(
        default="low", description="系统承诺债务等级"
    )
    payoff_urgency: Literal["low", "medium", "high", "immediate"] = Field(
        default="low", description="回报兑现紧迫性"
    )
    urgent_thread_ids: list[str] = Field(
        default_factory=list, description="急需推进或回收的 thread_id 列表"
    )

    @field_validator("urgent_thread_ids")
    @classmethod
    def _validate_non_blank_threads(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not v.strip() for v in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


class RelationalTrajectory(BaseModel):
    """3. 角色关系轨迹与人际杠杆."""

    model_config = ConfigDict(extra="forbid")

    dominant_dynamic: str = Field(
        default="关系相对稳定", description="当前主导关系动态描述"
    )
    active_leverages: list[str] = Field(
        default_factory=list, description="当前生效的人际杠杆（秘密/债务/软肋/把柄）"
    )
    estrangement_vs_bonding: Literal[
        "bonding", "estrangement", "confrontation", "reconciliation", "stable"
    ] = Field(default="stable", description="主要关系走向趋势")
    trajectory_notes: list[str] = Field(
        default_factory=list, description="各核心角色对的关系演变备忘"
    )

    @field_validator("dominant_dynamic")
    @classmethod
    def _validate_non_blank_text(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class EmotionalPacing(BaseModel):
    """4. 情绪模式与疲劳防御."""

    model_config = ConfigDict(extra="forbid")

    recent_temperatures: list[str] = Field(
        default_factory=list, description="近期情绪温度序列（如 ['压抑', '激昂', '危机']）"
    )
    current_rhythm: Literal["buildup", "peak", "release", "valley", "recovery"] = Field(
        default="buildup", description="当前情绪节律阶段"
    )
    fatigue_risk: bool = Field(
        default=False, description="连续高压导致的读者审美疲劳风险标记"
    )
    target_temperature: Optional[str] = Field(
        default=None, description="建议调控目标情绪"
    )
    pacing_directive: str = Field(
        default="稳步推进冲突", description="情绪节律指导语"
    )

    @field_validator("pacing_directive")
    @classmethod
    def _validate_non_blank_directive(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class ThreadRotation(BaseModel):
    """5. 线程轮换与支线防饿死."""

    model_config = ConfigDict(extra="forbid")

    active_threads: list[str] = Field(
        default_factory=list, description="所有活跃叙事线程列表"
    )
    starved_threads: list[str] = Field(
        default_factory=list, description="过久未出现的饿死风险支线"
    )
    rotation_recommendation: Literal[
        "main_push", "sub_rotation", "thread_convergence", "balanced"
    ] = Field(default="balanced", description="线程轮换建议")
    rotation_directive: str = Field(
        default="主支线平衡推进", description="线程轮换具体指导"
    )

    @field_validator("rotation_directive")
    @classmethod
    def _validate_non_blank_rot_dir(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class ChapterFunctionAllocation(BaseModel):
    """6. 章节宏观功能与钩子定位."""

    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(default=1, ge=1, description="当前章节序号")
    assigned_function: Literal[
        "setup", "escalation", "crisis", "payoff", "transition", "aftermath", "neutral"
    ] = Field(default="neutral", description="本章宏观功能分工")
    hook_strategy: Literal[
        "cliffhanger", "revelation", "emotional_resonance", "open_question", "none"
    ] = Field(default="open_question", description="建议章末钩子策略")
    pacing_role: str = Field(
        default="基础铺垫与局势引入", description="章节功能与推进定位描述"
    )

    @field_validator("pacing_role")
    @classmethod
    def _validate_non_blank_pacing_role(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class InformationDensityBudget(BaseModel):
    """7. 信息释放与场景密度预算."""

    model_config = ConfigDict(extra="forbid")

    reveal_budget: Literal["conservative", "moderate", "burst"] = Field(
        default="moderate", description="本阶段信息披露预算"
    )
    scene_density_target: Literal[
        "action_dense", "dialogue_dense", "atmospheric", "balanced"
    ] = Field(default="balanced", description="场景密度导向")
    exposure_pacing_limit: str = Field(
        default="避免集中说教，通过冲突释放信息", description="信息暴露节奏约束"
    )
    budget_notes: list[str] = Field(
        default_factory=list, description="信息与场景预算详细说明"
    )

    @field_validator("exposure_pacing_limit")
    @classmethod
    def _validate_non_blank_exp_limit(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class OrchestrationPlan(BaseModel):
    """从已提交历史派生的本章编排计划（纯派生产物，不含机械 prompt 清单）."""

    model_config = ConfigDict(extra="forbid")

    chapter_number: int = Field(default=1, ge=1)
    assigned_function: str = Field(default="neutral")
    priority_tasks: list[str] = Field(default_factory=list, description="本章优先推进任务")
    suppressed_tasks: list[str] = Field(default_factory=list, description="暂缓推进任务")
    silence_items: list[str] = Field(default_factory=list, description="必须保持沉默/不可揭示项")
    payoff_targets: list[str] = Field(default_factory=list, description="可兑现承诺目标")
    fatigue_risk: bool = Field(default=False)
    density_directive: str = Field(default="balanced")
    notes: list[str] = Field(default_factory=list)

    def to_chapter_packet(self) -> str:
        """生成极简结构化 Chapter Packet，无有效内容时不增加 prompt 字节."""
        lines = []
        if self.priority_tasks:
            lines.append(f"【本章优先任务】: {'；'.join(self.priority_tasks)}")
        if self.suppressed_tasks:
            lines.append(f"【暂缓任务】: {'；'.join(self.suppressed_tasks)}")
        if self.silence_items:
            lines.append(f"【保持沉默】: {'；'.join(self.silence_items)}")
        if self.payoff_targets:
            lines.append(f"【可兑现承诺】: {'；'.join(self.payoff_targets)}")
        if self.fatigue_risk:
            lines.append("【节奏风险】: 近期连续高压，本章必须安排缓冲复盘或情感交流")
        if self.assigned_function != "neutral":
            lines.append(f"【目标章节功能】: {self.assigned_function}")
        return "\n".join(lines)


class CommittedOrchestrationHistoryEntry(BaseModel):
    """已提交章节的编排履历."""

    model_config = ConfigDict(extra="forbid")

    chapter: int = Field(ge=1)
    function: str = Field(default="neutral")
    emotion: str = Field(default="normal")
    advanced_threads: list[str] = Field(default_factory=list)
    payoff_promises: list[str] = Field(default_factory=list)
    relational_shifts: list[str] = Field(default_factory=list)


class CommittedOrchestrationState(BaseModel):
    """已持久化的跨章编排状态机（只在章节成功提交后更新）."""

    model_config = ConfigDict(extra="forbid")

    last_committed_chapter: int = Field(default=0, ge=0)
    last_run_id: str = Field(default="")
    history_entries: list[CommittedOrchestrationHistoryEntry] = Field(default_factory=list)
    thread_last_seen: dict[str, int] = Field(default_factory=dict)
    thread_last_advanced: dict[str, int] = Field(default_factory=dict)
    expectation_started_at: dict[str, int] = Field(default_factory=dict)
    expectation_last_advanced_at: dict[str, int] = Field(default_factory=dict)
    recent_chapter_functions: list[str] = Field(default_factory=list)
    recent_emotional_patterns: list[str] = Field(default_factory=list)


class OrchestrationState(BaseModel):
    """长程叙事编排统一状态聚合对象."""

    model_config = ConfigDict(extra="forbid")

    orchestration_id: str = Field(
        default="orch_default", description="编排状态标识"
    )
    chapter_number: int = Field(default=1, ge=1, description="当前章节序号")
    step_index: int = Field(default=0, ge=0, description="当前编排步数")

    expectation_horizon: ReaderExpectationHorizon = Field(
        default_factory=ReaderExpectationHorizon, description="1. 读者预期"
    )
    promise_debt: PromisePayoffDebt = Field(
        default_factory=PromisePayoffDebt, description="2. 承诺/回报债务"
    )
    relational_trajectory: RelationalTrajectory = Field(
        default_factory=RelationalTrajectory, description="3. 关系轨迹"
    )
    emotional_pacing: EmotionalPacing = Field(
        default_factory=EmotionalPacing, description="4. 情绪模式与疲劳防御"
    )
    thread_rotation: ThreadRotation = Field(
        default_factory=ThreadRotation, description="5. 线程轮换与防饿死"
    )
    chapter_function: ChapterFunctionAllocation = Field(
        default_factory=ChapterFunctionAllocation, description="6. 章节功能分配"
    )
    density_budget: InformationDensityBudget = Field(
        default_factory=InformationDensityBudget, description="7. 信息与场景密度"
    )

    history_summary: list[str] = Field(
        default_factory=list, description="最近章节编排轨迹记录"
    )

    def to_prompt_context(self) -> str:
        """渲染为注入 LLM 续写/候选生成 prompt 的【叙事编排导向】块."""
        lines = ["【长程叙事编排导向】"]

        # 1. 读者预期
        exp = self.expectation_horizon
        exp_tag = {"low": "低张力", "medium": "适度张力", "high": "高张力", "critical": "危机张力"}[exp.cognitive_tension]
        q_str = "；".join(exp.top_questions[:3]) if exp.top_questions else "暂无急迫悬念"
        lines.append(f"1. 读者预期: [{exp_tag} | 回收视界: {exp.expectation_horizon}章] 核心待解: {q_str}")
        if exp.stalled_questions:
            lines.append(f"   - 停滞预期预警: {'；'.join(exp.stalled_questions[:2])}")

        # 2. 承诺/回报债务
        debt = self.promise_debt
        debt_tag = {"low": "低", "moderate": "中等", "high": "高", "critical": "极高"}[debt.debt_level]
        urg_tag = {"low": "平缓", "medium": "中等", "high": "高", "immediate": "即时兑现"}[debt.payoff_urgency]
        lines.append(f"2. 承诺债务: [债务等级: {debt_tag} | 兑现紧迫性: {urg_tag}] 活跃/已回收: {debt.open_threads_count}/{debt.resolved_threads_count}")
        if debt.urgent_thread_ids:
            lines.append(f"   - 急需推进/回收: {'；'.join(debt.urgent_thread_ids[:3])}")

        # 3. 关系轨迹
        rel = self.relational_trajectory
        lines.append(f"3. 关系轨迹: [{rel.estrangement_vs_bonding}] {rel.dominant_dynamic}")
        if rel.active_leverages:
            lines.append(f"   - 生效人际杠杆: {'；'.join(rel.active_leverages[:2])}")

        # 4. 情绪节律与疲劳防御
        emo = self.emotional_pacing
        lines.append(f"4. 情绪节律: [{emo.current_rhythm}] {emo.pacing_directive}")
        if emo.fatigue_risk:
            lines.append(f"   - 疲劳防御预警: 连续处于高张力状态，建议安排过渡/沉淀节拍")

        # 5. 线程轮换与防饿死
        rot = self.thread_rotation
        lines.append(f"5. 线程轮换: [{rot.rotation_recommendation}] {rot.rotation_directive}")
        if rot.starved_threads:
            lines.append(f"   - 防饿死召回线程: {'；'.join(rot.starved_threads[:2])}")

        # 6. 章节功能分配
        fn = self.chapter_function
        lines.append(f"6. 章节定位: [功能: {fn.assigned_function} | 钩子: {fn.hook_strategy}] {fn.pacing_role}")

        # 7. 信息与场景密度
        den = self.density_budget
        lines.append(f"7. 密度预算: [信息披露: {den.reveal_budget} | 场景导向: {den.scene_density_target}] {den.exposure_pacing_limit}")

        return "\n".join(lines)
