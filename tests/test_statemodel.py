"""StateModel（Narrative Living State）核心数据结构测试."""
import pytest

from src.object_state.statemodel import (
    CompressionLevel,
    KnowledgeEntry,
    NarrativeOpportunity,
    OffScreenProcess,
    Provenance,
    RelationshipEntry,
    StateModel,
    StrategicPosition,
    ThreadEdge,
    ThreadState,
)


def test_zero_cost_empty():
    """空 StateModel：is_empty True，渲染段为空串（prompt 字节不变）."""
    sm = StateModel()
    assert sm.is_empty()
    assert sm.render_prompt_section() == ""


def test_render_with_threads_and_offscreen():
    sm = StateModel(
        threads=[
            ThreadState(
                thread_id="t1", thread_type="商业线", label="恒通合作",
                current_state="谈判中", near_payoff=True,
                can_background=True, needs_protagonist=False,
            ),
            ThreadState(
                thread_id="t2", thread_type="家庭线", label="许家", current_state="平静",
                compression=CompressionLevel.DORMANT,
            ),
        ],
        offscreen=[
            OffScreenProcess(entity="韩东", background_state="被停职调查中", provenance=Provenance.SIMULATED)
        ],
        strategic=[
            StrategicPosition(entity="周正", waiting_for=["商业地皮批复"], pending_payoffs=["产业链整合"])
        ],
        narrative_opportunities=[
            NarrativeOpportunity(opp_type="人物重入", description="校园线 20 章未回归", priority=7)
        ],
    )
    assert not sm.is_empty()
    sec = sm.render_prompt_section()
    assert "【跨章状态】" in sec
    assert "恒通合作" in sec
    assert "接近兑现" in sec
    assert "可后台运行" in sec
    assert "韩东" in sec
    assert "周正" in sec
    assert "校园线 20 章未回归" in sec
    # DORMANT 线程不应出现在 active 渲染里
    assert "许家" not in sec


def test_provenance_guard():
    """后台模拟默认 SIMULATED，只有 CANON 才是正文事实."""
    off = OffScreenProcess(entity="配角A", background_state="可能辞职")
    assert off.provenance == Provenance.SIMULATED
    kn = KnowledgeEntry(fact_ref="f1", holder="周正", status="knows", detail="知道布局")
    assert kn.provenance == Provenance.CANON


def test_compression_levels():
    assert CompressionLevel.DORMANT.value == "dormant"
    # Dormant ≠ Forgotten：仍有压缩后的引用（这里用 thread 保留核心字段）
    t = ThreadState(thread_id="t", thread_type="人物线", label="配角", compression=CompressionLevel.DORMANT)
    assert t.label  # 压缩后仍保留身份


def test_thread_graph_edges():
    g = StateModel(
        thread_graph={
            "nodes": ["周正", "夏晴", "thread_商业"],
            "edges": [ThreadEdge(from_node="周正", to_node="thread_商业", edge_type="利益", detail="布局关联")],
        }
    )
    assert not g.is_empty()
    assert g.thread_graph.nodes == ["周正", "夏晴", "thread_商业"]
    assert g.thread_graph.edges[0].edge_type == "利益"


def test_relationship_records_why():
    r = RelationshipEntry(
        from_entity="周正", to_entity="夏晴",
        bonds=["亲密", "试探", "身份距离"],
        temperature="升温",
        why_changed="夏晴得知周正的产业布局后改观",
    )
    assert r.why_changed  # 关系变化必须记录原因
