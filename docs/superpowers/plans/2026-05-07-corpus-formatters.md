# Configurable Corpus Formatters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three named corpus formats (`compact`, `conversational`, `structured-json`) selectable via `[analyze].corpus_format` and `--corpus-format`, with `compact` byte-equivalent to today's output so existing projects don't change.

**Architecture:** A new `reddit_researcher/corpus_formatters.py` module owns six per-(mode, format) functions plus a `format_corpus(...)` dispatch + `VALID_CORPUS_FORMATS` constant. The existing `build_corpus` / `build_search_corpus` in `prompting.py` become thin wrappers that call `format_corpus(..., fmt="compact")` to preserve the public surface. `extract_from_run` calls `format_corpus(...)` directly using the project's `analyze.corpus_format`.

**Tech Stack:** Python 3.11+, json (stdlib), pytest.

**Spec:** [docs/superpowers/specs/2026-05-07-corpus-formatters-design.md](../specs/2026-05-07-corpus-formatters-design.md)

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `reddit_researcher/corpus_formatters.py` | create | Six per-mode formatters + `format_corpus` dispatch + `VALID_CORPUS_FORMATS` |
| `reddit_researcher/prompting.py`         | modify | `build_corpus` / `build_search_corpus` become thin wrappers around `format_corpus` |
| `reddit_researcher/config.py`            | modify | `AnalyzeConfig.corpus_format` + validation in `load_project` |
| `reddit_researcher/cli.py`               | modify | `--corpus-format` flag in `_add_analyze_overrides`; thread through `_apply_analyze_overrides` |
| `reddit_researcher/pipeline.py`          | modify | `extract_from_run` uses `format_corpus(...)` instead of direct `build_*` calls |
| `tests/test_corpus_formatters.py`        | create | All 6 formatters + dispatch error path |
| `tests/test_config.py`                   | modify | `corpus_format` parsing + validation |
| `tests/test_cli.py`                      | modify | `--corpus-format` override threads through `_apply_analyze_overrides` |
| `tests/test_extract.py`                  | modify | `extract_from_run` honors `analyze.corpus_format` |
| `docs/architecture.md`                   | modify | Short bullet describing dispatch |
| `README.md`                              | modify | "Corpus formats" subsection |
| `CHANGELOG.md`                           | modify | Entry under `0.2.0-beta` |
| `docs/roadmap.md`                        | modify | Check the corpus-formatters bullet |

---

## Task 1: `corpus_formatters.py` skeleton — `VALID_CORPUS_FORMATS` + `format_corpus` dispatch

**Files:**
- Create: `reddit_researcher/corpus_formatters.py`
- Create: `tests/test_corpus_formatters.py`

- [ ] **Step 1: Write failing tests for the dispatch surface**

Create `tests/test_corpus_formatters.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -v`
Expected: ImportError on `reddit_researcher.corpus_formatters`.

- [ ] **Step 3: Create `reddit_researcher/corpus_formatters.py` with skeleton**

```python
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
    raise NotImplementedError  # Filled in Task 4.


def _subreddit_structured_json(posts: list[dict], comments: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 5.


def _search_compact(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 3.


def _search_conversational(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 4.


def _search_structured_json(posts: list[dict]) -> str:
    raise NotImplementedError  # Filled in Task 5.
```

- [ ] **Step 4: Run tests — expect 3 passed**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run full suite — no regressions**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 179 passed, 2 skipped (current baseline) + 3 new = 182 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/corpus_formatters.py tests/test_corpus_formatters.py
git commit -m "feat: corpus_formatters.py skeleton with format_corpus dispatch"
```

---

## Task 2: Compact formatters — both modes, byte-equivalent to today

**Files:**
- Modify: `reddit_researcher/corpus_formatters.py`
- Modify: `reddit_researcher/prompting.py`
- Modify: `tests/test_corpus_formatters.py`

This task fills both compact stubs AND rewires the existing `build_corpus`/`build_search_corpus` in `prompting.py` to delegate to them. The byte-equivalence guarantee is verified two ways: (a) snapshot tests against fixed inputs, (b) the existing `tests/test_prompting.py` tests must continue to pass without modification.

- [ ] **Step 1: Write failing tests for both compact formatters**

Add to `tests/test_corpus_formatters.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure (NotImplementedError on the stubs)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -k compact -v`
Expected: 2 failed (NotImplementedError).

- [ ] **Step 3: Implement `_subreddit_compact` and `_search_compact`**

Replace the two stubs in `reddit_researcher/corpus_formatters.py` with the bodies of today's `build_corpus` and `build_search_corpus`. Open `reddit_researcher/prompting.py` and copy the body of each function verbatim into the corresponding stub.

The body of `build_corpus(posts, comments)` (currently in `prompting.py`):

```python
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
```

The body of `build_search_corpus(posts)`:

```python
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
```

- [ ] **Step 4: Make `prompting.build_corpus` and `prompting.build_search_corpus` thin wrappers**

In `reddit_researcher/prompting.py`, replace the bodies of `build_corpus` and `build_search_corpus` with delegations:

```python
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
```

Lazy-import `format_corpus` inside the functions to avoid any circular-import surprise (both modules are in the same package; should be fine either way, but lazy is defensive).

- [ ] **Step 5: Run tests — expect compact tests pass + existing prompting tests pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py tests/test_prompting.py -v`
Expected: all pass (2 new compact tests + the existing prompting tests).

- [ ] **Step 6: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 184 passed, 2 skipped (182 before + 2 new tests in this task; the prompting tests counted before too, no change in count there).

If full-suite count is off by a small amount, that's OK — what matters is everything passes.

- [ ] **Step 7: Commit**

```bash
git add reddit_researcher/corpus_formatters.py reddit_researcher/prompting.py tests/test_corpus_formatters.py
git commit -m "feat: compact corpus formatters; build_corpus/build_search_corpus thin wrappers"
```

---

## Task 3: Conversational formatters — both modes

**Files:**
- Modify: `reddit_researcher/corpus_formatters.py`
- Modify: `tests/test_corpus_formatters.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_corpus_formatters.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -k conversational -v`
Expected: 3 failed (NotImplementedError).

- [ ] **Step 3: Implement `_subreddit_conversational` and `_search_conversational`**

Replace the two stubs:

```python
def _subreddit_conversational(posts: list[dict], comments: list[dict]) -> str:
    """Markdown-headed conversational subreddit-mode corpus."""
    lines: list[str] = []

    # Build a lookup so each post's comments appear immediately after it.
    comments_by_post: dict[str, list[dict]] = {}
    for comment in comments:
        comments_by_post.setdefault(str(comment.get("post_id", "")), []).append(comment)

    for post in posts:
        subreddit = post.get("subreddit") or "unknown"
        author = post.get("author") or "unknown"
        score = post.get("score", 0)
        ncomments = post.get("num_comments", 0)
        lines.append(f"## Post: {post['title']}")
        lines.append(f"*r/{subreddit} — by {author} — {score} points, {ncomments} comments*")
        selftext = (post.get("selftext") or "").strip()
        if selftext:
            lines.append("")
            lines.append(selftext)
        for comment in comments_by_post.get(str(post.get("id", "")), []):
            c_author = comment.get("author") or "unknown"
            c_score = comment.get("score", 0)
            lines.append("")
            lines.append(f"### Comment by {c_author} ({c_score} points)")
            lines.append((comment.get("body") or "").strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _search_conversational(posts: list[dict]) -> str:
    """Markdown-headed conversational search-mode corpus, grouped by search term."""
    lines: list[str] = []
    active_term: str | None = None

    sorted_posts = sorted(
        posts, key=lambda post: (post.get("search_term") or "", -(post.get("score") or 0))
    )
    for post in sorted_posts:
        search_term = post.get("search_term") or "unknown"
        if search_term != active_term:
            if lines:
                lines.append("")
            lines.append(f"# Search term: {search_term}")
            active_term = search_term
            lines.append("")

        subreddit = post.get("subreddit") or "unknown"
        author = post.get("author") or "unknown"
        score = post.get("score", 0)
        ncomments = post.get("num_comments", 0)
        lines.append(f"## Post: {post['title']}")
        lines.append(f"*r/{subreddit} — by {author} — {score} points, {ncomments} comments*")
        selftext = (post.get("selftext") or "").strip()
        if selftext:
            lines.append("")
            lines.append(selftext)
        for comment in post.get("comments") or []:
            c_author = comment.get("author") or "unknown"
            c_score = comment.get("score", 0)
            lines.append("")
            lines.append(f"### Comment by {c_author} ({c_score} points)")
            lines.append((comment.get("body") or "").strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -k conversational -v`
Expected: 3 passed.

- [ ] **Step 5: Run full suite — no regressions**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 187 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/corpus_formatters.py tests/test_corpus_formatters.py
git commit -m "feat: conversational corpus formatters (markdown headings + prose metadata)"
```

---

## Task 4: Structured-JSON formatters — both modes

**Files:**
- Modify: `reddit_researcher/corpus_formatters.py`
- Modify: `tests/test_corpus_formatters.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_corpus_formatters.py`:

```python
import json as _json


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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -k structured_json -v`
Expected: 4 failed (NotImplementedError).

- [ ] **Step 3: Implement both structured-json formatters**

Add `import json` at the top of `reddit_researcher/corpus_formatters.py` (next to existing imports). Then replace the stubs:

```python
def _subreddit_structured_json(posts: list[dict], comments: list[dict]) -> str:
    """Structured-JSON subreddit-mode corpus: one JSON object per post,
    blank-line separated, comments nested under their post."""
    comments_by_post: dict[str, list[dict]] = {}
    for comment in comments:
        comments_by_post.setdefault(str(comment.get("post_id", "")), []).append(comment)

    blocks: list[str] = []
    for post in posts:
        obj = _post_to_json_dict(post)
        obj["comments"] = [_comment_to_json_dict(c) for c in comments_by_post.get(str(post.get("id", "")), [])]
        blocks.append(json.dumps(obj, ensure_ascii=True))

    return "\n\n".join(blocks)


def _search_structured_json(posts: list[dict]) -> str:
    """Structured-JSON search-mode corpus: same shape as subreddit-mode but
    each post object includes `search_term` and pulls comments from
    `post["comments"]`."""
    sorted_posts = sorted(
        posts, key=lambda post: (post.get("search_term") or "", -(post.get("score") or 0))
    )
    blocks: list[str] = []
    for post in sorted_posts:
        obj = _post_to_json_dict(post)
        obj["search_term"] = post.get("search_term") or ""
        obj["comments"] = [_comment_to_json_dict(c) for c in (post.get("comments") or [])]
        blocks.append(json.dumps(obj, ensure_ascii=True))
    return "\n\n".join(blocks)


def _post_to_json_dict(post: dict) -> dict:
    return {
        "id": str(post.get("id", "")),
        "subreddit": post.get("subreddit") or "unknown",
        "title": str(post.get("title", "")),
        "author": post.get("author") or "unknown",
        "score": int(post.get("score", 0) or 0),
        "body": (post.get("selftext") or "").strip(),
    }


def _comment_to_json_dict(comment: dict) -> dict:
    return {
        "id": str(comment.get("id", "")),
        "author": comment.get("author") or "unknown",
        "score": int(comment.get("score", 0) or 0),
        "body": (comment.get("body") or "").strip(),
    }
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corpus_formatters.py -k structured_json -v`
Expected: 4 passed.

- [ ] **Step 5: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 191 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/corpus_formatters.py tests/test_corpus_formatters.py
git commit -m "feat: structured-json corpus formatters (one obj per post, blank-line separated)"
```

---

## Task 5: `AnalyzeConfig.corpus_format` + `[analyze]` parsing + validation

**Files:**
- Modify: `reddit_researcher/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_analyze_corpus_format_defaults_to_compact(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n', encoding="utf-8"
    )
    project = load_project(project_dir / "project.toml")
    assert project.analyze.corpus_format == "compact"


def test_analyze_corpus_format_parsed(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n'
        '[analyze]\ncorpus_format = "conversational"\n',
        encoding="utf-8",
    )
    project = load_project(project_dir / "project.toml")
    assert project.analyze.corpus_format == "conversational"


def test_analyze_corpus_format_invalid_rejected(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "x"\n'
        '[analyze]\ncorpus_format = "yaml"\n',
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigError, match="invalid analyze.corpus_format"):
        load_project(project_dir / "project.toml")
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k corpus_format -v`
Expected: 3 failed.

- [ ] **Step 3: Add `corpus_format` to `AnalyzeConfig`**

In `reddit_researcher/config.py`, add to `AnalyzeConfig`:

```python
@dataclass
class AnalyzeConfig:
    model: str = field(default_factory=_default_ollama_model)
    prompt_file: Path | None = None
    ollama_url: str = field(default_factory=_default_ollama_url)
    ollama_timeout_seconds: int = 600
    chunk_char_limit: int = 12000
    chunk_limit: int | None = None
    force_reextract: bool = False
    corpus_format: str = "compact"
```

- [ ] **Step 4: Validate in `load_project`**

In `load_project` in `reddit_researcher/config.py`, find the `analyze = AnalyzeConfig(...)` block and add the corpus_format validation just before it:

```python
analyze_corpus_format = analyze_raw.get("corpus_format", "compact")
from .corpus_formatters import VALID_CORPUS_FORMATS

if analyze_corpus_format not in VALID_CORPUS_FORMATS:
    raise ProjectConfigError(
        f"invalid analyze.corpus_format: {analyze_corpus_format!r}. "
        f"Must be one of {sorted(VALID_CORPUS_FORMATS)}.",
        path=config_path,
    )
```

Then pass `corpus_format=analyze_corpus_format` to the `AnalyzeConfig(...)` constructor.

The `from .corpus_formatters import VALID_CORPUS_FORMATS` is intentionally inside `load_project` (not at module top) to avoid a circular import — `corpus_formatters.py` doesn't import config, but lazy-importing keeps the dependency direction clear.

- [ ] **Step 5: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k corpus_format -v`
Expected: 3 passed.

- [ ] **Step 6: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 194 passed, 2 skipped.

- [ ] **Step 7: Commit**

```bash
git add reddit_researcher/config.py tests/test_config.py
git commit -m "feat: AnalyzeConfig.corpus_format + project.toml validation"
```

---

## Task 6: `--corpus-format` CLI flag + pipeline integration

**Files:**
- Modify: `reddit_researcher/cli.py`
- Modify: `reddit_researcher/pipeline.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_extract.py`

- [ ] **Step 1: Write failing tests for the CLI override**

Add to `tests/test_cli.py`:

```python
def test_corpus_format_cli_override_threads_to_analyze_config() -> None:
    """--corpus-format overrides AnalyzeConfig.corpus_format via _apply_analyze_overrides."""
    import argparse

    from reddit_researcher.cli import _apply_analyze_overrides
    from reddit_researcher.config import AnalyzeConfig

    base = AnalyzeConfig()
    args = argparse.Namespace(
        prompt_file=None, model=None, ollama_url=None, ollama_timeout_seconds=None,
        chunk_char_limit=None, chunk_limit=None, force_reextract=False,
        corpus_format="conversational",
    )
    result = _apply_analyze_overrides(base, args)
    assert result.corpus_format == "conversational"


def test_corpus_format_cli_override_none_falls_back_to_base() -> None:
    import argparse

    from reddit_researcher.cli import _apply_analyze_overrides
    from reddit_researcher.config import AnalyzeConfig

    base = AnalyzeConfig(corpus_format="structured-json")
    args = argparse.Namespace(
        prompt_file=None, model=None, ollama_url=None, ollama_timeout_seconds=None,
        chunk_char_limit=None, chunk_limit=None, force_reextract=False,
        corpus_format=None,
    )
    result = _apply_analyze_overrides(base, args)
    assert result.corpus_format == "structured-json"
```

- [ ] **Step 2: Add a pipeline test** in `tests/test_extract.py`:

```python
def test_extract_from_run_uses_conversational_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """extract_from_run honors AnalyzeConfig.corpus_format."""
    import json as _json
    from pathlib import Path as _Path

    from reddit_researcher.config import AnalyzeConfig
    from reddit_researcher.pipeline import extract_from_run
    from reddit_researcher.storage import append_jsonl

    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "analysis" / "chunks").mkdir(parents=True)
    manifest = {
        "schema_version": 2, "mode": "subreddit", "status": "complete",
        "subreddits": ["AskReddit"], "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 1, "comment_count": 0,
    }
    (run_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")
    append_jsonl(
        run_dir / "normalized" / "posts.jsonl",
        {"id": "p1", "subreddit": "AskReddit", "title": "Hello", "author": "alice",
         "selftext": "world", "url": "u", "permalink": "/p1", "score": 1,
         "upvote_ratio": 0.9, "num_comments": 0, "created_utc": 1.0,
         "over_18": False, "is_self": True, "link_flair_text": None,
         "sort": "top", "time_filter": "month"},
    )
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Summarize.", encoding="utf-8")

    captured: dict[str, str] = {}

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def generate(self, *, model: str, prompt: str) -> str:
            captured["last_prompt"] = prompt
            return "stub response"

    monkeypatch.setattr("reddit_researcher.pipeline.OllamaClient", _StubClient)

    analyze = AnalyzeConfig(
        prompt_file=prompt_file, corpus_format="conversational", chunk_char_limit=10000,
    )
    extract_from_run(run_dir=run_dir, analyze=analyze)

    assert "## Post: Hello" in captured["last_prompt"]
    assert "[POST p1]" not in captured["last_prompt"]
```

- [ ] **Step 3: Run, expect failures**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -k corpus_format tests/test_extract.py -k conversational -v`
Expected: failures (CLI flag missing; pipeline still uses build_corpus directly).

- [ ] **Step 4: Add the CLI flag**

In `reddit_researcher/cli.py`, find `_add_analyze_overrides` and add:

```python
def _add_analyze_overrides(parser: argparse.ArgumentParser, *, require_prompt: bool = False) -> None:
    parser.add_argument("--prompt-file", required=require_prompt)
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--ollama-timeout-seconds", type=int, default=None)
    parser.add_argument("--chunk-char-limit", type=int, default=None)
    parser.add_argument("--chunk-limit", type=int, default=None)
    parser.add_argument("--force-reextract", action="store_true")
    parser.add_argument(
        "--corpus-format",
        default=None,
        choices=["compact", "conversational", "structured-json"],
        help="Override [analyze].corpus_format for this run.",
    )
```

In `_apply_analyze_overrides`, add the override:

```python
def _apply_analyze_overrides(base: AnalyzeConfig, args: argparse.Namespace) -> AnalyzeConfig:
    return AnalyzeConfig(
        model=args.model or base.model,
        prompt_file=Path(args.prompt_file) if getattr(args, "prompt_file", None) else base.prompt_file,
        ollama_url=args.ollama_url or base.ollama_url,
        ollama_timeout_seconds=args.ollama_timeout_seconds or base.ollama_timeout_seconds,
        chunk_char_limit=args.chunk_char_limit or base.chunk_char_limit,
        chunk_limit=args.chunk_limit if args.chunk_limit is not None else base.chunk_limit,
        force_reextract=base.force_reextract or bool(getattr(args, "force_reextract", False)),
        corpus_format=getattr(args, "corpus_format", None) or base.corpus_format,
    )
```

- [ ] **Step 5: Wire `format_corpus` into `extract_from_run`**

In `reddit_researcher/pipeline.py`, update the imports near the top (where `from .prompting import ...` lives):

```python
from .corpus_formatters import format_corpus
```

Inside `extract_from_run`, find the line:

```python
corpus = build_search_corpus(posts=posts) if is_search else build_corpus(posts=posts, comments=comments)
```

Replace with:

```python
corpus = format_corpus(
    mode="search" if is_search else "subreddit",
    fmt=analyze.corpus_format,
    posts=posts,
    comments=None if is_search else comments,
)
```

The existing `from .prompting import ... build_corpus, build_search_corpus, ...` line can stay — those wrappers are still public surface, just no longer called by `extract_from_run`. (If ruff flags an unused import after the change, remove just the unused names.)

- [ ] **Step 6: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -k corpus_format tests/test_extract.py -k conversational -v`
Expected: 3 passed.

- [ ] **Step 7: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 197 passed, 2 skipped.

- [ ] **Step 8: Commit**

```bash
git add reddit_researcher/cli.py reddit_researcher/pipeline.py tests/test_cli.py tests/test_extract.py
git commit -m "feat: --corpus-format CLI flag; extract_from_run honors analyze.corpus_format"
```

---

## Task 7: Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/roadmap.md`**

Find the `## 0.2.0 — analytics` block. Currently:

```markdown
- [ ] Configurable corpus formatters (compact, conversational, structured-JSON-for-tools).
```

Change to:

```markdown
- [x] Configurable corpus formatters (compact, conversational, structured-JSON-for-tools). *(0.2.0)*
```

- [ ] **Step 2: `docs/architecture.md`**

Find the existing prompting/extract section (or insert near the bottom of the architecture doc, after the Storage section). Add:

```markdown
## Corpus formatters

`reddit_researcher/corpus_formatters.py` owns the dispatch between three named
corpus shapes — `compact` (default, byte-equivalent to legacy output),
`conversational` (markdown headings + prose metadata), and `structured-json`
(one JSON object per post, blank-line separated). Selected via
`[analyze].corpus_format` in `project.toml`, overridable per-run with
`--corpus-format`. The legacy `build_corpus`/`build_search_corpus` in
`prompting.py` are now thin wrappers that call `format_corpus(..., fmt="compact")`.
```

- [ ] **Step 3: `README.md`**

Read the README first to find the right placement (probably near the existing usage section). Insert:

```markdown
### Corpus formats

The text corpus passed to the LLM has three selectable shapes:

- `compact` (default) — terse `[POST id] r/subreddit title: ...` markers, the historical format.
- `conversational` — markdown headings, prose metadata, more readable.
- `structured-json` — one JSON object per post, blank-line separated. Best when wrapping the LLM in tools.

Set the format in `project.toml`:

```toml
[analyze]
corpus_format = "conversational"
```

Or override on a single run:

```bash
reddit-researcher run my-project --corpus-format structured-json
```
```

(Use real triple-backticks in the file.)

- [ ] **Step 4: `CHANGELOG.md`**

Under the existing `## 0.2.0-beta` "Added" section, add:

```markdown
- **Configurable corpus formatters.** New `[analyze].corpus_format` field
  selects between `compact` (default, byte-equivalent to today's output),
  `conversational` (markdown headings + prose metadata), and `structured-json`
  (one JSON object per post, blank-line separated). Override per-run with
  `--corpus-format`. The legacy `build_corpus` / `build_search_corpus` are
  now thin wrappers around `format_corpus`.
```

- [ ] **Step 5: Sanity check**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 197 passed, 2 skipped.

Run: `.\.venv\Scripts\python.exe -m pytest --cov=reddit_researcher --cov-report=term-missing 2>&1 | findstr /C:"TOTAL"`
Expected: coverage ≥ 85%.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md README.md CHANGELOG.md docs/roadmap.md
git commit -m "docs: configurable corpus formatters — architecture, README, CHANGELOG, roadmap"
```

---

## Self-Review Notes

**Spec coverage:**

| Spec section | Task |
|--------------|------|
| Goals / Non-goals | Implicit in scope |
| Format shapes | Tasks 2 (compact), 3 (conversational), 4 (structured-json) |
| Module + dispatch | Task 1 (skeleton + dispatch); Task 2 (legacy wrappers) |
| Config | Task 5 |
| CLI | Task 6 |
| Pipeline | Task 6 |
| Testing items 1-2 | Task 2 |
| Testing items 3-4 | Task 3 |
| Testing items 5-6 | Task 4 |
| Testing item 7 | Task 1 |
| Testing items 8-11 | Task 5 + Task 6 |
| Testing items 12-13 | Task 6 |
| Documentation | Task 7 |
| Risks (snapshot drift, JSON chunking, future format) | Task 2 (byte-eq), Task 4 (escape-newlines test), Task 1 (dispatch is explicit if/elif) |

**Type/method consistency:**

- `format_corpus(*, mode, fmt, posts, comments=None)` signature stable across Tasks 1-6.
- `VALID_CORPUS_FORMATS = {"compact", "conversational", "structured-json"}` defined in Task 1, imported in Task 5 (config validation) and Task 6 (CLI choices — but Task 6 hardcodes the choices to avoid the import; both lists must stay in sync. The hardcoded `choices=[...]` in `_add_analyze_overrides` is explicit so the help text is correct without an import-time dependency).
- `_post_to_json_dict` and `_comment_to_json_dict` defined in Task 4, used by both structured-json formatters.
- `AnalyzeConfig.corpus_format: str = "compact"` defined in Task 5, read by `extract_from_run` in Task 6.

**Placeholder scan:** none.
