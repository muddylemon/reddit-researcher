"""Tests for the optional PRAW backend.

These do not require `praw` to be installed at test time. We exercise:

- The factory (`make_reddit_client`) selecting the right class.
- The credential and missing-package error paths via monkeypatch.
- The PRAW client's normalization logic via stubbed `praw.Reddit` objects.
- The config-loader rejecting unknown backend values.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reddit_researcher.config import (
    ENV_PRAW_CLIENT_ID,
    ENV_PRAW_CLIENT_SECRET,
    ScrapeConfig,
    load_project,
)
from reddit_researcher.praw_client import (
    PrawCredentialsMissing,
    PrawNotInstalled,
    PrawRedditClient,
    _import_praw,
    _resolve_credentials,
)
from reddit_researcher.reddit_client import RedditClient, make_reddit_client


def test_factory_returns_json_client_by_default() -> None:
    client = make_reddit_client(ScrapeConfig(subreddit="x"))
    assert isinstance(client, RedditClient)


def test_factory_routes_to_praw(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory should construct a PrawRedditClient for backend='praw'."""
    fake_reddit = SimpleNamespace(read_only=False)

    def fake_praw_module():
        return SimpleNamespace(Reddit=lambda **kwargs: fake_reddit)

    monkeypatch.setattr("reddit_researcher.praw_client._import_praw", fake_praw_module)
    monkeypatch.setenv(ENV_PRAW_CLIENT_ID, "abc")
    monkeypatch.setenv(ENV_PRAW_CLIENT_SECRET, "xyz")

    client = make_reddit_client(ScrapeConfig(subreddit="x", backend="praw"))
    assert isinstance(client, PrawRedditClient)
    assert client.reddit is fake_reddit
    assert fake_reddit.read_only is True


def test_resolve_credentials_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PRAW_CLIENT_ID, raising=False)
    monkeypatch.delenv(ENV_PRAW_CLIENT_SECRET, raising=False)
    with pytest.raises(PrawCredentialsMissing) as exc_info:
        _resolve_credentials()
    assert ENV_PRAW_CLIENT_ID in str(exc_info.value)
    assert ENV_PRAW_CLIENT_SECRET in str(exc_info.value)


def test_resolve_credentials_returns_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PRAW_CLIENT_ID, "id-value")
    monkeypatch.setenv(ENV_PRAW_CLIENT_SECRET, "secret-value")
    assert _resolve_credentials() == ("id-value", "secret-value")


def test_import_praw_reports_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """If praw is not importable, the error should explain how to install it."""
    monkeypatch.setitem(sys.modules, "praw", None)  # forces ImportError on `import praw`
    with pytest.raises(PrawNotInstalled) as exc_info:
        _import_praw()
    assert "pip install reddit-researcher[praw]" in str(exc_info.value)


def test_config_rejects_unknown_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\nbackend = "nonsense"\n',
        encoding="utf-8",
    )
    with pytest.raises(Exception) as exc_info:
        load_project(config_path)
    assert "scrape.backend" in str(exc_info.value)


def test_config_accepts_praw_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\nbackend = "praw"\n',
        encoding="utf-8",
    )
    project = load_project(config_path)
    assert project.scrape.backend == "praw"


# --- PrawRedditClient normalization ----------------------------------------


def _fake_submission(**overrides: Any) -> SimpleNamespace:
    base = SimpleNamespace(
        id="abc",
        title="A title",
        author=SimpleNamespace(name="alice"),
        selftext="body",
        url="https://example.com/x",
        permalink="/r/test/comments/abc/x/",
        score=42,
        upvote_ratio=0.97,
        num_comments=5,
        created_utc=12345.0,
        over_18=False,
        is_self=True,
        link_flair_text=None,
        subreddit=SimpleNamespace(display_name="test"),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _fake_comment(**overrides: Any) -> SimpleNamespace:
    base = SimpleNamespace(
        id="c1",
        parent_id="t3_abc",
        author=SimpleNamespace(name="bob"),
        body="A comment",
        score=10,
        created_utc=12346.0,
        permalink="/r/test/comments/abc/x/c1/",
        depth=0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _make_client_with_fake_reddit(fake_reddit: Any) -> PrawRedditClient:
    return PrawRedditClient(user_agent="test:reddit-researcher:test", reddit=fake_reddit)


def test_fetch_posts_normalizes_submissions() -> None:
    submissions = [_fake_submission(id="p1"), _fake_submission(id="p2", title="Two")]

    fake_subreddit = SimpleNamespace(top=lambda **_: iter(submissions))
    fake_reddit = SimpleNamespace(subreddit=lambda _name: fake_subreddit)
    client = _make_client_with_fake_reddit(fake_reddit)

    posts, raw = client.fetch_posts(subreddit="test", sort="top", limit=5, time_filter="month")
    assert [post.id for post in posts] == ["p1", "p2"]
    assert posts[0].author == "alice"
    assert raw["backend"] == "praw"
    assert raw["fetched"] == 2


def test_fetch_search_posts_uses_subreddit_search() -> None:
    submissions = [_fake_submission(id="p1")]

    captured: dict[str, Any] = {}

    def fake_search(query: str, **kwargs: Any) -> Any:
        captured["query"] = query
        captured.update(kwargs)
        return iter(submissions)

    fake_subreddit = SimpleNamespace(search=fake_search)
    fake_reddit = SimpleNamespace(
        subreddit=lambda name: (captured.setdefault("name", name), fake_subreddit)[1]
    )
    client = _make_client_with_fake_reddit(fake_reddit)

    posts, raw = client.fetch_search_posts(
        query="hello",
        limit=3,
        sort="top",
        time_filter="year",
        subreddit="test",
    )
    assert [post.id for post in posts] == ["p1"]
    assert captured["name"] == "test"
    assert captured["query"] == "hello"
    assert captured["sort"] == "top"
    assert captured["limit"] == 3
    assert captured["time_filter"] == "year"
    assert raw["backend"] == "praw"


def test_fetch_comments_skips_empty_bodies_and_caps_at_limit() -> None:
    comments = [
        _fake_comment(id="c1", body="first"),
        _fake_comment(id="c2", body="   "),  # skipped
        _fake_comment(id="c3", body="second"),
        _fake_comment(id="c4", body="third"),
    ]

    class _FakeForest:
        def replace_more(self, limit: int = 0) -> None:  # noqa: ARG002
            pass

        def list(self) -> list[Any]:
            return comments

    fake_submission = SimpleNamespace(comments=_FakeForest())
    fake_reddit = SimpleNamespace(submission=lambda id: fake_submission)
    client = _make_client_with_fake_reddit(fake_reddit)

    flat, raw = client.fetch_comments(permalink="/", post_id="abc", limit=2)
    assert [c.id for c in flat] == ["c1", "c3"]
    assert raw["comment_count"] == 2


def test_fetch_comments_zero_limit_short_circuits() -> None:
    fake_reddit = SimpleNamespace(submission=lambda id: pytest.fail("submission() should not be called"))
    client = _make_client_with_fake_reddit(fake_reddit)
    flat, raw = client.fetch_comments(permalink="/", post_id="abc", limit=0)
    assert flat == []
    assert raw == []
