"""Runtime object presence checks for staged workflows."""

from __future__ import annotations

from typing import TypeVar

from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    ReaderExpectationLedger,
    WorkSpec,
    WorldModel,
)


T = TypeVar("T")


def _type_name(object_type: type) -> str:
    return object_type.__name__


def require_single_object(objects: list, object_type: type[T]) -> T:
    matches = [obj for obj in objects if isinstance(obj, object_type)]
    name = _type_name(object_type)
    if not matches:
        raise ValueError(f"missing required runtime object: {name}")
    if len(matches) > 1:
        raise ValueError(f"multiple required runtime objects: {name}")
    return matches[0]


def require_latest_object(objects: list, object_type: type[T]) -> T:
    matches = [obj for obj in objects if isinstance(obj, object_type)]
    name = _type_name(object_type)
    if not matches:
        raise ValueError(f"missing required runtime object: {name}")
    return matches[-1]


def require_continue_runtime_state(
    objects: list,
) -> tuple[
    WorkSpec,
    WorldModel,
    NarrativeState,
    list[CharacterModel],
    FactLedger,
    ForeshadowGraph,
]:
    workspec = require_single_object(objects, WorkSpec)
    worldmodel = require_single_object(objects, WorldModel)
    narrative_state = require_latest_object(objects, NarrativeState)
    facts = require_single_object(objects, FactLedger)
    foreshadows = require_single_object(objects, ForeshadowGraph)
    characters = [obj for obj in objects if isinstance(obj, CharacterModel)]
    return workspec, worldmodel, narrative_state, characters, facts, foreshadows


def find_reader_expectation_ledger(
    objects: list,
) -> ReaderExpectationLedger | None:
    """取最新持久化的 ReaderExpectationLedger；旧状态没有则返回 None.

    dim7：ledger 是跨章 persistent reader model（stable_memory 层），
    旧提交状态不含该对象属正常——调用方按需新建。
    """
    matches = [o for o in objects if isinstance(o, ReaderExpectationLedger)]
    return matches[-1] if matches else None
