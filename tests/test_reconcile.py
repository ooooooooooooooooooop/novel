"""测试 ReconcileUnit."""

from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    WorkSpec,
    WorldModel,
)
from src.workflow_action.reconcile import ReconcileUnit


def test_cross_chapter_character_overlap_detected():
    from src.object_state import CharacterModel, ReviewIssue
    from src.workflow_action.reconcile import ReconcileUnit

    char = CharacterModel(
        character_id="c001",
        name="A",
        identity="身份",
        outer_goal="目标",
        inner_need="需求",
        fear="恐惧",
        flaw="缺陷",
        strength="优势",
        stance="立场",
        knowledge_state=["秘密X"],
        misinformation=["秘密X"],
        relations={},
    )

    unit = ReconcileUnit()
    issues = unit.check_cross_chapter_consistency([char])

    assert len(issues) == 1
    assert isinstance(issues[0], ReviewIssue)
    assert issues[0].issue_type == "character_distortion"
    assert "秘密X" in issues[0].description


def test_cross_chapter_foreshadow_orphan():
    from src.object_state import ForeshadowEntry, ForeshadowGraph, ReviewIssue
    from src.workflow_action.reconcile import ReconcileUnit

    graph = ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id="th1",
                setup_point="第一章",
                content="宝藏",
                visibility_level="explicit",
                expected_payoff="找到宝藏",
                current_status="active",
            )
        ]
    )

    unit = ReconcileUnit()
    issues = unit.check_cross_chapter_consistency([graph])

    assert len(issues) == 1
    assert isinstance(issues[0], ReviewIssue)
    assert issues[0].issue_type == "promise_loss"


def test_reconcile_characters_merges_knowledge_and_relations():
    ch1_char = CharacterModel(
        character_id="c001",
        name="A",
        identity="身份",
        outer_goal="目标",
        inner_need="需求",
        fear="恐惧",
        flaw="缺陷",
        strength="优势",
        stance="立场",
        knowledge_state=["知道1"],
        misinformation=[],
        relations={},
    )
    ch2_char = CharacterModel(
        character_id="c001",
        name="A",
        identity="身份",
        outer_goal="目标",
        inner_need="需求",
        fear="恐惧",
        flaw="缺陷",
        strength="优势",
        stance="立场",
        knowledge_state=["知道2"],
        misinformation=["误解1"],
        relations={"c002": "朋友"},
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_char], [ch2_char]])

    chars = [o for o in merged if isinstance(o, CharacterModel)]
    assert len(chars) == 1
    assert "知道1" in chars[0].knowledge_state
    assert "知道2" in chars[0].knowledge_state
    assert "误解1" in chars[0].misinformation
    assert chars[0].relations["c002"] == "朋友"


def test_reconcile_reports_character_name_mismatch_for_same_id():
    ch1_char = CharacterModel(
        character_id="c001",
        name="Alice",
        identity="detective",
        outer_goal="solve case",
        inner_need="trust partner",
        fear="failure",
        flaw="isolated",
        strength="observant",
        stance="cooperative",
    )
    ch2_char = CharacterModel(
        character_id="c001",
        name="Bob",
        identity="detective",
        outer_goal="solve case",
        inner_need="trust partner",
        fear="failure",
        flaw="isolated",
        strength="observant",
        stance="cooperative",
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_char], [ch2_char]])

    assert any("character name mismatch" in issue for issue in issues)
    chars = [o for o in merged if isinstance(o, CharacterModel)]
    assert chars[0].name == "Alice"


def test_reconcile_fact_ledger_dedup_by_statement():
    ch1_fl = FactLedger(
        entries=[
            FactEntry(fact_id="f1", statement="事实A", fact_type="event"),
        ]
    )
    ch2_fl = FactLedger(
        entries=[
            FactEntry(fact_id="f2", statement="事实A", fact_type="event"),
            FactEntry(fact_id="f3", statement="事实B", fact_type="rule"),
        ]
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_fl], [ch2_fl]])

    ledgers = [o for o in merged if isinstance(o, FactLedger)]
    assert len(ledgers) == 1
    assert len(ledgers[0].entries) == 2


def test_reconcile_takes_last_narrative_state():
    ch1_ns = NarrativeState(
        state_id="ns1",
        current_time="早晨",
        current_location="家",
        current_situation="起床",
    )
    ch2_ns = NarrativeState(
        state_id="ns2",
        current_time="夜晚",
        current_location="公司",
        current_situation="加班",
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_ns], [ch2_ns]])

    states = [o for o in merged if isinstance(o, NarrativeState)]
    assert len(states) == 1
    assert states[0].current_time == "夜晚"


def test_reconcile_detects_genre_mismatch():
    ch1_ws = WorkSpec(
        genre="仙侠", audience="青年", theme="成长", tone="克制", pacing="前快中稳后爆"
    )
    ch2_ws = WorkSpec(
        genre="科幻", audience="青年", theme="成长", tone="克制", pacing="前快中稳后爆"
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_ws], [ch2_ws]])

    assert any("genre mismatch" in i for i in issues)
    wss = [o for o in merged if isinstance(o, WorkSpec)]
    assert wss[0].genre == "仙侠"


def test_reconcile_detects_core_workspec_field_mismatches():
    ch1_ws = WorkSpec(
        genre="fantasy",
        audience="adult",
        theme="growth",
        tone="quiet",
        pacing="steady",
    )
    ch2_ws = WorkSpec(
        genre="fantasy",
        audience="young adult",
        theme="revenge",
        tone="dark",
        pacing="fast",
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_ws], [ch2_ws]])

    assert any("audience mismatch" in issue for issue in issues)
    assert any("theme mismatch" in issue for issue in issues)
    assert any("tone mismatch" in issue for issue in issues)
    assert any("pacing mismatch" in issue for issue in issues)
    wss = [o for o in merged if isinstance(o, WorkSpec)]
    assert wss[0].theme == "growth"


def test_reconcile_merges_worldmodel_factions_and_reports_scalar_conflicts():
    ch1_world = WorldModel(
        world_facts=["fact one"],
        social_structure="empire",
        power_system="magic",
        resource_system="mana",
        geography="north",
        factions=["guild"],
    )
    ch2_world = WorldModel(
        world_facts=["fact two"],
        social_structure="republic",
        power_system="technology",
        resource_system="credits",
        geography="south",
        factions=["council"],
    )

    unit = ReconcileUnit()
    merged, issues = unit.reconcile([[ch1_world], [ch2_world]])

    assert any("social_structure mismatch" in issue for issue in issues)
    assert any("power_system mismatch" in issue for issue in issues)
    assert any("resource_system mismatch" in issue for issue in issues)
    assert any("geography mismatch" in issue for issue in issues)
    worlds = [o for o in merged if isinstance(o, WorldModel)]
    assert set(worlds[0].factions) == {"guild", "council"}


def test_reconcile_extend_scenario():
    """验证 ReconcileUnit 能处理 extend 类型的多批次对象."""
    from src.object_state import (
        CharacterModel,
        FactLedger,
        ForeshadowGraph,
        NarrativeState,
        WorkSpec,
    )
    from src.workflow_action.reconcile import ReconcileUnit

    batch1 = [
        WorkSpec(
            genre="仙侠",
            audience="青年",
            theme="成长",
            tone="克制",
            pacing="前快中稳后爆",
        ),
        NarrativeState(
            state_id="ns_1",
            current_time="第一章",
            current_location="宗门",
            current_situation="入门",
        ),
        CharacterModel(
            character_id="c001",
            name="主角",
            identity="弟子",
            outer_goal="修炼",
            inner_need="认可",
            fear="失败",
            flaw="急躁",
            strength="天赋",
            stance="中立",
        ),
        FactLedger(),
        ForeshadowGraph(),
    ]
    batch2 = [
        WorkSpec(
            genre="仙侠",
            audience="青年",
            theme="成长",
            tone="克制",
            pacing="前快中稳后爆",
        ),
        NarrativeState(
            state_id="ns_2",
            current_time="第三章",
            current_location="秘境",
            current_situation="探险",
        ),
        CharacterModel(
            character_id="c001",
            name="主角",
            identity="弟子",
            outer_goal="突破",
            inner_need="力量",
            fear="死亡",
            flaw="急躁",
            strength="天赋",
            stance="敌对",
        ),
        FactLedger(),
        ForeshadowGraph(),
    ]

    reconciler = ReconcileUnit()
    objects, issues = reconciler.reconcile([batch1, batch2])

    workspecs = [o for o in objects if isinstance(o, WorkSpec)]
    assert len(workspecs) == 1

    states = [o for o in objects if isinstance(o, NarrativeState)]
    assert len(states) == 1
    assert states[0].current_time == "第三章"

    chars = [o for o in objects if isinstance(o, CharacterModel)]
    assert len(chars) == 1
    assert chars[0].outer_goal == "突破"


def test_reconcile_fact_negation_contradiction_detected():
    """跨章事实中一条否定另一条时检出 fact_conflict."""
    from src.workflow_action.reconcile import ReconcileUnit

    ledger = FactLedger(
        entries=[
            FactEntry(fact_id="f1", statement="主角在长安", fact_type="event"),
            FactEntry(fact_id="f2", statement="主角不在长安", fact_type="event"),
        ]
    )

    unit = ReconcileUnit()
    issues = unit.check_cross_chapter_consistency([ledger])

    assert len(issues) == 1
    assert issues[0].issue_type == "fact_conflict"
    assert "主角在长安" in issues[0].description
    assert "主角不在长安" in issues[0].description


def test_reconcile_fact_negation_severity_is_warning():
    """否定矛盾是启发式提示，必须为 warning（不阻断 Reconcile）。"""
    from src.workflow_action.reconcile import ReconcileUnit

    ledger = FactLedger(
        entries=[
            FactEntry(fact_id="f1", statement="他不认识她", fact_type="event"),
            FactEntry(fact_id="f2", statement="他认识她", fact_type="event"),
        ]
    )

    unit = ReconcileUnit()
    issues = unit.check_cross_chapter_consistency([ledger])

    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_reconcile_fact_similar_statements_not_flagged():
    """相近但不构成否定的陈述不应误报矛盾。"""
    from src.workflow_action.reconcile import ReconcileUnit

    ledger = FactLedger(
        entries=[
            FactEntry(fact_id="f1", statement="主角在长安", fact_type="event"),
            FactEntry(fact_id="f2", statement="主角在洛阳", fact_type="event"),
            FactEntry(fact_id="f3", statement="主角在长安", fact_type="event"),
        ]
    )

    unit = ReconcileUnit()
    issues = unit.check_cross_chapter_consistency([ledger])

    # f1 与 f3 完全相同：非矛盾（且 dedup 后同串不重复计）
    assert all(i.issue_type != "fact_conflict" for i in issues)
