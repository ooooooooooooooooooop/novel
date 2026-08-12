"""Pure A1 decision precedence; no filesystem or provider side effects."""

from __future__ import annotations

from typing import Literal

from src.object_state.autonomous import AutonomousDecision


ReaderRoute = Literal["pass", "rewrite", "block", "manual"]


def resolve_autonomous_decision(
    *,
    provider_error: str | None,
    viability_verdict: Literal["continue", "needs_premise", "stop"],
    premise_candidates_remaining: int,
    required_axes_armed: bool,
    reader_route: ReaderRoute,
    hard_violation: str | None,
    long_horizon_block: str | None = None,
    candidates_remaining: int,
    budget_available: bool,
    accepted_candidate_id: str | None,
) -> AutonomousDecision:
    if premise_candidates_remaining < 0 or candidates_remaining < 0:
        raise ValueError("candidate counts must be non-negative")

    if provider_error:
        return _terminal("execution_failed", f"provider/schema/evidence error: {provider_error}")
    if viability_verdict == "stop":
        return _terminal("narrative_stopped", "ContinuationViability=stop")
    if viability_verdict == "needs_premise":
        if premise_candidates_remaining == 0:
            return _terminal("premise_exhausted", "no viable premise candidate remains")
        return AutonomousDecision(
            route="search_premise",
            reasons=("ContinuationViability=needs_premise",),
            generation_allowed=True,
            commit_allowed=False,
            frame_advance_allowed=False,
        )
    if not required_axes_armed:
        return _terminal("evaluation_incomplete", "required evaluation axis is unarmed")
    if reader_route == "manual":
        return _terminal("evaluation_incomplete", "manual route is illegal in A1")
    if not budget_available:
        return _terminal("quality_exhausted", "frozen budget cannot fund another candidate")
    if hard_violation or reader_route in {"block", "rewrite"}:
        if candidates_remaining == 0:
            return _terminal("quality_exhausted", "all prose candidates failed quality gates")
        reason = hard_violation or f"reader route={reader_route}"
        return AutonomousDecision(
            route="reject_candidate",
            reasons=(reason,),
            generation_allowed=True,
            commit_allowed=False,
            frame_advance_allowed=False,
        )
    # 长程对账漂移（design §4：seam/contract drift > long-horizon block > quality
    # disagreement）——检查点正文重建与滚动摘要对账失败即停，不降级为候选偏好比较。
    if long_horizon_block:
        return _terminal(
            "quality_exhausted", f"long-horizon block: {long_horizon_block}"
        )
    if accepted_candidate_id:
        return AutonomousDecision(
            route="accepted",
            reasons=("candidate passed hard gates and deterministic selection",),
            accepted_candidate_id=accepted_candidate_id,
            generation_allowed=False,
            commit_allowed=True,
            frame_advance_allowed=True,
        )
    if candidates_remaining == 0:
        return _terminal("quality_exhausted", "no accepted prose candidate remains")
    return AutonomousDecision(
        route="continue_generation",
        reasons=("additional candidate evaluation required",),
        generation_allowed=True,
        commit_allowed=False,
        frame_advance_allowed=False,
    )


def _terminal(route: str, reason: str) -> AutonomousDecision:
    return AutonomousDecision(
        route=route,
        reasons=(reason,),
        generation_allowed=False,
        commit_allowed=False,
        frame_advance_allowed=False,
    )
