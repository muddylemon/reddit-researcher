# Architecture

Reddit Researcher is a small pipeline. It does five things in order and writes everything to disk.

```text
+----------------+     +------------------+     +----------------+     +-------------+     +-----------+
| 1. Load        | --> | 2. Reddit JSON   | --> | 3. Normalize   | --> | 4. Relevance| --> | 5. Ollama |
|    project.toml|     |    fetch         |     |    + persist   |     |    review   |     |   extract |
+----------------+     +------------------+     +----------------+     +-------------+     +-----------+
                              |                          |                    |                  |
                              v                          v                    v                  v
                          raw/*.json              normalized/*.jsonl     review/*.jsonl     analysis/*.md
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `cli.py`           | Argparse front door. Translates flags into config dataclasses and dispatches to the pipeline. |
| `config.py`        | Loads and validates `project.toml`. Resolves relative paths against the project folder. |
| `reddit_client.py` | JSON-endpoint backend (no auth) plus the `make_reddit_client(scrape)` factory. |
| `praw_client.py`   | Optional [PRAW](https://praw.readthedocs.io/) backend. Selected by `[scrape].backend = "praw"`; needs the `praw` extra. |
| `ollama_client.py` | Thin wrapper over Ollama's HTTP API. Surfaces missing models with the available list. |
| `pipeline.py`      | Orchestrates scrape → normalize → relevance → extract. Handles checkpointing. |
| `prompting.py`     | Loads prompt files, builds corpora, chunks long text, and assembles model prompts. |
| `relevance.py`     | Deterministic, configurable pre-LLM filter. Decides `include`, `review`, or `exclude`. |
| `storage.py`       | JSON, JSONL, and run-folder helpers. The output contract lives here. |
| `progress.py`      | Per-run logger that writes to `logs/scrape.log` and `logs/extract.log`. |
| `models.py`        | `PostRecord` and `CommentRecord` dataclasses. |

## Data contract

Every run writes the same shape:

```text
runs/<scope>/<timestamp>/
  manifest.json              run metadata
  raw/                       unmodified Reddit responses
  normalized/                clean rows for analysis
  review/                    relevance decisions
  analysis/                  LLM output
  logs/                      per-stage logs
```

This layout is intentionally flat and human-greppable. Forks should treat it as the public
interface — adding files is fine, renaming or restructuring is a breaking change.

## Invariants worth knowing

- **Scrapes are append-only.** A failed scrape does not delete prior progress; resuming into the
  same `--run-dir` re-uses everything in `normalized/`. As of 0.1.0 this applies to both subreddit
  and search modes.
- **Extractions reuse chunks.** `analysis/chunks/chunk-NNN.md` is reused if non-empty unless
  `--force-reextract` is passed.
- **Relevance is cheap and deterministic.** It runs in-process with no network calls. The LLM only
  ever sees posts whose decision is `include` or `review`.
- **Search-mode corpora are grouped by `search_term`.** This lets a per-term prompt produce a
  per-term section in the synthesis.
- **Manifests are versioned.** Every `manifest.json` written by 0.1.0+ carries a `schema_version`
  field. See "Manifest schema" below.

## Manifest schema

The current schema version is **2**, defined in `reddit_researcher/manifest.py`. Manifests
written before 0.1.0 do not have this field and are treated as v0; this matters only for
forward-compat code, since each version bump has been a strict superset (fields added; nothing
removed). The version bumps when a *required* field is added, removed, or changes meaning;
optional additions don't bump it. Each bump gets a CHANGELOG entry with migration guidance.

### Subreddit-mode fields (schema_version 2)

Subreddit-mode supports scraping one or more subreddits via `[scrape].subreddits = ["a", "b",
"c"]`. Single-subreddit projects (`subreddit = "x"`) are transparently normalised to a
one-element list at load time. Two new top-level fields appear in `manifest.json` for all
subreddit-mode runs:

- `subreddits` — list of subreddit names (always present in subreddit-mode, even for a
  single-sub project).
- `per_subreddit` — mapping of subreddit name → `{post_count, comment_count, status[, error]}`.
  Status is one of `pending`, `fetching`, `complete`, or `fetch_error`. Lets callers inspect
  partial failures when one sub in a multi-sub run errors out while others succeed.

Posts in `normalized/posts.jsonl` carry a `subreddit` field identifying their source
community, making it straightforward to partition or filter the corpus by sub.

Old (v1) manifests produced by 0.1.x are read forward via `normalize_manifest` without
rewriting the file — no migration step needed.

## Environment variables

Three variables reach into the defaults pipeline:

- `OLLAMA_URL` — replaces the built-in `http://127.0.0.1:11434` endpoint.
- `OLLAMA_MODEL` — replaces the built-in `qwen3:8b` default model.
- `REDDIT_RESEARCHER_USER_AGENT` — replaces the polite-default User-Agent header.

Loading order is repo-root `.env` → project `.env` → shell environment → `project.toml` →
CLI flags, with the higher item always winning. The dotenv parser is in
`reddit_researcher/env.py` and is intentionally tiny (no expansion, no multi-line values).

## Why TOML for projects

- Built into the standard library on Python 3.11+ (`tomllib`). No new dependency.
- Easy to read, easy to diff. Comments are first-class.
- Strict typing avoids the YAML "Norway problem" and ambiguous numbers.

## JSON vs PRAW backends

The default `"json"` backend reads Reddit's public JSON endpoints. Zero-config: no
`client_id`, `client_secret`, refresh tokens, or registered apps. Sufficient for low-volume
research and the path most forks will take.

The optional `"praw"` backend ships in 0.1.1 for users who need authenticated access:

- Higher rate-limit ceiling than the unauth endpoint.
- Listings can return more than 1000 posts.
- Comment trees automatically expand `MoreComments` placeholders.

Trade-offs:

- Adds the `praw` Python dependency (install via `pip install reddit-researcher[praw]`).
- Requires registering a "script" app on Reddit and stashing the resulting
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in your shell or a `.env` file.
- `pause_seconds` and `max_retries` are ignored; PRAW manages its own backoff.

Both backends emit identical `PostRecord` / `CommentRecord` shapes and produce the same
run-folder layout, so a project can be flipped from JSON to PRAW (or back) by changing one
line in `project.toml`.

## Why Ollama, not a hosted LLM

- Local-first: data never leaves the machine, no API key handling, no per-token spend during
  iteration.
- Practical for prompt tuning: rerunning extraction over the same scrape is free.
- The `OllamaClient` API is intentionally narrow (`generate`, `list_models`). Swapping it for a
  different local backend is a one-file change.

## Storage (optional DB sink)

A run's `normalized/*.jsonl` files are canonical. As of 0.2.0, every run is
*also* mirrored into a small relational database for cross-run analysis.

- **Default engine:** SQLite (stdlib, zero deps).
- **Optional engine:** DuckDB via the `[duckdb]` extra
  (`pip install reddit-researcher[duckdb]`). Set `[storage].engine = "duckdb"`.
- **DB location:** `[storage].db_path` (default `research.db` next to
  `project.toml`). Multiple projects can share one DB; `runs.project_name`
  distinguishes them.
- **When it's written:** post-hoc, after each `reddit-researcher run` finishes,
  unless `[storage].auto_sync = false`. JSONL is unaffected if the sync fails;
  the failure is logged and the run still succeeds.
- **Tables:** `runs`, `posts`, `comments`, `relevance_decisions`. The full
  manifest is stored verbatim in `runs.manifest_json` so queries can reach
  fields the schema doesn't promote.
- **Schema version:** stored in `_schema_meta`. If it diverges from the code's
  expected version, the sink raises `SchemaVersionMismatch`; recover with
  `reddit-researcher db sync --rebuild`.
- **Read-only queries:** `reddit-researcher db query "SELECT ..."` opens a
  read-only connection; writes raise an error rather than mutating data.
- **`diff` consumer:** `reddit-researcher diff <run-a> <run-b>` reads from this
  sink, auto-syncing each run if missing or stale.

## Series rollups

`reddit_researcher/series.py` produces a per-project trend report from the
sink. Like the `diff` module, it uses only the read-only connection
(`RunSink.read_only_connect()`) — JSONL on disk remains canonical.

- **Key:** `runs.project_name`. All runs of one project are joined on this
  column. If the user renames a project mid-series, pre-rename runs no
  longer match — documented as a known limitation.
- **Queries:** one ordered fetch from `runs`, one aggregate from
  `relevance_decisions`, one fetch-per-run from `posts`. Pure Python set
  arithmetic for new/carried/always-present.
- **Auto-sync:** the CLI walks the project's `output_root`, finds run
  dirs whose manifest's `project_name` matches and that are missing or
  stale in the sink, and syncs them before computing.
- **Output:** `runs/_series/<project_name>/<timestamp>/series.{md,json}`.
  `_series/` is collision-free with subreddit-mode and search-mode scope
  dirs because Reddit subreddit names cannot start with `_`.

## Corpus formatters

`reddit_researcher/corpus_formatters.py` owns the dispatch between three named
corpus shapes — `compact` (default, byte-equivalent to legacy output),
`conversational` (markdown headings + prose metadata), and `structured-json`
(one JSON object per post, blank-line separated). Selected via
`[analyze].corpus_format` in `project.toml`, overridable per-run with
`--corpus-format`. The legacy `build_corpus`/`build_search_corpus` in
`prompting.py` are now thin wrappers that call `format_corpus(..., fmt="compact")`.

## Caveats and known limitations

These are real friction points that have shown up in practice. They aren't bugs — most are
properties of Reddit's public surface — but they shape how you design a project.

- **Reddit's anonymous in-subreddit search returns empty for many small subs.** The
  `/r/<sub>/search.json?restrict_sr=1` endpoint is heavily restricted without OAuth. A search
  that obviously *should* match (e.g. `dispensary` in a sub that constantly discusses dispensaries)
  often returns zero results. The `top.json` and `hot.json` listing endpoints work fine. Workarounds:
  use subreddit mode against each sub directly, or switch to the PRAW backend.
- **Subreddit mode now supports multiple subreddits** via `[scrape].subreddits = ["a", "b",
  "c"]` (shipped in 0.2.0). Search mode still targets one set of terms across an allowlist.
  See the "Subreddit-mode fields" section under "Manifest schema" for the combined-run layout.
- **The default JSON backend caps at ~1000 posts per listing.** Reddit's pagination soft-limits
  there. For deeper pulls, switch to PRAW.
- **Comment trees are top-N, not exhaustive.** `fetch_comments` pulls the top `comment_limit`
  comments in one request; very large threads' deep replies are clipped. PRAW expands this fully
  via `MoreComments` resolution.
- **The relevance filter is intentionally simple** (substring + keyword). It runs *before* the
  LLM as a cost-control pass, not as a final classifier. The LLM is allowed to disagree, and the
  relevance rules are easy to misconfigure (too narrow → empty `relevant_posts.jsonl`; too
  broad → no signal).
