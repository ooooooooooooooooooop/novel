"""S3（54 计划）长程因果防线对抗样本集可重跑测试.

验证 causal_adversarial_suite：
- 5 类攻击样本齐全（每类正例 + 负控）
- run_suite 全过：正例全部检出（erased 必须 blocking），负控零检出
- 幂等：同组对象两次运行 issue 一致
"""
from __future__ import annotations

from src.domain_layer.causal_adversarial_suite import (
    ADVERSARIAL_CASES,
    ATTACK_CLASSES,
    run_suite,
)


def test_suite_covers_all_five_attack_classes() -> None:
    classes = {c.attack_class for c in ADVERSARIAL_CASES}
    assert classes == set(ATTACK_CLASSES)
    assert len(ATTACK_CLASSES) == 5


def test_every_class_has_positive_and_negative_control() -> None:
    for cls in ATTACK_CLASSES:
        cases = [c for c in ADVERSARIAL_CASES if c.attack_class == cls]
        assert any(c.expect == "block" for c in cases), f"{cls} 缺正例"
        assert any(c.expect == "pass" for c in cases), f"{cls} 缺负控"


def test_suite_run_all_pass() -> None:
    report = run_suite()
    assert report["suite_pass"], (
        f"对抗集未全过：{report['ok_cases']}/{report['total_cases']} "
        f"失败样本 {[r['case_id'] for r in report['rows'] if not r['ok']]}"
    )


def test_erased_positive_is_blocking() -> None:
    report = run_suite()
    erased_pos = next(r for r in report["rows"]
                     if r["attack_class"] == "erased" and r["expect"] == "block")
    assert erased_pos["blocking"] is True, "现实抹除正例必须是 blocking 级（提交前门禁阻断）"


def test_all_positive_detected_and_negatives_clean() -> None:
    report = run_suite()
    for cls, status in report["per_class"].items():
        assert status["positive_detected"], f"{cls} 正例未被检出"
        assert status["negative_clean"], f"{cls} 负控误报"


def test_idempotent_across_all_cases() -> None:
    report = run_suite()
    assert all(r["idempotent"] for r in report["rows"])


def test_suite_reproducible_twice() -> None:
    a = run_suite()
    b = run_suite()
    assert a["suite_pass"] == b["suite_pass"] == True
    assert a["ok_cases"] == b["ok_cases"]
