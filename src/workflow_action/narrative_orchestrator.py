"""NarrativeOrchestrator — 长程叙事编排决策引擎与跨章持久闭环 (P2 核心单元 & R2 整改).

分离读取、派生、提交三大阶段：
1. load_committed_orchestration_state: 从工作区读取上一个已提交章节的编排状态，校验 schema，损坏显式报错。
2. derive_orchestration_plan: 纯函数推导本章编排计划（priority, suppress, silence, payoff targets, fatigue），无证据为 neutral。
3. commit_orchestration_transition: 仅在章节事务真正提交成功后原子落盘，推进 expectation_started_at, promise_payoff_history, thread_last_seen 等。

接入真实选择链：Candidate Pool -> Narrative Selector -> Chapter Packet。
零成本契约：未开启编排或无有效导向时返回空串，不增加任何多余 prompt 字节。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Optional

from src.object_state.charactermodel import CharacterModel
from src.object_state.factledger import FactLedger
from src.object_state.foreshadowgraph import ForeshadowGraph
from src.object_state.narrativestate import NarrativeState
from src.object_state.orchestration import (
    ChapterFunctionAllocation,
    CommittedOrchestrationHistoryEntry,
    CommittedOrchestrationState,
    EmotionalPacing,
    InformationDensityBudget,
    OrchestrationPlan,
    OrchestrationState,
    PromisePayoffDebt,
    ReaderExpectationHorizon,
    RelationalTrajectory,
    ThreadRotation,
)
from src.object_state.plotunit import PlotUnit
from src.object_state.readerexpectation import derive_reader_expectations
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel


# 情绪张力分类标记词
_HIGH_TENSION_EMOTIONS = {
    "激昂", "压抑", "紧迫", "危机", "高潮", "紧张", "愤怒",
    "绝望", "惊骇", "杀机", "战意", "肃杀",
}
_LOW_TENSION_EMOTIONS = {
    "平稳", "轻松", "舒缓", "日常", "沉淀", "释然",
    "温和", "安宁", "休整", "复盘",
}

_CALM_REFLECTION_MARKERS = (
    "商议", "休整", "思考", "复盘", "调息", "缓和", "商讨",
    "沉思", "对坐", "探讨", "筹谋", "推敲", "暂歇", "清点",
)
_EXTREME_ACTION_MARKERS = (
    "血战", "狂暴", "生死关头", "连续轰击", "厮杀", "搏命",
    "爆裂", "死决", "拼死", "轰鸣不绝",
)


# =============================================================================
# 阶段 1: 读取已提交状态 (Load)
# =============================================================================

def load_committed_orchestration_state(
    output_dir: Optional[Path],
) -> CommittedOrchestrationState:
    """从工作区读取最后已提交章节的编排状态.

    若文件不存在，返回初始空白 CommittedOrchestrationState。
    若文件存在但损坏或格式非法，显式抛出 ValueError（禁止静默 swallow）。
    """
    if output_dir is None:
        return CommittedOrchestrationState()

    state_path = output_dir / "committed_orchestration_state.json"
    if not state_path.exists():
        # 兼容查找 orchestration_history.json
        hist_path = output_dir / "orchestration_history.json"
        if not hist_path.exists():
            return CommittedOrchestrationState()
        try:
            raw_hist = hist_path.read_text(encoding="utf-8")
            hist_data = json.loads(raw_hist)
            if isinstance(hist_data, list):
                entries = [CommittedOrchestrationHistoryEntry.model_validate(e) for e in hist_data]
                last_ch = entries[-1].chapter if entries else 0
                return CommittedOrchestrationState(
                    last_committed_chapter=last_ch,
                    history_entries=entries,
                )
        except Exception as exc:
            raise ValueError(f"Corrupted orchestration history in {hist_path}: {exc}") from exc

    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return CommittedOrchestrationState.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Corrupted committed orchestration state in {state_path}: {exc}") from exc


# =============================================================================
# 阶段 2: 纯函数派生本章计划 (Derive)
# =============================================================================

def derive_orchestration_plan(
    committed_state: CommittedOrchestrationState,
    objects: list,
    *,
    chapter_number: int = 1,
    frame_context: Optional[dict] = None,
    structure_template: Optional[str] = None,
) -> OrchestrationPlan:
    """纯函数：依据已提交历史与当前世界事实推导本章编排计划（无任何磁盘写入副作用）."""
    orchestrator = NarrativeOrchestrator()
    history_dicts = [e.model_dump() for e in committed_state.history_entries]
    full_state = orchestrator.derive_orchestration_state(
        objects,
        history=history_dicts,
        chapter_number=chapter_number,
        frame_context=frame_context,
        structure_template=structure_template,
    )

    priority_tasks: list[str] = []
    suppressed_tasks: list[str] = []
    silence_items: list[str] = []
    payoff_targets: list[str] = []
    notes: list[str] = []

    # 1. 疲劳风险控制
    fatigue_risk = full_state.emotional_pacing.fatigue_risk
    if fatigue_risk:
        priority_tasks.append("安排缓冲复盘或情感交互，防止连续高压审美疲劳")
        suppressed_tasks.append("暂缓极高压冲突激化与连续大招对轰")

    # 2. 承诺债务推进
    if full_state.promise_debt.urgent_thread_ids:
        urgent_str = "、".join(full_state.promise_debt.urgent_thread_ids[:2])
        priority_tasks.append(f"重点推进或兑现滞留伏笔承诺 [{urgent_str}]")
        payoff_targets.extend(full_state.promise_debt.urgent_thread_ids[:2])

    if full_state.promise_debt.debt_level == "critical":
        suppressed_tasks.append("承诺债务过高，禁止新开无前置铺垫的大型主线支线")

    # 3. 支线防饿死
    if full_state.thread_rotation.starved_threads:
        starved_str = "、".join(full_state.thread_rotation.starved_threads[:2])
        priority_tasks.append(f"照应沉寂支线 [{starved_str}]")

    # 4. 读者预期张力
    if full_state.expectation_horizon.cognitive_tension == "critical":
        if full_state.expectation_horizon.stalled_questions:
            silence_q = full_state.expectation_horizon.stalled_questions[0]
            priority_tasks.append(f"回应关键悬念问题: {silence_q}")

    assigned_fn = full_state.chapter_function.assigned_function
    density = full_state.density_budget.reveal_budget

    return OrchestrationPlan(
        chapter_number=chapter_number,
        assigned_function=assigned_fn,
        priority_tasks=priority_tasks,
        suppressed_tasks=suppressed_tasks,
        silence_items=silence_items,
        payoff_targets=payoff_targets,
        fatigue_risk=fatigue_risk,
        density_directive=density,
        notes=notes,
    )


# =============================================================================
# 阶段 3: 事务提交后原子落盘 (Commit)
# =============================================================================

def commit_orchestration_transition(
    output_dir: Path,
    plan: OrchestrationPlan,
    plotunit: Optional[PlotUnit] = None,
    *,
    chapter_number: int,
    run_id: str,
    emotional_shift: str = "normal",
    threads_advanced: Optional[list[str]] = None,
    payoff_promises: Optional[list[str]] = None,
    relational_shifts: Optional[list[str]] = None,
) -> CommittedOrchestrationState:
    """仅在章节提交事务成功后执行：原子更新已提交编排状态并落盘."""
    current_state = load_committed_orchestration_state(output_dir)

    # 提取本章实际发生的推进
    advanced = list(threads_advanced or [])
    payoffs = list(payoff_promises or [])
    relations = list(relational_shifts or [])
    emotion = emotional_shift

    if plotunit is not None:
        if not emotion or emotion == "normal":
            emotion = getattr(plotunit, "emotional_shift", "") or "normal"
        if not payoffs:
            payoffs = getattr(plotunit, "released_information", []) or []
        if not advanced:
            advanced = getattr(plotunit, "participants", []) or []

    entry = CommittedOrchestrationHistoryEntry(
        chapter=chapter_number,
        function=plan.assigned_function,
        emotion=emotion,
        advanced_threads=advanced,
        payoff_promises=payoffs,
        relational_shifts=relations,
    )

    new_history = list(current_state.history_entries)
    # 若存在同章节记录则替换，否则追加
    new_history = [e for e in new_history if e.chapter != chapter_number]
    new_history.append(entry)
    new_history.sort(key=lambda x: x.chapter)

    # 更新索引字典
    thread_seen = dict(current_state.thread_last_seen)
    thread_adv = dict(current_state.thread_last_advanced)
    exp_started = dict(current_state.expectation_started_at)
    exp_adv = dict(current_state.expectation_last_advanced_at)

    for t in advanced:
        thread_seen[t] = chapter_number
        thread_adv[t] = chapter_number

    recent_funcs = [e.function for e in new_history[-10:]]
    recent_emotions = [e.emotion for e in new_history[-10:]]

    updated_state = CommittedOrchestrationState(
        last_committed_chapter=chapter_number,
        last_run_id=run_id,
        history_entries=new_history,
        thread_last_seen=thread_seen,
        thread_last_advanced=thread_adv,
        expectation_started_at=exp_started,
        expectation_last_advanced_at=exp_adv,
        recent_chapter_functions=recent_funcs,
        recent_emotional_patterns=recent_emotions,
    )

    # 原子写入 committed_orchestration_state.json
    output_dir.mkdir(parents=True, exist_ok=True)
    target_file = output_dir / "committed_orchestration_state.json"
    history_file = output_dir / "orchestration_history.json"

    data_bytes = json.dumps(
        updated_state.model_dump(), ensure_ascii=False, indent=2
    ).encode("utf-8")

    hist_bytes = json.dumps(
        [e.model_dump() for e in new_history], ensure_ascii=False, indent=2
    ).encode("utf-8")

    # 写临时文件后 rename 实现原子落盘
    tmp_fd, tmp_path = tempfile.mkstemp(dir=output_dir, prefix="orch_state_", suffix=".tmp")
    with os.fdopen(tmp_fd, "wb") as f:
        f.write(data_bytes)
    os.replace(tmp_path, target_file)

    tmp_hfd, tmp_hpath = tempfile.mkstemp(dir=output_dir, prefix="orch_hist_", suffix=".tmp")
    with os.fdopen(tmp_hfd, "wb") as f:
        f.write(hist_bytes)
    os.replace(tmp_hpath, history_file)

    return updated_state


# =============================================================================
# 核心编排推导引擎类
# =============================================================================

class NarrativeOrchestrator:
    """长程叙事编排决策引擎."""

    def derive_orchestration_state(
        self,
        objects: list,
        *,
        history: Optional[list[dict]] = None,
        chapter_number: int = 1,
        frame_context: Optional[dict] = None,
        structure_template: Optional[str] = None,
    ) -> OrchestrationState:
        """从当前对象状态与历史记录推导全量 7 维编排状态."""
        state = next((o for o in objects if isinstance(o, NarrativeState)), None)
        facts = next((o for o in objects if isinstance(o, FactLedger)), None)
        foreshadows = next((o for o in objects if isinstance(o, ForeshadowGraph)), None)
        characters = [o for o in objects if isinstance(o, CharacterModel)]
        workspec = next((o for o in objects if isinstance(o, WorkSpec)), None)
        world = next((o for o in objects if isinstance(o, WorldModel)), None)

        history = history or []

        # 1. 读者预期与认知张力
        exp_horizon = self._derive_expectation_horizon(state, foreshadows, chapter_number)

        # 2. 承诺/回报债务
        promise_debt = self._derive_promise_debt(state, foreshadows, chapter_number)

        # 3. 关系轨迹
        rel_trajectory = self._derive_relational_trajectory(characters, state)

        # 4. 情绪模式与疲劳防御
        emotional_pacing = self._derive_emotional_pacing(state, history)

        # 5. 线程轮换与防饿死
        thread_rotation = self._derive_thread_rotation(foreshadows, state, history)

        # 6. 章节功能分配
        chapter_func = self._derive_chapter_function(
            chapter_number=chapter_number,
            frame_context=frame_context,
            structure_template=structure_template,
            emotional_pacing=emotional_pacing,
            promise_debt=promise_debt,
        )

        # 7. 信息与场景密度
        density_budget = self._derive_density_budget(
            chapter_func=chapter_func,
            emotional_pacing=emotional_pacing,
            promise_debt=promise_debt,
            rel_trajectory=rel_trajectory,
        )

        orch_state = OrchestrationState(
            orchestration_id=f"orch_ch{chapter_number}",
            chapter_number=chapter_number,
            step_index=len(history),
            expectation_horizon=exp_horizon,
            promise_debt=promise_debt,
            relational_trajectory=rel_trajectory,
            emotional_pacing=emotional_pacing,
            thread_rotation=thread_rotation,
            chapter_function=chapter_func,
            density_budget=density_budget,
            history_summary=[
                f"Ch{h.get('chapter', i+1)}: {h.get('function', 'scene')} - {h.get('emotion', 'normal')}"
                for i, h in enumerate(history[-5:])
            ],
        )
        return orch_state

    # -------------------------------------------------------------------------
    # 7 维独立推导逻辑
    # -------------------------------------------------------------------------
    def _derive_expectation_horizon(
        self,
        state: Optional[NarrativeState],
        foreshadows: Optional[ForeshadowGraph],
        chapter_number: int,
    ) -> ReaderExpectationHorizon:
        top_questions: list[str] = []
        stalled_questions: list[str] = []
        tension_score = 0

        if foreshadows:
            ledger = derive_reader_expectations(foreshadows, current_plotunit_count=chapter_number)
            top_q_entries = ledger.top_questions(limit=5)
            top_questions = [e.reader_question for e in top_q_entries]
            stalled_entries = ledger.overdue_expectations()
            stalled_questions = [e.reader_question for e in stalled_entries]
            if stalled_entries:
                tension_score += 2

        if state:
            if state.active_suspense_items:
                top_questions.extend([s for s in state.active_suspense_items if s not in top_questions])
                tension_score += len(state.active_suspense_items)
            if state.active_conflicts:
                tension_score += len(state.active_conflicts)

        if tension_score >= 4 or (stalled_questions and tension_score >= 2):
            cognitive_tension = "critical"
            horizon = 1
        elif tension_score >= 2:
            cognitive_tension = "high"
            horizon = 2
        elif tension_score >= 1:
            cognitive_tension = "medium"
            horizon = 3
        else:
            cognitive_tension = "low"
            horizon = 4

        return ReaderExpectationHorizon(
            cognitive_tension=cognitive_tension,
            expectation_horizon=horizon,
            top_questions=top_questions[:5],
            stalled_questions=stalled_questions[:3],
        )

    def _derive_promise_debt(
        self,
        state: Optional[NarrativeState],
        foreshadows: Optional[ForeshadowGraph],
        chapter_number: int,
    ) -> PromisePayoffDebt:
        if not foreshadows or not foreshadows.entries:
            return PromisePayoffDebt()

        active = foreshadows.get_active()
        resolved = [e for e in foreshadows.entries if e.current_status == "resolved"]
        overdue: list[str] = []

        current_time = state.current_time if state else ""
        for e in active:
            is_overdue = False
            if e.overdue_risk or e.current_status == "delayed":
                is_overdue = True
            elif e.expires_at and current_time and current_time >= e.expires_at:
                is_overdue = True
            elif len(e.advancement_nodes) == 0 and chapter_number >= 4:
                is_overdue = True
            if is_overdue:
                overdue.append(e.thread_id)

        open_count = len(active)
        res_count = len(resolved)
        overdue_count = len(overdue)

        if overdue_count >= 2 or (overdue_count >= 1 and open_count >= 4):
            debt_level = "critical"
            payoff_urgency = "immediate"
        elif overdue_count >= 1 or open_count >= 5:
            debt_level = "high"
            payoff_urgency = "high"
        elif open_count >= 2:
            debt_level = "moderate"
            payoff_urgency = "medium"
        else:
            debt_level = "low"
            payoff_urgency = "low"

        return PromisePayoffDebt(
            open_threads_count=open_count,
            resolved_threads_count=res_count,
            overdue_threads_count=overdue_count,
            debt_level=debt_level,
            payoff_urgency=payoff_urgency,
            urgent_thread_ids=overdue[:5],
        )

    def _derive_relational_trajectory(
        self,
        characters: list[CharacterModel],
        state: Optional[NarrativeState],
    ) -> RelationalTrajectory:
        if not characters:
            return RelationalTrajectory()

        protagonist = characters[0]
        notes: list[str] = []
        leverages: list[str] = []
        trend = "stable"

        # 检查主角对其他角色的关系和行为差异
        for other in characters[1:]:
            rel_desc = protagonist.relations.get(other.character_id, "")
            behav_desc = protagonist.relation_behaviors.get(other.character_id, "")
            if rel_desc or behav_desc:
                notes.append(f"{protagonist.name}对{other.name}: {rel_desc or behav_desc}")

            # 人际杠杆检查（秘密/压力/软肋）
            if other.secret:
                leverages.append(f"{other.name}持有秘密「{other.secret}」")
            if other.fear:
                leverages.append(f"{other.name}的软肋「{other.fear}」")

            # 关系走向判定
            if other.stance in ("敌对", "对抗", "对立") or "敌" in rel_desc or "对抗" in rel_desc:
                trend = "confrontation"
            elif other.stance in ("合作", "盟友", "信任") and trend != "confrontation":
                trend = "bonding"
            elif "怀疑" in rel_desc or "戒备" in rel_desc or "疏离" in rel_desc:
                if trend != "confrontation":
                    trend = "estrangement"

        if protagonist.current_pressure:
            leverages.extend(protagonist.current_pressure[:2])

        dynamic_desc = f"核心互动走向：{trend}；在场角色立场分明。"
        if notes:
            dynamic_desc = "；".join(notes[:3])

        return RelationalTrajectory(
            dominant_dynamic=dynamic_desc,
            active_leverages=leverages[:3],
            estrangement_vs_bonding=trend,
            trajectory_notes=notes,
        )

    def _derive_emotional_pacing(
        self,
        state: Optional[NarrativeState],
        history: list[dict],
    ) -> EmotionalPacing:
        recent_temps: list[str] = []
        for h in history[-3:]:
            if "emotion" in h and h["emotion"]:
                recent_temps.append(h["emotion"])
        if not recent_temps and state and state.emotional_temperature:
            recent_temps.append(state.emotional_temperature)

        # 统计连续高压/高张力
        high_tension_count = 0
        for temp in reversed(recent_temps):
            if any(marker in temp for marker in _HIGH_TENSION_EMOTIONS):
                high_tension_count += 1
            else:
                break

        # 审美疲劳防御：连续 2+ 节点高压
        if high_tension_count >= 2:
            return EmotionalPacing(
                recent_temperatures=recent_temps,
                current_rhythm="recovery",
                fatigue_risk=True,
                target_temperature="舒缓",
                pacing_directive="连续处于高张力对峙，本单元须安排缓冲沉淀、情感交流或战术复盘，防止读者审美疲劳",
            )

        # 检查连续平淡/低谷
        low_tension_count = 0
        for temp in reversed(recent_temps):
            if any(marker in temp for marker in _LOW_TENSION_EMOTIONS):
                low_tension_count += 1
            else:
                break

        if low_tension_count >= 2:
            return EmotionalPacing(
                recent_temperatures=recent_temps,
                current_rhythm="buildup",
                fatigue_risk=False,
                target_temperature="激昂",
                pacing_directive="前序节奏较为平缓，本单元应引入新变数或升级既有冲突，拉高叙事张力",
            )

        # 常规推进
        curr_temp = recent_temps[-1] if recent_temps else "稳步推进"
        return EmotionalPacing(
            recent_temperatures=recent_temps,
            current_rhythm="buildup",
            fatigue_risk=False,
            target_temperature=None,
            pacing_directive=f"保持当前情绪基调（{curr_temp}），稳步推进核心冲突与目标",
        )

    def _derive_thread_rotation(
        self,
        foreshadows: Optional[ForeshadowGraph],
        state: Optional[NarrativeState],
        history: list[dict],
    ) -> ThreadRotation:
        if not foreshadows:
            return ThreadRotation()

        active = [e.thread_id for e in foreshadows.get_active()]
        linked = set(state.linked_open_threads if state else [])

        # 检查历史出现过的线程
        seen_threads: dict[str, int] = {}
        for step_idx, h in enumerate(history):
            for tid in h.get("threads", []):
                seen_threads[tid] = step_idx

        # 支线防饿死：活跃但从未出现过或距离最近出现 >= 2 步
        starved: list[str] = []
        current_step = len(history)
        for tid in active:
            if tid not in linked:
                last_seen = seen_threads.get(tid, -1)
                if last_seen == -1 and current_step >= 2:
                    starved.append(tid)
                elif last_seen != -1 and (current_step - last_seen) >= 3:
                    starved.append(tid)

        if starved:
            rec = "sub_rotation"
            directive = f"建议照应沉寂支线 [{', '.join(starved[:2])}]，防止次要情节线断流饿死"
        elif len(active) <= 1:
            rec = "main_push"
            directive = "主线处于关键推进期，全力突破核心目标"
        else:
            rec = "balanced"
            directive = "主支线交替推进，保持各线程动态活力"

        return ThreadRotation(
            active_threads=active,
            starved_threads=starved,
            rotation_recommendation=rec,
            rotation_directive=directive,
        )

    def _derive_chapter_function(
        self,
        chapter_number: int,
        frame_context: Optional[dict],
        structure_template: Optional[str],
        emotional_pacing: EmotionalPacing,
        promise_debt: PromisePayoffDebt,
    ) -> ChapterFunctionAllocation:
        # 疲劳防御优先
        if emotional_pacing.fatigue_risk:
            return ChapterFunctionAllocation(
                chapter_index=chapter_number,
                assigned_function="transition",
                hook_strategy="emotional_resonance",
                pacing_role="张力缓冲与沉淀转折：复盘上一轮危机，休整与谋划下一步",
            )

        # 债务极高优先兑现
        if promise_debt.payoff_urgency == "immediate":
            return ChapterFunctionAllocation(
                chapter_index=chapter_number,
                assigned_function="payoff",
                hook_strategy="revelation",
                pacing_role="承诺回报兑现章：揭晓核心悬念或达成重大阶段性成果",
            )

        # 从 frame_context 提取 formula_node 导向
        formula_node = ""
        if frame_context and isinstance(frame_context, dict):
            current_frame = frame_context.get("current_frame", {})
            formula_node = current_frame.get("formula_node", "")

        if "起" in formula_node or "铺垫" in formula_node or "入局" in formula_node:
            func = "setup"
            hook = "open_question"
            role = "局势铺垫与新目标确立"
        elif "承" in formula_node or "升级" in formula_node or "交锋" in formula_node:
            func = "escalation"
            hook = "cliffhanger"
            role = "矛盾升级与阻碍加剧"
        elif "转" in formula_node or "破局" in formula_node or "高潮" in formula_node:
            func = "crisis"
            hook = "cliffhanger"
            role = "危机爆发与命运转折抉择"
        elif "合" in formula_node or "结算" in formula_node or "余波" in formula_node:
            func = "payoff"
            hook = "revelation"
            role = "阶段性成果回收与深层谜题开启"
        else:
            # 经典 4 步循环：1铺垫 2升级 3危机/兑现 4过渡/余波
            cycle = chapter_number % 4
            if cycle == 1:
                func = "setup"
                hook = "open_question"
                role = "阶段起步与局势导入"
            elif cycle == 2:
                func = "escalation"
                hook = "cliffhanger"
                role = "冲突深化与行动受阻"
            elif cycle == 3:
                func = "crisis"
                hook = "cliffhanger"
                role = "核心危机爆发与转折破局"
            else:
                func = "transition"
                hook = "emotional_resonance"
                role = "余波整理与下阶段过渡"

        return ChapterFunctionAllocation(
            chapter_index=chapter_number,
            assigned_function=func,
            hook_strategy=hook,
            pacing_role=role,
        )

    def _derive_density_budget(
        self,
        chapter_func: ChapterFunctionAllocation,
        emotional_pacing: EmotionalPacing,
        promise_debt: PromisePayoffDebt,
        rel_trajectory: RelationalTrajectory,
    ) -> InformationDensityBudget:
        notes: list[str] = []
        if chapter_func.assigned_function in ("payoff", "crisis") or promise_debt.debt_level == "critical":
            reveal_budget = "burst"
            notes.append("关键节点：允许集中揭晓重要信息与阶段性真相")
        elif chapter_func.assigned_function in ("transition", "setup") or emotional_pacing.fatigue_risk:
            reveal_budget = "conservative"
            notes.append("铺垫与缓冲阶段：克制信息释放，重在沉淀与细节感知")
        else:
            reveal_budget = "moderate"
            notes.append("稳步释放：按情节推进节奏适度释放次级信息")

        if chapter_func.assigned_function in ("crisis", "escalation"):
            scene_density = "action_dense"
        elif emotional_pacing.fatigue_risk or chapter_func.assigned_function == "transition":
            scene_density = "atmospheric"
        elif rel_trajectory.estrangement_vs_bonding in ("confrontation", "estrangement"):
            scene_density = "dialogue_dense"
        else:
            scene_density = "balanced"

        return InformationDensityBudget(
            reveal_budget=reveal_budget,
            scene_density_target=scene_density,
            exposure_pacing_limit="避免集中说教解说，信息必须随人物决策与外部冲突自然流出",
            budget_notes=notes,
        )

    # -------------------------------------------------------------------------
    # 对齐打分与生产集成
    # -------------------------------------------------------------------------
    def score_proposal_alignment(
        self,
        state: OrchestrationState,
        package: dict,
    ) -> tuple[float, list[str]]:
        """计算候选包与当前编排导向的对齐分（0.0-1.0）及理由."""
        score = 0.5
        notes: list[str] = []

        pu = package.get("plotunit")
        if pu is None:
            return score, ["无 PlotUnit 数据"]

        goal = getattr(pu, "goal", "")
        conflict = getattr(pu, "conflict", "")
        hook = getattr(pu, "hook", "") or ""
        shift = getattr(pu, "emotional_shift", "") or ""
        consequences = getattr(pu, "consequences", [])
        released = getattr(pu, "released_information", [])
        text = f"{goal} {conflict} {hook} {shift} {' '.join(consequences)} {' '.join(released)}"

        # 1. 疲劳防御对齐
        if state.emotional_pacing.fatigue_risk:
            if any(m in text for m in _CALM_REFLECTION_MARKERS):
                score += 0.2
                notes.append("命中情绪缓冲要求：包含战术复盘/思考交流")
            if any(m in text for m in _EXTREME_ACTION_MARKERS):
                score -= 0.2
                notes.append("违背疲劳防御：连续极高压喧嚣加剧审美疲劳")

        # 2. 紧迫债务兑现对齐
        if state.promise_debt.payoff_urgency in ("high", "immediate"):
            urgent_matched = any(tid in text for tid in state.promise_debt.urgent_thread_ids)
            if urgent_matched or bool(released):
                score += 0.2
                notes.append("有效响应高紧迫性债务：释放关键信息/推进紧迫线索")
            elif not released and not consequences:
                score -= 0.1
                notes.append("未响应承诺债务：未产生信息释放或明确后果")

        # 3. 支线防饿死对齐
        if state.thread_rotation.starved_threads:
            starved_matched = any(tid in text for tid in state.thread_rotation.starved_threads)
            if starved_matched:
                score += 0.15
                notes.append("防饿死召回：有效触及沉寂支线")

        # 4. 章节功能对齐
        func = state.chapter_function.assigned_function
        if func == "payoff" and (bool(released) or any(m in text for m in ("突破", "真相", "击败", "破解", "揭晓", "斩杀", "大成"))):
            score += 0.15
            notes.append("符合回报兑现定位：达成重大推进")
        elif func == "crisis" and any(m in text for m in ("危机", "变故", "险境", "突发", "生死", "搏杀", "来袭", "狂暴", "死战", "突围", "激战", "暴乱", "血战")):
            score += 0.15
            notes.append("符合危机定位：激化核心矛盾")
        elif func == "transition" and any(m in text for m in ("商定", "决定", "动身", "启程", "商议", "探讨", "复盘", "休整", "思考", "对坐", "清点")):
            score += 0.1
            notes.append("符合转折过渡定位：形成新走向决断或缓冲沉淀")

        clamped = max(0.0, min(1.0, score))
        return clamped, notes

    def build_orchestration_context(self, state: OrchestrationState) -> str:
        """生成注入 prompt 的上下文文本."""
        return state.to_prompt_context()


def load_orchestration_context(
    output_dir: Optional[Path],
    objects: list,
    *,
    enabled: bool = True,
    history: Optional[list[dict]] = None,
    chapter_number: int = 1,
    frame_context: Optional[dict] = None,
    structure_template: Optional[str] = None,
) -> str:
    """编排上下文 loader — 静默降级：未开启或无对象返回 ""（零成本契约）.

    从已持久化的 committed_orchestration_state.json 自动恢复历史。
    若 output_dir 存在且可写，持久化 active orchestration_state.json。
    """
    if not enabled or not objects:
        return ""

    # 优先从已持久化状态加载历史
    if history is None and output_dir is not None:
        try:
            committed = load_committed_orchestration_state(output_dir)
            if committed.history_entries:
                history = [e.model_dump() for e in committed.history_entries]
        except Exception:
            pass

    orchestrator = NarrativeOrchestrator()
    state = orchestrator.derive_orchestration_state(
        objects,
        history=history,
        chapter_number=chapter_number,
        frame_context=frame_context,
        structure_template=structure_template,
    )

    if output_dir and isinstance(output_dir, Path):
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            state_file = output_dir / "orchestration_state.json"
            state_file.write_text(
                json.dumps(state.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    return orchestrator.build_orchestration_context(state)
