"""领域层消费规则 — 信息凭证知识访问函数.

对齐 style_rules.py 的模式：从 info_warrant_knowledge.py 的表读取并渲染为
LLM 可理解的指导文本。
"""

from src.domain_layer.info_warrant_knowledge import (
    FIRSTHAND_DETAIL_MARKERS,
    FOCALIZATION_TYPES,
    INFO_CHANNELS,
    INFO_GAP_FORMS,
    RELAY_MARKERS,
    UNKNOWN_NEGATION_MARKERS,
    WARRANT_CONSTRAINTS,
)
from src.domain_layer.info_warrant_knowledge import (
    FocalizationType,
    InfoChannel,
    InfoGapForm,
    WarrantConstraint,
)


def get_info_channels() -> list[InfoChannel]:
    """信息通道谱系（亲历/转述/书面/公开/推断/记忆）."""
    return INFO_CHANNELS


def get_focalization_types() -> list[FocalizationType]:
    """聚焦三分（零/内/外，Genette）."""
    return FOCALIZATION_TYPES


def get_warrant_constraints() -> list[WarrantConstraint]:
    """四条凭证约束（P1-P4）."""
    return WARRANT_CONSTRAINTS


def get_info_gap_forms() -> list[InfoGapForm]:
    """信息差距形态（合法 4 种 + 非法 4 种）."""
    return INFO_GAP_FORMS


def get_firsthand_detail_markers() -> frozenset[str]:
    """亲历型细节触发词集（iss_info_channel_* 弱信号用）."""
    return FIRSTHAND_DETAIL_MARKERS


def get_unknown_negation_markers() -> frozenset[str]:
    """未知/未接触否定词集（iss_info_channel_* 弱信号用）."""
    return UNKNOWN_NEGATION_MARKERS


def get_relay_markers() -> frozenset[str]:
    """转述通道标记词集（iss_info_relay_* 弱信号用）."""
    return RELAY_MARKERS


def build_info_warrant_guidance() -> str:
    """渲染信息凭证约束为 LLM 可理解的指导文本（审查 prompt 注入用）.

    覆盖：通道谱系 + 聚焦三分 + 四条凭证约束。返回非空串；无空轴（纯数据表）。
    """
    sections: list[str] = []

    channel_lines = ["【信息通道谱系】"]
    for ch in INFO_CHANNELS:
        channel_lines.append(
            f"- {ch['name']}: {ch['definition']}（可产出: {ch['detail_capacity']}）"
        )
    sections.append("\n".join(channel_lines))

    focal_lines = ["【聚焦三分】"]
    for f in FOCALIZATION_TYPES:
        focal_lines.append(
            f"- {f['name']}: {f['definition']}（{f['narrator_relation']}）"
        )
    sections.append("\n".join(focal_lines))

    warrant_lines = ["【凭证约束】"]
    for c in WARRANT_CONSTRAINTS:
        warrant_lines.append(f"- {c['rule_id']} {c['name']}: {c['definition']}")
        warrant_lines.append(f"  指令: {c['instruction']}")
        warrant_lines.append(f"  误用警示: {c['misuse']}")
    sections.append("\n".join(warrant_lines))

    return "\n\n".join(sections)
