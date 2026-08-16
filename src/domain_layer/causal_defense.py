"""causal_defense — 长程因果防线（P1）.

把系统从「检测局部事实矛盾」升级为「阻止已发生现实、已付代价和已形成成长
被后文悄悄抹掉」。覆盖五类失败模式：

  1. 已完成事件被重写（抹掉已发生现实）
  2. 已付代价失效（代价未传播/无解释恢复）
  3. 人物成长或知识状态重置（成长/已接受事实被抹掉）
  4. 制度与群体后果未传播（制度改变不影响后续策略）
  5. 已有选择未改变后续策略空间（质量信号）

设计纪律（对齐 prose_reconcile 的既有原则）：
- 纯函数、确定性、零 LLM；证据来自已提交状态与可信对象。
- 每个检测器**保守触发**：只有同时具备「已确认前置事实 + 明确抹除/恢复/重置
  语言 + 同一实体」才产生 issue；证据不足返回空（不误伤负控制）。
- issue 类型全部复用现有 ReviewIssueType 枚举，不扩枚举。
- 输出按 (severity, issue_id) 排序，顺序无关；重复运行幂等。
- 接入 flow v3 提交点（evaluate_commit_reader_gate），blocking 即拒绝提交。

说明：prose_reconcile 已覆盖「状态回退（found/home → missing/dead）」「时间回退」
「重复顿悟」「纯氛围」。本模块与之互补——检测 prose_reconcile 未覆盖的
「已终结状态被重新激活/抹除」「代价传播」「成长重置」「制度后果」「选择无差异」。
"""

from __future__ import annotations

from src.object_state import (
    CharacterModel,
    FactLedger,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    WorldModel,
)

# ---------------------------------------------------------------------------
# 触发词表（与 review_signal_knowledge 风格一致，纯数据）
# ---------------------------------------------------------------------------

# 终结性状态词：已确认现实已「了结」，后续不应无解释地重新激活。
_TERMINAL_STATE_MARKERS: frozenset[str] = frozenset(
    (
        "死亡", "战死", "陨落", "焚毁", "烧毁", "摧毁", "夷为平地", "炸毁",
        "公开", "揭穿", "暴露", "交出", "失去", "遗失", "耗尽", "耗尽修为",
        "被夺", "被抢", "被抄", "被逐", "被废", "被灭", "被毁", "已死",
    )
)

# 抹除/重写语言：把已了结之事当作从未发生/重新完好。
_ERASURE_MARKERS: frozenset[str] = frozenset(
    (
        "完好如初", "恢复原状", "恢复原样", "重新完好", "死而复生", "起死回生",
        "失而复得", "从未发生", "像没发生过", "仿佛从未", "转眼恢复", "竟又恢复",
        "不知为何恢复", "忽然复原", "一夜恢复", "当作没有发生", "仿佛无事",
    )
)

# 代价已付的确认词（成本事实）。
_COST_FACT_MARKERS: frozenset[str] = frozenset(
    (
        "失去", "付出", "损失", "牺牲", "耗尽", "重伤", "折寿", "受罚", "代价",
        "被废", "被夺", "断臂", "失明", "废了", "反噬", "透支",
    )
)

# 新的代价支付动词（仅当恢复句本身出现这些才视为「为恢复再次付代价」）。
# 与 _COST_FACT_MARKERS 分离：恢复句里的对象名词（如「断臂」）不是新的支付。
_NEW_COST_PAYMENT_MARKERS: frozenset[str] = frozenset(
    (
        "失去", "付出", "损失", "牺牲", "耗尽", "重伤", "折寿", "受罚", "代价",
        "被废", "被夺", "反噬", "花费", "倾尽", "抵押", "献祭",
    )
)

# 无代价恢复语言：资源/能力/关系被无解释恢复。
_RECOVERY_MARKERS: frozenset[str] = frozenset(
    (
        "恢复", "复原", "康复", "痊愈", "重新拥有", "失而复得", "完好如初",
        "恢复如初", "重新获得", "拿回", "夺回", "又有了", "回归",
    )
)

# 成长/认知确认词（已形成成长或已接受事实）。
_GROWTH_MARKERS: frozenset[str] = frozenset(
    (
        "成长", "转变", "学会", "明白", "接受", "放下", "克服", "突破",
        "愿意托付", "不再逃避", "敢于", "承担",
    )
)

# 成长/认知重置语言：把已形成的成长或已接受事实抹掉。
_RESET_MARKERS: frozenset[str] = frozenset(
    (
        "回到从前", "又像从前", "恢复原样", "故态复萌", "打回原形", "恢复本性",
        "忘了", "忘记", "失忆", "重新变得", "仿佛从未改变", "又变回", "再次逃避",
        "重新不信", "又不敢", "回到原来的", "恢复冷漠",
    )
)

# 制度性后果词：公开/制度层面已改变，后续角色策略应受其影响。
_INSTITUTIONAL_MARKERS: frozenset[str] = frozenset(
    (
        "法令", "禁令", "通缉", "戒严", "封锁", "开战", "停战", "废黜", "抄家",
        "解散", "查封", "缉拿", "宵禁", "加税", "征兵", "灭门", "清剿", "削藩",
    )
)

# 策略空间变化词：选择应改变未来的可用资源/关系/风险/最优行动。
_STRATEGY_SPACE_MARKERS: frozenset[str] = frozenset(
    (
        "策略", "计划", "路线", "布局", "后手", "退路", "筹码", "底牌", "同盟",
        "报复", "反制", "戒备", "防范", "联合", "决裂", "投靠", "逃亡", "备战",
    )
)

# 重大选择触发词（声称是选择的单元必须有后续差异）。
_CHOICE_TRIGGERS: frozenset[str] = frozenset(
    (
        "决定", "选择", "放弃", "立誓", "答应", "拒绝", "背叛", "投靠", "决裂",
        "接受", "承诺", "赌上", "孤注一掷",
    )
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _plotunit_text(pu: PlotUnit) -> str:
    """拼接 PlotUnit 的信息承载字段（对齐 review_signals.pu_info_text）. """
    return " ".join(
        filter(
            None,
            [pu.goal, pu.conflict]
            + list(pu.released_information)
            + [pu.hook or "", pu.emotional_shift or ""]
            + list(pu.consequences)
            + [pu.state_change_summary or ""],
        )
    )


def _involved_entities(text: str, known_entities: list[str]) -> list[str]:
    """返回文本中出现的已知实体（优先完整标签匹配，再回退 2 字片段）. """
    hits: list[str] = []
    for entity in known_entities:
        label = entity
        if label and label in text:
            hits.append(label)
            continue
        # 中文 2 字回退（实体的可辨识前缀）
        if len(entity) >= 2 and entity[:2] in text:
            hits.append(entity)
    return hits


def _confirmed_facts(ledger: FactLedger) -> list:
    """已确认事实列表. """
    return [e for e in ledger.entries if e.confirmed]


def _fact_entities(fact) -> list[str]:
    """事实的匹配实体集：involved_entities + 陈述中的中文片段（兜底）. """
    entities = [eid for eid in (fact.involved_entities or []) if eid]
    entities.extend(seg for seg in _segments(fact.statement, 2))
    return sorted(set(entities))


# ---------------------------------------------------------------------------
# 检测器 1：已完成事件被重写（抹掉已发生现实）
# ---------------------------------------------------------------------------

def detect_erased_committed_event(objects: list) -> list[ReviewIssue]:
    """已确认的终结性事实（死亡/焚毁/公开/交出）被草案以「恢复/重写」语言抹掉.

    规则：存在 confirmed 的终结性事实（含 _TERMINAL_STATE_MARKERS 且为
    event/relation/reveal_status 类型），同一实体的 PlotUnit 草案含
    _ERASURE_MARKERS 且无新事件解释 → blocking fact_conflict。

    负控制：草案只提及历史（「他记得那里被烧毁了」）不含抹除词 → 不触发；
    草案有显式重建事件（「他们在废墟上重建」）且无抹除词 → 不触发。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    terminal_facts: list = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if e.fact_type not in ("event", "relation", "reveal_status"):
                continue
            if any(m in e.statement for m in _TERMINAL_STATE_MARKERS):
                terminal_facts.append(e)

    if not terminal_facts:
        return issues

    known_entities = sorted(
        {eid for f in terminal_facts for eid in f.involved_entities}
    )
    if not known_entities:
        # 无实体注册时用事实陈述中的 2 字片段兜底
        for f in terminal_facts:
            known_entities.extend(seg for seg in _segments(f.statement, 2))
        known_entities = sorted(set(known_entities))

    for f in terminal_facts:
        fact_entities = _fact_entities(f)
        for pu in plotunits:
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _ERASURE_MARKERS):
                continue
            # 需要事实实体出现在同一单元文本中，才判定为「同一现实的抹除」
            hit_entities = _involved_entities(text, fact_entities)
            if not hit_entities:
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_cd_erased_{f.fact_id}_{pu.unit_id}",
                    issue_type="fact_conflict",
                    severity="blocking",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="已发生现实",
                    violated_rule="已终结的既成事实不得被后文无解释地抹除",
                    description=(
                        f"已确认事实『{f.statement}』({f.fact_id}) 已被完成，"
                        f"但 PlotUnit {pu.unit_id} 含抹除/重写语言"
                        f"（{[m for m in _ERASURE_MARKERS if m in text][:3]}）"
                        f"且涉及同一实体 {hit_entities[:3]}——"
                        f"已发生现实被当作从未发生或重新完好。"
                        f"若确有复活/重建/逆转，必须有对应新事件与代价。"
                    ),
                    suggested_fix=(
                        "保留已终结状态；若要改变，需在 plotunit 中写明导致改变的"
                        "具体事件与代价（重建/复活/解禁需对应因果）。"
                    ),
                    supporting_facts=[f.fact_id],
                )
            )
    return _sorted(issues)


def _segments(text: str, length: int) -> list[str]:
    """提取文本中长度 >= length 的中文片段（用于无实体注册时的兜底匹配）. """
    import re

    segs: list[str] = []
    for m in re.findall(r"[一-鿿A-Za-z]{2,}", text or ""):
        seg = m.strip()
        if len(seg) >= length:
            segs.append(seg)
    return segs


# ---------------------------------------------------------------------------
# 检测器 2：已付代价失效（代价未传播 / 无解释恢复）
# ---------------------------------------------------------------------------

def detect_invalidated_cost(objects: list) -> list[ReviewIssue]:
    """已付出的代价（资源/身体/关系/修为）被无解释恢复.

    规则：存在 confirmed 的成本事实（含 _COST_FACT_MARKERS），同一实体后续
    PlotUnit 出现 _RECOVERY_MARKERS 且该 PlotUnit 自身不含新的代价词 → warning
    missing_cost（代价未传播）。若世界有 consequence_logic（代价机制），升级为
    blocking world_violation——世界规则明示代价不可免费逆转。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    worlds = [o for o in objects if isinstance(o, WorldModel)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    cost_facts: list = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if any(m in e.statement for m in _COST_FACT_MARKERS):
                cost_facts.append(e)
    if not cost_facts:
        return issues

    has_cost_mechanism = any(
        w.consequence_logic or w.prohibitions for w in worlds
    )
    severity = "blocking" if has_cost_mechanism else "warning"
    issue_type = "world_violation" if has_cost_mechanism else "missing_cost"

    for f in cost_facts:
        fact_entities = _fact_entities(f)
        for pu in plotunits:
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _RECOVERY_MARKERS):
                continue
            hit_entities = _involved_entities(text, fact_entities)
            if not hit_entities:
                continue
            # 该 PlotUnit 自身若有新的代价支付 → 合法（代价再次被付）
            if any(m in text for m in _NEW_COST_PAYMENT_MARKERS):
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_cd_cost_{f.fact_id}_{pu.unit_id}",
                    issue_type=issue_type,
                    severity=severity,
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="代价机制",
                    violated_rule=(
                        "已付代价不得无解释恢复"
                        if severity == "blocking"
                        else "已付代价应持续传播或需对应代价恢复"
                    ),
                    description=(
                        f"已确认成本事实『{f.statement}』({f.fact_id}) 表明 "
                        f"{hit_entities[:2]} 已付出代价，但 PlotUnit {pu.unit_id} "
                        f"出现恢复语言（{[m for m in _RECOVERY_MARKERS if m in text][:3]}）"
                        f"且无新代价支付——代价被悄悄抵消。"
                        f"世界代价机制: {'存在（升级为阻断）' if has_cost_mechanism else '未声明（质量信号）'}。"
                    ),
                    suggested_fix=(
                        "保持代价的持续影响（资源/身体/关系/权力），或为恢复"
                        "补充新的付出与因果事件。"
                    ),
                    supporting_facts=[f.fact_id],
                )
            )
    return _sorted(issues)


# ---------------------------------------------------------------------------
# 检测器 3：人物成长或知识状态重置
# ---------------------------------------------------------------------------

def detect_growth_reset(objects: list) -> list[ReviewIssue]:
    """已形成的成长/已接受的事实被重置为默认.

    规则：CharacterModel 有已确认成长（change_trajectory 非空 或 arc_stage
    已进阶 或 self_image 已建立），同一角色参与的 PlotUnit 含 _RESET_MARKERS
    且无回退事件 → warning character_distortion。
    """
    issues: list[ReviewIssue] = []
    characters = [o for o in objects if isinstance(o, CharacterModel)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not characters or not plotunits:
        return issues

    for cm in characters:
        has_growth = bool(cm.change_trajectory) or bool(cm.arc_stage) or bool(cm.self_image)
        if not has_growth:
            continue
        growth_hint = (
            (cm.change_trajectory[0] if cm.change_trajectory else "")
            or (cm.arc_stage or "")
            or (cm.self_image or "")
        )
        for pu in plotunits:
            if cm.character_id not in pu.participants:
                continue
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _RESET_MARKERS):
                continue
            # participants 已证明角色在本单元在场；重置语言即针对该角色的成长
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_cd_growth_{cm.character_id}_{pu.unit_id}",
                    issue_type="character_distortion",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="人物成长连续性",
                    violated_rule="已形成的成长/认知不得被无事件地重置",
                    description=(
                        f"角色 '{cm.name}' 已有成长记录"
                        f"（{growth_hint[:60]}），但 PlotUnit {pu.unit_id} 出现"
                        f"重置语言（{[m for m in _RESET_MARKERS if m in text][:3]}）"
                        f"且无回退事件——人物被悄悄打回原形。"
                        f"若确实发生倒退，必须有对应事件（新的打击/背叛/失败）。"
                    ),
                    suggested_fix=(
                        "保留成长轨迹；倒退必须由可见事件驱动，并在 change_trajectory"
                        "记录『倒退』而非删除既有成长。"
                    ),
                    affected_threads=[],
                )
            )
    return _sorted(issues)


# ---------------------------------------------------------------------------
# 检测器 4：制度与群体后果未传播
# ---------------------------------------------------------------------------

def detect_group_consequence_unpropagated(objects: list) -> list[ReviewIssue]:
    """已发生的制度性公开事件（法令/战争/通缉/查封）未影响后续角色策略.

    规则：存在已确认制度性事实（含 _INSTITUTIONAL_MARKERS），其后 PlotUnit 涉及
    同一实体（或世界势力）但完全没有策略/后果响应（无 _STRATEGY_SPACE_MARKERS、
    无代价、无反应）→ warning world_violation（制度改变被局部化，未进入社会层）。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    institutional_facts: list = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if any(m in e.statement for m in _INSTITUTIONAL_MARKERS):
                institutional_facts.append(e)
    if not institutional_facts:
        return issues

    for f in institutional_facts:
        fact_entities = _fact_entities(f)
        for pu in plotunits:
            text = _plotunit_text(pu)
            if not text:
                continue
            hit_entities = _involved_entities(text, fact_entities)
            if not hit_entities:
                continue
            # 有策略/代价/反应 → 后果已传播，不触发
            if any(m in text for m in _STRATEGY_SPACE_MARKERS):
                continue
            if any(m in text for m in _COST_FACT_MARKERS):
                continue
            if any(m in text for m in ("避", "逃", "藏", "忌惮", "不得不", "被迫")):
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_cd_inst_{f.fact_id}_{pu.unit_id}",
                    issue_type="world_violation",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="制度与群体后果传播",
                    violated_rule="已发生的制度性公开事件应影响相关角色策略",
                    description=(
                        f"已确认制度事件『{f.statement}』({f.fact_id}) 已发生，"
                        f"但 PlotUnit {pu.unit_id} 涉及相关实体 {hit_entities[:2]} "
                        f"却无任何策略/代价/反应——制度改变被局部化为单场景，"
                        f"未进入社会层状态。若该单元确在事件之前或无关，请忽略。"
                    ),
                    suggested_fix=(
                        "让制度后果进入后续角色策略（规避/配合/反抗/改变计划），"
                        "或把单元时间点明确置于事件之前。"
                    ),
                    supporting_facts=[f.fact_id],
                )
            )
    return _sorted(issues)


# ---------------------------------------------------------------------------
# 检测器 5：已有选择没有改变后续策略空间（质量信号）
# ---------------------------------------------------------------------------

def detect_choice_no_future_impact(objects: list) -> list[ReviewIssue]:
    """声称的重大选择没有改变后续策略空间.

    规则：PlotUnit 含重大选择触发词（_CHOICE_TRIGGERS），但其 consequences 为空
    且输入/输出 NarrativeState 在策略相关字段（active_conflicts / current_goals /
    hidden_information / active_suspense_items）完全无变化 → warning weak_progression
    （该选择对后续没有任何可核对影响——删除它故事可能不变）。
    """
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    states = {ns.state_id: ns for ns in objects if isinstance(ns, NarrativeState)}
    if not plotunits:
        return issues

    for pu in plotunits:
        text = _plotunit_text(pu)
        if not any(m in text for m in _CHOICE_TRIGGERS):
            continue
        # 若已有后果或状态变化摘要，视为有影响
        if pu.consequences or pu.state_change_summary:
            continue
        in_state = states.get(pu.input_state_ref)
        out_state = states.get(pu.output_state_ref)
        if in_state is None or out_state is None:
            continue
        strategy_changed = any(
            _strategy_field_changed(in_state, out_state)
            for _ in [0]
        )
        if strategy_changed:
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_cd_noimpact_{pu.unit_id}",
                issue_type="weak_progression",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="选择对后续策略空间的影响",
                violated_rule="重大选择应改变未来策略空间（资源/关系/风险/最优行动）",
                description=(
                    f"PlotUnit {pu.unit_id} 声称做出选择"
                    f"（{[m for m in _CHOICE_TRIGGERS if m in text][:3]}），"
                    f"但无 consequences、无状态变化摘要，且输入/输出 NarrativeState "
                    f"在策略相关字段（冲突/目标/隐藏信息/悬念）上无差异——"
                    f"删除该选择后故事可能完全不变。"
                ),
                suggested_fix=(
                    "为该选择补充实际后果：改变可用资源、关系、风险或世界响应；"
                    "或把该单元降级为非选择单元。"
                ),
            )
        )
    return _sorted(issues)


def _strategy_field_changed(a: NarrativeState, b: NarrativeState) -> bool:
    """比较两个 NarrativeState 的策略相关字段是否变化. """
    return any(
        (
            list(getattr(a, field, []) or []) != list(getattr(b, field, []) or [])
        )
        for field in (
            "active_conflicts",
            "current_goals",
            "hidden_information",
            "active_suspense_items",
            "open_questions",
        )
    )


# ---------------------------------------------------------------------------
# 聚合入口
# ---------------------------------------------------------------------------

# 检测器注册表：固定顺序（与文档一致；排序保证输出顺序无关）。
CAUSAL_DETECTORS: tuple[callable, ...] = (
    detect_erased_committed_event,
    detect_invalidated_cost,
    detect_growth_reset,
    detect_group_consequence_unpropagated,
    detect_choice_no_future_impact,
)


def run_causal_defense(objects: list) -> list[ReviewIssue]:
    """运行全部长程因果检测器，汇总 issue（去重、按 severity+issue_id 排序）.

    幂等：纯函数，重复调用返回相同结果。顺序无关：排序保证输出稳定。
    """
    seen: dict[str, ReviewIssue] = {}
    for detector in CAUSAL_DETECTORS:
        for issue in detector(objects):
            seen.setdefault(issue.issue_id, issue)
    return sorted(
        seen.values(),
        key=lambda i: (0 if i.is_blocking() else 1, i.issue_id),
    )


def _sorted(issues: list[ReviewIssue]) -> list[ReviewIssue]:
    """按 (blocking, issue_id) 排序，保证输出顺序稳定（顺序无关）. """
    return sorted(
        issues,
        key=lambda i: (0 if i.is_blocking() else 1, i.issue_id),
    )
