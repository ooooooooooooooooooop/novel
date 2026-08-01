"""ReconcileUnit — 跨章节对象合并."""

import re
from typing import Optional

from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    WorkSpec,
    WorldModel,
)


_CN_NUMERALS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_to_int(s: str) -> Optional[int]:
    """把常见中文数字串转为整数 (支持 一~十 及 十/十一/二十三 等). 失败返回 None."""
    s = s.strip()
    if not s:
        return None
    if s in _CN_NUMERALS:
        return _CN_NUMERALS[s]
    if "十" in s:
        parts = s.split("十")
        if len(parts) != 2:
            return None
        tens = _CN_NUMERALS.get(parts[0]) if parts[0] else 1
        ones = _CN_NUMERALS.get(parts[1]) if parts[1] else 0
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _narrative_position(value: Optional[str]) -> Optional[int]:
    """把叙事时间标识解析为可比较的位置.

    支持 '第三章'/'第3章'/'第3回'/'第十二章' 及纯数字; 无法解析返回 None(不可比).
    """
    if value is None:
        return None
    s = str(value).strip()
    m = re.search(r"第\s*([0-9０-９]+|[一二两三四五六七八九十]+)\s*[章回节]", s)
    if m:
        num = m.group(1)
        if num.isdigit():
            return int(num)
        return _cn_to_int(num)
    if s.isdigit():
        return int(s)
    return None


def _position_after(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    """a 是否严格晚于 b. 任一侧不可比返回 None."""
    pa = _narrative_position(a)
    pb = _narrative_position(b)
    if pa is None or pb is None:
        return None
    return pa > pb


def _bounds_overlap(
    a_from: Optional[str],
    a_until: Optional[str],
    b_from: Optional[str],
    b_until: Optional[str],
) -> bool:
    """两个时间区间是否重叠.

    None 边界视为无界. 只有两侧都可比且能证明严格不相交时才返回 False,
    否则保守返回 True(避免误报).
    """
    a_until_p = _narrative_position(a_until)
    b_from_p = _narrative_position(b_from)
    if a_until_p is not None and b_from_p is not None and a_until_p < b_from_p:
        return False
    b_until_p = _narrative_position(b_until)
    a_from_p = _narrative_position(a_from)
    if b_until_p is not None and a_from_p is not None and b_until_p < a_from_p:
        return False
    return True


def _from(entry: FactEntry) -> Optional[str]:
    """取事实的有效起点(无 interval 时回退 timestamp)."""
    if entry.validity_interval is not None:
        return entry.validity_interval.valid_from
    return entry.timestamp


def _until(entry: FactEntry) -> Optional[str]:
    """取事实的有效终点(无 interval 时回退 timestamp)."""
    if entry.validity_interval is not None:
        return entry.validity_interval.valid_until
    return entry.timestamp


def _statements_conflict(a: str, b: str) -> bool:
    """判断两条事实陈述是否构成否定冲突.

    处理 'X' vs '不X/未X/没X/不是X' 及 'X 不在/不拥有/未持有' 等形态:
    否定词可插在句首或句中, 移除否定词后核心陈述相同即视为冲突.
    同极(都含或都不含否定词)不冲突.
    """
    a_strip = a.strip()
    b_strip = b.strip()
    if a_strip == b_strip:
        return False
    for neg in ("不", "未", "没", "没有", "不是"):
        a_has = neg in a_strip
        b_has = neg in b_strip
        if a_has == b_has:
            continue
        if a_strip.replace(neg, "") == b_strip.replace(neg, ""):
            return True
    return False


class ReconcileUnit:
    """将多章 Rebuild 输出的局部对象合并为全局对象."""

    def reconcile(self, chapter_objects: list[list]) -> tuple[list, list[str]]:
        """合并多章对象.

        Args:
            chapter_objects: 每章的 Rebuild 输出对象列表，按章节顺序。

        Returns:
            (合并后的全局对象列表, 合并过程中发现的 issues)
        """
        issues: list[str] = []

        workspecs = []
        worldmodels = []
        characters = []
        states = []
        ledgers = []
        graphs = []

        for ch_idx, objects in enumerate(chapter_objects, 1):
            for obj in objects:
                if isinstance(obj, WorkSpec):
                    workspecs.append((ch_idx, obj))
                elif isinstance(obj, WorldModel):
                    worldmodels.append((ch_idx, obj))
                elif isinstance(obj, CharacterModel):
                    characters.append((ch_idx, obj))
                elif isinstance(obj, NarrativeState):
                    states.append((ch_idx, obj))
                elif isinstance(obj, FactLedger):
                    ledgers.append((ch_idx, obj))
                elif isinstance(obj, ForeshadowGraph):
                    graphs.append((ch_idx, obj))

        merged: list = []
        if ws := self._merge_workspecs(workspecs, issues):
            merged.append(ws)
        if wm := self._merge_worldmodels(worldmodels, issues):
            merged.append(wm)
        merged.extend(self._merge_characters(characters, issues))
        if ns := self._merge_narrative_states(states, issues):
            merged.append(ns)
        if fl := self._merge_fact_ledgers(ledgers, issues):
            merged.append(fl)
        if fg := self._merge_foreshadow_graphs(graphs, issues):
            merged.append(fg)

        return merged, issues

    def _merge_workspecs(
        self, items: list[tuple[int, WorkSpec]], issues: list[str]
    ) -> WorkSpec | None:
        if not items:
            return None
        first_ws = items[0][1]
        data = first_ws.model_dump()
        checked_fields = (
            "genre",
            "subgenre",
            "audience",
            "theme",
            "tone",
            "pacing",
            "structure_template",
            "platform",
        )
        for ch_idx, ws in items[1:]:
            for field in checked_fields:
                value = getattr(ws, field)
                first_value = getattr(first_ws, field)
                if value != first_value:
                    issues.append(
                        f"Chapter {ch_idx}: {field} mismatch ({value} vs {first_value})"
                    )
        return WorkSpec(**data)

    def _merge_worldmodels(
        self, items: list[tuple[int, WorldModel]], issues: list[str]
    ) -> WorldModel | None:
        if not items:
            return None
        data = items[0][1].model_dump()
        for ch_idx, wm in items[1:]:
            data["world_facts"] = self._merge_unique(
                data.get("world_facts", []), wm.world_facts
            )
            data["factions"] = self._merge_unique(data.get("factions", []), wm.factions)
            data["prohibitions"] = self._merge_unique(
                data.get("prohibitions", []), wm.prohibitions
            )
            data["time_rules"] = self._merge_unique(
                data.get("time_rules", []), wm.time_rules
            )
            data["consequence_logic"] = self._merge_unique(
                data.get("consequence_logic", []), wm.consequence_logic
            )
            for field in (
                "social_structure",
                "power_system",
                "resource_system",
                "geography",
            ):
                value = getattr(wm, field)
                existing = data.get(field)
                if value and existing and value != existing:
                    issues.append(
                        f"Chapter {ch_idx}: {field} mismatch ({value} vs {existing})"
                    )
                elif value and not existing:
                    data[field] = value
        return WorldModel(**data)

    def _merge_unique(self, first: list[str], second: list[str]) -> list[str]:
        return list(dict.fromkeys(first + second))

    def _merge_characters(
        self, items: list[tuple[int, CharacterModel]], issues: list[str]
    ) -> list[CharacterModel]:
        if not items:
            return []
        by_id: dict[str, dict] = {}
        for ch_idx, char in items:
            cid = char.character_id
            if cid not in by_id:
                by_id[cid] = {"last_ch": ch_idx, "data": char.model_dump()}
            else:
                existing = by_id[cid]["data"]
                if char.name != existing.get("name"):
                    issues.append(
                        f"Chapter {ch_idx}: character name mismatch for {cid} "
                        f"({char.name} vs {existing.get('name')})"
                    )
                existing["knowledge_state"] = list(
                    set(existing.get("knowledge_state", []) + char.knowledge_state)
                )
                existing["misinformation"] = list(
                    set(existing.get("misinformation", []) + char.misinformation)
                )
                existing["relations"] = {**existing.get("relations", {}), **char.relations}
                if ch_idx > by_id[cid]["last_ch"]:
                    for field in [
                        "arc_stage",
                        "self_image",
                        "outer_goal",
                        "inner_need",
                        "fear",
                        "flaw",
                        "strength",
                        "stance",
                    ]:
                        new_val = getattr(char, field)
                        if new_val:
                            existing[field] = new_val
                    by_id[cid]["last_ch"] = ch_idx
        return [CharacterModel(**d["data"]) for d in by_id.values()]

    def _merge_narrative_states(
        self, items: list[tuple[int, NarrativeState]], issues: list[str]
    ) -> NarrativeState | None:
        if not items:
            return None
        _, last_ns = max(items, key=lambda x: x[0])
        return last_ns

    def _merge_fact_ledgers(
        self, items: list[tuple[int, FactLedger]], issues: list[str]
    ) -> FactLedger | None:
        if not items:
            return None
        all_entries: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for ch_idx, fl in items:
            for entry in fl.entries:
                key = (entry.statement, entry.fact_type)
                if key not in seen:
                    seen.add(key)
                    all_entries.append(entry.model_dump())
        return FactLedger(entries=[FactEntry(**e) for e in all_entries])

    def _merge_foreshadow_graphs(
        self, items: list[tuple[int, ForeshadowGraph]], issues: list[str]
    ) -> ForeshadowGraph | None:
        if not items:
            return None
        all_entries: list[dict] = []
        seen: set[str] = set()
        for ch_idx, fg in items:
            for entry in fg.entries:
                if entry.thread_id not in seen:
                    seen.add(entry.thread_id)
                    all_entries.append(entry.model_dump())
        return ForeshadowGraph(entries=[ForeshadowEntry(**e) for e in all_entries])

    def check_cross_chapter_consistency(self, objects: list) -> list:
        """Reconcile 后检查全局一致性，返回 ReviewIssue 列表."""
        from src.object_state import CharacterModel, FactLedger, ForeshadowGraph, ReviewIssue

        issues: list[ReviewIssue] = []

        # 检测 1：角色 knowledge/misinformation 重叠（合并后可能新增）
        chars = [o for o in objects if isinstance(o, CharacterModel)]
        for char in chars:
            overlap = set(char.knowledge_state) & set(char.misinformation)
            if overlap:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_cross_char_{char.character_id}",
                        issue_type="character_distortion",
                        severity="blocking",
                        location=f"CharacterModel {char.character_id}",
                        scope_of_impact="角色逻辑一致性",
                        violated_rule="knowledge/misinformation 互斥",
                        description=f"角色 '{char.name}' 的 knowledge 与 misinformation 重叠: {overlap}",
                    )
                )

        # 检测 2：伏笔孤儿（有 setup 无 payoff 或反之）
        graphs = [o for o in objects if isinstance(o, ForeshadowGraph)]
        for graph in graphs:
            setups = {e.thread_id for e in graph.entries if e.current_status == "active"}
            payoffs = {e.thread_id for e in graph.entries if e.current_status == "resolved"}
            # 有 setup 无 payoff
            for orphan in setups - payoffs:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_cross_fore_{orphan}",
                        issue_type="promise_loss",
                        severity="warning",
                        location=f"ForeshadowGraph {orphan}",
                        scope_of_impact="承诺追踪",
                        violated_rule="伏笔必须有回收",
                        description=f"伏笔 '{orphan}' 已 setup 但未 payoff",
                    )
                )

        # 检测 3：事实陈述相似度冲突（简略版：检查 statement 子串包含关系）
        ledgers = [o for o in objects if isinstance(o, FactLedger)]
        for ledger in ledgers:
            statements = [e.statement for e in ledger.entries]
            for i, s1 in enumerate(statements):
                for s2 in statements[i + 1:]:
                    # 若两条事实互相矛盾（一条否定另一条）
                    if f"不{s1}" in s2 or f"未{s1}" in s2 or f"没{s1}" in s2:
                        issues.append(
                            ReviewIssue(
                                issue_id=f"iss_cross_fact_{i}",
                                issue_type="fact_conflict",
                                severity="blocking",
                                location="FactLedger",
                                scope_of_impact="全局事实一致性",
                                violated_rule="事实不得矛盾",
                                description=f"事实冲突: '{s1}' vs '{s2}'",
                            )
                        )

        return issues

    def check_temporal_contradictions(self, objects: list) -> list:
        """检测 FactLedger 的时间有效性矛盾(对齐 FACTTRACK).

        三个检测:
          1. 死亡后仍活跃: 存在 "死亡/陨落/阵亡" 类终结事实(带 validity 终点),
             同时存在同一实体后续仍活跃的 relation/rule 事实。
          2. 过期事实仍被持有: 事实带 validity_interval 且已过期,
             但同一实体/物品仍被引用为当前状态(如持有、属于、位于)。
          3. 时间感知否定: 同时存在 'X' 与其否定 '未X/不X/没X', 且二者时间区间重叠。

        Returns:
            ReviewIssue 列表.
        """
        from src.object_state import ReviewIssue

        issues: list[ReviewIssue] = []
        ledgers = [o for o in objects if isinstance(o, FactLedger)]
        if not ledgers:
            return issues

        entries: list[FactEntry] = []
        for ledger in ledgers:
            entries.extend(ledger.entries)

        # 检测 1: 死亡后仍活跃
        death_entries = [
            e
            for e in entries
            if e.fact_type in ("event", "reveal_status")
            and any(marker in e.statement for marker in ("死亡", "陨落", "阵亡"))
        ]
        alive_entries = [
            e
            for e in entries
            if e.fact_type in ("relation", "rule")
            and any(marker in e.statement for marker in ("活跃", "活着", "行动"))
        ]
        for de in death_entries:
            death_pos = _narrative_position(_from(de))
            for ae in alive_entries:
                if not (set(de.involved_entities) & set(ae.involved_entities)):
                    continue
                alive_pos = _narrative_position(_from(ae))
                if death_pos is not None and alive_pos is not None and alive_pos > death_pos:
                    issues.append(
                        ReviewIssue(
                            issue_id=f"iss_temp_death_{de.fact_id}_{ae.fact_id}",
                            issue_type="timeline_error",
                            severity="blocking",
                            location=f"FactLedger {de.fact_id} / {ae.fact_id}",
                            scope_of_impact="时间线一致性",
                            violated_rule="角色死亡后不得继续活跃",
                            description=(
                                f"事实 '{de.statement}'(死亡) 后, 事实 "
                                f"'{ae.statement}' 仍在活跃"
                            ),
                        )
                    )

        # 检测 2: 过期事实仍被持有
        for e in entries:
            vi = e.validity_interval
            if vi is None or vi.valid_until is None:
                continue
            # 该事实已声明过期, 但仍有同一实体的当前持有/归属事实
            for other in entries:
                if other.fact_id == e.fact_id:
                    continue
                if not (set(e.involved_entities) & set(other.involved_entities)):
                    continue
                if not any(
                    marker in other.statement for marker in ("持有", "属于", "位于", "拥有")
                ):
                    continue
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_temp_expired_{e.fact_id}",
                        issue_type="timeline_error",
                        severity="warning",
                        location=f"FactLedger {e.fact_id}",
                        scope_of_impact="时间线一致性",
                        violated_rule="过期事实不得继续作为当前状态",
                        description=(
                            f"事实 '{e.statement}' 已过期({vi.valid_until} 后), "
                            f"但 '{other.statement}' 仍将其作为当前状态"
                        ),
                    )
                )

        # 检测 3: 时间感知否定(X 与 未X/不X/没X 同时存在且区间重叠)
        for i, e1 in enumerate(entries):
            for e2 in entries[i + 1:]:
                if not (set(e1.involved_entities) & set(e2.involved_entities)):
                    continue
                if not _statements_conflict(e1.statement, e2.statement):
                    continue
                if _bounds_overlap(
                    _from(e1), _until(e1), _from(e2), _until(e2)
                ):
                    issues.append(
                        ReviewIssue(
                            issue_id=f"iss_temp_neg_{e1.fact_id}_{e2.fact_id}",
                            issue_type="timeline_error",
                            severity="blocking",
                            location=f"FactLedger {e1.fact_id} / {e2.fact_id}",
                            scope_of_impact="时间线一致性",
                            violated_rule="同一时间区间内事实不得互相否定",
                            description=(
                                f"事实 '{e1.statement}' 与 '{e2.statement}' "
                                "在同一时间区间内互相矛盾"
                            ),
                        )
                    )

        return issues

    def check_outline_consistency(
        self,
        objects: list,
        book_outline: object | None,
    ) -> list:
        """用 BookOutline 校验 Reconcile 后对象层的一致性.

        仅当 book_outline 非空时跑。返回 ReviewIssue 列表。
        """
        if book_outline is None:
            return []

        from src.object_state import CharacterModel, ReviewIssue, WorkSpec

        issues: list[ReviewIssue] = []

        outline_char_ids = {c.character_id for c in book_outline.characters}
        rebuilt_chars = [o for o in objects if isinstance(o, CharacterModel)]
        rebuilt_char_ids = {c.character_id for c in rebuilt_chars}

        for missing_id in outline_char_ids - rebuilt_char_ids:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_outline_char_missing_{missing_id}",
                    issue_type="character_distortion",
                    severity="warning",
                    location=f"CharacterModel {missing_id}",
                    scope_of_impact="结构先验一致性",
                    violated_rule="outline 已声明的角色应在 Rebuild 中重建",
                    description=(
                        f"BookOutline 中存在角色 '{missing_id}'，但 Reconcile 后"
                        "对象层未包含对应 CharacterModel"
                    ),
                )
            )

        for extra_id in rebuilt_char_ids - outline_char_ids:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_outline_char_extra_{extra_id}",
                    issue_type="character_distortion",
                    severity="low",
                    location=f"CharacterModel {extra_id}",
                    scope_of_impact="结构先验一致性",
                    violated_rule="Rebuild 中的角色应在 outline 采样范围内",
                    description=(
                        f"Reconcile 后存在角色 '{extra_id}'，但 BookOutline 未提及；"
                        "可能是 outline 采样未覆盖该角色（低严重度，仅作提示）"
                    ),
                )
            )

        workspec = next((o for o in objects if isinstance(o, WorkSpec)), None)
        if (
            workspec is not None
            and workspec.genre
            and book_outline.world.genre
            and workspec.genre != book_outline.world.genre
        ):
            issues.append(
                ReviewIssue(
                    issue_id="iss_outline_genre_mismatch",
                    issue_type="world_violation",
                    severity="warning",
                    location="WorkSpec.genre vs BookOutline.world.genre",
                    scope_of_impact="作品类型一致性",
                    violated_rule="outline 与 WorkSpec 的 genre 应一致",
                    description=(
                        f"BookOutline.world.genre='{book_outline.world.genre}'，"
                        f"但 WorkSpec.genre='{workspec.genre}'"
                    ),
                )
            )

        return issues
