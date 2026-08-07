"""MultiViewSelector tests — 作者性 3A/3B.

验证：Consistency Gate 硬阻断（state_ref 不匹配/坏 PlotUnit 淘汰）；Reader
代理（Interpretive Space 过度解释扣分、presence/unresolved 加分）；Style 代理
（禁忌词扣分、无档案中性）；Author 代理（Kernel 未形成中性、禁忌可否决=
Costly Taste、价值加分）；字典序选择（作者对齐 → 文风 → 读者，禁止 score=max）；
rejected/tradeoff 全量留痕（禁止 4）；全否决仍须选一；ChoiceRecord 落盘含全部
被拒候选。
"""

import pytest

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.object_state.scene_experience import SceneExperience
from src.object_state.styleprofile import StyleProfile, StyleQuantitativeStats
from src.workflow_action.author_selector import (
    author_proxy_score,
    build_choice_record,
    evaluate_candidates,
    reader_proxy_score,
    render_selection_report,
    select_candidate,
    style_proxy_score,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _scene(shift: str = "有些事放下，也放不下", states=None) -> SceneExperience:
    return SceneExperience(
        protagonist_sees="窗外檐雨成线",
        obstacles=["对手堵在门口"],
        choice_grounding="身为长子，不能退",
        outcome="他留下对峙",
        cognition_shift=shift,
        cognition_states=states,
    )


def _pu(cid: str, **overrides) -> PlotUnit:
    base = dict(
        unit_id=f"pu_{cid}",
        level="scene",
        goal="推进局势",
        participants=["c001"],
        conflict="坦白还是隐瞒",
        input_state_ref="ns_in",
        output_state_ref=f"ns_{cid}",
        hook="门外响起脚步声",
        consequences=["对方起了疑心"],
        is_effective=True,
        scene_experience=_scene(),
    )
    base.update(overrides)
    return PlotUnit(**base)


def _ns(state_id: str) -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="深夜",
        current_location="旧宅前厅",
        active_characters=["c001"],
        current_situation="对峙中",
    )


def _objects() -> list:
    """当前运行时对象：含当前 NarrativeState（input_state_ref 解析需要）."""
    return [_ns("ns_in")]


def _package(cid: str, pu: PlotUnit = None, tradeoff_hint: str = "") -> dict:
    return {
        "plotunit": pu or _pu(cid),
        "new_state": _ns(f"ns_{cid}"),
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": tradeoff_hint,
    }


def _style(*taboo) -> StyleProfile:
    return StyleProfile(
        profile_id="sp_test",
        source_text_ref="tests",
        narrative_pov="第三人称有限",
        pacing_description="克制",
        taboo_words=list(taboo),
        stats=StyleQuantitativeStats(
            total_chars=0,
            sentence_count=0,
            avg_sentence_len=0.0,
            short_sentence_ratio=0.0,
            long_sentence_ratio=0.0,
            dialogue_ratio=0.0,
            weak_adverb_density_per_1000=0.0,
            explanatory_phrase_count=0,
            dialogue_tag_density_per_1000=0.0,
            emotion_announcement_count=0,
            dash_colon_density_per_1000=0.0,
        ),
    )


def _kernel(*principles) -> AuthorKernel:
    """按类别路由六部列表（prohibition 进 prohibitions，value 进 values…）."""
    kw = dict(
        values=[],
        prohibitions=[],
        commitments=[],
        tensions=[],
        attention_biases=[],
        interpretive_biases=[],
    )
    for p in principles:
        field = {
            "value": "values",
            "prohibition": "prohibitions",
            "commitment": "commitments",
            "tension": "tensions",
            "attention_bias": "attention_biases",
            "interpretive_bias": "interpretive_biases",
        }[p.category]
        kw[field].append(p)
    return AuthorKernel(kernel_id="k", **kw)


def _principle(category: str, vocab_key: str, strength: float = 0.8, status: str = "stable") -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id=f"{category}_{vocab_key}",
        category=category,
        vocab_key=vocab_key,
        description="d",
        status=status,
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=strength,
    )


# ---------------------------------------------------------------------------
# Reader 代理（第 8 维 Interpretive Space）
# ---------------------------------------------------------------------------
def test_reader_presence_and_unresolved_bonus():
    pkg = _package("A", _pu("A", scene_experience=_scene(states=["unresolved"])))
    score, notes = reader_proxy_score(pkg)
    assert score > 0.5  # presence +0.1, unresolved +0.1
    assert any("unresolved" in n for n in notes)


def test_reader_penalizes_interpretive_overcompletion():
    pkg = _package(
        "A",
        _pu(
            "A",
            scene_experience=_scene(
                shift="他终于明白这一切都是命运的安排，彻底释然",
                states=["changed"],
            ),
        ),
    )
    score, notes = reader_proxy_score(pkg)
    assert score < 0.5
    assert any("解析式收尾" in n for n in notes)


def test_reader_penalizes_no_presence():
    pkg = {"plotunit": _pu("A", scene_experience=None), "new_state": _ns("ns_A")}
    score, notes = reader_proxy_score(pkg)
    assert score <= 0.5
    assert any("现场感弱" in n for n in notes)


def test_reader_penalizes_no_hook_no_consequences():
    pu = _pu("A", hook=None, consequences=[])
    score, notes = reader_proxy_score(_package("A", pu))
    assert score <= 0.5
    assert any("无钩子" in n for n in notes)


# ---------------------------------------------------------------------------
# Style 代理
# ---------------------------------------------------------------------------
def test_style_no_profile_neutral():
    score, notes = style_proxy_score(_package("A"), None)
    assert score == 0.5
    assert "无风格档案" in notes[0]


def test_style_taboo_penalty():
    pkg = _package("A", _pu("A", goal="他冷冷地看了对方一眼"))
    score, notes = style_proxy_score(pkg, _style("冷冷地"))
    assert score < 1.0
    assert any("禁忌词" in n for n in notes)


def test_style_clean_high_score():
    score, notes = style_proxy_score(_package("A"), _style("某个绝不出现的词"))
    assert score == 1.0
    assert any("无禁忌词" in n for n in notes)


# ---------------------------------------------------------------------------
# Author 代理（Kernel 对齐 / Costly Taste）
# ---------------------------------------------------------------------------
def test_author_no_kernel_neutral():
    score, veto, notes, conflicts = author_proxy_score(_package("A"), None)
    assert score == 0.5
    assert veto is False
    assert "kernel 未形成" in notes[0]


def test_author_prohibition_hits_and_veto():
    kernel = _kernel(
        _principle("prohibition", "no_instant_forgiveness", strength=0.8)
    )
    # 候选文本命中禁忌词（一次道歉修复）
    pu = _pu("A", conflict="对方道歉，他当场原谅，一切恢复如初")
    score, veto, notes, _ = author_proxy_score(_package("A", pu), kernel)
    assert veto is True
    assert score < 0.5


def test_author_prohibition_weak_no_veto():
    kernel = _kernel(
        _principle("prohibition", "no_instant_forgiveness", strength=0.4, status="weak")
    )
    pu = _pu("A", conflict="对方道歉，他当场原谅")
    score, veto, notes, _ = author_proxy_score(_package("A", pu), kernel)
    assert veto is False
    assert score < 0.5  # 仍扣分，但不可否决


def test_author_value_bonus():
    kernel = _kernel(
        _principle("value", "character_causality_over_plot_convenience", strength=0.8)
    )
    pu = _pu("A", conflict="角色因果优先于剧情便利：角色按自己的执念行动，哪怕让局面更糟")
    score, veto, notes, _ = author_proxy_score(_package("A", pu), kernel)
    assert veto is False
    assert score > 0.5
    assert any("价值" in n or "符合value" in n for n in notes)


# ---------------------------------------------------------------------------
# Consistency Gate（硬阻断）
# ---------------------------------------------------------------------------
def test_gate_blocks_bad_state_ref():
    # 候选 input_state_ref 与当前状态不符 → Gate 阻断
    pu = _pu("A", input_state_ref="ns_other")
    pkg = _package("A", pu)
    evals = evaluate_candidates([pkg], _objects(), current_state_ref="ns_in")
    assert evals["A"].consistency_pass is False
    assert evals["A"].consistency_issues


def test_gate_blocks_output_state_mismatch():
    pu = _pu("A", output_state_ref="ns_wrong")
    pkg = _package("A", pu)
    evals = evaluate_candidates([pkg], _objects(), current_state_ref="ns_in")
    assert evals["A"].consistency_pass is False


def test_gate_passes_valid_candidate():
    pkg = _package("A")
    evals = evaluate_candidates([pkg], _objects(), current_state_ref="ns_in")
    assert evals["A"].consistency_pass is True
    assert evals["A"].consistency_issues == []


def test_gate_reports_no_current_ref():
    pkg = _package("A")
    evals = evaluate_candidates([pkg], _objects(), current_state_ref="")
    assert evals["A"].consistency_pass is True  # 无当前 ref 时不做 input 检查


# ---------------------------------------------------------------------------
# 字典序选择（禁止 score=max）
# ---------------------------------------------------------------------------
def test_select_prefers_author_over_reader_when_kernel():
    """Costly Taste：Kernel 对齐的候选压过 Reader 最高的候选."""
    kernel = _kernel(
        _principle("value", "character_causality_over_plot_convenience", strength=0.9)
    )
    # A：Reader 最高但作者中性；B：作者强对齐
    pu_a = _pu("A", scene_experience=_scene(states=["unresolved"]))
    pu_b = _pu("B", conflict="角色因果优先于剧情便利，哪怕让局面更糟")
    packages = [_package("A", pu_a), _package("B", pu_b)]
    evals = evaluate_candidates(packages, _objects(), kernel=kernel, current_state_ref="ns_in")
    assert evals["A"].reader_score > evals["B"].reader_score  # Reader 说 A 好
    assert evals["B"].author_score > evals["A"].author_score  # Author 说 B 好
    outcome = select_candidate(packages, evals, kernel=kernel)
    assert outcome.selected_label == "B"
    assert "作者对齐" in outcome.tradeoff  # 换取作者优势


def test_select_without_kernel_uses_style_reader():
    packages = [_package("A"), _package("B")]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    outcome = select_candidate(packages, evals)
    assert outcome.selected_label in ("A", "B")


def test_select_vetoed_candidate_not_selected():
    """Reader 最高但命中作者硬禁忌 → 落选，且理由里写清楚（禁止 4）."""
    kernel = _kernel(
        _principle("prohibition", "no_instant_forgiveness", strength=0.8)
    )
    pu_a = _pu("A", conflict="对方道歉，他当场原谅，一切恢复如初")  # 命中禁忌
    pu_b = _pu("B")  # 未命中
    packages = [_package("A", pu_a), _package("B", pu_b)]
    evals = evaluate_candidates(packages, _objects(), kernel=kernel, current_state_ref="ns_in")
    outcome = select_candidate(packages, evals, kernel=kernel)
    assert outcome.selected_label == "B"
    rejected_reasons = {r["label"]: r["reason"] for r in outcome.rejected}
    assert "A" in rejected_reasons
    assert "硬禁忌否决" in rejected_reasons["A"]
    assert "作者对齐更高" in outcome.tradeoff  # Costly Taste 换取作者边界


def test_select_all_vetoed_still_selects():
    kernel = _kernel(
        _principle("prohibition", "no_instant_forgiveness", strength=0.8)
    )
    pu_a = _pu("A", conflict="对方道歉，他当场原谅")
    pu_b = _pu("B", conflict="对方道歉，他当场原谅一切")
    packages = [_package("A", pu_a), _package("B", pu_b)]
    evals = evaluate_candidates(packages, _objects(), kernel=kernel, current_state_ref="ns_in")
    outcome = select_candidate(packages, evals, kernel=kernel)
    assert outcome.all_vetoed is True
    assert outcome.selected_label in ("A", "B")  # 仍须选一
    assert "禁忌" in outcome.tradeoff


def test_select_all_fail_gate_raises():
    pu_a = _pu("A", input_state_ref="ns_wrong")
    packages = [_package("A", pu_a)]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    with pytest.raises(ValueError):
        select_candidate(packages, evals)


def test_select_gate_blocked_candidate_excluded_from_pool():
    """Gate 阻断的候选即使 Reader 最高也不能被选中（硬约束优先）."""
    pu_a = _pu("A", input_state_ref="ns_wrong")  # gate 阻断
    pu_b = _pu("B")  # gate 通过，Reader 略低
    packages = [_package("A", pu_a), _package("B", pu_b)]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    assert evals["A"].consistency_pass is False
    outcome = select_candidate(packages, evals)
    assert outcome.selected_label == "B"
    assert any(r["label"] == "A" and "Consistency Gate" in r["reason"] for r in outcome.rejected)


def test_select_kernel_cannot_override_consistency_gate():
    """6D Controlled Canary（§41）：作者 Kernel 强烈偏好的候选若被 Consistency Gate
    阻断，仍绝不能当选——gate 幸存者过滤发生在作者偏好之前，Kernel 不能推翻硬约束."""
    kernel = _kernel(
        _principle("value", "character_causality_over_plot_convenience", strength=0.9)
    )
    # A：命中作者价值（作者分高），但 input_state_ref 错 → gate 阻断
    pu_a = _pu("A", input_state_ref="ns_wrong", goal="角色因果优先，忠于人物")
    pu_b = _pu("B")  # gate 通过，作者中性
    packages = [_package("A", pu_a), _package("B", pu_b)]
    evals = evaluate_candidates(packages, _objects(), kernel=kernel, current_state_ref="ns_in")
    assert evals["A"].consistency_pass is False
    assert evals["A"].author_score > evals["B"].author_score  # 若无 gate，作者会选 A
    outcome = select_candidate(packages, evals, kernel=kernel)
    assert outcome.selected_label == "B"  # gate 优先于作者偏好
    assert any(r["label"] == "A" and "Consistency Gate" in r["reason"] for r in outcome.rejected)


def test_select_kernel_prefers_but_gate_blocked_pair():
    """Canary 对照：同一内核下，若 A 通过 gate 则作者偏好 A；阻断则落选——
    证明是 gate 在挡，不是内核中性."""
    kernel = _kernel(
        _principle("value", "character_causality_over_plot_convenience", strength=0.9)
    )
    # 对照组：A 通过 gate（input_state_ref 正确）→ 作者偏好 A
    pu_a_ok = _pu("A", goal="角色因果优先，忠于人物")
    pu_b_ok = _pu("B")
    evals_ok = evaluate_candidates(
        [_package("A", pu_a_ok), _package("B", pu_b_ok)],
        _objects(), kernel=kernel, current_state_ref="ns_in",
    )
    assert evals_ok["A"].consistency_pass is True
    assert select_candidate(
        [_package("A", pu_a_ok), _package("B", pu_b_ok)], evals_ok, kernel=kernel
    ).selected_label == "A"


# ---------------------------------------------------------------------------
# ChoiceRecord 落盘（禁止 4：含全部被拒候选）
# ---------------------------------------------------------------------------
def test_build_choice_record_includes_rejected():
    packages = [_package("A"), _package("B")]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    outcome = select_candidate(packages, evals)
    record = build_choice_record(
        packages,
        outcome,
        decision_id="d_001",
        decision_timestamp="2026-08-07T12:00:00",
        plot_context="坦白还是隐瞒",
        state_ref="ns_in",
        character_refs=["c001"],
        style_profile_id="sp_test",
    )
    assert record.selected_candidate == outcome.selected_label
    assert len(record.candidates) == 2  # 含落选候选
    assert record.candidates[0].candidate_id in ("A", "B")
    assert len(record.rejected) == 1  # 一个被拒
    assert record.rejected[0].reason  # 有理由
    assert record.tradeoff
    assert record.value_conflicts == outcome.value_conflicts


def test_build_choice_record_summary():
    packages = [_package("A")]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    outcome = select_candidate(packages, evals)
    record = build_choice_record(
        packages,
        outcome,
        decision_id="d_002",
        decision_timestamp="2026-08-07T12:00:00",
        plot_context="坦白还是隐瞒",
        state_ref="ns_in",
        character_refs=["c001"],
    )
    assert "推进局势" in record.candidates[0].summary  # goal 进 summary


def test_render_selection_report_readable():
    packages = [_package("A"), _package("B")]
    evals = evaluate_candidates(packages, _objects(), current_state_ref="ns_in")
    outcome = select_candidate(packages, evals)
    text = render_selection_report(outcome)
    assert "选中候选" in text
    assert "tradeoff" in text
    assert "多视角评估表" in text
