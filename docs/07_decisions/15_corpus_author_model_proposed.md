# ADR-15: Reusable Corpus Author model (proposed)

Status: proposed; this is a research and prior/shadow artifact, not production authorization.

## Decision

Add a reusable `Author` object for one real author's corpus evidence. The schema supports many
instances in parallel: each instance is stored as `author_models/<neutral-id>.json` and contains
method-layer deterministic statistics, selection-pattern inferences with confidence and chapter
evidence anchors, corpus-size metadata, extraction generation, runtime provenance, and optional
references to `AuthorTemplate` and `StyleProfile`. It does not contain an identity, biography,
persona, prose excerpt, title, or local path.

The entire boundary for **imitation of a specific living author is cancelled**, not narrowed to a
single-corpus exception. Writing styles influence and borrow from one another, and real authors
learn from other authors; an identity-shaped imitation boundary therefore misstates the
phenomenon. The legal guardrails remain: do not copy original expression, do not do identity
marketing, and keep generated artifacts under gitignored neutral IDs.

## Three existing bloodlines and this object

| Object | Responsibility | Relationship to `Author` |
|---|---|---|
| `AuthorKernel` | choice structure, challenges, long-term evolution, generation injection | remains the behavioral state model; `Author` does not replace or write into it |
| `AuthorModelV3` | cross-work evidence, state evolution, qualification and leave-one-out validation | remains the qualification model; `Author` does not bypass its evidence contract |
| `AuthorTemplate` | neutral choice evidence distilled from an explicit ChoiceLedger | may be referenced as a prior/shadow/tie-break input, never merged into identity claims |
| `StyleProfile` | how a work is written: deterministic metrics plus staged qualitative style extraction | may be referenced as a style specification; it is not a selection-pattern source |
| `Author` | reusable corpus-level method statistics plus staged selection-pattern inference | sibling evidence model; no production gate or automatic terminal judge |

## Extraction contract

1. The deterministic pass is batch-friendly: one extractor accepts N local corpus directories and
   materializes N neutral Author instances. It records method-layer proxy statistics for rhythm,
   dialogue habits, hook signals, viewpoint markers, conflict signals, turning-point signals,
   paragraphing, and chapter scale. These are measurements, not semantic truth.
2. The staged pass samples representative chapters into a local prompt, prints `[WAITING]`, and
   accepts only structured JSON selection patterns. Every pattern requires confidence and one or
   more chapter-numbered aggregate evidence anchors. The prompt/response may contain local source
   material, but the persisted model never stores prose.
3. A missing, malformed, duplicate, or identity-shaped response does not silently select a pattern.
   Materialization is atomic and rerunning with unchanged input is idempotent.
4. No provider is called by the CLI. The operator/Codex materializes the response file locally.

## Non-goals and legal boundary

This object is not a production selector, hard gate, aesthetic final judge, identity marketing
claim, or license to copy expression. The cancelled boundary is a scope correction, not permission
to publish source text or private identifiers. Corpus-derived files and neutral instance IDs remain
local and gitignored.
