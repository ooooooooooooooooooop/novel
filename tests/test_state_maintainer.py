"""StateModel 维护子系统测试（M6 桥梁）."""
from types import SimpleNamespace

from src.object_state.statemodel import (
    CompressionLevel,
    NarrativeOpportunity,
    Provenance,
    StateModel,
    ThreadState,
)
from src.workflow_action.state_maintainer import (
    apply_maintenance_response,
    build_maintenance_prompt,
    update_from_plotunit,
)


def _plotunit(**over):
    base = dict(
        unit_id="pu_1", level="scene", goal="推动恒通合作落地",
        participants=["周正", "韩东"], conflict="商业竞争",
        released_information=["恒通同意入股"], formula_node="climax",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _new_state():
    return SimpleNamespace(state_id="s2", hidden_information=[], public_information=[])


def test_update_adds_facts_and_knowledge():
    sm = StateModel()
    pu = _plotunit()
    update_from_plotunit(sm, pu, _new_state(), chapter_number=20)
    assert "恒通同意入股" in sm.facts  # released → facts
    assert any(k.fact_ref == "恒通同意入股" and k.holder == "周正" for k in sm.knowledge)
    assert any(k.provenance == Provenance.CANON for k in sm.knowledge)

    # production closed-loop commit：post-state 只能来自 accepted prose 的
    # PlotUnit/new_state；验证结果与 delta 必须进 trace。
    from src.workflow_action.state_v2_loop import commit_post_state
    sm2, delta = commit_post_state(StateModel(), _plotunit(), _new_state(), 20, "周正与韩东见面。")
    assert "恒通同意入股" in sm2.facts
    assert delta["proposed_state_delta"]["released_information"] == ["恒通同意入股"]
    assert delta["proposed_state_delta"]["new_state_ref"] == "s2"
    assert {"strategy_horizon", "offscreen_survival", "world_background"} <= set(delta["validation"])
    assert delta["post_state_changed"] is True
    # 计划/意图不升级为事实：无 released_information 时 facts 不增长
    sm3, delta3 = commit_post_state(
        StateModel(), _plotunit(released_information=[]), _new_state(), 21, "x")
    assert not any("恒通" in f for f in sm3.facts)

    # evidence grounding：transition 的 anchor 不在 accepted prose 中 → 拒绝关闭。
    from src.object_state.plotunit import ThreadTransition
    sm4 = StateModel(threads=[ThreadState(
        thread_id="t_p", thread_type="线", label="待办",
        current_state="未履行", compression=CompressionLevel.ACTIVE,
        provenance=Provenance.CANON)])
    pu_close = _plotunit()
    sm5, delta5 = commit_post_state(sm4, pu_close, _new_state(), 22, "周正与韩东见面。",
        thread_transitions=[ThreadTransition(
            action="CLOSE", thread_id="t_p", closure_kind="fulfilled",
            evidence_anchor="正文里没有的锚点")])
    assert sm5.threads[0].lifecycle.value == "open"
    assert delta5["thread_transitions"]["skipped_reason"]["decl#0:t_p"] == "evidence_not_grounded"
    # anchor 落在 prose 内 → 关闭
    pu_close2 = _plotunit()
    sm6, delta6 = commit_post_state(sm5, pu_close2, _new_state(), 23, "周正与韩东见面。",
        thread_transitions=[ThreadTransition(
            action="CLOSE", thread_id="t_p", closure_kind="fulfilled",
            evidence_anchor="见面")])
    assert sm6.threads[0].lifecycle.value == "closed"
    assert sm6.threads[0].closure_kind.value == "fulfilled"


def test_update_creates_intent_and_thread():
    sm = StateModel()
    update_from_plotunit(sm, _plotunit(), _new_state(), chapter_number=20)
    assert any(i.intent == "推动恒通合作落地" for i in sm.intents)  # goal → intent
    # goal 不再升级为 factual thread（plan≠fact；factual thread 只能由
    # accepted-prose-grounded OPEN transition 建立）
    assert not sm.threads

    # state_v2 生产接入层：seed provenance 校验 + trace/pre-state 往返。
    import json, tempfile
    from pathlib import Path
    from src.workflow_action import state_v2_loop

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        assert state_v2_loop.load_state(ws) is None

        seed_sm = StateModel(threads=[ThreadState(
            thread_id="t1", thread_type="商业线", label="恒通机芯",
            current_state="谈判中", compression=CompressionLevel.ACTIVE,
            provenance=Provenance.CANON)])
        good = {"state_model": seed_sm.model_dump(),
                "provenance_map": {"thread:t1": {"source": "prose", "ref": "chapter_450"}}}
        assert state_v2_loop.validate_seed_doc(good).threads[0].thread_id == "t1"

        for bad_doc in (
            {"state_model": seed_sm.model_dump(), "provenance_map": {}},  # 缺来源
            {"state_model": seed_sm.model_dump(),
             "provenance_map": {"thread:t1": {"source": "future_outline", "ref": "x"}}},  # 非法来源
            {"state_model": seed_sm.model_dump(),
             "provenance_map": {"thread:t1": {"source": "prose", "ref": ""}}},  # 空 ref
        ):
            try:
                state_v2_loop.validate_seed_doc(bad_doc)
                raise AssertionError("illegal seed accepted")
            except state_v2_loop.StateV2Error:
                pass

        # trace 追加与 post-state 往返（Ch2 读 Ch1 committed post-state）
        state_v2_loop.append_trace(ws, {"chapter": 1, "selected_ids": ["c_t1"]})
        state_v2_loop.append_trace(ws, {"chapter": 2, "selected_ids": []})
        entries = json.loads((ws / "state_v2_trace.json").read_text(encoding="utf-8"))
        assert [e["chapter"] for e in entries] == [1, 2]
        state_v2_loop.save_state(ws, seed_sm)
        assert state_v2_loop.load_state(ws).threads[0].thread_id == "t1"


def test_update_creates_relationship():
    sm = StateModel()
    update_from_plotunit(sm, _plotunit(), _new_state(), chapter_number=20)
    assert any(r.from_entity == "周正" and r.to_entity == "韩东" for r in sm.relationships)


def test_opportunity_when_thread_overdue():
    sm = StateModel(
        threads=[ThreadState(thread_id="t_old", thread_type="校园线", label="校园", last_chapter=1)],
        last_chapter=1,
    )
    update_from_plotunit(sm, _plotunit(), _new_state(), chapter_number=20)
    # 旧线程欠 19 章 → 产生机会
    assert any("校园" in o.description for o in sm.narrative_opportunities)


def test_maintenance_prompt_contains_chapter():
    sm = StateModel(facts=["旧事实"])
    prompt = build_maintenance_prompt(sm, "本章正文：谈判达成。")
    assert "本章正文" in prompt
    assert "谈判达成" in prompt
    assert "旧事实" in prompt


def test_apply_response_merges_offscreen_simulated():
    sm = StateModel()
    resp = (
        '{"offscreen_updates": [{"entity": "韩东", "background_state": "被停职调查", '
        '"next_most_likely": "可能调任", "events_since": ["被举报"]}], '
        '"strategic_updates": [{"entity": "周正", "waiting_for": ["地皮批复"], '
        '"pending_payoffs": ["产业链整合"]}]}'
    )
    sm = apply_maintenance_response(sm, resp)
    assert sm.offscreen[0].entity == "韩东"
    assert sm.offscreen[0].provenance == Provenance.SIMULATED  # 后台推演不升级
    assert sm.strategic[0].waiting_for == ["地皮批复"]


def test_apply_bad_json_noop():
    sm = StateModel(facts=["a"])
    sm2 = apply_maintenance_response(sm, "not json{{{")
    assert sm2 is sm  # 解析失败 no-op


def test_apply_knowledge_append():
    sm = StateModel()
    resp = '{"knowledge_updates": [{"fact_ref": "f1", "holder": "夏晴", "status": "misunderstands", "detail": "误解布局"}]}'
    sm = apply_maintenance_response(sm, resp)
    assert sm.knowledge[0].status == "misunderstands"
