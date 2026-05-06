from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def text_contains_term(text: str, term: str) -> bool:
    return normalize_text(term) in normalize_text(text)


def text_contains_any(text: str, keywords: Iterable[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(keyword) in normalized for keyword in keywords if keyword)


@dataclass
class RelevanceConfig:
    """Configures the deterministic pre-LLM relevance review.

    All fields are optional. When `keywords` is empty, only the exact-term
    search match drives the decision (still useful for search runs).
    """

    keywords: list[str] = field(default_factory=list)
    allowed_subreddits: set[str] | None = None
    require_exact_term_match: bool = True


def review_post_relevance(post: dict, config: RelevanceConfig | None = None) -> dict:
    """Return a deterministic relevance decision for a single post.

    Decision values:
      - `include` — clearly relevant. Send to LLM.
      - `review`  — possibly relevant. Send to LLM.
      - `exclude` — likely false positive. Skip LLM.
    """
    cfg = config or RelevanceConfig()

    search_term = post.get("search_term") or ""
    title = post.get("title") or ""
    selftext = post.get("selftext") or ""
    subreddit = post.get("subreddit") or ""
    comments = post.get("comments") or []
    comment_text = "\n".join(comment.get("body") or "" for comment in comments)
    searchable_text = "\n".join([title, selftext, comment_text])
    title_body_text = "\n".join([title, selftext])

    if cfg.allowed_subreddits is not None and subreddit.casefold() not in cfg.allowed_subreddits:
        return {
            "post_id": post.get("id"),
            "search_term": search_term,
            "subreddit": subreddit,
            "decision": "exclude",
            "reason": "subreddit outside allowlist",
        }

    reasons: list[str] = []

    has_search_term = bool(search_term) and cfg.require_exact_term_match
    exact_in_title_or_body = has_search_term and text_contains_term(title_body_text, search_term)
    exact_in_comments = has_search_term and text_contains_term(comment_text, search_term)
    has_keyword_context = bool(cfg.keywords) and text_contains_any(searchable_text, cfg.keywords)

    if exact_in_title_or_body:
        reasons.append("exact term in title/body")
    if exact_in_comments:
        reasons.append("exact term in comments")
    if has_keyword_context:
        reasons.append("project keyword present")

    if not has_search_term and not cfg.keywords:
        # Subreddit-mode run with no extra filtering: include everything.
        return {
            "post_id": post.get("id"),
            "search_term": search_term,
            "subreddit": subreddit,
            "decision": "include",
            "reason": "no relevance filter configured",
        }

    if cfg.keywords:
        if exact_in_title_or_body and has_keyword_context:
            decision = "include"
        elif exact_in_title_or_body or (exact_in_comments and has_keyword_context):
            decision = "review"
        elif has_keyword_context and not has_search_term:
            decision = "review"
        else:
            decision = "exclude"
    else:
        if exact_in_title_or_body:
            decision = "include"
        elif exact_in_comments:
            decision = "review"
        else:
            decision = "exclude"

    if decision == "exclude" and not reasons:
        reasons.append("no exact term match or project keyword context")

    return {
        "post_id": post.get("id"),
        "search_term": search_term,
        "subreddit": subreddit,
        "decision": decision,
        "reason": "; ".join(reasons),
    }
