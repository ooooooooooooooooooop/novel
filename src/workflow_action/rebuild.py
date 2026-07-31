"""RebuildUnit — 重建工作流."""

import json
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
from src.workflow_action.outline import BookOutline


class RebuildUnit:
    """从文本重建叙事对象层."""

    def build_prompt(self, text: str, book_outline: Optional[BookOutline] = None) -> str:
        """生成重建 prompt."""
        return self._build_prompt(text, book_outline)

    def parse_response(self, response: str) -> tuple[list, list[str]]:
        """解析 LLM 重建响应.

        Returns:
            (对象列表, confidence_gaps 列表)
        """
        data = json.loads(response)
        required_fields = (
            "workspec",
            "worldmodel",
            "charactermodels",
            "narrativestate",
            "factledger",
            "foreshadowgraph",
            "confidence_gaps",
        )
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(
                f"Rebuild response missing required field(s): {', '.join(missing)}"
            )
        extra = sorted(set(data) - set(required_fields))
        if extra:
            raise ValueError(
                f"Rebuild response has unexpected field(s): {', '.join(extra)}"
            )
        objects = self._parse(data)
        gaps = data["confidence_gaps"]
        if not isinstance(gaps, list):
            raise ValueError("Rebuild response field confidence_gaps must be a list")
        if not all(isinstance(gap, str) for gap in gaps):
            raise ValueError(
                "Rebuild response field confidence_gaps must be a list of strings"
            )
        if any(not gap.strip() for gap in gaps):
            raise ValueError(
                "Rebuild response field confidence_gaps entries must be non-empty"
            )
        return objects, gaps

    def _build_prompt(self, text: str, book_outline: Optional[BookOutline] = None) -> str:
        """生成重建 prompt."""
        outline_section = ""
        if book_outline is not None:
            outline_section = self._format_book_outline(book_outline) + "\n\n"

        return f"""你是一位叙事分析专家。请从以下文本中重建叙事系统的对象层。

{outline_section}【输入文本】
{text}

【需要重建的对象】

1. WorkSpec（作品规格）:
   - genre: 作品类型
   - subgenre: 子类型（可选）
   - audience: 目标读者
   - theme: 核心主题
   - tone: 叙事调性
   - pacing: 节奏策略
   - length_target: 目标长度（可选，整数）
   - constraints: 内容约束列表
   - romance_weight/mystery_weight/action_weight: 元素权重 0-1（可选）

2. WorldModel（世界模型）:
   - world_facts: 世界事实列表
   - social_structure: 社会结构（可选）
   - power_system: 力量体系（可选）
   - resource_system: 资源机制（可选）
   - geography: 地理（可选）
   - factions: 势力列表
   - time_rules: 时间规则列表
   - prohibitions: 禁止事项列表
   - consequence_logic: 后果逻辑列表

3. CharacterModel（角色模型）数组，每个角色:
   - character_id: 唯一ID
   - name: 名字
   - identity: 身份
   - outer_goal: 外在目标
   - inner_need: 内在需求
   - fear: 恐惧
   - flaw: 缺陷
   - strength: 优势
   - secret: 秘密（可选）
   - stance: 立场
   - arc_stage: 成长阶段（可选）
   - self_image: 自我认知（可选）
   - knowledge_state: 已知信息列表
   - misinformation: 错误信念列表
   - relations: {{角色ID: 关系描述}}

4. NarrativeState（叙事状态）:
   - state_id: 状态ID
   - current_time: 当前时间
   - current_location: 当前地点
   - active_characters: 出场角色ID列表
   - current_situation: 局势概述
   - primary_goal: 首要目标（可选）
   - active_conflicts: 活跃冲突列表
   - emotional_temperature: 情绪温度（可选）
   - public_information: 公开信息列表
   - hidden_information: 隐藏信息列表
   - active_suspense_items: 悬念列表
   - current_goals: 当前目标列表

5. FactLedger（事实账本）:
   - entries: 事实条目数组，每条:
     - fact_id: ID
     - statement: 事实陈述
     - fact_type: 类型(event/relation/rule/object/time_order/reveal_status)
     - involved_entities: 涉及实体ID列表
     - confirmed: true（重建时默认 true）

6. ForeshadowGraph（伏笔图）:
   - entries: 伏笔条目数组，每条:
     - thread_id: ID
     - setup_point: 埋设点
     - content: 内容
     - visibility_level: explicit/implicit
     - expected_payoff: 预期回收
     - current_status: active
     - linked_characters: 关联角色ID
     - linked_facts: 关联事实ID

【Track 1 约束 — 必须遵守】
- FactLedger 只记录已确认 hard facts
- 不确定的信息不要写进 FactLedger，放入 confidence_gaps
- 不要混淆事实和推断

【Track 3 约束 — 必须遵守】
- CharacterModel 只存压缩长期结论
- 支撑证据不要写进 knowledge_state 或 relations
- 关系只写结论，不写依据

【输出格式】
严格输出 JSON，不要 Markdown 代码块标记:
{{
  "workspec": {{...}},
  "worldmodel": {{...}},
  "charactermodels": [{{...}}],
  "narrativestate": {{...}},
  "factledger": {{"entries": [{{...}}]}},
  "foreshadowgraph": {{"entries": [{{...}}]}},
  "confidence_gaps": ["gap1", "gap2"]
}}"""

    def _format_book_outline(self, book_outline: BookOutline) -> str:
        """将 BookOutline 格式化为 Rebuild 可读的结构先验."""
        lines = [
            "【结构先验 — BookOutline】",
            "BookOutline 是已确认的 L1 结构先验。Rebuild 输出的对象层应与其保持一致；如文本局部信息与 outline 冲突，以 outline 为准。",
            "",
            "Arcs:",
        ]
        for arc in book_outline.arcs:
            lines.extend(
                [
                    f"- arc_id: {arc.arc_id}",
                    f"  name: {arc.name}",
                    f"  chapter_range: {arc.chapter_range}",
                    f"  purpose: {arc.purpose}",
                    f"  key_characters: {', '.join(arc.key_characters) if arc.key_characters else '无'}",
                    f"  key_events: {'; '.join(arc.key_events) if arc.key_events else '无'}",
                ]
            )

        lines.append("")
        lines.append("Characters:")
        for character in book_outline.characters:
            lines.extend(
                [
                    f"- character_id: {character.character_id}",
                    f"  name: {character.name}",
                    f"  identity: {character.identity}",
                    f"  first_appearance: {character.first_appearance}",
                ]
            )

        lines.extend(
            [
                "",
                "World:",
                f"- genre: {book_outline.world.genre}",
                f"- power_system: {book_outline.world.power_system}",
                f"- time_period: {book_outline.world.time_period}",
                f"- key_rules: {'; '.join(book_outline.world.key_rules) if book_outline.world.key_rules else '无'}",
                "",
                "Timeline:",
            ]
        )
        for entry in book_outline.timeline:
            lines.extend(
                [
                    f"- timestamp: {entry.timestamp}",
                    f"  event: {entry.event}",
                    f"  chapters: {entry.chapters}",
                ]
            )
        return "\n".join(lines)

    def _parse(self, data: dict) -> list:
        """解析 LLM 返回的 JSON 为对象."""
        objects = []
        objects.append(WorkSpec(**data["workspec"]))
        objects.append(WorldModel(**data["worldmodel"]))
        if not isinstance(data["charactermodels"], list):
            raise ValueError("Rebuild response field charactermodels must be a list")
        for cm in data["charactermodels"]:
            objects.append(CharacterModel(**cm))
        objects.append(NarrativeState(**data["narrativestate"]))
        # FactLedger
        fl_data = data["factledger"]
        if "entries" not in fl_data:
            raise ValueError("Rebuild response field factledger.entries is required")
        entries = [FactEntry(**e) for e in fl_data["entries"]]
        objects.append(FactLedger(entries=entries))
        # ForeshadowGraph
        fg_data = data["foreshadowgraph"]
        if "entries" not in fg_data:
            raise ValueError("Rebuild response field foreshadowgraph.entries is required")
        fg_entries = [ForeshadowEntry(**e) for e in fg_data["entries"]]
        objects.append(ForeshadowGraph(entries=fg_entries))
        return objects
