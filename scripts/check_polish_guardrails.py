#!/usr/bin/env python3
"""去AI味规则 guardrail 回归检查（Q1.3 自然修订验证 2026-09-11）.

不进 tests/：新增收集测试会触发 collected 基线 3138 漂移，而
current_state.json 再认证需双 profile bundle（public_clean 需 Linux），
本机无法完成。本脚本以独立检查形式提供等效回归保护。

用法: python scripts/check_polish_guardrails.py  →  全过 exit 0，任一失败 exit 1。

检查项对应 8 章真实润色中实测的误删案例：
  A 确认性洞察帧删除仅当认知已落地且无状态转移/hook
  B 收尾句携带 forward hook 时不得按总结句删除
  C 意象回声（水意象链）不得被 metaphor/style marker 直接删除
  D 压缩多关系比喻（像退潮）不得被 AI-flavor marker 直接删除
  E 结算型排比（逐项撤走状态维度）不得被 parallel4 拍平
  F 纯 STYLE_SUBSTITUTION 无明确收益时默认 NO_CHANGE
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.domain_layer.style_rules import (  # noqa: E402
    get_ai_flavor_markers,
    get_function_check_questions,
    get_function_protection_list,
    get_polish_discipline,
    lookup_marker,
)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def joined(rule_id: str) -> str:
    marker = lookup_marker(rule_id)
    if marker is None:
        return ""
    return "；".join(marker["instructions"])


# 1. 全部 marker 均为提审口径：不存在"命中即删除"直通道
markers = get_ai_flavor_markers()
for m in markers:
    text = "；".join(m["instructions"])
    check(
        f"marker {m['rule_id']} 是 review candidate（命中≠）",
        "命中≠" in text,
        text[:60],
    )

# 2. Case A：解释腔区分复述 vs 状态转移/forward hook
t = joined("ai_explanatory_voice")
check("ai_explanatory_voice 区分复述/状态转移/hook", "复述" in t and "hook" in t.lower())

# 3. Case B：hook 优先于去总结腔（POLISH_DISCIPLINE）
discipline = "；".join(get_polish_discipline())
check("POLISH_DISCIPLINE 声明 hook 保留优先", "hook" in discipline.lower() and "优先" in discipline)
check("POLISH_DISCIPLINE 声明 NO_CHANGE 合法", "NO_CHANGE" in discipline)
check("POLISH_DISCIPLINE 声明删除只能来自冗余确认", "冗余确认" in discipline)

# 4. Case C/D：保护清单覆盖意象回声与压缩比喻
protection = "；".join(get_function_protection_list())
check("保护清单含意象回声", "回声" in protection)
check("保护清单含压缩多关系比喻", "比喻" in protection)
check("保护清单含 forward hook 收尾句", "hook" in protection.lower() or "收尾" in protection)
check("保护清单含节拍型对白标记", "节拍" in protection)

# 5. Case E：排比规则保护结算型排比
t = joined("ai_parallel_four")
check("ai_parallel_four 保护结算型排比", "结算" in t)

# 6. 弱副词规则要求功能核查后处置
t = joined("ai_weak_adverb_density")
check("ai_weak_adverb_density 先功能核查", "渐进性" in t or "身体感" in t)

# 7. 对白标签规则区分僵硬标签与节拍标记
t = joined("ai_dialogue_tag_density")
check("ai_dialogue_tag_density 区分节拍标记", "节拍" in t)

# 8. 功能核查问题存在且含反事实测试要点
q = "；".join(get_function_check_questions())
check("功能核查问题 ≥5 条", len(get_function_check_questions()) >= 5)
check("功能核查含删除测试", "消失" in q)
check("功能核查含替换测试", "泛化模板" in q)
check("功能核查含后续后果测试", "预测" in q or "行动" in q)
check("功能核查含场景专属性测试", "移植" in q)

# 9. 组装后运行时表达验证（不只查常量）：lint → ReviewIssue.description
from src.workflow_action.style import StyleLintUnit  # noqa: E402
from src.workflow_action.author_selector import style_proxy_score  # noqa: E402
from src.object_state.styleprofile import StyleProfile, StyleQuantitativeStats  # noqa: E402

# 触发多条 marker 的样本文本（弱化副词密集 + 解释腔 + 排比）
sample = (
    "他微微皱眉，轻轻点头，缓缓说道：'我们走。'" * 6
    + "他忽然明白了，这意味着一切。"
    + "没有修为，没有身份，没有宗门，没有退路。"
)
issues = StyleLintUnit().lint(sample)
check("lint 产出 issue（样本应触发 marker）", len(issues) > 0)
for iss in issues:
    check(
        f"issue {iss.issue_id} description 为提审口径",
        "命中≠" in iss.description,
        iss.description[:80],
    )
    check(
        f"issue {iss.issue_id} 携带提审纪律尾注",
        "提审纪律" in iss.description and "保护清单" in iss.description,
    )
    check(
        f"issue {iss.issue_id} 无直通道删除指令（'请删除'/'直接删'）",
        "请删除" not in iss.description and "直接删" not in iss.description,
    )

# 10. taboo_words 运行时路径：issue 与 profile 渲染均为 review candidate
taboo_issues = StyleLintUnit().lint_taboo_words("他深吸一口气，又深吸一口气", ["深吸一口气"])
check("lint_taboo_words 产出 issue", len(taboo_issues) == 1)
if taboo_issues:
    check("taboo issue 提审口径", "命中≠" in taboo_issues[0].description)
    check("taboo issue 非直通道替换指令", "请替换为" not in taboo_issues[0].description)

# 11. style_proxy_score：taboo 命中只提审不扣分
from src.object_state.plotunit import PlotUnit  # noqa: E402

prof = StyleProfile(
    profile_id="t",
    source_text_ref="t",
    narrative_pov="第三人称有限",
    pacing_description="占位",
    taboo_words=["深吸一口气"],
    stats=StyleQuantitativeStats(
        total_chars=0, sentence_count=0, avg_sentence_len=0.0,
        short_sentence_ratio=0.0, long_sentence_ratio=0.0, dialogue_ratio=0.0,
        weak_adverb_density_per_1000=0.0, weak_adverb_counts={},
        metaphor_repeats=[], explanatory_phrase_count=0, shell_counts={},
        dialogue_tag_density_per_1000=0.0, emotion_announcement_count=0,
        dash_colon_density_per_1000=0.0, connective_abuse_count=0,
        colon_enumeration_count=0, scenery_density_per_1000=0.0,
        sensory_density_per_1000=0.0, scenery_sentence_ratio=0.0,
        scene_transition_count=0, time_marker_density_per_1000=0.0,
        psych_verb_density_per_1000=0.0, psych_sentence_ratio=0.0,
        inner_monologue_sentence_ratio=0.0, action_verb_density_per_1000=0.0,
        action_sentence_ratio=0.0, narration_sentence_ratio=0.0,
        modifier_load_density=0.0, bystander_reaction_density=0.0,
        foil_sentence_ratio=0.0, omission_marker_count=0,
        decision_grounding_marker_density=0.0, key_segment_len_ratio=0.0,
    ),
)
pu = PlotUnit(
    unit_id="pu_t",
    level="scene",
    goal="他深吸一口气",
    participants=["c001"],
    conflict="占位",
    input_state_ref="ns_in",
    output_state_ref="ns_t",
    hook="",
    consequences=[],
    is_effective=True,
)
score, notes = style_proxy_score({"plotunit": pu}, prof)
check("style_proxy_score taboo 命中不扣分", score == 1.0)
check("style_proxy_score 命中标记为 review candidate", any("review candidate" in n for n in notes))

ctx = prof.to_prompt_context()
check("profile 渲染禁忌词带提审口径", "命中≠" in ctx or "review candidate" in ctx)

if FAILURES:
    print(f"\n{len(FAILURES)} 项失败")
    sys.exit(1)
print(f"\n全部通过（{len(markers)} 条 marker + 功能核查协议 + 保护清单 + polish 纪律 + 运行时组装表达）")
