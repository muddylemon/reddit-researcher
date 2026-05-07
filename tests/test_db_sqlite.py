"""Tests for the SQLite RunSink and the engine-agnostic sync_run()."""

# Imports below are scaffolding for tests added by Tasks 3-8 in the SQLite/DuckDB
# sink plan. Symbols unused by current test bodies are suppressed with noqa: F401.
from __future__ import annotations

import json
import sqlite3  # noqa: F401
from pathlib import Path

import pytest

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import (
    DuckdbNotInstalled,  # noqa: F401
    RunSink,  # noqa: F401
    SchemaVersionMismatch,  # noqa: F401
    SyncResult,  # noqa: F401
    make_sink,
    sync_run,  # noqa: F401
)
from reddit_researcher.db_sqlite import SCHEMA_VERSION, SqliteRunSink  # noqa: F401


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


def test_sqlite_init_schema_mismatch_closes_connection(tmp_path: Path) -> None:
    """Regression: SchemaVersionMismatch in __init__ must not leak the connection."""
    db_path = tmp_path / "r.db"
    storage = StorageConfig(engine="sqlite", db_path=db_path)

    # Bootstrap the DB at the current schema_version.
    sink = make_sink(storage, project_dir=tmp_path)
    sink.close()

    # Tamper with the recorded version so the next open raises.
    raw = sqlite3.connect(db_path)
    raw.execute("UPDATE _schema_meta SET schema_version = 99")
    raw.commit()
    raw.close()

    with pytest.raises(SchemaVersionMismatch):
        make_sink(storage, project_dir=tmp_path)

    # If the failed init leaked its connection, the file is still locked on
    # Windows and unlink raises PermissionError.
    db_path.unlink()
    assert not db_path.exists()


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
