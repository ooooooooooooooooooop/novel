"""风格量化分析器 — 纯代码，无 LLM.

把《写作技巧总结.md》的量化清单自动化：句长分布、弱化副词密度、
比喻复用、解释腔、壳句式、四连排比、对话占比、对话标签、情绪宣布词、
破折号/冒号密度。
"""

import re

from src.domain_layer.style_knowledge import (
    CONNECTIVE_ABUSE_OPENERS,
    DIALOGUE_TAG_OVERUSE,
    EMOTION_ANNOUNCEMENT_PHRASES,
    EXPLANATORY_PHRASES,
    SHELL_NOT_A_BUT_B_RE,
    WEAK_ADVERB_SET,
)
from src.domain_layer.style_lexicon import (
    ACTION_VERBS,
    BYSTANDER_REACTION_PHRASES,
    DECISION_GROUNDING_MARKERS,
    EXPLICIT_TRANSITION_MARKERS,
    INNER_MONOLOGUE_PHRASES,
    MODIFIER_ADVERBS,
    PSYCH_VERBS,
    SCENERY_NOUNS,
    SENSORY_VERBS,
    TIME_MARKERS,
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
_CONNECTIVE_ABUSE_RE = re.compile(
    r"^(?:"
    + "|".join(re.escape(opener) for opener in CONNECTIVE_ABUSE_OPENERS)
    + r")[，,:：]?"
)
_COLON_ENUM_RE = re.compile(
    r"一是[^，。；\n]{1,15}[，,；;]?二是[^，。；\n]{1,15}[，,；;]?三是"
)
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


def detect_connective_abuse(text: str) -> int:
    """句首固定连接词计数（此外/同时/然而/综上所述等）.

    只锚定句子开头（'此外' 等出现在句中不算滥用），避免中置误报。
    """
    return sum(1 for s in _split_sentences(text) if _CONNECTIVE_ABUSE_RE.match(s))


def detect_colon_enumeration(text: str) -> int:
    """'一是…二是…三是…' 整齐枚举计数.

    关闭 ai_dash_colon_density 指令里"冒号+分号不要过于整齐的'一是…二是…三是'
    结构"（style_knowledge.py）此前无 detector 覆盖的缺口。
    """
    return len(_COLON_ENUM_RE.findall(text))


def _per_1000(count: float, text_len: int) -> float:
    """计数转每千字密度."""
    return count / text_len * 1000 if text_len else 0.0


def _word_count_map(text: str, words: frozenset[str]) -> dict[str, int]:
    """统计词表每个词的出现次数（子串匹配）."""
    counts: dict[str, int] = {}
    for word in words:
        count = text.count(word)
        if count:
            counts[word] = count
    return counts


def detect_scenery_metrics(text: str) -> dict[str, float]:
    """环境/景物描写指标：景物名词与感官动词的密度 + 句子占比."""
    sentences = _split_sentences(text)
    text_len = len(text)
    sentence_count = len(sentences) or 1
    scenery_hits = _word_count_map(text, SCENERY_NOUNS)
    sensory_hits = _word_count_map(text, SENSORY_VERBS)
    scenery_total = sum(scenery_hits.values())
    sensory_total = sum(sensory_hits.values())
    scenery_sentences = sum(
        1 for s in sentences if any(word in s for word in SCENERY_NOUNS)
    )
    sensory_sentences = sum(
        1 for s in sentences if any(word in s for word in SENSORY_VERBS)
    )
    return {
        "scenery_density_per_1000": round(_per_1000(scenery_total, text_len), 2),
        "sensory_density_per_1000": round(_per_1000(sensory_total, text_len), 2),
        "scenery_sentence_ratio": round(scenery_sentences / sentence_count, 4),
        "sensory_sentence_ratio": round(sensory_sentences / sentence_count, 4),
    }


def detect_transition_metrics(text: str) -> dict[str, float]:
    """场景转换指标：显式转场计数 + 段落首时间标记计数（对齐句首锚定先例）.

    scene_transition_count = 显式转场词计数 + 段落首时间标记计数。
    段落按换行切，时间标记只锚定段落开头，避免中置误报。
    """
    explicit_total = sum(_word_count_map(text, EXPLICIT_TRANSITION_MARKERS).values())
    paragraph_openers = sum(
        1
        for para in text.split("\n")
        if para.strip() and any(para.lstrip().startswith(word) for word in TIME_MARKERS)
    )
    time_total = sum(_word_count_map(text, TIME_MARKERS).values())
    return {
        "scene_transition_count": explicit_total + paragraph_openers,
        "time_marker_density_per_1000": round(_per_1000(time_total, len(text)), 2),
    }


def detect_psych_metrics(text: str) -> dict[str, float]:
    """心理与内视角指标：心理动词密度 + 心理句子占比 + 内独白句子占比."""
    sentences = _split_sentences(text)
    sentence_count = len(sentences) or 1
    psych_total = sum(_word_count_map(text, PSYCH_VERBS).values())
    psych_sentences = sum(
        1 for s in sentences if any(word in s for word in PSYCH_VERBS)
    )
    mono_sentences = sum(
        1 for s in sentences if any(word in s for word in INNER_MONOLOGUE_PHRASES)
    )
    return {
        "psych_verb_density_per_1000": round(_per_1000(psych_total, len(text)), 2),
        "psych_sentence_ratio": round(psych_sentences / sentence_count, 4),
        "inner_monologue_sentence_ratio": round(mono_sentences / sentence_count, 4),
    }


def detect_action_metrics(text: str) -> dict[str, float]:
    """叙事节奏的动作维度：动作动词密度 + 动作句子占比."""
    sentences = _split_sentences(text)
    sentence_count = len(sentences) or 1
    action_total = sum(_word_count_map(text, ACTION_VERBS).values())
    action_sentences = sum(
        1 for s in sentences if any(word in s for word in ACTION_VERBS)
    )
    return {
        "action_verb_density_per_1000": round(_per_1000(action_total, len(text)), 2),
        "action_sentence_ratio": round(action_sentences / sentence_count, 4),
    }


def detect_narrative_ratio(sentences: list[str]) -> float:
    """叙述句子占比 = 无引号 ∧ 无动作词 ∧ 无景物词 ∧ 无心理词的句子占比.

    与 dialogue_ratio / action_sentence_ratio / scenery_sentence_ratio /
    psych_sentence_ratio 一起构成章内配比指纹。注意四正项可重叠，
    narration 为余集，四正项 + narration 之和不等于 1。
    """
    if not sentences:
        return 0.0
    narration = sum(
        1
        for s in sentences
        if not _QUOTE_RE.search(s)
        and not any(word in s for word in ACTION_VERBS)
        and not any(word in s for word in SCENERY_NOUNS)
        and not any(word in s for word in PSYCH_VERBS)
    )
    return round(narration / len(sentences), 4)


# --- v3: 写作手法世界观量化（代理指标） ---
# 诚实边界：每条是"文笔手法的可量化侧面"，只捕捉显式信号；
# 隐式手法（不点破的衬托/留白/决策依据）由 LLM 质性字段判断。


def detect_modifier_load(text: str) -> float:
    """修饰词负载（每千字）—— 白描负代理.

    白描以动词+名词打天下、删除不承载信息的修饰语，故高修饰负载 = 非白描倾向。
    """
    total = sum(_word_count_map(text, MODIFIER_ADVERBS).values())
    return round(_per_1000(total, len(text)), 2)


def detect_bystander_reaction(text: str) -> tuple[float, float]:
    """旁观者反应密度（每千字）+ 旁观/侧面句占比.

    衬托（烘云托月）与侧面描写的代理：以他人之眼、之言、之反应呈现主体。
    """
    sentences = _split_sentences(text)
    total = sum(_word_count_map(text, BYSTANDER_REACTION_PHRASES).values())
    ratio = 0.0
    if sentences:
        ratio = sum(
            1
            for s in sentences
            if any(word in s for word in BYSTANDER_REACTION_PHRASES)
        ) / len(sentences)
    return round(_per_1000(total, len(text)), 2), round(ratio, 4)


def detect_omission_markers(text: str) -> int:
    """显式省略标记计数（省略号）—— 留白代理.

    诚实标注：只捕捉显式留白（省略号），隐式留白（不写、点到即止）不可量化。
    """
    return len(re.findall(r"…+", text)) + text.count("...")


def detect_decision_grounding_markers(text: str) -> float:
    """显式决策依据信号密度（每千字）.

    身份/信念/权衡的显式标记（不得不/基于/出于/作为…）。
    诚实标注：只捕捉显式信号；大量决策经叙述自然呈现、无法用关键词捕捉。
    """
    total = sum(_word_count_map(text, DECISION_GROUNDING_MARKERS).values())
    return round(_per_1000(total, len(text)), 2)


def detect_key_segment_len_ratio(text: str) -> float:
    """密疏详略代理：关键段（最长 20% 段落）与过渡段（最短 40% 段落）字数比.

    详略经济学：关键动作写细、过渡一笔带过（疏可走马密不透风）→ 比值高。
    <3 段时样本不足返回 0.0。
    """
    lengths = sorted(
        (len(paragraph.strip()) for paragraph in text.split("\n") if paragraph.strip()),
        reverse=True,
    )
    if len(lengths) < 3:
        return 0.0
    top_count = max(1, int(len(lengths) * 0.2))
    bottom_count = max(1, int(len(lengths) * 0.4))
    top_avg = sum(lengths[:top_count]) / top_count
    bottom_avg = sum(lengths[-bottom_count:]) / bottom_count
    if bottom_avg <= 0:
        return 0.0
    return round(top_avg / bottom_avg, 2)


def analyze_style_metrics(text: str) -> StyleQuantitativeStats:
    """对全文做纯代码量化分析."""
    sentences = _split_sentences(text)
    distribution = sentence_length_distribution(sentences)
    weak_density, weak_counts = detect_weak_adverbs(text)
    scenery = detect_scenery_metrics(text)
    transition = detect_transition_metrics(text)
    psych = detect_psych_metrics(text)
    action = detect_action_metrics(text)
    bystander_density, foil_ratio = detect_bystander_reaction(text)

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
        connective_abuse_count=detect_connective_abuse(text),
        colon_enumeration_count=detect_colon_enumeration(text),
        scenery_density_per_1000=scenery["scenery_density_per_1000"],
        sensory_density_per_1000=scenery["sensory_density_per_1000"],
        scenery_sentence_ratio=scenery["scenery_sentence_ratio"],
        scene_transition_count=transition["scene_transition_count"],
        time_marker_density_per_1000=transition["time_marker_density_per_1000"],
        psych_verb_density_per_1000=psych["psych_verb_density_per_1000"],
        psych_sentence_ratio=psych["psych_sentence_ratio"],
        inner_monologue_sentence_ratio=psych["inner_monologue_sentence_ratio"],
        action_verb_density_per_1000=action["action_verb_density_per_1000"],
        action_sentence_ratio=action["action_sentence_ratio"],
        narration_sentence_ratio=detect_narrative_ratio(sentences),
        # v3: 写作手法世界观代理指标（全零默认；诚实标注为代理信号）
        modifier_load_density=detect_modifier_load(text),
        bystander_reaction_density=bystander_density,
        foil_sentence_ratio=foil_ratio,
        omission_marker_count=detect_omission_markers(text),
        decision_grounding_marker_density=detect_decision_grounding_markers(text),
        key_segment_len_ratio=detect_key_segment_len_ratio(text),
    )
