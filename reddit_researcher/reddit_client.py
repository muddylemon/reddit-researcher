from __future__ import annotations

import time
from typing import Any

import requests

from .models import CommentRecord, PostRecord


class RedditClient:
    """Reads Reddit's public JSON endpoints. No auth required, but be polite.

    Set a descriptive `user_agent` per Reddit's API rules:
    https://github.com/reddit-archive/reddit/wiki/API
    """

    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://www.reddit.com",
        timeout_seconds: int = 30,
        pause_seconds: float = 1.0,
        max_retries: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.pause_seconds = pause_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def fetch_posts(
        self,
        subreddit: str,
        sort: str,
        limit: int,
        time_filter: str | None,
    ) -> tuple[list[PostRecord], dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        after: str | None = None

        while len(collected) < limit:
            batch_size = min(100, limit - len(collected))
            params: dict[str, Any] = {
                "limit": batch_size,
                "raw_json": 1,
            }
            if after:
                params["after"] = after
            if sort == "top" and time_filter:
                params["t"] = time_filter

            page = self._get_json(f"/r/{subreddit}/{sort}.json", params=params)
            raw_pages.append(page)
            children = page.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue
                collected.append(child.get("data", {}))
                if len(collected) >= limit:
                    break

            after = page.get("data", {}).get("after")
            if not after:
                break

            time.sleep(self.pause_seconds)

        posts = [
            self._normalize_post(item, subreddit=subreddit, sort=sort, time_filter=time_filter)
            for item in collected
        ]
        raw_payload = {
            "subreddit": subreddit,
            "sort": sort,
            "time_filter": time_filter,
            "pages": raw_pages,
        }
        return posts, raw_payload

    def fetch_search_posts(
        self,
        query: str,
        limit: int,
        sort: str,
        time_filter: str | None,
        subreddit: str | None = None,
    ) -> tuple[list[PostRecord], dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        after: str | None = None

        while len(collected) < limit:
            batch_size = min(100, limit - len(collected))
            params: dict[str, Any] = {
                "limit": batch_size,
                "raw_json": 1,
                "q": query,
                "sort": sort,
                "type": "link",
            }
            if subreddit:
                params["restrict_sr"] = 1
            if time_filter:
                params["t"] = time_filter
            if after:
                params["after"] = after

            path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
            page = self._get_json(path, params=params)
            raw_pages.append(page)
            children = page.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue
                collected.append(child.get("data", {}))
                if len(collected) >= limit:
                    break

            after = page.get("data", {}).get("after")
            if not after:
                break

            time.sleep(self.pause_seconds)

        posts = [
            self._normalize_post(
                item,
                subreddit=item.get("subreddit") or "unknown",
                sort=f"search:{sort}",
                time_filter=time_filter,
            )
            for item in collected
        ]
        raw_payload = {
            "query": query,
            "subreddit": subreddit,
            "sort": sort,
            "time_filter": time_filter,
            "pages": raw_pages,
        }
        return posts, raw_payload

    def fetch_comments(
        self,
        permalink: str,
        post_id: str,
        limit: int,
    ) -> tuple[list[CommentRecord], Any]:
        if limit <= 0:
            return [], []

        params = {
            "raw_json": 1,
            "limit": limit,
            "depth": 4,
            "sort": "top",
        }
        payload = self._get_json(f"{permalink}.json", params=params)
        if not isinstance(payload, list) or len(payload) < 2:
            return [], payload

        comment_listing = payload[1]
        children = comment_listing.get("data", {}).get("children", [])
        comments = self._flatten_comments(children=children, post_id=post_id, limit=limit)
        return comments, payload

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_seconds = (
                        float(retry_after)
                        if retry_after
                        else min(60.0, self.pause_seconds * (2 ** (attempt - 1)))
                    )
                    last_error = RuntimeError(
                        f"HTTP 429 rate limited on attempt {attempt}/{self.max_retries}; slept {sleep_seconds}s"
                    )
                    time.sleep(sleep_seconds)
                    continue

                response.raise_for_status()
                payload = response.json()
                time.sleep(self.pause_seconds)
                return payload
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(60.0, self.pause_seconds * (2 ** (attempt - 1))))

        raise RuntimeError(f"Failed to fetch Reddit JSON from {url}: {last_error}") from last_error

    def _normalize_post(
        self,
        item: dict[str, Any],
        subreddit: str,
        sort: str,
        time_filter: str | None,
    ) -> PostRecord:
        return PostRecord(
            id=item.get("id", ""),
            subreddit=subreddit,
            title=item.get("title", "").strip(),
            author=item.get("author"),
            selftext=item.get("selftext", "").strip(),
            url=item.get("url", ""),
            permalink=item.get("permalink", ""),
            score=int(item.get("score") or 0),
            upvote_ratio=item.get("upvote_ratio"),
            num_comments=int(item.get("num_comments") or 0),
            created_utc=item.get("created_utc"),
            over_18=bool(item.get("over_18")),
            is_self=bool(item.get("is_self")),
            link_flair_text=item.get("link_flair_text"),
            sort=sort,
            time_filter=time_filter,
        )

    def _flatten_comments(
        self,
        children: list[dict[str, Any]],
        post_id: str,
        limit: int,
    ) -> list[CommentRecord]:
        comments: list[CommentRecord] = []
        stack: list[tuple[dict[str, Any], int]] = [(child, 0) for child in reversed(children)]

        while stack and len(comments) < limit:
            child, depth = stack.pop()
            if child.get("kind") != "t1":
                continue

            data = child.get("data", {})
            body = (data.get("body") or "").strip()
            if body:
                comments.append(
                    CommentRecord(
                        id=data.get("id", ""),
                        post_id=post_id,
                        parent_id=data.get("parent_id"),
                        author=data.get("author"),
                        body=body,
                        score=int(data.get("score") or 0),
                        created_utc=data.get("created_utc"),
                        permalink=data.get("permalink", ""),
                        depth=depth,
                    )
                )

            replies = data.get("replies")
            if isinstance(replies, dict):
                reply_children = replies.get("data", {}).get("children", [])
                for reply in reversed(reply_children):
                    stack.append((reply, depth + 1))

        return comments
