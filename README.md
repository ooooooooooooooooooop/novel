# Automatic Novel Narrative System

## Project

This repository is building the foundation of an automatic novel narrative system.

The long-term goal is a system that can:

- parse narrative structure
- maintain narrative state
- plan story progression
- review generated results
- support rebuilding, continuation, rewriting, and later implementation work

## Current Phase

The repository is currently in the foundation-design phase.

Current work is focused on:

- core concepts
- data models
- state transition rules
- review rules
- minimal workflows
- examples and decision logs

This does not mean the repository will never participate in implementation.
It means implementation is intentionally deferred until the conceptual layer is stable enough to support it.

## Core Objects

- `WorkSpec`
- `WorldModel`
- `CharacterModel`
- `NarrativeState`
- `PlotUnit`
- `FactLedger`
- `ForeshadowGraph`
- `ReviewIssue`

## Core Judgments

- State first, text second.
- Facts must be separated from inference.
- A `PlotUnit` is only valid if it causes meaningful state change.
- `Review` is the routing hub of the operational workflows.
- Formal `Rewrite` should be issue-driven, not feeling-driven.

## Workflow Map

- `Rebuild`: reconstruct object state from existing text
- `Review`: judge validity, classify failures, and route next action
- `Continue`: generate the next valid progression from current state
- `Rewrite`: apply minimal repair based on formal issues

## Read First

If you are a newly opened agent, read in this order:

1. `AGENTS.md`
2. `docs/00_project/02_agent_quickstart.md`
3. `docs/00_project/03_current_status.md`
4. `docs/00_project/00_project_brief.md`
5. `docs/00_project/01_scope_and_boundaries.md`
6. `docs/07_decisions/03_workflow_order_decisions.md`

## Current Repository Shape

At the moment, the repository is mainly a design and documentation workspace.
That is a current-state description, not a permanent restriction on later phases.
