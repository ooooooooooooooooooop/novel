"""ReviewUnit — 审查工作流."""

import json
import re
from collections import defaultdict

from src.domain_layer.rules import (
    get_hook_effectiveness,
    get_platform_constraints,
    get_recommended_emotions,
    is_critical_hook_node,
    validate_node_emotion,
    validate_plotunit_hook,
)
from src.domain_layer.info_warrant_knowledge import (
    FIRSTHAND_DETAIL_MARKERS,
    INFO_GAP_FORMS,
    RELAY_MARKERS,
    UNKNOWN_NEGATION_MARKERS,
)
from src.domain_layer.info_warrant_rules import build_info_warrant_guidance
from src.domain_layer.style_knowledge import (
    EMOTION_ANNOUNCEMENT_PHRASES,
    EXPLANATORY_PHRASES,
)
from src.domain_layer.style_lexicon import DECISION_GROUNDING_MARKERS
from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    ReviewReminder,
    WorkSpec,
    WorldModel,
)

# v3: 决策依据检查的"决策动作触发词"（出现在 goal/conflict 才检查回溯性）
_AGENCY_TRIGGERS: frozenset[str] = frozenset({
    "答应", "拒绝", "决定", "选择", "放弃", "背叛", "归顺", "妥协",
    "出手", "收手", "立誓", "投靠", "反叛", "认罪", "放过", "杀掉",
    "救下", "改投", "投降", "屈服", "反击",
})

# v3: 信息凭证检查（iss_info_*）——
# 亲历前提豁免词：命中表示该处已补上"确实有人到过场"的亲历前提，
# 转述+亲历细节共现不再视为凭证断裂（诚实区分"事故"与"已补前提"）。
_FIRSTHAND_WITNESS_MARKERS: frozenset[str] = frozenset({
    "亲眼", "亲耳", "亲口", "亲眼所见", "远远看过", "去看过", "见过一面",
    "到场", "见过", "当面", "在面前", "当场",
})

# B 档（08_failure_types 弱信号）：8 个失败类型的触发词表（对象层代理信号）。
# 命中仅是"可能"，正式判断由 review prompt 的 LLM 承担；词表按语义分组，
# 与文档定义的失败类型一一对应，语义细节见各规则注释。
_MOTIVATION_JUMP_MARKERS: frozenset[str] = frozenset({
    # 态度/立场突然转向，缺决策依据 → motivation_gap
    "突然信任", "突然坦白", "突然合作", "突然原谅", "突然投靠", "突然归顺",
    "放下戒备", "吐露心声", "开始信任", "接受道歉", "欣然同意", "一口答应",
})

_RELATIONSHIP_JUMP_MARKERS: frozenset[str] = frozenset({
    # 关系性质跃迁，缺桥接 → relationship_jump
    "宿敌和解", "托付秘密", "确认关系", "结为同盟", "生死之交", "化敌为友",
    "放下仇恨", "义结金兰", "以身相许", "冰释前嫌", "握手言和", "推心置腹",
})

_HIGH_RISK_MARKERS: frozenset[str] = frozenset({
    # 高风险/越界行为，缺代价 → missing_cost
    "越阶", "越级", "动用禁术", "强行突破", "强行越界", "违逆", "违背禁令",
    "闯禁区", "以命相搏", "透支", "燃烧寿元", "孤注一掷",
})

_COST_MARKERS: frozenset[str] = frozenset({
    "代价", "付出", "损失", "惩罚", "反噬", "反扑", "耗尽", "重伤", "折寿",
    "受罚", "牺牲", "失去", "付出代价",
})

_PAYOFF_MARKERS: frozenset[str] = frozenset({
    # 揭晓/反转触发词 → abrupt_payoff
    "真相大白", "终于明白", "恍然大悟", "水落石出", "揭晓", "真相是",
    "原来如此", "真凶", "谜底",
})


# B 档：失败类型字典（源自 docs/03_rules/08_failure_types.md §10 默认严重度 /
# §11 阻断倾向），注入审查 prompt 供 LLM 对齐 issue_type 词汇。
FAILURE_TYPE_LEXICON: tuple[tuple[str, str, str], ...] = (
    ("fact_conflict", "high/critical", "默认阻断"),
    ("world_violation", "high/critical", "默认阻断"),
    ("timeline_error", "high/critical", "默认阻断"),
    ("character_distortion", "high", "条件性阻断"),
    ("information_leak", "high", "条件性阻断"),
    ("abrupt_payoff", "medium/high", "条件性阻断"),
    ("motivation_gap", "medium/high", "通常不阻断"),
    ("relationship_jump", "medium/high", "通常不阻断"),
    ("weak_progression", "medium", "通常不阻断"),
    ("missing_cost", "medium/high", "通常不阻断"),
    ("promise_loss", "medium/high", "通常不阻断"),
    ("missing_consequence", "medium", "通常不阻断"),
    ("duplication_of_threads", "medium", "通常不阻断"),
    ("redundancy", "low/medium", "通常不阻断"),
    ("style_drift", "low/medium", "通常不阻断"),
    ("generative_indicia", "low/medium", "通常不阻断"),
)


def _failure_type_lexicon_text() -> str:
    """渲染【失败类型字典】段（LLM 对齐 issue_type 词汇用）。"""
    lines = ["【失败类型字典】"]
    for issue_type, severity, blocking in FAILURE_TYPE_LEXICON:
        lines.append(f"- {issue_type}（默认 {severity}，{blocking}）")
    return "\n".join(lines)


def _info_warrant_guidance_text() -> str:
    """渲染【信息凭证约束】段（09_information_warrant_rules 审查 prompt 注入）.

    覆盖通道谱系 + 聚焦三分 + 四条凭证约束 + 信息差距形态（合法/非法 4+4）。
    """
    sections = [build_info_warrant_guidance()]
    gap_lines = ["【信息差距形态】"]
    for gap in INFO_GAP_FORMS:
        kind = "合法" if gap["kind"] == "legal" else "非法"
        gap_lines.append(
            f"- [{kind}] {gap['name']}（{gap['relation']}）: {gap['driver']}"
            f" — 检测: {gap['detection']}"
        )
    sections.append("\n".join(gap_lines))
    return "\n\n".join(sections)


def _bigram_jaccard(a: str, b: str) -> float:
    """字符 2-gram Jaccard 相似度（中文字符 2-gram 交集 / 并集）。"""
    if not a or not b:
        return 0.0
    ga = set(zip(a, a[1:]))
    gb = set(zip(b, b[1:]))
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _text_related(text: str, content: str, min_bigrams: int = 2) -> bool:
    """弱相关判定：两段文本共享 ≥ min_bigrams 个字符 2-gram 即视为相关.

    用于 abrupt_payoff 判定"释放信息是否与活跃伏笔有铺垫交集"。
    要求 ≥2 个共享 bigram 是为了过滤'的/是/一'等高频虚字造成的过敏。
    """
    if not text or not content:
        return False
    gt = set(zip(text, text[1:]))
    gc = set(zip(content, content[1:]))
    return len(gt & gc) >= min_bigrams


def _pu_info_text(pu: PlotUnit) -> str:
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


_FORESHADOW_STOPWORDS = frozenset(
    (
        "的", "了", "是", "说", "在", "有", "和", "与", "就", "都", "也",
        "不", "没", "会", "要", "能", "把", "被", "让", "那", "这",
        "他", "她", "你", "我", "们", "一个", "什么", "怎么", "为什么",
        "它", "上", "下", "里", "时", "后", "前", "再", "又", "还", "只",
    )
)


def _foreshadow_keywords(content: str, max_keywords: int = 4) -> list[str]:
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
                if any(stop in word for stop in _FORESHADOW_STOPWORDS):
                    continue
                seen.add(word)
                keywords.append(word)
    return keywords[:max_keywords]


def _foreshadow_referenced(
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
    keywords = _foreshadow_keywords(entry.content)
    if not keywords:
        return False
    return any(any(kw in text for kw in keywords) for text in pu_texts)


class ReviewUnit:
    """审查重建结果或推进结果."""

    VALID_ROUTES = {"pass", "rewrite", "block"}

    def build_prompt(self, objects: list, context: str = "audit") -> str:
        """生成审查 prompt."""
        hard_issues = self._hard_rules(objects)
        domain_issues = self._domain_rules(objects)
        return self._build_prompt(objects, hard_issues, domain_issues, context)

    def parse_response(self, response: str) -> tuple[list[ReviewIssue], list[ReviewReminder], str]:
        """解析 LLM 审查响应.

        Returns:
            (ReviewIssue 列表, ReviewReminder 列表, 路由推荐)
        """
        data = json.loads(response)
        required_fields = ("issues", "reminders", "route")
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(
                f"Review response missing required field(s): {', '.join(missing)}"
            )
        extra = sorted(set(data) - set(required_fields))
        if extra:
            raise ValueError(
                f"Review response has unexpected field(s): {', '.join(extra)}"
            )
        if not isinstance(data["issues"], list):
            raise ValueError("Review response field issues must be a list")
        if not isinstance(data["reminders"], list):
            raise ValueError("Review response field reminders must be a list")
        issues = [ReviewIssue(**i) for i in data["issues"]]
        reminders = [ReviewReminder(**r) for r in data["reminders"]]
        route = data["route"]
        if route not in self.VALID_ROUTES:
            raise ValueError(f"Invalid review route: {route}")
        return issues, reminders, route

    def resolve_route(self, issues: list[ReviewIssue], route: str) -> str:
        """Resolve final route after code and LLM issues are merged."""
        has_blocking = any(issue.is_blocking() for issue in issues)
        if has_blocking and route == "pass":
            return "rewrite"
        if not has_blocking and route == "rewrite":
            return "pass"
        return route

    def _hard_rules(self, objects: list) -> list[ReviewIssue]:
        """代码层面硬规则检查，返回正式 ReviewIssue."""
        issues: list[ReviewIssue] = []
        char_models = [o for o in objects if isinstance(o, CharacterModel)]
        fact_ledgers = [o for o in objects if isinstance(o, FactLedger)]
        foreshadows = [o for o in objects if isinstance(o, ForeshadowGraph)]

        # 规则1: CharacterModel knowledge 和 misinformation 不应重叠
        for cm in char_models:
            overlap = set(cm.knowledge_state) & set(cm.misinformation)
            if overlap:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_overlap_{cm.character_id}",
                        issue_type="character_distortion",
                        severity="blocking",
                        location=f"CharacterModel {cm.character_id}",
                        scope_of_impact="角色认知一致性",
                        violated_rule="knowledge_state 与 misinformation 互斥",
                        description=f"角色 '{cm.name}' 的 knowledge 与 misinformation 重叠: {overlap}",
                    )
                )

        # 规则2: FactLedger 空检查
        for fl in fact_ledgers:
            if not fl.entries:
                issues.append(
                    ReviewIssue(
                        issue_id="iss_hard_empty_fl",
                        issue_type="fact_conflict",
                        severity="warning",
                        location="FactLedger",
                        scope_of_impact="全局事实基础",
                        violated_rule="FactLedger 不得为空",
                        description="FactLedger 为空 — 未建立任何 hard facts",
                    )
                )

        # 规则3: ForeshadowGraph 空检查
        for fg in foreshadows:
            if not fg.entries:
                issues.append(
                    ReviewIssue(
                        issue_id="iss_hard_empty_fg",
                        issue_type="promise_loss",
                        severity="warning",
                        location="ForeshadowGraph",
                        scope_of_impact="承诺追踪",
                        violated_rule="ForeshadowGraph 不得为空",
                        description="ForeshadowGraph 为空 — 无伏笔/承诺被追踪",
                    )
                )

        # 规则4: 角色ID一致性
        char_ids = {cm.character_id for cm in char_models}
        for cm in char_models:
            for rel_id in cm.relations:
                if rel_id not in char_ids:
                    issues.append(
                        ReviewIssue(
                            issue_id=f"iss_hard_rel_{cm.character_id}",
                            issue_type="character_distortion",
                            severity="blocking",
                            location=f"CharacterModel {cm.character_id}",
                            scope_of_impact="角色关系网络",
                            violated_rule="relations 必须指向已知角色",
                            description=f"角色 '{cm.name}' 关联了未知 ID: {rel_id}",
                        )
                    )

        narrative_states = [o for o in objects if isinstance(o, NarrativeState)]
        if char_ids:
            for ns in narrative_states:
                for character_id in ns.active_characters:
                    if character_id not in char_ids:
                        issues.append(
                            ReviewIssue(
                                issue_id=(
                                    f"iss_hard_active_character_"
                                    f"{ns.state_id}_{character_id}"
                                ),
                                issue_type="character_distortion",
                                severity="blocking",
                                location=f"NarrativeState {ns.state_id}",
                                scope_of_impact="active character references",
                                violated_rule=(
                                    "NarrativeState.active_characters must reference "
                                    "known CharacterModel.character_id"
                                ),
                                description=(
                                    f"NarrativeState '{ns.state_id}' references unknown "
                                    f"active character ID: {character_id}"
                                ),
                            )
                        )

        # 规则5: PlotUnit 的 output_state_ref 必须指向存在的 NarrativeState
        plotunits = [o for o in objects if isinstance(o, PlotUnit)]
        state_ids = {ns.state_id for ns in narrative_states}

        for pu in plotunits:
            if pu.input_state_ref and pu.input_state_ref not in state_ids:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_input_state_ref_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="state transition chain",
                        violated_rule=(
                            "PlotUnit.input_state_ref must reference an existing "
                            "NarrativeState.state_id"
                        ),
                        description=(
                            f"PlotUnit '{pu.unit_id}' input_state_ref "
                            f"'{pu.input_state_ref}' does not exist in current "
                            "NarrativeState objects"
                        ),
                    )
                )
            if pu.output_state_ref and pu.output_state_ref not in state_ids:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_state_ref_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="状态链连续性",
                        violated_rule="PlotUnit.output_state_ref 必须指向存在的 NarrativeState",
                        description=(
                            f"PlotUnit '{pu.unit_id}' 的 output_state_ref "
                            f"'{pu.output_state_ref}' 不存在于当前 NarrativeState 列表"
                        ),
                    )
                )
            if not pu.is_effective:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_ineffective_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="推进有效性",
                        violated_rule="PlotUnit 必须导致有意义状态变化",
                        description=(
                            f"PlotUnit '{pu.unit_id}' 未被标记为有效推进；"
                            "不能作为通过结果继续流转"
                        ),
                    )
                )
            if char_ids:
                for character_id in pu.participants:
                    if character_id not in char_ids:
                        issues.append(
                            ReviewIssue(
                                issue_id=(
                                    f"iss_hard_plotunit_participant_"
                                    f"{pu.unit_id}_{character_id}"
                                ),
                                issue_type="character_distortion",
                                severity="blocking",
                                location=f"PlotUnit {pu.unit_id}",
                                scope_of_impact="PlotUnit participant references",
                                violated_rule=(
                                    "PlotUnit.participants must reference known "
                                    "CharacterModel.character_id"
                                ),
                                description=(
                                    f"PlotUnit '{pu.unit_id}' references unknown "
                                    f"participant ID: {character_id}"
                                ),
                            )
                        )

        # 规则6: active 状态的 ForeshadowEntry 必须至少被一个 PlotUnit 引用
        # （显式 linked_plotunits id，或任一 PlotUnit 信息文本提及伏笔核心内容）
        plotunit_ids = {pu.unit_id for pu in plotunits}
        pu_texts = [_pu_info_text(pu) for pu in plotunits]

        for fg in foreshadows:
            for entry in fg.get_active():
                if _foreshadow_referenced(entry, plotunit_ids, pu_texts):
                    continue
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_foreshadow_{entry.thread_id}",
                        issue_type="promise_loss",
                        severity="warning",
                        location=f"ForeshadowGraph {entry.thread_id}",
                        scope_of_impact="承诺追踪",
                        violated_rule="active 伏笔必须有 PlotUnit 引用",
                        description=(
                            f"伏笔 '{entry.content}' (setup: {entry.setup_point}) "
                            "处于 active 状态，但未被任何 PlotUnit 显式引用或推进"
                        ),
                        suggested_fix="在后续 PlotUnit 中回收此伏笔，或标记为 abandoned",
                        )
                    )

        # 规则7: 同一实体在同一时间点不应有矛盾事件
        time_facts = defaultdict(list)
        for fl in fact_ledgers:
            for entry in fl.entries:
                if entry.fact_type == "time_order" and entry.timestamp:
                    entities_key = (
                        tuple(sorted(entry.involved_entities))
                        if entry.involved_entities
                        else ("__none__",)
                    )
                    key = (entry.timestamp, entities_key)
                    time_facts[key].append(entry)

        for (timestamp, entities), entries in time_facts.items():
            if len(entries) > 1:
                statements = [e.statement for e in entries]
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_time_{timestamp}_{'_'.join(entities)}",
                        issue_type="fact_conflict",
                        severity="warning",
                        location="FactLedger",
                        scope_of_impact="时间线一致性",
                        violated_rule="同一实体在同一时间点不应有多条 time_order 事实",
                        description=(
                            f"时间点 '{timestamp}'，实体 {list(entities)} 有 "
                            f"{len(entries)} 条 time_order 事实: {statements}"
                        ),
                    )
                )

        return issues

    def _domain_rules(self, objects: list) -> list[ReviewIssue]:
        """领域层规则检查，返回正式 ReviewIssue."""
        issues: list[ReviewIssue] = []

        plotunits = [o for o in objects if isinstance(o, PlotUnit)]

        # 提取平台约束
        workspecs = [o for o in objects if isinstance(o, WorkSpec)]
        platform_id = workspecs[0].platform if workspecs else None
        platform_constraints = get_platform_constraints(platform_id) if platform_id else {}
        hook_pressure = platform_constraints.get("hook_pressure", "")
        reader_patience = platform_constraints.get("reader_patience", "")

        # 检查 PlotUnit hook 合法性
        for pu in plotunits:
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

        # 检查 emotional_shift 非空（当 structure_template 存在时）
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

        # 平台约束检查
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

        # Hook effectiveness 检查
        for pu in plotunits:
            if pu.formula_node and is_critical_hook_node(pu.formula_node) and pu.hook:
                effectiveness = get_hook_effectiveness(pu.hook, pu.level)
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
                                f"但 hook '{pu.hook}' 的 effectiveness 为 '{effectiveness}'，"
                                f"建议使用 high-effectiveness 钩子。"
                            ),
                        )
                    )

        # 新增：情绪-结构节点匹配检查
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

        # generative_indicia 启发式检测
        generative_markers = {
            "sudden_transitions": {"突然", "瞬间", "猛然", "骤然", "蓦地"},
            "over_modifiers": {"不可置信地", "难以置信地", "不由自主地", "下意识地"},
            "emotional_stacking": {"崩溃", "绝望", "疯狂", "撕心裂肺", "肝肠寸断"},
        }

        for pu in plotunits:
            text_to_check = " ".join(filter(None, [pu.goal, pu.conflict, pu.emotional_shift or ""]))
            found_modifiers = [
                marker
                for marker in generative_markers["over_modifiers"]
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
                    for word in generative_markers["emotional_stacking"]
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

        # ---- v3: 决策依据可回溯性（iss_agency_*）----
        # CharacterModel 已含 identity/outer_goal/fear/flaw/stance（决策依据层）。
        # 启发式弱信号：PlotUnit 的冲突/目标含"决策动作触发词"但完全无显式依据
        # 标记时，提示复核该选择是否有身份/信念依据 —— 诚实标注对象层代理性，
        # 真正判断在 LLM（区分"有意的戏剧性反转" vs "无依据的剧情需要/工具人"）。
        if any(isinstance(o, CharacterModel) for o in objects):
            for pu in plotunits:
                decision_text = " ".join(
                    filter(None, [pu.goal, pu.conflict])
                )
                if not decision_text:
                    continue
                if not any(marker in decision_text for marker in _AGENCY_TRIGGERS):
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

        # ---- v3: 描写分层失衡（iss_layering_*）----
        # 直给型陈述（解释腔/情绪宣布词）在 PlotUnit 字段出现 → 弱信号：
        # 该处可能"直给"了（他感到/涌起一股），散文型气质应改白描/衬托呈现。
        # 诚实标注：对象层无正文，这是代理信号，需在正文层确认（LLM 复核）。
        layering_markers = set(EXPLANATORY_PHRASES) | set(EMOTION_ANNOUNCEMENT_PHRASES)
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

        # ---- v3: 信息凭证检查（iss_info_channel_*）----
        # CharacterModel.knowledge_state 是平铺字符串（知道什么），不携带通道/时效。
        # 此处做对象层弱信号：同一单元"亲历细节词 + 未知/未接触否定词"共现，
        # 提示该处亲历细节可能越过了信息通道（P1 亲历凭证）。诚实标注代理性，
        # 真正判断在 LLM（区分"已补亲历前提" vs "通道断裂"）。
        for pu in plotunits:
            info_text = _pu_info_text(pu)
            if not info_text:
                continue
            firsthand_hits = [
                m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text
            ]
            unknown_hits = [
                m for m in UNKNOWN_NEGATION_MARKERS if m in info_text
            ]
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

        # ---- v3: 转述通道产出亲历细节（iss_info_relay_*）----
        # 信息经转述流入（电话/捎话/汇报）时，产出亲历型细节且无亲历前提豁免词
        # → 提示转述通道产出了转述者未亲历的细节（P3 渠道凭证 / P2 时效）。
        for pu in plotunits:
            info_text = _pu_info_text(pu)
            if not info_text:
                continue
            if any(m in info_text for m in _FIRSTHAND_WITNESS_MARKERS):
                continue  # 已补亲历前提（如"远远看过"），不算断裂
            relay_hits = [m for m in RELAY_MARKERS if m in info_text]
            firsthand_hits = [
                m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text
            ]
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

        # ---- v3: 知识域翻转（iss_info_scope_*）----
        # CharacterModel.knowledge_state 含明确"未知/未接触"断言，但该角色参与的
        # PlotUnit 产出亲历细节 → 提示前文断言未知、后文却依赖细节（P4 容量凭证）。
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
                info_text = _pu_info_text(pu)
                if not info_text:
                    continue
                firsthand_hits = [
                    m for m in FIRSTHAND_DETAIL_MARKERS if m in info_text
                ]
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

        # ---- B 档：8 个失败类型弱信号（全部 warning/low 非阻断）----
        # 对象层无正文，命中仅是"可能"，正式阻断判断由 review prompt 的 LLM 承担。
        # 代理信号说明写进 description，避免把代理当实证。
        states = {ns.state_id: ns for ns in objects if isinstance(ns, NarrativeState)}
        foreshadows = [o for o in objects if isinstance(o, ForeshadowGraph)]
        worlds = [o for o in objects if isinstance(o, WorldModel)]

        # iss_leak_* → information_leak
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
                info_text = _pu_info_text(pu)
                leaked = []
                for claim in neg_claims:
                    for neg in UNKNOWN_NEGATION_MARKERS:
                        if neg not in claim:
                            continue
                        subject = claim.replace(neg, "").strip("，,。 ")
                        # 实体关键词匹配：subject 内任意字符 2-gram 出现在释放信息
                        # → 提示该主题被当作已知释放（整串包含太脆，放宽到 2-gram）。
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

        # iss_motivation_* → motivation_gap
        # 含态度跃迁词但无决策依据词 → "方向可理解但缺桥"。
        for pu in plotunits:
            text = _pu_info_text(pu)
            if not any(m in text for m in _MOTIVATION_JUMP_MARKERS):
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
                        f"（{[m for m in _MOTIVATION_JUMP_MARKERS if m in text]}）"
                        f"但无决策依据词。提示转向可理解但缺桥——"
                        f"请确认该角色为何在此刻改变立场。"
                    ),
                )
            )

        # iss_cost_* → missing_cost
        # 世界有规则/后果逻辑 且 含高风险行为词 但后果无代价词 → 缺代价。
        if any(w.prohibitions or w.consequence_logic for w in worlds):
            for pu in plotunits:
                text = _pu_info_text(pu)
                if not any(m in text for m in _HIGH_RISK_MARKERS):
                    continue
                if any(m in text for m in _COST_MARKERS):
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
                            f"（{[m for m in _HIGH_RISK_MARKERS if m in text]}），"
                            f"但后果清单无代价词。提示高风险行为缺代价——"
                            f"请确认该行为是否真的免费，还是代价未显式化。"
                        ),
                    )
                )

        # iss_consequence_* → missing_consequence
        # 释放了新信息但输入/输出局势完全未变 → 揭露无后果。
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

        # iss_reljump_* → relationship_jump
        # 含关系跃迁词但无决策依据 → 关系移动缺桥。
        for pu in plotunits:
            text = _pu_info_text(pu)
            if not any(m in text for m in _RELATIONSHIP_JUMP_MARKERS):
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
                        f"（{[m for m in _RELATIONSHIP_JUMP_MARKERS if m in text]}）"
                        f"但无决策依据。提示关系移动缺桥——"
                        f"请确认这次关系变化是否凭空发生。"
                    ),
                )
            )

        # iss_redundancy_* → redundancy
        # 相邻 PlotUnit 的 conflict 或 hook 完全重复（goal 重复由 iss_genind3 管）。
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

        # iss_abrupt_* → abrupt_payoff
        # 释放信息含揭晓词但无活跃伏笔与其有铺垫交集 → 突兀揭晓。
        active_threads = [
            e for fg in foreshadows for e in fg.entries
            if e.current_status == "active"
        ]
        for pu in plotunits:
            rel_text = " ".join(pu.released_information)
            if not rel_text:
                continue
            if not any(m in rel_text for m in _PAYOFF_MARKERS):
                continue
            if any(_text_related(rel_text, e.content) for e in active_threads):
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
                        f"（{[m for m in _PAYOFF_MARKERS if m in rel_text]}）"
                        f"但没有活跃伏笔与其有明显铺垫交集。提示揭晓可能突兀——"
                        f"请确认该真相是否早已埋设。"
                    ),
                )
            )

        # iss_dupthread_* → duplication_of_threads
        # 两条活跃伏笔 content 字符 2-gram Jaccard ≥ 0.5 → 线程重复。
        if len(active_threads) >= 2:
            for i in range(len(active_threads)):
                for j in range(i + 1, len(active_threads)):
                    a, b = active_threads[i], active_threads[j]
                    sim = _bigram_jaccard(a.content, b.content)
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

    def _build_prompt(
        self,
        objects: list,
        hard_issues: list[ReviewIssue],
        domain_issues: list[ReviewIssue],
        context: str,
    ) -> str:
        """生成审查 prompt."""
        obj_ctx = []
        for obj in objects:
            if hasattr(obj, "to_prompt_context"):
                obj_ctx.append(obj.to_prompt_context())

        hard_section = ""
        if hard_issues:
            hard_section = "\n【代码硬规则已发现问题】\n" + "\n".join(
                f"- [{issue.severity}] {issue.issue_type}: {issue.description}"
                for issue in hard_issues
            )

        domain_section = ""
        if domain_issues:
            domain_section = "\n【领域规则已发现问题】\n" + "\n".join(
                f"- [{issue.severity}] {issue.issue_type}: {issue.description}"
                for issue in domain_issues
            )

        # B 档：失败类型字典（08_failure_types §10 默认严重度 + §11 阻断倾向）
        lexicon_section = "\n" + _failure_type_lexicon_text()

        # D 档：信息凭证指导（09_information_warrant_rules 审查 prompt 注入）
        warrant_section = "\n" + _info_warrant_guidance_text()

        object_summary = "\n---\n".join(obj_ctx)

        return f"""你是一位叙事审查专家。请对以下叙事对象层进行审查。
【审查上下文】{context}
{hard_section}{domain_section}

【对象层摘要】
{object_summary}

【审查维度】
1. 事实一致性: FactLedger 条目是否自洽? 是否有矛盾?
2. 角色一致性: CharacterModel 行为逻辑是否自洽? 目标/恐惧/缺陷是否驱动决策?
3. 世界合法性: WorldModel 规则是否被尊重? 是否有无代价的违规行为?
4. 承诺追踪: ForeshadowGraph 是否活跃? 是否有承诺被遗忘?
5. 状态有效性: NarrativeState 是否可运行? 时间/地点/冲突是否清晰?
{lexicon_section}

{warrant_section}

【Track 1 约束】
- 只审查硬事实, 不审查推断
- 不要把 working-state pressure 当成 fact violation

【Track 3 约束】
- 检查 CharacterModel 是否只存结论
- 检查 knowledge_state 是否混入支撑证据

【输出格式】严格输出 JSON:
{{
  "issues": [
    {{
      "issue_id": "iss_001",
      "issue_type": "fact_conflict",
      "severity": "warning",
      "location": "FactLedger",
      "scope_of_impact": "后续所有依赖该事实的推断",
      "violated_rule": "事实一致性",
      "description": "描述",
      "suggested_fix": "可选"
    }}
  ],
  "reminders": [
    {{
      "reminder_id": "rem_001",
      "family": "promise_followup_needed",
      "trigger_condition": "3个PlotUnit内未回收",
      "window": "plotunit_count=2",
      "escalation_issue_type": "missing_consequence",
      "early_escalation_condition": "same thread reminder repeats",
      "closure_condition": "promise is advanced, narrowed, or delayed with cost",
      "priority": "medium"
    }}
  ],
  "route": "pass"
}}

如无问题，返回空 issues 和 "pass" 路由。"""

    def is_pass(self, issues: list[ReviewIssue]) -> bool:
        """判断是否通过（无阻断性问题）."""
        return not any(issue.is_blocking() for issue in issues)
