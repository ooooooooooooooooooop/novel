"""领域层消费规则 — 合规知识访问函数.

对齐 rules.py / style_rules.py 的模式：从 compliance_knowledge.py 的表读取，
供 compliance workflow 消费。
"""

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


def get_platform_names() -> list[str]:
    """返回所有可用平台名."""
    return list(PLATFORM_POLICY.keys())
