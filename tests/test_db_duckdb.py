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
