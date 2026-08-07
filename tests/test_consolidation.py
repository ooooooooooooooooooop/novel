"""Choice Consolidation tests — 作者性 4A/4C.

验证：行为证据提取（supporting=选中候选命中关键词；counterexample=被拒候选命中
或事后懊悔）；防编造（支持不足→candidate、反例过多→contested、原则必附
supporting/counterexamples）；合并既有内核（去重并集、强化、挑战记录）；
Growth（有来由地变，允许）与 Drift（无因果突变，要防）区分；render 报告。
"""

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple, principle_id_for
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.workflow_action.consolidation import (
    consolidate_ledger,
    detect_drift,
    extract_evidence,
    render_consolidation_report,
)


KEY = "character_causality_over_plot_convenience"
TS = "2026-08-07T12:00:00"


def _pu_text(text: str) -> dict:
    return {
        "unit_id": "pu_x",
        "level": "scene",
        "goal": text,
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": [],
        "released_information": [],
        "is_effective": True,
    }


def _choice(
    did: str,
    selected_text: str,
    rejected_text: str = "",
    conflicts: list[str] | None = None,
    hindsight=None,
) -> ChoiceRecord:
    cands = [
        CandidateRecord(
            candidate_id="A", summary="A", plotunit=_pu_text(selected_text),
            new_state_ref="ns_out",
        ),
        CandidateRecord(
            candidate_id="B", summary="B", plotunit=_pu_text(rejected_text or "无关文本"),
            new_state_ref="ns_out",
        ),
    ]
    rejected = (
        [RejectedRecord(candidate_id="B", reason="落选")]
        if rejected_text
        else []
    )
    return ChoiceRecord(
        decision_id=did,
        decision_timestamp=TS,
        plot_context="决策",
        state_ref="ns_in",
        candidates=cands,
        selected_candidate="A",
        rejected=rejected,
        tradeoff="放弃 X 换取 Y",
        value_conflicts=[KEY] if conflicts is None else conflicts,
        hindsight=hindsight,
    )


def _ledger(*choices: ChoiceRecord) -> ChoiceLedgerEntry:
    return ChoiceLedgerEntry(choices=list(choices))


def _kernel_with_principle(key: str = KEY, supporting: list[str] | None = None,
                           counter: list[str] | None = None,
                           status: str = "stable", strength: float = 0.9) -> AuthorKernel:
    p = AuthorPrinciple(
        principle_id=principle_id_for("value", key, 1),
        category="value",
        vocab_key=key,
        description="d",
        supporting_choices=supporting or ["d_001"],
        counterexamples=counter or [],
        first_formed_at="2026-08-01T00:00:00",
        status=status,
        strength=strength,
    )
    return AuthorKernel(kernel_id="k", values=[p])


# ---------------------------------------------------------------------------
# 行为证据提取
# ---------------------------------------------------------------------------
def test_evidence_supporting_when_selected_hits_keywords():
    ev = extract_evidence(_ledger(_choice("d_001", "角色因果优先于剧情便利")))
    assert ev[KEY].supporting == ["d_001"]
    assert ev[KEY].counterexamples == []


def test_evidence_counterexample_when_rejected_hits_keywords():
    ev = extract_evidence(
        _ledger(_choice("d_001", "剧情便利优先", rejected_text="角色因果优先"))
    )
    assert ev[KEY].supporting == []
    assert ev[KEY].counterexamples == ["d_001"]


def test_evidence_counterexample_on_hindsight_regret():
    ev = extract_evidence(
        _ledger(_choice("d_001", "角色因果优先", hindsight="overturned"))
    )
    assert ev[KEY].supporting == []
    assert ev[KEY].counterexamples == ["d_001"]


def test_evidence_ignores_untouched_value():
    ev = extract_evidence(_ledger(_choice("d_001", "角色因果优先", conflicts=[])))
    assert ev == {}


def test_evidence_touched_but_unresolved():
    # 选中/被拒都未命中关键词 → 触及但无方向证据，不计数
    ev = extract_evidence(_ledger(_choice("d_001", "纯叙事推进")))
    assert ev[KEY].supporting == []
    assert ev[KEY].counterexamples == []


# ---------------------------------------------------------------------------
# 原则形成 / 防编造（禁止 10）
# ---------------------------------------------------------------------------
def test_consolidate_forms_principle_with_support():
    result = consolidate_ledger(
        _ledger(
            _choice("d_001", "角色因果优先于剧情便利"),
            _choice("d_002", "角色因果优先于剧情便利"),
        ),
        timestamp=TS,
    )
    assert result.touched_keys == [KEY]
    assert KEY in result.new_principles
    p = result.kernel.values[0]
    assert p.vocab_key == KEY
    assert p.supporting_choices == ["d_001", "d_002"]
    assert p.counterexamples == []
    assert p.status in ("weak", "stable")  # min_support=2 → weak
    assert p.strength == 1.0


def test_consolidate_requires_min_support():
    result = consolidate_ledger(
        _ledger(_choice("d_001", "角色因果优先于剧情便利")),
        timestamp=TS, min_support=2,
    )
    p = result.kernel.values[0]
    assert p.status == "candidate"  # 支持不足 → 不能形成稳定原则


def test_consolidate_downgrades_to_contested():
    # 反例过多 → 自动降级 contested（禁止 10d）
    ledger = _ledger(
        _choice("d_001", "角色因果优先"),
        _choice("d_002", "剧情便利优先", rejected_text="角色因果优先"),
        _choice("d_003", "剧情便利优先", rejected_text="角色因果优先"),
        _choice("d_004", "剧情便利优先", rejected_text="角色因果优先"),
    )
    result = consolidate_ledger(ledger, timestamp=TS, contested_ratio=0.5)
    p = result.kernel.values[0]
    assert p.status == "contested"
    assert len(p.counterexamples) == 3


def test_consolidate_principles_always_carry_evidence_refs():
    # 防编造：原则必须附 supporting/counterexamples（禁止 10b/c）
    result = consolidate_ledger(
        _ledger(
            _choice("d_001", "角色因果优先于剧情便利"),
            _choice("d_002", "角色因果优先于剧情便利"),
        ),
        timestamp=TS,
    )
    p = result.kernel.values[0]
    assert p.supporting_choices  # 有行为证据引用
    assert "d_001" in p.supporting_choices


# ---------------------------------------------------------------------------
# 合并既有内核（强化 / 挑战）
# ---------------------------------------------------------------------------
def test_consolidate_reinforces_existing_kernel():
    result = consolidate_ledger(
        _ledger(_choice("d_002", "角色因果优先于剧情便利")),
        kernel=_kernel_with_principle(supporting=["d_001"]),
        timestamp=TS,
    )
    p = result.kernel.values[0]
    assert p.supporting_choices == ["d_001", "d_002"]  # 去重并集
    assert p.last_reinforced == TS
    assert KEY in result.reinforced_principles


def test_consolidate_records_challenge_and_growth():
    # 既有 stable 原则遭遇反例但仍被支持 → 挑战 + Growth（允许）
    result = consolidate_ledger(
        _ledger(
            _choice("d_002", "角色因果优先于剧情便利"),
            _choice("d_003", "剧情便利优先", rejected_text="角色因果优先"),
        ),
        kernel=_kernel_with_principle(supporting=["d_001"]),
        timestamp=TS,
    )
    assert len(result.challenged_principles) == 1
    assert result.challenged_principles[0]["vocab_key"] == KEY
    assert result.challenged_principles[0]["status_before"] == "stable"
    assert result.growth_signals  # 有来由地变：反例增长但原则仍成立


def test_consolidate_without_kernel_creates_auto_kernel():
    result = consolidate_ledger(
        _ledger(_choice("d_001", "角色因果优先于剧情便利")),
        timestamp=TS,
    )
    assert isinstance(result.kernel, AuthorKernel)
    assert result.kernel.last_consolidation == TS


def test_consolidate_empty_ledger_no_principle():
    result = consolidate_ledger(_ledger(), timestamp=TS)
    assert result.kernel.all_principles() == []
    assert result.summary


# ---------------------------------------------------------------------------
# Drift / Growth 区分（§43）
# ---------------------------------------------------------------------------
def test_detect_drift_no_causal_experience():
    """原则强度骤降但该价值键本轮无新选择触及 → Drift（要防）."""
    before = _kernel_with_principle(strength=0.9)
    after = _kernel_with_principle(strength=0.4)
    signals = detect_drift(before, after, touched_keys=set())
    assert len(signals) == 1
    assert signals[0]["vocab_key"] == KEY


def test_detect_drift_silent_when_key_touched():
    """本轮有选择触及该价值 → 是因果经历，不算无因果突变."""
    before = _kernel_with_principle(strength=0.9)
    after = _kernel_with_principle(strength=0.4)
    signals = detect_drift(before, after, touched_keys={KEY})
    assert signals == []


def test_detect_drift_no_previous_kernel():
    assert detect_drift(None, _kernel_with_principle(), set()) == []


def test_detect_drift_ignores_untouched_unchanged():
    before = _kernel_with_principle(strength=0.9)
    after = _kernel_with_principle(strength=0.9)
    assert detect_drift(before, after, touched_keys=set()) == []


def test_consolidation_never_fabricates_drift():
    """Consolidation 只改被证据触及的键 → 自身永不产生 Drift 信号."""
    result = consolidate_ledger(
        _ledger(_choice("d_001", "角色因果优先于剧情便利")),
        kernel=_kernel_with_principle(strength=0.9),
        timestamp=TS,
    )
    assert result.drift_signals == []


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def test_render_consolidation_report_readable():
    result = consolidate_ledger(
        _ledger(
            _choice("d_001", "角色因果优先于剧情便利"),
            _choice("d_002", "角色因果优先于剧情便利"),
        ),
        timestamp=TS,
    )
    text = render_consolidation_report(result)
    assert "Consolidation" in text
    assert "角色因果" in text
