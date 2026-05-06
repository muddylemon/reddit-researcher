"""Tests for `pipeline.scrape_search_terms`.

Mirrors `test_subreddit_resume.py`: stub `make_reddit_client` so no HTTP
happens, then exercise the search-mode scrape's resume, error capture, and
relevance review behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reddit_researcher import pipeline
from reddit_researcher.config import ScrapeConfig
from reddit_researcher.manifest import MANIFEST_SCHEMA_VERSION
from reddit_researcher.models import CommentRecord, PostRecord
from reddit_researcher.relevance import RelevanceConfig


class _StubSearchClient:
    """Returns canned search results, optionally raising for chosen terms."""

    def __init__(
        self,
        *,
        posts_by_term: dict[str, list[PostRecord]],
        comments_by_post: dict[str, list[CommentRecord]],
        search_failures: set[tuple[str, str | None]] | None = None,
        comment_failures: set[str] | None = None,
    ) -> None:
        self.posts_by_term = posts_by_term
        self.comments_by_post = comments_by_post
        self.search_failures = search_failures or set()
        self.comment_failures = comment_failures or set()

    def fetch_search_posts(self, *, query, sort, limit, time_filter, subreddit=None):  # noqa: ARG002
        # Strip surrounding quotes so the test data can match unquoted keys.
        cleaned = query.strip('"')
        if (cleaned, subreddit) in self.search_failures:
            raise RuntimeError(f"simulated search failure for {cleaned}/{subreddit}")
        posts = self.posts_by_term.get(cleaned, [])
        return list(posts), {"query": query, "subreddit": subreddit, "fake": True}

    def fetch_comments(self, *, permalink, post_id, limit):  # noqa: ARG002
        if post_id in self.comment_failures:
            raise RuntimeError(f"simulated comment failure for {post_id}")
        return list(self.comments_by_post.get(post_id, [])), {"post_id": post_id, "fake": True}


def _make_post(post_id: str, *, search_term: str = "", subreddit: str = "test") -> PostRecord:
    return PostRecord(
        id=post_id,
        subreddit=subreddit,
        title=f"title for {post_id}",
        author="someone",
        selftext="body text",
        url=f"https://reddit.com/r/{subreddit}/comments/{post_id}/",
        permalink=f"/r/{subreddit}/comments/{post_id}/",
        score=10,
        upvote_ratio=0.9,
        num_comments=2,
        created_utc=0.0,
        over_18=False,
        is_self=True,
        link_flair_text=None,
        sort="search:top",
        time_filter="all",
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
        permalink=f"/r/test/comments/{post_id}/c/{comment_id}/",
        depth=0,
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _StubSearchClient) -> None:
    monkeypatch.setattr(pipeline, "make_reddit_client", lambda _scrape: client)


def _write_terms_file(tmp_path: Path, terms: list[str], name: str = "terms.txt") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(terms) + "\n", encoding="utf-8")
    return path


def test_search_scrape_writes_versioned_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    posts = {"alice": [_make_post("p1"), _make_post("p2")]}
    comments = {"p1": [_make_comment("c1", "p1")], "p2": []}
    _patch_client(monkeypatch, _StubSearchClient(posts_by_term=posts, comments_by_post=comments))

    terms_file = _write_terms_file(tmp_path, ["alice"])
    run_dir = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=3),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["status"] == "complete"
    assert manifest["mode"] == "search"
    assert manifest["post_count"] == 2
    assert manifest["comment_count"] == 1


def test_search_scrape_records_search_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _StubSearchClient(
        posts_by_term={"good": [_make_post("p1")], "bad": []},
        comments_by_post={"p1": []},
        search_failures={("bad", None)},
    )
    _patch_client(monkeypatch, client)

    terms_file = _write_terms_file(tmp_path, ["good", "bad"])
    run_dir = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=2),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["search_fetch_error_count"] == 1
    error = manifest["search_fetch_errors"][0]
    assert error["search_term"] == "bad"
    assert "simulated" in error["error"]


def test_search_scrape_records_comment_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _StubSearchClient(
        posts_by_term={"alice": [_make_post("p1"), _make_post("p2")]},
        comments_by_post={"p1": [_make_comment("c1", "p1")]},
        comment_failures={"p2"},
    )
    _patch_client(monkeypatch, client)

    terms_file = _write_terms_file(tmp_path, ["alice"])
    run_dir = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=2),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["comment_fetch_error_count"] == 1
    err = manifest["comment_fetch_errors"][0]
    assert err["post_id"] == "p2"


def test_search_scrape_resume_reuses_candidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Resuming into an existing run dir should skip already-processed posts."""
    posts = {"alice": [_make_post("p1"), _make_post("p2")]}
    comments = {"p1": [_make_comment("c1", "p1")], "p2": [_make_comment("c2", "p2")]}
    _patch_client(monkeypatch, _StubSearchClient(posts_by_term=posts, comments_by_post=comments))

    terms_file = _write_terms_file(tmp_path, ["alice"])
    first = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=2),
    )

    posts_path = first / "normalized" / "posts.jsonl"
    initial_lines = posts_path.read_text(encoding="utf-8").count("\n")
    assert initial_lines == 2

    # Second pass with the same client and same run_dir should not re-add posts.
    _patch_client(monkeypatch, _StubSearchClient(posts_by_term=posts, comments_by_post=comments))
    second = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=first,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=2),
    )
    assert second == first
    assert posts_path.read_text(encoding="utf-8").count("\n") == initial_lines


def test_search_scrape_applies_relevance_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """p1 hits the canonical 'include' path (exact term in body + keyword in comments).
    p2 has neither and should land 'exclude'."""
    posts_by_term = {
        "alice": [
            _make_post("p1"),
            _make_post("p2"),
        ]
    }
    posts_by_term["alice"][0].selftext = "I have been listening to alice for years."
    comments = {
        "p1": [_make_comment("c1", "p1")],
        "p2": [_make_comment("c2", "p2")],
    }
    comments["p1"][0].body = "Heard her on a podcast last week"

    _patch_client(monkeypatch, _StubSearchClient(posts_by_term=posts_by_term, comments_by_post=comments))

    terms_file = _write_terms_file(tmp_path, ["alice"])
    run_dir = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=5, comment_limit=2, exact_phrase=False),
        relevance=RelevanceConfig(keywords=["podcast"]),
    )

    review_path = run_dir / "review" / "relevance_review.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines() if line]
    decisions = {row["post_id"]: row["decision"] for row in rows}
    assert decisions["p1"] == "include"
    assert decisions["p2"] == "exclude"

    relevant_path = run_dir / "normalized" / "relevant_posts.jsonl"
    relevant_lines = [line for line in relevant_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(relevant_lines) == 1


def test_search_scrape_respects_term_slice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    posts = {term: [_make_post(f"p-{term}")] for term in ("a", "b", "c", "d")}
    comments = {f"p-{term}": [] for term in ("a", "b", "c", "d")}
    _patch_client(monkeypatch, _StubSearchClient(posts_by_term=posts, comments_by_post=comments))

    terms_file = _write_terms_file(tmp_path, ["a", "b", "c", "d"])
    run_dir = pipeline.scrape_search_terms(
        terms_file=terms_file,
        subreddits_file=None,
        output_root=tmp_path / "runs",
        run_dir=None,
        scrape=ScrapeConfig(mode="search", post_limit=2, comment_limit=1, exact_phrase=False),
        start_term_index=2,
        term_limit=2,
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["search_terms"] == ["b", "c"]
    posts_path = run_dir / "normalized" / "posts.jsonl"
    rows = [json.loads(line) for line in posts_path.read_text(encoding="utf-8").splitlines() if line]
    assert {row["id"] for row in rows} == {"p-b", "p-c"}


def test_search_scrape_validates_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_client(monkeypatch, _StubSearchClient(posts_by_term={}, comments_by_post={}))

    empty_terms = _write_terms_file(tmp_path, [])
    with pytest.raises(ValueError, match="No search terms"):
        pipeline.scrape_search_terms(
            terms_file=empty_terms,
            subreddits_file=None,
            output_root=tmp_path / "runs",
            run_dir=None,
            scrape=ScrapeConfig(mode="search"),
        )

    valid_terms = _write_terms_file(tmp_path, ["x"])
    with pytest.raises(ValueError, match="start_term_index"):
        pipeline.scrape_search_terms(
            terms_file=valid_terms,
            subreddits_file=None,
            output_root=tmp_path / "runs",
            run_dir=None,
            scrape=ScrapeConfig(mode="search"),
            start_term_index=0,
        )
