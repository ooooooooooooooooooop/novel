"""Experience Ablation：验证作品经验是否是决策的因果节点。

A 组让 ExperienceLedger 在事件之间累积；B 组始终接收空 ledger。两组使用同一
事件序列和同一确定性 decision_fn，因此分叉只可能来自作品经验的可见差异。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from src.research_agency.experience_ledger import ExperienceLedger


DecisionFn = Callable[[Any, ExperienceLedger], str]


@dataclass(frozen=True)
class AblationReport:
    """两组选择的差异报告。"""

    decisions_a: list[str]
    decisions_b: list[str]
    divergence_count: int
    divergence_rate: float
    verdict: str

    @classmethod
    def from_decisions(
        cls, decisions_a: Iterable[str], decisions_b: Iterable[str]
    ) -> "AblationReport":
        a = [str(decision) for decision in decisions_a]
        b = [str(decision) for decision in decisions_b]
        if len(a) != len(b):
            raise ValueError("decision sequences must have equal length")
        divergence_count = sum(left != right for left, right in zip(a, b))
        divergence_rate = divergence_count / len(a) if a else 0.0
        verdict = (
            "EXPERIENCE_IS_CAUSAL_NODE"
            if divergence_rate > 0
            else "EXPERIENCE_IS_DECORATION"
        )
        return cls(a, b, divergence_count, divergence_rate, verdict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decisions_a": list(self.decisions_a),
            "decisions_b": list(self.decisions_b),
            "divergence_count": self.divergence_count,
            "divergence_rate": self.divergence_rate,
            "verdict": self.verdict,
        }

    to_dict = as_dict

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


def _event_list(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise TypeError("events must be mappings")
        result.append(dict(event))
    return result


def _situation(event: Mapping[str, Any]) -> Any:
    if "situation" in event:
        return event["situation"]
    return {
        key: value
        for key, value in event.items()
        if key not in {"decision", "outcome", "lesson"}
    }


def run_ablation(
    events: Iterable[Mapping[str, Any]],
    decision_fn: DecisionFn,
    *,
    with_experience: bool,
) -> list[str]:
    """逐事件运行一组消融实验并返回选择序列。

    A 组在当前决策完成后才把该事件写入 ledger，表示在线决策只能使用此前
    已发生的作品经验；B 组从不写入，因而每一步都看到空历史。
    """
    if not callable(decision_fn):
        raise TypeError("decision_fn must be callable")

    event_list = _event_list(events)
    ledger = ExperienceLedger()
    decisions: list[str] = []

    for event in event_list:
        choice = str(decision_fn(_situation(event), ledger))
        decisions.append(choice)
        if with_experience:
            experience_event = dict(event)
            experience_event["decision"] = choice
            ledger.add_event(experience_event)

    return decisions


def build_ablation_report(
    events: Iterable[Mapping[str, Any]], decision_fn: DecisionFn
) -> AblationReport:
    """运行 A/B 两组并生成确定性报告。"""
    event_list = _event_list(events)
    decisions_a = run_ablation(event_list, decision_fn, with_experience=True)
    decisions_b = run_ablation(event_list, decision_fn, with_experience=False)
    return AblationReport.from_decisions(decisions_a, decisions_b)


# Descriptive aliases for small research notebooks and hidden callers.
run_ablation_experiment = build_ablation_report
compare_experience = build_ablation_report


def selftest() -> None:
    """运行本模块的确定性验收夹具。"""
    events = [
        {
            "event_id": f"event-{index}",
            "topic": "背叛",
            "chapter": index,
            "decision": "保留关系",
            "outcome": "关系继续发展",
            "lesson": "信任可修复",
        }
        for index in range(1, 11)
    ]

    def deterministic_decision(situation: Any, ledger: ExperienceLedger) -> str:
        if not ledger.history:
            return "默认制造冲突"
        return "依据作品经验修复关系"

    report = build_ablation_report(events, deterministic_decision)
    assert len(report.decisions_a) == 10
    assert len(report.decisions_b) == 10
    assert report.divergence_rate > 0
    assert report.verdict == "EXPERIENCE_IS_CAUSAL_NODE"

    first_a = run_ablation(events, deterministic_decision, with_experience=True)
    second_a = run_ablation(events, deterministic_decision, with_experience=True)
    repeat_report = AblationReport.from_decisions(first_a, second_a)
    assert repeat_report.divergence_count == 0
    assert repeat_report.divergence_rate == 0
    assert first_a == second_a

    explicit_situation = {
        "topic": "背叛",
        "plot_context": "显式传入的当前事实",
    }
    seen_situations: list[Any] = []
    overwrite_events = [
        {
            "event_id": "overwrite-1",
            "topic": "背叛",
            "chapter": 1,
            "decision": "旧标签",
            "outcome": "未来后果",
            "lesson": "未来教训",
        },
        {
            "event_id": "overwrite-2",
            "topic": "背叛",
            "chapter": 2,
            "situation": explicit_situation,
            "decision": "另一个旧标签",
            "outcome": "另一个未来后果",
            "lesson": "另一个未来教训",
        },
    ]

    def inspect_inputs(situation: Any, ledger: ExperienceLedger) -> str:
        seen_situations.append(situation)
        if ledger.history:
            assert ledger.history[-1]["decision"] == "实际选择-1"
        return f"实际选择-{len(seen_situations)}"

    overwrite_decisions = run_ablation(
        overwrite_events, inspect_inputs, with_experience=True
    )
    assert overwrite_decisions == ["实际选择-1", "实际选择-2"]
    assert "decision" not in seen_situations[0]
    assert "outcome" not in seen_situations[0]
    assert "lesson" not in seen_situations[0]
    assert seen_situations[0]["event_id"] == "overwrite-1"
    assert seen_situations[0]["topic"] == "背叛"
    assert seen_situations[0]["chapter"] == 1
    assert seen_situations[1] is explicit_situation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run deterministic fixtures")
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("only --selftest is supported")
    selftest()
    print("PASS: experience_ablation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
