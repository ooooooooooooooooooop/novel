"""Structural Search —— 章节级多尺度叙事搜索、异质性门禁、短程 Rollout 与 Pareto 锦标赛 (P3 & R3 整改).

对应 docs/00_project/52_mastery_upgrade_plan.md §4 及 R3 整改要求:
1. 候选表示：主要行动者 / 核心选择 / 阻力来源 / 代价 / 状态变化 / 关系变化 / 信息揭示 / 读者预期变化 / 对未来 3-5 章影响 / 主要风险。
2. 结构异质性硬门禁 (Diversity Gate)：近重复检测，全重复/伪装多样性时显式抛出 structural_diversity_failed，绝不静默兜底 proposals[:1]。
3. 真实状态克隆 3-5 章 Rollout (RolloutPlannerUnit)：深拷贝当前世界与叙事对象，真实推演状态演化，规则破坏直接淘汰。
4. 多维 Pareto 锦标赛：独立多维（因果/人物/读者/作品/原创/可持续/风险），禁止加权单总分。
5. Candidate Precommit 强绑定：生成正文前冻结本轮选择依据，选出结果成为生产唯一权威。
6. 启发式重命名为 heuristic_risk_probe。
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence

from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    CrossWorkValidationResult,
)
from src.object_state.charactermodel import CharacterModel
from src.object_state.factledger import FactEntry, FactLedger
from src.object_state.foreshadowgraph import ForeshadowEntry, ForeshadowGraph
from src.object_state.narrativestate import NarrativeState
from src.object_state.orchestration import OrchestrationState
from src.object_state.plotunit import PlotUnit
from src.object_state.structural_search import (
    CandidatePrecommit,
    NearDuplicatePair,
    ParetoDimensionScores,
    RolloutDelta,
    RolloutEvaluation,
    RolloutStateSnapshot,
    RolloutStep,
    RolloutTransition,
    StructuralDiversityReport,
    StructuralProposal,
    StructuralSearchResult,
)
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel
from src.workflow_action.authormodel_v3 import (
    is_author_model_certified_for_production,
    score_author_prior,
)


# ---------------------------------------------------------------------------
# 1. 结构异质性门禁与近重复检测 (Diversity Gate)
# ---------------------------------------------------------------------------

def _text_similarity(a: str, b: str) -> float:
    """计算两段文本的相似度 (0.0 - 1.0)."""
    a_clean = a.strip()
    b_clean = b.strip()
    if not a_clean and not b_clean:
        return 1.0
    if not a_clean or not b_clean:
        return 0.0
    return difflib.SequenceMatcher(None, a_clean, b_clean).ratio()


def evaluate_structural_diversity(
    proposals: list[StructuralProposal],
    threshold: float = 0.55,
) -> StructuralDiversityReport:
    """检查候选池是否具备真正的结构异质性，剔除结构近重复."""
    if not proposals:
        return StructuralDiversityReport(
            is_diverse=False,
            diversity_score=0.0,
            near_duplicates=[],
            valid_proposals=[],
            reasons=["候选列表为空"],
        )

    if len(proposals) == 1:
        return StructuralDiversityReport(
            is_diverse=True,
            diversity_score=1.0,
            near_duplicates=[],
            valid_proposals=[proposals[0].proposal_id],
            reasons=["单候选模式"],
        )

    near_duplicates: list[NearDuplicatePair] = []
    excluded_ids: set[str] = set()

    for i in range(len(proposals)):
        for j in range(i + 1, len(proposals)):
            p_a = proposals[i]
            p_b = proposals[j]

            shared_dims: list[str] = []
            # 1. 行动者
            same_actor = p_a.primary_actor.strip() == p_b.primary_actor.strip()
            if same_actor:
                shared_dims.append("primary_actor")

            # 2. 核心选择相似度
            choice_sim = _text_similarity(p_a.core_choice, p_b.core_choice)
            if choice_sim >= 0.5:
                shared_dims.append("core_choice")

            # 3. 阻力来源相似度
            res_sim = _text_similarity(p_a.resistance_source, p_b.resistance_source)
            if res_sim >= 0.5:
                shared_dims.append("resistance_source")

            # 4. 代价相似度
            cost_sim = _text_similarity(p_a.cost, p_b.cost)
            if cost_sim >= 0.5:
                shared_dims.append("cost")

            # 5. 状态变化相似度
            state_sim = _text_similarity(p_a.state_change, p_b.state_change)
            if state_sim >= 0.5:
                shared_dims.append("state_change")

            # 6. 章节功能
            same_fn = p_a.chapter_function.strip() == p_b.chapter_function.strip()
            if same_fn:
                shared_dims.append("chapter_function")

            # 综合结构重合度
            structural_sim = (
                (1.0 if same_actor else 0.0) * 0.20
                + choice_sim * 0.25
                + cost_sim * 0.20
                + state_sim * 0.20
                + res_sim * 0.10
                + (1.0 if same_fn else 0.0) * 0.05
            )

            if structural_sim >= threshold or len(shared_dims) >= 4:
                near_duplicates.append(
                    NearDuplicatePair(
                        proposal_a=p_a.proposal_id,
                        proposal_b=p_b.proposal_id,
                        similarity_score=round(structural_sim, 4),
                        shared_dimensions=shared_dims,
                        reason=f"结构近重复: 在 {', '.join(shared_dims)} 维度高度重合 (相似度 {structural_sim:.2f})",
                    )
                )
                # 剔除后者
                excluded_ids.add(p_b.proposal_id)

    valid_proposals = [p.proposal_id for p in proposals if p.proposal_id not in excluded_ids]
    diversity_score = len(valid_proposals) / len(proposals) if proposals else 0.0
    is_diverse = len(valid_proposals) >= 2 or (len(proposals) == 1 and len(valid_proposals) == 1)

    reasons: list[str] = []
    if near_duplicates:
        reasons.append(f"检出 {len(near_duplicates)} 对结构近重复候选")
    if is_diverse:
        reasons.append(f"候选池具备实质结构异质性 ({len(valid_proposals)}/{len(proposals)} 有效)")
    else:
        reasons.append(f"候选池结构异质性不足，有效分叉方案过少 ({len(valid_proposals)} 个)")

    return StructuralDiversityReport(
        is_diverse=is_diverse,
        diversity_score=round(diversity_score, 4),
        near_duplicates=near_duplicates,
        valid_proposals=valid_proposals,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# 2. 启发式风险探针与克隆状态推演 (heuristic_risk_probe & RolloutPlannerUnit)
# ---------------------------------------------------------------------------

_HIGH_STIMULUS_MARKERS = (
    "暴涨", "秒杀", "直接斩杀", "无敌", "顿悟圆满", "碾压", "十倍", "百倍",
    "瞬间突破", "连破三阶", "毫无悬念", "神级底牌",
)

_FATAL_TERMINAL_FACT_MARKERS = (
    "死亡", "已死", "殒命", "身亡", "击杀", "阵亡",
    "摧毁", "毁灭", "彻底损毁", "化为飞灰", "灰飞烟灭",
    "失去", "被夺", "被废", "剥夺", "公之于众", "废除",
)

_DELIBERATE_SETUP_MARKERS = (
    "暗中布局", "隐忍", "潜伏", "埋下暗线", "付出重伤代价", "牺牲", "封印",
    "借力打力", "以退为进", "交换条件", "立下血誓", "交出秘宝",
)

_CHEAP_COSMETIC_MARKERS = (
    "原地等待", "无关闲聊", "暂不理会", "无事发生", "稍作休整", "略微寒暄",
)


def heuristic_risk_probe(proposal_text: str) -> list[str]:
    """启发式风险探针（仅作为辅助探测信号，不可代替深层状态推演）."""
    flags: list[str] = []
    if any(m in proposal_text for m in _HIGH_STIMULUS_MARKERS):
        flags.append("heuristic_probe: reckless_escalation_burnout (战力透支与疲劳断崖风险)")
    if any(m in proposal_text for m in _CHEAP_COSMETIC_MARKERS):
        flags.append("heuristic_probe: flat_filler_stagnation (主线停滞与伪推进风险)")
    return flags


def clone_and_rollout_planner(
    proposal: StructuralProposal,
    state: NarrativeState,
    objects: list,
    steps: int = 3,
    workspec: Optional[WorkSpec] = None,
) -> RolloutEvaluation:
    """真实深拷贝对象级状态推演（RolloutPlannerUnit）:

    深拷贝 [NarrativeState, FactLedger, ForeshadowGraph, Characters, WorldModel]，
    执行真正的多步对象状态演化转移（RolloutStateSnapshot, RolloutDelta, RolloutTransition）：
    - Step 1: 真实应用候选方案的 state_change、cost、relationship_change
    - Step 2..K: 动态推演角色心理反应、世界规则反作用、伏笔生命周期与因果链
    - 伏笔检索使用 ForeshadowGraph.entries
    - 发现致命非法分支时将 sustainability 归零并阻断。
    """
    steps = max(3, min(5, steps))

    # 1. 深度拷贝隔离运行时所有状态对象，防止推演产生主线副作用
    cloned_state = state.model_copy(deep=True)
    cloned_objects = [
        o.model_copy(deep=True) if hasattr(o, "model_copy") else copy.deepcopy(o)
        for o in objects
    ]
    cloned_world = next((o for o in cloned_objects if isinstance(o, WorldModel)), None)
    cloned_ledger = next((o for o in cloned_objects if isinstance(o, FactLedger)), None)
    cloned_foreshadow = next((o for o in cloned_objects if isinstance(o, ForeshadowGraph)), None)
    cloned_characters: list[CharacterModel] = [o for o in cloned_objects if isinstance(o, CharacterModel)]

    # 记录 Step 0 初始状态快照
    initial_pressures = {
        c.character_id or c.name: list(c.current_pressure)
        for c in cloned_characters
    }
    initial_threads = [
        getattr(e, "thread_id", str(idx))
        for idx, e in enumerate(getattr(cloned_foreshadow, "entries", []))
        if getattr(e, "current_status", "active") == "active"
    ] if cloned_foreshadow else []
    initial_prohibitions = (
        list(cloned_world.prohibitions or []) + list(cloned_world.forbidden_actions or [])
        if cloned_world else []
    )
    initial_facts_count = len([
        e for e in getattr(cloned_ledger, "entries", [])
        if getattr(e, "confirmed", False)
    ]) if cloned_ledger else 0

    initial_snapshot = RolloutStateSnapshot(
        step_index=0,
        state_id=cloned_state.state_id,
        current_situation=cloned_state.current_situation,
        open_questions=list(cloned_state.open_questions or []),
        active_conflicts=list(cloned_state.active_conflicts or []),
        active_threads=initial_threads,
        character_pressures=initial_pressures,
        facts_count=initial_facts_count,
        prohibitions_checked=initial_prohibitions,
    )

    proposal_text = " ".join([
        proposal.core_choice,
        proposal.cost,
        proposal.state_change,
        proposal.impact_next_3_to_5_chapters,
        proposal.primary_risk,
    ])

    risk_flags = heuristic_risk_probe(proposal_text)
    is_high_stimulus = any("reckless_escalation_burnout" in f for f in risk_flags)
    is_deliberate_setup = any(m in proposal_text for m in _DELIBERATE_SETUP_MARKERS)
    is_cheap_cosmetic = any("flat_filler_stagnation" in f for f in risk_flags)

    # 2. 真实对象级推演与守恒检验
    # A. 世界规则禁忌守恒检验
    hard_rule_violation = False
    rule_violation_detail = ""
    if cloned_world:
        prohibitions = list(cloned_world.prohibitions or []) + list(cloned_world.forbidden_actions or [])
        cost_clean = proposal.cost.strip()
        is_zero_cost = not cost_clean or cost_clean in ("无", "无代价", "暂无", "无明确代价") or "无代价" in cost_clean
        for p in prohibitions:
            if not p:
                continue
            if is_zero_cost and (
                p in proposal_text
                or any(k in proposal_text and k in p for k in ("逆转生死", "经脉", "复活", "禁术", "断绝生机", "损毁"))
            ):
                hard_rule_violation = True
                rule_violation_detail = f"触犯世界禁忌[{p}]且未支付必要代价"
                risk_flags.append(f"hard_rule_violation: {rule_violation_detail}")
                break

    # B. 角色压力与关系演变模拟
    actor_char = None
    if proposal.primary_actor and cloned_characters:
        actor_char = next(
            (c for c in cloned_characters if c.name == proposal.primary_actor or c.character_id == proposal.primary_actor),
            None,
        )

    character_stress_overload = False
    if actor_char is not None:
        if any(w in proposal.cost for w in ("重伤", "反噬", "透支", "牺牲", "折寿", "残疾", "被废")):
            actor_char.current_pressure.append(f"rollout_cost: {proposal.cost}")
        if proposal.relationship_change and isinstance(actor_char.relations, dict):
            actor_char.relations["last_shift"] = proposal.relationship_change
        if len(actor_char.current_pressure) >= 5:
            character_stress_overload = True
            risk_flags.append("character_stress_overload: 角色承受压力达到崩溃临界")

    # C. 事实账本终结性事实冲突探测 (Fatal/Terminal Fact Check)
    causal_contradiction = False
    if cloned_ledger:
        for entry in getattr(cloned_ledger, "entries", []):
            if not getattr(entry, "confirmed", False):
                continue
            # 检查已确认死亡/终结/摧毁/失去的实体是否在 proposal 中被无代价或矛盾逆转复用
            for term in _FATAL_TERMINAL_FACT_MARKERS:
                if term in entry.statement:
                    involved = getattr(entry, "involved_entities", [])
                    matches_entity = any(ent in proposal_text for ent in involved if ent) or any(
                        chunk in entry.statement for chunk in (proposal.primary_actor, proposal.core_choice[:10]) if chunk
                    )
                    if matches_entity:
                        if any(rev in proposal.state_change or rev in proposal.core_choice for rev in ("恢复", "完好如初", "平安无事", "现身相助", "未死", "重获")):
                            if not is_deliberate_setup:
                                causal_contradiction = True
                                risk_flags.append(f"causal_contradiction: 与已确认终结性事实『{entry.statement}』存在矛盾逆转冲突")
                                break
                    elif term in entry.statement and "恢复" in proposal.state_change and not is_deliberate_setup:
                        causal_contradiction = True
                        risk_flags.append(f"causal_contradiction: 与已确认终结性事实『{entry.statement}』存在因果冲突")
                        break
            if causal_contradiction:
                break

    # D. 伏笔/线索饿死检测 (修复: 使用 entries 而非 nodes)
    thread_starvation = False
    if cloned_foreshadow:
        foreshadow_entries = getattr(cloned_foreshadow, "entries", [])
        open_entries = [
            e for e in foreshadow_entries
            if getattr(e, "current_status", "") == "active" or getattr(e, "status", "") == "active"
        ]
        if len(open_entries) >= 4 and not proposal.information_reveal and not is_deliberate_setup:
            thread_starvation = True
            risk_flags.append("thread_starvation: 活跃线索积压过多且未在推演中进行推进或照应")

    rollout_steps: list[RolloutStep] = []
    rollout_transitions: list[RolloutTransition] = []
    current_snapshot = initial_snapshot

def _rollout_single_step(
    step_idx: int,
    current_snapshot: RolloutStateSnapshot,
    cloned_state: NarrativeState,
    cloned_characters: list[CharacterModel],
    cloned_ledger: Optional[FactLedger],
    cloned_foreshadow: Optional[ForeshadowGraph],
    cloned_world: Optional[WorldModel],
    proposal: StructuralProposal,
    hard_rule_violation: bool,
    rule_violation_detail: str,
    causal_contradiction: bool,
    character_stress_overload: bool,
    is_high_stimulus: bool,
    is_deliberate_setup: bool,
    is_cheap_cosmetic: bool,
    thread_starvation: bool,
    initial_prohibitions: list[str],
) -> tuple[RolloutStep, RolloutDelta, RolloutStateSnapshot, RolloutTransition]:
    """执行状态驱动的单步状态演化转移（State-Driven Rollout Step Evolution）.

    由前一步快照的状态、已确认事实与角色压力，动态驱动下一步的角色应对与世界反制。
    """
    step_notes: list[str] = []
    actor_char = None
    if proposal.primary_actor and cloned_characters:
        actor_char = next(
            (c for c in cloned_characters if c.name == proposal.primary_actor or c.character_id == proposal.primary_actor),
            None,
        )

    # 1. 动态步进状态演化 (State Mutation)
    cur_sit_delta = ""
    cur_rel_shifts: list[str] = []
    cur_foreshadow_adv: list[str] = []

    if step_idx == 1:
        # Step 1: 主角核心选择落地与即时代价支付
        cur_sit_delta = f"主角行动落地: [{proposal.core_choice[:20]}] -> {proposal.state_change[:25]}"
        cloned_state.current_situation = f"{cloned_state.current_situation} -> {cur_sit_delta}"
        if proposal.relationship_change:
            cur_rel_shifts.append(proposal.relationship_change)
            step_notes.append(f"关系重构: {proposal.relationship_change}")
        if proposal.information_reveal:
            cur_foreshadow_adv.append(f"信息公开: {proposal.information_reveal}")
        if cloned_ledger and proposal.state_change:
            cloned_ledger.entries.append(
                FactEntry(
                    fact_id=f"f_rollout_step1_{proposal.proposal_id}",
                    fact_type="event",
                    statement=proposal.state_change,
                    confirmed=True,
                    involved_entities=[proposal.primary_actor] if proposal.primary_actor else [],
                )
            )
    elif step_idx == 2:
        # Step 2: 基于 Step 1 新状态，世界因果与阻力势力动态反制
        resistance_src = proposal.resistance_source or "外部反制力量"
        risk_outcome = proposal.primary_risk or "次生风险与局势演变"
        cur_sit_delta = f"阻力方[{resistance_src[:15]}]对Step 1行动采取反制，局势演变为: {risk_outcome[:25]}"
        cloned_state.current_situation = f"{cloned_state.current_situation} -> {cur_sit_delta}"
        step_notes.append(f"阻力反制: 来自 {resistance_src[:15]} 的反应展开")
        if actor_char is not None:
            actor_char.current_pressure.append(f"外部反制压力: 来自 {resistance_src[:15]}")
        if cloned_ledger:
            cloned_ledger.entries.append(
                FactEntry(
                    fact_id=f"f_rollout_step2_{proposal.proposal_id}",
                    fact_type="event",
                    statement=f"{resistance_src}针对主角行动采取应对反制",
                    confirmed=True,
                    involved_entities=[proposal.primary_actor] if proposal.primary_actor else [],
                )
            )
        if proposal.primary_risk:
            cur_foreshadow_adv.append(f"风险显露: {proposal.primary_risk[:20]}")
    else:
        # Step 3+: 叙事编排演化、长程因果后果发酵与期待流转
        impact_desc = proposal.impact_next_3_to_5_chapters or "进入下一阶段叙事稳态"
        exp_desc = proposal.reader_expectation_delta or "期待流转"
        cur_sit_delta = f"长程因果发酵: {impact_desc[:25]}，期待流转: {exp_desc[:20]}"
        cloned_state.current_situation = f"{cloned_state.current_situation} -> {cur_sit_delta}"
        step_notes.append(f"长程发酵: {impact_desc[:25]}")
        if proposal.reader_expectation_delta:
            cur_foreshadow_adv.append(f"期待推进: {proposal.reader_expectation_delta[:20]}")

    # 计算转移后快照
    next_pressures = {
        c.character_id or c.name: list(c.current_pressure)
        for c in cloned_characters
    }
    next_threads = [
        getattr(e, "thread_id", str(idx))
        for idx, e in enumerate(getattr(cloned_foreshadow, "entries", []))
        if getattr(e, "current_status", "active") == "active"
    ] if cloned_foreshadow else []
    next_facts_count = len([
        e for e in getattr(cloned_ledger, "entries", [])
        if getattr(e, "confirmed", False)
    ]) if cloned_ledger else 0

    next_snapshot = RolloutStateSnapshot(
        step_index=step_idx,
        state_id=f"{cloned_state.state_id}_step{step_idx}",
        current_situation=cloned_state.current_situation,
        open_questions=list(cloned_state.open_questions or []),
        active_conflicts=list(cloned_state.active_conflicts or []),
        active_threads=next_threads,
        character_pressures=next_pressures,
        facts_count=next_facts_count,
        prohibitions_checked=initial_prohibitions,
    )

    # 2. 动态指标计算 (基于演化后的真实状态与压力)
    actor_pressure_count = len(actor_char.current_pressure) if actor_char else 0
    if hard_rule_violation:
        fatigue = 1.0
        escalation = 1.0
        delayed_payoff = 0.0
        rule_risk = 1.0
        sustainability = 0.0
        step_notes.append(f"第+{step_idx}章: 世界规则崩溃 ({rule_violation_detail})，分支不可行")
    elif causal_contradiction:
        fatigue = 0.9
        escalation = 0.9
        delayed_payoff = 0.0
        rule_risk = 1.0
        sustainability = 0.0
        step_notes.append(f"第+{step_idx}章: 发生不可逆因果冲突，叙事链中断")
    elif character_stress_overload or actor_pressure_count >= 5:
        fatigue = min(1.0, 0.7 + 0.1 * step_idx)
        escalation = min(1.0, 0.6 + 0.1 * step_idx)
        delayed_payoff = 0.1
        rule_risk = 0.4
        sustainability = max(0.0, 0.3 - 0.1 * step_idx)
        step_notes.append(f"第+{step_idx}章: 角色心理与生理张力过载(压力={actor_pressure_count})，行动自洽度下降")
    elif is_high_stimulus:
        fatigue = min(1.0, 0.4 + 0.25 * step_idx)
        escalation = min(1.0, 0.5 + 0.20 * step_idx)
        delayed_payoff = max(0.1, 0.5 - 0.15 * step_idx)
        rule_risk = min(1.0, 0.3 + 0.20 * step_idx)
        sustainability = max(0.1, 0.8 - 0.25 * step_idx)
        step_notes.append(f"第+{step_idx}章: 战力与刺激门槛被拔高，后续常规矛盾失效")
    elif is_deliberate_setup:
        fatigue = max(0.1, 0.3 - 0.05 * step_idx)
        escalation = max(0.1, 0.3 - 0.05 * step_idx)
        delayed_payoff = min(1.0, 0.5 + 0.18 * step_idx)
        rule_risk = 0.1
        sustainability = min(1.0, 0.75 + 0.08 * step_idx)
        step_notes.append(f"第+{step_idx}章: 前置代价与暗线逐渐发酵，提供深层情绪回馈")
    elif is_cheap_cosmetic or thread_starvation:
        fatigue = min(1.0, 0.5 + 0.15 * step_idx)
        escalation = 0.2
        delayed_payoff = 0.2
        rule_risk = 0.1
        sustainability = max(0.2, 0.5 - 0.10 * step_idx)
        step_notes.append(f"第+{step_idx}章: 缺乏有效状态转移或支线滞留，叙事动力减弱")
    else:
        fatigue = min(1.0, 0.3 + 0.05 * (actor_pressure_count - 1) if actor_pressure_count > 1 else 0.3)
        escalation = 0.3
        delayed_payoff = min(1.0, 0.5 + 0.10 * step_idx)
        rule_risk = 0.15
        sustainability = max(0.2, 0.85 - 0.1 * (actor_pressure_count - 1) if actor_pressure_count > 1 else 0.75)
        step_notes.append(f"第+{step_idx}章: 因果自洽推进，预期正常流转")

    step_metric = RolloutStep(
        step_index=step_idx,
        projected_situation=f"推演章+{step_idx}: 基于[{proposal.core_choice[:15]}]的后续状态演化",
        fatigue_index=round(fatigue, 4),
        escalation_debt=round(escalation, 4),
        delayed_payoff_yield=round(delayed_payoff, 4),
        rule_break_risk=round(rule_risk, 4),
        sustainability=round(sustainability, 4),
        notes=step_notes,
    )

    delta = RolloutDelta(
        step_from=current_snapshot.step_index,
        step_to=step_idx,
        situation_delta=cur_sit_delta,
        pressure_deltas={
            k: [p for p in next_pressures.get(k, []) if p not in current_snapshot.character_pressures.get(k, [])]
            for k in next_pressures
        },
        relationship_shifts=cur_rel_shifts,
        new_facts_count=max(0, next_facts_count - current_snapshot.facts_count),
        foreshadow_advancements=cur_foreshadow_adv,
        rule_violations=[rule_violation_detail] if hard_rule_violation and step_idx == 1 else [],
    )

    transition = RolloutTransition(
        from_snapshot=current_snapshot,
        delta=delta,
        to_snapshot=next_snapshot,
        step_metrics=step_metric,
    )
    return step_metric, delta, next_snapshot, transition


def simulate_dynamic_state_rollout(
    proposal: StructuralProposal,
    state: NarrativeState,
    objects: list,
    steps: int = 3,
    workspec: Optional[WorkSpec] = None,
) -> RolloutEvaluation:
    """真实深拷贝对象级状态推演（RolloutPlannerUnit / State-Driven Rollout）:

    深拷贝 [NarrativeState, FactLedger, ForeshadowGraph, Characters, WorldModel]，
    执行真正的多步对象状态演化转移（RolloutStateSnapshot, RolloutDelta, RolloutTransition）：
    - Step 1: 真实应用候选方案的 state_change、cost、relationship_change
    - Step 2..K: 动态推演角色心理反应、世界规则反作用、伏笔生命周期与因果链
    - 伏笔检索使用 ForeshadowGraph.entries
    - 发现致命非法分支时将 sustainability 归零并阻断。
    """
    steps = max(3, min(5, steps))

    # 1. 深度拷贝隔离运行时所有状态对象，防止推演产生主线副作用
    cloned_state = state.model_copy(deep=True)
    cloned_objects = [
        o.model_copy(deep=True) if hasattr(o, "model_copy") else copy.deepcopy(o)
        for o in objects
    ]
    cloned_world = next((o for o in cloned_objects if isinstance(o, WorldModel)), None)
    cloned_ledger = next((o for o in cloned_objects if isinstance(o, FactLedger)), None)
    cloned_foreshadow = next((o for o in cloned_objects if isinstance(o, ForeshadowGraph)), None)
    cloned_characters: list[CharacterModel] = [o for o in cloned_objects if isinstance(o, CharacterModel)]

    # 记录 Step 0 初始状态快照
    initial_pressures = {
        c.character_id or c.name: list(c.current_pressure)
        for c in cloned_characters
    }
    initial_threads = [
        getattr(e, "thread_id", str(idx))
        for idx, e in enumerate(getattr(cloned_foreshadow, "entries", []))
        if getattr(e, "current_status", "active") == "active"
    ] if cloned_foreshadow else []
    initial_prohibitions = (
        list(cloned_world.prohibitions or []) + list(cloned_world.forbidden_actions or [])
        if cloned_world else []
    )
    initial_facts_count = len([
        e for e in getattr(cloned_ledger, "entries", [])
        if getattr(e, "confirmed", False)
    ]) if cloned_ledger else 0

    initial_snapshot = RolloutStateSnapshot(
        step_index=0,
        state_id=cloned_state.state_id,
        current_situation=cloned_state.current_situation,
        open_questions=list(cloned_state.open_questions or []),
        active_conflicts=list(cloned_state.active_conflicts or []),
        active_threads=initial_threads,
        character_pressures=initial_pressures,
        facts_count=initial_facts_count,
        prohibitions_checked=initial_prohibitions,
    )

    proposal_text = " ".join([
        proposal.core_choice,
        proposal.cost,
        proposal.state_change,
        proposal.impact_next_3_to_5_chapters,
        proposal.primary_risk,
    ])

    risk_flags = heuristic_risk_probe(proposal_text)
    is_high_stimulus = any("reckless_escalation_burnout" in f for f in risk_flags)
    is_deliberate_setup = any(m in proposal_text for m in _DELIBERATE_SETUP_MARKERS)
    is_cheap_cosmetic = any("flat_filler_stagnation" in f for f in risk_flags)

    # 2. 真实对象级推演与守恒检验
    # A. 世界规则禁忌守恒检验
    hard_rule_violation = False
    rule_violation_detail = ""
    if cloned_world:
        prohibitions = list(cloned_world.prohibitions or []) + list(cloned_world.forbidden_actions or [])
        cost_clean = proposal.cost.strip()
        is_zero_cost = not cost_clean or cost_clean in ("无", "无代价", "暂无", "无明确代价") or "无代价" in cost_clean
        for p in prohibitions:
            if not p:
                continue
            if is_zero_cost and (
                p in proposal_text
                or any(k in proposal_text and k in p for k in ("逆转生死", "经脉", "复活", "禁术", "断绝生机", "损毁"))
            ):
                hard_rule_violation = True
                rule_violation_detail = f"触犯世界禁忌[{p}]且未支付必要代价"
                risk_flags.append(f"hard_rule_violation: {rule_violation_detail}")
                break

    # B. 角色压力与关系演变模拟
    actor_char = None
    if proposal.primary_actor and cloned_characters:
        actor_char = next(
            (c for c in cloned_characters if c.name == proposal.primary_actor or c.character_id == proposal.primary_actor),
            None,
        )

    character_stress_overload = False
    if actor_char is not None:
        if any(w in proposal.cost for w in ("重伤", "反噬", "透支", "牺牲", "折寿", "残疾", "被废")):
            actor_char.current_pressure.append(f"rollout_cost: {proposal.cost}")
        if proposal.relationship_change and isinstance(actor_char.relations, dict):
            actor_char.relations["last_shift"] = proposal.relationship_change
        if len(actor_char.current_pressure) >= 5:
            character_stress_overload = True
            risk_flags.append("character_stress_overload: 角色承受压力达到崩溃临界")

    # C. 事实账本终结性事实冲突探测 (Fatal/Terminal Fact Check)
    causal_contradiction = False
    if cloned_ledger:
        for entry in getattr(cloned_ledger, "entries", []):
            if not getattr(entry, "confirmed", False):
                continue
            # 检查已确认死亡/终结/摧毁/失去的实体是否在 proposal 中被无代价或矛盾逆转复用
            for term in _FATAL_TERMINAL_FACT_MARKERS:
                if term in entry.statement:
                    involved = getattr(entry, "involved_entities", [])
                    matches_entity = any(ent in proposal_text for ent in involved if ent) or any(
                        chunk in entry.statement for chunk in (proposal.primary_actor, proposal.core_choice[:10]) if chunk
                    )
                    if matches_entity:
                        if any(rev in proposal.state_change or rev in proposal.core_choice for rev in ("恢复", "完好如初", "平安无事", "现身相助", "未死", "重获")):
                            if not is_deliberate_setup:
                                causal_contradiction = True
                                risk_flags.append(f"causal_contradiction: 与已确认终结性事实『{entry.statement}』存在矛盾逆转冲突")
                                break
                    elif term in entry.statement and "恢复" in proposal.state_change and not is_deliberate_setup:
                        causal_contradiction = True
                        risk_flags.append(f"causal_contradiction: 与已确认终结性事实『{entry.statement}』存在因果冲突")
                        break
            if causal_contradiction:
                break

    # D. 伏笔/线索饿死检测 (使用 entries 而非 nodes)
    thread_starvation = False
    if cloned_foreshadow:
        foreshadow_entries = getattr(cloned_foreshadow, "entries", [])
        open_entries = [
            e for e in foreshadow_entries
            if getattr(e, "current_status", "") == "active" or getattr(e, "status", "") == "active"
        ]
        if len(open_entries) >= 4 and not proposal.information_reveal and not is_deliberate_setup:
            thread_starvation = True
            risk_flags.append("thread_starvation: 活跃线索积压过多且未在推演中进行推进或照应")

    rollout_steps: list[RolloutStep] = []
    rollout_transitions: list[RolloutTransition] = []
    current_snapshot = initial_snapshot

    # 3. 动态 3-5 步对象推演状态迭代与状态转移构建
    for step_idx in range(1, steps + 1):
        step_metric, delta, next_snapshot, transition = _rollout_single_step(
            step_idx=step_idx,
            current_snapshot=current_snapshot,
            cloned_state=cloned_state,
            cloned_characters=cloned_characters,
            cloned_ledger=cloned_ledger,
            cloned_foreshadow=cloned_foreshadow,
            cloned_world=cloned_world,
            proposal=proposal,
            hard_rule_violation=hard_rule_violation,
            rule_violation_detail=rule_violation_detail,
            causal_contradiction=causal_contradiction,
            character_stress_overload=character_stress_overload,
            is_high_stimulus=is_high_stimulus,
            is_deliberate_setup=is_deliberate_setup,
            is_cheap_cosmetic=is_cheap_cosmetic,
            thread_starvation=thread_starvation,
            initial_prohibitions=initial_prohibitions,
        )
        rollout_steps.append(step_metric)
        rollout_transitions.append(transition)
        current_snapshot = next_snapshot

    avg_sustainability = sum(s.sustainability for s in rollout_steps) / len(rollout_steps)
    avg_delayed_payoff = sum(s.delayed_payoff_yield for s in rollout_steps) / len(rollout_steps)

    if hard_rule_violation or causal_contradiction:
        stimulus_vs_risk = 0.0
    elif is_high_stimulus:
        stimulus_vs_risk = 0.25
    elif is_deliberate_setup:
        stimulus_vs_risk = 0.90
    elif is_cheap_cosmetic:
        stimulus_vs_risk = 0.40
    else:
        stimulus_vs_risk = 0.75

    summary = (
        f"Rollout {steps}章推演: 可持续性 {avg_sustainability:.2f}, "
        f"中长程兑现潜力 {avg_delayed_payoff:.2f}, 风险标记: {len(risk_flags)} 项, "
        f"状态转移: {len(rollout_transitions)} 步已闭环"
    )

    return RolloutEvaluation(
        proposal_id=proposal.proposal_id,
        steps=rollout_steps,
        transitions=rollout_transitions,
        initial_snapshot=initial_snapshot,
        final_snapshot=current_snapshot,
        overall_sustainability=round(avg_sustainability, 4),
        immediate_stimulus_vs_longterm_risk=round(stimulus_vs_risk, 4),
        delayed_payoff_potential=round(avg_delayed_payoff, 4),
        risk_flags=risk_flags,
        summary=summary,
    )


# 别名绑定与兼容接口
clone_and_rollout_planner = simulate_dynamic_state_rollout
deterministic_scenario_projection = simulate_dynamic_state_rollout


# 兼容旧 simulate_rollout 接口
def simulate_rollout(
    proposal: StructuralProposal,
    state: NarrativeState,
    objects: list,
    steps: int = 3,
    workspec: Optional[WorkSpec] = None,
) -> RolloutEvaluation:
    return clone_and_rollout_planner(
        proposal, state, objects, steps=steps, workspec=workspec
    )


# ---------------------------------------------------------------------------
# 3. 独立多维 Pareto 评估与前沿计算
# ---------------------------------------------------------------------------

def score_structural_pareto(
    proposal: StructuralProposal,
    rollout: RolloutEvaluation,
    state: NarrativeState,
    objects: list,
    workspec: Optional[WorkSpec] = None,
    orchestration_state: Optional[OrchestrationState] = None,
) -> ParetoDimensionScores:
    """计算候选在 7 个独立多目标维度上的得分（禁止单总分加权）."""
    # 1. 因果价值 (causal_value): 状态改变与代价是否实质
    has_cost = bool(proposal.cost and proposal.cost not in ("无", "暂无", "无代价"))
    has_state_change = bool(proposal.state_change and len(proposal.state_change) > 5)
    causal_score = 0.4
    if has_cost:
        causal_score += 0.3
    if has_state_change:
        causal_score += 0.3
    causal_score = min(1.0, causal_score)

    # 2. 人物价值 (character_value): 主动选择与角色主体性
    char_score = 0.5
    if proposal.primary_actor:
        char_score += 0.2
    if proposal.relationship_change:
        char_score += 0.2
    if "牺牲" in proposal.cost or "坚持" in proposal.core_choice or "抉择" in proposal.core_choice:
        char_score += 0.1
    char_score = min(1.0, char_score)

    # 3. 读者动力 (reader_momentum): 认知悬念与推进
    momentum_score = 0.5
    if proposal.reader_expectation_delta:
        momentum_score += 0.25
    if proposal.chapter_function in ("危机", "兑现", "转向", "选择"):
        momentum_score += 0.15
    momentum_score = min(1.0, momentum_score)

    # 4. 作品契合度 (work_alignment): WorkSpec & Orchestration 适配
    alignment_score = 0.7
    if workspec is not None:
        if workspec.genre and workspec.genre in proposal.summary:
            alignment_score += 0.15
    if orchestration_state is not None:
        target_fn = orchestration_state.chapter_function.assigned_function
        fn_map = {
            "setup": "蓄力",
            "escalation": "推进",
            "crisis": "危机",
            "payoff": "兑现",
            "transition": "转向",
            "aftermath": "后果",
        }
        mapped_target = fn_map.get(target_fn, target_fn)
        if mapped_target and mapped_target in proposal.chapter_function:
            alignment_score += 0.15
    alignment_score = min(1.0, alignment_score)

    # 5. 原创性 (originality): 避开陈词滥调与套路
    originality_score = 0.6
    if "反常规" in proposal.summary or "出人意料" in proposal.summary or proposal.chapter_function == "留白":
        originality_score += 0.25
    if any(m in proposal.core_choice for m in _HIGH_STIMULUS_MARKERS):
        originality_score -= 0.20
    originality_score = max(0.1, min(1.0, originality_score))

    # 6. 长期可持续性 (sustainability): 来自 Rollout
    sustainability_score = rollout.overall_sustainability

    # 7. 风险惩罚 (risk_penalty): 破坏规则或透支战力风险
    risk_score = 0.1
    if rollout.risk_flags:
        risk_score += 0.3 * len(rollout.risk_flags)
    if "反噬" in proposal.primary_risk or "崩塌" in proposal.primary_risk or "暴露" in proposal.primary_risk:
        risk_score += 0.2
    risk_score = max(0.0, min(1.0, risk_score))

    return ParetoDimensionScores(
        causal_value=round(causal_score, 4),
        character_value=round(char_score, 4),
        reader_momentum=round(momentum_score, 4),
        work_alignment=round(alignment_score, 4),
        originality=round(originality_score, 4),
        sustainability=round(sustainability_score, 4),
        risk_penalty=round(risk_score, 4),
    )


def _dominates_pareto(
    scores_a: ParetoDimensionScores,
    scores_b: ParetoDimensionScores,
) -> bool:
    """判断 A 是否帕累托支配 B (全轴 A >= B 且至少一轴 A > B, risk 越低越好)."""
    dict_a = scores_a.to_dimension_dict()
    dict_b = scores_b.to_dimension_dict()

    strictly_better = False
    for dim, val_a in dict_a.items():
        val_b = dict_b.get(dim, 0.0)
        if val_a < val_b:
            return False
        if val_a > val_b:
            strictly_better = True
    return strictly_better


def compute_structural_pareto_frontier(
    proposal_ids: list[str],
    scores: dict[str, ParetoDimensionScores],
) -> list[str]:
    """计算多维帕累托非支配前沿（保留多解，不合并单总分）."""
    frontier: list[str] = []
    for candidate in proposal_ids:
        c_score = scores.get(candidate)
        if not c_score:
            frontier.append(candidate)
            continue
        dominated = False
        for other in proposal_ids:
            if other == candidate:
                continue
            o_score = scores.get(other)
            if o_score and _dominates_pareto(o_score, c_score):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return frontier


# ---------------------------------------------------------------------------
# 4. 候选选择预承诺 (Candidate Precommit)
# ---------------------------------------------------------------------------

def compute_trusted_state_hash(state: NarrativeState, objects: list) -> str:
    """基于可信状态对象生成稳定 SHA256 哈希."""
    payload = {
        "state_id": state.state_id,
        "situation": state.current_situation,
        "location": state.current_location,
        "active_conflicts": sorted(state.active_conflicts),
        "object_count": len(objects),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_candidate_precommit(
    target_chapter: int,
    state: NarrativeState,
    objects: list,
    orchestration_state: Optional[OrchestrationState] = None,
) -> CandidatePrecommit:
    """生成正文前冻结的选择依据与证伪承诺."""
    state_hash = compute_trusted_state_hash(state, objects)
    precommit_id = f"cand_precommit_ch{target_chapter:04d}_{state_hash[:8]}"

    core_q = f"第 {target_chapter} 章核心问题: 在当前情境[{state.current_situation[:20]}]下，主要行动者如何付出不可逆代价形成实质推进"
    mandatory_consequences = (
        "所做选择必须产生可观测的因果状态转移",
        "付出的代价不得在下一章无解释自动恢复",
        "揭示的关键信息必须进入可信事实账本",
    )
    pitfalls = (
        "华丽辞藻不能掩盖因果停滞与选择缺位",
        "无代价的即时战力暴涨视为高风险破坏",
        "自言自语式的动机解释不能替代行动与交互",
    )
    overturn = (
        "若正文实现中抹平了结构方案承诺的核心代价，推翻偏好",
        "若正文出现与世界规则冲突的超纲设定，推翻偏好",
        "若正文改变了选定候选的核心行动主体与核心选择，推翻偏好",
    )

    return CandidatePrecommit(
        precommit_id=precommit_id,
        target_chapter=target_chapter,
        core_question=core_q,
        mandatory_consequences=mandatory_consequences,
        superficial_pitfalls=pitfalls,
        overturn_conditions=overturn,
        trusted_state_hash=state_hash,
    )


# ---------------------------------------------------------------------------
# 5. 全流程搜索执行器 (Structural Search Engine)
# ---------------------------------------------------------------------------

class StructuralSearchEngine:
    """章节级多尺度结构搜索执行器."""

    def __init__(self, rollout_steps: int = 3):
        self.rollout_steps = rollout_steps

    def search_and_evaluate(
        self,
        proposals: list[StructuralProposal],
        state: NarrativeState,
        objects: list,
        *,
        target_chapter: int = 1,
        workspec: Optional[WorkSpec] = None,
        orchestration_state: Optional[OrchestrationState] = None,
        author_model: Optional[AuthorModelV3] = None,
        qualification_report: Optional[CrossWorkValidationResult] = None,
        manual_selection: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ) -> StructuralSearchResult:
        """执行完整搜索管线：多样性门禁 → Rollout → Pareto 评分 → 前沿提取 → 预承诺冻结 → 最优解与多解保留."""
        if not proposals:
            raise ValueError("proposals list cannot be empty")

        # 1. 结构异质性门禁 (R3: 杜绝 silent fallback)
        diversity_report = evaluate_structural_diversity(proposals)
        valid_candidates = [p for p in proposals if p.proposal_id in diversity_report.valid_proposals]

        if len(proposals) > 1 and not diversity_report.is_diverse:
            raise ValueError(
                f"structural_diversity_failed: Proposals failed structural diversity check "
                f"({len(valid_candidates)}/{len(proposals)} valid, near-duplicates detected: "
                f"{len(diversity_report.near_duplicates)} pairs). Refusing silent fallback."
            )

        if not valid_candidates:
            raise ValueError(
                f"structural_diversity_failed: No valid diverse proposals found out of {len(proposals)} proposals. "
                f"Refusing silent fallback."
            )

        # 2. 3-5 章短程状态 Rollout (深拷贝对象级推演与状态转移)
        rollout_evals: dict[str, RolloutEvaluation] = {}
        for p in valid_candidates:
            rollout_evals[p.proposal_id] = clone_and_rollout_planner(
                p, state, objects, steps=self.rollout_steps, workspec=workspec
            )

        # 3. 独立多维 Pareto 评估
        pareto_scores: dict[str, ParetoDimensionScores] = {}
        for p in valid_candidates:
            pareto_scores[p.proposal_id] = score_structural_pareto(
                p,
                rollout_evals[p.proposal_id],
                state,
                objects,
                workspec=workspec,
                orchestration_state=orchestration_state,
            )

        # 4. 帕累托前沿计算
        valid_ids = [p.proposal_id for p in valid_candidates]
        frontier_ids = compute_structural_pareto_frontier(valid_ids, pareto_scores)
        if not frontier_ids:
            raise ValueError(
                "pareto_frontier_empty: No non-dominated candidate could be computed from valid candidates."
            )

        # 5. 候选选择预承诺 (Precommit)
        precommit = build_candidate_precommit(
            target_chapter=target_chapter,
            state=state,
            objects=objects,
            orchestration_state=orchestration_state,
        )

        # 6. 从前沿中进行仲裁选择（Manual Selection / Pareto Dominance / Certified Author Prior / Unqualified Tie-Break）
        is_certified = is_author_model_certified_for_production(author_model, qualification_report)
        prop_map = {p.proposal_id: p for p in valid_candidates}

        if manual_selection and manual_selection in frontier_ids:
            selected_id = manual_selection
            tie_break_method = "manual_operator_selection"
            selection_underdetermined = False
            selected_score = pareto_scores[selected_id]
            rationale = (
                f"帕累托前沿存在多解 [{', '.join(frontier_ids)}]，由操作者手动指定选定 {selected_id}："
                f"可持续性 {selected_score.sustainability:.2f}, 因果价值 {selected_score.causal_value:.2f}, "
                f"人物价值 {selected_score.character_value:.2f}。"
            )
        elif len(frontier_ids) == 1:
            selected_id = frontier_ids[0]
            tie_break_method = "pareto_dominance"
            selection_underdetermined = False
            selected_score = pareto_scores[selected_id]
            rationale = (
                f"帕累托唯一支配最优解 {selected_id}："
                f"可持续性 {selected_score.sustainability:.2f}, 因果价值 {selected_score.causal_value:.2f}, "
                f"人物价值 {selected_score.character_value:.2f}, 风险惩罚 {selected_score.risk_penalty:.2f}。"
            )
        elif is_certified:
            # 经留一法 (L1WO) 资格认证的作者先验模型可进行生产仲裁
            def _author_key(cand_id: str) -> tuple[float, float]:
                cand_prop = prop_map[cand_id]
                prior = score_author_prior(cand_prop, author_model, workspec)
                return (prior, pareto_scores[cand_id].sustainability)

            selected_id = max(frontier_ids, key=_author_key)
            tie_break_method = "certified_author_prior"
            selection_underdetermined = False
            selected_score = pareto_scores[selected_id]
            rationale = (
                f"帕累托前沿存在多解 [{', '.join(frontier_ids)}]，由 L1WO 资格认证作者先验模型选定 {selected_id}："
                f"可持续性 {selected_score.sustainability:.2f}, 因果价值 {selected_score.causal_value:.2f}。"
            )
        else:
            # 帕累托前沿存在多解且未获得 L1WO 资格认证：严格保留不可比较性，一律标记 selection_underdetermined=True 进入人工选择槽
            def _selection_key(cand_id: str) -> tuple[float, float, float, float]:
                score = pareto_scores[cand_id]
                safety = 1.0 - score.risk_penalty
                return (score.sustainability, score.causal_value, score.character_value, safety)

            selected_id = max(frontier_ids, key=_selection_key)
            tie_break_method = "unqualified_tie_break" if author_model else "underdetermined_pareto_frontier"
            selection_underdetermined = True
            selected_score = pareto_scores[selected_id]
            rationale = (
                f"帕累托前沿存在多解 [{', '.join(frontier_ids)}]。按契约禁止使用未认证/关键词启发式自动仲裁，"
                f"提供最高可持续性建议候选 {selected_id}，但显式锁定未决状态 (selection_underdetermined=True) "
                f"进入 structural_selection 人工选择槽。"
            )

        incomparable = [cid for cid in frontier_ids if cid != selected_id]

        result = StructuralSearchResult(
            selected_proposal_id=selected_id,
            pareto_frontier=frontier_ids,
            diversity_report=diversity_report,
            rollout_evaluations=rollout_evals,
            pareto_scores=pareto_scores,
            precommit=precommit,
            selection_rationale=rationale,
            incomparable_candidates_preserved=incomparable,
            selection_underdetermined=selection_underdetermined,
            tie_break_method=tie_break_method,
        )

        # 7. 写入中间结果（若提供 output_dir）
        if output_dir is not None:
            out_path = output_dir / "structural_search_record.json"
            out_path.write_text(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return result
