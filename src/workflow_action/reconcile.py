"""ReconcileUnit — 跨章节对象合并."""

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
