"""LLM 输出 JSON 的展示层/字形修复工具（judge 评审与 plan 批量解析共用）.

prism claude-sonnet-4-6 实测三条缺陷：
1. 即便被要求「只输出 JSON」，仍会包一层 Markdown 代码围栏（```json … ```）。
2. 中文引号被写成裸 ASCII "（如 content_digest 里的 "快点儿"），使 JSON 非法。
3. 先写一段推理散文再给 JSON（judge 评审实测：响应以 "I need to carefully
   review..." 开头，JSON 对象在散文之后、尾随围栏之前）。

这里提供四层处理，供所有解析 LLM JSON 输出的入口共用：
- ``strip_code_fence``：剥围栏（展示层装饰，JSON 内容照常校验）。
- ``repair_unescaped_quotes``：字符串值内部的 " 若不是闭合定界符就转义为 \\"。
  标准合法 JSON 在此修复下逐字节不变。
- ``_balanced_object_end`` / ``_extract_first_json_object`` / ``_extract_json_candidates``：
  定位并截取（推测的）顶层 JSON 对象。实测 LLM 会在 JSON 前写推理散文，且散文里
  也可能出现 ``{...}``（如 anchor/position 说明），因此从**逐个** '{' 候选做平衡
  花括号扫描，取第一个能修复并严格解析的候选——绝不因为首个 '{' 落在散文里而放弃。
- ``parse_json``：严格解析，依次尝试原样 → 逐个候选（剥围栏+修复引号）。
"""

from __future__ import annotations

import json


def strip_code_fence(text: str) -> str:
    """去掉模型包在 JSON 外的 Markdown 代码围栏（```json … ```）.

    围栏是展示层装饰，JSON 内容本身照常校验；干净 JSON 原样通过。
    """
    s = text.strip()
    if s.startswith("```"):
        newline = s.find("\n")
        if newline == -1:
            return ""
        s = s[newline + 1 :]
    if s.endswith("```"):
        s = s[: -3].rstrip()
    return s.strip()


def repair_unescaped_quotes(text: str) -> str:
    """修复 JSON 字符串值内部未转义的 ASCII 引号（中文引号被写作裸 "）.

    修复原则：字符串内部的 " 若不是闭合定界符（其后非 ,]} 或结束），就转义为 \\"。
    标准合法 JSON 在此修复下逐字节不变。
    """
    out: list[str] = []
    in_string = False
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            if i + 1 < n:
                out.append(text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch != '"':
            out.append(ch)
            i += 1
            continue
        # 字符串内的 "：判断是否闭合定界符（其后非空白字符属于 ,]} 或结束）。
        j = i + 1
        while j < n and text[j] in " \t\r\n":
            j += 1
        nxt = text[j] if j < n else ""
        if nxt in ",]}:" or nxt == "":
            out.append(ch)
            in_string = False
        else:
            out.append('\\"')
        i += 1
    return "".join(out)


def _balanced_object_end(text: str, start: int) -> int | None:
    """从 ``text[start]=='{'`` 做平衡花括号扫描，返回顶层闭合的 '}' 下标（含）。

    字符串内的 '{'/'}' 不算结构——字符串内未转义引号用与
    ``repair_unescaped_quotes`` 相同的启发式判定（其后非 ,]} 的 " 视为内容引号），
    保证中文引语被写成裸 " 时括号计数不被内容干扰。找不到闭合返回 None。
    """
    depth = 0
    in_string = False
    escaped = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                # 内容引号（其后非 ,]}）→ 不切换 in_string。
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < n else ""
                if nxt in ",]}:" or nxt == "":
                    in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _extract_first_json_object(text: str) -> str | None:
    """截取第一个能平衡闭合的顶层 JSON 对象；找不到 '{' 返回 None.

    前导散文里的 ``{...}``（如 ``{position: "middle"}``）可能先于真正 JSON 出现，
    因此从**每个** '{' 候选做平衡扫描，取首个平衡闭合者；最后一个 '{' 若永不闭合，
    返回其到文末的尾段（兼容旧行为，仍走严格校验）。
    """
    pos = 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            return None
        end = _balanced_object_end(text, start)
        if end is not None:
            return text[start : end + 1]
        # 首个 '{' 即永不闭合：退回尾段（旧行为）。
        return text[start:]



def _extract_json_candidates(text: str):
    """按 '{' 出现顺序产出候选顶层 JSON 对象切片（含末尾永不闭合的尾段）.

    前导散文若含 ``{...}``（anchor/position 说明等），首个候选是散文里的对象，
    解析会失败但不会丢——``parse_json`` 会继续尝试下一个 '{' 候选，直到找到真正
    能严格解析的 JSON 对象。
    """
    pos = 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            return
        end = _balanced_object_end(text, start)
        if end is None:
            yield text[start:]
            return
        yield text[start : end + 1]
        pos = end + 1


def parse_json(text: str) -> object:
    """严格解析；失败时剥围栏+修复引号，再逐个 '{' 候选提取对象后重试."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        last_error = exc
    # 前导散文 + 围栏 + 未转义引号 + 散文内花括号四合一：从**原始**文本逐个 '{'
    # 提取平衡 JSON 对象候选，再单独修复提取出的切片——对整段文本先做 repair 会被
    # 散文引号污染字符串状态；首个 '{' 若落在散文里（如 {position: "middle"}），
    # 平衡扫描能把它跳过，继续找真正能严格解析的 JSON 对象。
    for candidate in _extract_json_candidates(text):
        try:
            return json.loads(repair_unescaped_quotes(strip_code_fence(candidate)))
        except (json.JSONDecodeError, TypeError) as exc:
            last_error = exc
    raise last_error

