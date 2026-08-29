"""Work Experience 的因果节点化：把作品历史转成主题意义视图。

本模块只使用 Python 标准库。它不负责生成正文，也不调用模型；其研究目标是
验证同一情境在不同作品历史下能否得到不同的、可解释的意义。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


Record = dict[str, Any]


def _text(value: Any) -> str:
    """将夹具字段确定性地渲染成非空文本。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    return str(value)


def _event_topic(event: Mapping[str, Any]) -> str:
    return _text(event.get("topic")) or _text(event.get("plot_context"))


def _situation_topic(situation: Any) -> str:
    if isinstance(situation, Mapping):
        return _text(situation.get("topic")) or _text(situation.get("plot_context"))
    return _text(situation)


def _event_label(event: Mapping[str, Any], index: int) -> str:
    event_id = _text(event.get("event_id"))
    if event_id:
        return f"事件{event_id}"
    chapter = _text(event.get("chapter"))
    if chapter:
        return f"第{chapter}章"
    return f"第{index}段经历"


def _render_event(event: Mapping[str, Any], index: int) -> str:
    label = _event_label(event, index)
    characters = _text(event.get("characters"))
    character_clause = f"（涉及{characters}）" if characters else ""
    decision = _text(event.get("decision")) or "未记录选择"
    outcome = _text(event.get("outcome")) or "未记录后果"
    lesson = _text(event.get("lesson")) or "尚未形成明确教训"
    return (
        f"{label}{character_clause}选择“{decision}”，后果是“{outcome}”，"
        f"留下教训“{lesson}”"
    )


@dataclass(frozen=True)
class MeaningView:
    """一个主题在作品历史中的意义视图。

    ``events`` 保留与渲染相关的最小历史记录；``render`` 产生稳定文本。
    ``build_meaning_view`` 是面向调用方的字符串接口。
    """

    topic: str
    events: tuple[Record, ...]

    @classmethod
    def from_ledger(cls, ledger: "ExperienceLedger", situation: Any) -> "MeaningView":
        topic = _situation_topic(situation)
        return cls(topic=topic, events=tuple(ledger.topic_index.get(topic, ())))

    def render(self) -> str:
        topic_label = self.topic or "未命名情境"
        if not self.events:
            return (
                f"主题“{topic_label}”尚无作品经验：这本书还没有经历可供反思，"
                "因此这次意味着从当下情境开始建立自己的轨迹。"
            )

        history_text = "；".join(
            _render_event(event, index) for index, event in enumerate(self.events, start=1)
        )
        last_lesson = _text(self.events[-1].get("lesson")) or "经验尚未定型"
        return (
            f"主题“{topic_label}”的意义来自这本书经历过什么：{history_text}。"
            f"所以面对当前情境，这次意味着带着“{last_lesson}”留下的判断继续选择，"
            "而不是把它当作一条脱离作品历史的通用信息。"
        )

    @property
    def text(self) -> str:
        return self.render()

    def __str__(self) -> str:
        return self.render()


class ExperienceLedger:
    """按主题索引作品历史，并保持事件的原始顺序。"""

    def __init__(self, history: Iterable[Mapping[str, Any]] | None = None) -> None:
        self.topic_index: dict[str, list[Record]] = {}
        self.history: list[Record] = []
        if history is not None:
            self.extend(history)

    def add_event(self, event: Mapping[str, Any]) -> Record:
        if not isinstance(event, Mapping):
            raise TypeError("experience events must be mappings")
        record = dict(event)
        self.history.append(record)
        topic = _event_topic(record)
        self.topic_index.setdefault(topic, []).append(record)
        return record

    def extend(self, events: Iterable[Mapping[str, Any]]) -> "ExperienceLedger":
        for event in events:
            self.add_event(event)
        return self

    def events_for_topic(self, topic: Any) -> list[Record]:
        return list(self.topic_index.get(_text(topic), ()))

    def meaning_view(self, situation: Any) -> MeaningView:
        return MeaningView.from_ledger(self, situation)


def build_meaning_view(ledger: ExperienceLedger, situation: Any) -> str:
    """将当前情境与该主题的作品经验渲染为稳定的意义文字。"""
    if not isinstance(ledger, ExperienceLedger):
        raise TypeError("ledger must be an ExperienceLedger")
    return ledger.meaning_view(situation).render()


def selftest() -> None:
    """运行本模块的确定性验收夹具。"""
    betrayal_history = [
        {
            "event_id": "betrayal-collapse",
            "topic": "背叛",
            "chapter": 12,
            "characters": ["主角", "朋友"],
            "decision": "相信朋友",
            "outcome": "关系崩塌",
            "lesson": "不轻信",
        }
    ]
    repair_history = [
        {
            "event_id": "betrayal-repair",
            "topic": "背叛",
            "chapter": 28,
            "characters": ["主角", "朋友"],
            "decision": "给出和好机会",
            "outcome": "关系修复",
            "lesson": "信任可修复",
        }
    ]
    situation = {"plot_context": "背叛", "chapter": 40}
    collapse_view = build_meaning_view(ExperienceLedger(betrayal_history), situation)
    repair_view = build_meaning_view(ExperienceLedger(repair_history), situation)
    keyed_situation = {
        "topic": "背叛",
        "plot_context": "朋友在宴会上再次隐瞒真相",
        "chapter": 41,
    }
    keyed_view = build_meaning_view(ExperienceLedger(betrayal_history), keyed_situation)

    assert collapse_view, "collapse meaning view must be non-empty"
    assert repair_view, "repair meaning view must be non-empty"
    assert collapse_view != repair_view, "different histories must produce different views"
    assert "关系崩塌" in collapse_view and "不轻信" in collapse_view
    assert "关系修复" in repair_view and "信任可修复" in repair_view
    assert "关系崩塌" in keyed_view and "不轻信" in keyed_view
    assert "再次隐瞒真相" not in keyed_view

    ledger = ExperienceLedger(betrayal_history + repair_history)
    assert len(ledger.history) == 2
    assert len(ledger.topic_index["背叛"]) == 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="run deterministic fixtures")
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("only --selftest is supported")
    selftest()
    print("PASS: experience_ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
