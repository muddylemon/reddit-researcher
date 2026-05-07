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
    raise NotImplementedError  # Filled in Task 2.


def _subreddit_conversational(posts: list[dict], comments: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 3.


def _subreddit_structured_json(posts: list[dict], comments: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 4.


def _search_compact(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 2.


def _search_conversational(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 3.


def _search_structured_json(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 4.
