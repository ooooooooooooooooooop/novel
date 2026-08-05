"""领域层消费规则 — 风格知识访问函数.

对齐 rules.py 的模式：从 style_knowledge.py 的表读取并渲染为
LLM 可理解的指导文本。
"""

from src.domain_layer.style_knowledge import (
    AI_FLAVOR_MARKERS,
    CHARACTER_METHODS,
    DECISION_GROUNDING_AXIS,
    DESCRIPTION_TECHNIQUES,
    DIALOGUE_TECHNIQUES,
    GENRE_STYLE_GUIDANCE,
    OMISSION_AXIS,
    SUBTLE_TECHNIQUES,
    TEMPERAMENT_BUCKETS,
    TEMPERAMENT_NAMES,
    TONE_STYLE_TRAITS,
    WEAK_ADVERB_SET,
)
from src.domain_layer.style_knowledge import (
    AiFlavorMarker,
    TechniqueEntry,
    TemperamentBucket,
    ToneTraitEntry,
)


def get_tone_style_traits(tone: str) -> list[ToneTraitEntry]:
    """获取指定调性的写作特征清单（未知调性返回空列表）."""
    return TONE_STYLE_TRAITS.get(tone, [])


def list_available_tones() -> list[str]:
    """返回所有可用调性名."""
    return list(TONE_STYLE_TRAITS.keys())


def build_tone_guidance(tone: str) -> str:
    """将调性特征翻译为 LLM 可理解的指导文本."""
    traits = get_tone_style_traits(tone)
    if not traits:
        return ""
    lines = [f"【调性: {tone}】"]
    for entry in traits:
        lines.append(f"- {entry['trait']}: {entry['instruction']}")
    return "\n".join(lines)


def get_genre_style_guidance(genre: str) -> str:
    """获取 genre 的风格指导文本（未知 genre 返回空字符串）."""
    rules = GENRE_STYLE_GUIDANCE.get(genre, [])
    if not rules:
        return ""
    lines = [f"【{genre} 类型风格】"]
    for rule in rules:
        lines.append(f"- {rule}")
    return "\n".join(lines)


def get_ai_flavor_markers() -> list[AiFlavorMarker]:
    """获取全部 AI 味标记规则."""
    return list(AI_FLAVOR_MARKERS)


def get_weak_adverb_set() -> set[str]:
    """获取弱化副词集合."""
    return set(WEAK_ADVERB_SET)


def lookup_marker(rule_id: str) -> AiFlavorMarker | None:
    """按 rule_id 查找 AI 味标记规则."""
    for marker in AI_FLAVOR_MARKERS:
        if marker["rule_id"] == rule_id:
            return marker
    return None


def build_style_knowledge_context(
    tone: str = "", genre: str = "", temperament: str = ""
) -> str:
    """拼接调性+genre+气质的风格知识上下文.

    同时用于：1) 提炼 prompt（给 LLM 分类轴） 2) Continue 注入（给续写约束）。
    """
    sections: list[str] = []
    if tone:
        tone_guidance = build_tone_guidance(tone)
        if tone_guidance:
            sections.append(tone_guidance)
    if genre:
        genre_guidance = get_genre_style_guidance(genre)
        if genre_guidance:
            sections.append(genre_guidance)
    if temperament:
        temperament_guidance = build_temperament_guidance(temperament)
        if temperament_guidance:
            sections.append(temperament_guidance)
    return "\n\n".join(sections)


def _render_technique_axis(title: str, techniques: list[TechniqueEntry]) -> str:
    """渲染一条手法轴的分类指导文本（提炼 prompt 用）. 返回空串表示该轴为空."""
    if not techniques:
        return ""
    lines = [f"【{title}】"]
    for entry in techniques:
        lines.append(f"- {entry['name']}: {entry['definition']}")
        lines.append(f"  指令: {entry['instruction']}")
        lines.append(f"  误用警示: {entry['misuse']}")
    return "\n".join(lines)


def build_worldview_axis_guidance() -> str:
    """渲染写作手法世界观的完整分类轴（供风格提炼 prompt 给 LLM 分类）.

    覆盖六条轴：描写手法 / 含蓄表现手法 / 留白 / 人物五法 / 对白技巧 / 决策依据。
    提炼时 LLM 按这些轴判断作品使用了哪些手法、什么配比。
    """
    axes = [
        ("描写手法轴", DESCRIPTION_TECHNIQUES),
        ("含蓄表现手法轴", SUBTLE_TECHNIQUES),
        ("留白轴", OMISSION_AXIS),
        ("人物五法轴", CHARACTER_METHODS),
        ("对白技巧轴", DIALOGUE_TECHNIQUES),
        ("决策依据轴", DECISION_GROUNDING_AXIS),
    ]
    return "\n\n".join(
        section
        for title, techniques in axes
        if (section := _render_technique_axis(title, techniques))
    )


def get_description_techniques() -> list[TechniqueEntry]:
    """描写手法全集（白描/细描/渲染/衬托/侧面/动静/点面）."""
    return DESCRIPTION_TECHNIQUES


def get_omission_axis() -> list[TechniqueEntry]:
    """留白轴（点破/留白）."""
    return OMISSION_AXIS


def get_subtle_techniques() -> list[TechniqueEntry]:
    """含蓄表现手法（象征/暗示/用典/双关）."""
    return SUBTLE_TECHNIQUES


def get_character_methods() -> list[TechniqueEntry]:
    """人物五法（肖像/动作/语言/心理/神态）."""
    return CHARACTER_METHODS


def get_dialogue_techniques() -> list[TechniqueEntry]:
    """对白技巧（潜文本/性格化/言外之意）."""
    return DIALOGUE_TECHNIQUES


def get_decision_grounding_axis() -> list[TechniqueEntry]:
    """决策依据轴（身份/信念/剧情需要/随机）."""
    return DECISION_GROUNDING_AXIS


def get_temperament_buckets() -> list[TemperamentBucket]:
    """全部叙事气质桶."""
    return TEMPERAMENT_BUCKETS


# 气质桶别名：容忍"散文"漏打"型"后缀等常见输入，归一化到全称（全称匹配优先）。
_TEMPERAMENT_ALIASES: dict[str, str] = {
    "散文": "散文型",
    "戏剧": "戏剧型",
    "信息": "信息型",
    "氛围": "氛围型",
}


def get_temperament_bucket(name: str) -> TemperamentBucket | None:
    """按名取气质桶（未知返回 None）; 支持常见简写别名归一化."""
    canonical = _TEMPERAMENT_ALIASES.get(name, name)
    for bucket in TEMPERAMENT_BUCKETS:
        if bucket["name"] == canonical:
            return bucket
    return None


def list_available_temperaments() -> list[str]:
    """返回所有可用气质桶名."""
    return list(TEMPERAMENT_NAMES)


def build_temperament_guidance(temperament: str) -> str:
    """将气质桶渲染为 LLM 可理解的指导文本（未知气质返回空串）.

    标题用 canonical 桶名（别名"散文"会渲染为"散文型"），保证不同输入
    产出稳定文本（可哈希/可比较）。
    """
    bucket = get_temperament_bucket(temperament)
    if not bucket:
        return ""
    lines = [
        f"【叙事气质: {bucket['name']}】",
        f"- {bucket['description']}",
        "默认聚焦手法:",
    ]
    lines.extend(f"- {focus}" for focus in bucket["default_focus"])
    lines.append("量化参考基线:")
    lines.extend(f"- {note}" for note in bucket["baseline_notes"])
    return "\n".join(lines)
