"""Tests for reddit_researcher.series."""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: F401

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import make_sink, sync_run
from reddit_researcher.series import RunRow, SeriesResult, compute_series
from reddit_researcher.storage import append_jsonl


def _post_row(post_id: str, subreddit: str = "AskReddit", search_term: str = "") -> dict:
    return {
        "id": post_id,
        "subreddit": subreddit,
        "search_term": search_term,
        "title": f"Title {post_id}",
        "author": "alice",
        "selftext": "body",
        "url": f"https://reddit.com/{post_id}",
        "permalink": f"/r/{subreddit}/comments/{post_id}/",
        "score": 1,
        "upvote_ratio": 0.9,
        "num_comments": 0,
        "created_utc": 1.0,
        "over_18": False,
        "is_self": True,
        "link_flair_text": None,
    }


def _make_synced_run(
    sink, tmp_path: Path, *, scope: str, ts: str, mode: str = "subreddit",
    posts: list[dict] | None = None, comments: list[dict] | None = None,
    decisions: list[dict] | None = None, project_name: str | None = "demo",
) -> Path:
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "status": "complete",
        "subreddits": [scope] if mode == "subreddit" else [],
        "scraped_at_utc": f"2026-05-07T{ts[-6:-4]}:00:00+00:00",
        "post_count": len(posts or []),
        "comment_count": len(comments or []),
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts or []:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    for c in comments or []:
        append_jsonl(run_dir / "normalized" / "comments.jsonl", c)
    for d in decisions or []:
        append_jsonl(run_dir / "review" / "relevance_review.jsonl", d)
    sync_run(sink, run_dir)
    return run_dir


def test_compute_series_returns_seriesresult_for_one_run(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert isinstance(result, SeriesResult)
        assert result.project_name == "demo"
        assert len(result.runs) == 1
        assert isinstance(result.runs[0], RunRow)
        assert result.runs[0].post_count == 1
    finally:
        sink.close()
