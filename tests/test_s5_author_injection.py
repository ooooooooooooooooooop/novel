"""S5（54 计划 §S5）作者先验生成注入实证测试.

锁住 verify_author_injection_effect 的确定性判据：
- OFF/kernel 未形成 → 空串（零成本）
- ON → 注入段含【作者选择结构】/【作者选择史】
- 同一状态点 ON ≠ OFF；重跑稳定
- 注入文本确定性来源：段落只由 kernel/选择史渲染（无正文、无来源名）
"""
from __future__ import annotations

from scripts.verify_author_injection_effect import verify_effect


def test_off_zero_cost_when_kernel_absent() -> None:
    assert verify_effect()["off_zero_cost"] is True, "kernel 未形成必须零成本（空串）"


def test_on_injection_nonempty() -> None:
    report = verify_effect()
    assert report["on_nonempty"] is True, "注入 ON 必须非空"


def test_on_contains_both_sections() -> None:
    report = verify_effect()
    assert report["on_has_kernel_section"] is True, "缺【作者选择结构】段"
    assert report["on_has_memory_section"] is True, "缺【作者选择史】段"


def test_on_differs_from_off_at_same_point() -> None:
    report = verify_effect()
    assert report["on_differs_from_off"] is True, "同一状态点 ON/OFF 必须可测差异"


def test_on_stable_across_runs() -> None:
    assert verify_effect()["on_stable_across_runs"] is True, "注入渲染必须稳定可复现"


def test_injection_content_is_principle_driven() -> None:
    text = verify_effect()["on_text"]
    # 注入内容来自 kernel 原则渲染（vocab 描述或原则描述），而非凭空文本
    assert "信任" in text, "注入内容必须携带作者价值结构（信任主题）"


def test_injection_has_no_corpus_privacy_leak() -> None:
    text = verify_effect()["on_text"]
    for forbidden in ("alpha_book", "beta_book", "碑下", "chapters"):
        assert forbidden not in text, f"注入段不得泄漏语料来源（含 {forbidden}）"
