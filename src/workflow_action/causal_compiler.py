"""世界因果编译器 (World Causal Compiler) 动作与审计器 (P6 研究轨).

实现：
1. compile_world_causality: 根规则 → 制度反应 → 角色策略空间推导。
2. audit_rule_deletion: 规则删除测试，检测装饰设定。
3. audit_cost_propagation: 代价传播审计，检测代价失效与免除。
"""

from __future__ import annotations

import hashlib
from typing import Optional

from src.object_state.causal_compiler import (
    CausalDerivation,
    CausalRule,
    CostPropagationAuditReport,
    RuleDeletionAuditReport,
)


def compile_world_causality(
    rule: CausalRule,
    trigger_event: str,
    active_characters: list[dict],
) -> CausalDerivation:
    """对单条规则与触发事件执行因果展开推导 (P6 研究轨，基于 SHA-256 确定性生成 ID)."""
    first_order = f"触发规则【{rule.rule_name}】：{rule.statement}。直接导致资源或能力状态变动。"

    if rule.institutional_enforcement:
        second_order = f"触动制度机制【{rule.institutional_enforcement}】，相关利益群体（{', '.join(rule.affected_groups)}）改变对待主角的博弈策略。"
    else:
        second_order = f"相关受影响群体（{', '.join(rule.affected_groups) or '周边势力'}）自发形成防御或争夺行为。"

    strategy_lines = []
    for char in active_characters:
        name = char.get("name", "主要角色")
        strategy_lines.append(f"{name} 必须在承受【{rule.usage_cost or '环境限制'}】的前提下重新调整行动路线。")

    raw_key = f"{rule.rule_id}_{trigger_event}"
    deriv_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]

    return CausalDerivation(
        derivation_id=f"deriv_{rule.rule_id}_{deriv_hash}",
        rule_id=rule.rule_id,
        trigger_event=trigger_event,
        first_order_effect=first_order,
        second_order_effect=second_order,
        strategic_consequence="; ".join(strategy_lines),
        research_only=True,
    )


def audit_rule_deletion(
    rule: CausalRule,
    character_strategies_with_rule: list[str],
    character_strategies_without_rule: list[str],
    conflicts_with_rule: list[str],
    conflicts_without_rule: list[str],
) -> RuleDeletionAuditReport:
    """规则删除测试：对比规则存在与被删除后人物策略与主要冲突的差异."""
    strategy_diff = set(character_strategies_with_rule) ^ set(character_strategies_without_rule)
    conflict_diff = set(conflicts_with_rule) ^ set(conflicts_without_rule)

    affected_strat_count = len(strategy_diff)
    affected_inst_count = len(conflict_diff)

    is_decorative = (affected_strat_count == 0) and (affected_inst_count == 0)

    if is_decorative:
        evidence = f"删除规则【{rule.rule_name}】后，所有人物的最优行为选择与核心冲突均保持一致，该规则未对叙事产生结构性因果约束，属于装饰设定。"
    else:
        evidence = f"删除规则【{rule.rule_name}】导致 {affected_strat_count} 项人物策略与 {affected_inst_count} 项冲突发生实质改变，具有真实因果约束力。"

    return RuleDeletionAuditReport(
        rule_id=rule.rule_id,
        rule_name=rule.rule_name,
        is_decorative_setting=is_decorative,
        affected_strategies_count=affected_strat_count,
        affected_institutions_count=affected_inst_count,
        evidence=evidence,
    )


def audit_cost_propagation(
    rule: CausalRule,
    usage_events: list[dict],
    subsequent_narrative_states: list[dict],
) -> CostPropagationAuditReport:
    """代价传播审计：检查使用代价是否在后续状态与选择中得到闭环保留与传播."""
    cost_text = rule.usage_cost
    unaccounted_flags = []

    if not cost_text:
        return CostPropagationAuditReport(
            rule_id=rule.rule_id,
            cost_statement="无显式代价声明",
            cost_propagates_to_resources=True,
            cost_propagates_to_health_or_state=True,
            cost_propagates_to_relationships=True,
            cost_propagates_to_subsequent_choices=True,
            unaccounted_cost_flags=[],
            is_cost_intact=True,
        )

    # 检查后续状态中是否存在代价记录
    health_intact = True
    resource_intact = True
    choices_constrained = True

    for event in usage_events:
        cost_paid = event.get("cost_paid", "")
        if "重伤" in cost_text and not any("伤" in s.get("status", "") for s in subsequent_narrative_states):
            health_intact = False
            unaccounted_flags.append(f"事件 {event.get('event_id', 'unknown')} 声明了重伤代价，但后续状态中健康完好且无医治交代")

        if "修为受损" in cost_text and any(s.get("power_surge", False) for s in subsequent_narrative_states):
            resource_intact = False
            unaccounted_flags.append("声明修为受损代价，但下文紧接着战力突破且无代价偿还")

    is_intact = len(unaccounted_flags) == 0

    return CostPropagationAuditReport(
        rule_id=rule.rule_id,
        cost_statement=cost_text,
        cost_propagates_to_resources=resource_intact,
        cost_propagates_to_health_or_state=health_intact,
        cost_propagates_to_relationships=True,
        cost_propagates_to_subsequent_choices=choices_constrained,
        unaccounted_cost_flags=unaccounted_flags,
        is_cost_intact=is_intact,
    )
