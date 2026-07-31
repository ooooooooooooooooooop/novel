"""Runtime object presence checks for staged workflows."""

from __future__ import annotations

from typing import TypeVar

from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
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
