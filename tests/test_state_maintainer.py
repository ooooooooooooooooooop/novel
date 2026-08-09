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


def test_update_creates_intent_and_thread():
    sm = StateModel()
    update_from_plotunit(sm, _plotunit(), _new_state(), chapter_number=20)
    assert any(i.intent == "推动恒通合作落地" for i in sm.intents)  # goal → intent
    assert any(t.last_chapter == 20 and t.compression == CompressionLevel.ACTIVE for t in sm.threads)


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
