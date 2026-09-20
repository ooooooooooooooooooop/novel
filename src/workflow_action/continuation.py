"""ContinueUnit — 续写工作流."""

import json

from src.object_state.narrativestate import INFORMATION_LAYER_GUIDANCE

from src.domain_layer.rules import (
    build_hook_type_guidance,
    build_platform_guidance,
    get_genre_guidance,
    get_recommended_emotions,
    get_structure_template,
    is_critical_hook_node,
)
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
)


def admit_new_facts(
    facts: FactLedger,
    new_facts: list,
    source_plotunit: str,
) -> list[dict]:
    """Validate the entire batch before admission; callers still verify prose evidence.

    confirmed=true is a schema declaration, not evidence of an event in the prose.
    """
    if not isinstance(new_facts, list):
        raise ValueError("new_facts must be a list")

    existing_ids = {entry.fact_id for entry in facts.entries}
    admitted: list[dict] = []
    validated_entries: list[FactEntry] = []
    for raw_fact in new_facts:
        if not isinstance(raw_fact, dict):
            raise ValueError("new_facts entries must be JSON objects")
        fact_data = dict(raw_fact)
        if "confirmed" not in fact_data:
            raise ValueError("new_facts entries must declare confirmed=true")
        if fact_data["confirmed"] is not True:
            raise ValueError("new_facts entries must be confirmed hard facts")
        fact_data["source_plotunit"] = source_plotunit

        entry = FactEntry(**fact_data)
        if entry.fact_id in existing_ids:
            raise ValueError(f"duplicate new fact_id: {entry.fact_id}")
        validated_entries.append(entry)
        existing_ids.add(entry.fact_id)
        admitted.append(entry.model_dump(mode="json"))

    for entry in validated_entries:
        facts.add_fact(entry)
    return admitted


class ContinueUnit:
    """从当前状态生成下一 PlotUnit."""

    def build_prompt(
        self,
        state: NarrativeState,
        characters: list[CharacterModel],
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
        workspec_context: str = "",
        frame_context: dict | None = None,
        structure_template: str | None = None,
        platform: str | None = None,
        genre: str | None = None,
        style_context: str = "",
        retrieval_context: str = "",
        timeline_context: str = "",
        time_context: str = "",
        excerpt_context: str = "",
        original_style_context: str = "",
        nsfw_context: str = "",
        packet_context: str = "",
        contract_context: str = "",
        viability_note: str = "",
        occupied_unit_ids: list | None = None,
        reader_expectation_context: str = "",
    ) -> str:
        """生成续写 prompt."""
        return self._build_prompt(
            state,
            characters,
            facts,
            foreshadows,
            workspec_context,
            frame_context,
            structure_template,
            platform,
            genre,
            style_context,
            retrieval_context,
            timeline_context,
            time_context,
            excerpt_context,
            original_style_context,
            nsfw_context,
            packet_context,
            contract_context,
            viability_note,
            occupied_unit_ids,
            reader_expectation_context,
        )

    def parse_response(self, response: str) -> tuple[PlotUnit, NarrativeState, list[str], list[str]]:
        """解析 LLM 续写响应.

        Returns:
            (PlotUnit, 新NarrativeState, 新增事实列表, confidence_gaps)
        """
        data = json.loads(response)
        required_fields = ("plotunit", "new_state", "new_facts", "confidence_gaps")
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(
                f"Continue response missing required field(s): {', '.join(missing)}"
            )
        extra = sorted(set(data) - set(required_fields))
        if extra:
            raise ValueError(
                f"Continue response has unexpected field(s): {', '.join(extra)}"
            )

        if not isinstance(data["new_facts"], list):
            raise ValueError("Continue response field new_facts must be a list")
        if not isinstance(data["confidence_gaps"], list):
            raise ValueError("Continue response field confidence_gaps must be a list")
        if not all(isinstance(gap, str) for gap in data["confidence_gaps"]):
            raise ValueError(
                "Continue response field confidence_gaps must be a list of strings"
            )
        if any(not gap.strip() for gap in data["confidence_gaps"]):
            raise ValueError(
                "Continue response field confidence_gaps entries must be non-empty"
            )

        plotunit = PlotUnit(**data["plotunit"])
        new_state = NarrativeState(**data["new_state"])
        new_facts = data["new_facts"]
        gaps = data["confidence_gaps"]

        return plotunit, new_state, new_facts, gaps

    def _build_prompt(
        self,
        state: NarrativeState,
        characters: list[CharacterModel],
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
        workspec_context: str,
        frame_context: dict | None,
        structure_template: str | None,
        platform: str | None,
        genre: str | None,
        style_context: str,
        retrieval_context: str,
        timeline_context: str = "",
        time_context: str = "",
        excerpt_context: str = "",
        original_style_context: str = "",
        nsfw_context: str = "",
        packet_context: str = "",
        contract_context: str = "",
        viability_note: str = "",
        occupied_unit_ids: list | None = None,
        reader_expectation_context: str = "",
    ) -> str:
        char_ctx = "\n---\n".join(c.to_prompt_context() for c in characters)
        # 离场人物在场感（§14 盲续写迭代：让单章多线并置时能自然召回离场人物近况。
        # 机制级修复——信息本已在角色状态里，这里显式标出"仍活在世界中"的离场者，
        # 避免生成器把整章压成单一待办引擎。零成本：无离场人物或 state 未标明在场者
        # 时为空段，prompt 字节不变）。
        offstage_ctx = ""
        active_ids = set(state.active_characters) if state and state.active_characters else None
        if active_ids:
            offstage = [c for c in characters if c.character_id not in active_ids]
            if offstage:
                lines = ["\n\n【离场人物在场感】"]
                lines.append(
                    "以下人物此刻不在当前场景，但仍在世界中有自己的生活与动向；"
                    "续写可在自然处召回其近况（不必每个都出现，也不要把他们彻底遗忘）："
                )
                for c in offstage:
                    bits = [f"{c.name}({c.character_id})"]
                    if c.identity:
                        bits.append(c.identity)
                    if c.current_pressure:
                        bits.append("近况:" + "；".join(c.current_pressure))
                    elif c.change_trajectory:
                        bits.append("动向:" + "；".join(c.change_trajectory))
                    if c.relations:
                        rels = "；".join(f"{k}:{v}" for k, v in list(c.relations.items())[:3])
                        bits.append("关系:" + rels)
                    lines.append("- " + "；".join(bits))
                offstage_ctx = "\n".join(lines)
        active_threads = foreshadows.get_active()
        thread_ctx = "\n".join(f"- {e.content}" for e in active_threads) if active_threads else "无"
        frame_section = ""
        emotion_section = ""
        hook_section = ""
        if frame_context is not None:
            if frame_context.get("no_active_frame"):
                # 终止帧已消费且无 successor：诚实进入 no-active-frame，不注入陈旧帧
                frame_section = (
                    "\n\n【层级上下文】\n"
                    '{"current_frame": null, "note": "无活跃叙事帧——当前结构已结束，'
                    '下一幕需由人工/规划层指定。"}'
                )
            else:
                frame_section = (
                    "\n\n【层级上下文】\n"
                    + json.dumps(frame_context, ensure_ascii=False, indent=2)
                )
                current_frame = frame_context.get("current_frame", {}) or {}
                formula_node = current_frame.get("formula_node", "")
                if formula_node:
                    recommended = get_recommended_emotions(formula_node)
                    if recommended:
                        emotion_lines = [
                            "\n\n【当前叙事阶段走向】",
                            f"当前结构节点: {formula_node}",
                            f"推荐情绪: {' / '.join(recommended)}",
                            "请让 emotional_shift 体现以上某种情绪变化。",
                        ]
                        if is_critical_hook_node(formula_node):
                            emotion_lines.append(
                                "【关键节点钩子要求】建议使用 high-effectiveness 钩子"
                                "（如 cliffhanger / reveal / in_media_res / revelation）。"
                            )
                        emotion_section = "\n".join(emotion_lines)
                # 显式 hook_type 枚举注入：已知层级（scene/chapter）时提示生成器
                # 填显式钩子类型，供 review 对已填值做严格层级校验。零成本：无
                # frame / level 未映射（book/arc/未知）时不注入，prompt 字节不变。
                hook_guidance = build_hook_type_guidance(current_frame.get("level", ""))
                if hook_guidance:
                    hook_section = "\n\n" + hook_guidance
        platform_section = ""
        if platform:
            guidance = build_platform_guidance(platform)
            if guidance:
                platform_section = f"\n\n{guidance}"
        genre_section = ""
        if genre:
            guidance = get_genre_guidance(genre)
            if guidance:
                genre_section = f"\n\n{guidance}"
        style_section = ""
        if style_context:
            style_section = f"\n\n【写作风格】\n{style_context}"
        time_section = ""
        if time_context:
            time_section = f"\n\n【时间上下文】\n{time_context}"
        retrieval_section = ""
        if retrieval_context:
            retrieval_section = f"\n\n【相关事实检索】\n{retrieval_context}"
        timeline_section = ""
        if timeline_context:
            timeline_section = f"\n\n【已发生事件时间线】\n{timeline_context}"
        excerpt_section = ""
        if excerpt_context:
            excerpt_section = f"\n\n【上文锚点（接续）】\n{excerpt_context}"
        original_style_section = ""
        if original_style_context:
            original_style_section = f"\n\n【原文文风参考】\n{original_style_context}"
        nsfw_section = ""
        if nsfw_context:
            nsfw_section = f"\n\n【内容分级】\n{nsfw_context}"
        # 本章上下文包（V2 Context Firewall）：正文模型只看 SELECT + 必要信息，
        # 看不到 BACKGROUND/DORMANT/完整 State。零成本：无 packet 时空段，prompt 字节不变。
        packet_section = ""
        if packet_context:
            packet_section = f"\n\n【本章上下文包】\n{packet_context}"
        # 读者契约（Q1 R3）：逐作品总规格。零成本：无契约时为空段，字节不变。
        contract_section = ""
        if contract_context:
            contract_section = f"\n\n【读者契约】\n{contract_context}"
        # 续写可行性注记（Q1 R1）：viability 判定通过后给生成器的明确注记。
        # 零成本：continue 无歧义时通常为空串，不注入。
        viability_section = ""
        if viability_note:
            viability_section = f"\n\n【续写可行性】\n{viability_note}"
        structure_section = ""
        if structure_template:
            nodes = get_structure_template(structure_template)
            if nodes:
                nodes_text = "\n".join(
                    f"- {n['name']} ({n['position']}): {n['purpose']}" for n in nodes
                )
                structure_section = (
                    f"\n\n【结构模板: {structure_template}】\n{nodes_text}"
                )
        # 已占用 PlotUnit id 显式化（hidden contract fix）：唯一性由 parser 强制，
        # id 空间必须对模型可见，否则只能撞号再失败。
        occupied_ids_note = ""
        if occupied_unit_ids:
            occupied_ids_note = (
                f"；当前已占用 unit_id: {'、'.join(sorted(occupied_unit_ids))}"
            )
        # 读者预期台账（dim7）：OPEN 预期是 expectation_intents 的作用对象。
        # 零成本：台账空/无开放预期时为空段，prompt 字节不变。
        expectation_section = ""
        if reader_expectation_context:
            expectation_section = (
                f"\n\n【读者预期台账】\n{reader_expectation_context}"
            )

        return f"""你是一位叙事续写专家。请基于当前叙事状态，生成下一个 PlotUnit。

【作品约束】
{workspec_context}{platform_section}{genre_section}{style_section}{time_section}{timeline_section}{excerpt_section}{original_style_section}{retrieval_section}{nsfw_section}{packet_section}{contract_section}{viability_section}

【当前叙事状态】
{state.to_prompt_context()}

【角色状态】
{char_ctx}
{offstage_ctx}

【已确认事实】
{facts.to_prompt_context()}

【活跃承诺/伏笔】
{thread_ctx}
{structure_section}{frame_section}{emotion_section}{hook_section}{expectation_section}

【续写要求】

{INFORMATION_LAYER_GUIDANCE}
new_state 是单元结束后的完整快照，保留仍有效的旧信息，不只填写本章增量。
计划通过 released_information 向读者揭示的信息，不能同时保留为输出状态的 hidden_information；
角色是否知情另按证据记录，不能因读者获知就自动移入 public_information。

1. PlotUnit 必须导致有意义的状态变化
2. 角色行为必须符合 CharacterModel 的驱动力、恐惧和缺陷
3. 新信息释放必须服务于 ForeshadowGraph 的承诺推进
4. 必须体现至少一个世界规则约束或代价
5. 不能一次性解决所有悬念，但可以推进其中一个
6. 情绪变化必须有依据，不能跳跃
7. 忠于原文：不得引入与已发生事件（时间线）矛盾的事件；新线索必须能与既有事实自洽，不得凭空捏造与原文无关的设定
8. 延续本作品的叙事组织方式——若原作单章常见多线并置/日常承载/离场人物近况自然回归，请保持这种组织；若原作单线紧凑，则保持其紧凑。不要因为续写而系统性改变作品的组织方式，也不要每章强行制造悬念钩子
9. scene_experience 可选：提供时须落在读者体验五维（看见/阻碍/选择/结果/认知变化），让正文展开有现场感；省略时不注入
9b. reader_handoffs 可选：本场景若有 1–3 个高价值认知交接点（读者应从证据中自己完成的关键推断），逐条声明。三层语义必须分离：evidence=正文将给的动作/对白/细节；reader_inference=希望读者自己得出的判断；explicitness=leave_implicit（默认，保持隐式）/explicit_when_condition（写明 explicit_when：什么情况下才允许显式，例如"只有人物意识到并因此改变行动时"）/must_explain（读者无法可靠推断：规则关键因果、角色不可见信息）。另须声明 evidence_sufficiency：sufficient=已计划足够可见证据；needs_more_evidence=想让读者推但还少一个必要前提（Prose 会先补证据再停）；must_explicit=信息无法合理推出必须明说。**粒度契约：每个 handoff 只能声明一个最小可独立完成的推断单位——若目标含两个可独立陈述、独立被证据支持、独立判真假的命题（如"A 而且 B"/"A 但 B"），必须拆成多个 handoff，不得合并声明**。不为每段都填表——只标真正值得交还给读者的关键 beat；没有合适的则省略整个字段
9c. diagnostic_choice 可选：本场景若有 1 个真正值得 dramatize 的取舍点，声明它。资格检查（不满足则省略整个字段，不硬造选择）：(a) 至少 2 个在人物当前知识/资源/规则下真实可行的选项；(b) 选项成本结构有有意义差异（不能只选 A 失去 X、选 B 什么都不失去）；(c) 决定权属于人物本人（非上级强迫/巧合替代/他人代决）。conditional_revelations 只能写条件性推断（"若选A会更支持'关系优先于收益'这一读者推断"），禁止写成人物事实（"此人物重感情"），不写进 CharacterModel
9d. dialogue_strategy 可选：本场景若有 1 场值得建模的社会博弈对话才声明（≤4 个稀疏 beat，只有策略位移才切）。资格检查（不满足则省略整个字段）：(a) 至少一方有需通过对话推进的目的；(b) 存在不能简单直说的社会/信息/利益约束；(c) 对方有真实 agency（可抵抗、还价、反制）；(d) 对话结果可能改变信息/承诺/杠杆/关系/行动空间。普通寒暄、交代地点、无争议确认、功能性短对白一律不建。interaction_objective 只能写条件性计划，不得写成人物事实
9e. detail_contract 可选：本场景若存在值得着墨的环境/空间/物品（新地点、行动舞台、关系场域、情绪载具）才声明（1-6 处承重细节）。资格检查（不满足则省略整个字段）：(a) 本场有环境着墨需求；(b) 细节差异实质影响读者定位、行动理解或氛围积累。纯对白场、普通过场（走廊/上车下车）不建。每处承重细节必须声明：functions（ORIENTATION/ACTION_CONSTRAINT/SENSORY/RELATIONAL/ATMOSPHERE 选1-2）+ realized_effect（该细节在当前句段要产生的具体读者效应——不得只复述功能标签；「用了颜色」≠完成感官功能）+ carrier（细节通过什么载体进入句段：挂在谁的动作/感知/判断/空间阻碍/关系变化上、改变了什么状态——不允许「物件被声明存在」式落地）。多个细节可共享 shared_cluster 共同兑现一个功能（如战斗前空间枚举共享定位+行动约束），但共享功能必须在当前行动/后文可兑现。已建立细节的再现必须新增状态/作用/意义，不得仅为证明其存在而重复出现
9f. expectation_intents 可选：本场景若对【读者预期台账】中的开放预期有明确的管理动作才声明（≤2 个，只动关键信息缺口）。资格检查（不满足则省略整个字段）：(a) 台账中存在本场景真正触及的开放预期，或本场确实建立一个新的关键信息缺口/结果空间；(b) 本场景会对读者可能性空间、预测或兑现状态产生真实变化——普通场景不造。intent 取值：OPEN=建立新预期 / NARROW=收窄可能性空间（呈现已有线索不解释指向）/ STRENGTHEN=强化当前预测方向 / WEAKEN=动摇当前预测 / FLIP=结果违反已建立的读者预测（须有证据基础，不得天降）/ RESOLVE=兑现关闭。answer_due_now=true 仅当当前因果链已经要求回答/行动（被当面问到、物证到场、deadline 到达、前置任务完成、承诺到兑现节点）——届时本场必须兑现，不得用停顿/打断/欲言又止推迟。intended_prediction 是隐藏作者意图（如想引导的误判方向），不会给正文写手；evidence_to_surface 只能引用已存在的事实/线索，不得凭空造新线索
9g. depiction_intents 可选：本场景若有值得刻意承载的体验质感（ambient quality：戒备中的敬畏/平静下的隐忧/亲昵下的酸涩/恭敬下的畏惧算计/夜色中的寂寥……希望读者【感受到】的调性，不是要读者【推断出】的命题——推断归 reader_handoffs），逐条声明（≤2 个）。资格检查（三条全满足才声明，否则省略整个字段）：(a) 该质感对本 beat 的读者体验重要——漏掉它场景只剩骨架；(b) 若用抽象命名兑现（「他很烦躁」）会损失体验价值；(c) 存在可观察载体空间（动作/神态/语气/器物/空间/节奏可承载它）。普通自陈/信息交代/每场景例行情绪不进。字段语义：target_quality=目标体验质感（experiential quality 词组，不是命题）；beat_link=责任绑定（硬字段——这个质感由哪个 beat/谁的哪段行动承载，写清「谁负责、在哪个 beat 负责」）；planned_carriers=可行的可观察载体候选（开放集合，正文可换用其他有效载体）；placement/rationale 可省略
10. hook_type 可选：若填，必须是当前层级的显式枚举（见【层级钩子类型】段；未提供该段时省略字段）——自由文本钩子走 hook 字段，hook_type 可留空
11. 借力不出面：若原作主角常借力布局、委托他人出面处理事务、居中调度留有余裕，请保持这种行动方式；不要让主角因续写而事事亲为、亲自上阵硬碰。若原作主角本就亲力亲为，则保持其亲力亲为

【输出格式】
严格输出 JSON:
{{
  "plotunit": {{
    "unit_id": "pu_xxx",
    "level": "scene",
    "goal": "本单元目标",
    "participants": ["角色ID"],
    "conflict": "核心冲突",
    "input_state_ref": "{state.state_id}",
    "output_state_ref": "新状态ID",
    "released_information": ["新释放给读者的信息"],
    "emotional_shift": "情绪变化",
    "hook": "钩子",
    "hook_type": "钩子类型（显式枚举，见【层级钩子类型】；可省略）",
    "formula_node": "当前结构节点名（如 climax）",
    "consequences": ["后果"],
    "is_effective": true,
    "scene_experience": {{
      "protagonist_sees": "主角看见了什么——本场景的感官焦点（具体画面，非概述）",
      "obstacles": ["遇到了什么阻碍（具体阻力）"],
      "choice_grounding": "为什么作出选择（身份/信念/压力依据，避免剧情需要式选择）",
      "outcome": "选择产生了什么结果（读者知道成/败/变的可见反馈）",
      "cognition_shift": "情绪和认知如何变化（从之前怎么想到现在怎么想）"
    }},
    "reader_handoffs": [
      {{
        "evidence": "正文将给出的动作/对白/细节",
        "reader_inference": "希望读者自己完成的判断",
        "explicitness": "leave_implicit",
        "evidence_sufficiency": "sufficient / needs_more_evidence / must_explicit",
        "explicit_when": "什么情况下才允许显式（可省略）",
        "payoff": "预期回报（可省略）"
      }}
    ],
    "diagnostic_choice": {{
      "pressure": "当前什么压力迫使人物不能什么都要",
      "alternatives": [
        {{"option": "真实可行选项A", "viability_basis": "为何在人物知识/资源/规则下可行", "cost": "选它失去什么"}},
        {{"option": "真实可行选项B", "viability_basis": "为何可行", "cost": "失去什么"}}
      ],
      "agency_basis": "为什么决定权属于人物本人",
      "conditional_revelations": [
        {{"if_option": "选项A", "preference_signal": "若选A会支持读者对人物偏好的哪种推断"}},
        {{"if_option": "选项B", "preference_signal": "若选B支持哪种推断"}}
      ]
    }},
    "dialogue_strategy": {{
      "participants": ["对话方A", "对话方B"],
      "interaction_objective": "这场对白真正想改变什么（关系/信息/承诺/行动层面）",
      "social_constraint": "为什么不能直说（体面/立场/信息优势/风险）",
      "information_asymmetry": "谁知道什么、谁不知道什么、什么不能明说",
      "stakes": "策略失败当场损失什么",
      "beats": [
        {{"actor": "行动方", "tactical_move": "PROBE/EVADE/PRESS/BARGAIN/COMMIT/REFUSE/REDIRECT/WITHHOLD",
          "target_delta": "INFORMATION/COMMITMENT/LEVERAGE/FACE_OR_STATUS/ACTION_SPACE",
          "pressure_basis": "为什么这一步能产生压力", "success_signal": "对方什么反应算奏效",
          "response_to": "第2个beat起填：回应哪个前序局面"}}
      ]
    }},
    "detail_contract": {{
      "reader_task": "本场景当前读者任务：读者此刻需要建立/追踪/感受什么",
      "load_bearing_details": [
        {{"detail": "计划写的细节内容",
          "functions": ["ORIENTATION/ACTION_CONSTRAINT/SENSORY/RELATIONAL/ATMOSPHERE 选1-2"],
          "realized_effect": "读了它读者获得什么定位/判断/感受",
          "carrier": "细节挂在什么动作/感知/判断/阻碍上、改变了什么状态",
          "shared_cluster": "共享功能簇id（可省略）"}}
      ],
      "detail_budget": 5
    }},
    "expectation_intents": [
      {{
        "expectation_id": "目标预期id（台账中的 id；OPEN 新预期时给新 id）",
        "reader_question": "该预期的读者视角问题",
        "intent": "OPEN/NARROW/STRENGTHEN/WEAKEN/FLIP/RESOLVE",
        "intended_prediction": "隐藏作者意图：希望读者形成的预测（可省略）",
        "evidence_to_surface": ["计划呈现给读者的已有证据/线索"],
        "answer_due_now": false
      }}
    ],
    "depiction_intents": [
      {{
        "target_quality": "目标体验质感（如：戒备中的敬畏）",
        "beat_link": "责任绑定：该质感由哪个 beat/谁的哪段行动承载",
        "planned_carriers": ["可行的可观察载体候选（开放集合）"],
        "placement": "单元内位置（可省略）",
        "rationale": "为何此刻需要这个质感（可省略）"
      }}
    ]
  }},
  "new_state": {{
    "state_id": "新状态ID",
    "current_time": "新时间",
    "current_location": "新地点",
    "active_characters": ["角色ID"],
    "current_situation": "新局势",
    "active_conflicts": ["新冲突"],
    "public_information": ["单元结束后故事局势中多人共享的信息"],
    "hidden_information": ["单元结束后读者仍不知道的信息"],
    "private_information_map": {{"仅部分角色知晓的信息": ["知情角色ID"]}}
  }},
  "new_facts": [
    {{
      "fact_id": "f_xxx",
      "statement": "新确认事实",
      "fact_type": "event",
      "involved_entities": [],
      "confirmed": true
    }}
  ],
  "confidence_gaps": ["不确定的信息"]
}}

注意：
- new_facts 只写入已确认的 hard facts，不确定的放入 confidence_gaps
- new_facts 的 fact_id 必须全局唯一，不得与既有 FactLedger 中已有
  fact_id 重复（建议按既有最大编号递增，如 f11、f12）
- plotunit.unit_id 必须唯一，不得与既有 PlotUnit 的 unit_id 重复
  （建议递增编号，如 pu_004）{occupied_ids_note}
- 角色关系变化如果是长期结论，更新 CharacterModel.relations
- 但 CharacterModel 字段只存压缩结论，支撑证据不要写入
"""
