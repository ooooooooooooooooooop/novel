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
    """验证 PlotUnit hook 的有效性.

    PlotUnit.hook 是自由文本钩子内容（LLM 生成），不是 hook taxonomy 的类型枚举：
    - 若 hook 显式等于该层级的合法类型名（如 scene 的 revelation），按类型严格校验；
    - 否则视为自由文本钩子，仅做轻量质量检查（非空、有实质长度），
      不再把内容文本与类型名精确比较——旧实现把中文句子钩子与枚举类型名匹配，
      导致全部 hook 被判"对层级不合法"的系统性误报。
    """
    if level not in HOOK_TAXONOMY:
        return True  # 未知层级不验证，避免误报
    if not hook or not hook.strip():
        return True  # 无 hook 不验证
    valid_types = {h["type"] for h in HOOK_TAXONOMY[level]}
    if hook in valid_types:
        return True  # 显式类型名且属于当前层级
    # hook 是其他层级的合法类型名（显式类型枚举但层级不匹配）→ 非法
    all_types = {
        h["type"] for entries in HOOK_TAXONOMY.values() for h in entries
    }
    if hook in all_types:
        return False
    # 自由文本钩子：有实质内容即视为有效
    return len(hook.strip()) >= 4


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


# 推荐情绪 → 近义表述扩展（供 validate_node_emotion 降低关键词漏检）。
# 覆盖 NODE_EMOTION_MAP 中的情绪值；匹配到任一近义表述即视为命中。
_EMOTION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "困惑": ("困惑", "不解", "茫然", "迟疑", "疑问", "迷惘", "动摇", "不安", "想问"),
    "压抑": ("压抑", "沉重", "沉闷", "低气压", "克制", "隐忍"),
    "好奇": ("好奇", "想知道", "追问", "探寻", "探究", "窥探"),
    "震惊": ("震惊", "惊骇", "震动", "难以置信", "猛地一缩"),
    "威胁": ("威胁", "压迫", "危机", "逼", "迫"),
    "决心": ("决心", "决意", "坚定", "下定决心", "打定主意"),
    "抉择": ("抉择", "选择", "取舍", "两难"),
    "蓄力": ("蓄力", "积攒", "酝酿", "蓄势", "准备"),
    "疑虑": ("疑虑", "怀疑", "将信将疑", "戒惧"),
    "悲痛": ("悲痛", "哀恸", "撕心裂肺"),
    "失去": ("失去", "没了"),
    "绝望": ("绝望", "无望", "心死"),
    "爆发": ("爆发", "炸开", "涌", "决堤", "压抑不住"),
    "仇恨": ("仇恨", "怨恨", "清算"),
    "清算": ("清算", "算账", "了结", "讨"),
    "余波": ("余波", "余震", "余温", "收束", "尘埃落定"),
    "重建": ("重建", "重来", "重新", "站起"),
    "升华": ("升华", "通透", "释然", "超越"),
    "觉醒": ("觉醒", "恍然", "顿悟"),
    "稳定": ("稳定", "安宁", "安稳", "踏实", "平静"),
    "揭露": ("揭露", "揭开", "真相大白", "暴露"),
}


def _emotion_text_hits(text: str, emotion: str) -> bool:
    """判断情绪文本是否命中推荐情绪（精确词或近义表述）."""
    if emotion in text:
        return True
    for synonym in _EMOTION_SYNONYMS.get(emotion, ()):
        if synonym and synonym in text:
            return True
    return False


def validate_node_emotion(emotional_shift: str | None, formula_node: str | None) -> bool:
    """验证情绪变化是否与结构节点的推荐情绪匹配.

    emotional_shift 为 None/空，或 formula_node 为 None/空，或节点不在映射中时，
    均返回 True（不做负向判断，避免误报）。匹配时除精确情绪词外，
    还接受近义表述（如「好奇」≈「想知道/追问」），降低关键词漏检。
    """
    if not emotional_shift or not formula_node:
        return True
    recommended = NODE_EMOTION_MAP.get(formula_node, [])
    if not recommended:
        return True
    return any(_emotion_text_hits(emotional_shift, emotion) for emotion in recommended)


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
