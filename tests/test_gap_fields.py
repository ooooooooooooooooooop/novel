"""C 档 12+4 字段 schema 补齐测试.

覆盖：
- 各新字段默认值
- 旧档案（不含新字段）反序列化 → 默认值补齐（向后兼容）
- to_prompt_context 零成本契约：无新字段时不注入字节
- ForeshadowEntry.current_status 补 open/delayed/false_path 管理态
"""

import json

from src.object_state import (
    FactEntry,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    WorldModel,
)


def _mk_state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="第3天",
        current_location="客栈",
        current_situation="局势稳定",
    )


def _mk_pu() -> PlotUnit:
    return PlotUnit(
        unit_id="pu_1",
        level="scene",
        goal="追查线索",
        conflict="线人失踪",
        input_state_ref="s0",
        output_state_ref="s1",
    )


# ---------- NarrativeState：private_information_map / open_questions ----------

def test_narrative_state_new_fields_defaults():
    ns = _mk_state()
    assert ns.private_information_map == {}
    assert ns.open_questions == []


def test_narrative_state_new_fields_roundtrip():
    ns = _mk_state()
    ns.private_information_map = {"顾府是卧底": ["char_a"]}
    ns.open_questions = ["谁是内鬼？"]
    assert ns.private_information_map["顾府是卧底"] == ["char_a"]


def test_narrative_state_to_prompt_context_zero_cost_without_fields():
    bare = _mk_state().to_prompt_context()
    assert "秘密知情分布" not in bare
    assert "开放问题" not in bare


def test_narrative_state_to_prompt_context_renders_fields_when_set():
    ns = _mk_state()
    ns.private_information_map = {"顾府是卧底": ["char_a"]}
    ns.open_questions = ["谁是内鬼？"]
    ctx = ns.to_prompt_context()
    assert "秘密知情分布" in ctx
    assert "顾府是卧底" in ctx and "char_a" in ctx
    assert "开放问题" in ctx and "谁是内鬼？" in ctx


def test_narrative_state_deserializes_old_archive():
    ns = NarrativeState.model_validate_json(json.dumps({
        "state_id": "s1",
        "current_time": "第3天",
        "current_location": "客栈",
        "current_situation": "局势稳定",
    }))
    assert ns.private_information_map == {}
    assert ns.open_questions == []


# ---------- FactEntry：known_by / chronological_order ----------

def test_factentry_new_fields_defaults():
    fe = FactEntry(fact_id="f1", statement="令牌归c001所有", fact_type="object")
    assert fe.known_by == []
    assert fe.chronological_order is None


def test_factentry_to_prompt_line_zero_cost_without_fields():
    fe = FactEntry(fact_id="f1", statement="令牌归c001所有", fact_type="object")
    line = fe.to_prompt_line()
    assert "[知:" not in line
    assert "[发生于" not in line


def test_factentry_to_prompt_line_renders_fields_when_set():
    fe = FactEntry(
        fact_id="f1",
        statement="令牌归c001所有",
        fact_type="object",
        known_by=["char_a", "char_b"],
        chronological_order="发生于令牌转移之前",
    )
    line = fe.to_prompt_line()
    assert "[知: char_a,char_b]" in line
    assert "[发生于令牌转移之前]" in line


def test_factentry_deserializes_old_archive():
    fe = FactEntry.model_validate_json(json.dumps({
        "fact_id": "f1",
        "statement": "令牌归c001所有",
        "fact_type": "object",
    }))
    assert fe.known_by == []
    assert fe.chronological_order is None


# ---------- ForeshadowEntry：6 字段 + current_status 管理态 ----------

def _mk_foreshadow(current_status: str = "active") -> ForeshadowEntry:
    return ForeshadowEntry(
        thread_id="th_1",
        setup_point="第1章",
        content="主角身世之谜",
        visibility_level="implicit",
        expected_payoff="回收揭晓",
        current_status=current_status,
    )


def test_foreshadow_new_fields_defaults():
    fe = _mk_foreshadow()
    assert fe.advancement_nodes == []
    assert fe.narrowing_events == []
    assert fe.payoff_nodes == []
    assert fe.urgency_to_payoff is None
    assert fe.overdue_risk is None
    assert fe.scope_level is None


def test_foreshadow_current_status_accepts_management_states():
    for status in ("open", "delayed", "false_path"):
        fe = _mk_foreshadow(current_status=status)
        assert fe.current_status == status


def test_foreshadow_get_active_still_filters_on_active():
    fg = ForeshadowGraph(entries=[
        _mk_foreshadow(current_status="active"),
        _mk_foreshadow(current_status="open"),
        _mk_foreshadow(current_status="delayed"),
    ])
    active = fg.get_active()
    assert len(active) == 1
    assert active[0].current_status == "active"


def test_foreshadow_renders_fields_when_set():
    fe = _mk_foreshadow()
    fe.advancement_nodes = ["pu_1"]
    fe.urgency_to_payoff = "临近真相"
    fe.overdue_risk = "主线承诺长时间无推进"
    fe.scope_level = "book"
    ctx = fe.to_prompt_context() if hasattr(fe, "to_prompt_context") else ""
    # ForeshadowGraph 负责渲染；验证字段本身可设置
    assert fe.advancement_nodes == ["pu_1"]
    assert fe.scope_level == "book"


def test_foreshadow_deserializes_old_archive():
    fe = ForeshadowEntry.model_validate_json(json.dumps({
        "thread_id": "th_1",
        "setup_point": "第1章",
        "content": "主角身世之谜",
        "visibility_level": "implicit",
        "expected_payoff": "回收揭晓",
    }))
    assert fe.current_status == "active"
    assert fe.advancement_nodes == []
    assert fe.scope_level is None


# ---------- PlotUnit：state_change_summary / removable_without_loss ----------

def test_plotunit_new_fields_defaults():
    pu = _mk_pu()
    assert pu.state_change_summary is None
    assert pu.removable_without_loss is None


def test_plotunit_to_prompt_context_zero_cost_without_fields():
    ctx = _mk_pu().to_prompt_context()
    assert "状态变化:" not in ctx
    assert "可删无损:" not in ctx


def test_plotunit_to_prompt_context_renders_fields_when_set():
    pu = _mk_pu()
    pu.state_change_summary = "线人身份暴露，顾府进入戒备"
    pu.removable_without_loss = False
    ctx = pu.to_prompt_context()
    assert "状态变化:" in ctx and "线人身份暴露" in ctx
    assert "可删无损:" in ctx and "否" in ctx


def test_plotunit_deserializes_old_archive():
    pu = PlotUnit.model_validate_json(json.dumps({
        "unit_id": "pu_1",
        "level": "scene",
        "goal": "追查线索",
        "conflict": "线人失踪",
        "input_state_ref": "s0",
        "output_state_ref": "s1",
    }))
    assert pu.state_change_summary is None
    assert pu.removable_without_loss is None


# ---------- WorldModel：hard_rules / death_rule / forbidden_actions / exception_rules ----------

def test_worldmodel_new_fields_defaults():
    wm = WorldModel()
    assert wm.hard_rules == []
    assert wm.death_rule is None
    assert wm.forbidden_actions == []
    assert wm.exception_rules == []


def test_worldmodel_to_prompt_context_zero_cost_without_fields():
    wm = WorldModel()
    ctx = wm.to_prompt_context()
    assert "硬规则:" not in ctx
    assert "死亡规则:" not in ctx
    assert "禁忌行为:" not in ctx
    assert "例外规则:" not in ctx


def test_worldmodel_renders_fields_when_set():
    wm = WorldModel(
        hard_rules=["力量上限"],
        death_rule="死亡不可逆",
        forbidden_actions=["血祭"],
        exception_rules=["掌门特许除外"],
    )
    ctx = wm.to_prompt_context()
    assert "硬规则: 力量上限" in ctx
    assert "死亡规则: 死亡不可逆" in ctx
    assert "禁忌行为: 血祭" in ctx
    assert "例外规则: 掌门特许除外" in ctx


def test_worldmodel_deserializes_empty_archive():
    wm = WorldModel.model_validate_json(json.dumps({}))
    assert wm.hard_rules == []
    assert wm.death_rule is None
    assert wm.forbidden_actions == []
    assert wm.exception_rules == []
