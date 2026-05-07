"""Tests for reddit_researcher.corpus_formatters."""

from __future__ import annotations

import pytest

from reddit_researcher.corpus_formatters import VALID_CORPUS_FORMATS, format_corpus


def test_valid_corpus_formats_set() -> None:
    assert VALID_CORPUS_FORMATS == {"compact", "conversational", "structured-json"}


def test_format_corpus_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unknown corpus format"):
        format_corpus(mode="subreddit", fmt="yaml", posts=[], comments=[])


def test_format_corpus_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown corpus mode"):
        format_corpus(mode="firehose", fmt="compact", posts=[], comments=[])


def _post(post_id: str, **overrides: object) -> dict:
    base = {
        "id": post_id,
        "subreddit": "AskReddit",
        "title": f"Title {post_id}",
        "author": "alice",
        "selftext": "selftext body",
        "url": "https://example.com",
        "permalink": f"/r/AskReddit/comments/{post_id}/",
        "score": 42,
        "upvote_ratio": 0.95,
        "num_comments": 7,
        "created_utc": 1700000000.0,
        "over_18": False,
        "is_self": True,
        "link_flair_text": None,
        "sort": "top",
        "time_filter": "month",
    }
    base.update(overrides)
    return base


def _comment(comment_id: str, post_id: str, **overrides: object) -> dict:
    base = {
        "id": comment_id,
        "post_id": post_id,
        "parent_id": f"t3_{post_id}",
        "author": "bob",
        "body": "comment body",
        "score": 3,
        "created_utc": 1700000100.0,
        "permalink": f"/r/AskReddit/comments/{post_id}/_/{comment_id}/",
        "depth": 0,
    }
    base.update(overrides)
    return base


def test_subreddit_compact_matches_legacy_build_corpus() -> None:
    """Byte-equivalent to today's reddit_researcher.prompting.build_corpus output."""
    from reddit_researcher.prompting import build_corpus

    posts = [_post("p1"), _post("p2", subreddit="news")]
    comments = [_comment("c1", "p1"), _comment("c2", "p2")]
    legacy = build_corpus(posts, comments)
    new = format_corpus(mode="subreddit", fmt="compact", posts=posts, comments=comments)
    assert new == legacy


def test_search_compact_matches_legacy_build_search_corpus() -> None:
    """Byte-equivalent to today's reddit_researcher.prompting.build_search_corpus output."""
    from reddit_researcher.prompting import build_search_corpus

    posts = [
        _post("p1", search_term="vim", comments=[_comment("c1", "p1")]),
        _post("p2", search_term="vim", comments=[]),
        _post("p3", search_term="emacs", comments=[]),
    ]
    legacy = build_search_corpus(posts)
    new = format_corpus(mode="search", fmt="compact", posts=posts)
    assert new == legacy
