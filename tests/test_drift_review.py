"""Author Drift Review tests — 作者性 6E（§42-43）.

验证：aligned / active_break（有记录理由 → KernelChallenge）/ drift（无记录理由，
只出信号不自动 Rewrite）；kernel 未形成 → aligned；pro 方向不冲突；KernelChallenge
→ 反例 ChoiceRecord → 下次 Consolidation 作为 counterexample（§43 Growth 闭环）；
台账 roundtrip。
"""

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.choicerecord import ChoiceLedgerEntry
from src.workflow_action.consolidation import consolidate_ledger
from src.workflow_action.drift_review import (
    ChallengeLedger,
    KernelChallenge,
    challenge_to_choice,
    challenges_to_choices,
    load_challenge_ledger,
    record_challenge,
    review_author_drift,
    save_challenge_ledger,
)

TS = "2026-08-07T12:00:00"
KEY = "character_causality_over_plot_convenience"
KEY_J = "no_instant_forgiveness"


def _value_principle(vocab_key: str, strength: float = 0.9) -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id=f"val_{vocab_key}",
        category="value",
        vocab_key=vocab_key,
        description="d",
        status="stable",
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=strength,
    )


def _prohibition_principle(vocab_key: str, strength: float = 0.8) -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id=f"pro_{vocab_key}",
        category="prohibition",
        vocab_key=vocab_key,
        description="d",
        status="stable",
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=strength,
    )


def _kernel(*principles) -> AuthorKernel:
    kw = dict(
        values=[], prohibitions=[], commitments=[], tensions=[],
        attention_biases=[], interpretive_biases=[],
    )
    for p in principles:
        field = {
            "value": "values", "prohibition": "prohibitions",
            "commitment": "commitments", "tension": "tensions",
            "attention_bias": "attention_biases",
            "interpretive_bias": "interpretive_biases",
        }[p.category]
        kw[field].append(p)
    return AuthorKernel(kernel_id="k", **kw)


def _kernel_value() -> AuthorKernel:
    return _kernel(_value_principle(KEY))


def _kernel_prohibition() -> AuthorKernel:
    return _kernel(_prohibition_principle(KEY_J))


# ---------------------------------------------------------------------------
# 判定：aligned / active_break / drift
# ---------------------------------------------------------------------------
def test_aligned_when_no_conflict():
    kernel = _kernel_value()
    r = review_author_drift(kernel, "作者选择了「角色因果优先」", decision_id="d1")
    assert r.verdict == "aligned"
    assert r.challenge is None
    assert r.principle is None


def test_aligned_when_pro_direction():
    """符合/回避原则（pro）不冲突."""
    kernel = _kernel_prohibition()
    r = review_author_drift(kernel, "作者选择了「不肯原谅」", decision_id="d2")
    assert r.verdict == "aligned"


def test_aligned_when_kernel_unformed():
    """kernel 未形成（无原则可漂移）→ aligned."""
    r = review_author_drift(None, "作者选择了「剧情便利优先」", decision_id="d3")
    assert r.verdict == "aligned"
    assert "kernel 未形成" in r.reason


def test_drift_when_contra_without_reason():
    """冲突稳定原则且无记录理由 → drift（只出信号，不自动 Rewrite）."""
    kernel = _kernel_value()
    r = review_author_drift(kernel, "作者选择了「剧情便利优先」", decision_id="d4")
    assert r.verdict == "drift"
    assert r.principle == KEY
    assert r.direction == "contra"
    assert r.tradeoff_present is False
    assert r.challenge is None  # 不产 KernelChallenge——不是主动突破


def test_active_break_with_recorded_reason():
    """冲突稳定原则但有记录理由 → active_break，产出 KernelChallenge."""
    kernel = _kernel_value()
    r = review_author_drift(
        kernel, "作者选择了「剧情便利优先」",
        tradeoff="为整卷节奏，牺牲本章人物一致性",
        decision_id="d5",
    )
    assert r.verdict == "active_break"
    assert r.tradeoff_present is True
    assert r.challenge is not None
    assert r.challenge.vocab_key == KEY
    assert r.challenge.decision_id == "d5"
    assert r.challenge.status == "open"
    assert "主动突破" in r.reason


def test_active_break_on_prohibition():
    """prohibition 原则同样：犯禁忌但有理由 → active_break."""
    kernel = _kernel_prohibition()
    r = review_author_drift(
        kernel, "作者选择了「当场原谅」",
        tradeoff="作者有意打破『不原谅』禁忌，探索和解主题",
        decision_id="d6",
    )
    assert r.verdict == "active_break"
    assert r.challenge.vocab_key == KEY_J


def test_first_contra_principle_wins():
    """多原则按序检查，命中第一个 contra 即返回."""
    kernel = _kernel(
        _value_principle(KEY),
        _value_principle("consequence_visible", strength=0.7),
    )
    r = review_author_drift(kernel, "作者选择了「剧情便利优先」", decision_id="d7")
    assert r.principle == KEY  # 顺序：先建的先检查


# ---------------------------------------------------------------------------
# §43 Growth 闭环：KernelChallenge → 反例 → 下次 Consolidation
# ---------------------------------------------------------------------------
def test_challenge_to_choice_consolidates_as_counterexample():
    """active_break 的 challenge → contra ChoiceRecord → 并入被挑战原则的反例，
    触发 challenged_principles + growth 信号（不是死账）."""
    kernel = _kernel_value()
    r = review_author_drift(
        kernel, "作者选择了「剧情便利优先」",
        tradeoff="为节奏牺牲人物一致性",
        decision_id="d_break",
    )
    assert r.verdict == "active_break"
    choice = challenge_to_choice(r.challenge)
    assert choice.decision_id == "d_break"
    assert choice.value_conflicts == [KEY]
    assert choice.tradeoff == "为节奏牺牲人物一致性"

    # 下次 Consolidation 把这条反例并进被挑战原则
    res = consolidate_ledger(
        ChoiceLedgerEntry(choices=[choice]), kernel=kernel, timestamp=TS
    )
    assert any(c["vocab_key"] == KEY for c in res.challenged_principles)
    growth = res.growth_signals
    assert growth, "growth 信号不应为空"
    # 反例已并入 counterexamples
    k = res.kernel
    p = next(p for p in k.all_principles() if p.vocab_key == KEY)
    assert p.counterexamples == ["d_break"]


def test_challenges_to_choices_batch():
    kernel = _kernel_value()
    r1 = review_author_drift(
        kernel, "作者选择了「剧情便利优先」", tradeoff="t1", decision_id="c1"
    )
    r2 = review_author_drift(
        kernel, "作者选择了「剧情便利优先」", tradeoff="t2", decision_id="c2"
    )
    choices = challenges_to_choices([r1.challenge, r2.challenge])
    assert [c.decision_id for c in choices] == ["c1", "c2"]


# ---------------------------------------------------------------------------
# 台账 sidecar
# ---------------------------------------------------------------------------
def test_challenge_ledger_roundtrip(tmp_path):
    ledger = ChallengeLedger()
    record_challenge(ledger, KernelChallenge(
        challenge_id="ch_d5", decision_id="d5", vocab_key=KEY,
        category="value", direction="contra", timestamp=TS,
        reason="为节奏牺牲人物一致性",
    ))
    record_challenge(ledger, KernelChallenge(
        challenge_id="ch_x", decision_id="x", vocab_key=KEY,
        category="value", direction="contra", timestamp=TS,
        reason="r", status="absorbed",
    ))
    assert len(ledger.open_challenges) == 1

    path = tmp_path / "drift" / "challenge_ledger.json"
    save_challenge_ledger(path, ledger)
    loaded = load_challenge_ledger(path)
    assert loaded is not None
    assert len(loaded.challenges) == 2
    assert loaded.open_challenges[0].challenge_id == "ch_d5"


def test_challenge_ledger_missing_returns_none(tmp_path):
    assert load_challenge_ledger(tmp_path / "nope.json") is None


def test_drift_review_does_not_rewrite():
    """6E 不是自动 Rewrite：drift 只出信号，selected_text 原样保留."""
    kernel = _kernel_value()
    text = "作者选择了「剧情便利优先」"
    r = review_author_drift(kernel, text, decision_id="d9")
    assert r.verdict == "drift"
    # 没有任何改写动作——返回值只携带判定与理由
    assert r.challenge is None
    assert r.reason
