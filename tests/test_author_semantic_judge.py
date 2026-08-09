"""Semantic Author Judge tests — Kernel→Selection 因果集成最小修复.

验证（Frozen Candidate Selection Gate 的代码层锁定）：
1. `author_semantic_score` 用 judge 的逐原则语义方向算分（不依赖关键词字面命中）；
2. `evaluate_candidates(author_judge=...)` 在**冻结候选**上，不同 kernel 产生
   系统性可解释分叉（Selection 真因果）；
3. 零成本契约：kernel 未形成 → 不调用 judge，返回中性 0.5；
4. 硬禁忌通过语义方向仍可否决（Costly Taste 机制）；
5. 关键字代理（author_proxy_score）是缺省 fallback，向后兼容。
"""

import pytest

from src.object_state.authorkernel import (
    AuthorKernel,
    AuthorPrinciple,
    VALUE_VOCAB_DESCRIPTIONS,
)
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.author_selector import (
    AuthorJudge,
    author_semantic_score,
    evaluate_candidates,
    select_candidate,
)


def _pu(cid: str, goal: str, conflict: str = "冲突") -> PlotUnit:
    return PlotUnit(
        unit_id=f"pu_{cid}",
        level="scene",
        goal=goal,
        participants=["c001"],
        conflict=conflict,
        input_state_ref="ns_in",
        output_state_ref=f"ns_{cid}",
        hook="门外脚步声",
        consequences=["局面变化"],
        is_effective=True,
    )


def _pkg(cid: str, goal: str) -> dict:
    return {
        "plotunit": _pu(cid, goal),
        "new_state": NarrativeState(
            state_id=f"ns_{cid}", current_time="夜", current_location="青云州",
            current_situation="当前局势",
        ),
        "new_facts": [],
        "confidence_gaps": [],
    }


def _principle(category: str, vocab_key: str, strength: float = 1.0, status: str = "stable") -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id=f"{category}_{vocab_key}",
        category=category,
        vocab_key=vocab_key,
        description=VALUE_VOCAB_DESCRIPTIONS.get(vocab_key, vocab_key),
        status=status,
        strength=strength,
        supporting_choices=["d_001"],
        first_formed_at="2026-08-09T00:00:00",
    )


def _kernel(values=(), prohibitions=()) -> AuthorKernel:
    return AuthorKernel(
        kernel_id="k_test",
        values=list(values),
        prohibitions=list(prohibitions),
    )


class FakeJudge:
    """确定性测试 judge：候选文本含 '因果' 就判对应原则 pro，含 '便利' 判 contra."""

    def __init__(self, vocab_key: str, direction_map: dict[str, dict[str, str]]):
        self._map = direction_map  # {candidate_id: {vocab_key: direction}}

    def judge_candidate(self, kernel, package, candidate_text, context=""):
        return self._map.get(package["plotunit"].unit_id, {})


# ---------------------------------------------------------------------------
# 1. author_semantic_score 用语义方向算分（无 kernel 中性）
# ---------------------------------------------------------------------------
def test_semantic_score_neutral_without_kernel():
    k = _kernel()
    pkg = _pkg("A", "某个推进")
    score, veto, notes, conflicts = author_semantic_score(pkg, k, judge=FakeJudge("x", {}))
    assert score == 0.5
    assert veto is False
    assert "kernel 未形成" in notes[0]


def test_semantic_score_reflects_directions():
    k = _kernel(values=[_principle("value", "character_causality_over_plot_convenience")])
    # candidate A 被判 pro（+0.2*1.0），B 未命中（0.5）
    judge = FakeJudge("character_causality_over_plot_convenience", {
        "pu_A": {"character_causality_over_plot_convenience": "pro"},
    })
    score_a, veto_a, notes_a, _ = author_semantic_score(_pkg("A", "忠于人物的推进"), k, judge=judge)
    score_b, veto_b, _, _ = author_semantic_score(_pkg("B", "随便推进"), k, judge=judge)
    assert score_a == pytest.approx(0.7)
    assert score_b == 0.5
    assert veto_a is False


def test_semantic_score_veto_on_stable_prohibition():
    k = _kernel(prohibitions=[_principle("prohibition", "no_unresolved_then_ignore")])
    judge = FakeJudge("no_unresolved_then_ignore", {
        "pu_A": {"no_unresolved_then_ignore": "contra"},
    })
    score, veto, notes, _ = author_semantic_score(
        _pkg("A", "悬而不决"), k, judge=judge
    )
    assert veto is True
    assert score < 0.5


# ---------------------------------------------------------------------------
# 2. 冻结候选 + 不同 kernel → 系统性分叉（Selection 因果）
# ---------------------------------------------------------------------------
def _frozen_decision():
    # 同一决策两个冻结候选：A=剧情便利，B=忠于人物因果
    return [
        _pkg("A", "剧情需要主角立即坦白，强行推进信任线"),
        _pkg("B", "主角出于自己的执念隐瞒，按人物一贯的活法走"),
    ]


def test_frozen_candidates_diverge_by_kernel():
    packages = _frozen_decision()
    objects = [p["new_state"] for p in packages] + [
        NarrativeState(state_id="ns_in", current_time="夜", current_location="地",
                       current_situation="局势")
    ]

    kernel_causal = _kernel(values=[_principle("value", "character_causality_over_plot_convenience")])
    kernel_closure = _kernel(prohibitions=[_principle("prohibition", "no_unresolved_then_ignore")])

    judge_causal = FakeJudge("character_causality_over_plot_convenience", {
        "pu_A": {"character_causality_over_plot_convenience": "contra"},
        "pu_B": {"character_causality_over_plot_convenience": "pro"},
    })
    judge_closure = FakeJudge("no_unresolved_then_ignore", {
        "pu_A": {"no_unresolved_then_ignore": "pro"},
        "pu_B": {"no_unresolved_then_ignore": "contra"},
    })

    ev_a = evaluate_candidates(packages, objects, kernel=kernel_causal,
                               current_state_ref="ns_in", author_judge=judge_causal)
    sel_a = select_candidate(packages, ev_a, kernel=kernel_causal).selected_label
    ev_b = evaluate_candidates(packages, objects, kernel=kernel_closure,
                               current_state_ref="ns_in", author_judge=judge_closure)
    sel_b = select_candidate(packages, ev_b, kernel=kernel_closure).selected_label

    assert sel_a == "B"   # 角色因果作者 → 忠于人物的隐瞒
    assert sel_b == "A"   # 接住未决作者 → 立即坦白


def test_keyword_proxy_still_default_fallback():
    """author_judge 缺省 None → 走 author_proxy_score（向后兼容，零成本契约不变）."""
    packages = [
        _pkg("A", "主角按部就班继续调查"),
        _pkg("B", "主角在雨夜独自前往渡口"),
    ]
    objects = [p["new_state"] for p in packages] + [
        NarrativeState(state_id="ns_in", current_time="夜", current_location="地",
                       current_situation="局势")
    ]
    kernel = _kernel(values=[_principle("value", "character_causality_over_plot_convenience")])
    ev = evaluate_candidates(packages, objects, kernel=kernel, current_state_ref="ns_in")
    # 候选文本不含受限词汇字面 → 关键词代理对两者都中性 → 平局选 A
    assert ev["A"].author_score == 0.5
    assert ev["B"].author_score == 0.5
