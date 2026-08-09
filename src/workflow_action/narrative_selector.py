"""Narrative Selector —— 从 Candidate Pool 选择本章入镜内容（V2 核心之二）.

V2 选择逻辑：
- **Empty Set Start**：从空章节材料开始。Candidate 必须证明"加入它会让这一章更符合
  当前作品在当前状态下的自然发展"才能进入。这样 Silence 是默认行为。
- **不设固定数量**：数量由 Work Model × 当前 State × 最近章节组织方式决定。
- **Minimum Sufficient Selection**：选择后再反向删除——如果拿掉某候选本章仍自然完整，
  则删除。追求 Minimum Sufficient Set，而非 Maximum Relevant Set。
- 三种结果：SELECT（进入正文）/ BACKGROUND（继续运行但不展示）/ DORMANT（无需推进）。

Selection 不记录"这个内容很精彩所以应该写"——判断来自作品与状态，不是通用标准。
"""

from typing import Optional

from src.object_state.statemodel import StateModel
from src.workflow_action.candidate_pool import Candidate, CandidatePool


class SelectionResult:
    """选择结果：SELECT / BACKGROUND / DORMANT."""

    def __init__(self) -> None:
        self.selected: list[Candidate] = []
        self.background: list[Candidate] = []
        self.dormant: list[Candidate] = []
        self.rejected: list[Candidate] = []  # 被 Suppressor 删除的

    def ids(self, kind: str) -> list[str]:
        return [c.candidate_id for c in getattr(self, kind)]


# ---------------------------------------------------------------------------
# Selection（Empty Set Start）
# ---------------------------------------------------------------------------

def _candidate_justifies_entry(
    c: Candidate,
    sm: StateModel,
    work_preferences: Optional[list[str]] = None,
) -> bool:
    """Candidate 是否证明自己有进入本章的资格.

    Empty Set Start：默认不选；只有满足以下之一才进入：
    - 主线程推进（thread_change / scene_connection）
    - 战略触发（strategic_trigger 且 pending 接近）
    - 叙事机会 priority 高（natural_reentry）
    - Work 偏好明确（该作在此类节点通常切入）
    无这些证据 → 不选（BACKGROUND/DORMANT）。
    """
    if c.trigger_source in ("thread_change", "scene_connection"):
        return True
    if c.trigger_source == "strategic_trigger":
        return True  # 战略触发总是有资格（但不保证最终入选）
    if c.trigger_source == "natural_reentry":
        return True
    if c.trigger_source == "work_preference":
        return bool(work_preferences)
    return False


def select_candidates(
    pool: CandidatePool,
    sm: StateModel,
    work_preferences: Optional[list[str]] = None,
    max_selected: Optional[int] = None,
) -> SelectionResult:
    """从 Candidate Pool 选择（Empty Set Start，最小充分）.

    - 先对每个 Candidate 问"是否有资格"（不是按优先级取前N）
    - 无资格 → DORMANT
    - 有资格但当前场景无自然连接 → BACKGROUND（仍运行）
    - 有资格且满足本章自然发展 → SELECT
    """
    result = SelectionResult()

    for c in pool.candidates:
        if not _candidate_justifies_entry(c, sm, work_preferences):
            result.dormant.append(c)
            continue

        # 与当前场景的关系：scene_connection 才最贴近主叙事；其余默认 BACKGROUND
        if c.trigger_source in ("thread_change", "scene_connection"):
            result.selected.append(c)
        elif c.trigger_source == "strategic_trigger":
            # 战略：默认 BACKGROUND（在后台演化），除非接近兑现
            if c.current_change and "接近兑现" in c.current_change:
                result.selected.append(c)
            else:
                result.background.append(c)
        elif c.trigger_source == "natural_reentry":
            result.background.append(c)  # 欠账线索：通常作为背景在场感，非主角线
        elif c.trigger_source == "work_preference":
            result.selected.append(c)  # 作品倾向（生活/关系承载）直接进

    # Minimum Sufficient：若未设上限且结果过满，按触发强度裁剪到默认自然范围
    if max_selected is not None and len(result.selected) > max_selected:
        # 保留 scene_connection/thread_change（主叙事），裁掉最弱的
        keep = [c for c in result.selected if c.trigger_source in ("thread_change", "scene_connection")]
        keep_n = len(keep)
        for c in result.selected:
            if len(keep) >= max_selected:
                break
            if c not in keep:
                keep.append(c)
        rest = [c for c in result.selected if c not in keep]
        result.background.extend(rest)
        result.selected = keep

    return result


# ---------------------------------------------------------------------------
# Selection Suppressor（只删，不增）
# ---------------------------------------------------------------------------

SUPPRESSION_PATTERNS = [
    ("reminiscence_mention", "为了证明记得而提及（无触发硬提）"),
    ("forced_reentry", "没有自然触发却硬回收（Forced Scene Re-entry）"),
    ("checklist_tick", "线程清单式点名（状态里有什么就报一遍）"),
    ("strategy_explain", "为了展示长期策略而提前解释布局（Strategic Reveal Leakage）"),
    ("padding_extra_line", "为了'丰富'强行增加第二条/第三条线"),
    ("hook_injection", "仅为了章末钩子引入新问题"),
]


def suppress_overreach(selection: SelectionResult) -> SelectionResult:
    """Selection Suppressor：反向审查层，只负责删。

    对每个 SELECT Candidate 问：
    - 拿掉它，本章是否仍自然完整？（Minimum Sufficient）
    - 是否命中抑制模式（清单点名/硬回收/强插/过度解释/为丰富加线/为钩子引入问题）？
    命中 → 删除（记录到 rejected，供审计）。

    Suppressor 没有权限创造新 Candidate；只能 保留/删除/延后。
    """
    pruned = []
    for c in selection.selected:
        # 抑制模式检测（基于候选的触发来源与当前变化文本的启发式）
        hits = []
        if c.trigger_source == "natural_reentry" and "欠账" in c.non_entry_impact:
            hits.append("checklist_tick")
        if c.trigger_source == "work_preference":
            hits.append("padding_extra_line")  # 若作品偏好被当清单执行
        if c.needs_reveal and c.current_change and ("计划" in c.current_change or "布局" in c.current_change):
            hits.append("strategy_explain")
        if c.trigger_source == "strategic_trigger" and not c.non_entry_impact:
            hits.append("strategy_explain")

        if hits:
            # 命中抑制：删除（延后到 BACKGROUND，不在本章展示）
            c_reason = "; ".join(hits)
            c.non_entry_impact = f"被 Suppressor 抑制（{c_reason}）"
            selection.rejected.append(c)
            selection.background.append(c)
        else:
            pruned.append(c)

    selection.selected = pruned
    return selection
