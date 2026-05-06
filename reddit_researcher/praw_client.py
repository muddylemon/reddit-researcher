"""Authenticated Reddit backend via PRAW.

This is the optional `[scrape].backend = "praw"` path. It mirrors the surface of
`reddit_client.RedditClient` so the pipeline can swap one for the other without
caring which is in use.

When to use this backend:

- You're hitting the public-JSON rate limit.
- You need more than 1000 results for a listing or search.
- You want fuller comment trees (PRAW expands `MoreComments` for you).

What it requires:

- `pip install reddit-researcher[praw]` (the `praw` package is an opt-in extra).
- A registered Reddit "script" app at https://www.reddit.com/prefs/apps
  yielding a client id and secret.
- `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in the shell environment or a
  `.env` file. The User-Agent is shared with the JSON backend
  (`REDDIT_RESEARCHER_USER_AGENT`).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .config import ENV_PRAW_CLIENT_ID, ENV_PRAW_CLIENT_SECRET
from .models import CommentRecord, PostRecord

if TYPE_CHECKING:  # pragma: no cover
    import praw  # noqa: F401


class PrawNotInstalled(RuntimeError):
    """Raised when the `praw` extra has not been installed."""


class PrawCredentialsMissing(RuntimeError):
    """Raised when REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set."""


def _import_praw() -> Any:
    try:
        import praw  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised via tests with monkeypatch
        raise PrawNotInstalled(
            "The PRAW backend requires the `praw` extra. Install it with:\n"
            "  pip install reddit-researcher[praw]\n"
            "Then set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in your shell or .env."
        ) from exc
    return praw


def _resolve_credentials() -> tuple[str, str]:
    client_id = os.environ.get(ENV_PRAW_CLIENT_ID, "").strip()
    client_secret = os.environ.get(ENV_PRAW_CLIENT_SECRET, "").strip()
    if not client_id or not client_secret:
        raise PrawCredentialsMissing(
            f"PRAW backend requires {ENV_PRAW_CLIENT_ID} and {ENV_PRAW_CLIENT_SECRET}.\n"
            "Register a 'script' app at https://www.reddit.com/prefs/apps and put\n"
            "the values in your shell environment or a project-level .env file."
        )
    return client_id, client_secret


class PrawRedditClient:
    """Match the surface of `RedditClient` but back it with PRAW.

    The unused `pause_seconds` and `max_retries` fields are accepted for
    signature parity. PRAW handles its own rate limiting and backoff.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        pause_seconds: float = 1.0,  # noqa: ARG002 - signature parity with RedditClient
        max_retries: int = 5,  # noqa: ARG002 - signature parity with RedditClient
        reddit: Any | None = None,
    ) -> None:
        if reddit is not None:
            self.reddit = reddit
        else:
            praw_module = _import_praw()
            client_id, client_secret = _resolve_credentials()
            self.reddit = praw_module.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
                check_for_async=False,
            )
            # Read-only mode: no user login required. PRAW infers this when
            # username/password are absent, but make it explicit.
            self.reddit.read_only = True

    def fetch_posts(
        self,
        subreddit: str,
        sort: str,
        limit: int,
        time_filter: str | None,
    ) -> tuple[list[PostRecord], dict[str, Any]]:
        listing = self._listing_for(subreddit=subreddit, sort=sort, time_filter=time_filter, limit=limit)
        submissions = list(listing)
        posts = [
            self._normalize_submission(sub, subreddit=subreddit, sort=sort, time_filter=time_filter)
            for sub in submissions
        ]
        raw = {
            "subreddit": subreddit,
            "sort": sort,
            "time_filter": time_filter,
            "backend": "praw",
            "fetched": len(submissions),
        }
        return posts, raw

    def fetch_search_posts(
        self,
        query: str,
        limit: int,
        sort: str,
        time_filter: str | None,
        subreddit: str | None = None,
    ) -> tuple[list[PostRecord], dict[str, Any]]:
        target = self.reddit.subreddit(subreddit or "all")
        kwargs: dict[str, Any] = {"sort": sort, "limit": limit}
        if time_filter:
            kwargs["time_filter"] = time_filter
        submissions = list(target.search(query, **kwargs))
        posts = [
            self._normalize_submission(
                sub,
                subreddit=str(getattr(sub, "subreddit", subreddit or "unknown")),
                sort=f"search:{sort}",
                time_filter=time_filter,
            )
            for sub in submissions
        ]
        raw = {
            "query": query,
            "subreddit": subreddit,
            "sort": sort,
            "time_filter": time_filter,
            "backend": "praw",
            "fetched": len(submissions),
        }
        return posts, raw

    def fetch_comments(
        self,
        permalink: str,  # noqa: ARG002 - submission lookup uses post_id
        post_id: str,
        limit: int,
    ) -> tuple[list[CommentRecord], Any]:
        if limit <= 0:
            return [], []
        submission = self.reddit.submission(id=post_id)
        submission.comments.replace_more(limit=0)
        flat = submission.comments.list()
        comments: list[CommentRecord] = []
        for comment in flat:
            if len(comments) >= limit:
                break
            body = (getattr(comment, "body", "") or "").strip()
            if not body:
                continue
            author_obj = getattr(comment, "author", None)
            author = author_obj.name if author_obj is not None else None
            comments.append(
                CommentRecord(
                    id=getattr(comment, "id", ""),
                    post_id=post_id,
                    parent_id=getattr(comment, "parent_id", None),
                    author=author,
                    body=body,
                    score=int(getattr(comment, "score", 0) or 0),
                    created_utc=getattr(comment, "created_utc", None),
                    permalink=getattr(comment, "permalink", "") or "",
                    depth=int(getattr(comment, "depth", 0) or 0),
                )
            )
        raw = {"backend": "praw", "post_id": post_id, "comment_count": len(comments)}
        return comments, raw

    def _listing_for(self, *, subreddit: str, sort: str, time_filter: str | None, limit: int) -> Any:
        sub = self.reddit.subreddit(subreddit)
        if sort == "hot":
            return sub.hot(limit=limit)
        if sort == "new":
            return sub.new(limit=limit)
        if sort == "rising":
            return sub.rising(limit=limit)
        # Default and "top" both flow here.
        return sub.top(time_filter=time_filter or "all", limit=limit)

    def _normalize_submission(
        self,
        submission: Any,
        *,
        subreddit: str,
        sort: str,
        time_filter: str | None,
    ) -> PostRecord:
        author_obj = getattr(submission, "author", None)
        author = author_obj.name if author_obj is not None else None
        return PostRecord(
            id=getattr(submission, "id", "") or "",
            subreddit=subreddit,
            title=(getattr(submission, "title", "") or "").strip(),
            author=author,
            selftext=(getattr(submission, "selftext", "") or "").strip(),
            url=getattr(submission, "url", "") or "",
            permalink=getattr(submission, "permalink", "") or "",
            score=int(getattr(submission, "score", 0) or 0),
            upvote_ratio=getattr(submission, "upvote_ratio", None),
            num_comments=int(getattr(submission, "num_comments", 0) or 0),
            created_utc=getattr(submission, "created_utc", None),
            over_18=bool(getattr(submission, "over_18", False)),
            is_self=bool(getattr(submission, "is_self", False)),
            link_flair_text=getattr(submission, "link_flair_text", None),
            sort=sort,
            time_filter=time_filter,
        )
