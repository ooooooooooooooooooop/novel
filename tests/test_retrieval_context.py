"""Tests for RetrievalUnit and load_retrieval_context — state-driven retrieval."""

from pathlib import Path

from src.object_state import (
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
)
from src.workflow_action.retrieval import (
    RetrievalUnit,
    load_retrieval_context,
    textualize_fact,
    textualize_foreshadow,
    textualize_narrative_state,
)


def _state(**overrides) -> NarrativeState:
    base = dict(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        current_situation="发现古书藏于密室",
        active_characters=["c001"],
        active_conflicts=["时间压力"],
    )
    base.update(overrides)
    return NarrativeState(**base)


def _facts(entries: list[FactEntry]) -> FactLedger:
    return FactLedger(entries=entries)


def _foreshadows(entries: list[ForeshadowEntry]) -> ForeshadowGraph:
    return ForeshadowGraph(entries=entries)


def test_textualize_narrative_state_joins_key_fields():
    state = _state()
    text = textualize_narrative_state(state)
    assert "发现古书藏于密室" in text
    assert "藏经阁" in text
    assert "c001" in text


def test_textualize_narrative_state_excludes_noise_fields():
    state = _state(primary_goal="夺取令牌", public_information=["世人皆知宗门规矩"])
    text = textualize_narrative_state(state)
    assert "夺取令牌" in text
    assert "世人皆知宗门规矩" not in text  # public_information 排除
    assert "s1" not in text  # state_id 排除


def test_textualize_fact_includes_entities():
    entry = FactEntry(
        fact_id="f_001",
        statement="古书藏于藏经阁密室",
        fact_type="relation",
        involved_entities=["c001", "藏经阁"],
        confirmed=True,
    )
    text = textualize_fact(entry)
    assert "古书藏于藏经阁密室" in text
    assert "c001" in text
    assert "藏经阁" in text


def test_textualize_foreshadow_includes_payoff():
    entry = ForeshadowEntry(
        thread_id="t_002",
        setup_point="第3章末尾神秘人影",
        content="主角身世之谜",
        visibility_level="implicit",
        expected_payoff="身世揭晓",
        linked_characters=["c001"],
    )
    text = textualize_foreshadow(entry)
    assert "主角身世之谜" in text
    assert "身世揭晓" in text
    assert "c001" in text


def test_empty_ledger_returns_empty():
    unit = RetrievalUnit()
    state = _state()
    out = unit.build_retrieval_context(state, _facts([]), _foreshadows([]))
    assert out == ""


def test_unconfirmed_facts_excluded():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                confirmed=True,
            ),
            FactEntry(
                fact_id="f_002",
                statement="令牌归宗门所有",
                fact_type="relation",
                confirmed=False,
            ),
        ]
    )
    unit = RetrievalUnit()
    out = unit.build_retrieval_context(_state(), facts, _foreshadows([]))
    assert "f_001" in out
    assert "令牌" not in out


def test_current_situation_keyword_hits_statement():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                involved_entities=["c001"],
                confirmed=True,
            ),
            FactEntry(
                fact_id="f_002",
                statement="祠堂香火不断",
                fact_type="relation",
                confirmed=True,
            ),
        ]
    )
    unit = RetrievalUnit(top_k=1)
    out = unit.build_retrieval_context(_state(), facts, _foreshadows([]))
    assert "古书藏于藏经阁密室" in out
    assert "祠堂香火" not in out


def test_active_characters_match_involved_entities():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="顾临持有令牌",
                fact_type="relation",
                involved_entities=["c001"],
                confirmed=True,
            ),
            FactEntry(
                fact_id="f_002",
                statement="沈砚闭关",
                fact_type="relation",
                involved_entities=["c002"],
                confirmed=True,
            ),
        ]
    )
    state = _state(active_characters=["c001"])
    unit = RetrievalUnit(top_k=2)
    out = unit.build_retrieval_context(state, facts, _foreshadows([]))
    assert "顾临持有令牌" in out
    assert "沈砚闭关" not in out


def test_linked_open_threads_filters_foreshadow_source():
    foreshadows = _foreshadows(
        [
            ForeshadowEntry(
                thread_id="t_001",
                setup_point="第3章",
                content="主角身世之谜",
                visibility_level="implicit",
                expected_payoff="身世揭晓",
                current_status="active",
                linked_characters=["c001"],
            ),
            ForeshadowEntry(
                thread_id="t_002",
                setup_point="第5章",
                content="宗门禁地",
                visibility_level="explicit",
                expected_payoff="禁地开启",
                current_status="active",
                linked_characters=["c001"],
            ),
            ForeshadowEntry(
                thread_id="t_003",
                setup_point="第1章",
                content="香炉暗格",
                visibility_level="implicit",
                expected_payoff="信物",
                current_status="resolved",
                linked_characters=["c001"],
            ),
        ]
    )
    # 只关联 t_002 且 active
    state = _state(linked_open_threads=["t_002"])
    unit = RetrievalUnit(top_k=5)
    out = unit.build_retrieval_context(state, _facts([]), foreshadows)
    assert "宗门禁地" in out
    assert "主角身世之谜" not in out
    assert "香炉暗格" not in out


def test_current_facts_in_scope_boost():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="藏经阁密道",
                fact_type="object",
                confirmed=True,
            ),
            FactEntry(
                fact_id="f_002",
                statement="藏经阁古书",
                fact_type="object",
                confirmed=True,
            ),
        ]
    )
    state = _state(current_facts_in_scope=["f_002"])
    unit = RetrievalUnit(top_k=1)
    out = unit.build_retrieval_context(state, facts, _foreshadows([]))
    assert "藏经阁古书" in out


def test_top_k_limits_rendered():
    facts = _facts(
        [
            FactEntry(
                fact_id=f"f_{i:03d}",
                statement=f"藏经阁第{i}处",
                fact_type="object",
                confirmed=True,
            )
            for i in range(1, 8)
        ]
    )
    unit = RetrievalUnit(top_k=2)
    out = unit.build_retrieval_context(_state(), facts, _foreshadows([]))
    lines = [line for line in out.splitlines() if line.startswith("- [事实]")]
    assert len(lines) == 2


def test_render_format_contains_labels_and_ids():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                confirmed=True,
            )
        ]
    )
    unit = RetrievalUnit()
    out = unit.build_retrieval_context(_state(), facts, _foreshadows([]))
    assert "【相关事实检索】" in out
    assert "- [事实] 古书藏于藏经阁密室 (id=f_001)" in out


def test_loader_returns_empty_for_empty_corpus():
    state = _state()
    out = load_retrieval_context(
        Path("output"),
        state=state,
        facts=_facts([]),
        foreshadows=_foreshadows([]),
    )
    assert out == ""


def test_loader_delegates_to_unit():
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                confirmed=True,
            )
        ]
    )
    out = load_retrieval_context(
        Path("output"),
        state=_state(),
        facts=facts,
        foreshadows=_foreshadows([]),
    )
    assert "古书藏于藏经阁密室" in out


def test_deterministic_output():
    state = _state()
    facts = _facts(
        [
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                confirmed=True,
            ),
            FactEntry(
                fact_id="f_002",
                statement="祠堂香火不断",
                fact_type="relation",
                confirmed=True,
            ),
        ]
    )
    unit = RetrievalUnit(top_k=2)
    out1 = unit.build_retrieval_context(state, facts, _foreshadows([]))
    out2 = unit.build_retrieval_context(state, facts, _foreshadows([]))
    assert out1 == out2
