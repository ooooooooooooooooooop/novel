"""ReviewUnit extended hard rule coverage."""


def test_review_detects_invalid_state_ref():
    """PlotUnit 指向不存在的 state_id 应被检测."""
    from src.object_state import NarrativeState, PlotUnit
    from src.workflow_action.review import ReviewUnit

    state = NarrativeState(
        state_id="ns_real",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    pu = PlotUnit(
        unit_id="pu_bad",
        level="scene",
        goal="测试",
        conflict="测试",
        input_state_ref="ns_real",
        output_state_ref="ns_nonexistent",
    )

    review = ReviewUnit()
    issues = review._hard_rules([state, pu])
    bad_refs = [i for i in issues if i.issue_id == "iss_hard_state_ref_pu_bad"]
    assert len(bad_refs) == 1
    assert bad_refs[0].issue_type == "weak_progression"
    assert bad_refs[0].severity == "blocking"
    assert "ns_nonexistent" in bad_refs[0].description


def test_review_passes_valid_state_ref():
    """PlotUnit 指向存在的 state_id 不应触发问题."""
    from src.object_state import NarrativeState, PlotUnit
    from src.workflow_action.review import ReviewUnit

    state = NarrativeState(
        state_id="ns_valid",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    pu = PlotUnit(
        unit_id="pu_good",
        level="scene",
        goal="测试",
        conflict="测试",
        input_state_ref="ns_valid",
        output_state_ref="ns_valid",
    )

    review = ReviewUnit()
    issues = review._hard_rules([state, pu])
    bad_refs = [i for i in issues if "state_ref" in i.issue_id]
    assert len(bad_refs) == 0


def test_review_detects_orphan_foreshadow():
    """active 但没有 PlotUnit 引用的伏笔应被检测."""
    from src.object_state import ForeshadowEntry, ForeshadowGraph, PlotUnit
    from src.workflow_action.review import ReviewUnit

    fg = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="t1",
                setup_point="第1章",
                content="神秘令牌",
                visibility_level="explicit",
                expected_payoff="揭示身份",
                current_status="active",
                linked_plotunits=[],
            )
        ]
    )
    pu = PlotUnit(
        unit_id="pu_001",
        level="scene",
        goal="其他事",
        conflict="其他冲突",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
    )

    review = ReviewUnit()
    issues = review._hard_rules([fg, pu])
    orphan = [i for i in issues if i.issue_id == "iss_hard_foreshadow_t1"]
    assert len(orphan) == 1
    assert orphan[0].issue_type == "promise_loss"
    assert orphan[0].severity == "warning"


def test_review_passes_linked_foreshadow():
    """有 PlotUnit 引用的 active 伏笔不应触发问题."""
    from src.object_state import ForeshadowEntry, ForeshadowGraph, PlotUnit
    from src.workflow_action.review import ReviewUnit

    fg = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="t2",
                setup_point="第1章",
                content="神秘令牌",
                visibility_level="explicit",
                expected_payoff="揭示身份",
                current_status="active",
                linked_plotunits=["pu_002"],
            )
        ]
    )
    pu = PlotUnit(
        unit_id="pu_002",
        level="scene",
        goal="回收伏笔",
        conflict="揭示真相",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
    )

    review = ReviewUnit()
    issues = review._hard_rules([fg, pu])
    orphan = [i for i in issues if "foreshadow" in i.issue_id]
    assert len(orphan) == 0


def test_review_detects_time_order_conflict():
    """同一实体在同一时间点有多条 time_order 事实应被检测."""
    from src.object_state import FactEntry, FactLedger
    from src.workflow_action.review import ReviewUnit

    fl = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="主角到达山门",
                fact_type="time_order",
                involved_entities=["c001"],
                timestamp="子时",
            ),
            FactEntry(
                fact_id="f2",
                statement="主角离开宗门",
                fact_type="time_order",
                involved_entities=["c001"],
                timestamp="子时",
            ),
        ]
    )

    review = ReviewUnit()
    issues = review._hard_rules([fl])
    time_issues = [i for i in issues if "time_" in i.issue_id]
    assert len(time_issues) == 1
    assert time_issues[0].issue_type == "fact_conflict"
    assert time_issues[0].severity == "warning"
    assert "子时" in time_issues[0].description


def test_review_blocks_ineffective_plotunit():
    """PlotUnit 未确认有效推进时应阻断."""
    from src.object_state import PlotUnit
    from src.workflow_action.review import ReviewUnit

    pu = PlotUnit(
        unit_id="pu_ineffective",
        level="scene",
        goal="原地讨论",
        conflict="没有实际阻力",
        input_state_ref="ns_1",
        output_state_ref="ns_1",
        is_effective=False,
    )

    issues = ReviewUnit()._hard_rules([pu])
    ineffective = [i for i in issues if i.issue_id == "iss_hard_ineffective_pu_ineffective"]
    assert len(ineffective) == 1
    assert ineffective[0].issue_type == "weak_progression"
    assert ineffective[0].severity == "blocking"


# --- v3: 决策依据可回溯性（iss_agency_*）与描写分层（iss_layering_*）---


def test_agency_rule_flags_unjustified_decision():
    """PlotUnit 含决策动作但无显式依据标记 + 有 CharacterModel → iss_agency 弱信号."""
    from src.object_state import CharacterModel, PlotUnit
    from src.workflow_action.review import ReviewUnit

    char = CharacterModel(
        character_id="c1",
        name="顾临",
        identity="被逐出宗门的弟子",
        outer_goal="为师父报仇",
        inner_need="被认可",
        fear="再次被抛弃",
        flaw="过度自我牺牲",
        strength="意志坚定",
        stance="敌对",
    )
    pu = PlotUnit(
        unit_id="pu_agency",
        level="scene",
        goal="顾临决定背叛宗门",
        conflict="他答应交出师父的遗物",
        input_state_ref="ns",
        output_state_ref="ns",
    )

    issues = ReviewUnit()._domain_rules([char, pu])
    agency = [i for i in issues if i.issue_id.startswith("iss_agency_")]
    assert len(agency) == 1
    assert agency[0].issue_type == "weak_progression"
    assert "依据" in agency[0].description


def test_agency_rule_skips_when_explicit_grounding():
    """含显式依据标记（不得不/作为/为保全）→ 不报 iss_agency."""
    from src.object_state import CharacterModel, PlotUnit
    from src.workflow_action.review import ReviewUnit

    char = CharacterModel(
        character_id="c1",
        name="顾临",
        identity="城主",
        outer_goal="守住城门",
        inner_need="守护家人",
        fear="城破",
        flaw="心软",
        strength="威望",
        stance="中立",
    )
    pu = PlotUnit(
        unit_id="pu_ok",
        level="scene",
        goal="作为城主，他不得不答应献城",
        conflict="为保全百姓，他选择了背叛",
        input_state_ref="ns",
        output_state_ref="ns",
    )

    issues = ReviewUnit()._domain_rules([char, pu])
    agency = [i for i in issues if i.issue_id.startswith("iss_agency_")]
    assert agency == []


def test_agency_rule_skips_without_character_model():
    """无 CharacterModel（如只审查 PlotUnit）→ 不跑 agency 检查."""
    from src.object_state import PlotUnit
    from src.workflow_action.review import ReviewUnit

    pu = PlotUnit(
        unit_id="pu_nochar",
        level="scene",
        goal="他决定离开",
        conflict="他答应留下",
        input_state_ref="ns",
        output_state_ref="ns",
    )
    issues = ReviewUnit()._domain_rules([pu])
    assert not any(i.issue_id.startswith("iss_agency_") for i in issues)


def test_agency_rule_skips_non_decision_plotunit():
    """无决策动作触发词（描述型 goal/conflict）→ 不报 iss_agency."""
    from src.object_state import CharacterModel, PlotUnit
    from src.workflow_action.review import ReviewUnit

    char = CharacterModel(
        character_id="c1",
        name="顾临",
        identity="弟子",
        outer_goal="练成剑法",
        inner_need="复仇",
        fear="失败",
        flaw="急躁",
        strength="天赋",
        stance="中立",
    )
    pu = PlotUnit(
        unit_id="pu_desc",
        level="scene",
        goal="练成第七重剑法",
        conflict="内力不足，剑招始终无法贯通",
        input_state_ref="ns",
        output_state_ref="ns",
    )
    issues = ReviewUnit()._domain_rules([char, pu])
    assert not any(i.issue_id.startswith("iss_agency_") for i in issues)


def test_layering_rule_flags_explanatory_announcement():
    """PlotUnit 字段含解释腔/情绪宣布词 → iss_layering 弱信号（low 非阻断）."""
    from src.object_state import PlotUnit
    from src.workflow_action.review import ReviewUnit

    pu = PlotUnit(
        unit_id="pu_lay",
        level="scene",
        goal="他忽然明白",
        conflict="她心中涌起一股怒火",
        emotional_shift="他感到恐惧",
        input_state_ref="ns",
        output_state_ref="ns",
    )
    issues = ReviewUnit()._domain_rules([pu])
    layering = [i for i in issues if i.issue_id.startswith("iss_layering_")]
    assert len(layering) == 1
    assert layering[0].severity == "low"
    assert not layering[0].is_blocking()


def test_layering_rule_clean():
    """无直给标记 → 不报 iss_layering."""
    from src.object_state import PlotUnit
    from src.workflow_action.review import ReviewUnit

    pu = PlotUnit(
        unit_id="pu_clean",
        level="scene",
        goal="追回失物",
        conflict="师父已死，遗物在仇人手中",
        emotional_shift="决意复仇",
        input_state_ref="ns",
        output_state_ref="ns",
    )
    issues = ReviewUnit()._domain_rules([pu])
    assert not any(i.issue_id.startswith("iss_layering_") for i in issues)


def test_foreshadow_set_status_valid_and_invalid():
    """set_status 支持合法状态，拒绝非法状态/未知 id（静默）."""
    from src.object_state import ForeshadowGraph, ForeshadowEntry

    fg = ForeshadowGraph(entries=[
        ForeshadowEntry(thread_id="th_001", content="伏笔一", setup_point="第1章", visibility_level="explicit", expected_payoff="回收"),
    ])
    assert fg.set_status("th_001", "resolved") is True
    assert fg.get_active() == []  # 不再 active
    assert fg.set_status("th_001", "bogus") is False  # 非法状态
    assert fg.set_status("th_nope", "resolved") is False  # 未知 id


def test_review_parse_response_applies_foreshadow_updates():
    """review 声明 resolved 的线程就地更新——消除 promise_loss 重复误报."""
    from src.object_state import ForeshadowGraph, ForeshadowEntry
    from src.workflow_action.review import ReviewUnit

    fg = ForeshadowGraph(entries=[
        ForeshadowEntry(thread_id="th_002", content="伏笔二", setup_point="第1章", visibility_level="explicit", expected_payoff="回收"),
    ])
    resp = (
        '{"issues": [], "reminders": [], "route": "pass",'
        ' "foreshadow_updates": [{"thread_id": "th_002", "status": "resolved",'
        ' "note": "正文已兑现"}]}'
    )
    issues, reminders, route = ReviewUnit().parse_response(resp, foreshadows=[fg])
    assert route == "pass"
    assert fg.get_active() == []  # th_002 已从活跃承诺移除


def test_review_parse_response_rejects_unknown_field_still():
    """未知字段仍被拒绝（foreshadow_updates 是新允许的可选字段）."""
    from src.workflow_action.review import ReviewUnit

    with _raises_valueerror("unexpected field"):
        ReviewUnit().parse_response(
            '{"issues": [], "reminders": [], "route": "pass", "bogus": 1}'
        )


def _raises_valueerror(substr):
    import pytest
    return pytest.raises(ValueError, match=substr)


def test_character_reconcile_knowledge_adds_and_drops():
    """reconcile_knowledge：learn 追加去重，drop_unknown 移除断言未知."""
    from src.object_state import CharacterModel

    cm = CharacterModel(
        character_id="c1", name="测试", identity="身份", outer_goal="目标",
        inner_need="需求", fear="恐惧", flaw="缺陷", strength="优势", stance="中立",
        knowledge_state=["知道甲", "不知道乙的来历"],
    )
    changed = cm.reconcile_knowledge(
        learn=["苏观使找了十二年", "苏观使找了十二年"],  # 重复只加一次
        drop_unknown=["不知道乙的来历"],
    )
    assert "苏观使找了十二年" in cm.knowledge_state
    assert "不知道乙的来历" not in cm.knowledge_state
    assert "知道甲" in cm.knowledge_state
    assert cm.knowledge_state.count("苏观使找了十二年") == 1
    assert len(changed) == 2  # +1 追加, -1 移除


def test_review_parse_response_applies_knowledge_updates():
    """review 声明角色新得知的信息——移除过期『不知道X』断言."""
    from src.object_state import CharacterModel
    from src.workflow_action.review import ReviewUnit

    cm = CharacterModel(
        character_id="c001", name="林烬", identity="抄碑人", outer_goal="生存",
        inner_need="被认可", fear="暴露", flaw="执念", strength="谨慎", stance="中立",
        knowledge_state=["不知道苏观使找了十二年", "不知道墨痕的来历与后果"],
    )
    resp = (
        '{"issues": [], "reminders": [], "route": "pass",'
        ' "character_knowledge_updates": [{"character_id": "c001",'
        ' "learn": ["苏观使找了十二年"],'
        ' "drop_unknown": ["不知道苏观使找了十二年"]}]}'
    )
    ReviewUnit().parse_response(resp, character_models=[cm])
    assert "苏观使找了十二年" in cm.knowledge_state
    assert "不知道苏观使找了十二年" not in cm.knowledge_state
    # 未声明的不动（墨痕来历仍未知——亲历≠知来历，正确保留）
    assert "不知道墨痕的来历与后果" in cm.knowledge_state


def test_review_parse_response_knowledge_unknown_id_skipped():
    """character_knowledge_updates 指向未知角色 id 时静默跳过."""
    from src.object_state import CharacterModel
    from src.workflow_action.review import ReviewUnit

    cm = CharacterModel(character_id="c001", name="林烬", identity="抄碑人", outer_goal="生存",
        inner_need="被认可", fear="暴露", flaw="执念", strength="谨慎", stance="中立",
        knowledge_state=["不知道X"])
    resp = (
        '{"issues": [], "reminders": [], "route": "pass",'
        ' "character_knowledge_updates": [{"character_id": "c999",'
        ' "learn": ["Y"], "drop_unknown": ["不知道X"]}]}'
    )
    ReviewUnit().parse_response(resp, character_models=[cm])
    assert cm.knowledge_state == ["不知道X"]  # 未受影响
