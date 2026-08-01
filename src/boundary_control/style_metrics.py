"""风格量化分析器 — 纯代码，无 LLM.

把《写作技巧总结.md》的量化清单自动化：句长分布、弱化副词密度、
比喻复用、解释腔、壳句式、四连排比、对话占比、对话标签、情绪宣布词、
破折号/冒号密度。
"""

import re

from src.domain_layer.style_knowledge import (
    DIALOGUE_TAG_OVERUSE,
    EMOTION_ANNOUNCEMENT_PHRASES,
    EXPLANATORY_PHRASES,
    SHELL_NOT_A_BUT_B_RE,
    WEAK_ADVERB_SET,
)
from src.object_state.styleprofile import (
    MetaphorHit,
    StyleQuantitativeStats,
)

_SENTENCE_END_RE = re.compile(r"[。！？；…\n]+")
_METAPHOR_RE = re.compile(
    r"(?:像|如|仿佛|好似|宛如)\s*([一-龥]{1,3}?)(?:一样|一般|似的|般)"
)
_SHELL_RE = re.compile(SHELL_NOT_A_BUT_B_RE)
_QUOTE_RE = re.compile(r"[“\"「]")
_CLAUSE_SPLIT_RE = re.compile(r"[，、,；;]")
_ANAPHORA_PREFIX_LEN = 2
_ANAPHORA_MIN_CLAUSES = 4
_ANAPHORA_MIN_SAME_PREFIX = 3

SHORT_SENTENCE_MAX = 8
LONG_SENTENCE_MIN = 30
METAPHOR_MIN_COUNT = 3


def _split_sentences(text: str) -> list[str]:
    """按句末标点/换行切分句子."""
    parts = [part.strip() for part in _SENTENCE_END_RE.split(text)]
    return [part for part in parts if part]


def _count_occurrences(text: str, phrases: list[str]) -> int:
    """统计短语出现总次数."""
    return sum(text.count(phrase) for phrase in phrases)


def _count_occurrences_map(text: str, words: set[str]) -> dict[str, int]:
    """统计集合中每个词的出现次数."""
    counts: dict[str, int] = {}
    for word in words:
        count = text.count(word)
        if count:
            counts[word] = count
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _percentile(values: list[float], pct: float) -> float:
    """线性插值百分位."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * pct
    lower = int(index)
    upper = lower + 1
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def detect_weak_adverbs(text: str) -> tuple[float, dict[str, int]]:
    """弱化副词密度（每千字）及逐词计数."""
    counts = _count_occurrences_map(text, WEAK_ADVERB_SET)
    total = sum(counts.values())
    density = total / len(text) * 1000 if text else 0.0
    return density, counts


def detect_metaphor_repeats(text: str, min_count: int = METAPHOR_MIN_COUNT) -> list[MetaphorHit]:
    """提取 像/如/仿佛…一样 后的喻体，count≥min_count 记 hit.

    启发式规则，预期有误报；保留样例片段供人工复核。
    """
    vehicle_counts: dict[str, list[str]] = {}
    for match in _METAPHOR_RE.finditer(text):
        vehicle = match.group(1)
        snippet_start = max(0, match.start() - 8)
        snippet = text[snippet_start : match.end() + 8].replace("\n", " ")
        vehicle_counts.setdefault(vehicle, []).append(snippet)

    hits: list[MetaphorHit] = []
    for vehicle, snippets in vehicle_counts.items():
        if len(snippets) >= min_count:
            hits.append(
                MetaphorHit(
                    vehicle=vehicle,
                    count=len(snippets),
                    sample_snippets=snippets[:3],
                )
            )
    return sorted(hits, key=lambda hit: -hit.count)


def detect_explanatory_phrases(text: str) -> int:
    """解释腔句式计数."""
    return _count_occurrences(text, EXPLANATORY_PHRASES)


def detect_parallel_four(text: str) -> int:
    """检测同构排比（≥4 分句且 ≥3 个共享同一 2 字前缀）.

    用首语重复（anaphora）判同构，避免把任意逗号长句误判为排比。
    """
    count = 0
    for sentence in _SENTENCE_END_RE.split(text):
        clauses = [
            clause.strip()
            for clause in _CLAUSE_SPLIT_RE.split(sentence)
            if clause.strip()
        ]
        if len(clauses) < _ANAPHORA_MIN_CLAUSES:
            continue
        prefix_counts: dict[str, int] = {}
        for clause in clauses:
            if len(clause) >= _ANAPHORA_PREFIX_LEN:
                prefix = clause[:_ANAPHORA_PREFIX_LEN]
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        if any(count_ >= _ANAPHORA_MIN_SAME_PREFIX for count_ in prefix_counts.values()):
            count += 1
    return count


def detect_shell_patterns(text: str) -> dict[str, int]:
    """壳句式计数: not_a_but_b + parallel4."""
    not_a_but_b = len(_SHELL_RE.findall(text))
    parallel4 = detect_parallel_four(text)
    counts: dict[str, int] = {}
    if not_a_but_b:
        counts["not_a_but_b"] = not_a_but_b
    if parallel4:
        counts["parallel4"] = parallel4
    return counts


def sentence_length_distribution(sentences: list[str]) -> dict[str, float]:
    """句长分布: 平均/短句占比/长句占比."""
    if not sentences:
        return {
            "avg": 0.0,
            "short_ratio": 0.0,
            "long_ratio": 0.0,
        }
    lengths = [float(len(s)) for s in sentences]
    short_count = sum(1 for length in lengths if length <= SHORT_SENTENCE_MAX)
    long_count = sum(1 for length in lengths if length >= LONG_SENTENCE_MIN)
    return {
        "avg": sum(lengths) / len(lengths),
        "short_ratio": short_count / len(lengths),
        "long_ratio": long_count / len(lengths),
    }


def dialogue_ratio(sentences: list[str]) -> float:
    """含引号句子占比（对话特征）."""
    if not sentences:
        return 0.0
    quoted = sum(1 for sentence in sentences if _QUOTE_RE.search(sentence))
    return quoted / len(sentences)


def detect_dialogue_tags(text: str) -> float:
    """对话标签密度（说道/问道/沉声道，每千字）."""
    total = _count_occurrences(text, DIALOGUE_TAG_OVERUSE)
    return total / len(text) * 1000 if text else 0.0


def detect_emotion_announcements(text: str) -> int:
    """情绪宣布词计数."""
    return _count_occurrences(text, EMOTION_ANNOUNCEMENT_PHRASES)


def detect_dash_colons(text: str) -> float:
    """破折号+冒号密度（每千字）.

    破折号按 '—' 字符计（—— 含两个 —，自然计入），冒号计 '：'。
    """
    total = text.count("—") + text.count("：")
    return total / len(text) * 1000 if text else 0.0


def analyze_style_metrics(text: str) -> StyleQuantitativeStats:
    """对全文做纯代码量化分析."""
    sentences = _split_sentences(text)
    distribution = sentence_length_distribution(sentences)
    weak_density, weak_counts = detect_weak_adverbs(text)

    return StyleQuantitativeStats(
        total_chars=len(text),
        sentence_count=len(sentences),
        avg_sentence_len=round(distribution["avg"], 2),
        short_sentence_ratio=round(distribution["short_ratio"], 4),
        long_sentence_ratio=round(distribution["long_ratio"], 4),
        dialogue_ratio=round(dialogue_ratio(sentences), 4),
        weak_adverb_density_per_1000=round(weak_density, 2),
        weak_adverb_counts=weak_counts,
        metaphor_repeats=detect_metaphor_repeats(text),
        explanatory_phrase_count=detect_explanatory_phrases(text),
        shell_counts=detect_shell_patterns(text),
        dialogue_tag_density_per_1000=round(detect_dialogue_tags(text), 2),
        emotion_announcement_count=detect_emotion_announcements(text),
        dash_colon_density_per_1000=round(detect_dash_colons(text), 2),
    )
