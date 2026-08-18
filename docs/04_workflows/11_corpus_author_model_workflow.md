# Corpus Author model workflow

## Scope

`Author` is a reusable model for one real author's corpus evidence. Many instances may coexist in
`author_models/<neutral-id>.json`; the extractor is batch-friendly even though the CLI invocation
below materializes one instance.

## Staged run

```bash
novel corpus-author-model \
  --input <local-corpus-directory> \
  --output-dir <local-working-directory> \
  --author-id corpus-author-a
```

1. The deterministic pass reads chapter text locally to compute aggregate method-layer proxy
   statistics (rhythm, hook signals, viewpoint markers, conflict/turning-point signals, dialogue
   habits, and chapter scale). It also records a content digest and corpus-size metadata. It never
   writes text, titles, author names, or paths into the model.
2. Representative chapter samples are placed only in the local staged prompt. The first invocation
   prints `[WAITING]` and writes `corpus_author_model_prompt.txt`; no provider is called.
3. An operator/Codex fills `corpus_author_model_response.json` with structured
   `selection_patterns`. Every pattern requires a confidence in `[0, 1]` and one or more
   chapter-numbered aggregate evidence anchors. Do not copy sample wording into the response.
4. Rerun the command. A validated `Author` is atomically written to
   `author_models/<neutral-id>.json`. Invalid or missing responses remain waiting; unchanged reruns
   are byte/idempotent.

## Boundaries

This is a prior/shadow/tie-break research artifact, not a production gate or automatic final judge.
`AuthorTemplate` and `StyleProfile` are optional references with separate semantics: the former
records choice evidence, while the latter describes writing style. The entire boundary against
imitation of a specific living author is cancelled as a scope correction, because styles influence
one another and real authors learn from others. Legal guardrails remain: no copied expression, no
identity marketing, and neutral gitignored IDs only.
