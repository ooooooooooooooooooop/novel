"""ContinueUnit — 续写工作流."""

import json

from src.domain_layer.rules import (
    build_platform_guidance,
    get_genre_guidance,
    get_recommended_emotions,
    get_structure_template,
    is_critical_hook_node,
)
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
)


def admit_new_facts(
    facts: FactLedger,
    new_facts: list,
    source_plotunit: str,
) -> list[dict]:
    """Admit Continue-produced hard facts into FactLedger."""
    if not isinstance(new_facts, list):
        raise ValueError("new_facts must be a list")

    existing_ids = {entry.fact_id for entry in facts.entries}
    admitted: list[dict] = []
    for raw_fact in new_facts:
        if not isinstance(raw_fact, dict):
            raise ValueError("new_facts entries must be JSON objects")
        fact_data = dict(raw_fact)
        if "confirmed" not in fact_data:
            raise ValueError("new_facts entries must declare confirmed=true")
        if fact_data["confirmed"] is not True:
            raise ValueError("new_facts entries must be confirmed hard facts")
        fact_data["source_plotunit"] = source_plotunit

        entry = FactEntry(**fact_data)
        if entry.fact_id in existing_ids:
            raise ValueError(f"duplicate new fact_id: {entry.fact_id}")
        facts.add_fact(entry)
        existing_ids.add(entry.fact_id)
        admitted.append(entry.model_dump(mode="json"))

    return admitted


class ContinueUnit:
    """从当前状态生成下一 PlotUnit."""

    def build_prompt(
        self,
        state: NarrativeState,
        characters: list[CharacterModel],
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
        workspec_context: str = "",
        frame_context: dict | None = None,
        structure_template: str | None = None,
        platform: str | None = None,
        genre: str | None = None,
        style_context: str = "",
        retrieval_context: str = "",
        timeline_context: str = "",
        time_context: str = "",
        excerpt_context: str = "",
        nsfw_context: str = "",
    ) -> str:
        """生成续写 prompt."""
        return self._build_prompt(
            state,
            characters,
            facts,
            foreshadows,
            workspec_context,
            frame_context,
            structure_template,
            platform,
            genre,
            style_context,
            retrieval_context,
            timeline_context,
            time_context,
            excerpt_context,
            nsfw_context,
        )

    def parse_response(self, response: str) -> tuple[PlotUnit, NarrativeState, list[str], list[str]]:
        """解析 LLM 续写响应.

        Returns:
            (PlotUnit, 新NarrativeState, 新增事实列表, confidence_gaps)
        """
        data = json.loads(response)
        required_fields = ("plotunit", "new_state", "new_facts", "confidence_gaps")
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(
                f"Continue response missing required field(s): {', '.join(missing)}"
            )
        extra = sorted(set(data) - set(required_fields))
        if extra:
            raise ValueError(
                f"Continue response has unexpected field(s): {', '.join(extra)}"
            )

        if not isinstance(data["new_facts"], list):
            raise ValueError("Continue response field new_facts must be a list")
        if not isinstance(data["confidence_gaps"], list):
            raise ValueError("Continue response field confidence_gaps must be a list")
        if not all(isinstance(gap, str) for gap in data["confidence_gaps"]):
            raise ValueError(
                "Continue response field confidence_gaps must be a list of strings"
            )
        if any(not gap.strip() for gap in data["confidence_gaps"]):
            raise ValueError(
                "Continue response field confidence_gaps entries must be non-empty"
            )

        plotunit = PlotUnit(**data["plotunit"])
        new_state = NarrativeState(**data["new_state"])
        new_facts = data["new_facts"]
        gaps = data["confidence_gaps"]

        return plotunit, new_state, new_facts, gaps

    def _build_prompt(
        self,
        state: NarrativeState,
        characters: list[CharacterModel],
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
        workspec_context: str,
        frame_context: dict | None,
        structure_template: str | None,
        platform: str | None,
        genre: str | None,
        style_context: str,
        retrieval_context: str,
        timeline_context: str = "",
        time_context: str = "",
        excerpt_context: str = "",
        nsfw_context: str = "",
    ) -> str:
        char_ctx = "\n---\n".join(c.to_prompt_context() for c in characters)
        active_threads = foreshadows.get_active()
        thread_ctx = "\n".join(f"- {e.content}" for e in active_threads) if active_threads else "无"
        frame_section = ""
        emotion_section = ""
        if frame_context is not None:
            frame_section = (
                "\n\n【层级上下文】\n"
                + json.dumps(frame_context, ensure_ascii=False, indent=2)
            )
            current_frame = frame_context.get("current_frame", {})
            formula_node = current_frame.get("formula_node", "")
            if formula_node:
                recommended = get_recommended_emotions(formula_node)
                if recommended:
                    emotion_lines = [
                        "\n\n【当前叙事阶段走向】",
                        f"当前结构节点: {formula_node}",
                        f"推荐情绪: {' / '.join(recommended)}",
                        "请让 emotional_shift 体现以上某种情绪变化。",
                    ]
                    if is_critical_hook_node(formula_node):
                        emotion_lines.append(
                            "【关键节点钩子要求】建议使用 high-effectiveness 钩子"
                            "（如 cliffhanger / reveal / in_media_res / revelation）。"
                        )
                    emotion_section = "\n".join(emotion_lines)
        platform_section = ""
        if platform:
            guidance = build_platform_guidance(platform)
            if guidance:
                platform_section = f"\n\n{guidance}"
        genre_section = ""
        if genre:
            guidance = get_genre_guidance(genre)
            if guidance:
                genre_section = f"\n\n{guidance}"
        style_section = ""
        if style_context:
            style_section = f"\n\n【写作风格】\n{style_context}"
        time_section = ""
        if time_context:
            time_section = f"\n\n【时间上下文】\n{time_context}"
        retrieval_section = ""
        if retrieval_context:
            retrieval_section = f"\n\n【相关事实检索】\n{retrieval_context}"
        timeline_section = ""
        if timeline_context:
            timeline_section = f"\n\n【已发生事件时间线】\n{timeline_context}"
        excerpt_section = ""
        if excerpt_context:
            excerpt_section = f"\n\n【原文锚点与文风样例】\n{excerpt_context}"
        nsfw_section = ""
        if nsfw_context:
            nsfw_section = f"\n\n【内容分级】\n{nsfw_context}"
        structure_section = ""
        if structure_template:
            nodes = get_structure_template(structure_template)
            if nodes:
                nodes_text = "\n".join(
                    f"- {n['name']} ({n['position']}): {n['purpose']}" for n in nodes
                )
                structure_section = (
                    f"\n\n【结构模板: {structure_template}】\n{nodes_text}"
                )

        return f"""你是一位叙事续写专家。请基于当前叙事状态，生成下一个 PlotUnit。

【作品约束】
{workspec_context}{platform_section}{genre_section}{style_section}{time_section}{timeline_section}{excerpt_section}{retrieval_section}{nsfw_section}

【当前叙事状态】
{state.to_prompt_context()}

【角色状态】
{char_ctx}

【已确认事实】
{facts.to_prompt_context()}

【活跃承诺/伏笔】
{thread_ctx}
{structure_section}{frame_section}{emotion_section}

【续写要求】

1. PlotUnit 必须导致有意义的状态变化
2. 角色行为必须符合 CharacterModel 的驱动力、恐惧和缺陷
3. 新信息释放必须服务于 ForeshadowGraph 的承诺推进
4. 必须体现至少一个世界规则约束或代价
5. 不能一次性解决所有悬念，但可以推进其中一个
6. 情绪变化必须有依据，不能跳跃
7. 忠于原文：不得引入与已发生事件（时间线）矛盾的事件；新线索必须能与既有事实自洽，不得凭空捏造与原文无关的设定
8. scene_experience 可选：提供时须落在读者体验五维（看见/阻碍/选择/结果/认知变化），让正文展开有现场感；省略时不注入

【输出格式】
严格输出 JSON:
{{
  "plotunit": {{
    "unit_id": "pu_xxx",
    "level": "scene",
    "goal": "本单元目标",
    "participants": ["角色ID"],
    "conflict": "核心冲突",
    "input_state_ref": "{state.state_id}",
    "output_state_ref": "新状态ID",
    "released_information": ["新释放给读者的信息"],
    "emotional_shift": "情绪变化",
    "hook": "钩子",
    "formula_node": "当前结构节点名（如 climax）",
    "consequences": ["后果"],
    "is_effective": true,
    "scene_experience": {{
      "protagonist_sees": "主角看见了什么——本场景的感官焦点（具体画面，非概述）",
      "obstacles": ["遇到了什么阻碍（具体阻力）"],
      "choice_grounding": "为什么作出选择（身份/信念/压力依据，避免剧情需要式选择）",
      "outcome": "选择产生了什么结果（读者知道成/败/变的可见反馈）",
      "cognition_shift": "情绪和认知如何变化（从之前怎么想到现在怎么想）"
    }}
  }},
  "new_state": {{
    "state_id": "新状态ID",
    "current_time": "新时间",
    "current_location": "新地点",
    "active_characters": ["角色ID"],
    "current_situation": "新局势",
    "active_conflicts": ["新冲突"],
    "public_information": ["新公开信息"],
    "hidden_information": ["新隐藏信息"]
  }},
  "new_facts": [
    {{
      "fact_id": "f_xxx",
      "statement": "新确认事实",
      "fact_type": "event",
      "involved_entities": [],
      "confirmed": true
    }}
  ],
  "confidence_gaps": ["不确定的信息"]
}}

注意：
- new_facts 只写入已确认的 hard facts，不确定的放入 confidence_gaps
- 角色关系变化如果是长期结论，更新 CharacterModel.relations
- 但 CharacterModel 字段只存压缩结论，支撑证据不要写入
"""
