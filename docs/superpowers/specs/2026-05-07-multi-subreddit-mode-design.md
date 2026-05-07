# Multi-subreddit subreddit-mode — Design

**Status:** approved (brainstorm)
**Target release:** 0.2.0 (first feature of the analytics line)
**Date:** 2026-05-07

## Background and motivation

Subreddit-mode today scrapes exactly one subreddit per run. The Missouri-cannabis
case study surfaced this as a real friction point: researchers who care about a
topic that lives in multiple communities (e.g. r/cannabis, r/marijuana, r/drugs)
have to either run the project N times and manually merge the corpora, or
hand-write a Python harness around the library.

The roadmap entry calls for `[scrape].subreddits = ["a", "b", "c"]` to scrape
each into one combined run dir.

## Goals

- Single-run scraping across multiple subreddits with one combined corpus.
- Backward compatibility: existing single-`subreddit` projects keep working
  unchanged, and the run-folder layout for single-sub runs is unchanged.
- Per-sub observability in the manifest (counts, per-sub failures isolated).
- Forward compatibility with the rest of the 0.2.0 line (DB sink, diff,
  time-series) — the per-post `subreddit` field becomes a load-bearing
  partition key.

## Non-goals

- Per-sub `post_limit` overrides (e.g. `{"cannabis": 50, "drugs": 10}`).
  YAGNI for v1; can be added later without schema break.
- Cross-sub dedup of cross-posts (Reddit IDs differ across crossposts; the
  noise isn't worth special-case handling).
- A `multi-` prefix in run-dir names — the joined slug below carries enough
  information.

## Architecture

One code path: refactor `scrape_subreddit` to take a list. Single-sub becomes
a list of one. The current per-post inner loop is preserved verbatim; an outer
loop wraps it for multi-sub.

### Function signature change ([reddit_researcher/pipeline.py](../../../reddit_researcher/pipeline.py))

```python
def scrape_subreddit(
    *,
    subreddits: list[str],   # was: subreddit: str
    output_root: Path,
    scrape: ScrapeConfig,
    relevance: RelevanceConfig | None = None,
    run_dir: Path | None = None,
) -> Path: ...
```

Callers (`pipeline.run_project`, `cli.scrape` command, tests) update to pass
a list. The function asserts `len(subreddits) >= 1`.

## Config and validation

[reddit_researcher/config.py](../../../reddit_researcher/config.py)

`ScrapeConfig.subreddit` (singular, currently `str | None`) is **removed**.
`ScrapeConfig` gains a single canonical `subreddits: list[str]` field instead.
TOML accepts both `subreddit = "x"` and `subreddits = [...]`, but they
collapse into one canonical list at config-load time, so internal callers
never see two shapes.

Callers that read `project.scrape.subreddit` today (manifest construction,
CLI fall-throughs, tests) update to read `project.scrape.subreddits` and
handle len-1 explicitly where needed.

TOML parsing rules:

- `subreddit = "x"` only → `subreddits = ["x"]`
- `subreddits = ["a", "b"]` only → `subreddits = ["a", "b"]`
- Both set → `ProjectConfigError`
- Neither set in subreddit-mode → `ProjectConfigError` (existing rule, message updated)
- `subreddits = []` → `ProjectConfigError`
- `subreddits = ["A", "a", "B"]` → `["A", "B"]` (case-insensitive dedup; first-occurrence casing wins)
- Entry contains `/` or whitespace, or is empty → `ProjectConfigError`

The error messages name `subreddit`/`subreddits` directly so the existing
line-number-aware error reporting from `0.0.2` keeps working.

## Run-dir scope slug

[reddit_researcher/storage.py](../../../reddit_researcher/storage.py)

New helper:

```python
def multi_subreddit_scope(subreddits: list[str], *, max_chars: int = 60) -> str:
    """Build the run-dir scope segment for one or many subreddits."""
```

Behavior:

- 1 sub → returns the sub name (today's behavior, byte-for-byte).
- N>1 subs → lowercase each, join with `-`. If joined length > `max_chars`,
  drop trailing entries until it fits, then append `+K` where K is the count
  of dropped subs. Examples:
  - `["cannabis", "marijuana", "drugs"]` → `cannabis-marijuana-drugs`
  - `["a", "b", "c", ..., "long-name-1", "long-name-2"]` →
    `a-b-c-...-long-name-1+2`

Run dirs become `runs/<slug>/<timestamp>/`. The `+K` suffix is filesystem-safe
on Windows and POSIX.

## Scrape loop and manifest

The outer loop iterates over subs in order; for each, the existing per-post
loop runs against that sub. Posts already carry the API-returned `subreddit`
field, so combined `posts.jsonl` rows are naturally tagged.

### File layout (unchanged)

- `normalized/posts.jsonl` — all posts (each row already carries `subreddit`)
- `normalized/comments.jsonl` — all comments
- `normalized/relevant_posts.jsonl` — relevance-filtered subset
- `review/relevance_review.jsonl` — relevance decisions

### Manifest shape

```json
{
  "schema_version": 2,
  "mode": "subreddit",
  "subreddit": "cannabis",
  "subreddits": ["cannabis", "marijuana", "drugs"],
  "post_count": 73,
  "comment_count": 412,
  "per_subreddit": {
    "cannabis":  {"post_count": 25, "comment_count": 140, "status": "complete"},
    "marijuana": {"post_count": 25, "comment_count": 138, "status": "complete"},
    "drugs":     {"post_count": 23, "comment_count": 134, "status": "fetch_error",
                  "error": "HTTP 503 from listing endpoint"}
  },
  "...": "(other existing fields unchanged)"
}
```

Rules:

- `subreddits` is always present on writes.
- `subreddit` is populated only when `len(subreddits) == 1`; otherwise omitted.
- `per_subreddit` is always present (even for single-sub runs, with one entry).
- Per-sub `status` values: `pending` (queued, not started), `fetching` (this
  sub is being scraped), `complete`, `fetch_error`. These describe the
  per-sub lifecycle and are distinct from the top-level run `status`
  (`starting`/`fetching_comments`/`complete`), which is unchanged.

### Schema version bump

`MANIFEST_SCHEMA_VERSION` goes from 1 → 2. The reader normalizes old manifests:

- v0/v1 with `subreddit` (string) → synthesizes `subreddits = [subreddit]` and
  `per_subreddit = {<subreddit>: {post_count, comment_count, status}}`
  populated from the top-level counters.
- This synthesis happens in `manifest.py` (or wherever the read site lives)
  so downstream code uses one shape.

CHANGELOG entry documents the bump and notes that v1 runs continue to read
without rewriting.

### Limit semantics

`post_limit` is **per-subreddit**. With 3 subs and `post_limit = 25`, the run
fetches up to 75 posts. This matches search-mode's per-term semantics.

### Resume

The existing `processed_post_ids` set is global to the run dir and carries
across the outer loop. Re-running a partially completed multi-sub scrape skips
posts already in `normalized/posts.jsonl` by ID, regardless of which sub they
came from. The `per_subreddit` counters are recomputed from the on-disk JSONL
on resume so partial state stays accurate.

### Error isolation

A failure fetching a sub's listing (e.g. 503, 404, banned community) is
recorded in `per_subreddit[<sub>] = {status: "fetch_error", error: ..., post_count: 0, comment_count: 0}`
and the loop continues. This matches search-mode's tolerant per-term behavior.

A comment-fetch failure on a single post is logged as today (per-post error
in the existing log), and counted as `comment_count: 0` for that post.

## Extract and corpus

### Corpus building ([reddit_researcher/prompting.py](../../../reddit_researcher/prompting.py))

`build_corpus(posts, comments)` gains an `r/<subreddit>` prefix on the post
header line so the LLM has the source community for each post. This is a
small additive change — the function still works identically for single-sub
runs (the prefix is just a fact, not a switch).

```text
[POST abc123] r/cannabis title: ...
author: ... | score: ... | comments: ...
```

`build_search_corpus` already prints `r/<subreddit>` in its header, so this
brings subreddit-mode to parity.

### Scope label

`scope_label_for(subreddit, search_terms)` extended to also accept
`subreddits: list[str] | None`. Resolution order:

- `search_terms` truthy → existing search-mode labels (unchanged).
- `subreddits` with len 1 → `r/<a>` (unchanged).
- `subreddits` with len 2 → `r/<a> and r/<b>`.
- `subreddits` with len 3–5 → `r/<a>, r/<b>, r/<c>` (Oxford comma).
- `subreddits` with len 6+ → `r/<a>, r/<b>, r/<c>, and N others`.
- Fallback (`subreddit` only, legacy callers) → `r/<x>`.

`extract_from_run` reads `subreddits` from the manifest (falling back to
`[subreddit]` for v0/v1 runs via the manifest reader's normalization) and
passes the list through.

## CLI surface

[reddit_researcher/cli.py](../../../reddit_researcher/cli.py)

### `scrape` subcommand

The `subreddit` positional becomes repeatable (`nargs="+"`). All of these
work:

```bash
reddit-researcher scrape personalfinance
reddit-researcher scrape cannabis marijuana drugs
```

### `init` subcommand

`--subreddit` becomes `action="append"`. When the user supplies more than one,
the scaffolded `project.toml` writes `subreddits = [...]` instead of
`subreddit = "..."`. Single-`--subreddit` invocations still scaffold
`subreddit = "..."` to keep the templates lean.

```bash
reddit-researcher init missouri-cannabis --mode subreddit \
    --subreddit cannabis --subreddit marijuana --subreddit drugs
```

### Naming collision in `scaffold_project`

`reddit_researcher/templates.py::scaffold_project` already has a `subreddits`
parameter — but it currently means "search-mode subreddit allowlist" (the
content of `subreddits.txt`), which is a different concept. To avoid two
incompatible meanings of the same parameter name:

1. Rename the existing search-mode parameter `subreddits` → `allowlist_subreddits`.
   This matches the existing CLI flag (`--allowlist-subreddit`).
2. Reuse `subreddits` for the new subreddit-mode list.
3. Keep the singular `subreddit` parameter for single-sub scaffolding.

`scaffold_project` is internal (not part of any public API surface beyond the
CLI), so the rename is local. Update its callers in `cli.py` accordingly.

The new signature:

```python
def scaffold_project(
    *,
    project_dir: Path,
    mode: str,
    subreddit: str | None = None,            # subreddit-mode, single sub
    subreddits: list[str] | None = None,     # subreddit-mode, multi
    terms: list[str] | None = None,          # search-mode terms
    allowlist_subreddits: list[str] | None = None,  # search-mode allowlist (was: subreddits)
    ...
) -> list[Path]: ...
```

Subreddit-mode validation: at least one of `subreddit` or `subreddits` must be
set; both at once raises.

## Testing

### `tests/test_config.py`

- Singular-only TOML loads with `subreddits == ["x"]`.
- Plural-only TOML loads as given.
- Both fields set raises `ProjectConfigError` with both field names in message.
- Empty `subreddits = []` raises `ProjectConfigError`.
- Duplicates collapse case-insensitively, first-occurrence casing wins.
- Entry containing `/` or whitespace raises.
- Neither field set in subreddit-mode raises (existing rule, refreshed).

### `tests/test_storage.py`

- `multi_subreddit_scope(["x"])` → `"x"`.
- `multi_subreddit_scope(["cannabis", "marijuana", "drugs"])` →
  `"cannabis-marijuana-drugs"`.
- 12-sub list with long names → truncates with `+K` suffix, total length
  ≤ `max_chars`.
- Lowercasing applied to non-lower input.

### `tests/test_pipeline.py`

- Multi-sub scrape via a stub Reddit client:
  - Combined `posts.jsonl` contains posts from all subs.
  - Manifest has `subreddits`, `per_subreddit` populated correctly.
  - Listing failure on one sub records `status: "fetch_error"` in
    `per_subreddit[<sub>]`, other subs complete normally.
- Single-sub scrape regression: file layout, manifest shape (with
  `subreddit` populated), and counts match today's output exactly.
- Resume of a partial multi-sub run: re-running with the same `run_dir`
  skips already-processed posts and updates `per_subreddit` counts.

### `tests/test_prompting.py`

- `scope_label_for(subreddits=["a"])` → `"r/a"`.
- `scope_label_for(subreddits=["a", "b"])` → `"r/a and r/b"`.
- `scope_label_for(subreddits=["a", "b", "c"])` → `"r/a, r/b, r/c"`.
- `scope_label_for(subreddits=["a","b","c","d","e","f","g"])` →
  `"r/a, r/b, r/c, and 4 others"`.
- `build_corpus` output prefixes each post header with `r/<subreddit>`.

### `tests/test_manifest.py`

- v1 manifest with `subreddit: "x"` reads as `subreddits=["x"]` and synthesizes
  `per_subreddit["x"]` from the top-level counters.

## Documentation

- [README.md](../../../README.md): add a multi-sub example to the
  subreddit-mode section. Either bump `example-subreddit-faq` to show the
  plural form or add a fourth subreddit-mode example.
- [docs/architecture.md](../../architecture.md): note that subreddit-mode
  supports a list; `posts.jsonl` rows are partitioned by their `subreddit`
  field.
- [docs/roadmap.md](../../roadmap.md): mark the multi-subreddit checkbox
  done with the version stamp.
- `CHANGELOG`: schema_version 1 → 2, additive (older runs read fine).

## Dependencies and risks

- **No new runtime dependencies.**
- **Risk: single-sub regression.** Mitigated by an explicit single-sub test
  that asserts file layout and manifest shape are byte-equivalent to today's
  output (modulo new fields that are additive).
- **Risk: PRAW backend parity.** The PRAW client implements the same
  `fetch_posts(subreddit=...)` interface as the JSON client, so the outer
  loop drives both backends identically. Test with a stub at the client
  boundary, not the network.
- **Risk: `_subreddit` casing drift.** Reddit's API returns subreddit names
  with their canonical casing; user config may differ. We use the user's
  configured casing for run-dir slug and `per_subreddit` keys, and the
  API-returned casing on each post row. The test suite locks this in.

## Acceptance criteria

- A `project.toml` with `subreddits = ["a", "b", "c"]` runs end-to-end and
  produces a single `runs/<slug>/<timestamp>/` folder with combined corpora,
  per-sub manifest sections, and a synthesized `analysis/final.md`.
- Existing single-sub example projects produce the same run-folder shape as
  today (additive manifest fields only).
- A v1 manifest can be read by the new code without modification.
- All new and existing tests pass; coverage gate (currently 70%) holds.
