# Open Threads

## Status

This file tracks project-level open threads: real, recognized issues
that are not currently being actioned.

Each thread is recorded so it does not silently disappear.

None of these threads is a current blocker.
None has been promoted to a `ReviewIssue`, a planning task, or a
`.taskflow/active/` entry.

When a thread becomes actionable, it is moved out of this file into the
appropriate planning artifact (decision file, taskflow folder, example
counterexample, etc.).

---

## Format

Each thread has:

- a stable identifier (`OT-NNN`)
- a short title
- current status: `recognized`, `parked`, `in-progress`, or `closed`
- the source where the thread was first surfaced
- a one-paragraph description
- why it is parked (if applicable)
- conditions for promotion to actionable

---

## OT-001: Decision review mechanism

- Status: `closed`
- Source: dialogue during the production of
  `docs/00_project/22_usage_oriented_roadmap.md` v2 revision

### Description

The repository accumulates `adopted` decisions in
`docs/07_decisions/`. As the project evolves and new perspectives are
introduced (such as the usage-oriented framing in document 22), older
decisions can come into tension with new framing.

The first observed instance is `DEC-20260326-22` ("当前不把'正文生成'独立成第一优先 workflow"),
which carries an implicit current-phase priority (compose deferred)
that conflicts at face value with the long-term goal of three-flow
equal-priority. Document 22 v2 resolves this specific case by
introducing a time-dimension priority layer in section 1.1.a, but the
underlying pattern is general.

### Why parked

A decision review mechanism is itself a meta-decision. Designing it
prematurely risks formalizing a process that may not match how
revisions actually arise in practice. At present only one tension has
been observed, which is not enough to pattern-match.

### Promotion conditions

Promote OT-001 from `recognized` to `in-progress` when any of the
following occurs:

- a second adopted decision is observed to conflict with project
  direction without an obvious local resolution
- a planning artifact is forced to silently work around an adopted
  decision rather than reference it
- an agent or contributor proposes modifying an `adopted` decision and
  the project lacks a documented procedure for doing so

### Next step on promotion

Open a `.taskflow/active/decision_review_mechanism/` folder and draft
a short procedural document. Candidate location for the result:
`docs/07_decisions/00_decision_log.md` extension, since 00 already
defines the decision-log structure.

---

## OT-002: Agent quickstart drift

- Status: `closed`
- Source: dialogue during the production of
  `docs/00_project/22_usage_oriented_roadmap.md` v1 (initial draft)

### Description

`docs/00_project/02_agent_quickstart.md` lags behind
`docs/00_project/03_current_status.md`:

- section 2 ("Current Phase") still describes the project as
  `foundation design`, while status describes
  `implementation_planning_in_progress`
- section 7 transition judgment still says
  `ready_for_transition_planning`, while status has moved past
  transition planning into implementation planning
- section 8 ("Read Next") does not list documents 16 through 21 (the
  implementation-planning artifacts that have already been produced)
- and now does not list document 22 either

A newly opened agent reading the README's onboarding chain hits
quickstart first, gets a phase description that contradicts current
state, and may infer the wrong context.

### Why parked

This is independent of the usage-oriented roadmap work. Folding the
quickstart sync into the document 22 task would have mixed two
unrelated cleanup tasks into one revision, making both harder to audit.
The user explicitly chose to keep them separate.

### Promotion conditions

Promote OT-002 from `recognized` to `in-progress` when any of the
following occurs:

- a new agent onboarding session produces visible confusion traceable
  to the drift
- another planning round adds yet another quickstart-relevant document
  (e.g. document 24+), making the gap larger
- the user signals readiness to do the cleanup pass

### Next step on promotion

Update `02_agent_quickstart.md` sections 2, 7, 8 to match
`03_current_status.md` current-state language. Add documents 16-22 to
the Read Next list. Decide whether to also reorganize section 7's
"Current Fragile Boundaries" subsection (it still references the
specific tracks 1/2/3 work that was the recent foundation focus, but
implementation planning has its own concerns that may belong here).

Closed: 2026-05-21. Resolution: `docs/00_project/02_agent_quickstart.md`
synced to match `docs/00_project/03_current_status.md` current-state
language. Sections 2, 7, 8 updated. Documents 16-22 added to Read Next
list.

---

## OT-003: A3 schema-stage validation

- Status: `closed`
- Source: document 22 v2, Phase A task A3

### Description

Document 22's task A3 proposes reserving external input hook fields
on `WorkSpec`:

- `external_market_snapshot`
- `target_platform`
- `audience_profile`

These were proposed without verifying against `02_data_models/`
schema files. It is possible that:

- equivalent fields already exist under different names
- the schema already has a partial reservation
- the schema's existing field set explicitly forbids this kind of
  external reference

Before closure, A3 was tagged `unverified` in document 22 section 10.

### Why parked

A3 was parked because compose was deferred per DEC-22 and the proposed
fields had no active consumer at the time.

### Promotion conditions

Historical promotion conditions were:

- A1 or A2 work surfaces a `WorkSpec` field question that touches the
  same schema area
- the project decides to begin compose-flow work earlier than DEC-22
  currently implies
- a Phase B B1 (Domain Layer) decision requires `WorkSpec` to carry
  domain knowledge references

### Next step on promotion

Completed verification against `src/object_state/workspec.py`.

Closed: 2026-05-28. Resolution: WorkSpec 已采纳 `audience`（必填）与
`platform`（可选）字段，覆盖 A3 提出的主要意图。
`external_market_snapshot` 字段当前无消费者（compose 流仍 deferred per
DEC-22），推迟至 compose 流真正激活时与消费逻辑一并设计，避免预占字段产生空字段污染。
Phase A 残留 A3 至此实质完成。

---

## How To Add A New Open Thread

When a future session surfaces a real-but-not-current-blocker issue:

1. Pick the next `OT-NNN` identifier (next is OT-004).
2. Add a section using the format above: identifier, status, source,
   description, why-parked, promotion-conditions, next-step.
3. Status starts as `recognized`.
4. If unsure whether something belongs here or elsewhere, prefer here:
   easier to move out than to recover from oblivion.

## How To Close A Thread

When a thread is resolved:

1. Change status to `closed`.
2. Add a final paragraph noting where the resolution lives (decision
   file path, planning artifact path, etc.).
3. Do not delete closed threads — keep them as a small audit trail of
   how project-level concerns were handled.
