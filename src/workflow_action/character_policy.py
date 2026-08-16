"""人物策略引擎 (Character Policy Engine) 动作实现 (P6 研究轨).

实现：
generate_character_action_proposal:
- 依据人物局部目标、已知信息、错误信念、关系债务、价值排序与资源约束生成行动提案。
- 保证信息权限隔离（角色只能基于 known_facts 与 false_beliefs 决策，禁止全知）。
- 输出 CharacterActionProposal，严禁直接生成小说正文。
"""

from __future__ import annotations

import hashlib
from typing import Optional

from src.object_state.character_policy import (
    CharacterActionProposal,
    CharacterPolicyState,
)


def generate_character_action_proposal(
    policy: CharacterPolicyState,
    situation: str,
    proposal_id: Optional[str] = None,
) -> CharacterActionProposal:
    """基于人物局部策略状态生成当前局势下的行动提案 (P6 研究轨，基于 SHA-256 确定性生成 ID)."""
    if proposal_id:
        p_id = proposal_id
    else:
        raw_key = f"{policy.character_id}_{situation}"
        prop_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]
        p_id = f"cap_{policy.character_id}_{prop_hash}"

    # 1. 提取首要目标与首要恐惧
    top_goal = policy.primary_goals[0] if policy.primary_goals else "保全自身立足点"
    top_fear = policy.core_fears[0] if policy.core_fears else "失去已有控制权"

    # 2. 结合价值排序与资源构建行动逻辑
    val_top = policy.value_hierarchy[0] if policy.value_hierarchy else "现实利益"
    avail_res = ", ".join(policy.available_resources) if policy.available_resources else "基础个人能力"

    # 3. 错误信念制造局部盲区
    false_belief_note = ""
    if policy.false_beliefs:
        false_belief_note = f"（基于其误以为『{policy.false_beliefs[0]}』）"

    # 4. 构建局部自洽的行动提案
    if policy.current_pressure >= 0.7:
        action = f"在承受高压逼迫下，优先动用【{avail_res}】以确保【{val_top}】，采取防御性反制策略以规避【{top_fear}】{false_belief_note}。"
    else:
        action = f"在局势尚可控时，暗中调动【{avail_res}】推进【{top_goal}】，同时维持对【{top_fear}】的警惕防备{false_belief_note}。"

    motivation = (
        f"从【{policy.character_name}】局部视角，其首要价值为【{val_top}】，"
        f"在当前已知信息（{len(policy.known_facts)} 条已知事实）下，该方案是最优生存与获益路径。"
    )

    # 5. 预测他人反应与信息不对称
    predicted_reactions = {}
    for other, belief in policy.beliefs_about_others.items():
        predicted_reactions[other] = f"预计其因【{belief}】而会产生迟疑或被诱导"

    info_asymmetry = ""
    if policy.false_beliefs:
        info_asymmetry = f"人物存在认知盲区：误信『{policy.false_beliefs[0]}』，可能被真正知情者利用。"
    elif len(policy.known_facts) > 0:
        info_asymmetry = f"人物掌握了对手尚未公开的先验事实（{policy.known_facts[0]}）。"

    risk = f"若外部局势超出【{val_top}】承受底线，或【{top_fear}】被对手击中，策略将面临破产。"

    return CharacterActionProposal(
        proposal_id=p_id,
        character_id=policy.character_id,
        proposed_action=action,
        local_motivation=motivation,
        predicted_other_reactions=predicted_reactions,
        information_asymmetry_revealed=info_asymmetry,
        risk_assessment=risk,
    )
