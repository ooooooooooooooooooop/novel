"""causal_defense — 长程因果防线（P1 / R4 整改）.

把系统从「检测局部事实矛盾」升级为「阻止已发生现实、已付代价和已形成成长
被后文悄悄抹掉」。覆盖五类失败模式：

  1. 已完成事件被重写（抹掉已发生现实）
  2. 已付代价失效（代价未传播/无解释恢复）
  3. 人物成长或知识状态重置（成长/已接受事实被抹掉）
  4. 制度与群体后果未传播（制度改变不影响后续策略）
  5. 已有选择未改变后续策略空间（质量信号）

R4 整改规则：
- 对比「当前候选发生前」已成立事实 (established_at_chapter / valid_from 叙事时间线校验)；
- 废除模糊2字重叠，使用实体 alias registry 与明确 rule/fact 链接；
- Reader Gate 路由映射：硬冲突 -> block，质量缺陷 -> rewrite，禁止直接 pass。
"""

from __future__ import annotations

import re
from typing import Optional, Set

from src.object_state import (
    CausalRule,
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    TimelineResolution,
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
        "被废", "被夺", "断臂", "失明", "废了", "反噬", "透支", "残疾", "尽断",
        "残废", "损毁", "碎裂", "自损",
    )
)

# 新的代价支付动词（仅当恢复句本身出现这些才视为「为恢复再次付代价」）。
_NEW_COST_PAYMENT_MARKERS: frozenset[str] = frozenset(
    (
        "付出", "支付", "牺牲", "耗费", "倾尽", "花费", "抵押", "献祭", "重金",
        "以命相搏", "自损",
    )
)

# 无代价恢复语言：资源/能力/关系被无解释恢复。
_RECOVERY_MARKERS: frozenset[str] = frozenset(
    (
        "恢复", "复原", "康复", "痊愈", "重新拥有", "失而复得", "完好如初",
        "恢复如初", "重新获得", "拿回", "夺回", "又有了", "回归", "重新站起",
        "重新行走",
    )
)

# 成长/认知确认词（已形成成长或已接受事实）。
_GROWTH_MARKERS: frozenset[str] = frozenset(
    (
        "成长", "转变", "学会", "明白", "接受", "放下", "克服", "突破",
        "愿意托付", "不再逃避", "敢于", "承担", "信任",
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
# 实体别名注册表 (EntityAliasRegistry)
# ---------------------------------------------------------------------------

class EntityAliasRegistry:
    """实体别名注册表：集中注册角色、地点、势力、物品的规范 ID 与别名，消除模糊 2 字切片误报."""

    def __init__(self, objects: list):
        self.alias_to_id: dict[str, str] = {}
        self.id_to_aliases: dict[str, set[str]] = {}
        self._build(objects)

    def _build(self, objects: list) -> None:
        for obj in objects:
            if isinstance(obj, CharacterModel):
                cid = obj.character_id
                self._register(cid, cid)
                if obj.name:
                    self._register(cid, obj.name)
                for alias in getattr(obj, "aliases", []):
                    self._register(cid, alias)
            elif isinstance(obj, FactLedger):
                for entry in obj.entries:
                    for eid in entry.involved_entities:
                        if eid:
                            self._register(eid, eid)
                    # 提取事实陈述中的规范实体词
                    self._extract_statement_entities(entry.statement)
            elif isinstance(obj, WorldModel):
                for prohibition in obj.prohibitions or []:
                    self._extract_statement_entities(prohibition)
                for cl in obj.consequence_logic or []:
                    self._extract_statement_entities(cl)
                for hr in obj.hard_rules or []:
                    self._extract_statement_entities(hr)

    def _extract_statement_entities(self, statement: str) -> None:
        """从陈述中提取主语/专有名词（如'古堡'、'张三'、'李四'、'王城'）."""
        if not statement:
            return
        # 匹配中文专有名词/地名/人名
        for m in re.finditer(r"([一-龥]{2,6})(?:已被|已被焚毁|已被毁|失去|透支|下达|开战|被夺|已被逐)", statement):
            noun = m.group(1).strip()
            if noun:
                self._register(noun, noun)

    def _register(self, entity_id: str, alias: str) -> None:
        if not alias or not alias.strip():
            return
        alias = alias.strip()
        self.alias_to_id[alias] = entity_id
        self.id_to_aliases.setdefault(entity_id, set()).add(alias)

    def get_aliases_for_entity(self, entity_id: str) -> set[str]:
        return self.id_to_aliases.get(entity_id, {entity_id} if entity_id else set())

    def match_entities_in_text(self, text: str, target_entities: Optional[set[str]] = None) -> list[str]:
        """精确匹配文本中出现的已知实体别名（杜绝模糊 2 字切片）."""
        hits: list[str] = []
        if not text:
            return hits
        for alias, eid in self.alias_to_id.items():
            if target_entities is not None:
                # 检查 target_entities 是否包含 eid 或 alias 本身
                if eid not in target_entities and alias not in target_entities:
                    continue
            if len(alias) >= 2 and alias in text:
                hits.append(alias)
        return sorted(set(hits))


# ---------------------------------------------------------------------------
# 叙事时间线约束与工具
# ---------------------------------------------------------------------------

_CN_NUMS: dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
}


def _cn_to_int(cn_str: str) -> Optional[int]:
    if not cn_str:
        return None
    if cn_str.isdigit():
        return int(cn_str)
    total = 0
    curr = 0
    for char in cn_str:
        val = _CN_NUMS.get(char)
        if val is None:
            continue
        if val == 10:
            if curr == 0:
                curr = 1
            total += curr * 10
            curr = 0
        elif val == 100:
            total += curr * 100
            curr = 0
        else:
            curr = val
    total += curr
    return total if total > 0 else None


def _parse_chapter_num(val: Optional[str]) -> Optional[int]:
    """从文本中解析章节序号（支持阿拉伯数字与中文数字，如'第5章'、'第二章'、'chapter_2'、'pu_ch2_01'）."""
    if not val:
        return None
    s = str(val).strip()
    m_cn = re.search(r"第([零一二两三四五六七八九十百\d]+)章", s)
    if m_cn:
        num = _cn_to_int(m_cn.group(1))
        if num is not None:
            return num
    m_cn2 = re.search(r"([零一二两三四五六七八九十百\d]+)章", s)
    if m_cn2:
        num = _cn_to_int(m_cn2.group(1))
        if num is not None:
            return num
    m_ch = re.search(r"ch(?:apter)?[_\-]?(\d+)", s, re.IGNORECASE)
    if m_ch:
        return int(m_ch.group(1))
    return None


def resolve_narrative_timeline(fact: FactEntry, pu: PlotUnit, objects: list) -> TimelineResolution:
    """校验事实与情节单元的时间线前后序 (Narrative Chronology & Degradation).

    返回 TimelineResolution, 包含 established 状态与 unreviewable 降级判定.
    """
    pu_chapter = _parse_chapter_num(pu.unit_id) or _parse_chapter_num(pu.input_state_ref)
    if pu_chapter is None:
        for obj in objects:
            if isinstance(obj, NarrativeState):
                pu_chapter = _parse_chapter_num(obj.current_time) or _parse_chapter_num(obj.state_id)
                if pu_chapter is not None:
                    break

    # 1. 检查事实的有效起点 valid_from / timestamp / source_plotunit
    fact_start_chapter = None
    if fact.validity_interval and fact.validity_interval.valid_from:
        fact_start_chapter = _parse_chapter_num(fact.validity_interval.valid_from)
    elif fact.timestamp:
        fact_start_chapter = _parse_chapter_num(fact.timestamp)
    elif fact.source_plotunit:
        fact_start_chapter = _parse_chapter_num(fact.source_plotunit)

    # 2. 显式未来事实
    if pu_chapter is not None and fact_start_chapter is not None and fact_start_chapter > pu_chapter:
        return TimelineResolution(
            established=False,
            status="future_fact",
            fact_chapter=fact_start_chapter,
            pu_chapter=pu_chapter,
            notes=[f"事实在第 {fact_start_chapter} 章生效，晚于当前单元第 {pu_chapter} 章"],
        )

    # 3. 显式失效事实
    if fact.validity_interval and fact.validity_interval.valid_until and pu_chapter is not None:
        fact_end_chapter = _parse_chapter_num(fact.validity_interval.valid_until)
        if fact_end_chapter is not None and pu_chapter > fact_end_chapter:
            return TimelineResolution(
                established=False,
                status="expired",
                fact_chapter=fact_start_chapter,
                pu_chapter=pu_chapter,
                notes=[f"事实在第 {fact_end_chapter} 章失效，早于当前单元第 {pu_chapter} 章"],
            )

    # 4. 双方均有确凿章节序号，且事实 <= pu
    if pu_chapter is not None and fact_start_chapter is not None:
        return TimelineResolution(
            established=True,
            status="resolved",
            fact_chapter=fact_start_chapter,
            pu_chapter=pu_chapter,
            notes=[f"事实在第 {fact_start_chapter} 章生效，有效约束当前第 {pu_chapter} 章"],
        )

    # 5. 事实包含相对时间顺序标注
    if fact.chronological_order:
        if any(w in fact.chronological_order for w in ("之前", "早于", "前置", "前")):
            return TimelineResolution(
                established=True,
                status="resolved",
                fact_chapter=fact_start_chapter,
                pu_chapter=pu_chapter,
                notes=[fact.chronological_order],
            )
        elif any(w in fact.chronological_order for w in ("之后", "晚于", "后续", "后")):
            return TimelineResolution(
                established=False,
                status="future_fact",
                fact_chapter=fact_start_chapter,
                pu_chapter=pu_chapter,
                notes=[fact.chronological_order],
            )
        elif any(w in fact.chronological_order for w in ("未决", "待定", "未知", "unreviewable", "不确定")):
            return TimelineResolution(
                established=None,
                status="unreviewable",
                fact_chapter=fact_start_chapter,
                pu_chapter=pu_chapter,
                notes=["时序标注为未决/未知，降级为 unreviewable"],
            )

    # 6. 未确认事实 -> 降级为 unreviewable
    if not getattr(fact, "confirmed", False):
        return TimelineResolution(
            established=None,
            status="unreviewable",
            fact_chapter=fact_start_chapter,
            pu_chapter=pu_chapter,
            notes=["事实未确认且时间线无法判定前后序，降级为 unreviewable"],
        )

    # 7. 事实已确认且未声明冲突 -> resolved
    return TimelineResolution(
        established=True,
        status="resolved",
        fact_chapter=fact_start_chapter,
        pu_chapter=pu_chapter,
        notes=["事实已确认且未声明未来/失效区间"],
    )


def _is_fact_established_before_or_at(fact: FactEntry, pu: PlotUnit, objects: list) -> bool:
    """向下兼容的布尔校验函数."""
    res = resolve_narrative_timeline(fact, pu, objects)
    return res.established is True


def extract_world_causal_rules(objects: list) -> dict[str, CausalRule]:
    """从 WorldModel 与传入对象中提取强类型 CausalRule 字典 (rule_id -> CausalRule)."""
    rules: dict[str, CausalRule] = {}
    worlds = [o for o in objects if isinstance(o, WorldModel)]

    # 直接传入的 CausalRule 对象
    for o in objects:
        if isinstance(o, CausalRule):
            rules[o.rule_id] = o

    _KW_APPLIES = ("修为", "灵力", "本源", "经脉", "生死", "命", "灵魂", "寿元", "生命", "资源", "灵石", "法宝", "禁术", "透支", "神识", "肉身", "气血", "丹药")
    for w in worlds:
        for idx, r in enumerate(w.hard_rules or []):
            rid = f"hard_rule_{idx+1}"
            cost_type = "general"
            if any(k in r for k in ("生死", "命", "亡", "死", "寿元", "生命", "灵魂")):
                cost_type = "life"
            elif any(k in r for k in ("修为", "灵力", "本源", "经脉", "透支", "禁术")):
                cost_type = "cultivation"
            elif any(k in r for k in ("资源", "灵石", "法宝", "财")):
                cost_type = "resource"
            elif any(k in r for k in ("断臂", "失明", "残疾", "肉身", "气血")):
                cost_type = "body"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="hard_rule",
                statement=r,
                applies_to=[k for k in _KW_APPLIES if k in r],
                cost_type=cost_type,
                reversibility="irreversible",
            )
        for idx, r in enumerate(w.consequence_logic or []):
            rid = f"consequence_logic_{idx+1}"
            cost_type = "general"
            if any(k in r for k in ("生死", "命", "亡", "死", "寿元", "生命", "灵魂")):
                cost_type = "life"
            elif any(k in r for k in ("修为", "灵力", "本源", "经脉", "透支", "禁术")):
                cost_type = "cultivation"
            elif any(k in r for k in ("资源", "灵石", "法宝", "财")):
                cost_type = "resource"
            elif any(k in r for k in ("断臂", "失明", "残疾", "肉身", "气血")):
                cost_type = "body"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="consequence_logic",
                statement=r,
                applies_to=[k for k in _KW_APPLIES if k in r],
                cost_type=cost_type,
                reversibility="conditional",
            )
        for idx, r in enumerate(w.prohibitions or []):
            rid = f"prohibition_{idx+1}"
            cost_type = "general"
            if any(k in r for k in ("生死", "命", "亡", "死", "寿元", "生命", "灵魂")):
                cost_type = "life"
            elif any(k in r for k in ("修为", "灵力", "本源", "经脉", "透支", "禁术")):
                cost_type = "cultivation"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="prohibition",
                statement=r,
                applies_to=[k for k in _KW_APPLIES if k in r],
                cost_type=cost_type,
                reversibility="forbidden",
            )
        for idx, r in enumerate(w.forbidden_actions or []):
            rid = f"forbidden_action_{idx+1}"
            cost_type = "general"
            if any(k in r for k in ("生死", "命", "亡", "死", "寿元", "生命", "灵魂")):
                cost_type = "life"
            elif any(k in r for k in ("修为", "灵力", "本源", "经脉", "透支", "禁术")):
                cost_type = "cultivation"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="forbidden_action",
                statement=r,
                applies_to=[k for k in _KW_APPLIES if k in r],
                cost_type=cost_type,
                reversibility="forbidden",
            )
        if getattr(w, "death_rule", None):
            rid = "death_rule_1"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="death_rule",
                statement=str(w.death_rule),
                applies_to=["死亡", "灵魂"],
                cost_type="life",
                reversibility="strict_irreversible",
            )
        if getattr(w, "resource_system", None):
            rid = "resource_system_1"
            rules[rid] = CausalRule(
                rule_id=rid,
                rule_type="resource_system",
                statement=str(w.resource_system),
                applies_to=["资源"],
                cost_type="resource",
                reversibility="conservation_of_cost",
            )
    return rules


def _plotunit_text(pu: PlotUnit) -> str:
    """拼接 PlotUnit 的信息承载字段."""
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


def _confirmed_facts(ledger: FactLedger) -> list[FactEntry]:
    """已确认事实列表."""
    return [e for e in ledger.entries if e.confirmed]


def _fact_entity_set(fact: FactEntry, registry: EntityAliasRegistry) -> set[str]:
    """获取事实涉及的完整实体与别名集合."""
    entities: set[str] = set()
    for eid in fact.involved_entities or []:
        if eid:
            entities.add(eid)
            entities.update(registry.get_aliases_for_entity(eid))
    # 从陈述中匹配已知实体
    matched = registry.match_entities_in_text(fact.statement)
    entities.update(matched)
    return entities


# ---------------------------------------------------------------------------
# 检测器 1：已完成事件被重写（抹掉已发生现实）
# ---------------------------------------------------------------------------

def detect_erased_committed_event(objects: list) -> list[ReviewIssue]:
    """已确认的终结性事实（死亡/焚毁/公开/交出）被草案以「恢复/重写」语言抹掉.

    规则：存在 confirmed 的终结性事实（含 _TERMINAL_STATE_MARKERS 且为
    event/relation/reveal_status 类型），经时间线校验已成立；同一实体的 PlotUnit
    草案含 _ERASURE_MARKERS 且无新事件解释 → blocking fact_conflict。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    registry = EntityAliasRegistry(objects)

    terminal_facts: list[FactEntry] = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if e.fact_type not in ("event", "relation", "reveal_status"):
                continue
            if any(m in e.statement for m in _TERMINAL_STATE_MARKERS):
                terminal_facts.append(e)

    if not terminal_facts:
        return issues

    for f in terminal_facts:
        f_entities = _fact_entity_set(f, registry)
        for pu in plotunits:
            timeline_res = resolve_narrative_timeline(f, pu, objects)
            if timeline_res.established is False or timeline_res.status == "unreviewable":
                continue
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _ERASURE_MARKERS):
                continue
            hit_entities = registry.match_entities_in_text(text, f_entities)
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
                        f"且涉及实体 {hit_entities[:3]}——"
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


# ---------------------------------------------------------------------------
# 检测器 2：已付代价失效（代价未传播 / 无解释恢复）
# ---------------------------------------------------------------------------

def detect_invalidated_cost(objects: list) -> list[ReviewIssue]:
    """已付出的代价（资源/身体/关系/修为）被无解释恢复.

    规则：存在 confirmed 的成本事实（含 _COST_FACT_MARKERS），经时间线校验已成立；
    同一实体后续 PlotUnit 出现 _RECOVERY_MARKERS 且该 PlotUnit 自身不含新的代价词。
    若世界有 consequence_logic / prohibitions 约束，升级为 blocking world_violation
    并明确绑定 rule；否则为 warning missing_cost。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    worlds = [o for o in objects if isinstance(o, WorldModel)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    registry = EntityAliasRegistry(objects)

    cost_facts: list[FactEntry] = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if any(m in e.statement for m in _COST_FACT_MARKERS):
                cost_facts.append(e)
    if not cost_facts:
        return issues

    causal_rules = extract_world_causal_rules(objects)

    for f in cost_facts:
        f_entities = _fact_entity_set(f, registry)
        for pu in plotunits:
            timeline_res = resolve_narrative_timeline(f, pu, objects)
            if timeline_res.established is False:
                continue
            if timeline_res.status == "unreviewable":
                continue
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _RECOVERY_MARKERS):
                continue
            hit_entities = registry.match_entities_in_text(text, f_entities)
            if not hit_entities:
                continue
            # 该 PlotUnit 自身若有新的代价支付 → 合法
            if any(m in text for m in _NEW_COST_PAYMENT_MARKERS):
                continue

            # 确定事实本身的代价类型
            f_cost_type = "general"
            if any(k in f.statement for k in ("生死", "命", "亡", "死", "寿元", "生命", "灵魂")):
                f_cost_type = "life"
            elif any(k in f.statement for k in ("修为", "灵力", "本源", "经脉", "透支", "禁术")):
                f_cost_type = "cultivation"
            elif any(k in f.statement for k in ("资源", "灵石", "法宝", "财")):
                f_cost_type = "resource"
            elif any(k in f.statement for k in ("断臂", "失明", "残疾", "肉身", "气血")):
                f_cost_type = "body"

            # 结构化绑定: FactEntry.cost_rule_id -> CausalRule.rule_id -> applies_to -> cost_type -> reversibility
            matching_rule: Optional[CausalRule] = None
            if f.cost_rule_id and f.cost_rule_id in causal_rules:
                matching_rule = causal_rules[f.cost_rule_id]
            else:
                # 1. 实体或关键词精准匹配
                for r in causal_rules.values():
                    if any(e in r.applies_to for e in hit_entities) or any(e in r.statement for e in hit_entities):
                        matching_rule = r
                        break
                # 2. 领域代价类型匹配 (life/cultivation/resource/body 且非通用 general)
                if matching_rule is None and f_cost_type != "general":
                    for r in causal_rules.values():
                        if r.cost_type == f_cost_type:
                            matching_rule = r
                            break

            # 严禁任何无关联规则兜底！未匹配规则时作为质量信号 (warning / missing_cost)
            has_hard_rule = False
            severity = "warning"
            issue_type = "missing_cost"
            violated_rule_str = "已付代价应持续传播或需对应代价恢复"
            mechanism_desc = "未声明硬规则（质量信号）"

            if matching_rule is not None:
                rule_id = matching_rule.rule_id
                rule_text = matching_rule.statement
                reversibility = matching_rule.reversibility
                cost_type = matching_rule.cost_type
                applies_to_str = ", ".join(matching_rule.applies_to or hit_entities[:2])

                # 严格执行可逆性模式 (Strict enforcement of reversibility modes)
                if reversibility in ("irreversible", "strict_irreversible", "forbidden"):
                    has_hard_rule = True
                    severity = "blocking"
                    issue_type = "world_violation"
                    violated_rule_str = (
                        f"世界代价规则不可逆转 [rule_id={rule_id}, applies_to={applies_to_str}, "
                        f"cost_type={cost_type}, reversibility={reversibility}]: {rule_text}"
                    )
                    mechanism_desc = f"绑定世界不可逆规则 {rule_id} (applies_to={applies_to_str}, cost_type={cost_type}, reversibility={reversibility}, 严格阻断)"
                elif reversibility == "conditional":
                    reqs = getattr(matching_rule, "reversal_requirements", []) or []
                    if reqs and any(req in text for req in reqs):
                        # 满足逆转前置条件，合法逆转，不报警
                        continue
                    has_hard_rule = True
                    severity = "blocking"
                    issue_type = "world_violation"
                    req_hint = f"（需满足前置条件: {', '.join(reqs)}）" if reqs else "（未满足逆转条件）"
                    violated_rule_str = (
                        f"世界代价规则条件可逆未满足 [rule_id={rule_id}, applies_to={applies_to_str}, "
                        f"cost_type={cost_type}, reversibility={reversibility}]: {rule_text} {req_hint}"
                    )
                    mechanism_desc = f"绑定世界条件可逆规则 {rule_id} (未满足逆转条件，阻断)"
                elif reversibility == "conservation_of_cost":
                    has_hard_rule = True
                    severity = "blocking"
                    issue_type = "world_violation"
                    violated_rule_str = (
                        f"世界代价规则守恒未满足 [rule_id={rule_id}, applies_to={applies_to_str}, "
                        f"cost_type={cost_type}, reversibility={reversibility}]: {rule_text}（未支付等价新代价）"
                    )
                    mechanism_desc = f"绑定世界代价守恒规则 {rule_id} (未支付等价新代价，阻断)"
                else:
                    has_hard_rule = (matching_rule.rule_type in ("hard_rule", "prohibition", "death_rule"))
                    severity = "blocking" if has_hard_rule else "warning"
                    issue_type = "world_violation" if has_hard_rule else "missing_cost"
                    violated_rule_str = (
                        f"世界代价规则 [rule_id={rule_id}, applies_to={applies_to_str}, "
                        f"cost_type={cost_type}, reversibility={reversibility}]: {rule_text}"
                    )
                    mechanism_desc = f"绑定世界规则 {rule_id}"

            issues.append(
                ReviewIssue(
                    issue_id=f"iss_cd_cost_{f.fact_id}_{pu.unit_id}",
                    issue_type=issue_type,
                    severity=severity,
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="代价机制",
                    violated_rule=violated_rule_str,
                    description=(
                        f"已确认成本事实『{f.statement}』({f.fact_id}) 表明 "
                        f"{hit_entities[:2]} 已付出代价，但 PlotUnit {pu.unit_id} "
                        f"出现恢复语言（{[m for m in _RECOVERY_MARKERS if m in text][:3]}）"
                        f"且无新代价支付——代价被悄悄抵消。"
                        f"世界代价机制: {mechanism_desc}。"
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

    registry = EntityAliasRegistry(objects)

    for cm in characters:
        has_growth = bool(cm.change_trajectory) or bool(cm.arc_stage) or bool(cm.self_image)
        if not has_growth:
            continue
        growth_hint = (
            (cm.change_trajectory[0] if cm.change_trajectory else "")
            or (cm.arc_stage or "")
            or (cm.self_image or "")
        )
        cm_aliases = registry.get_aliases_for_entity(cm.character_id)

        for pu in plotunits:
            is_participant = (
                cm.character_id in pu.participants
                or any(p in cm_aliases for p in pu.participants)
            )
            if not is_participant:
                continue
            text = _plotunit_text(pu)
            if not text:
                continue
            if not any(m in text for m in _RESET_MARKERS):
                continue
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

    规则：存在已确认制度性事实（含 _INSTITUTIONAL_MARKERS），经时间线校验已成立；
    其后 PlotUnit 涉及同一实体但完全没有策略/后果响应 → warning world_violation。
    """
    issues: list[ReviewIssue] = []
    ledgers = [o for o in objects if isinstance(o, FactLedger)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    if not ledgers or not plotunits:
        return issues

    registry = EntityAliasRegistry(objects)

    institutional_facts: list[FactEntry] = []
    for ledger in ledgers:
        for e in _confirmed_facts(ledger):
            if any(m in e.statement for m in _INSTITUTIONAL_MARKERS):
                institutional_facts.append(e)
    if not institutional_facts:
        return issues

    for f in institutional_facts:
        f_entities = _fact_entity_set(f, registry)
        for pu in plotunits:
            timeline_res = resolve_narrative_timeline(f, pu, objects)
            if timeline_res.established is False or timeline_res.status == "unreviewable":
                continue
            text = _plotunit_text(pu)
            if not text:
                continue
            hit_entities = registry.match_entities_in_text(text, f_entities)
            if not hit_entities:
                continue
            # 有策略/代价/反应 → 后果已传播，不触发
            if any(m in text for m in _STRATEGY_SPACE_MARKERS):
                continue
            if any(m in text for m in _COST_FACT_MARKERS):
                continue
            if any(m in text for m in ("避", "逃", "藏", "忌惮", "不得不", "被迫", "戒备")):
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
    hidden_information / active_suspense_items）完全无变化 → warning weak_progression。
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
        strategy_changed = _strategy_field_changed(in_state, out_state)
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
    """比较两个 NarrativeState 的策略相关字段是否变化."""
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

CAUSAL_DETECTORS: tuple[callable, ...] = (
    detect_erased_committed_event,
    detect_invalidated_cost,
    detect_growth_reset,
    detect_group_consequence_unpropagated,
    detect_choice_no_future_impact,
)


def run_causal_defense(objects: list) -> list[ReviewIssue]:
    """运行全部长程因果检测器，汇总 issue（去重、按 severity+issue_id 排序）."""
    seen: dict[str, ReviewIssue] = {}
    for detector in CAUSAL_DETECTORS:
        for issue in detector(objects):
            seen.setdefault(issue.issue_id, issue)
    return sorted(
        seen.values(),
        key=lambda i: (0 if i.is_blocking() else 1, i.issue_id),
    )


def _sorted(issues: list[ReviewIssue]) -> list[ReviewIssue]:
    """按 (blocking, issue_id) 排序，保证输出顺序稳定."""
    return sorted(
        issues,
        key=lambda i: (0 if i.is_blocking() else 1, i.issue_id),
    )
