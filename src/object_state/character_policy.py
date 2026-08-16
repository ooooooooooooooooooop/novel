"""人物策略引擎 (Character Policy Engine) 数据模型 (P6 研究轨).

根据 docs/00_project/52_mastery_upgrade_plan.md §7:
- 人物行动提案接口：基于目标/恐惧/价值排序/错误信念/已知信息（信息权限）/关系债务/资源/当前压力/对他人的判断生成行动提案。
- 人物只提出行动、局部动机、预测他人反应与暴露信息不对称，禁止直接写正文。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CharacterPolicyState(BaseModel):
    """人物策略决策状态（局部认知、动机与约束）."""

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(description="人物唯一标识")
    character_name: str = Field(description="人物名称")
    primary_goals: list[str] = Field(
        default_factory=list, description="首要核心目标（按优先级排序）"
    )
    core_fears: list[str] = Field(
        default_factory=list, description="深层恐惧与不可触碰底线"
    )
    value_hierarchy: list[str] = Field(
        default_factory=list,
        description="价值取舍排序（如 ['家族延续', '自身安危', '宗门威信']）",
    )
    false_beliefs: list[str] = Field(
        default_factory=list,
        description="人物持有的错误认知或被误导的信息（制造认知差与戏剧反讽）",
    )
    known_facts: list[str] = Field(
        default_factory=list, description="人物已确认知晓的事实（严格信息权限）"
    )
    relational_debts: dict[str, str] = Field(
        default_factory=dict, description="对其他角色的人情/恩怨/承诺债务"
    )
    available_resources: list[str] = Field(
        default_factory=list, description="当前实际可支配的物质与能力资源"
    )
    current_pressure: float = Field(
        default=0.5, ge=0.0, le=1.0, description="当前承受的外部情境与时间压力"
    )
    beliefs_about_others: dict[str, str] = Field(
        default_factory=dict, description="对其他主要角色意图和能力的判断"
    )


class CharacterActionProposal(BaseModel):
    """人物策略引擎生成的行动提案."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(description="提案唯一标识")
    character_id: str = Field(description="提出行动的人物 ID")
    proposed_action: str = Field(description="人物在当前局势下选择采取的行动")
    local_motivation: str = Field(
        description="从该人物局部视角完全成立的行动动机"
    )
    predicted_other_reactions: dict[str, str] = Field(
        default_factory=dict,
        description="人物预测其他相关角色会作出的反应（可能包含误判）",
    )
    information_asymmetry_revealed: str = Field(
        default="", description="该行动暴露或利用的信息不对称"
    )
    risk_assessment: str = Field(
        default="", description="人物自身意识到的风险与盲区"
    )
