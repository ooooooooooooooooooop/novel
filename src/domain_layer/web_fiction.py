"""网文领域层 — 规则知识，非事实，非推断."""

from typing import TypedDict


class FormulaNode(TypedDict):
    name: str
    purpose: str
    position: str  # "start" | "middle" | "end" | "flexible"


class HookEntry(TypedDict):
    type: str
    description: str
    effectiveness: str  # "high" | "medium" | "low"


class EmotionalNode(TypedDict):
    emotion: str
    trigger: str
    duration: str  # "chapter" | "scene" | "arc"


# --- Genre Formulas ---

GENRE_FORMULAS: dict[str, list[FormulaNode]] = {
    "eight_node": [
        {"name": "opener_hook", "purpose": "建立悬念", "position": "start"},
        {"name": "inciting_incident", "purpose": "打破平衡", "position": "start"},
        {"name": "first_plot_point", "purpose": "主角被迫行动", "position": "start"},
        {"name": "rising_action", "purpose": "阻力升级", "position": "middle"},
        {"name": "midpoint", "purpose": "揭示真相或方向改变", "position": "middle"},
        {"name": "second_plot_point", "purpose": "失去一切", "position": "middle"},
        {"name": "climax", "purpose": "最终对抗", "position": "end"},
        {"name": "resolution", "purpose": "新平衡", "position": "end"},
    ],
    "three_act": [
        {"name": "act1_setup", "purpose": "世界、角色、冲突建立", "position": "start"},
        {"name": "act2_confrontation", "purpose": "上升阻力与代价", "position": "middle"},
        {"name": "act3_resolution", "purpose": "高潮与解决", "position": "end"},
    ],
    "compressed_three_act": [
        {"name": "fast_setup", "purpose": "一章内建立冲突", "position": "start"},
        {"name": "compressed_rising", "purpose": "快速升级", "position": "middle"},
        {"name": "payoff", "purpose": "即时回收", "position": "end"},
    ],
    "five_act": [
        {"name": "exposition", "purpose": " exposition", "position": "start"},
        {"name": "rising_action", "purpose": "复杂化", "position": "start"},
        {"name": "climax", "purpose": "转折点", "position": "middle"},
        {"name": "falling_action", "purpose": "后果展开", "position": "middle"},
        {"name": "catastrophe", "purpose": "最终解决", "position": "end"},
    ],
    "hero_journey": [
        {"name": "ordinary_world", "purpose": "日常世界", "position": "start"},
        {"name": "call_to_adventure", "purpose": "冒险召唤", "position": "start"},
        {"name": "ordeal", "purpose": "终极考验", "position": "middle"},
        {"name": "return", "purpose": "携宝归返", "position": "end"},
    ],
    "infinite_dungeon": [
        {"name": "entry", "purpose": "副本进入", "position": "start"},
        {"name": "exploration", "purpose": "规则摸索", "position": "middle"},
        {"name": "boss_fight", "purpose": "首领战", "position": "end"},
        {"name": "exit", "purpose": "结算与收获", "position": "end"},
    ],
}

# --- Hook Taxonomy ---

HOOK_TAXONOMY: dict[str, list[HookEntry]] = {
    "chapter_end": [
        {"type": "cliffhanger", "description": "悬念突转", "effectiveness": "high"},
        {"type": "reveal", "description": "真相揭露", "effectiveness": "high"},
        {"type": "emotional_peak", "description": "情绪顶点", "effectiveness": "medium"},
        {"type": "promise", "description": "承诺未来事件", "effectiveness": "medium"},
    ],
    "chapter_open": [
        {"type": "in_media_res", "description": "切入动作", "effectiveness": "high"},
        {"type": "mystery_setup", "description": "新谜题", "effectiveness": "medium"},
        {"type": "emotional_anchor", "description": "情绪锚点", "effectiveness": "low"},
    ],
    "paragraph": [
        {"type": "micro_tension", "description": "微观张力", "effectiveness": "medium"},
        {"type": "sensory_detail", "description": "感官细节", "effectiveness": "low"},
    ],
    "scene": [
        {"type": "scene_hook", "description": "场景内钩子", "effectiveness": "medium"},
        {"type": "transition", "description": "场景过渡", "effectiveness": "low"},
        {"type": "revelation", "description": "信息揭露", "effectiveness": "high"},
    ],
}

# --- Emotional Arc Templates ---

EMOTIONAL_ARC_TEMPLATES: dict[str, list[EmotionalNode]] = {
    "catharsis_arc": [
        {"emotion": "压抑", "trigger": "主角受限", "duration": "chapter"},
        {"emotion": "爆发", "trigger": "突破限制", "duration": "scene"},
        {"emotion": "余波", "trigger": "后果显现", "duration": "scene"},
    ],
    "revelation_arc": [
        {"emotion": "困惑", "trigger": "新信息矛盾", "duration": "chapter"},
        {"emotion": "震惊", "trigger": "真相揭露", "duration": "scene"},
        {"emotion": "决心", "trigger": "重新定位", "duration": "scene"},
    ],
    "loss_arc": [
        {"emotion": "稳定", "trigger": "拥有某物", "duration": "chapter"},
        {"emotion": "威胁", "trigger": "失去信号", "duration": "scene"},
        {"emotion": "悲痛", "trigger": "确认失去", "duration": "scene"},
        {"emotion": "重建", "trigger": "寻找替代", "duration": "chapter"},
    ],
    "comeback_arc": [
        {"emotion": "低谷", "trigger": "被压制", "duration": "chapter"},
        {"emotion": "蓄力", "trigger": "准备反击", "duration": "scene"},
        {"emotion": "爆发", "trigger": "逆转胜利", "duration": "scene"},
    ],
    "sacrifice_arc": [
        {"emotion": "安稳", "trigger": "拥有重要之物", "duration": "chapter"},
        {"emotion": "抉择", "trigger": "必须放弃", "duration": "scene"},
        {"emotion": "悲痛", "trigger": "确认失去", "duration": "scene"},
        {"emotion": "升华", "trigger": "代价产生意义", "duration": "chapter"},
    ],
    "betrayal_arc": [
        {"emotion": "信任", "trigger": "同盟建立", "duration": "chapter"},
        {"emotion": "疑虑", "trigger": "异常信号", "duration": "scene"},
        {"emotion": "揭露", "trigger": "背叛确认", "duration": "scene"},
        {"emotion": "仇恨", "trigger": "代价结算", "duration": "chapter"},
    ],
}

NODE_EMOTION_MAP: dict[str, list[str]] = {
    # eight_node
    "opener_hook": ["困惑", "压抑", "好奇"],
    "inciting_incident": ["震惊", "威胁"],
    "first_plot_point": ["决心", "抉择"],
    "rising_action": ["蓄力", "疑虑", "威胁"],
    "midpoint": ["震惊", "觉醒"],
    "second_plot_point": ["悲痛", "失去", "绝望"],
    "climax": ["爆发", "仇恨", "清算"],
    "resolution": ["余波", "重建", "升华"],
    # three_act
    "act1_setup": ["困惑", "压抑", "稳定"],
    "act2_confrontation": ["蓄力", "威胁", "疑虑", "震惊"],
    "act3_resolution": ["爆发", "决心", "重建", "余波"],
    # compressed_three_act
    "fast_setup": ["困惑", "压抑"],
    "compressed_rising": ["威胁", "蓄力", "震惊"],
    "payoff": ["爆发", "决心", "重建"],
    # five_act
    "exposition": ["稳定", "困惑", "压抑"],
    "falling_action": ["悲痛", "失去", "揭露"],
    "catastrophe": ["爆发", "仇恨", "升华"],
    # hero_journey
    "ordinary_world": ["稳定", "安稳"],
    "call_to_adventure": ["困惑", "震惊", "威胁"],
    "ordeal": ["爆发", "悲痛", "抉择"],
    "return": ["重建", "升华", "决心"],
    # infinite_dungeon
    "entry": ["困惑", "威胁", "压抑"],
    "exploration": ["蓄力", "疑虑", "稳定"],
    "boss_fight": ["爆发", "仇恨", "决心"],
    "exit": ["重建", "升华", "余波"],
}

# 关键结构节点：这些叙事转折点要求 high-effectiveness hook
CRITICAL_HOOK_NODES: set[str] = {
    "opener_hook",
    "inciting_incident",
    "first_plot_point",
    "midpoint",
    "climax",
    "call_to_adventure",
    "ordeal",
    "boss_fight",
}

# Genre 最小规则指导
GENRE_RULES: dict[str, list[str]] = {
    "仙侠": [
        "修为突破必须有代价或限制，不能无成本升级",
        "禁术使用应留下可追踪痕迹",
        "力量体系需前后一致，同一境界的战力不应大幅波动",
    ],
    "科幻": [
        "新技术引入需有设定铺垫，不能凭空出现",
        "科技水平需保持一致性",
        "外星文明或未来技术应有合理解释或限制",
    ],
    "都市": [
        "系统流或超能力需有来源解释或限制条件",
        "现实社会规则（法律、经济）应被尊重",
        "主角优势应有代价，不能无条件碾压",
    ],
    "奇幻": [
        "魔法体系需有规则约束，不能随意破解",
        "魔法代价应明确，频繁使用应有积累后果",
        "种族/势力设定应前后一致",
    ],
}

# --- Platform Snapshots ---

PLATFORM_SNAPSHOTS: dict[str, dict] = {
    "web_novel_daily": {
        "chapter_length_target": "3000-5000",
        "update_frequency": "daily",
        "hook_pressure": "chapter_end mandatory",
        "reader_patience": "low",
        "source": "mainstream_preference",
    },
    "web_novel_serial": {
        "chapter_length_target": "2000-4000",
        "update_frequency": "2-3 per week",
        "hook_pressure": "chapter_end recommended",
        "reader_patience": "medium",
        "source": "mainstream_preference",
    },
    "short_form_burst": {
        "chapter_length_target": "1500-2500",
        "update_frequency": "burst release",
        "hook_pressure": "every 500 words",
        "reader_patience": "very low",
        "source": "school_specific",
    },
}
