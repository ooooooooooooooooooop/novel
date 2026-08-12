"""A1 T4/T5 — 语义接缝：上章末/本章首事件重演阻断（doc 48 §6 step 4/5）.

目标（tasks.md T4.3 / T5）：
- 同一事件（参与者∩ + 行为 + 结果 + 状态变化 全等）在相邻章首尾重演 → 阻断；
- 回忆产生新状态 → 不误杀（状态变化不同，fingerprint 不全等）；
- 真幻不明（certainty=ambiguous）→ 不当作事实冲突或重演证据（S3 反例）。

事实来源是事件的结构化指纹，不是固定句式列表。``_normalize`` 只剥离不改变事件
身份的时体/副词虚词（了/又/再一次…），不承担「检测事件」的功能；epistemic
情态标记只用于把句子降级为 ``ambiguous``（宁可不作为事实主张），同样不是
「以固定句式作为事实来源」。

提取是确定性启发式：按句子切分 → 参与者（实体注册表）命中 → 规范化行为核心 →
连接词后落点作 result/state_change。真实长文为尽力而为；测试夹具直接构造
指纹或书写可确定提取的句子。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Literal

from src.object_state.event_fingerprint import EventFingerprint, SeamReplayFinding

# 只剥离时体/副词虚词——整词匹配，最长优先；不拆字符（否则「终于」剥出「于」会
# 破坏「于是」、接着 剥出「接」会破坏「接到电话」，改变事件身份）。
_PARTICLE_RE = re.compile(
    "|".join(
        sorted(
            (
                "再一次", "又一次", "已经", "忽然", "终于", "顿时", "立刻",
                "猛地", "骤地", "竟然", "然后", "接著", "接着",
                "了", "又", "再", "已",
            ),
            key=len,
            reverse=True,
        )
    )
)
_PUNCT_RE = re.compile(
    r"[\s，。！？；：、,.!?;:“”‘’—…・、"
    r"\(\)\[\]{}<>《》「」『』（）【】“”‘’～~·　]+"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?…])|\n+")
# 主事代词：主语以代词指代实体时，代词不改变事件身份；参与者身份由实体名命中
# （participants）承担，代词本身不参与指纹比较。
_PRONOUN_RE = re.compile(
    "|".join(
        sorted(
            (
                "他们", "她们", "它们", "自己", "我们", "你们", "大家", "有人",
                "咱们", "彼此", "他", "她", "它", "我", "你",
            ),
            key=len,
            reverse=True,
        )
    )
)

# epistemic 情态/真幻不明标记：命中 → certainty=ambiguous（不作为确证事实主张）。
# 这是「宁可不主张」的保守降级，与「以固定句式作为事实来源」相反。
_EPISTEMIC_MARKERS = (
    "分不清", "不确定", "不知道是真是假", "不知道是不是真的", "不知道是不是梦",
    "像梦", "如梦", "仿佛", "恍如", "似乎是", "像是", "大概", "也许", "或许",
    "似乎", "隐约觉得", "半信半疑", "真的还是假的", "现实还是幻觉", "真假难辨",
    "是真实还是", "是梦还是", "不知是真是幻", "恍恍惚惚",
)

# 句中连接词：其后部分为 result/state_change 落点（终于在 _PARTICLE_RE 中剥离，
# 不作为连接词处理，避免与副词剥离语义冲突）。
_CONNECTIVE_MATCHER = re.compile(r"(但|却|于是|然后|便|就|因此|从而|所以)")


def _normalize(text: str) -> str:
    """规范化：NFKC + 去标点空白 + 剥离婚配/时体虚词 + 剥主事代词。"""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _PUNCT_RE.sub("", cleaned)
    cleaned = _PRONOUN_RE.sub("", cleaned)
    cleaned = _PARTICLE_RE.sub("", cleaned)
    return cleaned.strip()


def _is_ambiguous(text: str) -> bool:
    """句子是否携带真幻不明 / epistemic 情态。"""
    return any(marker in text for marker in _EPISTEMIC_MARKERS)


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(text or "") if sentence.strip()]


def _subject_of(sentence: str, entity_names: list[str]) -> str:
    """行为者推断：首个出现的实体为行为者；句首主事代词（在实体前）→ 不可解析 ""。

    主语是代词的句子无法从实体表解析行为者——这种情况下 subject="" 由重演判断
    的 actor 规则处理（假定与上一章末同一行为者，但不跨实体误杀）。
    """
    positions = [(sentence.find(entity), entity) for entity in entity_names if entity in sentence]
    positions = [(pos, entity) for pos, entity in positions if pos >= 0]
    if not positions:
        return ""
    first_pos, first_entity = min(positions)
    leading_pronoun = any(match.start() < first_pos for match in _PRONOUN_RE.finditer(sentence))
    return "" if leading_pronoun else first_entity


def _strip_participants(text: str, participants: list[str]) -> str:
    stripped = text
    for participant in sorted(participants, key=len, reverse=True):
        stripped = stripped.replace(participant, "")
    return stripped


def _trailing_result(core: str) -> tuple[str, str]:
    """连接词后落点作 result；核心其余作行为主体。

    返回 (behavior, result)。无连接词时 result 为空串。
    """
    match = _CONNECTIVE_MATCHER.search(core)
    if match is None:
        return core, ""
    split_at = match.start()
    return core[:split_at], core[match.end():]


def extract_event_fingerprints(
    text: str,
    *,
    chapter_number: int,
    entities: Iterable[str],
    position: Literal["start", "end", "middle"] = "middle",
) -> list[EventFingerprint]:
    """从一章文本确定性提取事件指纹（尽力而为，夹具可精确构造）。"""
    entity_names = sorted({entity for entity in entities if entity and entity.strip()})
    fingerprints: list[EventFingerprint] = []
    for index, sentence in enumerate(_split_sentences(text)):
        present = [entity for entity in entity_names if entity in sentence]
        if not present:
            continue
        core = _normalize(_strip_participants(sentence, present))
        if not core:
            continue
        behavior, result = _trailing_result(core)
        other_entities = [entity for entity in present[1:]]
        fingerprints.append(
            EventFingerprint(
                event_id=f"ev_{chapter_number:04d}_{position}_{index + 1:03d}",
                chapter_number=chapter_number,
                position=position,
                participants=tuple(present),
                subject=_subject_of(sentence, entity_names),
                behavior=behavior,
                object="、".join(other_entities) if other_entities else "",
                result=result,
                state_change=result,
                certainty="ambiguous" if _is_ambiguous(sentence) else "certain",
            )
        )
    return fingerprints


def detect_event_replay(
    previous: list[EventFingerprint],
    new: list[EventFingerprint],
    *,
    window: int = 1,
) -> list[SeamReplayFinding]:
    """上一章末/本章首事件重演判断（确定性）。

    重演 = 两个确证事件（certainty=certain）满足：
    - 参与者集合相交（≥1 共同实体）；
    - 行为核心规范化全等；
    - 结果与状态变化规范化全等；
    - 章距 ≤ window。
    任一项不同即不构成重演（如回忆产生新状态、真幻不明）。歧义事件不参与。
    """
    findings: list[SeamReplayFinding] = []
    previous_pool = [event for event in previous if event.certainty == "certain"]
    for new_event in new:
        if new_event.certainty != "certain":
            continue
        for prev_event in previous_pool:
            gap = new_event.chapter_number - prev_event.chapter_number
            if gap < 0 or gap > window:
                continue
            if not (set(new_event.participants) & set(prev_event.participants)):
                continue
            # 行为者判别：双方都可解析时须同一行为者（防跨角色同行为误杀）；
            # 新事件主语为代词（不可解析）时假定与上一章末同一行为者。
            if new_event.subject and prev_event.subject:
                if new_event.subject != prev_event.subject:
                    continue
            if _normalize(new_event.behavior) != _normalize(prev_event.behavior):
                continue
            if _normalize(new_event.result) != _normalize(prev_event.result):
                continue
            if _normalize(new_event.state_change) != _normalize(prev_event.state_change):
                continue
            findings.append(
                SeamReplayFinding(
                    finding_id=(
                        f"seam_replay_{new_event.event_id}_vs_{prev_event.event_id}"
                    ),
                    issue_type="seam_event_replay",
                    previous_event_id=prev_event.event_id,
                    new_event_id=new_event.event_id,
                    chapter_gap=gap,
                    description=(
                        f"本章首事件与上一章末重演：参与者 {','.join(new_event.participants)}"
                        f" 行为『{new_event.behavior}』结果『{new_event.result}』"
                        f"在 {gap} 章内原样再现，无新状态变化"
                    ),
                )
            )
    return findings


def character_names(characters: Iterable) -> list[str]:
    """从 CharacterModel 列表收集可参与匹配的角色名（去空去重）。"""
    names: list[str] = []
    for character in characters:
        name = getattr(character, "name", "")
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    return names
