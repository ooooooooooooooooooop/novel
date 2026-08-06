"""ReaderExpectation tests — 读者预期管理视图.

覆盖：
- 对象层：ReaderExpectation/ReaderExpectationLedger 构造与校验
- 派生：ForeshadowGraph → ReaderExpectationLedger 的状态判定
  （waiting / advanced / overdue / stale）
- 排序：top_questions 高优先在前
- 渲染：to_prompt_context 读者视角问题
"""

import pytest

from src.object_state.foreshadowgraph import ForeshadowEntry, ForeshadowGraph
from src.object_state.readerexpectation import (
    ReaderExpectation,
    ReaderExpectationLedger,
    derive_reader_expectations,
)


def _mk_fg(entries):
    return ForeshadowGraph(entries=[ForeshadowEntry(**e) for e in entries])


def _entry(thread_id="th1", content="墨痕来历", expected_payoff="揭示真相",
           status="active", scope="book", visibility="explicit",
           advancement=None, overdue_risk=None):
    return {
        "thread_id": thread_id,
        "setup_point": "第一章",
        "content": content,
        "visibility_level": visibility,
        "expected_payoff": expected_payoff,
        "current_status": status,
        "scope_level": scope,
        "advancement_nodes": list(advancement or []),
        "overdue_risk": overdue_risk,
    }


def test_reader_expectation_construction():
    e = ReaderExpectation(
        expectation_id="re_th1",
        reader_question="墨痕到底是什么？",
        source_thread_id="th1",
        importance="high",
        opened_at="第一章",
    )
    assert e.status == "waiting"
    assert e.window_plotunits == 3


def test_ledger_empty_context():
    ledger = ReaderExpectationLedger()
    assert ledger.to_prompt_context() == "【读者预期】无活跃期待"


def test_derive_waiting_within_window():
    fg = _mk_fg([_entry()])
    ledger = derive_reader_expectations(fg, current_plotunit_count=2)
    assert len(ledger.expectations) == 1
    assert ledger.expectations[0].status == "waiting"


def test_derive_overdue_after_window():
    fg = _mk_fg([_entry()])
    ledger = derive_reader_expectations(fg, current_plotunit_count=4)
    assert ledger.expectations[0].status == "overdue"


def test_derive_stale_far_beyond_window():
    fg = _mk_fg([_entry()])
    ledger = derive_reader_expectations(fg, current_plotunit_count=10)
    assert ledger.expectations[0].status == "stale"


def test_derive_advanced_when_advanced():
    fg = _mk_fg([_entry(advancement=["pu_001", "pu_002"])])
    ledger = derive_reader_expectations(fg, current_plotunit_count=10)
    assert ledger.expectations[0].status == "advanced"
    assert ledger.expectations[0].advancement_count == 2
    assert ledger.expectations[0].last_advanced_at == "pu_002"


def test_derive_overdue_risk_overrides_to_stale():
    fg = _mk_fg([_entry(overdue_risk="主线承诺长时间无推进")])
    ledger = derive_reader_expectations(fg, current_plotunit_count=1)
    assert ledger.expectations[0].status == "stale"


def test_derive_ignores_non_active():
    fg = _mk_fg([_entry(status="resolved"), _entry(thread_id="th2")])
    ledger = derive_reader_expectations(fg, current_plotunit_count=1)
    assert len(ledger.expectations) == 1
    assert ledger.expectations[0].source_thread_id == "th2"


def test_reader_question_translation():
    # 已含疑问词 → 保留
    fg1 = _mk_fg([_entry(content="墨痕是什么")])
    q1 = derive_reader_expectations(fg1).expectations[0].reader_question
    assert q1 == "墨痕是什么"
    # 揭示型 payoff → 补「真相是什么」
    fg2 = _mk_fg([_entry(content="墨痕来历", expected_payoff="揭示真相")])
    q2 = derive_reader_expectations(fg2).expectations[0].reader_question
    assert "真相是什么" in q2
    # 代价型 payoff → 补「代价」
    fg3 = _mk_fg([_entry(content="改写规则", expected_payoff="付出代价")])
    q3 = derive_reader_expectations(fg3).expectations[0].reader_question
    assert "代价" in q3
    # 默认（无匹配 payoff）→ 补「究竟是怎么回事」
    fg4 = _mk_fg([_entry(content="神秘人影", expected_payoff="神秘")])
    q4 = derive_reader_expectations(fg4).expectations[0].reader_question
    assert "究竟是怎么回事" in q4


def test_top_questions_sort_overdue_first():
    fg = _mk_fg([
        _entry(thread_id="th_stale", content="久远伏笔", expected_payoff="回收"),
        _entry(thread_id="th_adv", content="已推进伏笔", expected_payoff="回收",
               advancement=["pu_001"]),
    ])
    ledger = derive_reader_expectations(fg, current_plotunit_count=10)
    top = ledger.top_questions(limit=5)
    assert [e.source_thread_id for e in top] == ["th_stale", "th_adv"]


def test_overdue_expectations_filters():
    fg = _mk_fg([
        _entry(thread_id="th1"),
        _entry(thread_id="th2", overdue_risk="拖延"),
    ])
    ledger = derive_reader_expectations(fg, current_plotunit_count=1)
    overdue = ledger.overdue_expectations()
    assert len(overdue) == 1
    assert overdue[0].source_thread_id == "th2"


def test_to_prompt_context_renders():
    fg = _mk_fg([
        _entry(content="墨痕来历", expected_payoff="揭示真相"),
        _entry(thread_id="th2", content="沈望命运", expected_payoff="回收"),
    ])
    ledger = derive_reader_expectations(fg, current_plotunit_count=2)
    ctx = ledger.to_prompt_context()
    assert "【读者预期" in ctx
    assert "墨痕来历，真相是什么？" in ctx
    assert "沈望命运，最终会怎样？" in ctx
