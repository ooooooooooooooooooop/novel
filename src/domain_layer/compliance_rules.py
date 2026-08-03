"""领域层消费规则 — 合规知识访问函数.

对齐 rules.py / style_rules.py 的模式：从 compliance_knowledge.py 的表读取，
供 compliance workflow 消费。
"""

import re

from src.domain_layer.compliance_knowledge import (
    DEFAULT_PLATFORM,
    PLATFORM_POLICY,
    SENSITIVE_LEXICON,
    SensitiveEntry,
)


def get_sensitive_entries() -> list[SensitiveEntry]:
    """获取全部敏感词条目（展平所有分类）."""
    entries: list[SensitiveEntry] = []
    for category_entries in SENSITIVE_LEXICON.values():
        entries.extend(category_entries)
    return entries


def get_sensitive_categories() -> list[str]:
    """返回所有敏感词分类名."""
    return list(SENSITIVE_LEXICON.keys())


def build_lexicon_from_categories(
    categories: list[str] | None = None,
    custom_entries: list[SensitiveEntry] | None = None,
) -> list[SensitiveEntry]:
    """构建参与扫描的敏感词条目列表.

    Args:
        categories: 只扫描指定分类；None 表示全部分类。
        custom_entries: 自定义词库条目（--lexicon 导入），与内置合并。
    """
    all_entries = get_sensitive_entries()
    if categories is not None:
        allowed = set(categories)
        all_entries = [
            entry for entry in all_entries if entry["category"] in allowed
        ]
    if custom_entries:
        all_entries = [*all_entries, *custom_entries]
    return all_entries


def get_platform_policy(platform: str) -> dict:
    """获取平台政策；未知平台回退通用."""
    return PLATFORM_POLICY.get(platform) or PLATFORM_POLICY[DEFAULT_PLATFORM]


def parse_chapter_length_target(target: str) -> tuple[int, int] | None:
    """解析平台章节字数目标 'X-Y' 为 (lower, upper)；无法解析返回 None.

    '2000-3000' -> (2000, 3000)；'3000' -> (3000, 3000)；坏输入 -> None。
    """
    match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", target)
    if not match:
        return None
    lower = int(match.group(1))
    upper = int(match.group(2)) if match.group(2) else lower
    return (lower, upper)


def get_platform_names() -> list[str]:
    """返回所有可用平台名."""
    return list(PLATFORM_POLICY.keys())
