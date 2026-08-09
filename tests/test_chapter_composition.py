"""Chapter Composition 测试：章节组合接口（替代 Plot Task）."""
from src.object_state.statemodel import (
    CompressionLevel,
    NarrativeOpportunity,
    OffScreenProcess,
    Provenance,
    StateModel,
    StrategicPosition,
    ThreadState,
)
from src.workflow_action.chapter_composition import (
    ChapterComposition,
    build_chapter_composition,
)


def test_empty_zero_cost():
    comp = build_chapter_composition(StateModel())
    assert comp.is_empty()
    assert comp.render() == ""


def test_primary_thread_selected():
    sm = StateModel(
        threads=[
            ThreadState(thread_id="t1", thread_type="商业线", label="恒通", current_state="谈判中"),
            ThreadState(
                thread_id="t2", thread_type="官场线", label="陆平", current_state="观望",
                can_background=True, needs_protagonist=False, recent_change="正谋求外调",
            ),
        ]
    )
    comp = build_chapter_composition(sm)
    assert comp.primary_thread == "恒通"  # 需要主角的 ACTIVE 线程作主线
    assert "陆平" in comp.background_progress[0]  # 可后台线程只在场感提示


def test_reentry_and_payoff():
    sm = StateModel(
        threads=[
            ThreadState(thread_id="t1", thread_type="商业线", label="恒通", near_payoff=True),
            ThreadState(thread_id="t2", thread_type="家庭线", label="许家"),
        ],
        strategic=[
            StrategicPosition(
                entity="周正", waiting_for=["商业地皮批复"], pending_payoffs=["产业链整合"],
                triggers=["批复下达"],
            )
        ],
    )
    comp = build_chapter_composition(sm)
    assert any("恒通" in r and "兑现" in r for r in comp.reentries)
    assert any("周正" in s and "产业链整合" in s for s in comp.strategic_items)
    assert any("批复下达" in s for s in comp.strategic_items)


def test_opportunities_included():
    sm = StateModel(
        narrative_opportunities=[
            NarrativeOpportunity(opp_type="人物重入", description="校园线 20 章未回归", priority=8),
            NarrativeOpportunity(opp_type="生活回归", description="很久无日常", priority=6),
        ]
    )
    comp = build_chapter_composition(sm)
    assert "校园线 20 章未回归" in comp.opportunities
    assert "很久无日常" in comp.opportunities


def test_render_has_section():
    comp = ChapterComposition(primary_thread="恒通", opportunities=["校园线重入"])
    sec = comp.render()
    assert "【本章组合建议】" in sec
    assert "恒通" in sec
    assert "校园线重入" in sec
