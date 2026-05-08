# Time-series rollup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `reddit-researcher series <project>` — a per-project trend rollup written to `runs/_series/<project_name>/<timestamp>/series.{md,json}`. Closes the last open 0.2.0 roadmap item.

**Architecture:** New `reddit_researcher/series.py` module mirrors the shape of `reddit_researcher/diff.py`: pure read against the sink's read-only connection, dataclass result, separate text/json formatters. CLI subcommand auto-syncs stale runs (same pattern as `diff`), then writes outputs into a timestamped dir under `runs/_series/<project_name>/`. No new tables; queries use the existing `runs` / `posts` / `relevance_decisions` schema.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, optional `duckdb`, pytest, argparse. Follows the test conventions in `tests/test_diff.py` (`tmp_path` fixtures, `_make_synced_run` helper).

---

## File Structure

**Create:**
- `reddit_researcher/series.py` — `RunRow`, `SeriesResult` dataclasses; `compute_series`; `format_markdown`; `format_json`. Pure module, no I/O outside the sink connection.
- `tests/test_series.py` — unit tests for `compute_series` and formatters; CLI integration tests.

**Modify:**
- `reddit_researcher/cli.py` — register a new `series` subparser; add `_dispatch_series` handler; add `_sync_stale_for_project` helper.
- `reddit_researcher/__init__.py` — bump `__version__` to `"0.2.1-beta"`.
- `README.md` — new "Series rollups" subsection after "Comparing runs".
- `docs/architecture.md` — new "Series rollups" section after "Storage (optional DB sink)".
- `CHANGELOG.md` — new `0.2.1-beta` entry.
- `docs/roadmap.md` — tick the time-series checkbox with a `(0.2.1)` callout.

Each file has one clear responsibility:

- `series.py` does compute + format. No file I/O, no network, no CLI parsing.
- `cli.py` does argparse, sink construction, auto-sync, file writes.
- `tests/test_series.py` exercises both layers; CLI tests live in the same file (matches `test_diff.py`).

---

## Task 1: Bootstrap `series.py` with dataclasses and a stub `compute_series`

**Files:**
- Create: `reddit_researcher/series.py`
- Create: `tests/test_series.py`
- Test: `tests/test_series.py::test_compute_series_returns_seriesresult_for_one_run`

- [ ] **Step 1: Write the failing test**

Open `tests/test_series.py` and add:

```python
"""Tests for reddit_researcher.series."""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: F401

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import make_sink, sync_run
from reddit_researcher.series import RunRow, SeriesResult, compute_series
from reddit_researcher.storage import append_jsonl


def _post_row(post_id: str, subreddit: str = "AskReddit", search_term: str = "") -> dict:
    return {
        "id": post_id,
        "subreddit": subreddit,
        "search_term": search_term,
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


def test_compute_series_returns_seriesresult_for_one_run(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert isinstance(result, SeriesResult)
        assert result.project_name == "demo"
        assert len(result.runs) == 1
        assert isinstance(result.runs[0], RunRow)
        assert result.runs[0].post_count == 1
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_compute_series_returns_seriesresult_for_one_run -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_researcher.series'`.

- [ ] **Step 3: Create `reddit_researcher/series.py` with dataclasses and a minimal `compute_series`**

```python
"""Per-project time-series rollup.

Reads from the SQLite/DuckDB sink and produces a structured `SeriesResult`
plus Markdown and JSON formatters. Pure read; the CLI handler owns auto-sync
and file writes.

JSONL on disk remains canonical; this module is a derived view, like `diff.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .db import RunSink


@dataclass
class RunRow:
    run_dir: Path
    timestamp: str
    scraped_at_utc: str
    mode: str
    scope: str
    post_count: int
    comment_count: int
    relevant_count: int = 0
    new_post_ids: list[str] = field(default_factory=list)
    carried_post_ids: list[str] = field(default_factory=list)
    per_subreddit: dict[str, int] = field(default_factory=dict)
    per_search_term: dict[str, int] = field(default_factory=dict)


@dataclass
class SeriesResult:
    project_name: str
    runs: list[RunRow] = field(default_factory=list)
    always_present_post_ids: list[str] = field(default_factory=list)
    title_for: dict[str, str] = field(default_factory=dict)
    churn_top: list[tuple[str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compute_series(
    sink: RunSink, project_name: str, limit: int | None = None,
) -> SeriesResult:
    """Read all (or the most-recent N) runs for a project and build the rollup."""
    conn = sink.read_only_connect()
    try:
        rows = conn.execute(
            "SELECT run_dir, scraped_at_utc, mode, scope, post_count, comment_count "
            "FROM runs WHERE project_name = ? ORDER BY scraped_at_utc ASC",
            (project_name,),
        ).fetchall()
        if limit is not None and limit > 0 and len(rows) > limit:
            rows = rows[-limit:]
        result = SeriesResult(project_name=project_name)
        for run_dir_str, scraped_at_utc, mode, scope, post_count, comment_count in rows:
            run_dir = Path(run_dir_str)
            result.runs.append(
                RunRow(
                    run_dir=run_dir,
                    timestamp=run_dir.name,
                    scraped_at_utc=scraped_at_utc,
                    mode=mode,
                    scope=scope,
                    post_count=int(post_count),
                    comment_count=int(comment_count),
                )
            )
        return result
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_series.py::test_compute_series_returns_seriesresult_for_one_run -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): bootstrap series module with dataclasses and minimal compute"
```

---

## Task 2: Per-run `relevant_count`

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_compute_series_relevant_count`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_compute_series_relevant_count(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
                {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "off"},
                {"post_id": "p3", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
            ],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert result.runs[0].relevant_count == 2
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_compute_series_relevant_count -v`
Expected: FAIL — `relevant_count` is still `0`.

- [ ] **Step 3: Add the relevance count fill in `compute_series`**

In `reddit_researcher/series.py`, replace the `for ... in rows:` loop body with one that also fills `relevant_count`:

```python
        run_dir_strs = [r[0] for r in rows]
        relevant_counts: dict[str, int] = {rd: 0 for rd in run_dir_strs}
        if run_dir_strs:
            placeholders = ",".join(["?"] * len(run_dir_strs))
            for rd, cnt in conn.execute(
                f"SELECT run_dir, COUNT(*) FROM relevance_decisions "
                f"WHERE decision = 'include' AND run_dir IN ({placeholders}) "
                f"GROUP BY run_dir",
                run_dir_strs,
            ).fetchall():
                relevant_counts[rd] = int(cnt)

        result = SeriesResult(project_name=project_name)
        for run_dir_str, scraped_at_utc, mode, scope, post_count, comment_count in rows:
            run_dir = Path(run_dir_str)
            result.runs.append(
                RunRow(
                    run_dir=run_dir,
                    timestamp=run_dir.name,
                    scraped_at_utc=scraped_at_utc,
                    mode=mode,
                    scope=scope,
                    post_count=int(post_count),
                    comment_count=int(comment_count),
                    relevant_count=relevant_counts.get(run_dir_str, 0),
                )
            )
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): per-run relevant_count from relevance_decisions"
```

---

## Task 3: `new_post_ids`, `carried_post_ids`, and `title_for`

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_compute_series_new_and_carried_post_ids`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_compute_series_new_and_carried_post_ids(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260505-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p2"), _post_row("p3"), _post_row("p4")],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p3"), _post_row("p4"), _post_row("p5")],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        # Run 0 (first): new == all posts, carried == [].
        assert sorted(result.runs[0].new_post_ids) == ["p1", "p2", "p3"]
        assert result.runs[0].carried_post_ids == []
        # Run 1: new is what wasn't in run 0; carried is the intersection.
        assert sorted(result.runs[1].new_post_ids) == ["p4"]
        assert sorted(result.runs[1].carried_post_ids) == ["p2", "p3"]
        # Run 2: comparison is to the previous run only.
        assert sorted(result.runs[2].new_post_ids) == ["p5"]
        assert sorted(result.runs[2].carried_post_ids) == ["p3", "p4"]
        # title_for is populated for every post seen.
        assert result.title_for["p5"] == "Title p5"
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_compute_series_new_and_carried_post_ids -v`
Expected: FAIL — sets are not yet computed.

- [ ] **Step 3: Add per-run post fetch + new/carried diff in `compute_series`**

In `reddit_researcher/series.py`, after the `relevant_counts` block and before constructing `RunRow`s, add:

```python
        per_run_post_ids: dict[str, set[str]] = {}
        per_run_titles: dict[str, dict[str, str]] = {}
        for rd in run_dir_strs:
            id_set: set[str] = set()
            title_map: dict[str, str] = {}
            for post_id, title in conn.execute(
                "SELECT DISTINCT post_id, title FROM posts WHERE run_dir = ?",
                (rd,),
            ).fetchall():
                id_set.add(post_id)
                title_map[post_id] = title
            per_run_post_ids[rd] = id_set
            per_run_titles[rd] = title_map
```

Then change the `RunRow` construction loop to thread through `new`/`carried`/`title_for`:

```python
        result = SeriesResult(project_name=project_name)
        previous_ids: set[str] = set()
        title_for: dict[str, str] = {}
        for run_dir_str, scraped_at_utc, mode, scope, post_count, comment_count in rows:
            run_dir = Path(run_dir_str)
            current_ids = per_run_post_ids.get(run_dir_str, set())
            # First-run special case: every post is "new"; carried stays empty.
            if not result.runs:
                new_ids = sorted(current_ids)
                carried_ids: list[str] = []
            else:
                new_ids = sorted(current_ids - previous_ids)
                carried_ids = sorted(current_ids & previous_ids)
            # Latest title wins (chronological iteration).
            title_for.update(per_run_titles.get(run_dir_str, {}))
            result.runs.append(
                RunRow(
                    run_dir=run_dir,
                    timestamp=run_dir.name,
                    scraped_at_utc=scraped_at_utc,
                    mode=mode,
                    scope=scope,
                    post_count=int(post_count),
                    comment_count=int(comment_count),
                    relevant_count=relevant_counts.get(run_dir_str, 0),
                    new_post_ids=new_ids,
                    carried_post_ids=carried_ids,
                )
            )
            previous_ids = current_ids
        result.title_for = title_for
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): new_post_ids, carried_post_ids, and title_for per run"
```

---

## Task 4: `always_present_post_ids` and `churn_top`

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_compute_series_always_present_and_churn`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_compute_series_always_present_and_churn(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        # p1 in all 3 runs; p2 in 2 of 3; p3 in 1 of 3; p4 in 1 of 3.
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260505-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p4")],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        # Always-present is just p1.
        assert result.always_present_post_ids == ["p1"]
        # Churn: posts NOT in every run, sorted by descending run_count.
        # p2 -> 2, p3 -> 1, p4 -> 1.  Ties broken by post_id ascending for determinism.
        assert result.churn_top[0] == ("p2", 2)
        assert ("p3", 1) in result.churn_top
        assert ("p4", 1) in result.churn_top
        # p1 (always-present) is excluded from churn_top.
        assert all(post_id != "p1" for post_id, _ in result.churn_top)
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_compute_series_always_present_and_churn -v`
Expected: FAIL — both fields are still empty.

- [ ] **Step 3: Add the always-present + churn computation in `compute_series`**

In `reddit_researcher/series.py`, immediately before `return result` add:

```python
        # Aggregate post-id frequency across runs (using per_run_post_ids).
        if per_run_post_ids:
            total_runs = len(per_run_post_ids)
            frequency: dict[str, int] = {}
            for ids in per_run_post_ids.values():
                for post_id in ids:
                    frequency[post_id] = frequency.get(post_id, 0) + 1
            result.always_present_post_ids = sorted(
                pid for pid, count in frequency.items() if count == total_runs
            )
            churn = [
                (pid, count) for pid, count in frequency.items() if count < total_runs
            ]
            # Sort: descending by count, then ascending by post_id for determinism.
            churn.sort(key=lambda pair: (-pair[1], pair[0]))
            result.churn_top = churn[:10]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): always_present_post_ids and churn_top ranking"
```

---

## Task 5: Per-subreddit and per-search-term breakdowns

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_compute_series_per_subreddit_breakdown`, `::test_compute_series_per_search_term_breakdown`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series.py`:

```python
def test_compute_series_per_subreddit_breakdown(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="multi", ts="20260507-120000",
            posts=[
                _post_row("p1", subreddit="trees"),
                _post_row("p2", subreddit="trees"),
                _post_row("p3", subreddit="MOCannabis"),
            ],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert result.runs[0].per_subreddit == {"trees": 2, "MOCannabis": 1}
        # search-term map is empty for subreddit-mode rows.
        assert result.runs[0].per_search_term == {}
    finally:
        sink.close()


def test_compute_series_per_search_term_breakdown(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="search", ts="20260507-120000", mode="search",
            posts=[
                _post_row("p1", search_term="silksong"),
                _post_row("p2", search_term="silksong"),
                _post_row("p3", search_term="gta vi"),
            ],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert result.runs[0].per_search_term == {"silksong": 2, "gta vi": 1}
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series.py -v -k "breakdown"`
Expected: 2 FAILs — both `per_*` dicts are still empty.

- [ ] **Step 3: Replace the per-run post fetch with a richer query that also captures subreddit/term**

In `reddit_researcher/series.py`, replace the per-run post fetch loop body:

```python
        per_run_post_ids: dict[str, set[str]] = {}
        per_run_titles: dict[str, dict[str, str]] = {}
        per_run_sub_counts: dict[str, dict[str, int]] = {}
        per_run_term_counts: dict[str, dict[str, int]] = {}
        for rd in run_dir_strs:
            id_set: set[str] = set()
            title_map: dict[str, str] = {}
            sub_counts: dict[str, int] = {}
            term_counts: dict[str, int] = {}
            seen_pid: set[str] = set()  # avoid double-counting a post that appears
                                        # under multiple search_term rows in the sink.
            for post_id, title, subreddit, search_term in conn.execute(
                "SELECT post_id, title, subreddit, search_term FROM posts WHERE run_dir = ?",
                (rd,),
            ).fetchall():
                id_set.add(post_id)
                title_map[post_id] = title
                if post_id in seen_pid:
                    continue
                seen_pid.add(post_id)
                if subreddit:
                    sub_counts[subreddit] = sub_counts.get(subreddit, 0) + 1
                if search_term:
                    term_counts[search_term] = term_counts.get(search_term, 0) + 1
            per_run_post_ids[rd] = id_set
            per_run_titles[rd] = title_map
            per_run_sub_counts[rd] = sub_counts
            per_run_term_counts[rd] = term_counts
```

Then thread the maps into `RunRow`:

```python
            result.runs.append(
                RunRow(
                    run_dir=run_dir,
                    timestamp=run_dir.name,
                    scraped_at_utc=scraped_at_utc,
                    mode=mode,
                    scope=scope,
                    post_count=int(post_count),
                    comment_count=int(comment_count),
                    relevant_count=relevant_counts.get(run_dir_str, 0),
                    new_post_ids=new_ids,
                    carried_post_ids=carried_ids,
                    per_subreddit=per_run_sub_counts.get(run_dir_str, {}),
                    per_search_term=per_run_term_counts.get(run_dir_str, {}),
                )
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): per-subreddit and per-search-term breakdowns per run"
```

---

## Task 6: Mode/scope-change warnings

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_compute_series_warns_on_mode_change`, `::test_compute_series_warns_on_scope_change`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series.py`:

```python
def test_compute_series_warns_on_mode_change(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000", mode="subreddit",
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="all-reddit-search", ts="20260507-120000", mode="search",
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert any("mode change" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_series_warns_on_scope_change(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="trees", ts="20260506-120000", project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="MOCannabis", ts="20260507-120000", project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert any("scope change" in w for w in result.warnings)
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series.py -v -k "warns"`
Expected: 2 FAILs — `result.warnings` is still empty.

- [ ] **Step 3: Add warning detection in `compute_series`**

In `reddit_researcher/series.py`, after `result.churn_top = churn[:10]` (and before `return result`), add:

```python
        # Warnings: detect mode or scope changes between consecutive runs.
        for prev, curr in zip(result.runs, result.runs[1:], strict=False):
            if prev.mode != curr.mode:
                result.warnings.append(
                    f"mode change between {prev.timestamp} and {curr.timestamp}: "
                    f"{prev.mode} -> {curr.mode}"
                )
            if prev.scope != curr.scope:
                result.warnings.append(
                    f"scope change between {prev.timestamp} and {curr.timestamp}: "
                    f"{prev.scope} -> {curr.scope}"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): warnings for mode and scope changes between consecutive runs"
```

---

## Task 7: `--limit` truncation to most-recent N

**Files:**
- Modify: `reddit_researcher/series.py` (no change required — already implemented)
- Test: `tests/test_series.py::test_compute_series_limit_keeps_most_recent`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_compute_series_limit_keeps_most_recent(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        for i, ts in enumerate(
            [
                "20260501-120000",
                "20260502-120000",
                "20260503-120000",
                "20260504-120000",
                "20260505-120000",
            ]
        ):
            _make_synced_run(
                sink, tmp_path, scope="AskReddit", ts=ts,
                posts=[_post_row(f"p{i}")],
                project_name="demo",
            )
        result = compute_series(sink, project_name="demo", limit=3)
        assert len(result.runs) == 3
        # The 3 most recent timestamps.
        assert [r.timestamp for r in result.runs] == [
            "20260503-120000", "20260504-120000", "20260505-120000",
        ]
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it passes**

The Task 1 implementation already includes `limit` slicing. Run:

`pytest tests/test_series.py::test_compute_series_limit_keeps_most_recent -v`
Expected: PASS.

If it fails because something downstream of the slicing depends on `rows` rather than `result.runs`, audit `compute_series` and fix; the slicing must happen before `run_dir_strs` is built.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_series.py
git commit -m "test(series): --limit keeps the N most recent runs in chronological order"
```

---

## Task 8: `format_json` round-trip

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_format_json_round_trip`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_format_json_round_trip(tmp_path: Path) -> None:
    from reddit_researcher.series import format_json

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p1"), _post_row("p2")], project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p2"), _post_row("p3")], project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        payload = json.loads(format_json(result))
        for key in (
            "project_name", "runs", "always_present_post_ids",
            "title_for", "churn_top", "warnings",
        ):
            assert key in payload, f"missing key: {key}"
        assert payload["project_name"] == "demo"
        assert payload["always_present_post_ids"] == ["p2"]
        # Path serialized via default=str.
        assert isinstance(payload["runs"][0]["run_dir"], str)
        # Tuples become lists in JSON.
        assert payload["churn_top"] and isinstance(payload["churn_top"][0], list)
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_format_json_round_trip -v`
Expected: FAIL with `ImportError` for `format_json`.

- [ ] **Step 3: Implement `format_json` in `reddit_researcher/series.py`**

Append to `reddit_researcher/series.py`:

```python
def format_json(result: SeriesResult) -> str:
    """Serialize the SeriesResult as a single JSON object.

    `default=str` covers Path values; tuples in `churn_top` become lists,
    which is the standard JSON round-trip behavior.
    """
    return json.dumps(asdict(result), default=str, ensure_ascii=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_series.py -v`
Expected: 10 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): format_json"
```

---

## Task 9: `format_markdown` — header + run table

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_format_markdown_header_and_run_table`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_format_markdown_header_and_run_table(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p1"), _post_row("p2")], project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p2"), _post_row("p3")], project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        # Header
        assert "# Series: demo" in md
        assert "2 runs" in md
        # Run table
        assert "20260506-120000" in md
        assert "20260507-120000" in md
        assert "subreddit" in md.lower()  # mode column rendered
        assert "AskReddit" in md
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_format_markdown_header_and_run_table -v`
Expected: FAIL with `ImportError` for `format_markdown`.

- [ ] **Step 3: Implement `format_markdown` (header + run table) in `reddit_researcher/series.py`**

Append to `reddit_researcher/series.py`:

```python
_PERSISTENCE_CAP = 50
_CHURN_CAP = 10
_BREAKDOWN_ROW_CAP = 20
_TITLE_TRUNC = 80


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _format_text_table(headers: list[str], rows: list[list[str]]) -> str:
    """Plain-text aligned table — no external deps. Matches the diff module's vibe."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=False)))
    return "\n".join(lines)


def format_markdown(result: SeriesResult) -> str:
    """Render the SeriesResult as a human-readable Markdown report."""
    parts: list[str] = []

    # Header
    n = len(result.runs)
    if n == 0:
        return f"# Series: {result.project_name}\n\nno runs found.\n"
    first_ts = result.runs[0].scraped_at_utc
    last_ts = result.runs[-1].scraped_at_utc
    parts.append(f"# Series: {result.project_name}")
    parts.append(f"{n} runs from {first_ts} to {last_ts}")
    parts.append("")

    # Run table
    parts.append("## Runs")
    parts.append("")
    headers = ["run", "mode", "scope", "posts", "comments", "relevant", "new", "carried"]
    rows: list[list[str]] = []
    for i, r in enumerate(result.runs):
        rows.append([
            r.timestamp,
            r.mode,
            r.scope,
            str(r.post_count),
            str(r.comment_count),
            str(r.relevant_count),
            "-" if i == 0 else str(len(r.new_post_ids)),
            "-" if i == 0 else str(len(r.carried_post_ids)),
        ])
    parts.append(_format_text_table(headers, rows))
    parts.append("")

    return "\n".join(parts) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_series.py -v`
Expected: 11 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): format_markdown header and run table"
```

---

## Task 10: `format_markdown` — persistence and churn sections

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_format_markdown_persistence_and_churn`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_format_markdown_persistence_and_churn(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        # p1 in all 3, p2 in 2/3, p3 in 1/3.
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260505-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p1"), _post_row("p2")], project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")], project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        assert "## Persistence" in md
        # Always-present count + post id appear.
        assert "p1" in md
        assert "Title p1" in md
        assert "## Churn" in md
        # p2 is the most-frequent non-always post.
        assert "p2" in md
        assert "2/3" in md or "2 / 3" in md
    finally:
        sink.close()


def test_format_markdown_persistence_section_for_single_run(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")], project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        assert "## Persistence" in md
        assert "only one run" in md.lower()
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series.py -v -k "persistence_and_churn or single_run"`
Expected: 2 FAILs — sections aren't rendered yet.

- [ ] **Step 3: Append persistence + churn sections to `format_markdown`**

In `reddit_researcher/series.py`, before `return "\n".join(parts) + "\n"` add:

```python
    # Persistence
    parts.append("## Persistence")
    parts.append("")
    if n == 1:
        parts.append("(only one run; persistence not applicable)")
    else:
        always = result.always_present_post_ids
        parts.append(f"posts present in all {n} runs ({len(always)}):")
        if not always:
            parts.append("  (none)")
        else:
            shown = always[:_PERSISTENCE_CAP]
            for pid in shown:
                title = _truncate(result.title_for.get(pid, ""), _TITLE_TRUNC)
                parts.append(f"  {pid}  {title}")
            extra = len(always) - len(shown)
            if extra > 0:
                parts.append(f"  ... (+{extra} more)")
    parts.append("")

    # Churn
    parts.append("## Churn")
    parts.append("")
    if not result.churn_top:
        parts.append("(none — every post is either always-present or single-run)")
    else:
        parts.append(
            f"posts appearing in some-but-not-all runs (top {len(result.churn_top)} by frequency):"
        )
        for pid, count in result.churn_top:
            title = _truncate(result.title_for.get(pid, ""), _TITLE_TRUNC)
            parts.append(f"  {pid}  {count}/{n}  {title}")
    parts.append("")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 13 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): format_markdown persistence and churn sections"
```

---

## Task 11: `format_markdown` — subreddit/term breakdown matrix and warnings

**Files:**
- Modify: `reddit_researcher/series.py`
- Test: `tests/test_series.py::test_format_markdown_breakdown_matrix`, `::test_format_markdown_warnings_section`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series.py`:

```python
def test_format_markdown_breakdown_matrix(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="multi", ts="20260506-120000",
            posts=[
                _post_row("p1", subreddit="trees"),
                _post_row("p2", subreddit="MOCannabis"),
            ],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="multi", ts="20260507-120000",
            posts=[
                _post_row("p3", subreddit="trees"),
                _post_row("p4", subreddit="trees"),
                _post_row("p5", subreddit="MOCannabis"),
            ],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        assert "## Subreddit breakdown" in md or "## Subreddit / term breakdown" in md
        assert "trees" in md
        assert "MOCannabis" in md


def test_format_markdown_warnings_section(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="A", ts="20260506-120000", project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="B", ts="20260507-120000", project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        assert "## Warnings" in md
        assert "scope change" in md
    finally:
        sink.close()
```

Note: the first test is missing its `try/finally` — add it before saving:

```python
def test_format_markdown_breakdown_matrix(tmp_path: Path) -> None:
    from reddit_researcher.series import format_markdown

    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="multi", ts="20260506-120000",
            posts=[
                _post_row("p1", subreddit="trees"),
                _post_row("p2", subreddit="MOCannabis"),
            ],
            project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="multi", ts="20260507-120000",
            posts=[
                _post_row("p3", subreddit="trees"),
                _post_row("p4", subreddit="trees"),
                _post_row("p5", subreddit="MOCannabis"),
            ],
            project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        md = format_markdown(result)
        assert "## Subreddit breakdown" in md or "## Subreddit / term breakdown" in md
        assert "trees" in md
        assert "MOCannabis" in md
    finally:
        sink.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_series.py -v -k "breakdown_matrix or warnings_section"`
Expected: 2 FAILs.

- [ ] **Step 3: Append breakdown + warnings sections to `format_markdown`**

In `reddit_researcher/series.py`, before `return "\n".join(parts) + "\n"` add:

```python
    # Subreddit / term breakdown matrix
    has_subs = any(r.per_subreddit for r in result.runs)
    has_terms = any(r.per_search_term for r in result.runs)
    if has_subs or has_terms:
        if has_subs and not has_terms:
            heading, key = "## Subreddit breakdown", "per_subreddit"
        elif has_terms and not has_subs:
            heading, key = "## Search-term breakdown", "per_search_term"
        else:
            heading, key = "## Subreddit / term breakdown", "per_subreddit"
        parts.append(heading)
        parts.append("")
        # Pick rows: union of keys across runs, ranked by total count desc.
        totals: dict[str, int] = {}
        for r in result.runs:
            source = getattr(r, key)
            for k, v in source.items():
                totals[k] = totals.get(k, 0) + v
            if heading.endswith("breakdown") and key == "per_subreddit":
                # When showing "Subreddit / term breakdown", also fold in terms.
                if has_terms:
                    for k, v in r.per_search_term.items():
                        totals[k] = totals.get(k, 0) + v
        ranked = sorted(totals, key=lambda k: (-totals[k], k))[:_BREAKDOWN_ROW_CAP]
        headers = ["key"] + [r.timestamp for r in result.runs]
        rows = []
        for label in ranked:
            row = [label]
            for r in result.runs:
                count = r.per_subreddit.get(label, 0) + r.per_search_term.get(label, 0)
                row.append(str(count))
            rows.append(row)
        parts.append(_format_text_table(headers, rows))
        parts.append("")

    # Warnings
    if result.warnings:
        parts.append("## Warnings")
        parts.append("")
        for w in result.warnings:
            parts.append(f"- {w}")
        parts.append("")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 15 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/series.py tests/test_series.py
git commit -m "feat(series): format_markdown subreddit/term breakdown and warnings sections"
```

---

## Task 12: Register the `series` CLI subparser

**Files:**
- Modify: `reddit_researcher/cli.py`
- Test: `tests/test_series.py::test_cli_series_help_does_not_crash`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_cli_series_help_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    from reddit_researcher.cli import main as cli_main

    rc = cli_main(["series", "--help"])
    # argparse `--help` exits with 0.
    assert rc == 0
    out = capsys.readouterr().out
    assert "series" in out.lower()
    assert "--limit" in out
    assert "--format" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_cli_series_help_does_not_crash -v`
Expected: FAIL — `series` is not a known command.

- [ ] **Step 3: Add the subparser in `build_parser`**

In `reddit_researcher/cli.py`, after the `diff_parser` block (right before `return parser`), add:

```python
    series_parser = subparsers.add_parser(
        "series",
        help="Generate a per-project trend rollup across runs.",
    )
    series_parser.add_argument(
        "project",
        help="Path to project.toml or its directory.",
    )
    series_parser.add_argument(
        "--output-root", default=None,
        help="Override where _series/ lives. Defaults to the project's output_root or ./runs.",
    )
    series_parser.add_argument(
        "--limit", type=int, default=None,
        help="Only include the most recent N runs.",
    )
    series_parser.add_argument(
        "--format", default="md", choices=["md", "json", "both"],
        help="Output format(s). 'both' writes series.md and series.json.",
    )
```

Also dispatch it in `_dispatch` — add this branch immediately before the trailing `parser.error(...)`:

```python
    if args.command == "series":
        return _dispatch_series(args, parser)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_series.py::test_cli_series_help_does_not_crash -v`
Expected: PASS. `--help` is handled by argparse before `_dispatch` runs, so the not-yet-defined `_dispatch_series` reference is fine — Python resolves it lazily inside the `if args.command == "series":` branch and that branch never executes for `--help`.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/cli.py tests/test_series.py
git commit -m "feat(cli): register series subparser (no dispatch yet)"
```

---

## Task 13: Series CLI dispatcher with auto-sync

**Files:**
- Modify: `reddit_researcher/cli.py`
- Test: `tests/test_series.py::test_cli_series_writes_md_and_json`, `::test_cli_series_auto_syncs_unsynced_run`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series.py`:

```python
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
    tmp_path: Path, *, scope: str, ts: str, posts: list[dict],
    project_name: str | None = "proj",
) -> Path:
    """Write a run dir to disk WITHOUT syncing."""
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": [scope],
        "scraped_at_utc": f"2026-05-07T{ts[-6:-4]}:00:00+00:00",
        "post_count": len(posts),
        "comment_count": 0,
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    return run_dir


def test_cli_series_auto_syncs_unsynced_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from reddit_researcher.cli import main as cli_main

    project_dir = _write_project(tmp_path)
    # Project name from project.toml is the directory name -> "proj".
    _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260506-120000",
        posts=[_post_row("p1"), _post_row("p2")], project_name="proj",
    )
    _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p2"), _post_row("p3")], project_name="proj",
    )
    rc = cli_main([
        "series", str(project_dir), "--output-root", str(tmp_path / "runs"),
        "--format", "both",
    ])
    assert rc == 0
    series_root = tmp_path / "runs" / "_series" / "proj"
    assert series_root.exists()
    written = list(series_root.iterdir())
    assert len(written) == 1, f"expected one timestamped dir, got {written}"
    md = written[0] / "series.md"
    js = written[0] / "series.json"
    assert md.exists()
    assert js.exists()
    text = md.read_text(encoding="utf-8")
    assert "Series: proj" in text
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["project_name"] == "proj"
    assert sorted([r["timestamp"] for r in payload["runs"]]) == [
        "20260506-120000", "20260507-120000",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_series.py::test_cli_series_auto_syncs_unsynced_run -v`
Expected: FAIL — `_dispatch_series` is not implemented or `series` command isn't dispatched.

- [ ] **Step 3: Implement `_dispatch_series` and `_sync_stale_for_project`**

In `reddit_researcher/cli.py`, after `_dispatch_diff` add:

```python
def _dispatch_series(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .db import make_sink, sync_run
    from .series import compute_series, format_json, format_markdown
    from .storage import timestamp_slug

    project_path = find_project_config(Path(args.project))
    load_dotenvs_for(project_dir=project_path.parent, repo_root=REPO_ROOT)
    project = load_project(project_path)

    output_root = (
        Path(args.output_root) if args.output_root
        else (project.output_root or DEFAULT_OUTPUT_ROOT)
    )

    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        synced = _sync_stale_for_project(sink, sync_run, project.name, output_root)
        result = compute_series(sink, project_name=project.name, limit=args.limit)
    finally:
        sink.close()

    if not result.runs:
        print(
            f"error: no runs found for project '{project.name}'; run it at least once "
            "before generating a series report.",
            file=sys.stderr,
        )
        return 2

    out_dir = output_root / "_series" / project.name / timestamp_slug()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.format in ("md", "both"):
        (out_dir / "series.md").write_text(format_markdown(result), encoding="utf-8")
    if args.format in ("json", "both"):
        (out_dir / "series.json").write_text(format_json(result), encoding="utf-8")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(
        f"series report: {len(result.runs)} runs, "
        f"{len(result.always_present_post_ids)} always-present, "
        f"synced {synced} new run(s); written to {out_dir}"
    )
    return 0


def _sync_stale_for_project(sink, sync_run, project_name: str, output_root: Path) -> int:
    """Sync any run dir under `output_root` whose project_name matches and is missing-or-stale.

    Returns the count of runs synced. Skips dirs without a manifest.json or
    whose manifest doesn't match the project name. Cheap to call before any
    series query — the same pattern `diff` uses, generalized to one project.
    """
    if not output_root.exists():
        return 0
    synced = 0
    for manifest_path in output_root.rglob("manifest.json"):
        run_dir = manifest_path.parent
        # Skip _series/ artifacts and anything else that isn't a real run dir.
        if any(part == "_series" for part in run_dir.parts):
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("project_name") != project_name:
            continue
        if _needs_sync(sink, run_dir):
            try:
                sync_run(sink, run_dir)
                synced += 1
            except (FileNotFoundError, OSError):
                continue
    return synced
```

Add the missing `import json` at the top of `cli.py` if it isn't already there:

```python
import json
```

(It should already be present via `_needs_sync`'s local import — make sure the top-level import exists; if not, add it next to `import sys`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v`
Expected: 17 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add reddit_researcher/cli.py tests/test_series.py
git commit -m "feat(cli): series dispatcher with auto-sync; writes md+json into _series/"
```

---

## Task 14: CLI handles `--format md` and `--format json` distinctly

**Files:**
- Test: `tests/test_series.py::test_cli_series_format_md_only`, `::test_cli_series_format_json_only`
- (`reddit_researcher/cli.py` already supports the branching; this task just locks it in.)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_series.py`:

```python
def test_cli_series_format_md_only(tmp_path: Path) -> None:
    from reddit_researcher.cli import main as cli_main

    project_dir = _write_project(tmp_path)
    _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")], project_name="proj",
    )
    rc = cli_main([
        "series", str(project_dir), "--output-root", str(tmp_path / "runs"),
        "--format", "md",
    ])
    assert rc == 0
    out_dir = list((tmp_path / "runs" / "_series" / "proj").iterdir())[0]
    assert (out_dir / "series.md").exists()
    assert not (out_dir / "series.json").exists()


def test_cli_series_format_json_only(tmp_path: Path) -> None:
    from reddit_researcher.cli import main as cli_main

    project_dir = _write_project(tmp_path)
    _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")], project_name="proj",
    )
    rc = cli_main([
        "series", str(project_dir), "--output-root", str(tmp_path / "runs"),
        "--format", "json",
    ])
    assert rc == 0
    out_dir = list((tmp_path / "runs" / "_series" / "proj").iterdir())[0]
    assert (out_dir / "series.json").exists()
    assert not (out_dir / "series.md").exists()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_series.py -v -k "format_md_only or format_json_only"`
Expected: PASS — Task 13's `_dispatch_series` already branches on `args.format`.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_series.py
git commit -m "test(cli): --format md and --format json each write only their respective file"
```

---

## Task 15: CLI returns exit code 2 for projects with zero runs

**Files:**
- Test: `tests/test_series.py::test_cli_series_zero_runs_exits_2`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_cli_series_zero_runs_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from reddit_researcher.cli import main as cli_main

    project_dir = _write_project(tmp_path)
    # No run dirs at all.
    rc = cli_main([
        "series", str(project_dir), "--output-root", str(tmp_path / "runs"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no runs found" in err.lower()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_series.py::test_cli_series_zero_runs_exits_2 -v`
Expected: PASS — Task 13's dispatcher already handles the empty case.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_series.py
git commit -m "test(cli): series exits 2 with a clear message when no runs match the project"
```

---

## Task 16: DuckDB engine works for `compute_series`

**Files:**
- Test: `tests/test_series.py::test_compute_series_works_on_duckdb_engine`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_series.py`:

```python
def test_compute_series_works_on_duckdb_engine(tmp_path: Path) -> None:
    """Regression: ensure compute_series doesn't depend on sqlite-only cursor semantics."""
    pytest.importorskip("duckdb")
    storage = StorageConfig(engine="duckdb", db_path=tmp_path / "r.duckdb")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260506-120000",
            posts=[_post_row("p1"), _post_row("p2")], project_name="demo",
        )
        _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p2")], project_name="demo",
        )
        result = compute_series(sink, project_name="demo")
        assert result.always_present_post_ids == ["p2"]
    finally:
        sink.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_series.py::test_compute_series_works_on_duckdb_engine -v`
Expected: PASS if `duckdb` is installed; SKIP otherwise.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_series.py
git commit -m "test(series): regression test for compute_series on the DuckDB engine"
```

---

## Task 17: Bump version, README docs, architecture docs

**Files:**
- Modify: `reddit_researcher/__init__.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Bump `__version__`**

In `reddit_researcher/__init__.py`, change:

```python
__version__ = "0.2.0-beta"
```

to:

```python
__version__ = "0.2.1-beta"
```

- [ ] **Step 2: Add the README "Series rollups" subsection**

In `README.md`, after the "Comparing runs" subsection (which ends with the `--format json` paragraph), insert:

````markdown
### Series rollups

`reddit-researcher series <project>` produces a per-project trend report
across every run of that project, written to a timestamped folder under
`runs/_series/<project_name>/`.

```bash
reddit-researcher series projects/missouri-cannabis
```

Output shape:

```text
runs/_series/missouri-cannabis/<timestamp>/
  series.md       # human-readable report
  series.json     # raw structured data (with --format=json or --format=both)
```

The report includes one row per run (post/comment counts, relevance
breakdown, new vs. carried posts), an "always-present" set of post IDs
that appeared in every run, churn for posts in some-but-not-all runs,
and a per-subreddit (or per-search-term) count matrix. No LLM call —
pure stats from the sink.

Use `--limit N` to only include the most recent N runs, or
`--format json` for machine-readable output.
````

- [ ] **Step 3: Add the architecture.md "Series rollups" section**

In `docs/architecture.md`, immediately before the `## Corpus formatters` heading, insert:

```markdown
## Series rollups

`reddit_researcher/series.py` produces a per-project trend report from the
sink. Like the `diff` module, it uses only the read-only connection
(`RunSink.read_only_connect()`) — JSONL on disk remains canonical.

- **Key:** `runs.project_name`. All runs of one project are joined on this
  column. If the user renames a project mid-series, pre-rename runs no
  longer match — documented as a known limitation.
- **Queries:** one ordered fetch from `runs`, one aggregate from
  `relevance_decisions`, one fetch-per-run from `posts`. Pure Python set
  arithmetic for new/carried/always-present.
- **Auto-sync:** the CLI walks the project's `output_root`, finds run
  dirs whose manifest's `project_name` matches and that are missing or
  stale in the sink, and syncs them before computing.
- **Output:** `runs/_series/<project_name>/<timestamp>/series.{md,json}`.
  `_series/` is collision-free with subreddit-mode and search-mode scope
  dirs because Reddit subreddit names cannot start with `_`.
```

- [ ] **Step 4: Add the CHANGELOG entry**

In `CHANGELOG.md`, immediately after the existing top-level frontmatter and before the `## [0.2.0-beta]` heading, insert:

```markdown
## [0.2.1-beta] — 2026-05-07

Closes the last open item in the `0.2.0` milestone — time-series mode.

### Added
- **`reddit-researcher series <project>`** — per-project trend rollup
  across every run of that project. Writes `series.md` and/or `series.json`
  into `runs/_series/<project_name>/<timestamp>/`. Pure stats (no LLM
  call): per-run counts and relevance breakdown, posts present in every
  run, churn for partial-presence posts, and a per-subreddit/per-term
  count matrix. Auto-syncs missing or stale runs into the sink before
  computing.
  - Flags: `--limit N` (most-recent N runs), `--format md|json|both`,
    `--output-root <path>`.

### Internal
- New `reddit_researcher/series.py` module mirrors the shape of `diff.py`:
  pure read against the sink, dataclass result, separate text/json formatters.
- New `tests/test_series.py` covers the compute pipeline (per-run stats,
  persistence/churn, breakdowns, warnings) plus the CLI handler
  (auto-sync, format selection, exit codes). DuckDB regression test
  matches the pattern in `test_diff.py`.

```

- [ ] **Step 5: Tick the roadmap checkbox**

In `docs/roadmap.md`, change:

```markdown
- [ ] Time-series mode: re-run a project on a schedule and aggregate results across timestamps.
```

to:

```markdown
- [x] Time-series mode: re-run a project on a schedule and aggregate results across timestamps. *(0.2.1)*
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: all tests PASS, including the existing 0.2.0 tests. Coverage gate (85%) still satisfied.

- [ ] **Step 7: Commit**

```powershell
git add reddit_researcher/__init__.py README.md docs/architecture.md CHANGELOG.md docs/roadmap.md
git commit -m "docs: 0.2.1-beta — series rollup; README, architecture, CHANGELOG, roadmap"
```

---

## Self-review notes

**Spec coverage check:**

- CLI surface (Task 12, 13, 14) — covers `<project>`, `--output-root`, `--limit`, `--format md|json|both`.
- Output layout (Task 13) — `runs/_series/<project_name>/<timestamp>/series.{md,json}` via `timestamp_slug`.
- Report contents (Tasks 9–11) — header, run table, persistence, churn, breakdown matrix, warnings.
- Architecture: `series.py` mirrors `diff.py` (Tasks 1–11), CLI handler with auto-sync (Task 13).
- Edge cases:
  - Zero runs → exit 2 (Task 15).
  - Single run → persistence section says "only one run" (Task 10).
  - Mode-change warning (Task 6).
  - Scope-change warning (Task 6, Task 11 verifies it surfaces in markdown).
  - `_series/` doesn't collide with subreddit names (`_sync_stale_for_project` skips paths containing `_series`).
  - `--limit N` truncation (Task 7).
- Testing: covers all 11 numbered items in the spec's testing section. DuckDB regression in Task 16.
- Documentation: README + architecture + CHANGELOG + roadmap (Task 17).
- Version bump: `0.2.1-beta` (Task 17).

**Type / signature consistency:** `compute_series(sink, project_name, limit=None)` is defined in Task 1 and used as such in every later task. `format_markdown(result)` and `format_json(result)` are defined in Tasks 9–11 and 8 respectively, used in Task 13 with the same signatures.

**Placeholders:** None. Every step has the actual code or command needed.
