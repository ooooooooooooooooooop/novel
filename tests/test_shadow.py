"""Shadow Mode tests — 作者性 6C（§40）.

验证：生产 Selector 出 A、Author Selector 出影子 B（B 不进正文）；分叉原因分类
（author_veto / author_preference / baseline）；无 kernel 基线；空 packages 零
成本；台账落盘/读回/分叉率；B 绝不进正文（production_label 不被影子改写）。
"""

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.object_state.scene_experience import SceneExperience
from src.workflow_action.shadow import (
    ShadowComparison,
    ShadowLedger,
    load_shadow_ledger,
    record_shadow_comparison,
    render_shadow_comparison,
    run_shadow_selection,
    save_shadow_ledger,
)

TS = "2026-08-07T12:00:00"


def _scene() -> SceneExperience:
    return SceneExperience(
        protagonist_sees="窗外檐雨成线",
        obstacles=[],
        choice_grounding="身为长子，不能退",
        outcome="他留下对峙",
        cognition_shift="有些事放下，也放不下",
    )


def _pu(cid: str, goal: str = "推进局势") -> PlotUnit:
    return PlotUnit(
        unit_id=f"pu_{cid}",
        level="scene",
        goal=goal,
        participants=["c001"],
        conflict="坦白还是隐瞒",
        input_state_ref="ns_in",
        output_state_ref=f"ns_{cid}",
        hook="门外响起脚步声",
        consequences=["对方起了疑心"],
        is_effective=True,
        scene_experience=_scene(),
    )


def _ns(state_id: str) -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="深夜",
        current_location="旧宅前厅",
        active_characters=["c001"],
        current_situation="对峙中",
    )


def _objects():
    return [_ns("ns_in")]


def _package(cid: str, pu: PlotUnit = None) -> dict:
    return {
        "plotunit": pu or _pu(cid),
        "new_state": _ns(f"ns_{cid}"),
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": "",
    }


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


# ---------------------------------------------------------------------------
# 分叉与分类
# ---------------------------------------------------------------------------
def test_shadow_diverges_on_author_preference():
    """生产选 Reader 更高的 A；kernel 偏好 B（作者对齐）→ 影子 B，author_preference."""
    kernel = _kernel(_value_principle("character_causality_over_plot_convenience"))
    packages = [
        _package("A", _pu("A", goal="推进局势")),                    # reader 高，作者中性
        _package("B", _pu("B", goal="角色因果优先，忠于人物")),        # 作者对齐
    ]
    cmp = run_shadow_selection(
        packages, _objects(),
        production_label="A", decision_id="d1", timestamp=TS,
        state_ref="ns_in", kernel=kernel, current_state_ref="ns_in",
    )
    assert cmp.divergent is True
    assert cmp.shadow_label == "B"
    assert cmp.production_label == "A"
    assert cmp.divergence_kind == "author_preference"
    assert cmp.kernel_formed is True


def test_shadow_author_veto_kind():
    """生产选中被作者硬禁忌否决的候选 → 分叉分类 author_veto."""
    kernel = _kernel(_prohibition_principle("no_instant_forgiveness"))
    packages = [
        _package("A", _pu("A", goal="对方道歉，他当场原谅")),   # 犯禁忌 → 作者 veto
        _package("B", _pu("B", goal="他不肯原谅，伤口还在")),    # 回避禁忌
    ]
    cmp = run_shadow_selection(
        packages, _objects(),
        production_label="A", decision_id="d2", timestamp=TS,
        state_ref="ns_in", kernel=kernel, current_state_ref="ns_in",
    )
    assert cmp.divergent is True
    assert cmp.divergence_kind == "author_veto"
    assert cmp.shadow_label == "B"


def test_shadow_aligned_when_kernel_agrees():
    """生产选 A，kernel 也偏好 A → 一致."""
    kernel = _kernel(_value_principle("character_causality_over_plot_convenience"))
    packages = [
        _package("A", _pu("A", goal="角色因果优先，忠于人物")),
        _package("B", _pu("B", goal="推进局势")),
    ]
    cmp = run_shadow_selection(
        packages, _objects(),
        production_label="A", decision_id="d3", timestamp=TS,
        state_ref="ns_in", kernel=kernel, current_state_ref="ns_in",
    )
    assert cmp.divergent is False
    assert cmp.divergence_kind == "aligned"
    assert cmp.shadow_label == "A"


def test_shadow_no_kernel_baseline():
    """无 kernel → 基线分叉（style/reader 维度），诚实标注 kernel_formed=False."""
    packages = [
        _package("A"),
        _package("B"),
    ]
    cmp = run_shadow_selection(
        packages, _objects(),
        production_label="B", decision_id="d4", timestamp=TS,
        state_ref="ns_in", current_state_ref="ns_in",
    )
    assert cmp.divergent is True
    assert cmp.kernel_formed is False
    assert cmp.divergence_kind == "baseline"


def test_shadow_empty_packages_no_op():
    """空 packages → 返回 None（主流程 no-op，零成本）."""
    assert run_shadow_selection(
        [], _objects(), production_label="A", decision_id="d", timestamp=TS
    ) is None


def test_shadow_b_never_enters_prose():
    """B 不进正文：production_label 恒等于传入的生产结果，影子不改写输出."""
    kernel = _kernel(_value_principle("character_causality_over_plot_convenience"))
    packages = [
        _package("A", _pu("A", goal="推进局势")),
        _package("B", _pu("B", goal="角色因果优先，忠于人物")),
    ]
    cmp = run_shadow_selection(
        packages, _objects(),
        production_label="A", decision_id="d5", timestamp=TS,
        state_ref="ns_in", kernel=kernel, current_state_ref="ns_in",
    )
    assert cmp.production_label == "A"   # 生产输出不变
    assert cmp.shadow_label != cmp.production_label  # 影子只是记录


# ---------------------------------------------------------------------------
# 台账 sidecar
# ---------------------------------------------------------------------------
def test_shadow_ledger_roundtrip(tmp_path):
    ledger = ShadowLedger()
    record_shadow_comparison(ledger, ShadowComparison(
        decision_id="d1", timestamp=TS, state_ref="ns_in",
        production_label="A", shadow_label="B", divergent=True,
        divergence_kind="author_preference",
        shadow_reasons=["作者对齐更高"], production_reasons=[],
        shadow_tradeoff="放弃 X 换 Y", kernel_formed=True,
    ))
    record_shadow_comparison(ledger, ShadowComparison(
        decision_id="d2", timestamp=TS, state_ref="ns_in",
        production_label="A", shadow_label="A", divergent=False,
        divergence_kind="aligned", kernel_formed=True,
    ))
    assert ledger.divergence_rate == 0.5

    path = tmp_path / "shadow" / "shadow_ledger.json"
    save_shadow_ledger(path, ledger)
    loaded = load_shadow_ledger(path)
    assert loaded is not None
    assert len(loaded.comparisons) == 2
    assert loaded.comparisons[0].divergence_kind == "author_preference"


def test_shadow_ledger_missing_returns_none(tmp_path):
    assert load_shadow_ledger(tmp_path / "nope.json") is None


def test_render_shadow_comparison_readable():
    cmp = ShadowComparison(
        decision_id="d1", timestamp=TS, state_ref="ns_in",
        production_label="A", shadow_label="B", divergent=True,
        divergence_kind="author_preference",
        shadow_reasons=["作者对齐更高"], production_reasons=[],
        shadow_tradeoff="放弃 X 换 Y", kernel_formed=True,
    )
    text = render_shadow_comparison(cmp)
    assert "DIVERGE" in text
    assert "A" in text and "B" in text
