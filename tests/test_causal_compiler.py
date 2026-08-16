"""P6 世界因果编译器 (World Causal Compiler) 单元测试.

覆盖：
1. 规则展开与二阶推导 (compile_world_causality)。
2. 规则删除测试 (audit_rule_deletion)：检出装饰设定 vs 真实因果约束。
3. 代价传播审计 (audit_cost_propagation)：检出代价失效抹除 vs 闭环代价。
"""

import pytest

from src.object_state.causal_compiler import (
    CausalDerivation,
    CausalRule,
    CostPropagationAuditReport,
    RuleDeletionAuditReport,
)
from src.workflow_action.causal_compiler import (
    audit_cost_propagation,
    audit_rule_deletion,
    compile_world_causality,
)


class TestWorldCausalCompiler:
    def test_compile_world_causality_derivation(self):
        rule = CausalRule(
            rule_id="rule_soul_drain",
            rule_name="神魂燃血代价",
            rule_type="cost_constraint",
            statement="凡施展九幽禁术者，必损耗三年神魂寿元且三月内无法动用神识。",
            usage_cost="三年神魂寿元与三月神识封锁",
            institutional_enforcement="执法堂严禁私用禁术，违者废除修为",
            affected_groups=["宗门执法堂", "魔道余孽", "同门弟子"],
        )

        active_chars = [{"name": "林尘"}, {"name": "执法堂长老"}]
        deriv = compile_world_causality(rule, trigger_event="林尘绝境施展九幽禁术", active_characters=active_chars)

        assert isinstance(deriv, CausalDerivation)
        assert deriv.rule_id == "rule_soul_drain"
        assert "九幽禁术" in deriv.first_order_effect
        assert "执法堂严禁私用禁术" in deriv.second_order_effect
        assert "林尘" in deriv.strategic_consequence

    def test_audit_rule_deletion_detects_decorative_setting(self):
        # 装饰设定：删去后人物策略和主要冲突毫无变化
        dec_rule = CausalRule(
            rule_id="rule_fluff_moon",
            rule_name="双月同天微光",
            rule_type="capability_boundary",
            statement="天穹上有两轮明月，光芒微带青色。",
            affected_groups=[],
        )

        report = audit_rule_deletion(
            dec_rule,
            character_strategies_with_rule=["正面硬拼", "暗中取证"],
            character_strategies_without_rule=["正面硬拼", "暗中取证"],
            conflicts_with_rule=["宗门争斗"],
            conflicts_without_rule=["宗门争斗"],
        )

        assert report.is_decorative_setting is True
        assert report.affected_strategies_count == 0
        assert "装饰设定" in report.evidence

    def test_audit_rule_deletion_validates_active_causal_rule(self):
        # 真实因果规则：删去后策略发生实质转变
        real_rule = CausalRule(
            rule_id="rule_spirit_scarcity",
            rule_name="灵气枯竭税",
            rule_type="resource_scarcity",
            statement="宗门按月征收灵石税，交不起者贬为杂役矿奴。",
            usage_cost="灵石资源消耗",
            institutional_enforcement="矿堂强制押解",
            affected_groups=["外门弟子", "矿堂守卫"],
        )

        report = audit_rule_deletion(
            real_rule,
            character_strategies_with_rule=["拼命下山做悬赏任务赚灵石", "向高利贷借灵石"],
            character_strategies_without_rule=["在宗门内安心打坐修炼", "随意外出游玩"],
            conflicts_with_rule=["还债危机", "矿奴暴动"],
            conflicts_without_rule=["同门切磋"],
        )

        assert report.is_decorative_setting is False
        assert report.affected_strategies_count > 0
        assert "真实因果约束力" in report.evidence

    def test_audit_cost_propagation_detects_erased_cost(self):
        rule = CausalRule(
            rule_id="rule_heavy_cost",
            rule_name="禁术反噬",
            rule_type="cost_constraint",
            statement="施术必身受重伤经脉破损",
            usage_cost="重伤",
        )

        # 违规样本：使用事件记录了重伤，但后续叙事状态中健康完好
        usage_events = [{"event_id": "ev_01", "cost_paid": "重伤"}]
        subsequent_states = [{"status": "精力充沛，完好无损"}]

        report = audit_cost_propagation(rule, usage_events, subsequent_states)
        assert report.is_cost_intact is False
        assert len(report.unaccounted_cost_flags) >= 1
        assert "健康完好且无医治交代" in report.unaccounted_cost_flags[0]
