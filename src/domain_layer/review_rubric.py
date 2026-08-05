"""WebNovelBench 8 维本地评测 rubric — 领域知识导出.

把 ReviewUnit 的 code rules（_hard_rules / _domain_rules）+ web_fiction.py 领域知识
按 WebNovelBench（arXiv:2505.14818）8 个评测维度映射为可导出的本地 rubric。

规则知识，非事实，非推断。纯数据 + 渲染，纯 stdlib，offline。
不 import web_fiction / rules（引用是字符串名，模块是惰性数据表）。

诚实标注：本系统审查的对象是叙事对象层（PlotUnit / NarrativeState /
CharacterModel / FactLedger / ForeshadowGraph），不是正文文本。因此 LLM-judge
维（感官描述丰富度 / 对白独特性等）无本地规则，local_signal_strength 标 "none"；
有代码代理的维度按覆盖厚度标 "weak" / "moderate" / "strong"。
"""

import json
from typing import TypedDict


class RubricDimension(TypedDict):
    id: str  # "wnb_01" ... "wnb_08"
    name_cn: str
    name_en: str
    description: str
    evaluation_focus: list[str]
    mapped_issue_types: list[str]  # ReviewIssueType 子集
    mapped_rule_ids: list[str]  # review.py issue_id 前缀
    evidence_sources: list[str]  # "web_fiction.py:NODE_EMOTION_MAP" 等
    local_signal_strength: str  # "strong" | "moderate" | "weak" | "none"
    notes: str  # 诚实标注，如 "LLM-judge dimension, no local rule"


REVIEW_RUBRIC: list[RubricDimension] = [
    {
        "id": "wnb_01",
        "name_cn": "修辞手法",
        "name_en": "Literary Devices",
        "description": "修辞手法与句式变化是否丰富，避免空转壳句式与重复比喻",
        "evaluation_focus": ["重复喻体密度", "壳句式（不是A而是B / 四连排比）", "弱化副词"],
        "mapped_issue_types": ["generative_indicia"],
        "mapped_rule_ids": ["iss_genind", "iss_genind2", "iss_genind3", "iss_layering"],
        "evidence_sources": [
            "web_fiction.py:HOOK_TAXONOMY(paragraph.sensory_detail)",
            "style_knowledge.py:AI_FLAVOR_MARKERS(ai_parallel_four/ai_shell_not_a_but_b/ai_metaphor_repeat)",
        ],
        "local_signal_strength": "weak",
        "notes": "负向代理：不测修辞丰富度，只测 AI 味重复；正向丰富度无本地规则",
    },
    {
        "id": "wnb_02",
        "name_cn": "感官描述丰富度",
        "name_en": "Sensory Detail",
        "description": "五感（视/听/触/嗅/味）描述是否丰富，而非单感官堆叠",
        "evaluation_focus": ["感官锚点存在性", "多感官覆盖面"],
        "mapped_issue_types": [],
        "mapped_rule_ids": [],
        "evidence_sources": [
            "web_fiction.py:HOOK_TAXONOMY(paragraph.sensory_detail)",
        ],
        "local_signal_strength": "none",
        "notes": "LLM-judge 维度，无本地规则——对象层不含正文文本，旗舰诚实标注",
    },
    {
        "id": "wnb_03",
        "name_cn": "角色平衡度",
        "name_en": "Character Presence",
        "description": "角色戏份与存在感是否平衡，配角是否立体而非陪衬",
        "evaluation_focus": ["参与者分布", "活跃角色覆盖"],
        "mapped_issue_types": [],
        "mapped_rule_ids": [],
        "evidence_sources": [
            "PlotUnit.participants",
            "NarrativeState.active_characters",
            "CharacterModel.relations",
        ],
        "local_signal_strength": "none",
        "notes": "数据在（参与者/活跃角色/关系网络），但无平衡度规则；留白给人工/LLM 评测",
    },
    {
        "id": "wnb_04",
        "name_cn": "角色对白独特性",
        "name_en": "Character Dialogue",
        "description": "对白是否贴合角色身份/性格，是否可区分不同说话者",
        "evaluation_focus": ["对话标签滥用", "对白口语化/个性化"],
        "mapped_issue_types": [],
        "mapped_rule_ids": [],
        "evidence_sources": [
            "style_knowledge.py:AI_FLAVOR_MARKERS(ai_dialogue_tag_density)",
        ],
        "local_signal_strength": "none",
        "notes": "仅负向代理（对话标签密度），不足以支撑该维度；对象层无对白正文",
    },
    {
        "id": "wnb_05",
        "name_cn": "角色一致性",
        "name_en": "Character Consistency",
        "description": "角色行为逻辑是否自洽，认知/关系/参与者引用是否一致",
        "evaluation_focus": ["knowledge/misinformation 互斥", "关系引用完整性", "活跃角色/参与者引用完整性", "情绪-结构节点匹配", "信息凭证一致性"],
        "mapped_issue_types": ["character_distortion"],
        "mapped_rule_ids": [
            "iss_hard_overlap",
            "iss_hard_rel",
            "iss_hard_active_character",
            "iss_hard_plotunit_participant",
            "iss_agency",
            "iss_info_channel",
            "iss_info_relay",
            "iss_info_scope",
        ],
        "evidence_sources": [
            "review.py:_hard_rules(1,4,5-participants)",
            "web_fiction.py:NODE_EMOTION_MAP",
            "rules.py:validate_node_emotion",
            "web_fiction.py:GENRE_RULES",
            "info_warrant_knowledge.py:FIRSTHAND_DETAIL_MARKERS/RELAY_MARKERS/UNKNOWN_NEGATION_MARKERS",
        ],
        "local_signal_strength": "strong",
        "notes": "对象层引用完整性 + 情绪-节点匹配 + 信息凭证弱信号（P1/P2/P3/P4），最厚本地覆盖",
    },
    {
        "id": "wnb_06",
        "name_cn": "意境匹配度",
        "name_en": "Atmospheric/Thematic",
        "description": "场景情绪与结构节点/类型惯例是否匹配，意境是否贴合",
        "evaluation_focus": ["情绪弧-结构节点对齐", "关键节点钩子质量", "类型风格引导"],
        "mapped_issue_types": ["weak_progression"],
        "mapped_rule_ids": ["iss_emotion_match", "iss_emotion", "iss_hook_eff"],
        "evidence_sources": [
            "web_fiction.py:NODE_EMOTION_MAP/EMOTIONAL_ARC_TEMPLATES/CRITICAL_HOOK_NODES/GENRE_RULES",
            "style_knowledge.py:GENRE_STYLE_GUIDANCE/TONE_STYLE_TRAITS",
            "rules.py:validate_node_emotion",
            "rules.py:is_critical_hook_node",
            "rules.py:get_hook_effectiveness",
        ],
        "local_signal_strength": "moderate",
        "notes": "结构代理：情绪弧-结构节点对齐 + 关键节点钩子质量",
    },
    {
        "id": "wnb_07",
        "name_cn": "语境适配度",
        "name_en": "Contextual Appropriateness",
        "description": "内容与平台/读者耐心/当前单元语境是否适配",
        "evaluation_focus": ["hook 合法性", "平台约束满足度", "生成痕迹词密度"],
        "mapped_issue_types": ["weak_progression", "generative_indicia"],
        "mapped_rule_ids": [
            "iss_hook",
            "iss_platform_hook",
            "iss_platform_patience",
            "iss_genind",
            "iss_genind2",
        ],
        "evidence_sources": [
            "web_fiction.py:HOOK_TAXONOMY/PLATFORM_SNAPSHOTS",
            "rules.py:validate_plotunit_hook",
            "rules.py:get_platform_constraints",
            "rules.py:build_platform_guidance",
        ],
        "local_signal_strength": "moderate",
        "notes": "平台约束 + hook 合法性 + 生成痕迹词，语境适配的部分代码代理",
    },
    {
        "id": "wnb_08",
        "name_cn": "跨场景衔接度",
        "name_en": "Scene-to-Scene Coherence",
        "description": "场景/单元之间状态链、伏笔、时间线是否连贯承接",
        "evaluation_focus": ["state 引用链连续性", "伏笔引用完整性", "时间线矛盾", "空数据基础检查"],
        "mapped_issue_types": ["weak_progression", "promise_loss", "fact_conflict"],
        "mapped_rule_ids": [
            "iss_hard_input_state_ref",
            "iss_hard_state_ref",
            "iss_hard_ineffective",
            "iss_hard_foreshadow",
            "iss_hard_time",
            "iss_hard_empty_fl",
            "iss_hard_empty_fg",
        ],
        "evidence_sources": [
            "review.py:_hard_rules(5,6,7,2,3)",
            "PlotUnit state-refs",
            "ForeshadowGraph",
            "FactLedger(time_order)",
            "web_fiction.py:GENRE_FORMULAS",
        ],
        "local_signal_strength": "strong",
        "notes": "状态链连续性 + 伏笔引用 + 时间线矛盾 + 空数据检查，跨场景衔接最厚覆盖",
    },
]

# 时间一致性维（wnb_09）—— 仅在存在 timeline_report.json 时挂载（P8 先置）。
# 默认保持 8 维（len(REVIEW_RUBRIC)==8 契约不变），有报告才扩为 9 维。
TIME_CONSISTENCY_DIMENSION: RubricDimension = {
    "id": "wnb_09",
    "name_cn": "时间一致性",
    "name_en": "Temporal Coherence",
    "description": "章节时间锚点、先知/时间线时效与季节历法是否符合设定，叙事时间是否连贯",
    "evaluation_focus": ["章节时间锚单调性", "先知/时间线时效", "季节/历法规则", "事件时间有效性"],
    "mapped_issue_types": ["timeline_error", "fact_conflict"],
    "mapped_rule_ids": [
        "iss_time_regress",
        "iss_time_foreshadow_expired",
        "iss_time_timeline_ended",
        "iss_time_season",
        "iss_hard_time",
    ],
    "evidence_sources": [
        "time_audit.py:run_time_audit(det4/5/6)",
        "time_audit.py:_detect_anchor_regression",
        "time_audit.py:_detect_foreshadow_expiry",
        "time_audit.py:_detect_season_violation",
        "timebook.py:extract_time_anchors",
    ],
    "local_signal_strength": "moderate",
    "notes": "FACTTRACK v2 代码检测；仅在存在 TimeBook/timeline_report 时生效（无报告不挂载此维）",
}

RUBRIC_SCHEMA_VERSION = 1


def export_rubric(timeline_report: dict | None = None) -> dict:
    """导出完整 rubric 包（schema 头 + 8 维，有 timeline_report 时 + 时间一致性维）.

    Args:
        timeline_report: audit / `novel time --check` 的 timeline_report.json 内容；
            非 None 时挂载 wnb_09（时间一致性）维（P8 先置）。
    """
    dimensions = list(REVIEW_RUBRIC)
    if timeline_report is not None:
        dimensions.append(TIME_CONSISTENCY_DIMENSION)
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "benchmark": "WebNovelBench",
        "benchmark_reference": "arXiv:2505.14818",
        "source": "local-domain-rules",
        "offline": True,
        "dimensions": dimensions,
    }


def render_rubric_json(timeline_report: dict | None = None) -> str:
    """渲染 rubric 为 JSON 字符串（ensure_ascii=False + 2 缩进）."""
    return json.dumps(export_rubric(timeline_report), ensure_ascii=False, indent=2)
