"""StateModel 运行机制：后台推进 + Pivot.

- Off-screen 后台推进：离场实体不冻结，按时间/意图/环境/资源/关系推演"最可能发生什么"。
  产出默认 Provenance.SIMULATED；只有写进正文才升级为 CANON（防后台污染）。
- Pivot 机制：Thread Suspension / Re-entry / Merge / Split / Escalation / Natural Death。
  判断依据（非"为了丰富"）：当前事件是否需要即时处理 / 是否存在等待时间 /
  其他线程是否达到入镜点 / 作品本身是否常这样切换。
"""

from typing import Optional

from src.object_state.statemodel import (
    CompressionLevel,
    NarrativeOpportunity,
    OffScreenProcess,
    Provenance,
    StateModel,
    ThreadState,
)


# ---------------------------------------------------------------------------
# Pivot 操作（结构性，代码可测）
# ---------------------------------------------------------------------------

def suspend_thread(sm: StateModel, thread_id: str) -> Optional[ThreadState]:
    """挂起线程：当前事件有等待时间，暂不处理（不杀死，保留后台）. """
    for t in sm.threads:
        if t.thread_id == thread_id:
            t.compression = CompressionLevel.WARM
            return t
    return None


def reenter_thread(sm: StateModel, thread_id: str) -> Optional[ThreadState]:
    """线程重入：达到入镜点，回到 ACTIVE. """
    for t in sm.threads:
        if t.thread_id == thread_id:
            t.compression = CompressionLevel.ACTIVE
            return t
    return None


def archive_thread(sm: StateModel, thread_id: str) -> Optional[ThreadState]:
    """线程自然死亡/归档：保留压缩引用（Dormant/Archived ≠ Forgotten）. """
    for t in sm.threads:
        if t.thread_id == thread_id:
            t.compression = CompressionLevel.ARCHIVED
            return t
    return None


def merge_threads(sm: StateModel, primary: str, merged: str) -> Optional[ThreadState]:
    """线程合流：两条线合并进主线程（如商业谈判与官场线交汇）. """
    p = next((t for t in sm.threads if t.thread_id == primary), None)
    m = next((t for t in sm.threads if t.thread_id == merged), None)
    if p and m:
        p.current_state = f"{p.current_state}；汇入{m.label}"
        p.next_natural_evolution = m.next_natural_evolution or p.next_natural_evolution
        m.compression = CompressionLevel.ARCHIVED
        sm.threads.remove(m)
        return p
    return None


def escalate_thread(sm: StateModel, thread_id: str) -> Optional[ThreadState]:
    """线程升级：冲突/事件升级（如埋伏笔到兑现前的总爆发）. """
    for t in sm.threads:
        if t.thread_id == thread_id:
            t.near_payoff = True
            return t
    return None


# ---------------------------------------------------------------------------
# Off-screen 后台推进（启发式 SIMULATED 推演）
# ---------------------------------------------------------------------------

def propose_background_evolution(
    off: OffScreenProcess,
    elapsed_chapters: int,
    intents: Optional[list[str]] = None,
    resources: Optional[list[str]] = None,
) -> OffScreenProcess:
    """基于时间/意图/资源，为离场实体推演最可能发生的事（SIMULATED，非 CANON）.

    规则（启发式，可测）：
    - elapsed 很小 → 基本延续现状（下一最可能 = 沿其既有方向）
    - elapsed 很大 + 有明确意图 → 意图推进一个台阶
    - 有资源/关系变化 → 该变化开始产生后果
    """
    steps = max(1, elapsed_chapters // 10)
    intents = intents or []
    resources = resources or []

    parts = []
    if intents:
        target = intents[0]
        parts.append(f"在朝「{target}」推进（已推进约{steps}步）")
    else:
        parts.append(f"按原有轨迹自行运转（已过{elapsed_chapters}章）")
    if resources:
        parts.append(f"其资源「{'、'.join(resources[:3])}」正开始产生变化")
    if elapsed_chapters >= 30:
        parts.append("性格/处境已有可见变化")

    off.background_state = "；".join(parts) if parts else off.background_state
    off.next_most_likely = "；".join(parts)
    off.events_since.append(f"（模拟）{off.next_most_likely}")
    off.provenance = Provenance.SIMULATED  # 防污染：默认不升级
    return off


def make_reentry_opportunity(
    sm: StateModel, entity: str, description: str, last_seen: Optional[int]
) -> NarrativeOpportunity:
    """离场实体欠账太久 → 生成叙事机会（供 Chapter Composition 考虑重入）. """
    overdue = 0
    if last_seen is not None and sm.last_chapter is not None:
        overdue = max(0, sm.last_chapter - last_seen)
    priority = min(10, 3 + overdue // 5)  # 欠得越久优先级越高
    return NarrativeOpportunity(
        opp_type="人物重入",
        description=f"{description}（已离场{overdue}章）",
        last_seen=last_seen,
        priority=priority,
        provenance=Provenance.INFERRED,
    )


def check_offscreen_opportunities(
    sm: StateModel, offscreen_threshold: int = 20
) -> StateModel:
    """扫描离场实体，欠账超过阈值且无机会时，补一条重入机会. """
    existing = {o.description for o in sm.narrative_opportunities}
    for off in sm.offscreen:
        last = off.last_seen_chapter
        overdue = (sm.last_chapter - last) if (sm.last_chapter and last is not None) else 0
        if overdue >= offscreen_threshold and off.entity not in existing:
            sm.narrative_opportunities.append(
                make_reentry_opportunity(sm, off.entity, f"{off.entity}线", last)
            )
    return sm


# ---------------------------------------------------------------------------
# V2：Pivot 由 Selection 结果驱动（§52 改造——不再独立硬规则）
# ---------------------------------------------------------------------------

def pivot_from_selection(sm: StateModel, selection) -> StateModel:
    """Pivot = Selection 结果，而非独立硬规则.

    - SELECT 候选对应的线程 → 保持 ACTIVE（本章推进）
    - BACKGROUND 候选 → WARM（挂起，仍在运行但不展示；BACKGROUND ≠ Forgotten）
    - DORMANT → WARM/DORMANT（无需推进）
    这是"线程竞争入镜资格后的自然结果"，而不是"为了丰富切一条线"。
    """
    selected_sources = {c.source_thread for c in selection.selected}
    background_sources = {c.source_thread for c in selection.background}
    dormant_sources = {c.source_thread for c in selection.dormant}

    for t in sm.threads:
        if t.label in selected_sources:
            t.compression = CompressionLevel.ACTIVE
        elif t.label in background_sources:
            t.compression = CompressionLevel.WARM  # 挂起不杀死
        elif t.label in dormant_sources:
            t.compression = CompressionLevel.WARM
    return sm
