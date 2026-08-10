"""审查信号检测器 — 对象层弱信号检测（ReviewUnit 的领域规则拆分）.

对齐 info_warrant_rules.py 的模式：纯函数检测器，从 review_signal_knowledge.py
读触发词表，对 objects 返回 ReviewIssue 列表。

重构解耦说明：本模块承接原 src/workflow_action/review.py `_domain_rules`
的全部弱信号检测逻辑（B 档 8 失败类型 + 信息凭证 + 决策依据 + 描写分层 +
平台/钩子/情绪）。迁移时逐字保留每个检测器的触发条件、issue_id、severity、
violated_rule、description 文案——保证与解耦前输出完全一致（零回归契约）。

ReviewUnit 只做编排：逐类调用 detect_* 汇总 issue。硬规则（_hard_rules）
校验对象层契约（state_ref 存在性/角色 ID 一致性/事实时间冲突），属审查
编排职责，留在 review.py 不与弱信号混合（方向文档第八节模块边界）。
"""

import re

from src.domain_layer.info_warrant_knowledge import (
    FIRSTHAND_DETAIL_MARKERS,
    RELAY_MARKERS,
    UNKNOWN_NEGATION_MARKERS,
)
from src.domain_layer.review_signal_knowledge import (
    AGENCY_TRIGGERS,
    COST_MARKERS,
    FIRSTHAND_WITNESS_MARKERS,
    FORESHADOW_STOPWORDS,
    GENERATIVE_MARKERS,
    HIGH_RISK_MARKERS,
    MOTIVATION_JUMP_MARKERS,
    PAYOFF_MARKERS,
    RELATIONSHIP_JUMP_MARKERS,
)
from src.domain_layer.rules import (
    get_hook_effectiveness,
    get_hook_type_effectiveness,
    get_hook_types_for_level,
    get_platform_constraints,
    get_recommended_emotions,
    is_critical_hook_node,
    validate_node_emotion,
    validate_plotunit_hook,
    validate_plotunit_hook_type,
)
from src.domain_layer.style_knowledge import (
    EMOTION_ANNOUNCEMENT_PHRASES,
    EXPLANATORY_PHRASES,
)
from src.domain_layer.style_lexicon import DECISION_GROUNDING_MARKERS
from src.object_state import (
    CharacterModel,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    WorkSpec,
    WorldModel,
)


# --- 辅助函数（从 review.py 迁移，逐字保留） ---


def bigram_jaccard(a: str, b: str) -> float:
    """字符 2-gram Jaccard 相似度（中文字符 2-gram 交集 / 并集）。"""
    if not a or not b:
        return 0.0
    ga = set(zip(a, a[1:]))
    gb = set(zip(b, b[1:]))
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def text_related(text: str, content: str, min_bigrams: int = 2) -> bool:
    """弱相关判定：两段文本共享 ≥ min_bigrams 个字符 2-gram 即视为相关.

    用于 abrupt_payoff 判定"释放信息是否与活跃伏笔有铺垫交集"。
    要求 ≥2 个共享 bigram 是为了过滤'的/是/一'等高频虚字造成的过敏。
    """
    if not text or not content:
        return False
    gt = set(zip(text, text[1:]))
    gc = set(zip(content, content[1:]))
    return len(gt & gc) >= min_bigrams


def pu_info_text(pu: PlotUnit) -> str:
    """拼接 PlotUnit 的信息承载字段，供 iss_info_* 弱信号检测."""
    return " ".join(
        filter(
            None,
            [pu.goal, pu.conflict]
            + list(pu.released_information)
            + [pu.hook or "", pu.emotional_shift or ""]
            + list(pu.consequences),
        )
    )


def foreshadow_keywords(content: str, max_keywords: int = 4) -> list[str]:
    """从伏笔内容提取核心关键词（2-6 字中文片段，排除停用词），供内容级引用匹配."""
    segments = re.findall(r"[一-鿿]{2,}", content or "")
    keywords: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        for length in range(6, 1, -1):
            for i in range(len(seg) - length + 1):
                word = seg[i : i + length]
                if word in seen:
                    continue
                if any(stop in word for stop in FORESHADOW_STOPWORDS):
                    continue
                seen.add(word)
                keywords.append(word)
    return keywords[:max_keywords]


def foreshadow_referenced(
    entry,
    plotunit_ids: set[str],
    pu_texts: list[str],
) -> bool:
    """判断 active 伏笔是否被任一 PlotUnit 引用.

    优先看显式 linked_plotunits；否则做内容级匹配——任一 PlotUnit 的信息文本
    包含伏笔内容的核心关键词即视为被引用（避免只看 id 链接导致漏判）。
    """
    linked = set(entry.linked_plotunits or [])
    if linked.intersection(plotunit_ids):
        return True
    keywords = foreshadow_keywords(entry.content)
    if not keywords:
        return False
    return any(any(kw in text for kw in keywords) for text in pu_texts)


# --- 检测器：每类一个 detect_* 函数，返回 list[ReviewIssue] ---

# 与 review.py `_domain_rules` 的调用顺序保持一致，保证 issue 列表顺序逐条一致。


def detect_hook_validation(objects: list) -> list[ReviewIssue]:
    """iss_hook：PlotUnit hook 合法性（validate_plotunit_hook）. 需 workspec/无.

    W5 双路径：已填 hook_type（显式枚举）→ 严格层级校验（validate_plotunit_hook_type，
    非法即 blocking）；hook_type 未填 → 维持自由文本轻量检查（validate_plotunit_hook，
    不回归）。
    """
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        if pu.hook_type and pu.hook_type.strip():
            if not validate_plotunit_hook_type(pu.hook_type, pu.level):
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hook_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="钩子层级合法性",
                        violated_rule="hook_type 必须属于当前层级的显式枚举",
                        description=(
                            f"hook_type '{pu.hook_type}' 对层级 '{pu.level}' 不合法；"
                            f"该层级合法枚举为 "
                            f"{sorted(get_hook_types_for_level(pu.level)) or '无'}"
                        ),
                    )
                )
            continue
        if not validate_plotunit_hook(pu.hook, pu.level):
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_hook_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="当前推进单元",
                    violated_rule="hook 合法性",
                    description=f"hook '{pu.hook}' 对层级 '{pu.level}' 不合法",
                )
            )
    return issues


def detect_emotional_shift_presence(objects: list) -> list[ReviewIssue]:
    """iss_emotion：emotional_shift 非空（当 structure_template 存在时）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    workspecs = [o for o in objects if hasattr(o, "structure_template")]
    template_name = workspecs[0].structure_template if workspecs else None
    if template_name:
        for pu in plotunits:
            if not pu.emotional_shift:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_emotion_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="warning",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="情绪弧完整性",
                        violated_rule="emotional_shift 非空",
                        description=f"PlotUnit {pu.unit_id} 缺少 emotional_shift",
                    )
                )
    return issues


def detect_platform_constraints(objects: list) -> list[ReviewIssue]:
    """iss_platform_hook / iss_platform_patience：平台约束（钩子压力/读者耐心）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    workspecs = [o for o in objects if isinstance(o, WorkSpec)]
    platform_id = workspecs[0].platform if workspecs else None
    platform_constraints = get_platform_constraints(platform_id) if platform_id else {}
    hook_pressure = platform_constraints.get("hook_pressure", "")
    reader_patience = platform_constraints.get("reader_patience", "")
    if platform_constraints:
        for pu in plotunits:
            if "mandatory" in hook_pressure and not pu.hook:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_platform_hook_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="warning",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="平台约束满足度",
                        violated_rule=f"平台 {platform_id} 要求 {hook_pressure}",
                        description=(
                            f"PlotUnit {pu.unit_id} 缺少 hook，"
                            f"但平台 '{platform_id}' 要求 {hook_pressure}"
                        ),
                    )
                )
            if reader_patience == "very low" and not pu.emotional_shift:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_platform_patience_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="warning",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="平台约束满足度",
                        violated_rule=f"平台 {platform_id} 读者耐心极低，需要频繁推进",
                        description=(
                            f"PlotUnit {pu.unit_id} 缺少 emotional_shift，"
                            f"不符合 '{platform_id}' 的低耐心读者预期"
                        ),
                    )
                )
    return issues


def detect_hook_effectiveness(objects: list) -> list[ReviewIssue]:
    """iss_hook_eff：关键节点应使用 high-effectiveness hook.

    W5：已填 hook_type 时按其显式类型查 effectiveness（get_hook_type_effectiveness，
    映射 level→taxonomy 键）；未填时沿用自由文本 hook 的旧路径（不回归）。
    """
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        if not (pu.formula_node and is_critical_hook_node(pu.formula_node)):
            continue
        if pu.hook_type and pu.hook_type.strip():
            effectiveness = get_hook_type_effectiveness(pu.hook_type, pu.level)
            hook_label = pu.hook_type
        else:
            if not pu.hook:
                continue
            effectiveness = get_hook_effectiveness(pu.hook, pu.level)
            hook_label = pu.hook
        if effectiveness and effectiveness != "high":
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_hook_eff_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="钩子质量",
                    violated_rule="关键节点应使用 high-effectiveness hook",
                    description=(
                        f"PlotUnit {pu.unit_id} 处于关键节点 '{pu.formula_node}'，"
                        f"但 hook '{hook_label}' 的 effectiveness 为 '{effectiveness}'，"
                        f"建议使用 high-effectiveness 钩子。"
                    ),
                )
            )
    return issues


def detect_emotion_node_match(objects: list) -> list[ReviewIssue]:
    """iss_emotion_match：emotional_shift 应匹配当前结构节点的推荐情绪."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        if pu.formula_node and pu.emotional_shift:
            if not validate_node_emotion(pu.emotional_shift, pu.formula_node):
                recommended = get_recommended_emotions(pu.formula_node)
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_emotion_match_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="warning",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="情绪弧与结构节点对齐",
                        violated_rule="emotional_shift 应匹配当前结构节点的推荐情绪",
                        description=(
                            f"PlotUnit {pu.unit_id} 处于结构节点 '{pu.formula_node}'，"
                            f"emotional_shift 为 '{pu.emotional_shift}'，"
                            f"但推荐情绪为 {recommended}，未检测到匹配。"
                        ),
                    )
                )
    return issues


def detect_generative_indicia(objects: list) -> list[ReviewIssue]:
    """iss_genind / iss_genind2 / iss_genind3：生成痕迹启发式检测."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]

    for pu in plotunits:
        text_to_check = " ".join(
            filter(None, [pu.goal, pu.conflict, pu.emotional_shift or ""])
        )
        found_modifiers = [
            marker
            for marker in GENERATIVE_MARKERS["over_modifiers"]
            if marker in text_to_check
        ]
        if len(found_modifiers) >= 2:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_genind_{pu.unit_id}",
                    issue_type="generative_indicia",
                    severity="low",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="表达层",
                    violated_rule="过度修饰",
                    description=f"检测到生成痕迹词: {', '.join(found_modifiers)}",
                )
            )

        if pu.released_information:
            emotional_count = sum(
                1
                for word in GENERATIVE_MARKERS["emotional_stacking"]
                for info in pu.released_information
                if word in info
            )
            if emotional_count >= 3:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_genind2_{pu.unit_id}",
                        issue_type="generative_indicia",
                        severity="low",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="表达层",
                        violated_rule="情绪标签堆砌",
                        description=f"单单元内情绪标记密度过高 ({emotional_count})",
                    )
                )

    if len(plotunits) >= 2:
        for i in range(len(plotunits) - 1):
            pu_a, pu_b = plotunits[i], plotunits[i + 1]
            if pu_a.goal == pu_b.goal:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_genind3_{pu_b.unit_id}",
                        issue_type="generative_indicia",
                        severity="low",
                        location=f"PlotUnit {pu_b.unit_id}",
                        scope_of_impact="表达层",
                        violated_rule="句式模板重复",
                        description=f"goal 与 PlotUnit {pu_a.unit_id} 完全重复",
                    )
                )

    return issues


def detect_agency_grounding(objects: list) -> list[ReviewIssue]:
    """iss_agency：关键选择应可回溯到身份/信念/恐惧（决策依据弱信号）."""
    issues: list[ReviewIssue] = []
    if not any(isinstance(o, CharacterModel) for o in objects):
        return issues
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        decision_text = " ".join(filter(None, [pu.goal, pu.conflict]))
        if not decision_text:
            continue
        if not any(marker in decision_text for marker in AGENCY_TRIGGERS):
            continue
        if any(marker in decision_text for marker in DECISION_GROUNDING_MARKERS):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_agency_{pu.unit_id}",
                issue_type="weak_progression",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="角色动机一致性",
                violated_rule="关键选择应可回溯到身份/信念/恐惧",
                description=(
                    f"PlotUnit {pu.unit_id} 的选择 '{decision_text[:40]}…' "
                    f"含决策动作但无显式依据标记（不得不/基于/出于/作为…）。"
                    f"请复核该选择是否有身份/信念依据，区分'有意的戏剧性反转'"
                    f"与'无依据的剧情需要（工具人风险）'。"
                ),
            )
        )
    return issues


def detect_layering(objects: list) -> list[ReviewIssue]:
    """iss_layering：直给型陈述应改用动作/衬托呈现（描写分层弱信号）."""
    issues: list[ReviewIssue] = []
    layering_markers = set(EXPLANATORY_PHRASES) | set(EMOTION_ANNOUNCEMENT_PHRASES)
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        text_to_check = " ".join(
            filter(None, [pu.goal, pu.conflict, pu.emotional_shift or ""])
        )
        hits = [marker for marker in layering_markers if marker in text_to_check]
        if hits:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_layering_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="low",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="表达层",
                    violated_rule="直给型陈述应改用动作/衬托呈现",
                    description=(
                        f"PlotUnit {pu.unit_id} 字段含直给型标记 {hits}。"
                        f"提示该处可能'直给'了（他感到/涌起一股）。"
                        f"散文型气质应改白描/衬托：以动作、身体反应、他人反应呈现。"
                    ),
                )
            )
    return issues


def detect_info_channel(objects: list) -> list[ReviewIssue]:
    """iss_info_channel：亲历细节须有亲历感知通道供给（P1 弱信号）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        info_text = pu_info_text(pu)
        if not info_text:
            continue
        firsthand_hits = [m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text]
        unknown_hits = [m for m in UNKNOWN_NEGATION_MARKERS if m in info_text]
        if firsthand_hits and unknown_hits:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_info_channel_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="信息凭证一致性",
                    violated_rule="亲历型细节须有亲历感知通道供给（P1）",
                    description=(
                        f"PlotUnit {pu.unit_id} 信息字段含亲历细节标记 {firsthand_hits}"
                        f"与未知/未接触标记 {unknown_hits} 共现。"
                        f"提示该处可能'亲历细节越过信息通道'"
                        f"（例：未摸实位置却知道人瘦了）。"
                        f"请确认是否存在亲历前提——补观察者 / 降细节级 / 删细节。"
                    ),
                )
            )
    return issues


def detect_info_relay(objects: list) -> list[ReviewIssue]:
    """iss_info_relay：转述通道产出亲历细节（P3/P2 弱信号）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        info_text = pu_info_text(pu)
        if not info_text:
            continue
        if any(m in info_text for m in FIRSTHAND_WITNESS_MARKERS):
            continue  # 已补亲历前提（如"远远看过"），不算断裂
        relay_hits = [m for m in RELAY_MARKERS if m in info_text]
        firsthand_hits = [m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text]
        if relay_hits and firsthand_hits:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_info_relay_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="信息凭证一致性",
                    violated_rule="转述通道不可产出转述者未亲历的细节（P3/P2）",
                    description=(
                        f"PlotUnit {pu.unit_id} 信息经转述通道（{relay_hits}）流入，"
                        f"却产出亲历型细节（{firsthand_hits}）且无亲历前提标记。"
                        f"提示转述可能越出信息通道，或旧消息被当当下状态。"
                        f"请确认转述者（或其代理）是否亲历过该细节。"
                    ),
                )
            )
    return issues


def detect_info_scope(objects: list) -> list[ReviewIssue]:
    """iss_info_scope：角色知识域与其身份匹配、知情状态不得翻转（P4 弱信号）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for cm in (o for o in objects if isinstance(o, CharacterModel)):
        neg_claims = [
            k
            for k in cm.knowledge_state
            if any(m in k for m in UNKNOWN_NEGATION_MARKERS)
        ]
        if not neg_claims:
            continue
        for pu in plotunits:
            if cm.character_id not in pu.participants:
                continue
            info_text = pu_info_text(pu)
            if not info_text:
                continue
            firsthand_hits = [m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text]
            if not firsthand_hits:
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_info_scope_{cm.character_id}_{pu.unit_id}",
                    issue_type="weak_progression",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="信息凭证一致性",
                    violated_rule="角色知识域与其身份匹配，知情状态不得翻转（P4）",
                    description=(
                        f"角色 '{cm.character_id}' 的知识域断言未知"
                        f"（{neg_claims[:2]}），却参与产出亲历细节的单元"
                        f"（{firsthand_hits}）。提示知识域可能翻转——"
                        f"前文'不知道'，此处却依赖细节。请确认是否引入了新信息通道。"
                    ),
                )
            )
    return issues


def detect_information_leak(objects: list) -> list[ReviewIssue]:
    """iss_leak：信息分配矛盾（public∩hidden 硬信号）+ 断言未知被当已知释放（弱信号）."""
    issues: list[ReviewIssue] = []
    states = {ns.state_id: ns for ns in objects if isinstance(ns, NarrativeState)}
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]

    # 硬信号：同一信息同时出现在 public_information 与 hidden_information。
    for ns in states.values():
        overlap = sorted(set(ns.public_information) & set(ns.hidden_information))
        if not overlap:
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_leak_{ns.state_id}",
                issue_type="information_leak",
                severity="warning",
                location=f"NarrativeState {ns.state_id}",
                scope_of_impact="信息分配一致性",
                violated_rule="同一信息不应既公开又隐藏（信息分配自洽）",
                description=(
                    f"NarrativeState {ns.state_id} 中 {overlap} 同时出现在"
                    f" public_information 与 hidden_information。提示信息分配层矛盾——"
                    f"请确认该信息对读者/角色到底是否已知。"
                ),
            )
        )

    # 弱信号：角色知识域断言"不知X"，但 X 出现在其参与的 PlotUnit 释放信息。
    for cm in (o for o in objects if isinstance(o, CharacterModel)):
        neg_claims = [
            k
            for k in cm.knowledge_state
            if any(m in k for m in UNKNOWN_NEGATION_MARKERS)
        ]
        if not neg_claims:
            continue
        for pu in plotunits:
            if cm.character_id not in pu.participants:
                continue
            info_text = pu_info_text(pu)
            leaked = []
            for claim in neg_claims:
                for neg in UNKNOWN_NEGATION_MARKERS:
                    if neg not in claim:
                        continue
                    subject = claim.replace(neg, "").strip("，,。 ")
                    if subject and any(
                        info_text.find(subject[i:i + 2]) >= 0
                        for i in range(len(subject) - 1)
                    ):
                        leaked.append(subject)
                        break
            if not leaked:
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_leak_{cm.character_id}_{pu.unit_id}",
                    issue_type="information_leak",
                    severity="warning",
                    location=f"PlotUnit {pu.unit_id}",
                    scope_of_impact="信息凭证一致性",
                    violated_rule="断言未知的信息不得作为已知释放（信息泄露）",
                    description=(
                        f"角色 '{cm.character_id}' 知识域断言未知"
                        f"（{neg_claims[:2]}），但本单元释放信息涉及 {leaked}。"
                        f"提示该信息可能被当作已知泄露给了不该知情的对象——"
                        f"请确认知情分布是否违反信息凭证。"
                    ),
                )
            )

    return issues


def detect_motivation_gap(objects: list) -> list[ReviewIssue]:
    """iss_motivation：态度/立场转向须有决策依据或桥接（动机自洽）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        text = pu_info_text(pu)
        if not any(m in text for m in MOTIVATION_JUMP_MARKERS):
            continue
        if any(m in text for m in DECISION_GROUNDING_MARKERS):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_motivation_{pu.unit_id}",
                issue_type="motivation_gap",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="角色决策连贯性",
                violated_rule="态度/立场转向须有决策依据或桥接（动机自洽）",
                description=(
                    f"PlotUnit {pu.unit_id} 出现态度跃迁词"
                    f"（{[m for m in MOTIVATION_JUMP_MARKERS if m in text]}）"
                    f"但无决策依据词。提示转向可理解但缺桥——"
                    f"请确认该角色为何在此刻改变立场。"
                ),
            )
        )
    return issues


def detect_missing_cost(objects: list) -> list[ReviewIssue]:
    """iss_cost：高风险/越界行为须付出可见代价（世界代价机制）."""
    issues: list[ReviewIssue] = []
    worlds = [o for o in objects if isinstance(o, WorldModel)]
    if not any(w.prohibitions or w.consequence_logic for w in worlds):
        return issues
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        text = pu_info_text(pu)
        if not any(m in text for m in HIGH_RISK_MARKERS):
            continue
        if any(m in text for m in COST_MARKERS):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_cost_{pu.unit_id}",
                issue_type="missing_cost",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="世界规则可信度",
                violated_rule="高风险/越界行为须付出可见代价（世界代价机制）",
                description=(
                    f"PlotUnit {pu.unit_id} 含高风险行为词"
                    f"（{[m for m in HIGH_RISK_MARKERS if m in text]}），"
                    f"但后果清单无代价词。提示高风险行为缺代价——"
                    f"请确认该行为是否真的免费，还是代价未显式化。"
                ),
            )
        )
    return issues


def detect_missing_consequence(objects: list) -> list[ReviewIssue]:
    """iss_consequence：释放新信息后局势应发生可感知变化（推进自洽）."""
    issues: list[ReviewIssue] = []
    states = {ns.state_id: ns for ns in objects if isinstance(ns, NarrativeState)}
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        if not pu.released_information:
            continue
        in_state = states.get(pu.input_state_ref)
        out_state = states.get(pu.output_state_ref)
        if in_state is None or out_state is None:
            continue
        if in_state.current_situation != out_state.current_situation:
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_consequence_{pu.unit_id}",
                issue_type="missing_consequence",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="推进有效性",
                violated_rule="释放新信息后局势应发生可感知变化（推进自洽）",
                description=(
                    f"PlotUnit {pu.unit_id} 释放了 {len(pu.released_information)} 条新信息"
                    f"但输入/输出 NarrativeState 的 current_situation 完全未变。"
                    f"提示揭露无后果——请确认该信息是否真的改变了局势。"
                ),
            )
        )
    return issues


def detect_relationship_jump(objects: list) -> list[ReviewIssue]:
    """iss_reljump：关系性质跃迁须有桥接或代价（关系自洽）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for pu in plotunits:
        text = pu_info_text(pu)
        if not any(m in text for m in RELATIONSHIP_JUMP_MARKERS):
            continue
        if any(m in text for m in DECISION_GROUNDING_MARKERS):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_reljump_{pu.unit_id}",
                issue_type="relationship_jump",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="关系连续性",
                violated_rule="关系性质跃迁须有桥接或代价（关系自洽）",
                description=(
                    f"PlotUnit {pu.unit_id} 出现关系跃迁词"
                    f"（{[m for m in RELATIONSHIP_JUMP_MARKERS if m in text]}）"
                    f"但无决策依据。提示关系移动缺桥——"
                    f"请确认这次关系变化是否凭空发生。"
                ),
            )
        )
    return issues


def detect_redundancy(objects: list) -> list[ReviewIssue]:
    """iss_redundancy：相邻推进单元不应重复同一切口（冗余）."""
    issues: list[ReviewIssue] = []
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    for i in range(len(plotunits) - 1):
        pu_a, pu_b = plotunits[i], plotunits[i + 1]
        repeated = []
        if pu_a.conflict == pu_b.conflict:
            repeated.append("conflict")
        if pu_a.hook and pu_a.hook == pu_b.hook:
            repeated.append("hook")
        if not repeated:
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_redundancy_{pu_b.unit_id}",
                issue_type="redundancy",
                severity="low",
                location=f"PlotUnit {pu_b.unit_id}",
                scope_of_impact="结构效率",
                violated_rule="相邻推进单元不应重复同一切口（冗余）",
                description=(
                    f"PlotUnit {pu_b.unit_id} 与 {pu_a.unit_id} 的"
                    f" {'/'.join(repeated)} 完全重复。提示两步推进可能是同一动作的重复——"
                    f"请确认该单元是否可合并或删除而无损。"
                ),
            )
        )
    return issues


def detect_abrupt_payoff(objects: list) -> list[ReviewIssue]:
    """iss_abrupt：揭晓/反转应挂在前置伏笔之上（承诺连贯）."""
    issues: list[ReviewIssue] = []
    foreshadows = [o for o in objects if isinstance(o, ForeshadowGraph)]
    plotunits = [o for o in objects if isinstance(o, PlotUnit)]
    active_threads = [
        e for fg in foreshadows for e in fg.entries
        if e.current_status == "active"
    ]
    for pu in plotunits:
        rel_text = " ".join(pu.released_information)
        if not rel_text:
            continue
        if not any(m in rel_text for m in PAYOFF_MARKERS):
            continue
        if any(text_related(rel_text, e.content) for e in active_threads):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_abrupt_{pu.unit_id}",
                issue_type="abrupt_payoff",
                severity="warning",
                location=f"PlotUnit {pu.unit_id}",
                scope_of_impact="承诺兑现",
                violated_rule="揭晓/反转应挂在前置伏笔之上（承诺连贯）",
                description=(
                    f"PlotUnit {pu.unit_id} 释放信息含揭晓词"
                    f"（{[m for m in PAYOFF_MARKERS if m in rel_text]}）"
                    f"但没有活跃伏笔与其有明显铺垫交集。提示揭晓可能突兀——"
                    f"请确认该真相是否早已埋设。"
                ),
            )
        )
    return issues


def detect_duplication_of_threads(objects: list) -> list[ReviewIssue]:
    """iss_dupthread：活跃承诺线程不应高度重复（线索去重）."""
    issues: list[ReviewIssue] = []
    foreshadows = [o for o in objects if isinstance(o, ForeshadowGraph)]
    active_threads = [
        e for fg in foreshadows for e in fg.entries
        if e.current_status == "active"
    ]
    if len(active_threads) >= 2:
        for i in range(len(active_threads)):
            for j in range(i + 1, len(active_threads)):
                a, b = active_threads[i], active_threads[j]
                sim = bigram_jaccard(a.content, b.content)
                if sim < 0.5:
                    continue
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_dupthread_{a.thread_id}_{b.thread_id}",
                        issue_type="duplication_of_threads",
                        severity="warning",
                        location=f"ForeshadowGraph {a.thread_id} / {b.thread_id}",
                        scope_of_impact="承诺清晰度",
                        violated_rule="活跃承诺线程不应高度重复（线索去重）",
                        description=(
                            f"活跃伏笔 '{a.thread_id}' 与 '{b.thread_id}' 内容"
                            f" 2-gram 相似度 {sim:.2f} ≥ 0.5。提示两条线程可能是"
                            f"同一承诺的分裂——请确认是否应合并或明确区分。"
                        ),
                    )
                )
                break
    return issues


# 检测器注册表：ReviewUnit._domain_rules 按此顺序汇总（与原 _domain_rules 调用顺序一致）。
SIGNAL_DETECTORS: tuple[callable, ...] = (
    detect_hook_validation,
    detect_emotional_shift_presence,
    detect_platform_constraints,
    detect_hook_effectiveness,
    detect_emotion_node_match,
    detect_generative_indicia,
    detect_agency_grounding,
    detect_layering,
    detect_info_channel,
    detect_info_relay,
    detect_info_scope,
    detect_information_leak,
    detect_motivation_gap,
    detect_missing_cost,
    detect_missing_consequence,
    detect_relationship_jump,
    detect_redundancy,
    detect_abrupt_payoff,
    detect_duplication_of_threads,
)


def run_all_signal_detectors(objects: list) -> list[ReviewIssue]:
    """运行全部弱信号检测器，按注册表顺序汇总 issue.

    ReviewUnit._domain_rules 调用本函数；issue 顺序与解耦前逐条一致
    （零回归契约：触发条件/issue_id/severity/文案均未改动）。
    """
    issues: list[ReviewIssue] = []
    for detector in SIGNAL_DETECTORS:
        issues.extend(detector(objects))
    return issues
