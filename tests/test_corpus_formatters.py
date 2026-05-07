"""Tests for reddit_researcher.corpus_formatters."""

from __future__ import annotations

import json as _json

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


def test_subreddit_conversational_uses_markdown_headings() -> None:
    posts = [_post("p1", title="What's the best book?", selftext="Curious about non-fiction.")]
    comments = [_comment("c1", "p1", body="I just finished Sapiens.")]
    out = format_corpus(mode="subreddit", fmt="conversational", posts=posts, comments=comments)
    assert "## Post: What's the best book?" in out
    assert "### Comment by bob (3 points)" in out
    # Conversational metadata line.
    assert "*r/AskReddit — by alice — 42 points, 7 comments*" in out
    # No legacy markers.
    assert "[POST p1]" not in out
    assert "[COMMENT c1]" not in out


def test_subreddit_conversational_handles_empty_selftext() -> None:
    posts = [_post("p1", selftext="")]
    out = format_corpus(mode="subreddit", fmt="conversational", posts=posts, comments=[])
    assert "## Post:" in out
    # Empty body shouldn't insert a blank "body:" placeholder.
    assert "body:" not in out


def test_search_conversational_adds_search_term_heading() -> None:
    posts = [
        _post("p1", search_term="vim", title="Vim tips", comments=[_comment("c1", "p1")]),
        _post("p2", search_term="emacs", title="Emacs config"),
    ]
    out = format_corpus(mode="search", fmt="conversational", posts=posts)
    assert "# Search term: vim" in out
    assert "# Search term: emacs" in out
    assert "## Post: Vim tips" in out
    assert "## Post: Emacs config" in out


def test_subreddit_structured_json_parses_per_paragraph() -> None:
    posts = [_post("p1", title="One"), _post("p2", title="Two")]
    comments = [_comment("c1", "p1"), _comment("c2", "p2")]
    out = format_corpus(mode="subreddit", fmt="structured-json", posts=posts, comments=comments)
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) == 2
    objs = [_json.loads(p) for p in paragraphs]
    assert objs[0]["id"] == "p1"
    assert objs[0]["title"] == "One"
    assert objs[0]["subreddit"] == "AskReddit"
    assert objs[0]["author"] == "alice"
    assert objs[0]["score"] == 42
    assert "body" in objs[0]
    assert "search_term" not in objs[0]  # subreddit-mode has no search_term
    # Each post's comments are nested.
    assert len(objs[0]["comments"]) == 1
    assert objs[0]["comments"][0]["id"] == "c1"
    assert objs[0]["comments"][0]["author"] == "bob"
    assert objs[0]["comments"][0]["score"] == 3


def test_subreddit_structured_json_post_with_no_comments_has_empty_array() -> None:
    posts = [_post("p1")]
    out = format_corpus(mode="subreddit", fmt="structured-json", posts=posts, comments=[])
    obj = _json.loads(out.strip())
    assert obj["comments"] == []


def test_search_structured_json_includes_search_term() -> None:
    posts = [
        _post("p1", search_term="vim", comments=[_comment("c1", "p1")]),
        _post("p2", search_term="emacs"),
    ]
    out = format_corpus(mode="search", fmt="structured-json", posts=posts)
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) == 2
    objs = [_json.loads(p) for p in paragraphs]
    by_id = {o["id"]: o for o in objs}
    assert by_id["p1"]["search_term"] == "vim"
    assert by_id["p2"]["search_term"] == "emacs"
    assert by_id["p1"]["comments"][0]["id"] == "c1"


def test_structured_json_escapes_newlines_in_body() -> None:
    """Bodies with literal newlines must not break paragraph chunking."""
    posts = [_post("p1", selftext="line one\n\nline two")]
    out = format_corpus(mode="subreddit", fmt="structured-json", posts=posts, comments=[])
    # The serialized body should contain backslash-n, not a literal newline.
    assert "\\n\\n" in out or "\\n" in out
    # The post object is one paragraph (one entry after split).
    paragraphs = [p for p in out.split("\n\n") if p.strip()]
    assert len(paragraphs) == 1
    obj = _json.loads(paragraphs[0])
    assert obj["body"] == "line one\n\nline two"  # round-trips
