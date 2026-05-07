# SQLite/DuckDB sink — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a queryable SQLite database (with optional DuckDB extra) populated post-hoc from each run's JSONL files, so cross-run analysis becomes a SQL query instead of an ad-hoc script.

**Architecture:** A `RunSink` Protocol with engine-specific implementations (`SqliteRunSink`, `DuckdbRunSink`), dispatched by a `make_sink()` factory that mirrors the existing `make_reddit_client()` factory. A small engine-agnostic `sync_run()` reads JSONL/manifest and calls sink methods inside a transaction. The pipeline's `run_project()` calls `sync_run()` at the end (when `auto_sync=true`); failures are logged and never fail the run. JSONL stays canonical; `db sync --rebuild` is the recovery path.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), optional duckdb (>=0.10), argparse, pytest.

**Spec:** [docs/superpowers/specs/2026-05-07-sqlite-duckdb-sink-design.md](../specs/2026-05-07-sqlite-duckdb-sink-design.md)

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `reddit_researcher/config.py`        | modify | Add `StorageConfig`, `VALID_DB_ENGINES`, parse `[storage]` |
| `reddit_researcher/db.py`            | create | `RunSink` Protocol, `make_sink()` factory, `sync_run()`, errors, `SyncResult` |
| `reddit_researcher/db_sqlite.py`     | create | `SqliteRunSink` concrete impl, schema DDL, FK pragma |
| `reddit_researcher/db_duckdb.py`     | create | `DuckdbRunSink` impl with lazy duckdb import |
| `reddit_researcher/pipeline.py`      | modify | Call `sync_run()` from `run_project()` when `auto_sync=true` |
| `reddit_researcher/cli.py`           | modify | New `db sync`/`db status`/`db query` subcommands |
| `pyproject.toml`                     | modify | Add `duckdb` optional extra |
| `tests/test_db_sqlite.py`            | create | Round-trip, idempotency, schema, FK cascade |
| `tests/test_db_duckdb.py`            | create | Skip-if-not-installed parallel of sqlite tests |
| `tests/test_db_cli.py`               | create | `db sync`/`status`/`query` CLI surface |
| `tests/test_db_pipeline.py`          | create | `auto_sync` integration into `run_project` |
| `tests/test_config.py`               | modify | `[storage]` parsing + validation tests |
| `docs/architecture.md`               | modify | Storage section |
| `README.md`                          | modify | "Querying across runs" section |
| `CHANGELOG.md`                       | modify | 0.2.0-beta entry |

---

## Task 1: StorageConfig dataclass + parser + validation

**Files:**
- Modify: `reddit_researcher/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for `StorageConfig` parsing**

Add to `tests/test_config.py` (top of file imports already include `load_project`, `ProjectConfigError`; add `StorageConfig` to the import):

```python
def test_storage_defaults_when_section_omitted(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n', encoding="utf-8"
    )
    project = load_project(project_dir / "project.toml")
    assert project.storage.engine == "sqlite"
    assert project.storage.db_path == (project_dir / "research.db").resolve()
    assert project.storage.auto_sync is True


def test_storage_engine_validated(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n'
        '[storage]\nengine = "postgres"\n',
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigError, match="invalid storage.engine"):
        load_project(project_dir / "project.toml")


def test_storage_db_path_resolved_relative_to_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n'
        '[storage]\ndb_path = "../shared.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    project = load_project(project_dir / "project.toml")
    assert project.storage.db_path == (project_dir.parent / "shared.db").resolve()
    assert project.storage.auto_sync is False
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_config.py -k storage -v`
Expected: collection or import error referencing `StorageConfig`.

- [ ] **Step 3: Add `StorageConfig` and parsing to `reddit_researcher/config.py`**

Near the existing `VALID_BACKENDS` constant, add:

```python
VALID_DB_ENGINES = {"sqlite", "duckdb"}
```

Add a new dataclass next to `AnalyzeConfig`:

```python
@dataclass
class StorageConfig:
    engine: str = "sqlite"
    db_path: Path = field(default_factory=lambda: Path("research.db"))
    auto_sync: bool = True
```

Add `storage` field to `ProjectConfig`:

```python
@dataclass
class ProjectConfig:
    name: str
    description: str
    project_dir: Path
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    analyze: AnalyzeConfig = field(default_factory=AnalyzeConfig)
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    output_root: Path | None = None
```

In `load_project`, after the `relevance = RelevanceConfig(...)` block and before `output_root = ...`, add:

```python
storage_raw = raw.get("storage", {})
storage_engine = storage_raw.get("engine", "sqlite")
if storage_engine not in VALID_DB_ENGINES:
    raise ProjectConfigError(
        f"invalid storage.engine: {storage_engine!r}. Must be one of {sorted(VALID_DB_ENGINES)}.",
        path=config_path,
    )
storage_db_path_raw = storage_raw.get("db_path", "research.db")
storage_db_path = _resolve_path(storage_db_path_raw, base_dir)
if storage_db_path is None:
    storage_db_path = (base_dir / "research.db").resolve()
storage = StorageConfig(
    engine=storage_engine,
    db_path=storage_db_path,
    auto_sync=bool(storage_raw.get("auto_sync", True)),
)
```

Pass `storage=storage` to the `ProjectConfig(...)` constructor at the bottom of `load_project`.

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_config.py -k storage -v`
Expected: 3 passed.

- [ ] **Step 5: Run full test suite**

Run: `pytest -q`
Expected: all tests pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/config.py tests/test_config.py
git commit -m "feat: add StorageConfig and [storage] section parser"
```

---

## Task 2: `RunSink` protocol, factory, and error types

**Files:**
- Create: `reddit_researcher/db.py`
- Create: `tests/test_db_sqlite.py` (skeleton — only the factory test in this task)

- [ ] **Step 1: Write failing test for the factory**

Create `tests/test_db_sqlite.py`:

```python
"""Tests for the SQLite RunSink and the engine-agnostic sync_run()."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import (
    DuckdbNotInstalled,
    RunSink,
    SchemaVersionMismatch,
    SyncResult,
    make_sink,
    sync_run,
)
from reddit_researcher.db_sqlite import SCHEMA_VERSION, SqliteRunSink


def test_factory_returns_sqlite_sink_by_default(tmp_path: Path) -> None:
    storage = StorageConfig(engine="sqlite", db_path=tmp_path / "research.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        assert isinstance(sink, SqliteRunSink)
        assert (tmp_path / "research.db").exists()
    finally:
        sink.close()


def test_factory_raises_for_unknown_engine(tmp_path: Path) -> None:
    storage = StorageConfig(engine="postgres", db_path=tmp_path / "x.db")
    with pytest.raises(ValueError, match="unknown storage engine"):
        make_sink(storage, project_dir=tmp_path)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_sqlite.py -v`
Expected: ImportError on `reddit_researcher.db`.

- [ ] **Step 3: Create `reddit_researcher/db.py`**

```python
"""Database sink — engine-agnostic surface.

`RunSink` is a Protocol implemented by `SqliteRunSink` (default, stdlib) and
`DuckdbRunSink` (optional `[duckdb]` extra). `make_sink()` dispatches on
`StorageConfig.engine`. `sync_run()` is the engine-agnostic logic that reads
a run dir's JSONL + manifest and writes them through the sink in one
transaction.

JSONL on disk is the source of truth. The DB is a derived view; deleting it
is always safe — re-sync from JSONL.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import StorageConfig
from .manifest import normalize_manifest
from .storage import read_jsonl


class DuckdbNotInstalled(RuntimeError):
    """Raised when the `duckdb` extra has not been installed."""


class SchemaVersionMismatch(RuntimeError):
    """Raised when the on-disk DB schema version differs from the current code's."""


@dataclass
class SyncResult:
    run_dir: Path
    posts: int
    comments: int
    relevance: int


class RunSink(Protocol):
    """Engine-agnostic write surface for one run's data."""

    def transaction(self) -> AbstractContextManager[Any]: ...

    def upsert_run(self, run_dir: Path, manifest: dict[str, Any]) -> None: ...

    def insert_posts(self, run_dir: Path, posts: list[dict[str, Any]]) -> None: ...

    def insert_comments(self, run_dir: Path, comments: list[dict[str, Any]]) -> None: ...

    def insert_relevance(self, run_dir: Path, decisions: list[dict[str, Any]]) -> None: ...

    def delete_run(self, run_dir: Path) -> None: ...

    def read_only_connect(self) -> Any: ...

    def rebuild(self) -> None: ...

    def close(self) -> None: ...


def make_sink(storage: StorageConfig, project_dir: Path) -> RunSink:
    """Build a RunSink for the given storage config.

    The duckdb branch lazy-imports its module so users without the extra never
    hit the import.
    """
    db_path = storage.db_path
    if not db_path.is_absolute():
        db_path = (project_dir / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if storage.engine == "sqlite":
        from .db_sqlite import SqliteRunSink

        return SqliteRunSink(db_path)
    if storage.engine == "duckdb":
        try:
            from .db_duckdb import DuckdbRunSink
        except DuckdbNotInstalled:
            raise
        return DuckdbRunSink(db_path)
    raise ValueError(f"unknown storage engine: {storage.engine!r}")


def sync_run(sink: RunSink, run_dir: Path) -> SyncResult:
    """Read JSONL + manifest from a run dir and upsert into the sink.

    Idempotent — re-syncing the same run dir is safe. The whole sync runs in
    one transaction, so a crash mid-sync leaves prior state untouched.
    """
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json under {run_dir}")
    manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))

    posts_path = run_dir / "normalized" / "posts.jsonl"
    comments_path = run_dir / "normalized" / "comments.jsonl"
    review_path = run_dir / "review" / "relevance_review.jsonl"

    posts = read_jsonl(posts_path) if posts_path.exists() else []
    comments = read_jsonl(comments_path) if comments_path.exists() else []
    reviews = read_jsonl(review_path) if review_path.exists() else []

    with sink.transaction():
        sink.delete_run(run_dir)
        sink.upsert_run(run_dir, manifest)
        sink.insert_posts(run_dir, posts)
        sink.insert_comments(run_dir, comments)
        sink.insert_relevance(run_dir, reviews)

    return SyncResult(
        run_dir=run_dir,
        posts=len(posts),
        comments=len(comments),
        relevance=len(reviews),
    )
```

- [ ] **Step 4: Create `reddit_researcher/db_sqlite.py` with the bare class**

```python
"""SQLite implementation of `RunSink`.

Stdlib-only. JSONL on disk is canonical; this DB is a derived index for
queries. Schema is created on open. Foreign keys are enforced via PRAGMA.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import __version__ as RR_VERSION
from .db import SchemaVersionMismatch

SCHEMA_VERSION = 1

_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS _schema_meta (
      schema_version INTEGER NOT NULL,
      created_at_utc TEXT NOT NULL,
      reddit_researcher_version TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
      run_dir          TEXT PRIMARY KEY,
      project_name     TEXT,
      mode             TEXT NOT NULL,
      scope            TEXT NOT NULL,
      status           TEXT NOT NULL,
      scraped_at_utc   TEXT NOT NULL,
      post_count       INTEGER NOT NULL,
      comment_count    INTEGER NOT NULL,
      schema_version   INTEGER NOT NULL,
      manifest_json    TEXT NOT NULL,
      synced_at_utc    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posts (
      run_dir          TEXT NOT NULL,
      post_id          TEXT NOT NULL,
      subreddit        TEXT,
      search_term      TEXT NOT NULL DEFAULT '',
      title            TEXT NOT NULL,
      author           TEXT,
      selftext         TEXT NOT NULL,
      url              TEXT NOT NULL,
      permalink        TEXT NOT NULL,
      score            INTEGER NOT NULL,
      upvote_ratio     REAL,
      num_comments     INTEGER NOT NULL,
      created_utc      REAL,
      over_18          INTEGER NOT NULL,
      is_self          INTEGER NOT NULL,
      link_flair_text  TEXT,
      PRIMARY KEY (run_dir, post_id, search_term),
      FOREIGN KEY (run_dir) REFERENCES runs(run_dir) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_posts_subreddit   ON posts(subreddit)",
    "CREATE INDEX IF NOT EXISTS idx_posts_search_term ON posts(search_term)",
    """
    CREATE TABLE IF NOT EXISTS comments (
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(run_dir, post_id)",
    """
    CREATE TABLE IF NOT EXISTS relevance_decisions (
      run_dir       TEXT NOT NULL,
      post_id       TEXT NOT NULL,
      search_term   TEXT NOT NULL DEFAULT '',
      subreddit     TEXT,
      decision      TEXT NOT NULL,
      reason        TEXT NOT NULL,
      PRIMARY KEY (run_dir, post_id, search_term),
      FOREIGN KEY (run_dir) REFERENCES runs(run_dir) ON DELETE CASCADE
    )
    """,
]


class SqliteRunSink:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        for stmt in _SCHEMA_DDL:
            cur.execute(stmt)
        row = cur.execute("SELECT schema_version FROM _schema_meta LIMIT 1").fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO _schema_meta (schema_version, created_at_utc, reddit_researcher_version) "
                "VALUES (?, ?, ?)",
                (SCHEMA_VERSION, datetime.now(UTC).isoformat(), RR_VERSION),
            )
        else:
            existing = int(row[0])
            if existing != SCHEMA_VERSION:
                raise SchemaVersionMismatch(
                    f"DB schema_version is {existing}; expected {SCHEMA_VERSION}. "
                    f"Run `reddit-researcher db sync --rebuild` to recreate from JSONL."
                )
        self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # sqlite3 driver is in autocommit-default; BEGIN to start an explicit txn.
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def upsert_run(self, run_dir: Path, manifest: dict[str, Any]) -> None:
        # Filled in Task 3.
        raise NotImplementedError

    def insert_posts(self, run_dir: Path, posts: list[dict[str, Any]]) -> None:
        # Filled in Task 4.
        raise NotImplementedError

    def insert_comments(self, run_dir: Path, comments: list[dict[str, Any]]) -> None:
        # Filled in Task 5.
        raise NotImplementedError

    def insert_relevance(self, run_dir: Path, decisions: list[dict[str, Any]]) -> None:
        # Filled in Task 6.
        raise NotImplementedError

    def delete_run(self, run_dir: Path) -> None:
        # Filled in Task 3.
        raise NotImplementedError

    def read_only_connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def rebuild(self) -> None:
        # Filled in Task 8.
        raise NotImplementedError

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 5: Run tests — expect pass**

Run: `pytest tests/test_db_sqlite.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add reddit_researcher/db.py reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: RunSink protocol, make_sink factory, SQLite skeleton"
```

---

## Task 3: SQLite — `upsert_run` and `delete_run`

**Files:**
- Modify: `reddit_researcher/db_sqlite.py`
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_sqlite.py`:

```python
def _make_run_dir(tmp_path: Path, *, scope: str = "AskReddit", mode: str = "subreddit") -> Path:
    """Create a minimal run dir with manifest + empty JSONL files."""
    run_dir = tmp_path / "runs" / scope / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "status": "complete",
        "subreddits": [scope] if mode == "subreddit" else [],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 0,
        "comment_count": 0,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "normalized" / "posts.jsonl").write_text("", encoding="utf-8")
    (run_dir / "normalized" / "comments.jsonl").write_text("", encoding="utf-8")
    return run_dir


def test_upsert_run_inserts_one_row(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
        ro = sink.read_only_connect()
        try:
            row = ro.execute("SELECT mode, scope, status, post_count FROM runs").fetchone()
        finally:
            ro.close()
        assert row == ("subreddit", "AskReddit", "complete", 0)
    finally:
        sink.close()


def test_upsert_run_replaces_existing(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        m1 = json.loads((run_dir / "manifest.json").read_text())
        m2 = dict(m1)
        m2["status"] = "fetching_comments"
        with sink.transaction():
            sink.upsert_run(run_dir, m1)
        with sink.transaction():
            sink.upsert_run(run_dir, m2)
        ro = sink.read_only_connect()
        try:
            rows = ro.execute("SELECT status FROM runs").fetchall()
        finally:
            ro.close()
        assert rows == [("fetching_comments",)]
    finally:
        sink.close()


def test_delete_run_removes_row(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
            sink.delete_run(run_dir)
        ro = sink.read_only_connect()
        try:
            count = ro.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            ro.close()
        assert count == 0
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_sqlite.py -k "upsert_run or delete_run" -v`
Expected: NotImplementedError on the relevant calls.

- [ ] **Step 3: Implement `upsert_run` and `delete_run` in `db_sqlite.py`**

Replace the `upsert_run` and `delete_run` stubs:

```python
    def upsert_run(self, run_dir: Path, manifest: dict[str, Any]) -> None:
        run_dir_str = str(run_dir.resolve())
        subs = manifest.get("subreddits") or []
        if manifest.get("mode") == "search":
            scope = manifest.get("subreddit") or "all-reddit-search"
        elif len(subs) == 1:
            scope = subs[0]
        elif subs:
            from .storage import multi_subreddit_scope

            scope = multi_subreddit_scope(subs)
        else:
            scope = manifest.get("subreddit") or "unknown"
        self.conn.execute(
            "INSERT OR REPLACE INTO runs ("
            " run_dir, project_name, mode, scope, status, scraped_at_utc,"
            " post_count, comment_count, schema_version, manifest_json, synced_at_utc"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_dir_str,
                manifest.get("project_name"),
                manifest.get("mode", "unknown"),
                scope,
                manifest.get("status", "unknown"),
                manifest.get("scraped_at_utc", ""),
                int(manifest.get("post_count", 0)),
                int(manifest.get("comment_count", 0)),
                int(manifest.get("schema_version", 0)),
                json.dumps(manifest, ensure_ascii=True),
                datetime.now(UTC).isoformat(),
            ),
        )

    def delete_run(self, run_dir: Path) -> None:
        run_dir_str = str(run_dir.resolve())
        # Cascade clears posts/comments/relevance_decisions via FK.
        self.conn.execute("DELETE FROM runs WHERE run_dir = ?", (run_dir_str,))
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_sqlite.py -k "upsert_run or delete_run" -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: SqliteRunSink upsert_run + delete_run"
```

---

## Task 4: SQLite — `insert_posts`

**Files:**
- Modify: `reddit_researcher/db_sqlite.py`
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_sqlite.py`:

```python
def _post_row(post_id: str, subreddit: str, *, search_term: str | None = None) -> dict:
    row = {
        "id": post_id,
        "subreddit": subreddit,
        "title": f"Title for {post_id}",
        "author": "alice",
        "selftext": "body",
        "url": f"https://reddit.com/r/{subreddit}/{post_id}",
        "permalink": f"/r/{subreddit}/comments/{post_id}/",
        "score": 42,
        "upvote_ratio": 0.95,
        "num_comments": 7,
        "created_utc": 1700000000.0,
        "over_18": False,
        "is_self": True,
        "link_flair_text": None,
        "sort": "top",
        "time_filter": "month",
        "comments": [],
    }
    if search_term is not None:
        row["search_term"] = search_term
    return row


def test_insert_posts_subreddit_mode(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
            sink.insert_posts(run_dir, [_post_row("a1", "AskReddit"), _post_row("a2", "AskReddit")])
        ro = sink.read_only_connect()
        try:
            rows = ro.execute("SELECT post_id, subreddit, search_term FROM posts ORDER BY post_id").fetchall()
        finally:
            ro.close()
        assert rows == [("a1", "AskReddit", ""), ("a2", "AskReddit", "")]
    finally:
        sink.close()


def test_insert_posts_search_mode_dedupes_same_post_under_different_terms(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path, scope="all-reddit-search", mode="search")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
            sink.insert_posts(
                run_dir,
                [
                    _post_row("p1", "Tools", search_term="vim"),
                    _post_row("p1", "Tools", search_term="emacs"),  # same post_id, different term
                ],
            )
        ro = sink.read_only_connect()
        try:
            rows = ro.execute("SELECT post_id, search_term FROM posts ORDER BY search_term").fetchall()
        finally:
            ro.close()
        assert rows == [("p1", "emacs"), ("p1", "vim")]
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_sqlite.py -k insert_posts -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `insert_posts`**

Replace the `insert_posts` stub:

```python
    def insert_posts(self, run_dir: Path, posts: list[dict[str, Any]]) -> None:
        if not posts:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str,
                str(post.get("id", "")),
                post.get("subreddit"),
                str(post.get("search_term", "")),
                str(post.get("title", "")),
                post.get("author"),
                str(post.get("selftext", "")),
                str(post.get("url", "")),
                str(post.get("permalink", "")),
                int(post.get("score", 0) or 0),
                post.get("upvote_ratio"),
                int(post.get("num_comments", 0) or 0),
                post.get("created_utc"),
                1 if post.get("over_18") else 0,
                1 if post.get("is_self") else 0,
                post.get("link_flair_text"),
            )
            for post in posts
        ]
        self.conn.executemany(
            "INSERT INTO posts ("
            " run_dir, post_id, subreddit, search_term, title, author, selftext,"
            " url, permalink, score, upvote_ratio, num_comments, created_utc,"
            " over_18, is_self, link_flair_text"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_sqlite.py -k insert_posts -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: SqliteRunSink insert_posts (subreddit + search modes)"
```

---

## Task 5: SQLite — `insert_comments`

**Files:**
- Modify: `reddit_researcher/db_sqlite.py`
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_db_sqlite.py`:

```python
def _comment_row(comment_id: str, post_id: str) -> dict:
    return {
        "id": comment_id,
        "post_id": post_id,
        "parent_id": f"t3_{post_id}",
        "author": "bob",
        "body": "interesting",
        "score": 3,
        "created_utc": 1700000100.0,
        "permalink": f"/r/x/comments/{post_id}/_/{comment_id}/",
        "depth": 0,
    }


def test_insert_comments_round_trips(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
            sink.insert_comments(
                run_dir,
                [_comment_row("c1", "a1"), _comment_row("c2", "a1")],
            )
        ro = sink.read_only_connect()
        try:
            rows = ro.execute(
                "SELECT comment_id, post_id, body, score FROM comments ORDER BY comment_id"
            ).fetchall()
        finally:
            ro.close()
        assert rows == [("c1", "a1", "interesting", 3), ("c2", "a1", "interesting", 3)]
    finally:
        sink.close()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/test_db_sqlite.py -k insert_comments -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `insert_comments`**

Replace the `insert_comments` stub:

```python
    def insert_comments(self, run_dir: Path, comments: list[dict[str, Any]]) -> None:
        if not comments:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str,
                str(comment.get("id", "")),
                str(comment.get("post_id", "")),
                comment.get("parent_id"),
                comment.get("author"),
                str(comment.get("body", "")),
                int(comment.get("score", 0) or 0),
                comment.get("created_utc"),
                str(comment.get("permalink", "")),
                int(comment.get("depth", 0) or 0),
            )
            for comment in comments
        ]
        self.conn.executemany(
            "INSERT INTO comments ("
            " run_dir, comment_id, post_id, parent_id, author, body, score,"
            " created_utc, permalink, depth"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/test_db_sqlite.py -k insert_comments -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: SqliteRunSink insert_comments"
```

---

## Task 6: SQLite — `insert_relevance`

**Files:**
- Modify: `reddit_researcher/db_sqlite.py`
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_db_sqlite.py`:

```python
def test_insert_relevance_round_trips(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _make_run_dir(tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        decisions = [
            {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "matches keyword"},
            {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "no match"},
        ]
        with sink.transaction():
            sink.upsert_run(run_dir, manifest)
            sink.insert_relevance(run_dir, decisions)
        ro = sink.read_only_connect()
        try:
            rows = ro.execute(
                "SELECT post_id, decision, reason FROM relevance_decisions ORDER BY post_id"
            ).fetchall()
        finally:
            ro.close()
        assert rows == [("p1", "include", "matches keyword"), ("p2", "exclude", "no match")]
    finally:
        sink.close()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/test_db_sqlite.py -k insert_relevance -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `insert_relevance`**

Replace the `insert_relevance` stub:

```python
    def insert_relevance(self, run_dir: Path, decisions: list[dict[str, Any]]) -> None:
        if not decisions:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str,
                str(decision.get("post_id", "")),
                str(decision.get("search_term", "")),
                decision.get("subreddit"),
                str(decision.get("decision", "")),
                str(decision.get("reason", "")),
            )
            for decision in decisions
        ]
        self.conn.executemany(
            "INSERT INTO relevance_decisions ("
            " run_dir, post_id, search_term, subreddit, decision, reason"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/test_db_sqlite.py -k insert_relevance -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: SqliteRunSink insert_relevance"
```

---

## Task 7: `sync_run` end-to-end + idempotency + FK cascade

**Files:**
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_sqlite.py`:

```python
from reddit_researcher.storage import append_jsonl


def _write_full_run(tmp_path: Path, *, scope: str = "AskReddit") -> Path:
    """Create a run dir with one post, two comments, and two relevance decisions."""
    run_dir = _make_run_dir(tmp_path, scope=scope)
    posts_path = run_dir / "normalized" / "posts.jsonl"
    comments_path = run_dir / "normalized" / "comments.jsonl"
    review_path = run_dir / "review" / "relevance_review.jsonl"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(posts_path, _post_row("p1", scope))
    append_jsonl(comments_path, _comment_row("c1", "p1"))
    append_jsonl(comments_path, _comment_row("c2", "p1"))
    append_jsonl(
        review_path,
        {"post_id": "p1", "subreddit": scope, "decision": "include", "reason": "ok"},
    )
    append_jsonl(
        review_path,
        {"post_id": "px", "subreddit": scope, "decision": "exclude", "reason": "off-topic"},
    )
    return run_dir


def test_sync_run_round_trip(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        result = sync_run(sink, run_dir)
        assert result.posts == 1
        assert result.comments == 2
        assert result.relevance == 2
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
            assert ro.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 2
            assert ro.execute("SELECT COUNT(*) FROM relevance_decisions").fetchone()[0] == 2
        finally:
            ro.close()
    finally:
        sink.close()


def test_sync_run_idempotent(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        sync_run(sink, run_dir)
        sync_run(sink, run_dir)
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
            assert ro.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 2
        finally:
            ro.close()
    finally:
        sink.close()


def test_sync_run_reflects_jsonl_changes(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        sync_run(sink, run_dir)
        # Add another comment to the JSONL on disk.
        append_jsonl(run_dir / "normalized" / "comments.jsonl", _comment_row("c3", "p1"))
        sync_run(sink, run_dir)
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 3
        finally:
            ro.close()
    finally:
        sink.close()


def test_delete_run_cascades_to_children(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        sync_run(sink, run_dir)
        with sink.transaction():
            sink.delete_run(run_dir)
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
            assert ro.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0
            assert ro.execute("SELECT COUNT(*) FROM relevance_decisions").fetchone()[0] == 0
        finally:
            ro.close()
    finally:
        sink.close()


def test_sync_run_missing_manifest_raises(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = tmp_path / "runs" / "empty" / "20260507-120000"
        run_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="no manifest.json"):
            sync_run(sink, run_dir)
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect pass (no impl change needed)**

Run: `pytest tests/test_db_sqlite.py -v`
Expected: all tests in file pass — `sync_run` and `delete_run` cascade are already wired.

If any fail, fix the underlying bug — do not skip.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_db_sqlite.py
git commit -m "test: sync_run round-trip, idempotency, JSONL re-sync, FK cascade"
```

---

## Task 8: SchemaVersionMismatch + `rebuild`

**Files:**
- Modify: `reddit_researcher/db_sqlite.py`
- Modify: `tests/test_db_sqlite.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_sqlite.py`:

```python
def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "r.db"
    storage = StorageConfig(db_path=db_path)
    # Open once to set up schema, then close.
    make_sink(storage, project_dir=tmp_path).close()
    # Tamper with the recorded version.
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE _schema_meta SET schema_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaVersionMismatch):
        make_sink(storage, project_dir=tmp_path)


def test_rebuild_drops_and_recreates(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        sync_run(sink, run_dir)
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        finally:
            ro.close()
        sink.rebuild()
        ro = sink.read_only_connect()
        try:
            # Tables exist but are empty.
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
            assert ro.execute("SELECT schema_version FROM _schema_meta").fetchone()[0] == SCHEMA_VERSION
        finally:
            ro.close()
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_sqlite.py -k "schema_version_mismatch or rebuild" -v`
Expected: `test_schema_version_mismatch_raises` passes (already wired in `_init_schema`), `test_rebuild_drops_and_recreates` fails (NotImplementedError on `rebuild`).

- [ ] **Step 3: Implement `rebuild` in `db_sqlite.py`**

Replace the `rebuild` stub:

```python
    def rebuild(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        for table in ("relevance_decisions", "comments", "posts", "runs", "_schema_meta"):
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()
        self._init_schema()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_sqlite.py -k "schema_version_mismatch or rebuild" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/db_sqlite.py tests/test_db_sqlite.py
git commit -m "feat: SchemaVersionMismatch on stale DB; rebuild() drops + recreates"
```

---

## Task 9: `auto_sync` integration in `run_project`

**Files:**
- Modify: `reddit_researcher/pipeline.py`
- Create: `tests/test_db_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db_pipeline.py`:

```python
"""Tests for auto_sync integration in pipeline.run_project."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from reddit_researcher.config import (
    AnalyzeConfig,
    ProjectConfig,
    ScrapeConfig,
    StorageConfig,
)
from reddit_researcher.models import CommentRecord, PostRecord
from reddit_researcher.pipeline import run_project


class _StubClient:
    """Minimal stand-in for the Reddit client. Returns one canned post."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        pass

    def fetch_posts(self, subreddit: str, sort: str, limit: int, time_filter: str | None):
        post = PostRecord(
            id="p1",
            subreddit=subreddit,
            title="t",
            author="a",
            selftext="body",
            url="https://reddit.com/p1",
            permalink="/r/x/comments/p1/",
            score=5,
            upvote_ratio=0.9,
            num_comments=1,
            created_utc=1700000000.0,
            over_18=False,
            is_self=True,
            link_flair_text=None,
            sort=sort,
            time_filter=time_filter,
        )
        return [post], {"backend": "stub"}

    def fetch_comments(self, permalink: str, post_id: str, limit: int):  # noqa: ARG002
        comment = CommentRecord(
            id="c1",
            post_id=post_id,
            parent_id=f"t3_{post_id}",
            author="b",
            body="hello",
            score=1,
            created_utc=1700000100.0,
            permalink=f"{permalink}c1",
            depth=0,
        )
        return [comment], []


@pytest.fixture
def patched_make_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reddit_researcher.pipeline.make_reddit_client",
        lambda scrape: _StubClient(),
    )


def _build_project(tmp_path: Path, *, auto_sync: bool) -> ProjectConfig:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    return ProjectConfig(
        name="demo",
        description="",
        project_dir=project_dir,
        scrape=ScrapeConfig(mode="subreddit", subreddits=["AskReddit"], post_limit=1, comment_limit=1),
        analyze=AnalyzeConfig(),
        storage=StorageConfig(db_path=project_dir / "r.db", auto_sync=auto_sync),
    )


def test_auto_sync_populates_db(tmp_path: Path, patched_make_client: None) -> None:  # noqa: ARG001
    project = _build_project(tmp_path, auto_sync=True)
    run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    db_path = project.project_dir / "r.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    finally:
        conn.close()


def test_auto_sync_disabled_does_not_create_db(tmp_path: Path, patched_make_client: None) -> None:  # noqa: ARG001
    project = _build_project(tmp_path, auto_sync=False)
    run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    assert not (project.project_dir / "r.db").exists()


def test_auto_sync_failure_does_not_fail_run(
    tmp_path: Path, patched_make_client: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG001
) -> None:
    project = _build_project(tmp_path, auto_sync=True)

    def boom(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        raise RuntimeError("disk full")

    monkeypatch.setattr("reddit_researcher.pipeline.sync_run", boom)
    # Should not raise.
    run_dir = run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    assert (run_dir / "normalized" / "posts.jsonl").exists()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_pipeline.py -v`
Expected: failures (no DB written; `sync_run` not called from pipeline yet).

- [ ] **Step 3: Wire `sync_run` into `run_project`**

In `reddit_researcher/pipeline.py`, add to imports near the top:

```python
from .config import AnalyzeConfig, ProjectConfig, ScrapeConfig
from .db import make_sink, sync_run
```

At the bottom of the existing `run_project` function — after the existing body that returns `scrape_dir` — replace the final `return` block. Find:

```python
    if skip_extract:
        return scrape_dir

    if project.analyze.prompt_file is None:
        return scrape_dir

    extract_from_run(run_dir=scrape_dir, analyze=project.analyze)
    return scrape_dir
```

Replace with:

```python
    if not skip_extract and project.analyze.prompt_file is not None:
        extract_from_run(run_dir=scrape_dir, analyze=project.analyze)

    if project.storage.auto_sync:
        try:
            sink = make_sink(project.storage, project_dir=project.project_dir)
        except Exception as exc:
            RunLogger(scrape_dir).info(f"auto_sync skipped: could not open DB: {exc}")
        else:
            try:
                sync_run(sink, scrape_dir)
            except Exception as exc:
                RunLogger(scrape_dir).info(f"auto_sync skipped: sync failed: {exc}")
            finally:
                sink.close()

    return scrape_dir
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_pipeline.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/pipeline.py tests/test_db_pipeline.py
git commit -m "feat: auto_sync hook in run_project; failures logged, never fail run"
```

---

## Task 10: CLI `db sync` subcommand

**Files:**
- Modify: `reddit_researcher/cli.py`
- Create: `tests/test_db_cli.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db_cli.py`:

```python
"""Tests for the `db` subcommand group."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reddit_researcher.cli import main as cli_main
from reddit_researcher.storage import append_jsonl


def _write_project_with_run(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "AskReddit"\n'
        '[storage]\ndb_path = "r.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": ["AskReddit"],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 1,
        "comment_count": 0,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    append_jsonl(
        run_dir / "normalized" / "posts.jsonl",
        {
            "id": "p1", "subreddit": "AskReddit", "title": "t", "author": "a",
            "selftext": "b", "url": "u", "permalink": "p", "score": 1,
            "upvote_ratio": 0.9, "num_comments": 0, "created_utc": 1.0,
            "over_18": False, "is_self": True, "link_flair_text": None,
            "sort": "top", "time_filter": "month", "comments": [],
        },
    )
    return project_dir, run_dir


def test_db_sync_one_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    rc = cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    assert rc == 0
    db_path = project_dir / "r.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    finally:
        conn.close()
    out = capsys.readouterr().out
    assert "synced" in out.lower()


def test_db_sync_all(tmp_path: Path) -> None:
    project_dir, _ = _write_project_with_run(tmp_path)
    # Override output_root via env-less path: pass --output-root via args is not on db sync;
    # we rely on the default ./runs heuristic. Move our run dir under the default location.
    runs_root = tmp_path / "runs"
    assert runs_root.exists()
    rc = cli_main(
        ["db", "sync", "--all", "--project", str(project_dir), "--output-root", str(runs_root)]
    )
    assert rc == 0
    conn = sqlite3.connect(project_dir / "r.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_sync_rebuild(tmp_path: Path) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    cli_main(["db", "sync", "--rebuild", str(run_dir), "--project", str(project_dir)])
    conn = sqlite3.connect(project_dir / "r.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_sync_no_args_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, _ = _write_project_with_run(tmp_path)
    rc = cli_main(["db", "sync", "--project", str(project_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "run-dir" in err.lower() or "--all" in err.lower()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_cli.py -v`
Expected: argparse errors — no `db` subcommand registered.

- [ ] **Step 3: Add `db` subparsers and dispatch in `cli.py`**

In `build_parser`, after the `review_parser = ...` block, add:

```python
    db_parser = subparsers.add_parser(
        "db",
        help="Query and sync the project's research DB.",
    )
    db_subs = db_parser.add_subparsers(dest="db_command", required=True)

    db_sync_parser = db_subs.add_parser("sync", help="Sync run dirs into the DB.")
    db_sync_parser.add_argument("run_dirs", nargs="*", help="One or more run directories.")
    db_sync_parser.add_argument("--project", default=None, help="Path to project.toml or its directory.")
    db_sync_parser.add_argument("--all", action="store_true", help="Sync every run under output_root.")
    db_sync_parser.add_argument(
        "--output-root", default=None,
        help="Override output_root when using --all. Defaults to project's output_root or ./runs.",
    )
    db_sync_parser.add_argument(
        "--rebuild", action="store_true",
        help="Drop and recreate all tables before syncing (recovers from schema mismatch).",
    )

    db_status_parser = db_subs.add_parser("status", help="Show DB engine, path, schema, row counts.")
    db_status_parser.add_argument("--project", default=None)

    db_query_parser = db_subs.add_parser("query", help="Run a read-only SQL query against the DB.")
    db_query_parser.add_argument("sql", help="SQL statement (read-only connection).")
    db_query_parser.add_argument("--project", default=None)
    db_query_parser.add_argument("--format", default="table", choices=["table", "json", "csv"])
```

In `_dispatch`, before the final `parser.error(...)`, add:

```python
    if args.command == "db":
        return _dispatch_db(args, parser)
```

Add a new `_dispatch_db` function near the bottom of `cli.py` (above `if __name__ == "__main__":`):

```python
def _dispatch_db(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .db import SchemaVersionMismatch, make_sink, sync_run

    project_arg = getattr(args, "project", None)
    if project_arg is None:
        candidate = Path.cwd() / "project.toml"
        if not candidate.exists():
            parser.error(
                "db: pass --project <path> or run from a directory containing project.toml."
            )
        project_path = candidate
    else:
        project_path = find_project_config(Path(project_arg))
    load_dotenvs_for(project_dir=project_path.parent, repo_root=REPO_ROOT)
    project = load_project(project_path)

    if args.db_command == "sync":
        return _db_sync(args, project, make_sink, sync_run, parser)
    if args.db_command == "status":
        return _db_status(project, make_sink)
    if args.db_command == "query":
        return _db_query(args, project, make_sink)
    parser.error(f"Unsupported db command: {args.db_command}")
    return 2


def _db_sync(args, project, make_sink, sync_run, parser) -> int:
    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        if args.rebuild:
            sink.rebuild()
        run_dirs = [Path(p) for p in (args.run_dirs or [])]
        if args.all:
            output_root = (
                Path(args.output_root) if args.output_root
                else (project.output_root or DEFAULT_OUTPUT_ROOT)
            )
            run_dirs.extend(_walk_run_dirs(output_root))
        if not run_dirs:
            parser.error(
                "db sync: pass one or more run directories, or --all with an output_root."
            )
        synced = 0
        for run_dir in run_dirs:
            sync_run(sink, run_dir)
            synced += 1
        print(f"synced {synced} run dir(s) into {project.storage.db_path}")
        return 0
    finally:
        sink.close()


def _walk_run_dirs(output_root: Path) -> list[Path]:
    """Yield every run dir under output_root that has a manifest.json."""
    if not output_root.exists():
        return []
    found: list[Path] = []
    for manifest_path in output_root.rglob("manifest.json"):
        found.append(manifest_path.parent)
    return found
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_cli.py -k "db_sync" -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/cli.py tests/test_db_cli.py
git commit -m "feat: 'db sync' CLI (one or many runs, --all walker, --rebuild)"
```

---

## Task 11: CLI `db status` subcommand

**Files:**
- Modify: `reddit_researcher/cli.py`
- Modify: `tests/test_db_cli.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_db_cli.py`:

```python
def test_db_status_shows_engine_and_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    rc = cli_main(["db", "status", "--project", str(project_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sqlite" in out
    assert "schema_version" in out
    assert "posts" in out
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/test_db_cli.py -k status -v`
Expected: NotImplementedError (no `_db_status`).

- [ ] **Step 3: Implement `_db_status`**

Add to `reddit_researcher/cli.py` (next to `_db_sync`):

```python
def _db_status(project, make_sink) -> int:
    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        ro = sink.read_only_connect()
        try:
            schema_row = ro.execute(
                "SELECT schema_version, created_at_utc, reddit_researcher_version FROM _schema_meta"
            ).fetchone()
            counts = {
                table: ro.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("runs", "posts", "comments", "relevance_decisions")
            }
            recent = ro.execute(
                "SELECT run_dir, mode, scope, status, post_count, comment_count "
                "FROM runs ORDER BY synced_at_utc DESC LIMIT 10"
            ).fetchall()
        finally:
            ro.close()
    finally:
        sink.close()

    print(f"engine:           {project.storage.engine}")
    print(f"db_path:          {project.storage.db_path}")
    if schema_row:
        print(f"schema_version:   {schema_row[0]} (created {schema_row[1]}, rr {schema_row[2]})")
    print("row counts:")
    for table, n in counts.items():
        print(f"  {table:<22} {n}")
    if recent:
        print("recent runs:")
        for run_dir, mode, scope, status, posts, comments in recent:
            print(f"  [{mode}] {scope:<24} {status:<18} {posts}p {comments}c  {run_dir}")
    return 0
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/test_db_cli.py -k status -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/cli.py tests/test_db_cli.py
git commit -m "feat: 'db status' prints engine, schema, row counts, recent runs"
```

---

## Task 12: CLI `db query` with read-only enforcement

**Files:**
- Modify: `reddit_researcher/cli.py`
- Modify: `tests/test_db_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_cli.py`:

```python
def test_db_query_table_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    rc = cli_main(
        ["db", "query", "SELECT post_id, subreddit FROM posts", "--project", str(project_dir)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "post_id" in out
    assert "p1" in out
    assert "AskReddit" in out


def test_db_query_json_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    cli_main(
        ["db", "query", "SELECT post_id FROM posts", "--project", str(project_dir), "--format", "json"]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload == [{"post_id": "p1"}]


def test_db_query_csv_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    cli_main(
        ["db", "query", "SELECT post_id FROM posts", "--project", str(project_dir), "--format", "csv"]
    )
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert lines[0] == "post_id"
    assert lines[1] == "p1"


def test_db_query_rejects_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    rc = cli_main(["db", "query", "DELETE FROM posts", "--project", str(project_dir)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "read" in err.lower() or "readonly" in err.lower()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_db_cli.py -k db_query -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `_db_query` and a small text-table formatter**

Add to `reddit_researcher/cli.py` (near `_db_status`):

```python
def _db_query(args, project, make_sink) -> int:
    import csv
    import sqlite3

    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        ro = sink.read_only_connect()
        try:
            try:
                cursor = ro.execute(args.sql)
            except sqlite3.OperationalError as exc:
                # Read-only mode in sqlite raises this for any write.
                print(f"error: {exc}", file=sys.stderr)
                return 1
            cols = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
        finally:
            ro.close()
    finally:
        sink.close()

    if args.format == "json":
        import json as _json

        payload = [dict(zip(cols, row)) for row in rows]
        print(_json.dumps(payload, ensure_ascii=True))
        return 0
    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        if cols:
            writer.writerow(cols)
        writer.writerows(rows)
        return 0
    # table
    print(_format_table(cols, rows))
    return 0


def _format_table(cols: list[str], rows: list[tuple]) -> str:
    if not cols:
        return "(no rows)"
    string_rows = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [len(c) for c in cols]
    for row in string_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    sep = "  ".join("-" * w for w in widths)
    header = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    body = "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths)) for row in string_rows)
    return f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}"
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_db_cli.py -k db_query -v`
Expected: 4 passed.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/cli.py tests/test_db_cli.py
git commit -m "feat: 'db query' read-only SQL with table/json/csv formatters"
```

---

## Task 13: DuckDB backend (optional)

**Files:**
- Create: `reddit_researcher/db_duckdb.py`
- Create: `tests/test_db_duckdb.py`
- Modify: `reddit_researcher/db.py` (already imports lazily; verify error path)

- [ ] **Step 1: Write tests (skip-if-not-installed)**

Create `tests/test_db_duckdb.py`:

```python
"""DuckDB-backed RunSink tests. Skip when the optional extra is missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")  # noqa: F841

from reddit_researcher.config import StorageConfig  # noqa: E402
from reddit_researcher.db import make_sink, sync_run  # noqa: E402
from reddit_researcher.db_duckdb import DuckdbRunSink  # noqa: E402


def _write_full_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": ["AskReddit"],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 1,
        "comment_count": 1,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "normalized" / "posts.jsonl").write_text(
        json.dumps({
            "id": "p1", "subreddit": "AskReddit", "title": "t", "author": "a",
            "selftext": "b", "url": "u", "permalink": "/p1", "score": 1,
            "upvote_ratio": 0.9, "num_comments": 0, "created_utc": 1.0,
            "over_18": False, "is_self": True, "link_flair_text": None,
            "sort": "top", "time_filter": "month", "comments": [],
        }) + "\n",
        encoding="utf-8",
    )
    (run_dir / "normalized" / "comments.jsonl").write_text(
        json.dumps({
            "id": "c1", "post_id": "p1", "parent_id": "t3_p1", "author": "b",
            "body": "hi", "score": 1, "created_utc": 1.0, "permalink": "/c1", "depth": 0,
        }) + "\n",
        encoding="utf-8",
    )
    (run_dir / "review" / "relevance_review.jsonl").write_text("", encoding="utf-8")
    return run_dir


def test_factory_returns_duckdb_sink(tmp_path: Path) -> None:
    storage = StorageConfig(engine="duckdb", db_path=tmp_path / "r.duckdb")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        assert isinstance(sink, DuckdbRunSink)
    finally:
        sink.close()


def test_duckdb_sync_round_trip(tmp_path: Path) -> None:
    storage = StorageConfig(engine="duckdb", db_path=tmp_path / "r.duckdb")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_dir = _write_full_run(tmp_path)
        result = sync_run(sink, run_dir)
        assert result.posts == 1
        assert result.comments == 1
        ro = sink.read_only_connect()
        try:
            assert ro.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        finally:
            ro.close()
    finally:
        sink.close()
```

- [ ] **Step 2: Add a non-skip test for the missing-package error path in `tests/test_db_sqlite.py`**

Add at the bottom of `tests/test_db_sqlite.py`:

```python
def test_make_sink_duckdb_not_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If `duckdb` import fails, make_sink raises DuckdbNotInstalled with install hint."""
    import sys as _sys

    # Force a fresh import of db_duckdb so its top-level `import duckdb` re-runs.
    monkeypatch.delitem(_sys.modules, "reddit_researcher.db_duckdb", raising=False)
    monkeypatch.setitem(_sys.modules, "duckdb", None)  # poisons future import duckdb
    storage = StorageConfig(engine="duckdb", db_path=tmp_path / "r.duckdb")
    with pytest.raises(DuckdbNotInstalled, match=r"pip install reddit-researcher\[duckdb\]"):
        make_sink(storage, project_dir=tmp_path)
```

- [ ] **Step 3: Create `reddit_researcher/db_duckdb.py`**

```python
"""DuckDB implementation of `RunSink` (optional)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import __version__ as RR_VERSION
from .db import DuckdbNotInstalled, SchemaVersionMismatch

try:
    import duckdb  # type: ignore[import-not-found]
except ImportError as exc:  # pragma: no cover
    raise DuckdbNotInstalled(
        "The DuckDB sink requires the `duckdb` extra. Install it with:\n"
        "  pip install reddit-researcher[duckdb]"
    ) from exc

SCHEMA_VERSION = 1

_SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS _schema_meta (
      schema_version INTEGER NOT NULL,
      created_at_utc VARCHAR NOT NULL,
      reddit_researcher_version VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
      run_dir          VARCHAR PRIMARY KEY,
      project_name     VARCHAR,
      mode             VARCHAR NOT NULL,
      scope            VARCHAR NOT NULL,
      status           VARCHAR NOT NULL,
      scraped_at_utc   VARCHAR NOT NULL,
      post_count       BIGINT NOT NULL,
      comment_count    BIGINT NOT NULL,
      schema_version   INTEGER NOT NULL,
      manifest_json    JSON NOT NULL,
      synced_at_utc    VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS posts (
      run_dir         VARCHAR NOT NULL,
      post_id         VARCHAR NOT NULL,
      subreddit       VARCHAR,
      search_term     VARCHAR NOT NULL DEFAULT '',
      title           VARCHAR NOT NULL,
      author          VARCHAR,
      selftext        VARCHAR NOT NULL,
      url             VARCHAR NOT NULL,
      permalink       VARCHAR NOT NULL,
      score           BIGINT NOT NULL,
      upvote_ratio    DOUBLE,
      num_comments    BIGINT NOT NULL,
      created_utc     DOUBLE,
      over_18         BOOLEAN NOT NULL,
      is_self         BOOLEAN NOT NULL,
      link_flair_text VARCHAR,
      PRIMARY KEY (run_dir, post_id, search_term)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comments (
      run_dir       VARCHAR NOT NULL,
      comment_id    VARCHAR NOT NULL,
      post_id       VARCHAR NOT NULL,
      parent_id     VARCHAR,
      author        VARCHAR,
      body          VARCHAR NOT NULL,
      score         BIGINT NOT NULL,
      created_utc   DOUBLE,
      permalink     VARCHAR NOT NULL,
      depth         INTEGER NOT NULL,
      PRIMARY KEY (run_dir, comment_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relevance_decisions (
      run_dir       VARCHAR NOT NULL,
      post_id       VARCHAR NOT NULL,
      search_term   VARCHAR NOT NULL DEFAULT '',
      subreddit     VARCHAR,
      decision      VARCHAR NOT NULL,
      reason        VARCHAR NOT NULL,
      PRIMARY KEY (run_dir, post_id, search_term)
    )
    """,
]


class DuckdbRunSink:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        for stmt in _SCHEMA_DDL:
            self.conn.execute(stmt)
        existing = self.conn.execute(
            "SELECT schema_version FROM _schema_meta LIMIT 1"
        ).fetchone()
        if existing is None:
            self.conn.execute(
                "INSERT INTO _schema_meta VALUES (?, ?, ?)",
                [SCHEMA_VERSION, datetime.now(UTC).isoformat(), RR_VERSION],
            )
        elif int(existing[0]) != SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                f"DuckDB schema_version is {existing[0]}; expected {SCHEMA_VERSION}. "
                f"Run `reddit-researcher db sync --rebuild`."
            )

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def upsert_run(self, run_dir: Path, manifest: dict[str, Any]) -> None:
        run_dir_str = str(run_dir.resolve())
        subs = manifest.get("subreddits") or []
        if manifest.get("mode") == "search":
            scope = manifest.get("subreddit") or "all-reddit-search"
        elif len(subs) == 1:
            scope = subs[0]
        elif subs:
            from .storage import multi_subreddit_scope

            scope = multi_subreddit_scope(subs)
        else:
            scope = manifest.get("subreddit") or "unknown"
        # DuckDB: no ON CONFLICT REPLACE, so DELETE + INSERT.
        self.conn.execute("DELETE FROM runs WHERE run_dir = ?", [run_dir_str])
        self.conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_dir_str,
                manifest.get("project_name"),
                manifest.get("mode", "unknown"),
                scope,
                manifest.get("status", "unknown"),
                manifest.get("scraped_at_utc", ""),
                int(manifest.get("post_count", 0)),
                int(manifest.get("comment_count", 0)),
                int(manifest.get("schema_version", 0)),
                json.dumps(manifest, ensure_ascii=True),
                datetime.now(UTC).isoformat(),
            ],
        )

    def insert_posts(self, run_dir: Path, posts: list[dict[str, Any]]) -> None:
        if not posts:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str, str(p.get("id", "")), p.get("subreddit"),
                str(p.get("search_term", "")), str(p.get("title", "")),
                p.get("author"), str(p.get("selftext", "")), str(p.get("url", "")),
                str(p.get("permalink", "")), int(p.get("score", 0) or 0),
                p.get("upvote_ratio"), int(p.get("num_comments", 0) or 0),
                p.get("created_utc"), bool(p.get("over_18")), bool(p.get("is_self")),
                p.get("link_flair_text"),
            )
            for p in posts
        ]
        self.conn.executemany(
            "INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def insert_comments(self, run_dir: Path, comments: list[dict[str, Any]]) -> None:
        if not comments:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str, str(c.get("id", "")), str(c.get("post_id", "")),
                c.get("parent_id"), c.get("author"), str(c.get("body", "")),
                int(c.get("score", 0) or 0), c.get("created_utc"),
                str(c.get("permalink", "")), int(c.get("depth", 0) or 0),
            )
            for c in comments
        ]
        self.conn.executemany(
            "INSERT INTO comments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def insert_relevance(self, run_dir: Path, decisions: list[dict[str, Any]]) -> None:
        if not decisions:
            return
        run_dir_str = str(run_dir.resolve())
        rows = [
            (
                run_dir_str, str(d.get("post_id", "")),
                str(d.get("search_term", "")), d.get("subreddit"),
                str(d.get("decision", "")), str(d.get("reason", "")),
            )
            for d in decisions
        ]
        self.conn.executemany(
            "INSERT INTO relevance_decisions VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def delete_run(self, run_dir: Path) -> None:
        run_dir_str = str(run_dir.resolve())
        # No FK cascade in our DuckDB schema — explicit cleanup.
        for table in ("relevance_decisions", "comments", "posts", "runs"):
            self.conn.execute(f"DELETE FROM {table} WHERE run_dir = ?", [run_dir_str])

    def read_only_connect(self) -> Any:
        return duckdb.connect(str(self.db_path), read_only=True)

    def rebuild(self) -> None:
        for table in ("relevance_decisions", "comments", "posts", "runs", "_schema_meta"):
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 4: Update `db.py` factory to use the typed error**

In `reddit_researcher/db.py`, replace the duckdb branch in `make_sink`:

```python
    if storage.engine == "duckdb":
        try:
            from .db_duckdb import DuckdbRunSink
        except ImportError as exc:
            raise DuckdbNotInstalled(
                "The DuckDB sink requires the `duckdb` extra. Install it with:\n"
                "  pip install reddit-researcher[duckdb]"
            ) from exc
        return DuckdbRunSink(db_path)
```

(The `db_duckdb.py` module re-raises `DuckdbNotInstalled` at import time too, but
catching `ImportError` here covers the case where the user has the codebase
checked out without the extra.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_db_duckdb.py -v`
Expected: skip if duckdb not installed; otherwise 2 passed.

Run: `pytest tests/test_db_sqlite.py -k duckdb -v`
Expected: 1 passed (the not-installed branch).

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/db.py reddit_researcher/db_duckdb.py tests/test_db_duckdb.py tests/test_db_sqlite.py
git commit -m "feat: optional DuckDB sink behind [duckdb] extra"
```

---

## Task 14: Packaging — `[duckdb]` extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the optional dependency**

In `pyproject.toml`, find the `[project.optional-dependencies]` section and add:

```toml
# Queryable run database via DuckDB. SQLite (stdlib) is the default sink; this
# extra unlocks `[storage].engine = "duckdb"`. Opt-in:
#     pip install -e ".[duckdb]"
duckdb = [
    "duckdb>=0.10,<2.0",
]
```

Place it after the existing `praw = [...]` block.

- [ ] **Step 2: Verify install resolution**

Run: `python -m pip install -e ".[duckdb]" --dry-run`
Expected: resolves duckdb without errors. (If `--dry-run` is unsupported in the local pip, skip — install for real and verify in step 3.)

- [ ] **Step 3: Confirm DuckDB tests still pass after install**

Run: `pip install -e ".[duckdb]"` (only if not already installed)
Run: `pytest tests/test_db_duckdb.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add [duckdb] optional extra"
```

---

## Task 15: Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Update `docs/roadmap.md`**

Find the `## 0.2.0 — analytics` block and change the SQLite/DuckDB line from
unchecked to checked:

```markdown
- [x] Optional SQLite/DuckDB sink writing each run's normalized rows into a queryable database. *(0.2.0)*
```

- [ ] **Step 2: Add a "Storage" section to `docs/architecture.md`**

Append at the end of the file (or insert before any "## Caveats" section if it exists):

```markdown
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
```

- [ ] **Step 3: Add "Querying across runs" to `README.md`**

Find the section after the run-results description (or near the end of the
"Usage" portion). Add:

```markdown
### Querying across runs

Every run is mirrored into a small SQLite database (default: `research.db`
next to your `project.toml`) so you can ask questions across runs without
re-parsing JSONL.

```bash
# How many posts per subreddit, summed across every run?
reddit-researcher db query \
  "SELECT subreddit, COUNT(*) FROM posts GROUP BY subreddit ORDER BY 2 DESC"

# Posts that appeared under multiple search terms in the same run
reddit-researcher db query \
  "SELECT post_id, GROUP_CONCAT(search_term) FROM posts
   WHERE search_term <> '' GROUP BY post_id HAVING COUNT(*) > 1"
```

To switch to DuckDB:

```toml
# project.toml
[storage]
engine = "duckdb"
db_path = "research.duckdb"
```

```bash
pip install reddit-researcher[duckdb]
```
```

- [ ] **Step 4: Update `CHANGELOG.md`**

Under the existing `## 0.2.0-beta` section, add to "Added":

```markdown
- **Run database sink.** Each run's normalized rows are mirrored into a
  small relational DB for cross-run analysis. SQLite (stdlib) is the default;
  DuckDB is opt-in via `pip install reddit-researcher[duckdb]` plus
  `[storage].engine = "duckdb"`. New `[storage]` config block (`engine`,
  `db_path`, `auto_sync`). Tables: `runs`, `posts`, `comments`,
  `relevance_decisions`, plus `_schema_meta`. JSONL on disk remains canonical.
- **`db` CLI subcommand group.**
  - `db sync [<run-dir>...] [--all] [--rebuild]` — sync one or many run dirs.
  - `db status` — print engine, DB path, schema version, row counts, recent runs.
  - `db query "<SQL>"` — run a read-only query; output as table, JSON, or CSV.
```

- [ ] **Step 5: Run full suite as a sanity check**

Run: `pytest -q`
Expected: all pass.

Run: `pytest --cov=reddit_researcher --cov-report=term-missing`
Expected: coverage ≥ 85%.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md README.md CHANGELOG.md docs/roadmap.md
git commit -m "docs: SQLite/DuckDB sink — architecture, README, CHANGELOG, roadmap"
```

---

## Self-Review Notes

**Spec coverage** (every spec section maps to at least one task):

| Spec section | Task(s) |
|--------------|---------|
| Goals / Non-goals | Implicit in scope of Task 1–14 |
| Config | Task 1 |
| Schema | Task 2 (DDL), Task 3–6 (writes), Task 13 (DuckDB DDL) |
| Sync logic | Task 2 (`sync_run` core), Task 7 (round-trip / idempotency) |
| CLI surface | Task 10 (sync), Task 11 (status), Task 12 (query) |
| Module layout | Task 2 (`db.py`), Task 13 (`db_duckdb.py`) |
| Error handling | Task 8 (mismatch), Task 9 (auto_sync), Task 13 (DuckdbNotInstalled) |
| Testing | Tasks 1, 3–13 (each adds tests) |
| Packaging | Task 14 |
| Documentation | Task 15 |
| Risks (FK pragma) | Task 2 (`PRAGMA foreign_keys = ON`), Task 7 (cascade test) |

**Type/method consistency check:**

- `RunSink` Protocol methods (`transaction`, `upsert_run`, `insert_posts`,
  `insert_comments`, `insert_relevance`, `delete_run`, `read_only_connect`,
  `rebuild`, `close`) are each implemented by both `SqliteRunSink` (Tasks
  2–8) and `DuckdbRunSink` (Task 13).
- `SyncResult` fields (`run_dir`, `posts`, `comments`, `relevance`) are
  defined in Task 2 and asserted in Tasks 7, 9, 13.
- `SCHEMA_VERSION = 1` is defined in both `db_sqlite.py` (Task 2) and
  `db_duckdb.py` (Task 13). They must stay in lock-step; if a future task
  bumps one, it must bump the other.
- `make_sink(storage, project_dir)` signature is stable across Tasks 2, 9, 10–13.
