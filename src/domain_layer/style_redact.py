"""风格档案入库脱敏 — 中性命名红线落地.

红线（CLAUDE.md）：风格库允许入库的是"中性写作风格积累"，统一放仓库根
`style_library/<name>.json`，不得含小说名 / 作者笔名 / 机器路径 / 具体角色名。

本模块在 style 流写库前对 StyleProfile 做脱敏（工作区本地 profile 保留真实
信息，只有入库副本脱敏）：
- 确定性脱敏：`source_text_ref` 去机器路径，仅保留中性文件名；
- 实体词替换：调用方传入 {原词: 占位} 映射，递归替换所有字符串字段
  （含列表 / 嵌套对象内的字符串）。

设计：
- `redact_profile` 返回深拷贝，不改动原 profile（工作区档案仍可复用）；
- 未传替换词表时仍做 source_text_ref 确定性脱敏（最小红线保障）；
- 占位符由调用方显式给出（`assign_placeholders` 可自动分配 角色A/B…）。
"""

from __future__ import annotations

import re

from src.object_state.styleprofile import StyleProfile

# 兼容 \ 与 / 的路径分隔（Windows 反斜杠在 POSIX 下是字面字符，需统一）。
_PATH_SEP = re.compile(r"[\\/]")


def sanitize_source_ref(ref: str) -> str:
    """去机器路径，仅保留文件名（含扩展名）。

    例：`D:\\x\\novels\\示例\\input.txt` -> `input.txt`。
    空串或无法取尾段时原样返回。
    """
    if not ref:
        return ref
    tail = _PATH_SEP.split(str(ref))[-1]
    return tail if tail else ref


def redact_text(text: str, replacements: dict[str, str]) -> str:
    """把 text 中出现的实体词替换为占位符.

    按原词长度降序替换，避免"主角"命中"主角集团"等前缀的子串误伤。
    """
    if not text:
        return text
    for term, repl in sorted(
        replacements.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if term in text:
            text = text.replace(term, repl)
    return text


def _redact_value(value, replacements: dict[str, str]):
    """递归替换字符串字段（标量 / 列表 / 嵌套 dict）。"""
    if isinstance(value, str):
        return redact_text(value, replacements)
    if isinstance(value, list):
        return [_redact_value(v, replacements) for v in value]
    if isinstance(value, dict):
        return {k: _redact_value(v, replacements) for k, v in value.items()}
    return value


def redact_profile(
    profile: StyleProfile, replacements: dict[str, str] | None = None
) -> StyleProfile:
    """返回脱敏后的 StyleProfile（深拷贝，原 profile 不变）.

    - 确定性：source_text_ref 去机器路径仅留文件名；
    - 实体词：replacements {原词: 占位} 应用到全部字符串字段。
    未传 replacements 时仅做 source_text_ref 确定性脱敏。
    """
    data = profile.model_dump(mode="json")
    ref = data.get("source_text_ref")
    if isinstance(ref, str):
        data["source_text_ref"] = sanitize_source_ref(ref)
    if replacements:
        data = _redact_value(data, replacements)
    return StyleProfile.model_validate(data)


def assign_placeholders(terms: list[str]) -> dict[str, str]:
    """为实体词表自动分配中性占位符：{原词: 角色A/角色B/…}（按输入顺序）."""
    return {
        term: f"角色{chr(ord('A') + i)}"
        for i, term in enumerate(terms)
        if term and term.strip()
    }


def parse_redact_arg(raw: str | None) -> list[str]:
    """解析 --redact "词1,词2" 参数（兼容中英文逗号、空白），返回词表."""
    if not raw:
        return []
    terms = [t.strip() for t in re.split(r"[，,]", raw) if t.strip()]
    return terms
