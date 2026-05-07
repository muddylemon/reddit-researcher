"""Tests for multi-subreddit subreddit-mode scraping."""

from __future__ import annotations

import json
from pathlib import Path

from reddit_researcher import pipeline
from reddit_researcher.config import ScrapeConfig
from reddit_researcher.models import CommentRecord, PostRecord


def _make_post(post_id: str, subreddit: str) -> PostRecord:
    return PostRecord(
        id=post_id,
        subreddit=subreddit,
        title=f"title for {post_id}",
        author="someone",
        selftext="body",
        url=f"https://reddit.com/r/{subreddit}/comments/{post_id}/",
        permalink=f"/r/{subreddit}/comments/{post_id}/",
        score=10,
        upvote_ratio=0.9,
        num_comments=1,
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
        permalink=f"/c/{comment_id}/",
        depth=0,
    )


class _MultiSubStubClient:
    """Stub that returns per-sub posts and supports controlled fetch failures."""

    def __init__(
        self,
        posts_by_sub: dict[str, list[PostRecord]],
        comments_by_post: dict[str, list[CommentRecord]],
        fetch_errors: dict[str, str] | None = None,
    ) -> None:
        self._posts = posts_by_sub
        self._comments = comments_by_post
        self._errors = fetch_errors or {}

    def fetch_posts(self, subreddit, sort, limit, time_filter):  # noqa: ARG002
        if subreddit in self._errors:
            raise RuntimeError(self._errors[subreddit])
        return list(self._posts.get(subreddit, [])), {"subreddit": subreddit, "sort": sort, "pages": []}

    def fetch_comments(self, permalink, post_id, limit):  # noqa: ARG002
        return list(self._comments.get(post_id, [])), {"post_id": post_id, "fake": True}


def _patch_client(monkeypatch, client) -> None:
    monkeypatch.setattr(pipeline, "make_reddit_client", lambda _scrape: client)


def test_multi_sub_scrape_combines_posts_into_one_run_dir(monkeypatch, tmp_path: Path) -> None:
    posts_by_sub = {
        "cannabis": [_make_post("a1", "cannabis"), _make_post("a2", "cannabis")],
        "marijuana": [_make_post("b1", "marijuana")],
    }
    comments = {pid: [_make_comment(f"c-{pid}", pid)] for pid in ("a1", "a2", "b1")}
    _patch_client(monkeypatch, _MultiSubStubClient(posts_by_sub, comments))

    run_dir = pipeline.scrape_subreddit(
        subreddits=["cannabis", "marijuana"],
        output_root=tmp_path,
        scrape=ScrapeConfig(
            mode="subreddit",
            subreddits=["cannabis", "marijuana"],
            post_limit=5,
            comment_limit=1,
        ),
    )

    # Run dir uses the joined slug.
    assert run_dir.parent.name == "cannabis-marijuana"

    posts_path = run_dir / "normalized" / "posts.jsonl"
    rows = [json.loads(line) for line in posts_path.read_text(encoding="utf-8").splitlines() if line]
    assert sorted(row["id"] for row in rows) == ["a1", "a2", "b1"]
    assert {row["subreddit"] for row in rows} == {"cannabis", "marijuana"}

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["subreddits"] == ["cannabis", "marijuana"]
    assert "subreddit" not in manifest  # omitted for multi-sub
    assert manifest["per_subreddit"]["cannabis"]["post_count"] == 2
    assert manifest["per_subreddit"]["marijuana"]["post_count"] == 1
    assert manifest["per_subreddit"]["cannabis"]["status"] == "complete"
    assert manifest["per_subreddit"]["marijuana"]["status"] == "complete"
    assert manifest["status"] == "complete"
    assert manifest["post_count"] == 3


def test_multi_sub_scrape_isolates_fetch_failure(monkeypatch, tmp_path: Path) -> None:
    posts_by_sub = {
        "cannabis": [_make_post("a1", "cannabis")],
        "marijuana": [],  # never reached because fetch fails
        "drugs": [_make_post("c1", "drugs")],
    }
    comments = {pid: [_make_comment(f"c-{pid}", pid)] for pid in ("a1", "c1")}
    errors = {"marijuana": "HTTP 503 from listing endpoint"}
    _patch_client(monkeypatch, _MultiSubStubClient(posts_by_sub, comments, errors))

    run_dir = pipeline.scrape_subreddit(
        subreddits=["cannabis", "marijuana", "drugs"],
        output_root=tmp_path,
        scrape=ScrapeConfig(
            mode="subreddit",
            subreddits=["cannabis", "marijuana", "drugs"],
            post_limit=5,
            comment_limit=1,
        ),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["per_subreddit"]["cannabis"]["status"] == "complete"
    assert manifest["per_subreddit"]["marijuana"]["status"] == "fetch_error"
    assert "503" in manifest["per_subreddit"]["marijuana"]["error"]
    assert manifest["per_subreddit"]["drugs"]["status"] == "complete"
    # Other subs still produced posts.
    assert manifest["post_count"] == 2
