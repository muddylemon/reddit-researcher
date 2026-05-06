from __future__ import annotations

from pathlib import Path
from typing import Iterable


def load_prompt_text(prompt_file: Path) -> str:
    return prompt_file.read_text(encoding="utf-8").strip()


def load_terms(terms_file: Path) -> list[str]:
    """Load line-delimited terms from a file. Skips blank lines and `#` comments."""
    terms: list[str] = []
    for line in terms_file.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        terms.append(value)
    return terms


def quote_search_term(term: str) -> str:
    """Wrap a term in quotes for Reddit's exact-phrase search."""
    escaped = term.replace('"', '\\"')
    return f'"{escaped}"'


def build_corpus(posts: list[dict], comments: list[dict]) -> str:
    """Build a text corpus for subreddit-mode runs (posts + flat comments)."""
    lines: list[str] = []

    for post in posts:
        lines.extend(
            [
                f"[POST {post['id']}] title: {post['title']}",
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


def build_search_corpus(posts: list[dict]) -> str:
    """Build a text corpus for search-mode runs, grouped by search term."""
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


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split a long string into roughly-sized chunks at paragraph boundaries."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return [text]

    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = start + max_chars
            chunks.append(paragraph[start:end])
            start = end

    if current:
        chunks.append(current)

    return chunks


def build_chunk_prompt(
    *,
    scope_label: str,
    prompt_text: str,
    chunk_text_value: str,
    chunk_index: int,
    chunk_count: int,
) -> str:
    return (
        f"You are analyzing Reddit discussions from {scope_label}.\n\n"
        f"Task:\n{prompt_text}\n\n"
        f"This is chunk {chunk_index} of {chunk_count}.\n"
        "Use only the supplied Reddit content. If evidence is weak or conflicting, say so.\n"
        "When possible, cite post or comment ids exactly as written in brackets.\n\n"
        f"Dataset chunk:\n{chunk_text_value}\n"
    )


def build_synthesis_prompt(
    *,
    scope_label: str,
    prompt_text: str,
    chunk_outputs: Iterable[str],
) -> str:
    combined = "\n\n".join(chunk_outputs)
    return (
        f"You are synthesizing prior analyses of Reddit discussions from {scope_label}.\n\n"
        f"Original task:\n{prompt_text}\n\n"
        "Combine the partial analyses into one final answer.\n"
        "Deduplicate overlapping findings, rank the most recurring patterns first, and note uncertainty where appropriate.\n"
        "Prefer concrete, representative examples over vague summaries.\n\n"
        f"Chunk analyses:\n{combined}\n"
    )


def scope_label_for(subreddit: str | None, search_terms: list[str] | None) -> str:
    """Produce a human-readable label for the run's data scope."""
    if search_terms:
        if subreddit:
            return f"a Reddit search across r/{subreddit}"
        return "a global Reddit search"
    if subreddit:
        return f"r/{subreddit}"
    return "Reddit"
