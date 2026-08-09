"""State V2 / Narrative Selection 核心测试.

验证 V2 架构三个关键点：
1. Full State → Candidate Pool：只收有触发的内容，无触发的进 excluded_alive（不丢）；
2. Selection：Empty Set Start + Minimum Sufficient + Suppressor（治 checklist_like）；
3. Context Firewall：正文只看 Chapter Packet（SELECT），BACKGROUND/DORMANT 拿不到；
4. Reveal Validation：隐藏计划不提前泄露；Silence 拆 Explicit Mention / Forced Re-entry。
"""
from src.object_state.statemodel import (
    CompressionLevel,
    NarrativeOpportunity,
    Provenance,
    StateModel,
    StrategicPosition,
    ThreadState,
)
from src.workflow_action.candidate_pool import CandidatePool, build_candidate_pool
from src.workflow_action.context_firewall import (
    build_chapter_packet,
)
from src.workflow_action.narrative_selector import (
    select_candidates,
    suppress_overreach,
)


def _sm() -> StateModel:
    """一个含多线程/战略/机会的 StateModel（类似 ch450）."""
    return StateModel(
        last_chapter=450,
        threads=[
            ThreadState(thread_id="t_main", thread_type="商业线", label="恒通机芯",
                        current_state="谈判中", near_payoff=True,
                        needs_protagonist=True, compression=CompressionLevel.ACTIVE,
                        provenance=Provenance.CANON),
            ThreadState(thread_id="t_bg", thread_type="官场线", label="陆平官场",
                        current_state="暗中角力", can_background=True,
                        needs_protagonist=False, compression=CompressionLevel.WARM,
                        provenance=Provenance.CANON),
            ThreadState(thread_id="t_dead", thread_type="旧线", label="已归档旧线",
                        compression=CompressionLevel.ARCHIVED, provenance=Provenance.CANON),
            ThreadState(thread_id="t_warm", thread_type="家庭线", label="夏晴家庭",
                        current_state="日常", can_background=True,
                        needs_protagonist=False, compression=CompressionLevel.WARM,
                        recent_change="夏安准备去香港",
                        provenance=Provenance.CANON),
        ],
        strategic=[
            StrategicPosition(entity="周正", pending_payoffs=["机芯工厂"], triggers=["顾总同意"])
        ],
        narrative_opportunities=[
            NarrativeOpportunity(opp_type="线程回归", description="夏晴家庭线欠账", priority=8)
        ],
    )


def test_candidate_pool_only_triggered():
    """Candidate Pool 只收有触发的内容；无触发 → excluded_alive（不丢）. """
    pool = build_candidate_pool(_sm())
    # near_payoff 的 t_main → 有触发
    sources = [c.source_thread for c in pool.candidates]
    assert any("恒通" in s for s in sources)
    # 无触发、可后台的 t_bg → excluded_alive（仍在运行，非遗忘）
    assert any("陆平" in e for e in pool.excluded_alive)
    # 已归档 → 完全不参与
    assert not any("归档" in (c.source_thread or "") for c in pool.candidates)


def test_empty_set_start_default():
    """Empty Set Start：无触发或证据不足的候选默认不 SELECT. """
    sm = StateModel(
        threads=[ThreadState(thread_id="t1", thread_type="线", label="仅活跃无变化",
                             compression=CompressionLevel.ACTIVE,
                             needs_protagonist=False, can_background=True)]
    )
    pool = build_candidate_pool(sm)
    sel = select_candidates(pool, sm)
    # 无触发 → 没有候选进入 selected
    assert sel.selected == []
    assert pool.excluded_alive  # 它仍在运行


def test_minimum_sufficient_caps_overload():
    """Minimum Sufficient：max_selected 上限时裁剪，多余的转 BACKGROUND. """
    pool = build_candidate_pool(_sm())
    sel = select_candidates(pool, _sm(), max_selected=2)
    assert len(sel.selected) <= 2
    assert sel.background  # 被裁剪的在后台（不是遗忘）


def test_suppressor_removes_checklist():
    """Suppressor 删除清单式/硬回收候选. """
    pool = build_candidate_pool(_sm())
    sel = select_candidates(pool, _sm())
    before = len(sel.selected)
    suppress_overreach(sel)
    # work_preference / 欠账 natural_reentry 被抑制
    assert len(sel.selected) <= before
    assert sel.rejected  # 记录被删除项


def test_context_firewall_blocks_background():
    """Context Firewall：正文包只含 SELECT；BACKGROUND/DORMANT 拿不到. """
    pool = build_candidate_pool(_sm())
    sel = select_candidates(pool, _sm())
    bg_sources = {c.source_thread for c in sel.background}
    packet = build_chapter_packet(sel, chapter=450)
    packet_sources = {c.source_thread for c in packet.selected}
    # BACKGROUND 的候选不在包里
    for s in bg_sources:
        assert s not in packet_sources
    # render 只含 SELECT
    render = packet.render()
    assert render.startswith("【本章上下文包】")
    assert "未列入的世界状态请勿提及" in render


def test_packet_zero_cost_empty():
    from src.workflow_action.narrative_selector import SelectionResult
    packet = build_chapter_packet(SelectionResult())
    assert packet.is_empty()
    assert packet.render() == ""


def test_reveal_leakage_detection():
    from src.workflow_action.reveal_validation import check_reveal_leakage
    good = check_reveal_leakage("两人喝了茶，谈了谈机芯的事。", hidden_plans=["三章后背叛"])
    assert good["leakage_score"] == 0
    bad = check_reveal_leakage("他真正的目的是三章后背叛。", hidden_plans=["三章后背叛"])
    assert bad["leaked_plans"] == ["三章后背叛"]
    assert bad["leakage_score"] > 0


def test_silence_metrics_split():
    from src.workflow_action.reveal_validation import silence_metrics
    leaky = silence_metrics("至于陆平那边，暂且不提。", set())
    assert leaky["explicit_leak_count"] > 0
    clean = silence_metrics("两人只谈了机芯。", set())
    assert clean["explicit_leak_count"] == 0
