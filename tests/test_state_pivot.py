"""StateModel 运行机制测试：Pivot + 后台推进."""
from src.object_state.statemodel import (
    CompressionLevel,
    NarrativeOpportunity,
    OffScreenProcess,
    Provenance,
    StateModel,
    ThreadState,
)
from src.workflow_action.state_pivot import (
    archive_thread,
    check_offscreen_opportunities,
    escalate_thread,
    merge_threads,
    propose_background_evolution,
    reenter_thread,
    suspend_thread,
)


def _sm_with_threads():
    return StateModel(
        threads=[
            ThreadState(thread_id="t1", thread_type="商业线", label="恒通", current_state="谈判中"),
            ThreadState(thread_id="t2", thread_type="官场线", label="陆平", current_state="观望"),
        ],
        last_chapter=40,
    )


def test_suspend_reenter_archive():
    sm = _sm_with_threads()
    suspend_thread(sm, "t1")
    assert sm.threads[0].compression == CompressionLevel.WARM  # 挂起不杀死
    reenter_thread(sm, "t1")
    assert sm.threads[0].compression == CompressionLevel.ACTIVE  # 重入
    archive_thread(sm, "t1")
    assert sm.threads[0].compression == CompressionLevel.ARCHIVED  # 归档仍保留


def test_merge_threads():
    sm = _sm_with_threads()
    merge_threads(sm, "t1", "t2")
    assert len(sm.threads) == 1  # 合流后只剩主线程
    assert "陆平" in sm.threads[0].current_state  # 汇入说明


def test_escalate():
    sm = _sm_with_threads()
    escalate_thread(sm, "t1")
    assert sm.threads[0].near_payoff is True  # 升级到接近兑现


def test_background_evolution_simulated():
    off = OffScreenProcess(entity="韩东", last_seen_chapter=10)
    propose_background_evolution(
        off, elapsed_chapters=25, intents=["寻找资金"], resources=["商铺"]
    )
    assert off.provenance == Provenance.SIMULATED  # 关键：后台推演默认不升级为 CANON
    assert "寻找资金" in off.next_most_likely
    assert off.events_since  # 记录了模拟事件


def test_background_evolution_long_elapsed():
    off = OffScreenProcess(entity="某同学", last_seen_chapter=1)
    propose_background_evolution(off, elapsed_chapters=50, intents=["毕业就业"], resources=[])
    assert "性格/处境已有可见变化" in off.background_state  # 离场50章必有变化


def test_offscreen_opportunity_after_threshold():
    sm = StateModel(
        offscreen=[OffScreenProcess(entity="校园线", last_seen_chapter=5)],
        last_chapter=45,  # 欠 40 章
    )
    check_offscreen_opportunities(sm, offscreen_threshold=20)
    assert sm.narrative_opportunities
    opp = sm.narrative_opportunities[0]
    assert opp.opp_type == "人物重入"
    assert opp.priority >= 7  # 欠得越久优先级越高（40章 → 3+8=11→10）


def test_offscreen_no_opportunity_when_recent():
    sm = StateModel(
        offscreen=[OffScreenProcess(entity="配角", last_seen_chapter=38)],
        last_chapter=40,  # 只欠 2 章
    )
    check_offscreen_opportunities(sm, offscreen_threshold=20)
    assert not sm.narrative_opportunities  # 未超阈值不制造机会
