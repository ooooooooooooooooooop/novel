"""AuthorKernel / AuthorPrinciple schema tests — 作者性 4B.

验证：受限价值词汇表强制映射（禁止 10 防编造第一道闸）；六部 schema；
status 五态；强度/置信度区间；supporting_choices/counterexamples 引用必填；
原则 id 生成。
"""

import pytest
from pydantic import ValidationError

from src.object_state.authorkernel import (
    VALUE_VOCAB,
    VALUE_VOCAB_KEYWORDS,
    AuthorKernel,
    AuthorPrinciple,
    principle_id_for,
    value_direction,
)


def _principle(**overrides) -> AuthorPrinciple:
    base = dict(
        principle_id="val_char_causality_001",
        category="value",
        vocab_key="character_causality_over_plot_convenience",
        description="角色因果优先于剧情便利",
        strength=0.8,
        plasticity=0.4,
        supporting_choices=["d_001", "d_002", "d_003"],
        counterexamples=["d_004"],
        first_formed_at="2026-08-07T12:00:00",
        last_reinforced="2026-08-07T12:00:00",
        last_challenged="2026-08-07T13:00:00",
        confidence=0.7,
        status="stable",
    )
    base.update(overrides)
    return AuthorPrinciple(**base)


def test_principle_roundtrip():
    p = _principle()
    assert p.status == "stable"
    assert p.vocab_key == "character_causality_over_plot_convenience"


def test_vocab_key_must_be_restricted():
    with pytest.raises(ValidationError):
        _principle(vocab_key="写得更好看")  # 不在受限词汇表 → 拒绝（禁止 10）


def test_vocab_key_must_match_category_vocab():
    # 类别限定校验在 Consolidation 层，schema 层只锁词汇表全集
    p = _principle(category="prohibition", vocab_key="no_instant_forgiveness")
    assert p.category == "prohibition"


def test_principle_extra_forbid():
    with pytest.raises(ValidationError):
        _principle(bogus=True)


def test_strength_and_confidence_in_unit_interval():
    with pytest.raises(ValidationError):
        _principle(strength=1.5)
    with pytest.raises(ValidationError):
        _principle(confidence=-0.1)


def test_principle_refs_must_be_non_blank():
    with pytest.raises(ValidationError):
        _principle(supporting_choices=[""])
    with pytest.raises(ValidationError):
        _principle(counterexamples=["  "])


def test_status_five_states():
    for state in ("candidate", "weak", "stable", "contested", "deprecated"):
        assert _principle(status=state).status == state
    with pytest.raises(ValidationError):
        _principle(status="true")  # 不是 true/false


def test_kernel_six_categories():
    k = AuthorKernel(
        kernel_id="kernel_001",
        style_profile_id="克制-官商-001",
        values=[_principle()],
        prohibitions=[
            _principle(
                principle_id="pro_no_instant_forgiveness_001",
                category="prohibition",
                vocab_key="no_instant_forgiveness",
            )
        ],
        commitments=[],
        tensions=[
            _principle(
                principle_id="ten_restraint_001",
                category="tension",
                vocab_key="restraint_vs_release",
            )
        ],
        attention_biases=[
            _principle(
                principle_id="att_power_001",
                category="attention_bias",
                vocab_key="attend_power_dynamics",
            )
        ],
        interpretive_biases=[
            _principle(
                principle_id="int_interest_001",
                category="interpretive_bias",
                vocab_key="interpret_via_interest_structure",
            )
        ],
    )
    assert len(k.all_principles()) == 5
    assert k.status == "formed"  # 含 stable 原则 → formed；只含 candidate → forming


def test_kernel_empty_by_default():
    k = AuthorKernel(kernel_id="kernel_002")
    assert k.status == "empty"
    assert k.all_principles() == []


def test_kernel_extra_forbid():
    with pytest.raises(ValidationError):
        AuthorKernel(kernel_id="k", bogus=1)


def test_principles_by_category():
    k = AuthorKernel(
        kernel_id="k",
        values=[_principle()],
        prohibitions=[_principle(principle_id="p2", category="prohibition", vocab_key="no_instant_forgiveness")],
    )
    assert len(k.principles_by_category("value")) == 1
    assert len(k.principles_by_category("prohibition")) == 1
    assert len(k.principles_by_category("tension")) == 0


def test_principle_id_generation():
    assert principle_id_for("value", "character_causality_over_plot_convenience", 1) == (
        "val_charactercausalityoverplotconvenience_001"
    )
    assert principle_id_for("prohibition", "no_instant_forgiveness", 12) == (
        "pro_noinstantforgiveness_012"
    )


def test_vocab_keywords_cover_vocab():
    for key in VALUE_VOCAB:
        assert key in VALUE_VOCAB_KEYWORDS, f"missing keywords for {key}"


# ---------------------------------------------------------------------------
# 方向判定（§23：归纳必须挖到方向层，不能只命中关键词）
# ---------------------------------------------------------------------------
KEY = "character_causality_over_plot_convenience"


def test_direction_pro_for_alignment():
    # 表达「角色因果优先」→ pro（符合价值）
    assert value_direction("角色因果优先于剧情便利", KEY) == "pro"


def test_direction_contra_for_violation():
    # 表达「剧情便利优先」→ contra（牺牲价值）——即使两者都含关键词字面
    assert value_direction("剧情便利优先于一切", KEY) == "contra"


def test_direction_none_when_untouched():
    assert value_direction("主角穿过长街", KEY) is None


def test_direction_pro_wins_when_both_present():
    # pro 与 contra 字面同时出现 → 倾向 pro（诚实标注启发式）
    assert value_direction("角色因果优先，不为剧情便利低头", KEY) == "pro"


def test_direction_forbidden_act_is_contra():
    # 禁忌行为（当场原谅）→ contra
    assert value_direction("对方道歉，他当场原谅，一切恢复如初", "no_instant_forgiveness") == "contra"
    # 拒绝禁忌 → pro
    assert value_direction("他无法原谅，伤口还在", "no_instant_forgiveness") == "pro"
