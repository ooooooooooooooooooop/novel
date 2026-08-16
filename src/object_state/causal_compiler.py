"""世界因果编译器 (World Causal Compiler) 数据模型 (P6 研究轨).

根据 docs/00_project/52_mastery_upgrade_plan.md §7:
推导链：根规则 → 能力与资源边界 → 使用代价 → 制度 → 权力结构 → 群体利益 → 人物策略 → 冲突。
核心验证：
- 规则删除测试 (Rule Deletion Test): 删规则后策略/制度/冲突完全不变 → 标记为装饰设定。
- 代价传播测试 (Cost Propagation Test): 代价传播至资源/身体/关系/权力/后续选择。
- 二阶后果推导 (Second-order Consequence): 规则变动 → 群体反应 → 制度反弹 → 策略调整。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CausalRule(BaseModel):
    """世界因果根规则定义."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="规则唯一标识（如 rule_magic_drain_01）")
    rule_name: str = Field(description="规则名称")
    rule_type: Literal[
        "capability_boundary",
        "cost_constraint",
        "institution_law",
        "power_dynamic",
        "resource_scarcity",
    ] = Field(description="规则类型")
    statement: str = Field(description="规则核心陈述")
    usage_cost: str = Field(default="", description="使用或触发该规则所需的不可逆代价")
    institutional_enforcement: str = Field(
        default="", description="维护或惩戒该规则的社会制度机制"
    )
    affected_groups: list[str] = Field(
        default_factory=list, description="直接受影响的群体/阶层"
    )


class CausalDerivation(BaseModel):
    """因果推导链步进结果."""

    model_config = ConfigDict(extra="forbid")

    derivation_id: str = Field(description="推导标识")
    rule_id: str = Field(description="源规则 ID")
    trigger_event: str = Field(description="触发情境或规则变动")
    first_order_effect: str = Field(description="一阶直接效应（能力与资源变化）")
    second_order_effect: str = Field(
        description="二阶社会与制度效应（群体行为转变与制度反弹）"
    )
    strategic_consequence: str = Field(
        description="战略后果（对主要角色的最优选择空间的实质改变）"
    )


class RuleDeletionAuditReport(BaseModel):
    """规则删除审计报告（检测是否为装饰设定）."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="被审计规则 ID")
    rule_name: str = Field(description="规则名称")
    is_decorative_setting: bool = Field(
        description="是否为装饰设定（删去后人物策略与主要冲突均无变化）"
    )
    affected_strategies_count: int = Field(
        description="因该规则发生实质改变的人物策略数量"
    )
    affected_institutions_count: int = Field(
        description="因该规则发生实质改变的制度与权力结构数量"
    )
    evidence: str = Field(description="判定证据与推导理由")


class CostPropagationAuditReport(BaseModel):
    """代价传播审计报告（验证代价是否被后文悄悄抹去）."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(description="规则 ID")
    cost_statement: str = Field(description="声明的代价")
    cost_propagates_to_resources: bool = Field(
        default=True, description="代价是否传播到后续可用资源"
    )
    cost_propagates_to_health_or_state: bool = Field(
        default=True, description="代价是否传播到身体/精神状态"
    )
    cost_propagates_to_relationships: bool = Field(
        default=True, description="代价是否传播到人际与权力关系"
    )
    cost_propagates_to_subsequent_choices: bool = Field(
        default=True, description="代价是否制约了后续章节的备选行动"
    )
    unaccounted_cost_flags: list[str] = Field(
        default_factory=list, description="未被跟踪或被免除的代价记录"
    )
    is_cost_intact: bool = Field(
        default=True, description="综合判定代价是否全链条闭环传播"
    )
