"""S5（54 计划 §S5）作者先验生成注入实证——同一状态点 ON/OFF 注入差异可测.

装置验证（确定性层，S6 真实 provider 双生成盲评的前奏）：
- OFF / kernel 未形成 → build_author_prompt_context 返回空串（零成本，prompt 字节不变）
- ON（kernel + 选择史在场）→ 注入段非空，含【作者选择结构】/【作者选择史】
- 同一 decision_context 下 ON ≠ OFF（差异可测且可归因于注入）
- 重跑一致（注入渲染稳定）

用法：python scripts/verify_author_injection_effect.py
隐私：装置只用中性合成数据，不接触任何真实小说工作区。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.workflow_action.author_selection import build_author_prompt_context

DECISION_CONTEXT = "他当众坦白，选择以持续行动换取信任（对峙中，需要选择如何推进）"


def _principle() -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id="val_trust_earned",
        category="value",
        vocab_key="trust_earned_over_time",
        description="信任必须随时间与代价挣得，不能因一次道歉即刻恢复",
        status="stable",
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=0.8,
    )


def _kernel() -> AuthorKernel:
    p = _principle()
    kw = dict(
        values=[p], prohibitions=[], commitments=[], tensions=[],
        attention_biases=[], interpretive_biases=[],
    )
    return AuthorKernel(kernel_id="k_s5", **kw)


def _ledger() -> ChoiceLedgerEntry:
    def _candidate(cid: str, summary: str) -> CandidateRecord:
        return CandidateRecord(
            candidate_id=cid, summary=summary,
            plotunit={"unit_id": f"pu_{cid}", "level": "scene"},
            new_state_ref=f"ns_{cid}",
        )

    def _choice(did: str, context: str, selected: str, tradeoff: str) -> ChoiceRecord:
        return ChoiceRecord(
            decision_id=did,
            decision_timestamp="2026-08-24T00:00:00+00:00",
            plot_context=context,
            state_ref="ns_in",
            candidates=[_candidate("A", "当众摊牌"), _candidate("C", "即刻原谅")],
            selected_candidate=selected,
            rejected=[RejectedRecord(candidate_id="C", reason="人物当前不会这样")],
            tradeoff=tradeoff,
            value_conflicts=["trust_earned_over_time"],
        )

    return ChoiceLedgerEntry(choices=[
        _choice("d_001", "他当众摊牌，换来背叛者的坦诚", "A", "信任以风险换取真实"),
        _choice("d_002", "他再次原谅，代价被一笔带过", "C", "信任被廉价消费"),
    ])


def _write_workspace(root: Path) -> None:
    (root / "author_kernel.json").write_text(
        _kernel().model_dump_json(indent=2), encoding="utf-8")
    (root / "choice_ledger.json").write_text(
        _ledger().model_dump_json(indent=2), encoding="utf-8")


def verify_effect() -> dict:
    """跑 ON/OFF 注入实证，返回结构化报告."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # OFF：工作区无 kernel / 无选择史
        off = build_author_prompt_context(root, DECISION_CONTEXT)
        # ON：kernel + 选择史在场
        _write_workspace(root)
        on_1 = build_author_prompt_context(root, DECISION_CONTEXT)
        on_2 = build_author_prompt_context(root, DECISION_CONTEXT)  # 重跑稳定
        return {
            "off_zero_cost": off == "",
            "on_nonempty": on_1 != "",
            "on_has_kernel_section": "【作者选择结构】" in on_1,
            "on_has_memory_section": "【作者选择史】" in on_1,
            "on_differs_from_off": on_1 != off,
            "on_stable_across_runs": on_1 == on_2,
            "on_text": on_1,
        }


def main(argv: list[str] | None = None) -> int:
    report = verify_effect()
    checks = {
        "OFF 零成本（kernel 未形成 → 空串）": report["off_zero_cost"],
        "ON 注入非空": report["on_nonempty"],
        "ON 含【作者选择结构】段": report["on_has_kernel_section"],
        "ON 含【作者选择史】段": report["on_has_memory_section"],
        "同一状态点 ON ≠ OFF（差异可测）": report["on_differs_from_off"],
        "重跑稳定": report["on_stable_across_runs"],
    }
    ok = all(checks.values())
    print("S5 作者先验生成注入实证（确定性层）")
    for label, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if report["on_nonempty"]:
        print(f"  注入段预览: {report['on_text'][:80]}...")
    print(f"SUITE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
