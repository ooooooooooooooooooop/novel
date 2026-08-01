"""领域层消费规则 — 风格知识访问函数.

对齐 rules.py 的模式：从 style_knowledge.py 的表读取并渲染为
LLM 可理解的指导文本。
"""

from src.domain_layer.style_knowledge import (
    AI_FLAVOR_MARKERS,
    GENRE_STYLE_GUIDANCE,
    TONE_STYLE_TRAITS,
    WEAK_ADVERB_SET,
)
from src.domain_layer.style_knowledge import (
    AiFlavorMarker,
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


def build_style_knowledge_context(tone: str = "", genre: str = "") -> str:
    """拼接调性+genre 的风格知识上下文.

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
    return "\n\n".join(sections)
