# Usage-Oriented Roadmap (Proposal)

## Status

- Status: `proposal`
- Self-classification: not yet `accepted`, not yet `reference`
- Reason: this roadmap was produced across planning sessions and contains
  unverified judgments and undecided items. It is recorded here so future
  work can verify, revise, or upgrade it. It is not yet project-level
  consensus.
- Revision: v2. Major revision after compatibility verification against
  documents 11-21, decisions 01/02/03/05/06, `01_rebuild_workflow.md`,
  and `08_failure_types.md`. Specific revisions are noted inline.

## Purpose

This file proposes a usage-oriented roadmap for the repository.

It exists because the existing planning chain (documents 11 through 21)
optimizes for internal coherence of the design, not for the goal of
putting the system into real use across **audit / extend / compose**
flows for novels.

It does not replace any existing planning document.
It does not modify any of the eight core objects.
It does not modify any of the four core workflows.
It does not loosen Track 1, Track 2, or Track 3 locks.

It only proposes a forward-looking phase map that lets the existing
foundation be carried into real usage without distorting it.

---

## 1. Core Reframing

### 1.1 Goal Restatement

The implicit driver of the current implementation-planning phase is real
usage of the narrative system across three flows:

- **audit**: take an existing novel, reconstruct its state, and review it
- **extend**: take partial state and partial text, continue from there
- **compose**: start from a `WorkSpec` and accumulate state from zero

These three flows share the same eight objects and four workflows.
They differ only in entry path, trajectory, and exit condition.

### 1.1.a Time Dimensions Of Priority

Two priority dimensions exist and must not be conflated:

- **Long-term goal level**: the three flows are equal-priority. The
  system is not considered fully usable until all three are supported.
- **Current-phase level**: per `DEC-20260326-22` ("当前不把'正文生成'独立成第一优先 workflow"),
  compose is deferred until audit/extend close the basic loop. Current
  phase priority is therefore: **audit > extend > compose**.

This roadmap respects both dimensions. Phase A and Phase B work-item
priorities follow the current-phase ordering. Phase exit conditions
and ultimate Phase C scope follow the long-term goal level.

`DEC-20260326-22` is `adopted` and is not being revised. This roadmap
adapts to it rather than overriding it.

### 1.2 Three Flows As Entry Modes, Not New Workflows

This is the central judgment of this roadmap.

The three flows are not new workflows.
They are **entry modes** for the existing four workflows.

| Flow | Entry path | Trajectory | Exit |
|---|---|---|---|
| audit | full text → `Rebuild` | `Rebuild` → `Review` (dominant) → optional `Rewrite` | `Rebuild` output package + issue list with severity routing |
| extend | partial state + partial text → `Rebuild` | `Rebuild` → `Continue` → `Review` (loop) | continued text with synchronized state and updated `Rebuild` output package |
| compose | `WorkSpec` only | `Continue` → `Review` (loop), state grows from empty | a complete narrative that satisfies `WorkSpec` |

Implication for `Rebuild`:
the existing `Rebuild` workflow document already covers audit and extend
input cases under different scenario names (section 2.1: "从已完结小说重建",
section 2.2: "从断更小说重建"). It does **not** cover the compose case,
because compose by definition has no existing text for `Rebuild` to
process. The gap is therefore not "Rebuild semantics are unclear" but
"compose has no entry workflow defined yet, and the three flows lack
unified terminology".

### 1.2.a Reuse Of Existing Rebuild Document Concepts

`01_rebuild_workflow.md` already provides several primitives this
roadmap can reuse without inventing new concepts:

- **Input completeness levels** (section 3.2): A 完整文本型 / B 半完整资料型 / C 零散碎片型.
  These align directly with audit (typically A), extend (typically B), and
  compose-initialization (typically C).
- **Input context packages** (section 3.4): A 源材料包 / B 稳定约束候选包 /
  C 当前断点包 / D 置信度包. These specify what `Rebuild` must be able to
  read at entry.
- **Output state packages** (section 4.4): A 静态记忆包 / B 可运行状态包 /
  C 修复与不确定性包. These specify what each entry mode produces as exit.
- **Repeated recovery additional requirements** (section 4.4 sub-clause):
  hard-fact constraints / current working pressures / pending inferences
  must be kept split. This is the operational form of Track 1 lock.
- **Result classification** (section 7): 完整重建 / 结构性重建 /
  初始化式重建 / 失败重建. These map naturally onto audit / extend
  variants and provide ready-made stress-test variant axes.

Future Phase A and Phase B documents should reference these primitives
rather than redefine them.

### 1.3 Coverage Estimate

[Speculation, partially verified] Current coverage of the three flows
is uneven:

| Flow | Long-term coverage | Current-phase priority | Likely gap |
|---|---|---|---|
| audit | mid | high (current focus) | unified terminology missing; domain-quality failure types missing; `ReviewIssue` type set incomplete |
| extend | better | high | Track 1/2/3 already protect this flow; weak point is robustness when input text is imperfect |
| compose | low | low (deferred per DEC-22) | `Rebuild` does not cover compose entry; `WorkSpec` expressiveness limited; long-range orchestration has no explicit object-layer owner; style consistency mechanism not formalized |

[Verified via DEC-16, DEC-17] The repository has indeed treated `Rebuild` →
`Continue` (extend's core path) as the canonical loop, and `Review` as
the routing hub.

[Speculation] The repository has been implicitly optimizing the `extend`
flow. `audit` is now becoming explicit; `compose` is intentionally
deferred.

[Verified via batch-1 reading] `01_rebuild_workflow.md` covers audit and
extend input cases under scenario language. The compose case is not
covered there.

[Verified via batch-2 reading] `08_failure_types.md` defines 15 failure
types in 4 layers. Generative-indicia / AI-output-fingerprint as a
failure mode is **not** explicitly covered, although `redundancy` and
`style_drift` partially overlap.


---

## 2. Three-Phase Roadmap

The roadmap is split into Phase A, Phase B, and Phase C.

The boundary between phases is **dependency**, not calendar time.
A phase begins only when its inputs are available, and a phase ends
when its exit conditions are satisfied. No phase claims a date.

```
Phase A  Usage-oriented boundary alignment   (target layer)
   |
Phase B  Domain layer + end-to-end validation (landing layer)
   |
Phase C  Implementation slice + deployment    (execution layer)
```

A blocks B. B blocks C. Skipping ahead is rejected because:

- starting B without A means the domain layer is built on a flow model
  that has not been usage-aligned
- starting C without B means an implementation slice will be chosen
  without seeing real usage stress points

Within each phase, the **current-phase priority** ordering applies:
audit > extend > compose. Compose-specific work items are explicitly
marked as deferrable.

---

## 3. Phase A: Usage-Oriented Boundary Alignment

### 3.1 Goal

Make the existing design explicitly recognize the usage goal.
Fix structural blind spots without adding new objects, new workflows,
or weakened locks.

### 3.2 Tasks

#### A1. Make three flow entry modes explicit

[Verified via batch-1] `01_rebuild_workflow.md` already covers audit and
extend input cases under scenario language (section 2.1, 2.2). What is
missing is unified terminology and a compose-entry definition.

A1 is therefore **not** a new workflow document. A1 is two smaller
actions:

1. **Extend `01_rebuild_workflow.md` with a compose-mode section**.
   Compose has no existing text, so `Rebuild` cannot process source
   material in the usual sense. The compose-mode section should define
   what `Rebuild` does when input is `WorkSpec`-only: produce a stub
   `NarrativeState` and stub object packages from `WorkSpec` constraints,
   without claiming any reconstructed history. This is closer to
   "initialization" than to "reconstruction" but should still be
   represented in the same workflow for consistency.

2. **Build a usage-mode terminology index**. Candidate location:
   `04_workflows/06_usage_modes.md` (new file, terminology index only,
   not a redefinition of workflow semantics). It should:
   - name the three modes (audit / extend / compose)
   - point each mode to the relevant sections in
     `01_rebuild_workflow.md`, `02_review_workflow.md`,
     `03_continue_workflow.md`, `04_rewrite_workflow.md`
   - state explicitly that Track 1, Track 2, Track 3 are unchanged
     across all three modes
   - reuse `Rebuild` document's existing primitives (input completeness
     levels, input/output context packages, result classification)
     rather than redefine them

Not in scope of A1:
- adding new workflows
- modifying the semantic of existing four workflows
- redefining `Rebuild`'s scenario coverage; the existing scenarios
  already work, only need re-tagging with mode names

#### A2. Add Failure Type for generative indicia

[Verified via batch-2] `08_failure_types.md` defines 15 failure types
in 4 layers. Generative indicia (AI-output fingerprint: structural
clichés, over-balanced phrasing, dense modifier stacking,
template-shaped emotional outbursts) is not explicitly covered.
`redundancy` (functional repetition) and `style_drift` (drift from
configured narrative style) partially overlap with generative indicia
but do not subsume it.

A2 is therefore: **add a 16th failure type to `08_failure_types.md`**,
not a separate "10.7" outside the existing taxonomy.

Specific shape:

- Candidate name: `generative_indicia`
- Position: layer 4 (表达与表面层 / expressive surface), alongside
  `redundancy` and `style_drift`
- Default severity (per DEC-20260326-43): `low / medium`
- Default blocking class: 通常不阻断 (typically non-blocking)
- Default issue routing (per DEC-20260326-15, DEC-20260326-42): prefer
  `ReviewReminder` over `ReviewIssue`. Promote to formal issue only when
  the indicia are repeated across `PlotUnit`s or are dense enough to
  break style memory.
- Edge with `style_drift`: `style_drift` measures **relative** deviation
  from configured style; `generative_indicia` measures **absolute** AI
  signature. They can co-occur. They are not the same axis.
- Edge with `redundancy`: `redundancy` measures functional overlap
  (the unit could be merged with neighbors); `generative_indicia`
  measures language-surface signature regardless of functional
  contribution.

Not in scope of A2:
- detection method
- repair method
- specific signature dictionary
These belong to Phase B.

#### A3. Reserve external input hooks on `WorkSpec`

[Verified 2026-05-28] Specific gaps in `WorkSpec` schema were checked
against `src/object_state/workspec.py`. `audience` and `platform` cover the
current hook need; `external_market_snapshot` is deferred until compose-flow
activation and a concrete consumer exists.

The compose flow requires access to real-world input such as target platform,
audience profile, and external market snapshots.
Current schema verification found that `audience` and `platform` cover the
active WorkSpec-level need; external market snapshots remain application-layer
inputs deferred until compose-flow activation.

[Speculation] If `WorkSpec` cannot reference external context at all,
`compose` becomes structurally impossible to use, regardless of how
strong the rest of the system is.

Resolution: do not add new reserved fields on `WorkSpec` at this stage.
Candidate fields were verified as follows:

- `external_market_snapshot`: deferred application-layer concern with no current consumer
- `target_platform`: covered by existing `WorkSpec.platform`
- `audience_profile`: partially covered by existing `WorkSpec.audience`; structured profiling remains outside WorkSpec

A3 schema-stage validation is complete.

Not in scope of A3:
- consuming the external snapshot
- mapping audience profile to specific tone parameters
These belong to Phase B (consumption logic) or Phase C (real ingestion).

#### A4. Add end-to-end usage walkthroughs

[Verified] Existing examples under `05_examples/` are local pressure
tests of fields, objects, or workflow segments. None walks a full task
from a user's point of view.

Proposed action: add end-to-end walkthrough examples, ordered by
current-phase priority:

- `audit_walkthrough_*.md`: full `audit` of a fictitious novel.
  **Highest current-phase priority.** Should reuse the existing
  `示例小说甲` mock case to satisfy DEC-20260326-32 (single mock case).
- `extend_walkthrough_*.md`: full `extend` of a fictitious half-finished
  novel with partial state. **High current-phase priority.** Same mock
  case reuse.
- `compose_walkthrough_*.md`: full `compose` from `WorkSpec` to a short
  finished narrative. **Deferrable per DEC-22.** Can be written after
  audit and extend walkthroughs are stable, or pushed to Phase B if
  Phase A is at risk of expanding scope.

Purpose: surface real gaps that local pressure tests cannot expose.
These walkthroughs become the input for Phase B.

### 3.3 Phase A Exit Conditions

- audit and extend entry modes are documented in unified terminology
- compose entry mode at minimum has a documented stub form (compose
  walkthrough may still be deferred)
- Failure Types include `generative_indicia` as a layer-4 entry
- `WorkSpec` reserved-input-hooks decision has been taken (either
  implemented or explicitly deferred to Phase B)
- at least audit and extend walkthroughs exist (compose walkthrough
  may be deferred)
- Track 1, Track 2, Track 3 are unchanged
- no new core object has been added
- no existing workflow semantic has been modified

### 3.4 Excluded Simpler Alternatives

- **Directly editing schemas**: rejected because the gap is not in field
  count, it is in usage-perspective absence. Editing schemas first lets
  field decisions drift back later.
- **Jumping to implementation**: rejected because the implementation unit
  map (document 17) was built from a self-coherence perspective, not
  from real usage stress.
- **Adding `usage_mode` as a new core object**: rejected because usage
  modes belong to workflow entry metadata, not to narrative truth. Adding
  it as a core object would pollute the eight-object set.
- **Creating an entirely new `06_usage_modes.md` workflow document**:
  rejected after batch-1 verification. The existing `Rebuild` workflow
  document already covers audit and extend; only a terminology index
  plus a compose-mode extension is needed.

---

## 4. Phase B: Domain Layer And End-To-End Validation

### 4.0 Phase B Entry Condition

Phase B requires that the existing mock case (`示例小说甲`) has been run
through the workflow loop at least twice in stable form, per
`DEC-20260326-37` ("only when the current mock case can run two stable
rounds, introduce a second mock case"). The Phase A audit and extend
walkthroughs partially satisfy this requirement, but a full Phase A
walkthrough double-pass should be confirmed before Phase B starts
expanding samples.

### 4.1 Goal

Make the system's ability to operate on specific domains (e.g. web fiction,
serious literature, screenplay) explicit. Use the Phase A walkthroughs
as driving stress.

### 4.2 Tasks

#### B1. Introduce a Domain Layer separate from the core

Proposed structure:

```
Application Layer  (deferred until later phases)
        |
Domain Layer       (new in Phase B; pluggable per domain)
        |
Core Layer         (unchanged: 8 objects + 4 workflows + 3 locks)
```

Proposed Domain Layer contents (web fiction example):

- genre formula sets (eight-node, three-act, compressed three-act, etc.)
  → consumable as `WorkSpec.structure_template` options
- hook taxonomy (chapter-end, chapter-open, paragraph-level)
  → constrains `PlotUnit.hook` legal classification
- emotional arc templates
  → constrains `PlotUnit.emotional_shift` legal shapes
- platform-feature snapshots
  → consumable dictionary keyed by `WorkSpec.platform`

Boundary requirement:
- the Domain Layer is **rule knowledge**, not facts and not inference
- it is not part of any single novel's `WorldModel`
- it is part of the meta-rules of "novels of this kind"

[Undecided] Physical placement of Domain Layer content. Candidates:

1. external normative reference attached via `WorkSpec`
2. judgment-standard library used by `Review` workflow
3. dual track: structure templates via `WorkSpec`, judgment standards via
   `Review`

This is a Phase B blocking decision.

Track 1 consistency check:
- Domain Layer entries are not facts, must not enter `FactLedger`
- if introduced as `Review` standards, they constrain judgment, not truth

Plug-in requirement:
- Domain Layer must be replaceable without touching the core
- the system must be able to swap web fiction → screenplay → literary
  domain by swapping the Domain Layer

#### B2. External resource absorption strategy

Proposed policy for absorbing existing external resources (e.g. third-party
writing-skill collections):

- methodology of analysis (拆文)        → `Rebuild` workflow learning sub-mode reference
- writing formulae and emotional arcs   → Domain Layer (web fiction track)
- de-AI techniques                      → `Review` `generative_indicia` detection / repair reference
- market-trend scanning                 → not absorbed; future application-layer input when compose flow activates

Risk:
external resources are typically empirical and semi-structured.
Direct absorption would import "subjective preference treated as
objective standard". A required pre-step is structuring labels:
- `hard_pattern` (most successful same-class works satisfy this)
- `mainstream_preference` (common in genre but not required)
- `school_specific` (specific subgenre or platform only)

[Speculation] The structuring cost itself is the main work of B2 and
may dominate Phase B effort.

#### B3. Three-flow stress test suite

Extend the Phase A walkthroughs into a stress test suite. Per
`DEC-20260326-37`, the existing `示例小说甲` mock case must support all
audit and extend variants before introducing a second mock case.

Recommended variants per flow (audit and extend first, compose last):

- audit: successful work / problematic work / mixed-style work
- extend: complete-state continuation / gapped-state continuation /
  cross-arc continuation
- compose: full short narrative / long-form outline segment /
  multi-`PlotUnit` chain (deferrable per DEC-22)

Variant axes can reuse `01_rebuild_workflow.md` section 7 result
classification (完整重建 / 结构性重建 / 初始化式重建 / 失败重建) for
audit and extend. This is a direct reuse of existing primitives.

Purpose: validate whether Phase A boundary alignment plus Phase B
Domain Layer can actually carry the three flows. Failures here become
Phase B's reopening triggers.

#### B4. Decide long-range orchestration owner

[Verified] Document 17 (`implementation_unit_map`) defines
`OrchestrationGateUnit` for gate-level orchestration (entry / exit /
escalation gating). Long-range orchestration (book → arc → chapter →
scene hierarchy, cross-chapter consistency maintenance) has no explicit
owner.

`PlotUnit.level` field implies hierarchy but does not own the relation
between levels.

[Undecided] Owner candidates:
1. new implementation unit `NarrativeFrameUnit` (planning unit, not new
   core object)
2. expand `WorkSpec` to own structural framing
3. multi-level `NarrativeState` (introduce explicit hierarchy in state)

This is a Phase B blocking decision.
A wrong choice here would either bloat `WorkSpec` beyond intent or
weaken `NarrativeState` runtime focus or create a new orchestration
unit competing with `OrchestrationGateUnit`.

### 4.3 Phase B Exit Conditions

- Phase B entry condition (4.0) was satisfied at start
- Domain Layer is isolated from the eight core objects
- at least one domain (web fiction) has concrete Domain Layer fill
- audit and extend stress test suites are in place with at least three
  variants each (compose stress tests deferrable)
- long-range orchestration owner has been decided (any of the three options)
- `generative_indicia` failure type has concrete detection / repair
  methodology references

### 4.4 Excluded Simpler Alternatives

- **Putting domain knowledge into `WorldModel`**: rejected because it
  violates `WorldModel`'s "world of one novel" semantic and turns
  `WorldModel` into a junk drawer.
- **Skipping Domain Layer and writing rules into prompts**: rejected
  because that fixes domain knowledge into the model-routing layer,
  breaks plug-in requirement, and violates state-first.
- **Letting an external resource ship as a direct plug-in**: rejected
  because external resources are typically tied to a specific deployment
  shell. Domain Layer must be data and rules, consumable by any
  deployment shape.

---

## 5. Phase C: Implementation Slice And Deployment

### 5.1 Goal

Choose a minimal end-to-end implementation slice and start touching
previously deferred topics (storage / model routing / orchestration
runtime / deployment shape / UI). Phase C must not start until Phase A
and Phase B exit conditions are satisfied.

### 5.2 Tasks

#### C1. First implementation slice selection

[Recommended, undecided] Start with **short-form audit**.

Rationale:
- audit input is existing complete text, no generation pressure
- short form avoids long-range orchestration stress
- audit simultaneously stress-tests the two most complex workflows:
  `Rebuild` and `Review`
- explicitly aligns with `DEC-20260326-22` ("先验证 Rebuild / Continue /
  Review / Rewrite，再考虑表达层") by deferring text-generation pressure
- aligns with current-phase priority (audit > extend > compose)

Second slice: short-form extend, adds `Continue` to the loop.
Third slice: short-form compose, adds `WorkSpec`-driven full-flow.
Long-term goal level (three flows equal-priority) is satisfied only when
all three slices have been validated.

Excluded simpler choice: starting from long-form compose. Rejected
because it would expose long-range orchestration unresolved issues
plus `WorkSpec` expressiveness gaps simultaneously, and the two would
be hard to separate. It also conflicts with DEC-22.

[Undecided] The actual first slice may differ if there are external
constraints not visible from the design layer alone.

#### C2. Deployment shape decision

Defer until C1 has at least one slice running.
Candidates to consider at that point:
- agent-skill shape (per-domain knowledge as references)
- standalone service plus agent
- embedded library
- hybrid (core as library, application layer as skill)

Decision rule: deployment shape decision waits for at least one slice
to be functional. Otherwise it is speculation.

#### C3. Deferred topics, ordered

Enter previously deferred topics in dependency order:

1. persistence storage (serialization candidate note already exists, doc 12)
2. model routing (which step uses which model)
3. prompt orchestration (handoff packet exists, but actual prompt
   generation is a new problem)
4. UI / product flow
5. performance tuning

Constraint: before entering each topic, re-verify that Track 1, Track 2,
Track 3 still hold under the proposed addition.

### 5.3 Phase C Exit Conditions

- at least one end-to-end flow (recommended: short-form audit) runs
  for real
- Track 1, Track 2, Track 3 still hold in the running environment
- at least one deployment shape has been validated as usable
- the system can be used by real users on real tasks
- long-term goal level reached when all three flow slices are validated

---

## 6. Track 1 / 2 / 3 Through The Roadmap

These three locks are unchanged across all three phases.

Each phase exit must verify:

- Track 1: `FactLedger` is not polluted by Domain Layer rules, by
  external market data, or by application-layer judgments
- Track 2: `Rewrite` same-packet local-repair boundary is not weakened
  by usage-mode semantics or by domain-specific repair shortcuts
- Track 3: `CharacterModel` is not bloated by domain knowledge or by
  style-rule storage

If any phase action conflicts with these checks, that action is rejected
regardless of usage benefit.

---

## 7. Open Decisions

These are the items this roadmap intentionally does not decide.
They are listed here so future work knows what to close.

| Item | Phase | Notes |
|---|---|---|
| Domain Layer physical placement (`WorkSpec` ref / Review std lib / dual) | B | blocking for B1 |
| Long-range orchestration owner (new unit / `WorkSpec` / multi-level `NarrativeState`) | B | blocking for B4 |
| First implementation slice (short-form audit recommended, not committed) | C | blocking for C1 |
| Deployment shape | C | wait for C1 to produce running slice |
| Internal task order within each phase | A / B / C | listed orders are suggestion, not dependency |
| `WorkSpec` external input hook fields (subject to schema-stage validation) | A (verified, partial adoption) | audience + platform adopted; external_market_snapshot deferred to compose-flow activation |

Project-level open threads (decision review mechanism, agent quickstart
drift, etc.) are tracked separately in
`docs/00_project/23_open_threads.md`.

---

## 8. Relation To Existing Documents

This roadmap does not replace any existing planning document.

- documents 11 through 21 remain authoritative for current
  implementation-planning artifacts
- this roadmap adds a usage-oriented layer above them, not in place of them
- Phase A produces additions, not edits to the existing planning chain
- if Phase A or B exposes a real conflict with documents 11-21, that
  conflict is a reopening trigger handled per document 09's
  pre-implementation-boundary-lock policy, not a license to silently
  modify locked decisions

This roadmap **does not modify** any existing decision in
`docs/07_decisions/`. Where a tension exists with a decision (notably
DEC-20260326-22), the roadmap adapts to the decision, not the reverse.

---

## 9. Relation To External References

[Verified] An external reference (`oh-story-claudecode`) was reviewed
during the planning conversation that produced this roadmap.

That reference is **not** an architectural source. It operates at the
application layer (writing-skill agent collection), not at the narrative
operating-system layer.

It is treated in this roadmap as:

- a source of structurable domain knowledge for Phase B (web fiction track)
- a real-world reminder that `audit` and `compose` flows must be supported
  for the system to be usable
- not an architectural pattern to copy

The roadmap explicitly rejects:
- copying its workflow shape (linear `scan → analyze → write → deslop`),
  because the existing `Continue → Review → Rewrite | Replan` routing
  hub design is incompatible with linear flow
- copying its data shape, because it has no schema layer
- copying its deployment as a direct decision, because deployment is
  Phase C work and must wait for slice validation

---

## 10. Verification Status

[Verified items in this roadmap]
- existing example files do not include end-to-end usage walkthroughs
  (verified by inspection of `05_examples/`)
- document 17 has no explicit owner for long-range orchestration
  (verified by reading 17)
- documents 11 through 21 plus quickstart and current-status documents
  do not contain the entry-mode framing for `audit` / `extend` / `compose`
  (verified by reading)
- `01_rebuild_workflow.md` covers audit and extend input cases under
  scenario language (sections 2.1, 2.2); it does not cover compose
  (verified by batch-1 reading)
- `08_failure_types.md` defines 15 failure types in 4 layers; generative
  indicia is not explicitly covered (verified by batch-2 reading)
- compatibility with decisions 01, 02, 03, 05, 06 (DEC-01 through DEC-26
  excluding DEC-27 to DEC-31, DEC-32 through DEC-47): no direct conflict;
  DEC-22 priority tension is addressed via section 1.1.a (verified by
  batch-4 reading)
- specific gaps in `WorkSpec` schema: verified 2026-05-28 against
  `src/object_state/workspec.py`. `audience` and `platform` are already in
  schema; `external_market_snapshot` is deferred until compose-flow
  activation and a concrete consumer exists.

[Speculative items in this roadmap]
- current system implicitly optimizes the `extend` flow
- audit coverage is mid; compose coverage is low
- structuring cost will dominate Phase B effort

[Unverified items in this roadmap]
- compatibility with decisions 04, 07 (`schema_granularity`,
  `experiment_strategy`) and decisions 08-13 beyond the title-level
  awareness (source: not fully read in this revision)
- whether `03_rules/` files beyond `08_failure_types.md` contain
  additional usage-blind-spot evidence

[Undecided items deferred to specific phases]
- listed in section 7 above

---

## 11. One-Sentence Summary

This roadmap proposes carrying the existing foundation into real usage
through a three-phase plan that aligns boundaries first, builds a
plug-in domain layer second, and starts implementation only after both,
respecting current-phase priority (audit > extend > compose per DEC-22)
while preserving long-term equal-priority across the three flows, and
without modifying core objects, workflows, or locks.
