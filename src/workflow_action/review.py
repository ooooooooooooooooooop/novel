"""ReviewUnit — 审查工作流（对象层一致性审查编排器）.

职责边界（重构解耦）：
- 硬规则 `_hard_rules`：校验对象层契约（state_ref 存在性/角色 ID 一致性/
  事实时间冲突/Foreshadow 引用）——属核心1 一致性审查的编排职责，保留本处。
- 领域弱信号：已拆分到 src/domain_layer/review_signals.py（每类失败类型一个
  detect_* 检测器），`_domain_rules` 只做循环调用汇总。
- prompt 渲染 / 路由解析 / 正文级复核：保留本处。

数据表（触发词/失败类型字典/四层分类）在 src/domain_layer/
review_signal_knowledge.py；FAILURE_TYPE_LEXICON 在此 re-export
（测试与 prompt 渲染依赖 `from src.workflow_action.review import FAILURE_TYPE_LEXICON`）。
"""

import json
import re
from collections import defaultdict

from src.domain_layer.review_signal_knowledge import FAILURE_TYPE_LEXICON
from src.domain_layer.review_signals import (
    run_all_signal_detectors,
)
from src.domain_layer.info_warrant_knowledge import (
    INFO_GAP_FORMS,
)
from src.domain_layer.info_warrant_rules import build_info_warrant_guidance
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


# F3a：可做正文级复核的 issue 类型（对象层弱信号、正文层可兑现）。
_PROSE_RECHECK_TYPES = frozenset(
    ("abrupt_payoff", "promise_loss", "missing_consequence", "character_distortion")
)


def _prose_evidence(desc: str, prose_text: str, window: int = 20) -> str:
    """在正文中定位与 issue 描述共享 2-gram 的首次命中点，取邻窗作证据片段."""
    desc_bigrams = set(zip(desc, desc[1:]))
    for pos in range(len(prose_text) - 1):
        if (prose_text[pos], prose_text[pos + 1]) in desc_bigrams:
            start = max(0, pos - window // 2)
            end = min(len(prose_text), pos + window)
            return prose_text[start:end]
    return ""


def recheck_against_prose(issues, prose_text: str, evidence_chars: int = 40) -> list[dict]:
    """正文级复核（F3a）：对对象层 issue 做 prose 兑现检查，返回标注（不改 route）.

    对象层 Review 在成文前运行，部分 issue（伏笔/承诺/后果/角色）可能在成文
    正文中已被自然兑现——这些是"对象层弱信号、正文层已解决"的噪声。本函数对
    prose-recheckable 类型 issue 判定其描述与正文的相关性（字符 2-gram ≥2）：

    - 相关 → prose_confirmed=True，附命中片段证据（evidence）；
    - 不相关 → prose_confirmed=False；
    - 其余类型 → prose_confirmed=None（不适用，保持对象层原判）。

    返回值仅用于展示/注释，不修改 issue、不改 route。
    """
    if not prose_text or not prose_text.strip():
        return []
    results: list[dict] = []
    for issue in issues:
        entry: dict = {
            "issue_id": issue.issue_id,
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "location": issue.location,
        }
        if issue.issue_type not in _PROSE_RECHECK_TYPES:
            entry["prose_confirmed"] = None
            results.append(entry)
            continue
        confirmed = _text_related(issue.description, prose_text)
        entry["prose_confirmed"] = confirmed
        if confirmed:
            entry["evidence"] = _prose_evidence(
                issue.description, prose_text
            )[:evidence_chars]
        results.append(entry)
    return results


class ReviewUnit:
    """审查重建结果或推进结果."""

    VALID_ROUTES = {"pass", "rewrite", "block"}

    def build_prompt(self, objects: list, context: str = "audit") -> str:
        """生成审查 prompt."""
        hard_issues = self._hard_rules(objects)
        domain_issues = self._domain_rules(objects)
        return self._build_prompt(objects, hard_issues, domain_issues, context)

    def parse_response(
        self,
        response: str,
        foreshadows: list | None = None,
        character_models: list | None = None,
    ) -> tuple[list[ReviewIssue], list[ReviewReminder], str]:
        """解析 LLM 审查响应.

        Args:
            response: LLM 返回的 JSON 文本。
            foreshadows: 可选 ForeshadowGraph 列表；响应含 foreshadow_updates 时，
                就地更新对应线程状态（正文已兑现的承诺在此落为 resolved，消除
                后续 promise_loss 重复误报）。
            character_models: 可选 CharacterModel 列表；响应含
                character_knowledge_updates 时，就地同步角色已知信息（移除已过期
                的『不知道X』断言，消除信息凭证重复误报）。

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
        allowed_fields = required_fields + (
            "foreshadow_updates",
            "character_knowledge_updates",
        )
        extra = sorted(set(data) - set(allowed_fields))
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
        if foreshadows:
            updates = data.get("foreshadow_updates") or []
            if not isinstance(updates, list):
                raise ValueError("Review response field foreshadow_updates must be a list")
            self._apply_foreshadow_updates(foreshadows, updates)
        if character_models:
            updates = data.get("character_knowledge_updates") or []
            if not isinstance(updates, list):
                raise ValueError(
                    "Review response field character_knowledge_updates must be a list"
                )
            self._apply_knowledge_updates(character_models, updates)
        return issues, reminders, route

    @staticmethod
    def _apply_foreshadow_updates(foreshadows: list, updates: list) -> None:
        """把 review 声明的线程状态更新落到 ForeshadowGraph（unknown id 静默跳过）."""
        for item in updates:
            if not isinstance(item, dict):
                continue
            thread_id = item.get("thread_id")
            status = item.get("status")
            if not isinstance(thread_id, str) or not thread_id.strip():
                continue
            if not isinstance(status, str) or not status.strip():
                continue
            for fg in foreshadows:
                fg.set_status(thread_id.strip(), status.strip())

    @staticmethod
    def _apply_knowledge_updates(character_models: list, updates: list) -> None:
        """把 review 声明的角色已知信息更新落到 CharacterModel（unknown id 静默跳过）."""
        by_id = {cm.character_id: cm for cm in character_models}
        for item in updates:
            if not isinstance(item, dict):
                continue
            character_id = item.get("character_id")
            if not isinstance(character_id, str) or character_id.strip() not in by_id:
                continue
            cm = by_id[character_id.strip()]
            learn = item.get("learn")
            drop_unknown = item.get("drop_unknown")
            if isinstance(learn, list) and learn:
                cm.reconcile_knowledge(learn=learn)
            if isinstance(drop_unknown, list) and drop_unknown:
                cm.reconcile_knowledge(drop_unknown=drop_unknown)

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
        """领域层规则检查，返回正式 ReviewIssue.

        弱信号检测已拆分到 src/domain_layer/review_signals.py（每类失败类型
        一个 detect_* 检测器，按注册表顺序汇总）。本方法只做编排——调用
        run_all_signal_detectors 汇总，issue 列表逐条与解耦前一致（零回归契约）。
        """
        return run_all_signal_detectors(objects)


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
  "route": "pass",
  "foreshadow_updates": [
    {{
      "thread_id": "th_002",
      "status": "resolved",
      "note": "该伏笔在正文已兑现/回收，从活跃承诺中移除"
    }}
  ],
  "character_knowledge_updates": [
    {{
      "character_id": "c001",
      "learn": ["苏观使找了十二年"],
      "drop_unknown": ["不知道苏观使找了十二年"]
    }}
  ]
}}

如无问题，返回空 issues 和 "pass" 路由。
foreshadow_updates 可选：仅当某 active 伏笔在本章（含其后果/正文）已被兑现或
明确推进时列出，status 取 active/resolved/abandoned/transformed/open/delayed/
false_path 之一；仍开放的承诺不要列入（保持 active）。
character_knowledge_updates 可选：仅当某角色在本章得知了新信息（情节揭示给了他），
把对应的『不知道X』断言从 drop_unknown 移除、把新得知的信息加入 learn；角色仍
不知道的不要列入。"""

    def is_pass(self, issues: list[ReviewIssue]) -> bool:
        """判断是否通过（无阻断性问题）."""
        return not any(issue.is_blocking() for issue in issues)
