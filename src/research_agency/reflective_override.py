"""Reflective Override：对默认吸引子执行确定性的二阶欲望检查。

一阶选择是“最自然的处理方式”；二阶检查追问作品是否认可这个默认答案。
本模块只使用标准库，并且不依赖仓库内既有业务模块。
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from typing import Any



def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    return str(value)


def _event_topic(event: Mapping[str, Any]) -> str:
    return _text(event.get("topic")) or _text(event.get("plot_context"))


def _topic_from(value: Any) -> str:
    if isinstance(value, Mapping):
        return _text(value.get("topic")) or _text(value.get("plot_context"))
    return _text(value)


def _history(source: Any) -> list[dict[str, Any]]:
    if source is None:
        return []
    if hasattr(source, "history"):
        source = getattr(source, "history")
    if isinstance(source, Mapping):
        raise TypeError("history must be an iterable of event mappings")
    result: list[dict[str, Any]] = []
    for event in source:
        if not isinstance(event, Mapping):
            raise TypeError("history events must be mappings")
        result.append(dict(event))
    return result


class DefaultAttractorDetector:
    """检测同一主题下连续重复的处理方式。"""

    def __init__(self, history: Any = None, *, min_run: int = 3) -> None:
        if min_run < 1:
            raise ValueError("min_run must be positive")
        self.min_run = min_run
        self.history: list[dict[str, Any]] = []
        self.attractors: dict[str, list[str]] = {}
        if history is not None:
            self.fit(history)

    def fit(self, history: Any) -> "DefaultAttractorDetector":
        self.history = _history(history)
        self.attractors = self.detect(self.history)
        return self

    def detect(self, history: Any = None) -> dict[str, list[str]]:
        """返回 ``{topic: [default_decision, ...]}``，排序保证确定性。"""
        events = self.history if history is None else _history(history)
        found: dict[str, set[str]] = {}
        previous_topic = None
        previous_decision = None
        run_length = 0

        for event in events:
            topic = _event_topic(event)
            decision = _text(event.get("decision"))
            if topic == previous_topic and decision == previous_decision:
                run_length += 1
            else:
                previous_topic = topic
                previous_decision = decision
                run_length = 1
            if run_length >= self.min_run:
                found.setdefault(topic, set()).add(decision)

        return {topic: sorted(decisions) for topic, decisions in sorted(found.items())}

    def is_default_attractor(self, topic: Any, decision: Any) -> bool:
        decision_text = _text(decision)
        topic_text = _text(topic)
        if topic_text:
            return decision_text in self.attractors.get(topic_text, ())
        return any(decision_text in decisions for decisions in self.attractors.values())

    def longest_run(self, topic: Any, decision: Any) -> int:
        topic_text = _text(topic)
        decision_text = _text(decision)
        longest = current = 0
        for event in self.history:
            if _event_topic(event) == topic_text and _text(event.get("decision")) == decision_text:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        return longest

    def default_decisions(self, topic: Any = None) -> list[str]:
        if topic is None or not _text(topic):
            decisions = {decision for values in self.attractors.values() for decision in values}
        else:
            decisions = set(self.attractors.get(_text(topic), ()))
        return sorted(decisions)

    # A descriptive alias makes the detector convenient for direct experiments.
    detect_default_attractors = detect


class ReflectiveOverride:
    """对候选方案执行二阶 reflective endorsement。"""

    def __init__(
        self,
        history: Any = None,
        *,
        detector: DefaultAttractorDetector | None = None,
        topic: Any = None,
        min_run: int = 3,
    ) -> None:
        if detector is not None:
            self.detector = detector
        else:
            self.detector = DefaultAttractorDetector(history, min_run=min_run)
        self.topic = _text(topic)

    def _resolve_topic(self, candidate: Mapping[str, Any], situation: Any = None) -> str:
        candidate_topic = _topic_from(candidate)
        if candidate_topic:
            return candidate_topic
        situation_topic = _topic_from(situation)
        if situation_topic:
            return situation_topic
        if self.topic:
            return self.topic
        topics = sorted(self.detector.attractors)
        if len(topics) == 1:
            return topics[0]
        return ""

    def check(self, candidate: Mapping[str, Any], situation: Any = None) -> dict[str, Any]:
        if not isinstance(candidate, Mapping):
            raise TypeError("candidate must be a mapping")
        candidate_id = candidate.get("candidate_id")
        decision = _text(candidate.get("decision"))
        topic = self._resolve_topic(candidate, situation)
        is_default = self.detector.is_default_attractor(topic, decision)
        trajectory_conflict = bool(
            candidate.get("character_trajectory_conflict")
            or candidate.get("character_fidelity_violation")
        )
        reasons: list[str] = []

        if is_default:
            run = self.detector.longest_run(topic, decision)
            reasons.extend(
                [
                    f"主题“{topic or '未指定'}”下“{decision}”形成连续默认吸引子（最长连续{run}次）",
                    "一阶上它最自然，但二阶检查不认可再次掉入同一套路",
                    "应优先寻找更属于当前作品历史的处理方式",
                ]
            )
        if trajectory_conflict:
            reasons.append("候选破坏人物既有变化轨迹，违反人物忠实性，因此需要二阶否决")

        if is_default or trajectory_conflict:
            verdict = "override"
        else:
            reasons = [
                f"“{decision}”不是主题“{topic or '未指定'}”的默认吸引子",
                "当前候选没有触发连续同类处理或人物轨迹冲突的反思否决条件",
                "二阶检查认可这次非常规或尚未固化的选择",
            ]
            verdict = "endorse"

        return {
            "candidate_id": candidate_id,
            "is_default_attractor": is_default,
            "override_verdict": verdict,
            "reasons": reasons,
        }

    evaluate = check
    review = check

    def __call__(self, candidate: Mapping[str, Any], situation: Any = None) -> dict[str, Any]:
        return self.check(candidate, situation)


def selftest() -> None:
    """运行本模块的确定性验收夹具。"""
    history = [
        {"event_id": "a", "topic": "背叛", "decision": "立即报复"},
        {"event_id": "b", "topic": "背叛", "decision": "立即报复"},
        {"event_id": "c", "topic": "背叛", "decision": "立即报复"},
        {"event_id": "d", "topic": "背叛", "decision": "等待证据"},
    ]
    override = ReflectiveOverride(history)
    default_result = override.check(
        {"candidate_id": "candidate-default", "topic": "背叛", "decision": "立即报复"}
    )
    unusual_result = override.check(
        {"candidate_id": "candidate-unusual", "topic": "背叛", "decision": "先修复关系"}
    )
    trajectory_result = override.check(
        {
            "candidate_id": "candidate-trajectory-conflict",
            "topic": "背叛",
            "decision": "先修复关系",
            "character_trajectory_conflict": True,
        }
    )
    fidelity_result = override.check(
        {
            "candidate_id": "candidate-fidelity-conflict",
            "topic": "背叛",
            "decision": "先修复关系",
            "character_fidelity_violation": True,
        }
    )

    assert default_result == {
        "candidate_id": "candidate-default",
        "is_default_attractor": True,
        "override_verdict": "override",
        "reasons": default_result["reasons"],
    }
    assert default_result["override_verdict"] == "override"
    assert default_result["is_default_attractor"] is True
    assert unusual_result["override_verdict"] == "endorse"
    assert unusual_result["is_default_attractor"] is False
    assert trajectory_result["is_default_attractor"] is False
    assert trajectory_result["override_verdict"] == "override"
    assert any("破坏人物既有变化轨迹" in reason for reason in trajectory_result["reasons"])
    assert fidelity_result["override_verdict"] == "override"
    assert any("人物忠实性" in reason for reason in fidelity_result["reasons"])
    assert len(default_result["reasons"]) >= 1

    detector = DefaultAttractorDetector(history)
    assert detector.default_decisions("背叛") == ["立即报复"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run deterministic fixtures")
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("only --selftest is supported")
    selftest()
    print("PASS: reflective_override")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
