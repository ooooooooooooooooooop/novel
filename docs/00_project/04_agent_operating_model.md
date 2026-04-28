# Agent Operating Model

## Purpose

This file defines how an agent should operate inside this repository during the foundation-design phase.

It is not an implementation workflow.
It is an operating model for:

- onboarding
- context loading
- task execution
- state updates
- boundary protection

---

## 1. Why This File Exists

This project is vulnerable to a specific failure mode:

- each newly opened agent can understand the project in a slightly different way
- each round can invent new terms or assumptions
- local fixes can drift away from the agreed object boundaries

The purpose of this file is to reduce that drift.

---

## 2. Current Operating Assumption

The repository is currently in the foundation-design phase.

That means the main job of an agent is:

- clarify the system
- tighten definitions
- align schemas, rules, workflows, and examples
- record decisions and current status

That does not mean implementation is permanently excluded.

It means:

- do not let implementation pressure prematurely distort the foundation
- do not optimize current work around code architecture before the conceptual layer is stable

---

## 3. Minimal Onboarding Sequence

When a new agent starts work, it should read in this order:

1. `AGENTS.md`
2. `README.md`
3. `docs/00_project/02_agent_quickstart.md`
4. `docs/00_project/03_current_status.md`
5. `docs/00_project/10_transition_planning.md`
6. `docs/00_project/11_implementation_planning_entry_pack.md`
7. `docs/00_project/05_narrative_agent_harness.md`
8. `docs/00_project/00_project_brief.md`
9. `docs/00_project/01_scope_and_boundaries.md`
10. `docs/07_decisions/03_workflow_order_decisions.md`
11. `docs/07_decisions/08_context_packaging_decisions.md`
12. `docs/07_decisions/10_ownership_matrix_decisions.md`
13. `docs/07_decisions/11_reviewreminder_escalation_matrix.md`
14. `docs/07_decisions/12_concurrent_reminder_routing_decisions.md`
15. `docs/07_decisions/13_factledger_admission_thresholds.md`

Then it should read only the workflow, schema, rule, or example files directly relevant to the assigned task.

The point is:

- first load project consensus
- then load current state
- only then load local task detail

---

## 4. Context Layers

This repository should be understood as four context layers.

### 4.1 Persistent Direction Layer

Files:

- `AGENTS.md`
- `README.md`
- `docs/00_project/00_project_brief.md`
- `docs/00_project/01_scope_and_boundaries.md`

Role:

- define what the project is
- define current phase boundaries
- define long-term direction

This layer should change slowly.

### 4.2 Fast Onboarding Layer

Files:

- `docs/00_project/02_agent_quickstart.md`
- `docs/00_project/03_current_status.md`
- this file

Role:

- let a new agent become productive quickly
- summarize current consensus and unresolved edges
- reduce repeated full-repo interpretation

This layer should be updated more often than the direction layer.

### 4.3 Decision Layer

Files:

- `docs/07_decisions/`

Role:

- record why important boundaries and workflow choices were adopted
- prevent the same argument from being reopened every round

### 4.4 Task Detail Layer

Files:

- concepts
- schemas
- rules
- workflows
- examples

Role:

- hold the actual detailed project definitions

Agents should not start here unless the task is extremely local and low risk.

---

## 5. Default Working Cycle

For most tasks, an agent should operate in the following cycle:

1. load onboarding context
2. identify the relevant object, rule, workflow, or decision boundary
3. check whether the task changes project direction, local detail, or only status
4. make the smallest coherent update
5. verify nearby files for consistency
6. update status context if the task changed project shape or consensus

This repository should prefer small coherent rounds over large uncontrolled rewrites.

---

## 6. What To Update After Different Kinds Of Work

### 6.1 If a task changes project direction

Update as needed:

- `README.md`
- `AGENTS.md`
- `docs/00_project/00_project_brief.md`
- `docs/00_project/01_scope_and_boundaries.md`
- relevant decision files

### 6.2 If a task changes workflow or schema consensus

Update as needed:

- affected workflow/schema/rule file
- matching decision file
- `docs/00_project/03_current_status.md`

### 6.3 If a task only resolves a local inconsistency

Update:

- the affected local files

Update status context only if the fix changes what future agents should assume.

---

## 7. Boundary Protection Rules

Agents should slow down when touching these areas:

- knowledge ownership
- relation ownership
- `ReviewReminder` threshold and escalation design
- `FactLedger` entry thresholds
- object conflict precedence

In these areas:

- do not silently create new ownership rules
- do not spread one local assumption across multiple files without a decision anchor
- do not upgrade a provisional pattern into project consensus without recording it

---

## 8. Anti-Drift Rules

To avoid project drift, an agent should not:

- create a new object just to hide unclear ownership
- add terms that are not tied to a problem and a field boundary
- patch one workflow while ignoring the schema or rule layer it depends on
- treat `warning` prose as equivalent to a formal issue object
- let examples become the only place where a rule exists

If a rule is important enough to guide repeated work, it should not live only in chat memory.

---

## 9. How To Use Status Compression

`docs/00_project/03_current_status.md` should be treated as the active summary, not a marketing overview.

It should answer:

- what is already stable
- what was recently aligned
- what remains fragile
- what the next reasonable work is

If a round of work changes any of those answers, update the file.

---

## 10. What This Repository Should Borrow From Agentic Engineering

The useful part is not "more agents".
The useful part is:

- externalized context
- stable onboarding order
- explicit state updates
- decision memory
- drift control

For this repository, the main bottleneck is conceptual consistency, not execution throughput.

So the operating model should optimize for:

- shared understanding
- bounded edits
- recorded decisions

before optimizing for:

- parallelism
- automation
- implementation speed

---

## 11. One-Sentence Summary

In this repository, an agent should behave less like a freeform co-writer and more like a disciplined maintainer of a shared conceptual system.
