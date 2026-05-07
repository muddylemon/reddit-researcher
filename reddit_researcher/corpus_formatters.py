"""Corpus format dispatch.

Three named formats — compact, conversational, structured-json — selectable
via [analyze].corpus_format. `compact` is byte-equivalent to the historical
output (the wrappers in prompting.py preserve the public surface).

Each (mode, format) pair has its own function. The data shapes differ enough
between subreddit and search modes that a unified renderer would be more
abstract than helpful.
"""

from __future__ import annotations

VALID_CORPUS_FORMATS = {"compact", "conversational", "structured-json"}
_VALID_MODES = {"subreddit", "search"}


def format_corpus(
    *,
    mode: str,
    fmt: str,
    posts: list[dict],
    comments: list[dict] | None = None,
) -> str:
    """Dispatch to the appropriate (mode, fmt) formatter."""
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown corpus mode: {mode!r}. Must be one of {sorted(_VALID_MODES)}.")
    if fmt not in VALID_CORPUS_FORMATS:
        raise ValueError(
            f"unknown corpus format: {fmt!r}. Must be one of {sorted(VALID_CORPUS_FORMATS)}."
        )
    if mode == "subreddit":
        if fmt == "compact":
            return _subreddit_compact(posts, comments or [])
        if fmt == "conversational":
            return _subreddit_conversational(posts, comments or [])
        return _subreddit_structured_json(posts, comments or [])
    # mode == "search"
    if fmt == "compact":
        return _search_compact(posts)
    if fmt == "conversational":
        return _search_conversational(posts)
    return _search_structured_json(posts)


def _subreddit_compact(posts: list[dict], comments: list[dict]) -> str:
    """Compact subreddit-mode corpus. Byte-equivalent to legacy build_corpus."""
    lines: list[str] = []

    for post in posts:
        subreddit = post.get("subreddit") or "unknown"
        lines.extend(
            [
                f"[POST {post['id']}] r/{subreddit} title: {post['title']}",
                f"author: {post.get('author') or 'unknown'} | score: {post.get('score', 0)} | comments: {post.get('num_comments', 0)}",
                f"flair: {post.get('link_flair_text') or 'none'}",
            ]
        )
        selftext = (post.get("selftext") or "").strip()
        if selftext:
            lines.append(f"body: {selftext}")
        lines.append("")

    for comment in comments:
        lines.append(
            f"[COMMENT {comment['id']}] post={comment['post_id']} depth={comment.get('depth', 0)} score={comment.get('score', 0)}"
        )
        lines.append(f"body: {(comment.get('body') or '').strip()}")
        lines.append("")

    return "\n".join(lines).strip()


def _subreddit_conversational(posts: list[dict], comments: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 3.


def _subreddit_structured_json(posts: list[dict], comments: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 4.


def _search_compact(posts: list[dict]) -> str:
    """Compact search-mode corpus. Byte-equivalent to legacy build_search_corpus."""
    lines: list[str] = []
    active_term: str | None = None

    sorted_posts = sorted(posts, key=lambda post: (post.get("search_term") or "", -(post.get("score") or 0)))
    for post in sorted_posts:
        search_term = post.get("search_term") or "unknown"
        if search_term != active_term:
            if lines:
                lines.append("")
            lines.append(f"## Search term: {search_term}")
            active_term = search_term

        subreddit = post.get("subreddit") or "unknown"
        lines.extend(
            [
                f"[POST {post['id']}] r/{subreddit} title: {post['title']}",
                f"author: {post.get('author') or 'unknown'} | score: {post.get('score', 0)} | comments: {post.get('num_comments', 0)}",
                f"url: {post.get('url') or post.get('permalink') or 'unknown'}",
                f"flair: {post.get('link_flair_text') or 'none'}",
            ]
        )
        selftext = (post.get("selftext") or "").strip()
        if selftext:
            lines.append(f"body: {selftext}")

        for comment in post.get("comments") or []:
            lines.append(
                f"[COMMENT {comment['id']}] post={comment['post_id']} depth={comment.get('depth', 0)} score={comment.get('score', 0)}"
            )
            lines.append(f"body: {(comment.get('body') or '').strip()}")
        lines.append("")

    return "\n".join(lines).strip()


def _search_conversational(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 3.


def _search_structured_json(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 4.
