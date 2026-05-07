# Design: SQLite/DuckDB sink (0.2.0)

A queryable database that sits alongside each project's run folders, populated
by a post-hoc sync step from the JSONL files that already exist. Default engine
is SQLite (Python stdlib). DuckDB is opt-in via a `[duckdb]` extra. The DB is a
derived view — the source of truth stays in the per-run JSONL files.

This design unblocks the rest of the 0.2.0 milestone: `diff <run-a> <run-b>`
becomes a join, and time-series mode becomes an aggregate over `runs`.

## Goals

- Make multi-run analysis tractable: count, compare, and aggregate across runs
  without writing one-off scripts that re-parse JSONL.
- Stay zero-dep on the default path. SQLite ships with Python; DuckDB stays
  optional.
- Preserve the existing data contract — JSONL on disk is canonical and survives
  even if the DB is deleted.
- Mirror the existing PRAW backend pattern so the codebase has one shape for
  optional-dependency dispatch.

## Non-goals

- A migration framework. Schema changes use `db sync --rebuild` (drop + re-sync
  from JSONL). Acceptable because JSONL is canonical.
- Indexing analysis output (`analysis/chunks/*.md`, `analysis/final.md`). Files
  are fine; an `analyses` table can land in 0.3.0 alongside cost tracking.
- Cross-engine compatibility of the DB file itself. SQLite and DuckDB files are
  not interchangeable; switching engines requires `db sync --rebuild`.

## Config

A new `[storage]` section in `project.toml`. All keys optional; the section
itself is optional.

```toml
[storage]
engine = "sqlite"            # "sqlite" (default) or "duckdb"
db_path = "research.db"      # relative to project dir; default "research.db"
auto_sync = true             # sync at end of each run; default true
```

A new `StorageConfig` dataclass in [config.py](../../../reddit_researcher/config.py)
holds these:

```python
@dataclass
class StorageConfig:
    engine: str = "sqlite"
    db_path: Path = field(default_factory=lambda: Path("research.db"))
    auto_sync: bool = True
```

`engine` is validated against `{"sqlite", "duckdb"}` in `load_project` and
raises `ProjectConfigError` on bad input. `db_path` is resolved against the
project dir like other paths. `ProjectConfig` gains a `storage:
StorageConfig` field with a default-constructed instance, so projects with
no `[storage]` section work identically to today.

A single DB file may serve multiple projects if they share `db_path` (e.g.
`../shared.db`). `runs.project_name` distinguishes them — queries can scope
to a project with `WHERE project_name = ?`. This is a feature, not a
constraint to defend against.

## Schema

Schema version 1, stored in `_schema_meta`. SQLite types shown; DuckDB uses
native equivalents (`BIGINT`, `DOUBLE`, `BOOLEAN`, `JSON`).

```sql
CREATE TABLE _schema_meta (
  schema_version INTEGER NOT NULL,
  created_at_utc TEXT NOT NULL,
  reddit_researcher_version TEXT NOT NULL
);

CREATE TABLE runs (
  run_dir          TEXT PRIMARY KEY,   -- canonical absolute path
  project_name     TEXT,
  mode             TEXT NOT NULL,      -- 'subreddit' | 'search'
  scope            TEXT NOT NULL,      -- e.g. 'AskReddit' or 'mo-cannabis-combined'
  status           TEXT NOT NULL,
  scraped_at_utc   TEXT NOT NULL,
  post_count       INTEGER NOT NULL,
  comment_count    INTEGER NOT NULL,
  schema_version   INTEGER NOT NULL,   -- the manifest's schema_version (not the DB's)
  manifest_json    TEXT NOT NULL,      -- full manifest, verbatim
  synced_at_utc    TEXT NOT NULL
);

CREATE TABLE posts (
  run_dir          TEXT NOT NULL,
  post_id          TEXT NOT NULL,
  subreddit        TEXT,
  search_term      TEXT NOT NULL DEFAULT '',  -- '' for subreddit-mode rows
  title            TEXT NOT NULL,
  author           TEXT,
  selftext         TEXT NOT NULL,
  url              TEXT NOT NULL,
  permalink        TEXT NOT NULL,
  score            INTEGER NOT NULL,
  upvote_ratio     REAL,
  num_comments     INTEGER NOT NULL,
  created_utc      REAL,
  over_18          INTEGER NOT NULL,    -- 0/1
  is_self          INTEGER NOT NULL,
  link_flair_text  TEXT,
  PRIMARY KEY (run_dir, post_id, search_term),
  FOREIGN KEY (run_dir) REFERENCES runs(run_dir) ON DELETE CASCADE
);
CREATE INDEX idx_posts_subreddit   ON posts(subreddit);
CREATE INDEX idx_posts_search_term ON posts(search_term);

CREATE TABLE comments (
  run_dir       TEXT NOT NULL,
  comment_id    TEXT NOT NULL,
  post_id       TEXT NOT NULL,
  parent_id     TEXT,
  author        TEXT,
  body          TEXT NOT NULL,
  score         INTEGER NOT NULL,
  created_utc   REAL,
  permalink     TEXT NOT NULL,
  depth         INTEGER NOT NULL,
  PRIMARY KEY (run_dir, comment_id),
  FOREIGN KEY (run_dir) REFERENCES runs(run_dir) ON DELETE CASCADE
);
CREATE INDEX idx_comments_post ON comments(run_dir, post_id);

CREATE TABLE relevance_decisions (
  run_dir       TEXT NOT NULL,
  post_id       TEXT NOT NULL,
  search_term   TEXT NOT NULL DEFAULT '',
  subreddit     TEXT,
  decision      TEXT NOT NULL,        -- 'include' | 'review' | 'exclude'
  reason        TEXT NOT NULL,
  PRIMARY KEY (run_dir, post_id, search_term),
  FOREIGN KEY (run_dir) REFERENCES runs(run_dir) ON DELETE CASCADE
);
```

### Schema notes

- **Composite PK includes `search_term`.** In search mode, the same post can
  appear under multiple terms; each is a distinct row. Subreddit-mode rows use
  the empty string `''` (not `NULL`) so the PK constraint actually fires —
  SQLite treats NULLs as distinct in primary keys.
- **`manifest_json` stored verbatim.** Lets you query manifest fields the
  schema doesn't promote (e.g. `per_subreddit`, `search_fetch_errors`) without
  re-reading files, and survives manifest schema bumps without revving the DB
  schema.
- **`runs.schema_version` is the *manifest's* version**, not the DB schema's.
  The DB schema version lives in `_schema_meta` and starts at 1.
- **`run_dir` is the canonical absolute path** so the same run dir always maps
  to one row regardless of how the user typed the path.

## Sync logic

```python
def sync_run(sink: RunSink, run_dir: Path) -> SyncResult:
    manifest = normalize_manifest(json.loads((run_dir/"manifest.json").read_text()))
    posts = read_jsonl(run_dir/"normalized"/"posts.jsonl")
    comments = read_jsonl(run_dir/"normalized"/"comments.jsonl")
    review_path = run_dir/"review"/"relevance_review.jsonl"
    reviews = read_jsonl(review_path) if review_path.exists() else []

    with sink.transaction():
        sink.delete_run(run_dir)                           # cascades posts/comments/reviews
        sink.upsert_run(run_dir, manifest)
        sink.insert_posts(run_dir, posts)
        sink.insert_comments(run_dir, comments)
        sink.insert_relevance(run_dir, reviews)
    return SyncResult(run_dir=run_dir, posts=len(posts), ...)
```

Idempotent. `delete_run` + re-insert (rather than per-row upsert) is simpler,
atomic in a single transaction, and correctly drops rows that were removed from
JSONL. A crash mid-sync leaves the prior committed state intact.

`auto_sync = true` (the default) means `run_project` calls `sync_run` after
extract finishes — or after scrape if `--skip-extract` is passed. Sync failures
are logged via the run logger but do not fail the run. The JSONL is still on
disk; the user can re-sync later with `db sync`.

`db sync --all` with no explicit run-dir args walks the project's
`output_root` (or the CLI default `./runs` when unset) and syncs every run
dir whose `runs.synced_at_utc` is older than the manifest's `updated_at_utc`,
plus any run dir not yet present in the DB. Without `--all`, `db sync` with
no run-dir args is an error rather than an implicit walk — explicit beats
surprising.

## CLI surface

Three new subcommands under a `db` group, dispatched from
[cli.py](../../../reddit_researcher/cli.py):

```text
reddit-researcher db sync [<run-dir>...] [--project <path>] [--all] [--rebuild]
reddit-researcher db status [--project <path>]
reddit-researcher db query "<SQL>" [--project <path>] [--format table|json|csv]
```

- **`db sync`** — sync one or more run dirs. `--all` walks `output_root` and
  syncs everything stale or missing. `--rebuild` drops every table and re-runs
  the schema setup before syncing. `--project` selects a project; default is
  the cwd's `project.toml` (error with a clear message if absent).
- **`db status`** — prints engine, DB path, schema version, per-table row
  counts, and the 10 most recent runs.
- **`db query`** — opens a *read-only* connection, runs the SQL, formats the
  result. Default `--format table` uses a small in-tree text-table formatter
  (no new dep). `--format csv` uses stdlib `csv`. `--format json` emits a list
  of row-objects.

Read-only on `db query` is enforced by the connection itself — SQLite
`file:...?mode=ro` URI; DuckDB `read_only=True`. Catches accidents like
`DROP TABLE` rather than relying on the user to be careful.

## Module layout

Mirror the PRAW backend pattern:

```text
reddit_researcher/
  db.py            # RunSink Protocol, make_sink(), sync_run(), errors
  db_sqlite.py     # SqliteRunSink (concrete impl)
  db_duckdb.py     # DuckdbRunSink (lazy-imports duckdb)
```

`db.py` exposes:

- `RunSink` — `Protocol` with: `transaction()`, `upsert_run()`,
  `insert_posts()`, `insert_comments()`, `insert_relevance()`, `delete_run()`,
  `read_only_connect()`, `close()`.
- `make_sink(storage, project_dir) -> RunSink` — factory dispatching on
  `storage.engine`. Same shape as `make_reddit_client(scrape)` in
  [reddit_client.py](../../../reddit_researcher/reddit_client.py).
- `sync_run(sink, run_dir) -> SyncResult` — engine-agnostic.
- Errors: `DuckdbNotInstalled` (with install message), `SchemaVersionMismatch`
  (suggests `db sync --rebuild`).

`db_duckdb.py` does `import duckdb` at module top. The factory only imports
that module when `engine == "duckdb"`, so users without the extra never
trigger the import — same lazy-import strategy as
[praw_client.py](../../../reddit_researcher/praw_client.py).

## Error handling

- `DuckdbNotInstalled` — engine is `duckdb` but the package isn't installed.
  Surface install instructions: `pip install reddit-researcher[duckdb]`.
- `SchemaVersionMismatch` — DB's `_schema_meta.schema_version` differs from
  the current code's. Message tells the user to run `db sync --rebuild`.
- Missing `manifest.json` for a run dir → clear error from `db sync`, no DB
  mutation.
- `auto_sync` failures are logged via the run logger and don't fail the run.

## Testing

New `tests/test_db.py` covering, at minimum:

1. `sync_run` against a single subreddit-mode run (round-trips post/comment
   counts, manifest fields, relevance decisions).
2. `sync_run` against a search-mode run (verifies `search_term` PK semantics
   for posts that appear under multiple terms).
3. `sync_run` against a multi-sub run (verifies per-sub counts via SQL).
4. Idempotency: syncing the same run twice yields the same row counts.
5. Re-sync after editing JSONL: rows added/removed in JSONL are reflected.
6. `--rebuild`: drops and recreates clean.
7. `SchemaVersionMismatch` raised when `_schema_meta.schema_version` is wrong.
8. `auto_sync = true`: `run_project` populates the DB; sync failure does not
   fail the run.
9. `auto_sync = false`: no DB writes happen during `run_project`.
10. `make_sink` raises `DuckdbNotInstalled` when duckdb is missing and
    engine is `duckdb`.
11. `db query` rejects writes (`DROP TABLE` raises a read-only error).

DuckDB tests skip-if-not-installed, matching the PRAW test pattern. Existing
coverage gate of 85% must continue to pass.

## Packaging

- `[project.optional-dependencies]` in `pyproject.toml` gains a
  `duckdb = ["duckdb>=0.10"]` extra. Installs via
  `pip install reddit-researcher[duckdb]`.

## Documentation

- New "Storage" section in [docs/architecture.md](../../architecture.md)
  describing the sink, when it runs, and the schema (with a small ER blurb).
- README gets a short "Querying across runs" section showing one or two
  example queries against the SQLite DB.
- CHANGELOG entry under `0.2.0-beta` covering the new `[storage]` section,
  the `db` subcommands, and the optional `[duckdb]` extra.

## Risks

- **DuckDB version churn.** DuckDB has historically broken file-format
  compatibility between minor releases. Pinning `>=0.10` is loose; we accept
  that users upgrading DuckDB may need `db sync --rebuild`. Documented in the
  CHANGELOG.
- **JSONL is canonical, but `manifest_json` in the DB can drift** if a sync is
  skipped after a manual manifest edit. `db sync` with no args re-syncs anything
  stale, so the workflow is: edit, then `db sync`.
- **Foreign keys in SQLite are off by default.** The sink must execute
  `PRAGMA foreign_keys = ON` on every connection or the cascade delete in
  `delete_run` won't fire. Caught in tests.
