# `reddit-researcher diff` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `reddit-researcher diff <run-a> <run-b>` CLI subcommand that compares two run dirs (counts + post_id set membership + relevance flips) by reading from the SQLite/DuckDB sink, auto-syncing each run if not already present.

**Architecture:** A new `reddit_researcher/diff.py` module owns the structured logic (`compute_diff`, `format_text`, `format_json`) so it stays unit-testable independent of argparse. The CLI handler resolves the project, opens a sink, syncs each run if stale, then calls `compute_diff` and prints the chosen format.

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), the existing `RunSink` Protocol from `reddit_researcher/db.py`, argparse.

**Spec:** [docs/superpowers/specs/2026-05-07-diff-command-design.md](../specs/2026-05-07-diff-command-design.md)

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `reddit_researcher/diff.py`     | create | `RunSummary`, `DiffResult`, `compute_diff`, `format_text`, `format_json` |
| `reddit_researcher/cli.py`      | modify | New `diff` subparser + `_dispatch_diff` handler with sync-on-the-fly |
| `tests/test_diff.py`            | create | Unit tests for `compute_diff`/`format_text`/`format_json` + CLI E2E |
| `docs/architecture.md`          | modify | One sentence in Storage section pointing at `diff` |
| `README.md`                     | modify | New "Comparing runs" subsection |
| `CHANGELOG.md`                  | modify | Entry under `0.2.0-beta` |
| `docs/roadmap.md`               | modify | Check the `diff` bullet |

---

## Task 1: `diff.py` skeleton — dataclasses + empty `compute_diff`

**Files:**
- Create: `reddit_researcher/diff.py`
- Create: `tests/test_diff.py`

- [ ] **Step 1: Write failing test for the module shape**

Create `tests/test_diff.py`:

```python
"""Tests for reddit_researcher.diff."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import make_sink, sync_run
from reddit_researcher.diff import (
    DiffResult,
    RunSummary,
    compute_diff,
    format_json,
    format_text,
)
from reddit_researcher.storage import append_jsonl


def _post_row(post_id: str, subreddit: str = "AskReddit") -> dict:
    return {
        "id": post_id,
        "subreddit": subreddit,
        "title": f"Title {post_id}",
        "author": "alice",
        "selftext": "body",
        "url": f"https://reddit.com/{post_id}",
        "permalink": f"/r/{subreddit}/comments/{post_id}/",
        "score": 1,
        "upvote_ratio": 0.9,
        "num_comments": 0,
        "created_utc": 1.0,
        "over_18": False,
        "is_self": True,
        "link_flair_text": None,
        "sort": "top",
        "time_filter": "month",
        "comments": [],
    }


def _comment_row(comment_id: str, post_id: str) -> dict:
    return {
        "id": comment_id,
        "post_id": post_id,
        "parent_id": f"t3_{post_id}",
        "author": "bob",
        "body": "comment body",
        "score": 1,
        "created_utc": 2.0,
        "permalink": f"/r/x/comments/{post_id}/_/{comment_id}/",
        "depth": 0,
    }


def _make_synced_run(
    sink, tmp_path: Path, *, scope: str, ts: str, mode: str = "subreddit",
    posts: list[dict] | None = None, comments: list[dict] | None = None,
    decisions: list[dict] | None = None, project_name: str | None = "demo",
) -> Path:
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "status": "complete",
        "subreddits": [scope] if mode == "subreddit" else [],
        "scraped_at_utc": f"2026-05-07T{ts[-6:-4]}:00:00+00:00",
        "post_count": len(posts or []),
        "comment_count": len(comments or []),
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts or []:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    for c in comments or []:
        append_jsonl(run_dir / "normalized" / "comments.jsonl", c)
    for d in decisions or []:
        append_jsonl(run_dir / "review" / "relevance_review.jsonl", d)
    sync_run(sink, run_dir)
    return run_dir


def test_compute_diff_returns_diffresult(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert isinstance(result, DiffResult)
        assert isinstance(result.a, RunSummary)
        assert isinstance(result.b, RunSummary)
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_returns_diffresult -v`
Expected: ImportError on `reddit_researcher.diff`.

- [ ] **Step 3: Create `reddit_researcher/diff.py`**

```python
"""Compute and format a diff between two run dirs.

Reads from the SQLite/DuckDB sink. The CLI handler is responsible for
ensuring both runs are synced before calling `compute_diff`.

JSONL on disk remains canonical; `compute_diff` is a pure read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .db import RunSink


@dataclass
class RunSummary:
    run_dir: Path
    mode: str
    scope: str
    project_name: str | None
    scraped_at_utc: str
    post_count: int
    comment_count: int


@dataclass
class DiffResult:
    a: RunSummary
    b: RunSummary
    posts_only_in_a: list[str] = field(default_factory=list)
    posts_only_in_b: list[str] = field(default_factory=list)
    posts_in_both: list[str] = field(default_factory=list)
    comments_only_in_a: int = 0
    comments_only_in_b: int = 0
    comments_in_both: int = 0
    relevance_changes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _summary_for(conn: Any, run_dir: Path) -> RunSummary:
    """Read the runs row for one run dir into a RunSummary."""
    row = conn.execute(
        "SELECT mode, scope, project_name, scraped_at_utc, post_count, comment_count "
        "FROM runs WHERE run_dir = ?",
        (str(run_dir.resolve()),),
    ).fetchone()
    if row is None:
        raise LookupError(f"run_dir not in sink: {run_dir}")
    return RunSummary(
        run_dir=run_dir.resolve(),
        mode=row[0],
        scope=row[1],
        project_name=row[2],
        scraped_at_utc=row[3],
        post_count=int(row[4]),
        comment_count=int(row[5]),
    )


def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Compute the structured diff between two synced runs."""
    conn = sink.read_only_connect()
    try:
        a = _summary_for(conn, run_a)
        b = _summary_for(conn, run_b)
        return DiffResult(a=a, b=b)
    finally:
        conn.close()


def format_text(result: DiffResult) -> str:
    return f"=== Diff: A vs B ===\n(stub — populated in Task 7)\n"


def format_json(result: DiffResult) -> str:
    return json.dumps(asdict(result), default=str, ensure_ascii=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_returns_diffresult -v`
Expected: 1 passed.

- [ ] **Step 5: Run full suite — no regressions**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 163 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: diff.py skeleton with RunSummary + DiffResult dataclasses"
```

---

## Task 2: `compute_diff` populates posts set diff

**Files:**
- Modify: `reddit_researcher/diff.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_diff.py`:

```python
def test_compute_diff_posts_only_in_a(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3"), _post_row("p4")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert sorted(result.posts_only_in_a) == ["p1"]
        assert sorted(result.posts_only_in_b) == ["p4"]
        assert sorted(result.posts_in_both) == ["p2", "p3"]
    finally:
        sink.close()


def test_compute_diff_identical_post_sets(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1"), _post_row("p2")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert result.posts_only_in_a == []
        assert result.posts_only_in_b == []
        assert sorted(result.posts_in_both) == ["p1", "p2"]
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k "posts_only_in_a or identical_post_sets" -v`
Expected: 2 failed (lists are empty).

- [ ] **Step 3: Add post-set query to `compute_diff`**

Replace the body of `compute_diff` in `reddit_researcher/diff.py`:

```python
def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Compute the structured diff between two synced runs."""
    a_str = str(run_a.resolve())
    b_str = str(run_b.resolve())
    conn = sink.read_only_connect()
    try:
        a = _summary_for(conn, run_a)
        b = _summary_for(conn, run_b)
        result = DiffResult(a=a, b=b)
        _fill_posts(conn, a_str, b_str, result)
        return result
    finally:
        conn.close()


def _fill_posts(conn: Any, a_str: str, b_str: str, result: DiffResult) -> None:
    a_ids = {row[0] for row in conn.execute(
        "SELECT post_id FROM posts WHERE run_dir = ?", (a_str,)
    )}
    b_ids = {row[0] for row in conn.execute(
        "SELECT post_id FROM posts WHERE run_dir = ?", (b_str,)
    )}
    result.posts_only_in_a = sorted(a_ids - b_ids)
    result.posts_only_in_b = sorted(b_ids - a_ids)
    result.posts_in_both = sorted(a_ids & b_ids)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k "posts_only_in_a or identical_post_sets" -v`
Expected: 2 passed.

- [ ] **Step 5: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 165 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: compute_diff fills post_id set diff (only-in-A / only-in-B / both)"
```

---

## Task 3: `compute_diff` populates comments set-diff counts

**Files:**
- Modify: `reddit_researcher/diff.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_diff.py`:

```python
def test_compute_diff_comments_set_counts(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            comments=[_comment_row("c1", "p1"), _comment_row("c2", "p1"), _comment_row("c3", "p1")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1")],
            comments=[_comment_row("c2", "p1"), _comment_row("c3", "p1"), _comment_row("c4", "p1")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert result.comments_only_in_a == 1   # c1
        assert result.comments_only_in_b == 1   # c4
        assert result.comments_in_both == 2     # c2, c3
    finally:
        sink.close()
```

- [ ] **Step 2: Run test — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_comments_set_counts -v`
Expected: 1 failed (counts are 0).

- [ ] **Step 3: Add comments set-diff to `compute_diff`**

In `reddit_researcher/diff.py`, add a `_fill_comments` helper and call it in `compute_diff`:

```python
def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Compute the structured diff between two synced runs."""
    a_str = str(run_a.resolve())
    b_str = str(run_b.resolve())
    conn = sink.read_only_connect()
    try:
        a = _summary_for(conn, run_a)
        b = _summary_for(conn, run_b)
        result = DiffResult(a=a, b=b)
        _fill_posts(conn, a_str, b_str, result)
        _fill_comments(conn, a_str, b_str, result)
        return result
    finally:
        conn.close()


def _fill_comments(conn: Any, a_str: str, b_str: str, result: DiffResult) -> None:
    a_ids = {row[0] for row in conn.execute(
        "SELECT comment_id FROM comments WHERE run_dir = ?", (a_str,)
    )}
    b_ids = {row[0] for row in conn.execute(
        "SELECT comment_id FROM comments WHERE run_dir = ?", (b_str,)
    )}
    result.comments_only_in_a = len(a_ids - b_ids)
    result.comments_only_in_b = len(b_ids - a_ids)
    result.comments_in_both = len(a_ids & b_ids)
```

- [ ] **Step 4: Run test — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_comments_set_counts -v`
Expected: 1 passed.

- [ ] **Step 5: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 166 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: compute_diff fills comment_id set-diff counts"
```

---

## Task 4: `compute_diff` populates `relevance_changes`

**Files:**
- Modify: `reddit_researcher/diff.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_diff.py`:

```python
def test_compute_diff_relevance_changes(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
                {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "off-topic"},
                {"post_id": "p3", "subreddit": "AskReddit", "decision": "review", "reason": "ambiguous"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule changed"},
                {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "off-topic"},
                {"post_id": "p3", "subreddit": "AskReddit", "decision": "include", "reason": "now matches"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        # Two flips: p1 (include→exclude), p3 (review→include). p2 unchanged.
        changes_by_id = {c["post_id"]: c for c in result.relevance_changes}
        assert set(changes_by_id) == {"p1", "p3"}
        assert changes_by_id["p1"]["a_decision"] == "include"
        assert changes_by_id["p1"]["b_decision"] == "exclude"
        assert changes_by_id["p3"]["a_decision"] == "review"
        assert changes_by_id["p3"]["b_decision"] == "include"
    finally:
        sink.close()
```

- [ ] **Step 2: Run test — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_relevance_changes -v`
Expected: 1 failed (relevance_changes is empty).

- [ ] **Step 3: Add `_fill_relevance_changes`**

In `reddit_researcher/diff.py`:

```python
def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Compute the structured diff between two synced runs."""
    a_str = str(run_a.resolve())
    b_str = str(run_b.resolve())
    conn = sink.read_only_connect()
    try:
        a = _summary_for(conn, run_a)
        b = _summary_for(conn, run_b)
        result = DiffResult(a=a, b=b)
        _fill_posts(conn, a_str, b_str, result)
        _fill_comments(conn, a_str, b_str, result)
        _fill_relevance_changes(conn, a_str, b_str, result)
        return result
    finally:
        conn.close()


def _fill_relevance_changes(conn: Any, a_str: str, b_str: str, result: DiffResult) -> None:
    rows = conn.execute(
        "SELECT a.post_id, a.decision, b.decision "
        "FROM relevance_decisions a JOIN relevance_decisions b "
        "  ON a.post_id = b.post_id AND a.search_term = b.search_term "
        "WHERE a.run_dir = ? AND b.run_dir = ? AND a.decision != b.decision "
        "ORDER BY a.post_id",
        (a_str, b_str),
    ).fetchall()
    result.relevance_changes = [
        {"post_id": row[0], "a_decision": row[1], "b_decision": row[2]} for row in rows
    ]
```

- [ ] **Step 4: Run test — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_compute_diff_relevance_changes -v`
Expected: 1 passed.

- [ ] **Step 5: Full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 167 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: compute_diff fills relevance_changes (decision flips on shared posts)"
```

---

## Task 5: `compute_diff` populates mismatch warnings

**Files:**
- Modify: `reddit_researcher/diff.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_diff.py`:

```python
def test_compute_diff_warns_on_mode_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000", mode="subreddit",
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="all-reddit-search", ts="20260508-120000", mode="search",
        )
        result = compute_diff(sink, run_a, run_b)
        assert any("mode mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_warns_on_scope_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="worldnews", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert any("scope mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_warns_on_project_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000", project_name="alpha",
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000", project_name="beta",
        )
        result = compute_diff(sink, run_a, run_b)
        assert any("project mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_no_warnings_when_runs_match(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert result.warnings == []
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k "warns_on or no_warnings" -v`
Expected: 3 failed (warnings empty), 1 passed (no_warnings — already empty).

- [ ] **Step 3: Add `_fill_warnings`**

In `reddit_researcher/diff.py`:

```python
def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Compute the structured diff between two synced runs."""
    a_str = str(run_a.resolve())
    b_str = str(run_b.resolve())
    conn = sink.read_only_connect()
    try:
        a = _summary_for(conn, run_a)
        b = _summary_for(conn, run_b)
        result = DiffResult(a=a, b=b)
        _fill_posts(conn, a_str, b_str, result)
        _fill_comments(conn, a_str, b_str, result)
        _fill_relevance_changes(conn, a_str, b_str, result)
        _fill_warnings(result)
        return result
    finally:
        conn.close()


def _fill_warnings(result: DiffResult) -> None:
    if result.a.mode != result.b.mode:
        result.warnings.append(f"mode mismatch: A={result.a.mode}, B={result.b.mode}")
    if result.a.scope != result.b.scope:
        result.warnings.append(f"scope mismatch: A={result.a.scope}, B={result.b.scope}")
    if result.a.project_name != result.b.project_name:
        result.warnings.append(
            f"project mismatch: A={result.a.project_name}, B={result.b.project_name}"
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k "warns_on or no_warnings" -v`
Expected: 4 passed.

- [ ] **Step 5: Full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 171 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: compute_diff warns on mode/scope/project mismatch"
```

---

## Task 6: `format_text` real implementation

**Files:**
- Modify: `reddit_researcher/diff.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_diff.py`:

```python
def test_format_text_includes_summary_and_counts(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            comments=[_comment_row("c1", "p1")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3")],
            comments=[_comment_row("c1", "p2"), _comment_row("c2", "p2")],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "Diff: A vs B" in text
        assert "AskReddit" in text
        assert "posts:" in text
        assert "only-in-A=1" in text
        assert "only-in-B=1" in text
        assert "in-both=1" in text
        assert "p1" in text       # listed in only-in-A
        assert "p3" in text       # listed in only-in-B
    finally:
        sink.close()


def test_format_text_caps_long_lists(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        # 25 posts only in A — text format should cap at 20 and append "(+N more)".
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row(f"p{i:02d}") for i in range(25)],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "(+5 more)" in text
    finally:
        sink.close()


def test_format_text_includes_relevance_changes(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "relevance changes" in text.lower()
        assert "include -> exclude" in text or "include → exclude" in text
```

- [ ] **Step 2: Run tests — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k format_text -v`
Expected: 3 failed (current `format_text` is the stub).

- [ ] **Step 3: Implement `format_text`**

Replace the stub `format_text` in `reddit_researcher/diff.py`:

```python
_TEXT_LIST_CAP = 20


def format_text(result: DiffResult) -> str:
    lines: list[str] = []
    lines.append("=== Diff: A vs B ===")
    lines.append("")
    lines.append(_format_summary("A", result.a))
    lines.append(_format_summary("B", result.b))
    lines.append("")
    lines.append(
        f"posts: A={result.a.post_count}, B={result.b.post_count}, "
        f"only-in-A={len(result.posts_only_in_a)}, "
        f"only-in-B={len(result.posts_only_in_b)}, "
        f"in-both={len(result.posts_in_both)}"
    )
    lines.append(
        f"comments: A={result.a.comment_count}, B={result.b.comment_count}, "
        f"only-in-A={result.comments_only_in_a}, "
        f"only-in-B={result.comments_only_in_b}, "
        f"in-both={result.comments_in_both}"
    )
    lines.append(f"relevance changes (in-both posts whose decision flipped): "
                 f"{len(result.relevance_changes)}")
    lines.append("")
    lines.append(f"posts only in A ({len(result.posts_only_in_a)}):")
    lines.extend(_capped_id_block(result.posts_only_in_a))
    lines.append("")
    lines.append(f"posts only in B ({len(result.posts_only_in_b)}):")
    lines.extend(_capped_id_block(result.posts_only_in_b))
    if result.relevance_changes:
        lines.append("")
        lines.append("relevance changes:")
        for change in result.relevance_changes:
            lines.append(
                f"  {change['post_id']:<10}  {change['a_decision']} -> {change['b_decision']}"
            )
    return "\n".join(lines) + "\n"


def _format_summary(label: str, summary: RunSummary) -> str:
    return (
        f"{label}: {summary.run_dir}  "
        f"({summary.mode}, {summary.scope}, {summary.scraped_at_utc})\n"
        f"   project={summary.project_name}  "
        f"posts={summary.post_count}  comments={summary.comment_count}"
    )


def _capped_id_block(ids: list[str]) -> list[str]:
    if not ids:
        return ["  (none)"]
    shown = ids[:_TEXT_LIST_CAP]
    lines = ["  " + ", ".join(shown[i:i + 8]) for i in range(0, len(shown), 8)]
    extra = len(ids) - len(shown)
    if extra > 0:
        lines.append(f"  ... (+{extra} more)")
    return lines
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k format_text -v`
Expected: 3 passed.

- [ ] **Step 5: Full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 174 passed, 1 skipped.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/diff.py tests/test_diff.py
git commit -m "feat: format_text — counts header, capped id lists, relevance changes"
```

---

## Task 7: `format_json` round-trip test

**Files:**
- Modify: `tests/test_diff.py` only (the implementation in Task 1 is already correct)

- [ ] **Step 1: Write a confirming test**

Add to `tests/test_diff.py`:

```python
def test_format_json_round_trip(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            comments=[_comment_row("c1", "p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3")],
            comments=[_comment_row("c2", "p2")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        payload = json.loads(format_json(result))
        # All DiffResult fields present.
        for key in (
            "a", "b", "posts_only_in_a", "posts_only_in_b", "posts_in_both",
            "comments_only_in_a", "comments_only_in_b", "comments_in_both",
            "relevance_changes", "warnings",
        ):
            assert key in payload, f"missing key: {key}"
        # Lists round-trip without truncation (unlike text).
        assert payload["posts_only_in_a"] == ["p1"]
        assert payload["posts_only_in_b"] == ["p3"]
        assert payload["posts_in_both"] == ["p2"]
        # Path serialized via default=str.
        assert isinstance(payload["a"]["run_dir"], str)
    finally:
        sink.close()
```

- [ ] **Step 2: Run test — expect pass (format_json already implemented in Task 1)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py::test_format_json_round_trip -v`
Expected: 1 passed.

If it fails, fix the underlying bug — the spec requires `format_json` to round-trip cleanly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_diff.py
git commit -m "test: format_json round-trip with full DiffResult fields"
```

---

## Task 8: CLI `diff` subcommand + sync-on-the-fly

**Files:**
- Modify: `reddit_researcher/cli.py`
- Modify: `tests/test_diff.py`

- [ ] **Step 1: Write failing CLI tests**

Add to `tests/test_diff.py`:

```python
from reddit_researcher.cli import main as cli_main


def _write_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "AskReddit"\n'
        '[storage]\ndb_path = "r.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    return project_dir


def _write_run_jsonl_only(
    tmp_path: Path, *, scope: str, ts: str, posts: list[dict], project_name: str | None = "demo",
) -> Path:
    """Write a run dir to disk WITHOUT syncing (CLI is supposed to auto-sync)."""
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": [scope],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": len(posts),
        "comment_count": 0,
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    return run_dir


def test_cli_diff_text_format_auto_syncs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1"), _post_row("p2")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260508-120000",
        posts=[_post_row("p2"), _post_row("p3")],
    )
    rc = cli_main(["diff", str(run_a), str(run_b), "--project", str(project_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Diff: A vs B" in out
    assert "p1" in out
    assert "p3" in out


def test_cli_diff_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260508-120000",
        posts=[_post_row("p1")],
    )
    rc = cli_main([
        "diff", str(run_a), str(run_b),
        "--project", str(project_dir), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["posts_in_both"] == ["p1"]


def test_cli_diff_missing_run_dir_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")],
    )
    bogus = tmp_path / "nope"
    rc = cli_main(["diff", str(run_a), str(bogus), "--project", str(project_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "manifest" in err.lower() or "not found" in err.lower() or "no such" in err.lower()


def test_cli_diff_warnings_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000", posts=[_post_row("p1")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="worldnews", ts="20260508-120000", posts=[_post_row("p2", subreddit="worldnews")],
    )
    rc = cli_main(["diff", str(run_a), str(run_b), "--project", str(project_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "warning:" in captured.err.lower()
    assert "scope mismatch" in captured.err.lower()
```

- [ ] **Step 2: Run tests — expect failure (no `diff` subcommand)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k cli_diff -v`
Expected: argparse errors — no `diff` subcommand registered.

- [ ] **Step 3: Add `diff` subparser in `reddit_researcher/cli.py`**

In `build_parser()`, after the `db_query_parser = ...` block (or anywhere within `subparsers.add_parser(...)` calls), add:

```python
    diff_parser = subparsers.add_parser(
        "diff",
        help="Compare two run directories (counts, post-id sets, relevance flips).",
    )
    diff_parser.add_argument("run_a", help="First run directory.")
    diff_parser.add_argument("run_b", help="Second run directory.")
    diff_parser.add_argument("--project", default=None, help="Path to project.toml or its directory.")
    diff_parser.add_argument(
        "--format", default="text", choices=["text", "json"],
        help="Output format (default text).",
    )
```

In `_dispatch(args, parser)`, before the final `parser.error("Unsupported command: ...")`, add:

```python
    if args.command == "diff":
        return _dispatch_diff(args, parser)
```

Add a new `_dispatch_diff` function near `_dispatch_db` in `cli.py`:

```python
def _dispatch_diff(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .db import make_sink, sync_run
    from .diff import compute_diff, format_json, format_text

    run_a = Path(args.run_a).resolve()
    run_b = Path(args.run_b).resolve()
    for label, run_dir in (("run_a", run_a), ("run_b", run_b)):
        if not (run_dir / "manifest.json").exists():
            parser.error(f"diff: no manifest.json under {label}: {run_dir}")

    project_arg = getattr(args, "project", None)
    if project_arg is None:
        candidate = Path.cwd() / "project.toml"
        if not candidate.exists():
            parser.error(
                "diff: pass --project <path> or run from a directory containing project.toml."
            )
        project_path = candidate
    else:
        project_path = find_project_config(Path(project_arg))
    load_dotenvs_for(project_dir=project_path.parent, repo_root=REPO_ROOT)
    project = load_project(project_path)

    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        for run_dir in (run_a, run_b):
            if _needs_sync(sink, run_dir):
                try:
                    sync_run(sink, run_dir)
                except (FileNotFoundError, OSError) as exc:
                    parser.error(f"diff: {exc}")
        try:
            result = compute_diff(sink, run_a, run_b)
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        sink.close()

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.format == "json":
        print(format_json(result))
    else:
        print(format_text(result), end="")
    return 0


def _needs_sync(sink, run_dir: Path) -> bool:
    """True if the run isn't in the sink, or the manifest is newer than the synced row."""
    import json as _json

    ro = sink.read_only_connect()
    try:
        row = ro.execute(
            "SELECT synced_at_utc FROM runs WHERE run_dir = ?", (str(run_dir.resolve()),)
        ).fetchone()
    finally:
        ro.close()
    if row is None:
        return True
    try:
        manifest = _json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return False
    updated = manifest.get("updated_at_utc")
    if updated is None:
        return False
    return str(updated) > str(row[0])
```

- [ ] **Step 4: Run tests — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_diff.py -k cli_diff -v`
Expected: 4 passed.

- [ ] **Step 5: Full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 179 passed, 1 skipped.

- [ ] **Step 6: Ruff: no NEW issues**

Run: `.\.venv\Scripts\python.exe -m ruff check reddit_researcher tests`

- [ ] **Step 7: Commit**

```bash
git add reddit_researcher/cli.py tests/test_diff.py
git commit -m "feat: 'reddit-researcher diff' CLI with sync-on-the-fly"
```

---

## Task 9: Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/roadmap.md`**

Find the `## 0.2.0 — analytics` block and change the diff bullet from unchecked to checked:

```markdown
- [x] `reddit-researcher diff <run-a> <run-b>` to compare two runs of the same project. *(0.2.0)*
```

- [ ] **Step 2: `docs/architecture.md`**

In the existing "Storage (optional DB sink)" section, append a one-line bullet (or short paragraph at the bottom of that section) noting that `diff` is a sink consumer:

```markdown
- **`diff` consumer:** `reddit-researcher diff <run-a> <run-b>` reads from this
  sink, auto-syncing each run if missing or stale.
```

- [ ] **Step 3: `README.md`**

After the "Querying across runs" subsection, insert:

```markdown
### Comparing runs

`reddit-researcher diff <run-a> <run-b>` shows what changed between two runs
(counts, which posts appeared/disappeared, which relevance decisions flipped).
Both runs are auto-synced into the DB if not already present.

\`\`\`bash
reddit-researcher diff runs/AskReddit/20260507-120000 runs/AskReddit/20260508-120000
\`\`\`

For machine-readable output, pass `--format json`. Mismatched modes/scopes
warn to stderr but the diff still runs.
```

(Use real triple-backticks in the actual file — escaped here only because they would close the prompt fence.)

- [ ] **Step 4: `CHANGELOG.md`**

Under the existing `## 0.2.0-beta` "Added" section, add:

```markdown
- **`reddit-researcher diff <run-a> <run-b>`.** Compare two runs of (typically)
  the same project: counts diff, post_id set membership (only-in-A,
  only-in-B, in-both), comment counts, and relevance-decision flips. Reads
  from the SQLite/DuckDB sink and auto-syncs each run if missing. Text
  table by default; `--format json` for piping. Warns on mode/scope/project
  mismatch but always produces a result.
```

- [ ] **Step 5: Sanity check**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 179 passed, 1 skipped.

Run: `.\.venv\Scripts\python.exe -m pytest --cov=reddit_researcher --cov-report=term-missing 2>&1 | findstr /C:"TOTAL"`
Expected: coverage ≥ 85%.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md README.md CHANGELOG.md docs/roadmap.md
git commit -m "docs: 'diff' subcommand — architecture, README, CHANGELOG, roadmap"
```

---

## Self-Review Notes

**Spec coverage:**

| Spec section | Task(s) |
|--------------|---------|
| Goals / Non-goals | Implicit in scope of Tasks 1-9 |
| CLI surface | Task 8 |
| Module + data shape | Task 1 (skeleton), Tasks 2-5 (compute_diff fills) |
| Sync-on-the-fly logic | Task 8 (`_needs_sync` + `_dispatch_diff`) |
| Mismatch warnings | Task 5 |
| Text format | Task 6 |
| JSON format | Task 1 (impl) + Task 7 (round-trip test) |
| Error handling | Task 8 (CLI handler catches LookupError, FileNotFoundError, OSError) |
| Testing | Tasks 1-8 (each adds tests; checklist items 1-11 all covered) |
| Documentation | Task 9 |
| Risks | Auto-sync delay & posts_in_both unused-in-text both noted in spec, no task needed |

**Type/method consistency check:**

- `RunSummary` fields (`run_dir, mode, scope, project_name, scraped_at_utc, post_count, comment_count`) defined in Task 1, queried in Task 1's `_summary_for`, asserted in Tasks 5/8.
- `DiffResult` fields (`a, b, posts_only_in_a, posts_only_in_b, posts_in_both, comments_only_in_a, comments_only_in_b, comments_in_both, relevance_changes, warnings`) defined in Task 1, populated by Tasks 2-5, formatted by Tasks 6-7.
- `compute_diff(sink, run_a, run_b) -> DiffResult` signature stable across Tasks 1-8.
- `format_text(result) -> str` and `format_json(result) -> str` signatures stable.
- `relevance_changes` items use keys `post_id, a_decision, b_decision` — same in Task 4 (impl), Task 4 (test), Task 6 (text formatter), Task 7 (json round-trip).
- `_needs_sync` and `_dispatch_diff` defined together in Task 8.
