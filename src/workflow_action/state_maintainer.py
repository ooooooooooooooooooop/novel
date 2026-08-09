"""StateModel 维护子系统：从每章增量提取/更新 8 类状态.

桥梁：让 State Model 真正随章运行（M6 的前置）。
混合策略：
- 确定性结构更新（代码）：facts / knowledge / intents / threads / relationships /
  narrative_opportunities 的机械维护（从 PlotUnit + NarrativeState 提取）。
- LLM 质性提取契约（[WAITING]）：offscreen 后台演化 / strategic 站位 /
  高质量 knowledge 分层——这些需要语义判断，走 prompt。
零成本契约：无 prev StateModel → 从空开始；无章节/无响应 → no-op，不注入。
"""

import json
from typing import Optional

from src.object_state.statemodel import (
    CompressionLevel,
    IntentEntry,
    KnowledgeEntry,
    NarrativeOpportunity,
    OffScreenProcess,
    Provenance,
    RelationshipEntry,
    StateModel,
    StrategicPosition,
    ThreadState,
)


# ---------------------------------------------------------------------------
# 确定性结构更新（从 PlotUnit / NarrativeState 机械维护）
# ---------------------------------------------------------------------------

def update_from_plotunit(
    sm: StateModel,
    plotunit: object,
    new_state: object,
    chapter_number: int,
) -> StateModel:
    """基于一个 PlotUnit + 新 NarrativeState 增量更新 StateModel.

    - facts：追加 released_information（去重）
    - knowledge：released_information → CANON（若新状态 hidden_information 减少 = 揭示）
    - intents：plotunit.goal → 主角的 immediate 意图
    - threads：plotunit 涉及的参与者/线程 → 更新 last_chapter + 提升 WARM→ACTIVE
    - relationships：participants 两两触碰 → 更新 temperature（轻量）
    - narrative_opportunities：其他线程 last_chapter 落后 → 机会优先级上涨
    """
    # 1. facts（released_information 是"读者/世界新得知"的事实）
    released = getattr(plotunit, "released_information", None) or []
    for info in released:
        if info and info not in sm.facts:
            sm.facts.append(info)

    # 2. knowledge：released_information 进入主要参与者的 knowledge（CANON）
    participants = getattr(plotunit, "participants", None) or []
    for info in released:
        for pid in participants:
            existing = [k for k in sm.knowledge if k.fact_ref == info and k.holder == pid]
            if not existing:
                sm.knowledge.append(
                    KnowledgeEntry(
                        fact_ref=info, holder=pid, status="knows",
                        provenance=Provenance.CANON,
                    )
                )

    # 3. intents：plotunit.goal → 主角 immediate 意图
    goal = getattr(plotunit, "goal", None)
    if goal and participants:
        for pid in participants:
            existing = [i for i in sm.intents if i.entity == pid and i.intent_scale == "immediate"]
            if not existing:
                sm.intents.append(
                    IntentEntry(entity=pid, intent_scale="immediate", intent=goal)
                )
            else:
                existing[0].intent = goal

    # 4. threads：本单元的标签/参与者 → 找到或建立对应线程，标记 ACTIVE + last_chapter
    unit_label = getattr(plotunit, "goal", None) or ""
    # 用 participants + formula_node 关联线程
    thread_hit = None
    for t in sm.threads:
        # 简化的关联：线程 label 出现在 unit goal 里，或参与者名出现在线程里
        if t.label and unit_label and t.label[:2] in unit_label:
            thread_hit = t
            break
    if thread_hit is None and participants:
        # 没有匹配线程则建一个"当前事件"线程（粗粒度）
        thread_hit = ThreadState(
            thread_id=f"thread_ch{chapter_number}",
            thread_type="当前事件",
            label=unit_label[:12] or "当前事件",
            current_state=unit_label,
            last_chapter=chapter_number,
            compression=CompressionLevel.ACTIVE,
            provenance=Provenance.CANON,
        )
        sm.threads.append(thread_hit)
    if thread_hit:
        thread_hit.last_chapter = chapter_number
        thread_hit.compression = CompressionLevel.ACTIVE

    # 5. relationships：participants 两两触碰
    for i in range(len(participants)):
        for j in range(i + 1, len(participants)):
            a, b = participants[i], participants[j]
            existing = [r for r in sm.relationships if r.from_entity == a and r.to_entity == b]
            if not existing:
                sm.relationships.append(
                    RelationshipEntry(from_entity=a, to_entity=b, bonds=["互动"], temperature="有接触")
                )
            else:
                existing[0].temperature = "有接触（近章）"

    # 6. narrative_opportunities：其他线程欠账上涨
    if sm.last_chapter is not None and sm.threads:
        for t in sm.threads:
            if t.compression in (CompressionLevel.WARM, CompressionLevel.ACTIVE) and t.last_chapter:
                overdue = chapter_number - t.last_chapter
                if overdue >= 15:
                    existing = [o for o in sm.narrative_opportunities if t.label in o.description]
                    if not existing:
                        sm.narrative_opportunities.append(
                            NarrativeOpportunity(
                                opp_type="线程回归", description=f"{t.label}线",
                                last_seen=t.last_chapter, priority=min(10, 3 + overdue // 5),
                            )
                        )

    sm.last_chapter = chapter_number
    return sm


# ---------------------------------------------------------------------------
# LLM 质性提取契约（offscreen / strategic / 深层 knowledge）
# ---------------------------------------------------------------------------

def build_maintenance_prompt(sm: StateModel, chapter_text: str) -> str:
    """构建 StateModel 质性维护 prompt（[WAITING]）.

    让 LLM 从本章正文提取/更新：offscreen 后台演化、strategic 站位、
    knowledge 分层（谁知道什么/误解/隐瞒）、narrative 机会。
    输出 JSON 与 StateModel 结构兼容，由 apply_maintenance_response 合并。
    """
    prev = sm.model_dump() if sm else {}
    return (
        "你是叙事状态维护器。基于本章正文，更新跨章状态（Narrative Living State）的质性部分。\n\n"
        "【上一章状态（JSON）】\n" + json.dumps(prev, ensure_ascii=False)[:4000] + "\n\n"
        "【本章正文】\n" + chapter_text[:6000] + "\n\n"
        "【输出 JSON 结构】\n"
        '{\n'
        '  "offscreen_updates": [{"entity": "...", "background_state": "...", '
        '"next_most_likely": "...", "events_since": ["..."]}],\n'
        '  "strategic_updates": [{"entity": "...", "observation": [...], "judgment": [...], '
        '"positioning": [...], "waiting_for": [...], "triggers": [...], "pending_payoffs": [...]}],\n'
        '  "knowledge_updates": [{"fact_ref": "...", "holder": "...", "status": "knows|not_knows|'
        'misunderstands|partial|withholds", "detail": "..."}],\n'
        '  "narrative_opportunities": [{"opp_type": "...", "description": "...", "priority": 0}]\n'
        '}\n\n'
        "规则：离场实体继续生活（时间/意图/环境/资源推演）；后台推演 provenance 保持 simulated；"
        "不知道就留空，不要编造。"
    )


def apply_maintenance_response(sm: StateModel, response_text: str) -> StateModel:
    """把 LLM 维护响应合并进 StateModel（后台推演默认 SIMULATED）. """
    try:
        data = json.loads(response_text)
    except Exception:
        return sm  # 解析失败 → no-op（零成本）

    # offscreen：合并/新建（SIMULATED）
    for o in data.get("offscreen_updates", []):
        entity = o.get("entity", "")
        if not entity:
            continue
        existing = [x for x in sm.offscreen if x.entity == entity]
        if existing:
            existing[0].background_state = o.get("background_state", existing[0].background_state)
            existing[0].next_most_likely = o.get("next_most_likely", existing[0].next_most_likely)
        else:
            sm.offscreen.append(OffScreenProcess(entity=entity, **{
                k: v for k, v in o.items() if k in ("background_state", "next_most_likely", "events_since")
            }))

    # strategic：合并/新建
    for s in data.get("strategic_updates", []):
        entity = s.get("entity", "")
        if not entity:
            continue
        existing = [x for x in sm.strategic if x.entity == entity]
        if existing:
            for k in ("observation", "judgment", "positioning", "waiting_for", "triggers", "pending_payoffs"):
                if s.get(k):
                    setattr(existing[0], k, s[k])
        else:
            sm.strategic.append(StrategicPosition(entity=entity, **{
                k: v for k, v in s.items() if k != "entity"
            }))

    # knowledge：合并
    for k in data.get("knowledge_updates", []):
        if k.get("fact_ref") and k.get("holder"):
            sm.knowledge.append(KnowledgeEntry(**k))

    # narrative_opportunities：追加（去重）
    existing_desc = {o.description for o in sm.narrative_opportunities}
    for n in data.get("narrative_opportunities", []):
        if n.get("description") and n["description"] not in existing_desc:
            sm.narrative_opportunities.append(NarrativeOpportunity(**n))

    return sm
