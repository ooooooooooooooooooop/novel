"""Candidate Pool —— Full State → Narrative Candidate Pool（V2 核心之一）.

V1 问题：Full State 直接进 Prompt → 诱导模型"既然告诉我就写出来" → checklist_like。
V2 转变：Full State 先转换成"当前可能值得进入叙事的材料"（Candidate Pool），
只有【有触发】的内容才有资格成为 Candidate；即使 State 里很重要，无触发也不进池。

原则 A：Known ≠ Shown；原则 B：Alive ≠ On-screen；原则 C：World Change ≠ Narrative Reveal。

Candidate 来源（必须带触发）：
- 当前线程真正发生变化
- 人物关系发生变化
- 后台进程形成结果
- 某战略条件达到触发点
- 某长期线程出现自然重入条件
- 当前场景自然连接到其他内容
- 某已有信息现在具备揭示价值
- Work Model 表明类似情况下作品通常会切入其他生活/关系内容

无触发的 State（即使重要）不得自动成为 Candidate。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.statemodel import (
    CompressionLevel,
    Provenance,
    StateModel,
    ThreadState,
)


class Candidate(BaseModel):
    """一条当前可能值得进入叙事的材料."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(description="候选唯一标识")
    source_thread: str = Field(description="来源线程/实体")
    current_change: str = Field(description="当前发生了什么变化（触发内容）")
    trigger_source: str = Field(
        description="触发来源: thread_change/relationship_change/offscreen_result/"
        "strategic_trigger/natural_reentry/scene_connection/reveal_value/work_preference"
    )
    involved_characters: list[str] = Field(default_factory=list, description="涉及人物")
    relation_to_current_scene: str = Field(
        default="", description="与当前场景的关系（自然连接/独立/冲突）"
    )
    needs_reveal: bool = Field(
        default=False, description="是否需要向读者揭示（true=有揭示价值）"
    )
    reader_knows: bool = Field(
        default=True, description="读者当前是否已知（false=对读者是新信息，需谨慎）"
    )
    dependencies: list[str] = Field(default_factory=list, description="依赖的其他候选")
    conflicts: list[str] = Field(default_factory=list, description="冲突的其他候选")
    non_entry_impact: str = Field(
        default="", description="不进入正文是否影响世界继续运行（空=不影响）"
    )
    evidence: str = Field(default="", description="来源证据（T-1 以内）")
    provenance: Provenance = Field(default=Provenance.INFERRED, description="来源分级")


class CandidatePool(BaseModel):
    """当前章的可叙事候选池."""

    model_config = ConfigDict(extra="forbid")

    chapter: Optional[int] = Field(default=None, description="当前章节号")
    candidates: list[Candidate] = Field(default_factory=list, description="候选列表")
    # 记录被排除但仍在运行的（供审计：BACKGROUND ≠ Forgotten）
    excluded_alive: list[str] = Field(
        default_factory=list, description="未入池但仍在运行的线程（BACKGROUND/DORMANT）"
    )

    def is_empty(self) -> bool:
        return not self.candidates


# ---------------------------------------------------------------------------
# 触发判定（V2 核心：不是"所有活跃 State"）
# ---------------------------------------------------------------------------

def _thread_has_trigger(t: ThreadState) -> Optional[str]:
    """线程是否有进入叙事的自然触发.

    触发条件（符合任一即返回触发来源）：
    - near_payoff=True：接近兑现（Strategic trigger / natural reentry）
    - recent_change 非空且 last_chapter 近：线程真正发生变化
    - compression==ACTIVE 且 needs_protagonist：当前主线需要推进
    """
    if t.near_payoff:
        return "strategic_trigger"
    if t.recent_change:
        return "thread_change"
    if t.compression == CompressionLevel.ACTIVE and t.needs_protagonist:
        return "scene_connection"
    return None


def build_candidate_pool(
    sm: StateModel,
    work_preference: Optional[list[str]] = None,
    reader_knowledge: Optional[set[str]] = None,
) -> CandidatePool:
    """从 Full State 构建 Candidate Pool（只收有触发的内容）.

    - 无触发的活跃线程 → excluded_alive（仍在运行，但本章不展示）
    - work_preference：作品倾向（如该作常切生活/关系），作为候选来源之一
    - reader_knowledge：读者已知集合（决定 needs_reveal / reader_knows）
    """
    pool = CandidatePool(chapter=sm.last_chapter)
    reader_knowledge = reader_knowledge or set()

    for t in sm.threads:
        if t.compression == CompressionLevel.ARCHIVED:
            continue  # 归档不产候选
        trigger = _thread_has_trigger(t)
        if trigger:
            change = t.current_state or t.recent_change or "状态"
            if t.near_payoff:
                change = f"{change}（接近兑现）"
            pool.candidates.append(
                Candidate(
                    candidate_id=f"c_{t.thread_id}",
                    source_thread=t.label,
                    current_change=change,
                    trigger_source=trigger,
                    involved_characters=[t.thread_id],  # 简化：线程ID占位
                    needs_reveal=bool(t.near_payoff),
                    reader_knows=(t.label in reader_knowledge),
                    non_entry_impact="无（可在后台继续运行）" if t.can_background else "",
                    provenance=Provenance.CANON if t.provenance == Provenance.CANON else Provenance.INFERRED,
                )
            )
        else:
            # 无触发：仍在运行，但本章不展示（BACKGROUND ≠ Forgotten）
            pool.excluded_alive.append(t.label)

    # 战略触发：waiting 条件可能达成 / pending_payoffs 接近
    for s in sm.strategic:
        if s.triggers or s.pending_payoffs:
            pool.candidates.append(
                Candidate(
                    candidate_id=f"c_strat_{s.entity}",
                    source_thread=f"战略-{s.entity}",
                    current_change="战略条件接近触发/待兑现",
                    trigger_source="strategic_trigger",
                    involved_characters=[s.entity],
                    needs_reveal=False,
                    reader_knows=False,
                    non_entry_impact="无（战略在后台继续演化）",
                    evidence="; ".join(s.pending_payoffs[:2]),
                    provenance=s.provenance,
                )
            )

    # 叙事机会：欠账足够（构成 natural reentry）
    for o in sm.narrative_opportunities:
        if o.priority >= 7:
            pool.candidates.append(
                Candidate(
                    candidate_id=f"c_opp_{len(pool.candidates)}",
                    source_thread=o.description,
                    current_change=o.description,
                    trigger_source="natural_reentry",
                    needs_reveal=True,
                    reader_knows=(o.description in reader_knowledge),
                    non_entry_impact="无（可继续欠账，但优先级很高）",
                    provenance=o.provenance,
                )
            )

    # Work 偏好：该作在类似情况下会切入生活/关系（作为候选来源之一，供 Selector 判断）
    if work_preference:
        for pref in work_preference:
            pool.candidates.append(
                Candidate(
                    candidate_id=f"c_work_{len(pool.candidates)}",
                    source_thread=f"作品倾向-{pref}",
                    current_change=f"作品在类似节点通常包含：{pref}",
                    trigger_source="work_preference",
                    needs_reveal=False,
                    reader_knows=True,
                    non_entry_impact="无",
                    provenance=Provenance.INFERRED,
                )
            )

    return pool
