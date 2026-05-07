"""DuckDB implementation of `RunSink` (optional)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        try:
            self._init_schema()
        except Exception:
            self.conn.close()
            raise

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
        # DuckDB: no ON CONFLICT REPLACE; DELETE + INSERT.
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
