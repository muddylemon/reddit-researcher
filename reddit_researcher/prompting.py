from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


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
    """Build a text corpus for subreddit-mode runs (posts + flat comments).

    Thin wrapper around `corpus_formatters.format_corpus` for backward compat.
    """
    from .corpus_formatters import format_corpus

    return format_corpus(mode="subreddit", fmt="compact", posts=posts, comments=comments)


def build_search_corpus(posts: list[dict]) -> str:
    """Build a text corpus for search-mode runs, grouped by search term.

    Thin wrapper around `corpus_formatters.format_corpus` for backward compat.
    """
    from .corpus_formatters import format_corpus

    return format_corpus(mode="search", fmt="compact", posts=posts)


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


def scope_label_for(
    subreddit: str | None,
    search_terms: list[str] | None,
    subreddits: list[str] | None = None,
) -> str:
    """Produce a human-readable label for the run's data scope.

    Accepts either a single `subreddit` (legacy callers) or a `subreddits`
    list (multi-sub mode). Search-mode takes precedence when `search_terms`
    is truthy.
    """
    if search_terms:
        if subreddit:
            return f"a Reddit search across r/{subreddit}"
        return "a global Reddit search"

    if subreddits:
        if len(subreddits) == 1:
            return f"r/{subreddits[0]}"
        if len(subreddits) == 2:
            return f"r/{subreddits[0]} and r/{subreddits[1]}"
        if len(subreddits) <= 5:
            return ", ".join(f"r/{s}" for s in subreddits)
        head = ", ".join(f"r/{s}" for s in subreddits[:3])
        return f"{head}, and {len(subreddits) - 3} others"

    if subreddit:
        return f"r/{subreddit}"
    return "Reddit"
