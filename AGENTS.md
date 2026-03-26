# AGENTS.md

## Project
Automatic Novel Narrative System

## Current Phase
Foundation design only. Do not rush into implementation.

## Primary Goal
Build the conceptual foundation of a novel system that can:
- parse narrative structure
- maintain narrative state
- plan story progression
- review generated results
- support future rebuilding, continuation, and rewriting workflows

## Current Scope
At this stage, focus on:
1. core concepts
2. data models
3. state transition rules
4. review rules
5. minimal workflows
6. examples and decision logs

## Out of Scope for Now
Do not optimize for:
- full implementation
- model selection
- deployment
- long-form automatic completion
- imitation of a specific living author
- seamless continuation of arbitrary existing novels
- publication-grade prose quality

## Working Principles
- State first, text second.
- Facts must be separated from inference.
- Narrative units must be evaluated by state change.
- Reviewability is more important than polish.
- Prefer clear structure over premature complexity.
- Every generated narrative unit should update state and memory.
- Avoid vague abstractions that cannot be tested with examples.

## Core Objects
The system is built around these objects:
- WorkSpec
- WorldModel
- CharacterModel
- NarrativeState
- PlotUnit
- FactLedger
- ForeshadowGraph
- ReviewIssue

## Required Design Direction
When drafting new files or refining existing ones:
- define what each object is
- define what it is not
- define what problem it solves
- define how it relates to other objects
- define which fields are hard facts, inferred values, or runtime state

## Review Priorities
When evaluating any narrative design, prioritize:
1. fact consistency
2. character consistency
3. world legality
4. effective progression
5. promise / foreshadow tracking

## PlotUnit Rule
A PlotUnit is only valid if it causes meaningful state change.
If a unit does not change state, it should be treated as non-effective progression.

## State Transition Formula
Input State + Character Decision + World Constraint + Conflict Pressure = Event = Output State

## Expected Output Style
When writing docs for this repo:
- be concise
- be explicit
- prefer bullet structure when it reduces ambiguity
- define terms before using them
- separate concepts, schemas, rules, and workflows
- include small examples when needed

## File Priorities
If new work begins, prioritize these files first:
- 00_project/00_project_brief.md
- 00_project/01_scope_and_boundaries.md
- 01_concepts/00_glossary.md
- 01_concepts/05_plotunit.md
- 02_data_models/09_field_rules.md
- 03_rules/01_state_transition_rules.md
- 03_rules/07_review_rules.md
- 05_examples/07_mock_project_case.md

## Decision Policy
If uncertain between elegance and clarity, choose clarity.
If uncertain between more features and tighter boundaries, choose tighter boundaries.
If uncertain between prose discussion and structured definition, choose structured definition.