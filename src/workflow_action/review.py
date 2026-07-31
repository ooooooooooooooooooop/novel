"""ReviewUnit — 审查工作流."""

import json
from collections import defaultdict

from src.domain_layer.rules import (
    get_hook_effectiveness,
    get_platform_constraints,
    get_recommended_emotions,
    is_critical_hook_node,
    validate_node_emotion,
    validate_plotunit_hook,
)
from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    ReviewReminder,
    WorkSpec,
)


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
        plotunit_ids = {pu.unit_id for pu in plotunits}

        for fg in foreshadows:
            for entry in fg.get_active():
                linked = set(entry.linked_plotunits or [])
                if not linked.intersection(plotunit_ids):
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
                                "处于 active 状态，但没有 PlotUnit 引用它"
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
