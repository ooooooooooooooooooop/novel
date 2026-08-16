"""确定性门禁对抗性防火墙测试（Track A 替代验收证据 · 第二批）.

聚焦既有测试**未覆盖**的确定性程序不变量：
  1. `analyze_continuation_viability` 幂等（同输入 → 同裁决/同信号/确定性）；
  2. needs_premise 的 required_premise 必须提及具体未兑现承诺内容（非仅计数）；
  3. `check_reveal_leakage` 对「语义暗示但未逐字说出」的隐藏计划不得误报（负控制）；
  4. `check_temporal_contradictions` 对同组事实的检出与**条目顺序无关**。

都是 state-first 的一致性验收证据：纯代码、可注入、可复现、可证伪。
"""

from src.object_state import ForeshadowEntry, ForeshadowGraph, NarrativeState
from src.object_state.factledger import FactEntry, FactLedger, ValidityInterval
from src.object_state.readercontract import ReaderContract
from src.workflow_action.continuation_viability import analyze_continuation_viability
from src.workflow_action.reconcile import ReconcileUnit
from src.workflow_action.reveal_validation import check_reveal_leakage


# ---------------------------------------------------------------------------
# 夹具（与既有单测同构，避免重复构造）
# ---------------------------------------------------------------------------

def _state(situation: str = "当前局势") -> NarrativeState:
    return NarrativeState(
        state_id="ns_t", current_time="夜晚", current_location="场景",
        current_situation=situation, active_characters=["c001"],
    )


def _foreshadows(*contents: str) -> ForeshadowGraph:
    return ForeshadowGraph(entries=[
        ForeshadowEntry(
            thread_id=f"th_{i}", setup_point="第1章", content=content,
            visibility_level="explicit", expected_payoff="回收",
            current_status="active",
        )
        for i, content in enumerate(contents)
    ])


def _frame(no_active: bool) -> dict:
    if no_active:
        return {
            "cursor": None, "current_frame": None, "parent_chain": [],
            "sibling_context": [], "active_threads": [], "no_active_frame": True,
        }
    return {
        "cursor": {"current_frame_id": "scene_001", "current_level": "scene"},
        "current_frame": {
            "frame_id": "scene_001", "level": "scene", "title": "场景",
            "purpose": "推进", "position": "middle", "status": "active",
            "formula_node": "",
        },
        "parent_chain": [], "sibling_context": [], "active_threads": [],
        "no_active_frame": False,
    }


def _contract(ending_conditions: list[str]) -> ReaderContract:
    return ReaderContract(
        contract_id="default", audience="大众网文读者",
        core_pleasures=["围绕「核心矛盾」的张力推进", "每章产生可感知的新状态变化"],
        follow_reason="主角在压力下做出代价明确的选择",
        core_tension="「核心矛盾」驱动下的持续对抗",
        chapter_pacing="每章推进一个量级的事件",
        opening_minimum_promise="开场需给出值得期待的核心冲突",
        ending_conditions=ending_conditions,
    )


# ---------------------------------------------------------------------------
# 1. 确定性：幂等
# ---------------------------------------------------------------------------

def test_viability_deterministic_idempotent():
    kwargs = dict(
        narrative_state=_state("顾承风起身告辞"),
        foreshadows=_foreshadows("三章后顾承风背叛沈砚"),
        frame_context=_frame(no_active=False),
        contract=_contract(["尘埃落定"]),
        recent_chapter_count=1,
    )
    first = analyze_continuation_viability(**kwargs)
    second = analyze_continuation_viability(**kwargs)
    assert first.verdict == second.verdict
    assert first.deterministic is True and second.deterministic is True
    assert [s.signal_id for s in first.signals] == [s.signal_id for s in second.signals]
    assert first.reasons == second.reasons
    assert first.required_premise == second.required_premise


# ---------------------------------------------------------------------------
# 2. needs_premise：required_premise 必须提及具体承诺内容
# ---------------------------------------------------------------------------

def test_needs_premise_required_premise_mentions_promise():
    promise = "三章后顾承风背叛沈砚"
    d = analyze_continuation_viability(
        narrative_state=_state("故事走到尾声"),
        foreshadows=_foreshadows(promise),
        frame_context=_frame(no_active=True),
        contract=None,
    )
    assert d.verdict == "needs_premise"
    assert d.deterministic is True
    assert d.required_premise is not None
    assert promise in d.required_premise  # 不是只报数字，要带上具体承诺内容


# ---------------------------------------------------------------------------
# 3. reveal 泄漏：语义暗示 ≠ 逐字泄露（负控制，防误报）
# ---------------------------------------------------------------------------

def test_reveal_paraphrased_plan_not_flagged():
    out = check_reveal_leakage(
        "他打算过些时日再表明立场，眼下不动声色。",
        hidden_plans=["三章后顾承风背叛沈砚"],
        reader_knowledge={"读者已知主角身份"},
    )
    assert out["leaked_plans"] == []
    assert out["leakage_score"] == 0


def test_reveal_verbatim_plan_flagged():
    out = check_reveal_leakage(
        "他真正的目的是三章后顾承风背叛沈砚。",
        hidden_plans=["三章后顾承风背叛沈砚"],
    )
    assert "三章后顾承风背叛沈砚" in out["leaked_plans"]
    assert out["leakage_score"] >= 1


# ---------------------------------------------------------------------------
# 4. 时间门禁：检出与条目顺序无关
# ---------------------------------------------------------------------------

def _death_active_ledger(*, alive_first: bool) -> FactLedger:
    death = FactEntry(
        fact_id="f_death", statement="张三死亡", fact_type="event",
        involved_entities=["张三"],
        validity_interval=ValidityInterval(valid_from="第三章", valid_until="第五章"),
    )
    alive = FactEntry(
        fact_id="f_alive", statement="张三仍在行动", fact_type="relation",
        involved_entities=["张三"],
        validity_interval=ValidityInterval(valid_from="第六章"),
    )
    return FactLedger(entries=[alive, death] if alive_first else [death, alive])


def test_temporal_detection_order_independent():
    issues_a = ReconcileUnit().check_temporal_contradictions(
        [_death_active_ledger(alive_first=False)]
    )
    issues_b = ReconcileUnit().check_temporal_contradictions(
        [_death_active_ledger(alive_first=True)]
    )
    assert len(issues_a) == 1 and len(issues_b) == 1
    assert issues_a[0].issue_type == issues_b[0].issue_type == "timeline_error"
    assert issues_a[0].severity == issues_b[0].severity == "blocking"
    # 更强不变量：同组事实的顺序无关包括 issue_id 也相同
    assert issues_a[0].issue_id == issues_b[0].issue_id
    assert issues_a[0].description == issues_b[0].description
