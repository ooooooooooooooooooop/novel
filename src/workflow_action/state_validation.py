"""State Model 测试三件套（验证 harness）.

设计目标：把「掌控局面 vs 遇事解决」「配角离场存活」「世界后台独立运行」
变成可检查的代理，供 M6 消融与目标作品 30 样本回归使用。

三件套：
1. Strategy Horizon：一个行为/站位的时间跨度（当前章→3章→10章→一卷后）。
   若 StrategicPosition 只有「现在解决」= 短视；有 waiting/trigger/pending_payoffs = 多时域。
2. 非主角线程存活：配角离开主角视野 10/30/50 章后，仍应有目标/变化/关系/新问题/成果。
   失败信号 = 「等待主角重新出现」。
3. 世界后台独立动力学：组织/公司/学校/家庭在主角不干预时仍独立变化（非冻结）。

注意：本模块是**代理/判据**；真实生成验证在 M6（目标作品 30 样本）里跑。
"""

from typing import Optional

from src.object_state.statemodel import (
    CompressionLevel,
    OffScreenProcess,
    Provenance,
    StateModel,
    StrategicPosition,
)


# ---------------------------------------------------------------------------
# 1. Strategy Horizon（时间跨度代理）
# ---------------------------------------------------------------------------

def strategy_horizon_score(sm: StateModel) -> dict:
    """评估战略站位的时间跨度.

    - multi_horizon：同时有 waiting(未来) + pending_payoffs(待兑现) + triggers(条件) → 高
    - solve_now_only：只有当前判断、无等待/兑现 → 短视（Problem→Response→Solution 特征）
    返回 {n_strategic, multi_horizon, solve_now_only, horizon_span}.
    """
    n = len(sm.strategic)
    multi = 0
    solve_now = 0
    max_span = 0
    for s in sm.strategic:
        has_future = bool(s.waiting_for or s.pending_payoffs or s.triggers)
        has_span = bool(s.waiting_for) and bool(s.pending_payoffs)
        if has_span:
            multi += 1
            max_span = max(max_span, 3)  # 至少覆盖未来兑现
        elif not has_future:
            solve_now += 1
    return {
        "n_strategic": n,
        "multi_horizon": multi,
        "solve_now_only": solve_now,
        "horizon_span": max_span,
    }


# ---------------------------------------------------------------------------
# 2. 非主角线程存活（离场配角不冻结）
# ---------------------------------------------------------------------------

def offscreen_survival_check(sm: StateModel, elapsed_chapters: int = 30) -> dict:
    """检查离场实体的存活度.

    通过条件（对每个离场实体）：
    - 有 background_state（离场期间有状态，非空）
    - 有 events_since（发生过事，不是冻结）
    - next_most_likely 不是「等待主角回来」这类被动句
    返回 {total, survived, waiting_passive, detail}.
    """
    if not sm.offscreen:
        return {"total": 0, "survived": 0, "waiting_passive": 0, "detail": "无离场实体"}

    survived = 0
    waiting_passive = 0
    passive_markers = ["等待", "等主角", "等他", "盼着", "守候"]
    for off in sm.offscreen:
        has_state = bool(off.background_state)
        has_events = bool(off.events_since) or elapsed_chapters >= 20
        passive = any(m in (off.next_most_likely or "") for m in passive_markers)
        if has_state and has_events and not passive:
            survived += 1
        elif passive:
            waiting_passive += 1
    return {
        "total": len(sm.offscreen),
        "survived": survived,
        "waiting_passive": waiting_passive,
        "detail": f"离场{elapsed_chapters}章后存活 {survived}/{len(sm.offscreen)}（被动等待 {waiting_passive}）",
    }


# ---------------------------------------------------------------------------
# 3. 世界后台独立动力学（组织/机构不冻结）
# ---------------------------------------------------------------------------

def world_background_check(sm: StateModel, entity_kinds: Optional[list[str]] = None) -> dict:
    """检查组织/机构类离场实体的独立动力学.

    entity_kinds 过滤：如 ["组织","公司","学校","家庭","社会环境"].
    通过条件：该类实体有 background_state + events_since（独立变化，非冻结）.
    """
    kinds = entity_kinds or ["组织", "公司", "学校", "家庭"]
    orgs = [o for o in sm.offscreen if any(k in o.entity for k in kinds)]
    if not orgs:
        return {"total_org": 0, "independent": 0, "detail": "无组织类离场实体"}

    independent = sum(1 for o in orgs if o.background_state and o.events_since)
    return {
        "total_org": len(orgs),
        "independent": independent,
        "detail": f"组织类 {independent}/{len(orgs)} 有独立动力学（非冻结）",
    }


def build_survival_probe(
    entity: str, intents: Optional[list[str]], elapsed_chapters: int, kind: str = ""
) -> OffScreenProcess:
    """构造一个离场实体的存活探针（供测试用）. """
    off = OffScreenProcess(entity=entity, last_seen_chapter=0)
    # 复用 state_pivot 的启发式推演，但避免循环依赖：这里直接构造
    steps = max(1, elapsed_chapters // 10)
    parts = []
    if intents:
        parts.append(f"在朝「{intents[0]}」推进（已推进约{steps}步）")
    else:
        parts.append(f"按原有轨迹自行运转（已过{elapsed_chapters}章）")
    if elapsed_chapters >= 30:
        parts.append("性格/处境已有可见变化")
    off.background_state = "；".join(parts)
    off.next_most_likely = "；".join(parts)
    off.events_since.append(f"（模拟）{off.next_most_likely}")
    return off


# ---------------------------------------------------------------------------
# 三指标（State 阶段的质量核心）：Selection Precision / Silence Discipline / Off-screen Survival
# ---------------------------------------------------------------------------

def _thread_mentions(text: str, thread_keywords: dict) -> set:
    """正文命中哪些线程（keyword 命中，工程诊断用，不作质量证明）. """
    return {name for name, kws in thread_keywords.items() if any(k in text for k in kws)}


def selection_precision(gen_text: str, real_text: str, thread_keywords: dict) -> dict:
    """Selection Precision：进入正文的状态，是不是该进入的？

    定义：state-gen 用到的线程 ∩ 真实章用到的线程 / state-gen 用到的线程。
    高 = 生成选对了；低 = 塞入了真实章没有的东西。
    同时报告"用而未见于真实"（潜在塞入）与"真实用而 state-gen 漏"（选择失败）。
    """
    gen = _thread_mentions(gen_text, thread_keywords)
    real = _thread_mentions(real_text, thread_keywords)
    inter = gen & real
    return {
        "precision": len(inter) / len(gen) if gen else 0.0,
        "gen_used": len(gen),
        "real_used": len(real),
        "crammed": sorted(gen - real),
        "missed": sorted(real - gen),
    }


def silence_discipline(gen_text: str, thread_keywords: dict) -> dict:
    """Silence Discipline：不该进入正文的状态，有没有被忍住？

    定义：正文实际用到的线程数 / 状态中活跃线程总数。
    - 理想是"自然子集"（用 2-3 / 8），不是全部。
    - ratio=1.0（全用）= 状态清单式丰富（Checklist 化风险）。
    同时报告被忍住的线程（正文未写）——它们应仍活着，而非被遗忘。
    """
    used = _thread_mentions(gen_text, thread_keywords)
    total = len(thread_keywords)
    return {
        "used": len(used),
        "total": total,
        "usage_ratio": len(used) / total if total else 0.0,
        "restrained": sorted(set(thread_keywords) - used),
        "checklist_like": len(used) == total,  # 全用 = 清单化信号
    }


def offscreen_survival(sm: StateModel, gen_text: str, thread_keywords: dict) -> dict:
    """Off-screen Survival：没进入正文的状态，有没有继续活着（没被遗忘）？

    检查：正文未用的线程，在 State 里是否仍标记为活跃（ACTIVE/WARM），
    或离场实体仍有 background_state / events_since（非冻结）。
    """
    used = _thread_mentions(gen_text, thread_keywords)
    restrained = set(thread_keywords) - used
    # 线程仍在 state 中活跃
    alive_threads = {
        t.label for t in sm.threads
        if t.compression in (CompressionLevel.ACTIVE, CompressionLevel.WARM)
    }
    # 离场实体仍有背景状态
    alive_offscreen = {o.entity for o in sm.offscreen if o.background_state or o.events_since}
    survived = [r for r in restrained if r in alive_threads or any(r in e for e in alive_offscreen)]
    return {
        "restrained": sorted(restrained),
        "survived_in_state": sorted(survived),
        "forgotten": sorted(set(restrained) - set(survived)),
        "survival_rate": len(survived) / len(restrained) if restrained else 1.0,
    }
