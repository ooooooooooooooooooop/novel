"""领域层消费规则 — 供 Review 和 WorkSpec 使用."""

from src.domain_layer.web_fiction import (
    CRITICAL_HOOK_NODES,
    EMOTIONAL_ARC_TEMPLATES,
    GENRE_FORMULAS,
    GENRE_RULES,
    HOOK_TAXONOMY,
    NODE_EMOTION_MAP,
    PLATFORM_SNAPSHOTS,
)


def validate_plotunit_hook(hook: str, level: str) -> bool:
    """验证 hook 类型在指定层级是否合法."""
    if level not in HOOK_TAXONOMY:
        return True  # 未知层级不验证，避免误报
    if hook is None:
        return True  # 无 hook 不验证
    valid_types = {h["type"] for h in HOOK_TAXONOMY[level]}
    return hook in valid_types


def get_structure_template(formula_name: str) -> list[dict]:
    """获取结构模板节点列表."""
    if formula_name not in GENRE_FORMULAS:
        raise ValueError(f"unknown structure template: {formula_name}")
    return GENRE_FORMULAS[formula_name]


def list_available_formulas() -> list[str]:
    """返回所有可用公式名."""
    return list(GENRE_FORMULAS.keys())


def validate_emotional_shift(shift: str, template_name: str) -> bool:
    """验证情绪变化是否在模板允许范围内."""
    template = EMOTIONAL_ARC_TEMPLATES.get(template_name)
    if not template:
        return False
    valid_shifts = {node["emotion"] for node in template}
    return shift in valid_shifts


def get_platform_constraints(platform_id: str) -> dict:
    """获取平台约束字典."""
    return PLATFORM_SNAPSHOTS.get(platform_id, {})


def get_recommended_emotions(formula_node: str) -> list[str]:
    """获取指定结构节点推荐的情绪列表."""
    return NODE_EMOTION_MAP.get(formula_node, [])


def validate_node_emotion(emotional_shift: str | None, formula_node: str | None) -> bool:
    """验证情绪变化是否与结构节点的推荐情绪匹配.

    emotional_shift 为 None/空，或 formula_node 为 None/空，或节点不在映射中时，
    均返回 True（不做负向判断，避免误报）。
    """
    if not emotional_shift or not formula_node:
        return True
    recommended = NODE_EMOTION_MAP.get(formula_node, [])
    if not recommended:
        return True
    return any(emotion in emotional_shift for emotion in recommended)


def build_platform_guidance(platform_id: str) -> str:
    """将平台约束翻译为 LLM 可理解的指导文本."""
    constraints = get_platform_constraints(platform_id)
    if not constraints:
        return ""

    lines = [f"【平台约束: {platform_id}】"]

    patience_map = {
        "low": "读者耐心较低，需要频繁维持张力",
        "medium": "读者耐心中等，允许适度铺垫",
        "very low": "读者耐心极低，几乎每段都需要推进或钩子",
    }

    if hook := constraints.get("hook_pressure"):
        lines.append(f"钩子策略: {hook}")
    if length := constraints.get("chapter_length_target"):
        lines.append(f"章节长度目标: {length} 字")
    if patience := constraints.get("reader_patience"):
        lines.append(patience_map.get(patience, f"读者耐心: {patience}"))

    return "\n".join(lines)


def get_hook_effectiveness(hook: str, level: str) -> str | None:
    """获取 hook 在指定层级的 effectiveness 等级."""
    entries = HOOK_TAXONOMY.get(level, [])
    for entry in entries:
        if entry["type"] == hook:
            return entry["effectiveness"]
    return None


def is_critical_hook_node(formula_node: str | None) -> bool:
    """判断结构节点是否为关键钩子节点."""
    if not formula_node:
        return False
    return formula_node in CRITICAL_HOOK_NODES


def get_genre_guidance(genre: str) -> str:
    """获取 genre 的写作指导文本."""
    rules = GENRE_RULES.get(genre, [])
    if not rules:
        return ""
    lines = [f"【{genre} 类型约束】"]
    for rule in rules:
        lines.append(f"- {rule}")
    return "\n".join(lines)
