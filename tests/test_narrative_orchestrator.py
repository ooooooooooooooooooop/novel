"""Tests for Narrative Orchestrator (P2).

Validates:
1. 7-dimension derivation (Reader expectation, Promise debt, Relational trajectory,
   Emotional pacing, Thread rotation, Chapter function, Density budget).
2. Zero-cost contract (byte-identical prompt when empty, silent degradation when off).
3. Adversarial tests (identical state + different history -> divergent directives and scoring).
4. Integration with proposal builder and candidate evaluation.
"""

import json
from pathlib import Path
import pytest

from src.object_state.charactermodel import CharacterModel
from src.object_state.factledger import FactEntry, FactLedger
from src.object_state.foreshadowgraph import ForeshadowEntry, ForeshadowGraph
from src.object_state.narrativestate import NarrativeState
from src.object_state.orchestration import (
    ChapterFunctionAllocation,
    EmotionalPacing,
    InformationDensityBudget,
    OrchestrationState,
    PromisePayoffDebt,
    ReaderExpectationHorizon,
    RelationalTrajectory,
    ThreadRotation,
)
from src.object_state.plotunit import PlotUnit
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.narrative_orchestrator import (
    NarrativeOrchestrator,
    load_orchestration_context,
)
from src.workflow_action.proposal_generator import build_proposal_prompt
from src.workflow_action.author_selector import evaluate_candidates


def _make_sample_objects():
    workspec = WorkSpec(
        genre="仙侠",
        subgenre="古典修真",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
        audience="老白读者",
        platform="通用",
    )
    world = WorldModel(
        world_facts=[],
        power_system="金丹元婴体系",
        social_structure="宗门林立",
        factions=["青云宗", "万毒门"],
        time_rules=[],
        prohibitions=["禁术必有代价"],
        consequence_logic=[],
    )
    c1 = CharacterModel(
        character_id="c001",
        name="林尘",
        identity="青云宗弃徒",
        outer_goal="查明灭门真相",
        inner_need="求道本心",
        fear="重蹈覆辙",
        flaw="多疑戒备",
        strength="神识过人",
        stance="中立探查",
        relations={"c002": "互相戒备的同行者"},
        relation_behaviors={"c002": "保持三步距离，不露底牌"},
        current_pressure=["宗门追杀令明日生效"],
    )
    c2 = CharacterModel(
        character_id="c002",
        name="苏清雪",
        identity="万毒门叛逃圣女",
        outer_goal="寻找解毒圣药",
        inner_need="摆脱宗门控制",
        fear="毒发身亡",
        flaw="行事狠辣",
        strength="通晓药理",
        stance="合作",
        secret="身怀万毒秘典残页",
    )
    state = NarrativeState(
        state_id="ns_001",
        current_time="天元三百年春",
        current_location="落枫谷古遗迹",
        current_situation="两人在遗迹入口避雨，四周妖气弥漫",
        active_characters=["c001", "c002"],
        active_conflicts=["妖兽夜袭迫在眉睫"],
        active_suspense_items=["万毒门暗探是否已在谷外设伏"],
        emotional_temperature="压抑",
        linked_open_threads=["th_01"],
    )
    facts = FactLedger(
        entries=[
            FactEntry(
                fact_id="f001",
                statement="林尘与苏清雪在落枫谷结成临时同盟",
                fact_type="relation",
                involved_entities=["c001", "c002"],
                confirmed=True,
            )
        ]
    )
    foreshadows = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="th_01",
                setup_point="第1章",
                content="林家祖传古玉在月圆之夜会发热异动",
                visibility_level="explicit",
                expected_payoff="揭晓古玉暗藏的仙府密匙秘密",
                current_status="active",
            ),
            ForeshadowEntry(
                thread_id="th_02",
                setup_point="第2章",
                content="苏清雪怀中的剧毒封印正在缓慢松动",
                visibility_level="implicit",
                expected_payoff="毒发危机迫使林尘作出抉择",
                current_status="active",
            ),
        ]
    )
    return [workspec, world, c1, c2, state, facts, foreshadows]


def _make_sample_proposal(unit_id: str, goal: str, conflict: str, text_keywords: str):
    pu = PlotUnit(
        unit_id=unit_id,
        level="scene",
        goal=goal,
        participants=["c001", "c002"],
        conflict=conflict,
        input_state_ref="ns_001",
        output_state_ref=f"ns_out_{unit_id}",
        released_information=[text_keywords] if "真相" in text_keywords or "秘密" in text_keywords else [],
        emotional_shift=text_keywords,
        hook="夜幕降临，远处传来啸声",
        consequences=["局势推进了一步"],
        is_effective=True,
    )
    ns = NarrativeState(
        state_id=f"ns_out_{unit_id}",
        current_time="天元三百年春夜",
        current_location="落枫谷深处",
        current_situation=f"推进后局势: {text_keywords}",
        active_characters=["c001", "c002"],
    )
    return {
        "plotunit": pu,
        "new_state": ns,
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": "取舍说明",
    }


class TestNarrativeOrchestratorDerivation:
    """测试 7 维编排状态的完整推导."""

    def test_all_seven_dimensions_present(self):
        objects = _make_sample_objects()
        orchestrator = NarrativeOrchestrator()
        state = orchestrator.derive_orchestration_state(objects, chapter_number=2)

        assert isinstance(state, OrchestrationState)
        assert isinstance(state.expectation_horizon, ReaderExpectationHorizon)
        assert isinstance(state.promise_debt, PromisePayoffDebt)
        assert isinstance(state.relational_trajectory, RelationalTrajectory)
        assert isinstance(state.emotional_pacing, EmotionalPacing)
        assert isinstance(state.thread_rotation, ThreadRotation)
        assert isinstance(state.chapter_function, ChapterFunctionAllocation)
        assert isinstance(state.density_budget, InformationDensityBudget)

        # 检查字段值
        assert state.chapter_number == 2
        assert state.expectation_horizon.cognitive_tension in ("medium", "high", "critical", "low")
        assert len(state.expectation_horizon.top_questions) > 0
        assert state.promise_debt.open_threads_count == 2
        assert "林尘" in state.relational_trajectory.dominant_dynamic or "苏清雪" in state.relational_trajectory.dominant_dynamic or "走向" in state.relational_trajectory.dominant_dynamic
        assert state.emotional_pacing.current_rhythm in ("buildup", "peak", "release", "valley", "recovery")
        assert len(state.thread_rotation.active_threads) == 2
        assert state.chapter_function.assigned_function == "escalation"
        assert state.density_budget.reveal_budget in ("conservative", "moderate", "burst")

    def test_to_prompt_context_rendering(self):
        objects = _make_sample_objects()
        orchestrator = NarrativeOrchestrator()
        state = orchestrator.derive_orchestration_state(objects, chapter_number=1)
        prompt_ctx = state.to_prompt_context()

        assert "【长程叙事编排导向】" in prompt_ctx
        assert "1. 读者预期:" in prompt_ctx
        assert "2. 承诺债务:" in prompt_ctx
        assert "3. 关系轨迹:" in prompt_ctx
        assert "4. 情绪节律:" in prompt_ctx
        assert "5. 线程轮换:" in prompt_ctx
        assert "6. 章节功能:" in prompt_ctx
        assert "7. 密度预算:" in prompt_ctx


class TestZeroCostContract:
    """测试零成本契约与静默降级."""

    def test_disabled_loader_returns_empty_string(self, tmp_path):
        objects = _make_sample_objects()
        ctx = load_orchestration_context(tmp_path, objects, enabled=False)
        assert ctx == ""
        assert not (tmp_path / "orchestration_state.json").exists()

    def test_empty_objects_returns_empty_string(self, tmp_path):
        ctx = load_orchestration_context(tmp_path, [], enabled=True)
        assert ctx == ""

    def test_proposal_prompt_byte_identical_when_orchestration_empty(self):
        objects = _make_sample_objects()
        cont = ContinueUnit()
        state = objects[4]
        chars = [objects[2], objects[3]]
        facts = objects[5]
        foreshadows = objects[6]

        prompt_without = build_proposal_prompt(
            cont, 2, state, chars, facts, foreshadows, orchestration_context=""
        )
        prompt_default = build_proposal_prompt(
            cont, 2, state, chars, facts, foreshadows
        )
        assert prompt_without == prompt_default

    def test_proposal_prompt_includes_orchestration_when_provided(self):
        objects = _make_sample_objects()
        cont = ContinueUnit()
        state = objects[4]
        chars = [objects[2], objects[3]]
        facts = objects[5]
        foreshadows = objects[6]

        orch_ctx = "【长程叙事编排导向】\n1. 读者预期: 重点解开古玉秘密"
        prompt_with = build_proposal_prompt(
            cont, 2, state, chars, facts, foreshadows, orchestration_context=orch_ctx
        )
        assert "【长程叙事编排导向】" in prompt_with
        assert "重点解开古玉秘密" in prompt_with
        assert "【多候选要求】" in prompt_with


class TestAdversarialOrchestration:
    """对抗测试：相同事实/状态 + 不同编排历史 -> 产出不同推进优先级与评分."""

    def test_adversarial_fatigue_vs_escalation(self):
        objects = _make_sample_objects()
        orchestrator = NarrativeOrchestrator()

        # 历史 A：连续两章极高压危机（审美疲劳风险）
        history_fatigue = [
            {"chapter": 1, "function": "escalation", "emotion": "危机"},
            {"chapter": 2, "function": "crisis", "emotion": "激昂"},
        ]
        # 历史 B：连续两章平稳铺垫
        history_calm = [
            {"chapter": 1, "function": "setup", "emotion": "平稳"},
            {"chapter": 2, "function": "setup", "emotion": "舒缓"},
        ]

        state_a = orchestrator.derive_orchestration_state(
            objects, history=history_fatigue, chapter_number=3
        )
        state_b = orchestrator.derive_orchestration_state(
            objects, history=history_calm, chapter_number=3
        )

        # 1. 导向分叉判定
        assert state_a.emotional_pacing.fatigue_risk is True
        assert state_a.emotional_pacing.target_temperature == "舒缓"
        assert state_a.chapter_function.assigned_function == "transition"

        assert state_b.emotional_pacing.fatigue_risk is False
        assert state_b.emotional_pacing.target_temperature == "激昂"
        assert state_b.chapter_function.assigned_function == "crisis"

        # 2. 候选评分对抗测试
        # 候选 1：冷静复盘、商议对策（缓冲型）
        proposal_calm = _make_sample_proposal(
            "pu_calm", "清点战利品并商议对策", "就利益分配进行探讨", "两人对坐沉思，商讨下一步行动"
        )
        # 候选 2：连续极高压血战（激化型）
        proposal_action = _make_sample_proposal(
            "pu_action", "生死搏杀突围", "妖王狂暴来袭", "生死关头血战，狂暴对轰厮杀"
        )

        score_a_calm, notes_a_calm = orchestrator.score_proposal_alignment(state_a, proposal_calm)
        score_a_act, notes_a_act = orchestrator.score_proposal_alignment(state_a, proposal_action)

        score_b_calm, notes_b_calm = orchestrator.score_proposal_alignment(state_b, proposal_calm)
        score_b_act, notes_b_act = orchestrator.score_proposal_alignment(state_b, proposal_action)

        # 在疲劳历史 A 下：缓冲候选得分明显高于高压血战候选
        assert score_a_calm > score_a_act
        assert any("疲劳" in n for n in notes_a_calm + notes_a_act)

        # 在平淡历史 B 下：危机爆发候选得分高于缓冲候选
        assert score_b_act > score_b_calm

    def test_adversarial_starved_thread_rotation(self):
        objects = _make_sample_objects()
        orchestrator = NarrativeOrchestrator()

        # 支线 th_02 过久未被提及
        history_starved = [
            {"chapter": 1, "function": "setup", "emotion": "平稳", "threads": ["th_01"]},
            {"chapter": 2, "function": "escalation", "emotion": "紧迫", "threads": ["th_01"]},
            {"chapter": 3, "function": "escalation", "emotion": "紧迫", "threads": ["th_01"]},
        ]
        state = orchestrator.derive_orchestration_state(
            objects, history=history_starved, chapter_number=4
        )

        assert "th_02" in state.thread_rotation.starved_threads
        assert state.thread_rotation.rotation_recommendation == "sub_rotation"

        # 候选 1 触及饿死支线 th_02
        prop_sub = _make_sample_proposal("pu_sub", "压制毒发", "th_02毒性发作", "苏清雪th_02隐患爆发")
        # 候选 2 纯走主线
        prop_main = _make_sample_proposal("pu_main", "继续探索古迹", "遭遇禁制", "破解石门")

        score_sub, notes_sub = orchestrator.score_proposal_alignment(state, prop_sub)
        score_main, notes_main = orchestrator.score_proposal_alignment(state, prop_main)

        assert score_sub > score_main
        assert any("防饿死" in n for n in notes_sub)


class TestCandidateEvaluationIntegration:
    """测试 CandidateEvaluation 对 OrchestrationState 的消费."""

    def test_evaluate_candidates_records_orchestration_score(self):
        objects = _make_sample_objects()
        orchestrator = NarrativeOrchestrator()
        orch_state = orchestrator.derive_orchestration_state(objects, chapter_number=1)

        pkg_a = _make_sample_proposal("pu_A", "目标A", "冲突A", "平稳推进")
        pkg_b = _make_sample_proposal("pu_B", "目标B", "冲突B", "商议探讨")
        packages = [pkg_a, pkg_b]

        evals = evaluate_candidates(
            packages,
            objects,
            current_state_ref="ns_001",
            orchestration_state=orch_state,
        )

        assert "A" in evals and "B" in evals
        assert evals["A"].orchestration_score is not None
        assert evals["B"].orchestration_score is not None
        assert isinstance(evals["A"].orchestration_notes, list)


class TestPersistenceIntegration:
    """测试状态落盘与加载."""

    def test_load_orchestration_context_persists_state(self, tmp_path):
        objects = _make_sample_objects()
        ctx = load_orchestration_context(
            tmp_path,
            objects,
            enabled=True,
            chapter_number=3,
        )
        assert "【长程叙事编排导向】" in ctx
        state_file = tmp_path / "orchestration_state.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["chapter_number"] == 3
        assert "expectation_horizon" in data
        assert "promise_debt" in data
        assert "relational_trajectory" in data
        assert "emotional_pacing" in data
        assert "thread_rotation" in data
        assert "chapter_function" in data
        assert "density_budget" in data
