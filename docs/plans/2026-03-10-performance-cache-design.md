# Performance Cache Design

**Date:** 2026-03-10

**Context**

The orchestrator spends most of its wall-clock time in repeated external work:

- arXiv source downloads and extraction
- Codex CLI subprocess calls for clean, extract, score, and email analysis
- GitHub repo scans after paper scoring

The approved goal for this change is to speed up repeated and same-day runs without
changing discovery semantics or scoring heuristics.

## Chosen Approach

Implement two focused changes:

1. Add persistent reuse for expensive repeated work.
2. Stop issuing a dedicated Codex email-analysis call and build the mail body from
   existing scoring output.

This keeps the current pipeline shape intact while removing the most obvious wasted
work.

## Alternatives Considered

### Option 1: Tune only config defaults

This is the lowest-risk option, but it does not help repeat runs and does not fix the
per-paper subprocess overhead.

### Option 2: Merge multiple Codex prompts into one giant prompt

This reduces process count, but it is a larger behavior change and would make prompt
failures harder to isolate.

### Option 3: Add caching plus remove the extra email Codex pass

This is the recommended option and the one approved for implementation. It preserves
the core pipeline while cutting repeated network and subprocess work.

## Scope

### In scope

- Reuse extracted arXiv sources when a paper was already fetched locally.
- Cache Codex JSON results based on the rendered prompt content.
- Reuse prior score output to render email markdown locally.
- Add tests that prove the new behavior.

### Out of scope

- Redesigning discovery heuristics
- Changing scoring formulas
- Reworking the orchestrator CLI
- Adding new runtime services

## Data Flow

### arXiv source reuse

- `source_fetch()` checks whether the paper output directory already contains a saved
  archive and extracted `.tex` files.
- If present, it returns that payload immediately.
- If not present, it performs the existing download and extraction path.

### Codex result cache

- Before calling `codex exec`, the orchestrator computes a cache key from:
  - operation name
  - paper identity
  - rendered prompt content
- If a cached JSON payload exists, it is returned immediately.
- Otherwise the existing Codex call is executed and the payload is saved atomically.

### Email analysis

- The pipeline no longer performs a fourth Codex pass just to create email markdown.
- Instead it renders a markdown summary from fields already produced during scoring,
  including TLDR, summary, extracted highlights, recommendation, and repo links.

## Error Handling

- Cache lookup failures must degrade to the current slow path.
- Cache write failures must not fail the run; they only skip reuse for later runs.
- Partial or invalid arXiv extraction directories must fall back to download.

## Testing Strategy

- Add a regression test proving `source_fetch()` reuses an existing extraction.
- Add regression tests proving clean and score Codex steps only call
  `_run_codex_json()` once across repeated identical invocations.
- Add a regression test proving email analysis does not call Codex when scoring output
  is already available.
