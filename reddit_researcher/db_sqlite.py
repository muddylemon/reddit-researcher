"""SQLite implementation of `RunSink`.

Stdlib-only. JSONL on disk is canonical; this DB is a derived index for
queries. Schema is created on open. Foreign keys are enforced via PRAGMA.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        try:
            self._init_schema()
        except Exception:
            self.conn.close()
            raise

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

    def delete_run(self, run_dir: Path) -> None:
        run_dir_str = str(run_dir.resolve())
        # Cascade clears posts/comments/relevance_decisions via FK.
        self.conn.execute("DELETE FROM runs WHERE run_dir = ?", (run_dir_str,))

    def read_only_connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def rebuild(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        for table in ("relevance_decisions", "comments", "posts", "runs", "_schema_meta"):
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()
        self._init_schema()

    def close(self) -> None:
        self.conn.close()
