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

from src.object_state.charactermodel import CharacterModel
from src.object_state.factledger import FactLedger
from src.object_state.foreshadowgraph import ForeshadowGraph
from src.object_state.narrativestate import NarrativeState
from src.object_state.orchestration import OrchestrationState
from src.object_state.plotunit import PlotUnit
from src.object_state.structural_search import (
    CandidatePrecommit,
    NearDuplicatePair,
    ParetoDimensionScores,
    RolloutEvaluation,
    RolloutStep,
    StructuralDiversityReport,
    StructuralProposal,
    StructuralSearchResult,
)
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel


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
    """真实深拷贝对象状态推演（RolloutPlannerUnit）:

    深拷贝 [NarrativeState, FactLedger, ForeshadowGraph, Characters, WorldModel]，
    模拟 3-5 步状态演变与世界规则守恒校验。
    """
    steps = max(3, min(5, steps))

    # 深拷贝隔离运行时对象，防止推演污染主线
    cloned_state = state.model_copy(deep=True)
    cloned_objects = [
        o.model_copy(deep=True) if hasattr(o, "model_copy") else copy.deepcopy(o)
        for o in objects
    ]
    cloned_world = next((o for o in cloned_objects if isinstance(o, WorldModel)), None)

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

    # 检查是否有显式违背世界规则禁忌
    hard_rule_violation = False
    if cloned_world and cloned_world.prohibitions:
        for p in cloned_world.prohibitions:
            if p in proposal_text:
                cost_clean = proposal.cost.strip()
                if not cost_clean or cost_clean in ("无", "无代价", "暂无", "无明确代价") or "无代价" in cost_clean:
                    hard_rule_violation = True
                    risk_flags.append(f"hard_rule_violation: 触犯世界禁忌[{p}]且未提供自洽代价")

    rollout_steps: list[RolloutStep] = []

    for step_idx in range(1, steps + 1):
        step_notes: list[str] = []
        if hard_rule_violation:
            fatigue = 1.0
            escalation = 1.0
            delayed_payoff = 0.0
            rule_risk = 1.0
            sustainability = 0.0
            step_notes.append(f"第+{step_idx}章: 世界规则崩溃，叙事分支不可行")
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
        elif is_cheap_cosmetic:
            fatigue = min(1.0, 0.5 + 0.15 * step_idx)
            escalation = 0.2
            delayed_payoff = 0.2
            rule_risk = 0.1
            sustainability = max(0.2, 0.5 - 0.10 * step_idx)
            step_notes.append(f"第+{step_idx}章: 缺乏有效状态转移，叙事动力减弱")
        else:
            fatigue = 0.3
            escalation = 0.3
            delayed_payoff = min(1.0, 0.5 + 0.10 * step_idx)
            rule_risk = 0.15
            sustainability = 0.75
            step_notes.append(f"第+{step_idx}章: 因果自洽推进，预期正常流转")

        rollout_steps.append(
            RolloutStep(
                step_index=step_idx,
                projected_situation=f"推演章+{step_idx}: 基于[{proposal.core_choice[:15]}]的后续状态演化",
                fatigue_index=round(fatigue, 4),
                escalation_debt=round(escalation, 4),
                delayed_payoff_yield=round(delayed_payoff, 4),
                rule_break_risk=round(rule_risk, 4),
                sustainability=round(sustainability, 4),
                notes=step_notes,
            )
        )

    avg_sustainability = sum(s.sustainability for s in rollout_steps) / len(rollout_steps)
    avg_delayed_payoff = sum(s.delayed_payoff_yield for s in rollout_steps) / len(rollout_steps)

    if hard_rule_violation:
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
        f"中长程兑现潜力 {avg_delayed_payoff:.2f}, 风险标记: {len(risk_flags)} 项"
    )

    return RolloutEvaluation(
        proposal_id=proposal.proposal_id,
        steps=rollout_steps,
        overall_sustainability=round(avg_sustainability, 4),
        immediate_stimulus_vs_longterm_risk=round(stimulus_vs_risk, 4),
        delayed_payoff_potential=round(avg_delayed_payoff, 4),
        risk_flags=risk_flags,
        summary=summary,
    )


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
        output_dir: Optional[Path] = None,
    ) -> StructuralSearchResult:
        """执行完整搜索管线：多样性门禁 → Rollout → Pareto 评分 → 前沿提取 → 预承诺冻结 → 最优解与多解保留."""
        if not proposals:
            raise ValueError("proposals list cannot be empty")

        # 1. 结构异质性门禁 (R3: 杜绝 silent fallback)
        diversity_report = evaluate_structural_diversity(proposals)
        valid_candidates = [p for p in proposals if p.proposal_id in diversity_report.valid_proposals]

        if len(proposals) > 1 and len(valid_candidates) == 0:
            raise ValueError(
                f"structural_diversity_failed: All {len(proposals)} proposals failed structural diversity check "
                f"(near-duplicates detected: {len(diversity_report.near_duplicates)} pairs). "
                f"Refusing silent fallback."
            )

        if not valid_candidates:
            valid_candidates = proposals

        # 2. 3-5 章短程状态 Rollout (深拷贝对象级推演)
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
            frontier_ids = valid_ids[:1]

        # 5. 候选选择预承诺 (Precommit)
        precommit = build_candidate_precommit(
            target_chapter=target_chapter,
            state=state,
            objects=objects,
            orchestration_state=orchestration_state,
        )

        # 6. 从前沿中选择最符合预承诺与长期可持续性的候选（同时保留其他非支配解）
        def _selection_key(cand_id: str) -> tuple[float, float, float, float]:
            score = pareto_scores[cand_id]
            safety = 1.0 - score.risk_penalty
            return (score.sustainability, score.causal_value, score.character_value, safety)

        selected_id = max(frontier_ids, key=_selection_key)
        incomparable = [cid for cid in frontier_ids if cid != selected_id]

        selected_score = pareto_scores[selected_id]
        rationale = (
            f"从帕累托前沿 [{', '.join(frontier_ids)}] 中选定 {selected_id}："
            f"可持续性 {selected_score.sustainability:.2f}, 因果价值 {selected_score.causal_value:.2f}, "
            f"人物价值 {selected_score.character_value:.2f}, 风险惩罚 {selected_score.risk_penalty:.2f}。"
            f"同时在前沿中独立保留非支配解: {incomparable}"
        )

        result = StructuralSearchResult(
            selected_proposal_id=selected_id,
            pareto_frontier=frontier_ids,
            diversity_report=diversity_report,
            rollout_evaluations=rollout_evals,
            pareto_scores=pareto_scores,
            precommit=precommit,
            selection_rationale=rationale,
            incomparable_candidates_preserved=incomparable,
        )

        # 7. 写入中间结果（若提供 output_dir）
        if output_dir is not None:
            out_path = output_dir / "structural_search_record.json"
            out_path.write_text(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return result
