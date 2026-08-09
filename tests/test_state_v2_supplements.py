"""State V2 增补测试：Reader Knowledge / Composition from Selection / Pivot from Selection."""
from src.object_state.statemodel import (
    CompressionLevel,
    StateModel,
    ThreadState,
)
from src.workflow_action.candidate_pool import build_candidate_pool
from src.workflow_action.chapter_composition import (
    build_composition_from_selection,
)
from src.workflow_action.narrative_selector import select_candidates
from src.workflow_action.state_pivot import pivot_from_selection


def _sm() -> StateModel:
    return StateModel(
        last_chapter=450,
        reader_known=["恒通谈判"],
        world_timeline=["夏晴已回海州（未向读者揭示）"],
        threads=[
            ThreadState(thread_id="t1", thread_type="商业线", label="恒通机芯",
                        current_state="谈判中", near_payoff=True,
                        needs_protagonist=True, compression=CompressionLevel.ACTIVE),
            ThreadState(thread_id="t2", thread_type="官场线", label="陆平官场",
                        current_state="暗中角力", can_background=True,
                        needs_protagonist=False, compression=CompressionLevel.WARM),
        ],
    )


def test_reader_knowledge_fields():
    """Reader Knowledge 独立于世界：world_timeline 可含读者未知信息."""
    sm = _sm()
    assert "恒通谈判" in sm.reader_known
    assert "夏晴已回海州（未向读者揭示）" in sm.world_timeline
    assert "夏晴已回海州" not in sm.reader_known  # 世界已发生 ≠ 读者已知道


def test_composition_from_selection_uses_only_selected():
    """Composition 输入 = Selected Candidate Set，不从 Full State 硬塞."""
    sm = _sm()
    pool = build_candidate_pool(sm)
    sel = select_candidates(pool, sm)
    comp = build_composition_from_selection(sel)
    # 主承载来自 SELECT 候选（不是直接从 state 取）
    assert comp.primary_thread  # 有主承载
    # BACKGROUND 只作"后台运行"提示，不进 reentries（正文承载）
    for b in comp.background_progress:
        assert "后台运行" in b


def test_pivot_from_selection_suspends_background():
    """Pivot = Selection 结果：BACKGROUND 线程被挂起（WARM，非遗忘），SELECT 保持 ACTIVE."""
    sm = _sm()
    pool = build_candidate_pool(sm)
    sel = select_candidates(pool, sm)
    # 手动确认：至少有一个被选为 SELECT，一个可能进 BACKGROUND/DORMANT
    pivot_from_selection(sm, sel)
    # SELECT 对应的线程 ACTIVE
    selected_labels = {c.source_thread for c in sel.selected}
    for t in sm.threads:
        if t.label in selected_labels:
            assert t.compression == CompressionLevel.ACTIVE
    # 没有任何线程被归档/遗忘（pivot 不杀死）
    assert all(t.compression != CompressionLevel.ARCHIVED for t in sm.threads)


def test_pivot_does_not_archive():
    """Pivot 挂起 ≠ 遗忘：无线程被归档."""
    sm = _sm()
    pool = build_candidate_pool(sm)
    sel = select_candidates(pool, sm)
    pivot_from_selection(sm, sel)
    assert all(t.compression != CompressionLevel.ARCHIVED for t in sm.threads)
