"""Style Drift 测量（measurement-only，不自动纠正）.

回答两类问题：
1. **AI 自己有没有漂**：比较 人类原文 baseline 与 AI 各章，是否出现『AI 化 drift』
   ——即越来越像模型自己的高概率习惯（句式整齐、情绪总被总结、身体反应重复、
   章末模板化、比喻模板化、每场戏完整闭环），而不是『越来越不像原作者』。
2. **Review 是不是 homogenization 来源**：对同一章比较 Draft vs Committed——
   如果 Draft 还有变化，Review 一修就越来越统一，罪魁祸首是 Review 而非 Prose。

指标分两层：
- 表层：句长 / 段长 / 对白比例 / 心理叙述比例 / 破折号+省略号密度 / 高频句式。
- AI 化：`他意识到/明白/忽然明白` 密度 / 身体反应重复 / 解释性收尾 /
  相同转折结构（不是A而是B）/ 比喻密度。

纯 stdlib 实现（无分词），中文按标点切句；全部为每千字密度，可复现。
"""

from __future__ import annotations

import re
from pathlib import Path

# ---- 表层指标 ----

_SENT_SPLIT = re.compile(r"[。！？；]+")


def _density(text: str, patterns: list[str]) -> float:
    """统计 patterns 中任一子串的出现次数，换算为每千字密度."""
    compact = "".join(text.split())
    if not compact:
        return 0.0
    count = 0
    for p in patterns:
        count += len(re.findall(re.escape(p), compact))
    return round(count * 1000 / len(compact), 4)


def _sentence_lengths(text: str) -> list[int]:
    compact = "".join(text.split())
    if not compact:
        return []
    return [len(s) for s in _SENT_SPLIT.split(compact) if s]


def measure_text(text: str) -> dict:
    """测量一段正文的表层 + AI 化指标（全部为每千字密度或均值）."""
    compact = "".join(text.split())
    total = len(compact)
    if not total:
        return {"empty": True}

    paras = [p.strip() for p in text.split("\n") if p.strip()]
    sents = _sentence_lengths(text)
    # 对白：整行以「或“开头的行数占比
    dialogue_lines = sum(1 for p in paras if p.startswith(("「", "“")))
    # 心理叙述标记（间接独白）：『他忍不住于心里』『思绪一转』『他忽然明白』
    psych_marks = _density(text, ["忍不住", "思绪", "心里", "忽然明白", "意识到", "他明白", "他懂得"])

    surface = {
        "avg_sentence_len": round(sum(sents) / len(sents), 2) if sents else 0.0,
        "sentence_count": len(sents),
        "paragraph_count": len(paras),
        "avg_paragraph_len": round(total / len(paras), 1) if paras else 0.0,
        "dialogue_ratio": round(dialogue_lines / len(paras), 3) if paras else 0.0,
        "psych_marker_per_1k": psych_marks,
        "dash_ellipsis_per_1k": _density(text, ["——", "…", "……"]),
        "weak_adv_per_1k": _density(text, ["微微", "淡淡", "缓缓", "轻轻", "隐隐", "慢慢"]),
    }

    ai = {
        "realization_per_1k": _density(
            text, ["他意识到", "他明白", "忽然明白", "此刻他知道了", "他终于明白", "他终于意识到"]
        ),
        "not_a_but_b_per_1k": _density(text, ["不是", "而是", "不是A"]),  # 近似：含『而是』即壳句式候选
        "body_reaction_per_1k": _density(
            text, ["攥", "咬牙", "冷汗", "呼吸一滞", "瞳孔", "脊背", "指尖发白", "心口"]
        ),
        "explanatory_ending_per_1k": _density(text, ["这意味着", "这似乎表明", "也就是说", "这说明"]),
        "metaphor_per_1k": _density(text, ["像", "如同", "宛如", "仿佛"]),
        "symmetric_per_1k": _density(text, ["不是", "而是"]),
    }
    return {"surface": surface, "ai": ai, "chars": total}


def drift_report(chapters: list[tuple[str, str]], baseline: str) -> dict:
    """比较 baseline（人类原文）与各 AI 章，报告表层 + AI 化随章变化。

    Args:
        chapters: [(label, text)]，如 [("ch1", "…"), ("ch3", "…"), …]。
        baseline: 人类原文文本。

    Returns:
        {"baseline": 指标, "chapters": [{label, metrics, delta_vs_baseline}],
         "ai_drift_signals": 逐章 AI 化指标是否单调上升的判定}
    """
    base = measure_text(baseline)
    rows = []
    for label, text in chapters:
        m = measure_text(text)
        rows.append({
            "label": label,
            "metrics": m,
            "delta": {
                "realization_per_1k": m["ai"]["realization_per_1k"] - base["ai"]["realization_per_1k"],
                "body_reaction_per_1k": m["ai"]["body_reaction_per_1k"] - base["ai"]["body_reaction_per_1k"],
                "explanatory_per_1k": m["ai"]["explanatory_ending_per_1k"] - base["ai"]["explanatory_ending_per_1k"],
                "not_a_but_b_per_1k": m["ai"]["not_a_but_b_per_1k"] - base["ai"]["not_a_but_b_per_1k"],
                "metaphor_per_1k": m["ai"]["metaphor_per_1k"] - base["ai"]["metaphor_per_1k"],
                "sentence_len": m["surface"]["avg_sentence_len"] - base["surface"]["avg_sentence_len"],
            },
        })
    return {"baseline": base, "chapters": rows}


def compare_draft_committed(draft: str, committed: str) -> dict:
    """比较同一章的 Draft vs Committed，判定 Review 是否在制造 homogenization.

    若 Draft 的『变化性/多样性』指标（句长方差、对话比例、弱副词、比喻）高于
    Committed，说明 Review 修订后文字更统一——需标记为 homogenization 风险。
    """
    d = measure_text(draft)
    c = measure_text(committed)
    return {
        "draft": d,
        "committed": c,
        "homogenization_signals": {
            "dash_ellipsis_delta": c["surface"]["dash_ellipsis_per_1k"] - d["surface"]["dash_ellipsis_per_1k"],
            "realization_delta": c["ai"]["realization_per_1k"] - d["ai"]["realization_per_1k"],
            "body_reaction_delta": c["ai"]["body_reaction_per_1k"] - d["ai"]["body_reaction_per_1k"],
            "not_a_but_b_delta": c["ai"]["not_a_but_b_per_1k"] - d["ai"]["not_a_but_b_per_1k"],
            "sentence_len_delta": c["surface"]["avg_sentence_len"] - d["surface"]["avg_sentence_len"],
        },
    }
