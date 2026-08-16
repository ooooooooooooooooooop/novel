"""P6 人物策略引擎 (Character Policy Engine) 单元测试.

覆盖：
1. 局部动机、价值排序与资源约束对行动提案的影响。
2. 错误信念 (false_beliefs) 与戏剧认知盲区。
3. 严格信息权限隔离与行动提案生成 (generate_character_action_proposal)。
"""

import pytest

from src.object_state.character_policy import (
    CharacterActionProposal,
    CharacterPolicyState,
)
from src.workflow_action.character_policy import (
    generate_character_action_proposal,
)


class TestCharacterPolicyEngine:
    def test_character_action_proposal_respects_policy_and_blindspots(self):
        policy = CharacterPolicyState(
            character_id="char_elder_chen",
            character_name="陈长老",
            primary_goals=["维持对戒律堂的掌控", "为私生子铺平真传之路"],
            core_fears=["当年私吞宗门灵脉的事发暴露"],
            value_hierarchy=["家族利益", "长老地位", "宗门法纪"],
            false_beliefs=["主角林尘只是个没有背景的普通外门杂役"],
            known_facts=["林尘昨日进入过戒律密室"],
            available_resources=["戒律堂执法队", "宗门三品禁锢阵盘"],
            current_pressure=0.85,
            beliefs_about_others={"林尘": "容易被恐吓屈服"},
        )

        proposal = generate_character_action_proposal(
            policy,
            situation="林尘在演武场声称掌握假账证据",
            proposal_id="prop_chen_01",
        )

        assert isinstance(proposal, CharacterActionProposal)
        assert proposal.character_id == "char_elder_chen"
        assert "戒律堂执法队" in proposal.proposed_action
        assert "陈长老" in proposal.local_motivation
        assert "普通外门杂役" in proposal.proposed_action
        assert "林尘" in proposal.predicted_other_reactions
        assert "误信" in proposal.information_asymmetry_revealed

    def test_low_pressure_proactive_policy_proposal(self):
        policy = CharacterPolicyState(
            character_id="char_su_qingxue",
            character_name="苏清雪",
            primary_goals=["查明师尊失踪真相"],
            core_fears=["被宗门保守派软禁"],
            value_hierarchy=["真相", "师门情谊", "个人名誉"],
            available_resources=["宗门藏经阁特许令", "家族传讯灵蝶"],
            current_pressure=0.3,
            known_facts=["藏经阁第七层有封印记录"],
        )

        proposal = generate_character_action_proposal(
            policy,
            situation="宗门大比前夕各方备战",
        )

        assert "苏清雪" in proposal.local_motivation
        assert "查明师尊失踪真相" in proposal.proposed_action
        assert "藏经阁特许令" in proposal.proposed_action
