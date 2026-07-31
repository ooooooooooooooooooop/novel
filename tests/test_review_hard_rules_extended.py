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
