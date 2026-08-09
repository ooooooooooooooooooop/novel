"""Chapter Composition —— 章节组合（替代 Plot Task 的生成接口）.

旧模式：当前问题是什么？下一章怎么推进？
新模式：从当前 State + Work Model 选择本章自然应该同时承载什么。

产出不是固定模板（不是每章必须 N 项），而是从当前活跃状态挑选：
A. 当前事件变化（主线推进）
B. 人物互动
C. 某后台线程重新入镜
D. 一个生活内容
E. 战略判断/布局（waiting/trigger/payoff）
F. 某关系细微变化
G. 叙事机会（欠账久的东西）

零成本契约：无 StateModel 或全空时返回空，prompt 字节不变。
"""

from typing import Optional

from src.object_state.statemodel import (
    CompressionLevel,
    Provenance,
    StateModel,
    ThreadState,
)


class ChapterComposition:
    """一章的组合建议."""

    def __init__(
        self,
        primary_thread: Optional[str] = None,
        reentries: Optional[list[str]] = None,
        background_progress: Optional[list[str]] = None,
        strategic_items: Optional[list[str]] = None,
        opportunities: Optional[list[str]] = None,
    ) -> None:
        self.primary_thread = primary_thread
        self.reentries = reentries or []
        self.background_progress = background_progress or []
        self.strategic_items = strategic_items or []
        self.opportunities = opportunities or []

    def is_empty(self) -> bool:
        return not (
            self.primary_thread
            or self.reentries
            or self.background_progress
            or self.strategic_items
            or self.opportunities
        )

    def render(self) -> str:
        """渲染 Chapter Composition 注入段（空则空串）. """
        if self.is_empty():
            return ""
        lines = ["【本章组合建议】（从当前跨章状态自然选择，非固定模板，可只取部分）"]
        if self.primary_thread:
            lines.append(f"- 主线推进：{self.primary_thread}")
        if self.reentries:
            lines.append(f"- 可重入线程：{'；'.join(self.reentries)}")
        if self.background_progress:
            lines.append(f"- 后台线程自然变化（可不展开，仅保留在场感）：{'；'.join(self.background_progress)}")
        if self.strategic_items:
            lines.append(f"- 战略/布局（可含等待与兑现）：{'；'.join(self.strategic_items)}")
        if self.opportunities:
            lines.append(f"- 叙事机会（欠账较久，值得重新入镜）：{'；'.join(self.opportunities)}")
        return "\n".join(lines)


def build_chapter_composition(
    sm: StateModel,
    work_prefers_life: bool = True,
    work_prefers_pivot: bool = True,
) -> ChapterComposition:
    """从当前 State 构建本章组合建议（启发式，可后续 LLM 细化）.

    - primary_thread：当前需要即时推进的线程（ACTIVE 且 needs_protagonist）
    - reentries：欠账达到阈值、且 near_payoff 或 有叙事机会的线程
    - background_progress：can_background 的离场线程最近变化（保留在场感）
    - strategic_items：pending_payoffs 中 waiting 条件已满足 或 接近兑现的
    - opportunities：优先级最高的一两条叙事机会
    """
    if sm.is_empty():
        return ChapterComposition()

    comp = ChapterComposition()

    # A. 主线推进：ACTIVE 且需要主角的线程，取第一个
    primary = next(
        (t for t in sm.threads
         if t.compression == CompressionLevel.ACTIVE and t.needs_protagonist),
        None,
    )
    if primary:
        comp.primary_thread = primary.label

    # C. 可重入：near_payoff 或 叙事机会里被点名的线程
    opp_entities = [o.description for o in sm.narrative_opportunities[:2]]
    for t in sm.threads:
        if t.compression in (CompressionLevel.WARM, CompressionLevel.ACTIVE) and t.near_payoff:
            comp.reentries.append(f"{t.label}（接近兑现）")
    if work_prefers_pivot:
        # 有离场机会时，允许主线被挂起（pivot 依据：存在等待时间）
        if opp_entities and primary:
            pass  # 提示：本章可不强行推进主线

    # B. 后台在场感：可后台运行的线程最近变化
    for t in sm.threads:
        if t.can_background and not t.needs_protagonist and t.compression != CompressionLevel.ARCHIVED:
            if t.recent_change:
                comp.background_progress.append(f"{t.label}（{t.recent_change}）")

    # E. 战略：待兑现且 waiting 条件可能有进展的
    for s in sm.strategic:
        if s.pending_payoffs:
            wait_part = "；".join(s.waiting_for) if s.waiting_for else "（无等待项）"
            payoff_part = "；".join(s.pending_payoffs)
            comp.strategic_items.append(f"{s.entity}：在等「{wait_part}」，待兑现「{payoff_part}」")
            if s.triggers:
                comp.strategic_items[-1] += f"，触发条件：{'、'.join(s.triggers)}"

    # G. 叙事机会
    for o in sorted(sm.narrative_opportunities, key=lambda x: -x.priority)[:2]:
        comp.opportunities.append(o.description)

    return comp


def build_composition_from_selection(
    selection,
    work_prefers_life: bool = True,
) -> ChapterComposition:
    """V2：Composition 输入 = SelectionResult（Selected Candidate Set），不是 Full State.

    这是 §52 的接口改造——Composition 只基于"已选择的候选"组织本章，
    不再直接从 Full State 取材料（避免绕开 Selection 硬塞）。
    """
    comp = ChapterComposition()

    selected = selection.selected
    if not selected:
        return comp

    # 主承载：第一个 SELECT 候选（主叙事线）
    comp.primary_thread = selected[0].current_change or selected[0].source_thread

    # 其余 SELECT：作为可承载项（自然经过/次要篇幅，非全部展开）
    for c in selected[1:]:
        comp.reentries.append(c.current_change or c.source_thread)

    # 后台在场感：Selection 明确划到 BACKGROUND 的（仍运行，但不展示）
    for c in selection.background[:3]:
        comp.background_progress.append(f"{c.source_thread}（后台运行）")

    return comp
