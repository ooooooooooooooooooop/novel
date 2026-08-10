"""领域层消费规则 — 合规知识访问函数.

对齐 rules.py / style_rules.py 的模式：从 compliance_knowledge.py 的表读取，
供 compliance workflow 消费。
"""

import re

from src.domain_layer.compliance_knowledge import (
    DEFAULT_PLATFORM,
    NSFW_ALLOW_CONTENT_POLICY,
    NSFW_CATEGORY,
    NSFW_GENRE_BOUNDARIES,
    NSFW_SAFE_CONTENT_POLICY,
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


def build_lexicon_nsfw_aware(
    sensitive_on: bool,
    nsfw_on: bool,
    custom_entries: list[SensitiveEntry] | None = None,
) -> list[SensitiveEntry]:
    """构建参与扫描的敏感词条目列表（NSFW 感知）.

    - ``sensitive_on=False``: 整体跳过词库扫描（与 --sensitive off 一致）。
    - ``nsfw_on=True``: 跳过「涉黄」分类（成人向作品不扫涉黄），其余分类仍扫。
    """
    if not sensitive_on:
        return []
    categories = None
    if nsfw_on:
        categories = [
            category
            for category in get_sensitive_categories()
            if category != NSFW_CATEGORY
        ]
    all_entries = build_lexicon_from_categories(
        categories=categories, custom_entries=custom_entries
    )
    if nsfw_on:
        # 自定义词库条目不经 categories 过滤，统一再剔除涉黄，保证 NSFW 语义一致.
        all_entries = [
            entry for entry in all_entries if entry["category"] != NSFW_CATEGORY
        ]
    return all_entries


def build_nsfw_context(
    nsfw_on: bool,
    genre: str | None = None,
    theme: str | None = None,
    subgenre: str | None = None,
) -> str:
    """生成侧内容分级文案：--nsfw off 返回正常向禁令，on 返回成人向授权.

    --nsfw off 且已知题材时，按题材返回细化的禁边界文案（亲情向=无任何性化/亲密
    极克制；热血向=打斗不渲染血腥；仙侠/都市/悬疑等同理）。genre/theme/subgenre
    均为 None 或未命中题材表时，返回与旧版逐字节相同的通用禁令（零成本契约）。
    """
    if nsfw_on:
        return NSFW_ALLOW_CONTENT_POLICY
    boundary = _match_nsfw_boundary(genre, theme, subgenre)
    return boundary if boundary is not None else NSFW_SAFE_CONTENT_POLICY


def _match_nsfw_boundary(
    genre: str | None, theme: str | None, subgenre: str | None
) -> str | None:
    """在题材表内做子串匹配，返回首个命中的禁边界文案；未命中返回 None.

    匹配优先级：theme（题材意图最具体，亲情/热血等主题词优先于宽泛 genre）
    → subgenre → genre。子串匹配容忍组合题材（如「仙侠言情」命中「仙侠」）。
    """
    for value in (theme, subgenre, genre):
        if not value:
            continue
        for key, text in NSFW_GENRE_BOUNDARIES.items():
            if key in value:
                return text
    return None


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
