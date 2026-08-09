"""Reveal Validation —— Reader Knowledge 泄露检测（V2 核心之四）.

原则 C：World Change ≠ Narrative Reveal。世界已经发生 ≠ 现在必须告诉读者。

隐藏信息处理：不能把完整计划塞给 prose generator（否则容易解释出来），
应转换成"行为约束"（当前行为需保持与未公开利益目标一致，不主动解释真实动机）。

Reveal Validator 检查：正文是否产生了超出 Reader Knowledge 的泄露——
- 提前解释未来布局/计划
- 说出角色不该知道/读者不该知道的信息
- 把 SIMULATED/PLANNED 当 CANON 呈现

关键词只作工程诊断；最终质量判断交给开放盲评。
"""

from typing import Optional

from src.workflow_action.candidate_pool import Candidate


# 泄露信号（启发式，工程诊断）
REVEAL_LEAK_MARKERS = [
    "其实他早就", "他早有计划", "背后的计划是", "这一切都是他安排的",
    "原来这就是", "他真正的目的是", "早在几个月前就", "他一直在等这个",
]


def check_reveal_leakage(
    prose_text: str,
    hidden_plans: Optional[list[str]] = None,
    reader_knowledge: Optional[set[str]] = None,
) -> dict:
    """检测正文是否泄露了未允许揭示的信息.

    - hidden_plans：系统知道但读者不该现在知道的计划（传关键词）
    - reader_knowledge：读者已知集合
    返回 {leak_markers, leaked_plans, leakage_score}.
    """
    leaks_found = [m for m in REVEAL_LEAK_MARKERS if m in prose_text]
    leaked_plans = []
    for plan in (hidden_plans or []):
        if plan and plan in prose_text:
            leaked_plans.append(plan)
    return {
        "leak_markers": leaks_found,
        "leaked_plans": leaked_plans,
        "leakage_score": len(leaks_found) + len(leaked_plans),
    }


def plan_to_constraint(hidden_plan: str, constraint: str) -> str:
    """隐藏计划 → 行为约束（传给正文的是约束，不是计划）. """
    return constraint


# ---------------------------------------------------------------------------
# Selection Validation —— Silence 拆成两个指标
# ---------------------------------------------------------------------------

# 显式提及泄露：没有真正入镜必要，却为证明记得而提一句
EXPLICIT_MENTION_MARKERS = [
    "至于", "那边的情况", "暂且不提", "暂时放下", "回头再说", "稍后再议",
    "他的事", "她那边", "这件事不急", "过些日子", "有机会再",
]


def silence_metrics(prose_text: str, selected_sources: set[str]) -> dict:
    """Silence 拆成两个独立指标.

    1. Explicit Mention Leakage：轻度高频污染（"至于XX那边……"）
    2. Forced Scene Re-entry：更严重——专门插一场没有自然触发的戏让状态出现

    返回 {explicit_mention_leakage, forced_reentry_hits, silenced}.
    """
    explicit = [m for m in EXPLICIT_MENTION_MARKERS if m in prose_text]

    # Forced Re-entry 检测：正文中出现 SELECT 候选以外的线程名（且是"专门提"）
    # 简化启发式：SELECT 之外的关键词被提及 = 可能的 forced mention
    forced = []
    # 这里只做占位：真正的 forced re-entry 需要场景级判断（开放盲评承担）
    return {
        "explicit_mention_leakage": explicit,
        "explicit_leak_count": len(explicit),
        "forced_reentry_hits": forced,
        "silenced": True,  # 占位：Selection 已把不写的东西留在 BACKGROUND
    }
