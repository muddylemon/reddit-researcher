"""Tests for subreddit-mode resume parity.

These exercise scrape_subreddit's append-only behavior without hitting Reddit by
faking the RedditClient at the point where the pipeline calls it.
"""

from __future__ import annotations

import json
from pathlib import Path

from reddit_researcher import pipeline
from reddit_researcher.config import ScrapeConfig
from reddit_researcher.manifest import MANIFEST_SCHEMA_VERSION
from reddit_researcher.models import CommentRecord, PostRecord


class _StubRedditClient:
    """Returns a fixed list of posts/comments without making HTTP calls."""

    def __init__(self, posts: list[PostRecord], comments_by_post: dict[str, list[CommentRecord]]) -> None:
        self._posts = posts
        self._comments = comments_by_post

    def fetch_posts(self, subreddit, sort, limit, time_filter):  # noqa: ARG002 - signature parity
        return list(self._posts), {"subreddit": subreddit, "sort": sort, "pages": []}

    def fetch_comments(self, permalink, post_id, limit):  # noqa: ARG002
        return list(self._comments.get(post_id, [])), {"post_id": post_id, "fake": True}


def _make_post(post_id: str, title: str = "title") -> PostRecord:
    return PostRecord(
        id=post_id,
        subreddit="testsub",
        title=title,
        author="someone",
        selftext="body",
        url=f"https://reddit.com/r/testsub/comments/{post_id}/",
        permalink=f"/r/testsub/comments/{post_id}/",
        score=10,
        upvote_ratio=0.9,
        num_comments=2,
        created_utc=0.0,
        over_18=False,
        is_self=True,
        link_flair_text=None,
        sort="top",
        time_filter="month",
    )


def _make_comment(comment_id: str, post_id: str) -> CommentRecord:
    return CommentRecord(
        id=comment_id,
        post_id=post_id,
        parent_id=None,
        author="someone",
        body="comment body",
        score=1,
        created_utc=0.0,
        permalink=f"/r/testsub/comments/{post_id}/c/{comment_id}/",
        depth=0,
    )


def _patch_client(monkeypatch, posts, comments_by_post) -> None:
    monkeypatch.setattr(
        pipeline,
        "make_reddit_client",
        lambda _scrape: _StubRedditClient(posts, comments_by_post),
    )


def test_subreddit_scrape_writes_versioned_manifest(monkeypatch, tmp_path: Path) -> None:
    posts = [_make_post("p1"), _make_post("p2")]
    comments = {"p1": [_make_comment("c1", "p1")], "p2": [_make_comment("c2", "p2")]}
    _patch_client(monkeypatch, posts, comments)

    run_dir = pipeline.scrape_subreddit(
        subreddit="testsub",
        output_root=tmp_path,
        scrape=ScrapeConfig(mode="subreddit", subreddit="testsub", post_limit=2, comment_limit=2),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["status"] == "complete"
    assert manifest["post_count"] == 2
    assert manifest["comment_count"] == 2


def test_subreddit_scrape_resumes_from_existing_run(monkeypatch, tmp_path: Path) -> None:
    posts = [_make_post("p1"), _make_post("p2"), _make_post("p3")]
    comments = {pid: [_make_comment(f"c-{pid}", pid)] for pid in ("p1", "p2", "p3")}
    _patch_client(monkeypatch, posts[:2], {pid: comments[pid] for pid in ("p1", "p2")})

    initial_run = pipeline.scrape_subreddit(
        subreddit="testsub",
        output_root=tmp_path,
        scrape=ScrapeConfig(mode="subreddit", subreddit="testsub", post_limit=2, comment_limit=1),
    )
    posts_path = initial_run / "normalized" / "posts.jsonl"
    assert posts_path.read_text(encoding="utf-8").count("\n") == 2

    # Second run with the full set of three posts; only p3 should be appended.
    _patch_client(monkeypatch, posts, comments)
    resumed = pipeline.scrape_subreddit(
        subreddit="testsub",
        output_root=tmp_path,
        scrape=ScrapeConfig(mode="subreddit", subreddit="testsub", post_limit=3, comment_limit=1),
        run_dir=initial_run,
    )
    assert resumed == initial_run

    # posts.jsonl should now contain three rows, with p3 last.
    rows = [json.loads(line) for line in posts_path.read_text(encoding="utf-8").splitlines() if line]
    assert [row["id"] for row in rows] == ["p1", "p2", "p3"]
    manifest = json.loads((resumed / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["post_count"] == 3
    assert manifest["status"] == "complete"
