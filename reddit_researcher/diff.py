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


def format_text(result: DiffResult) -> str:
    return "=== Diff: A vs B ===\n(stub — populated in Task 7)\n"


def format_json(result: DiffResult) -> str:
    return json.dumps(asdict(result), default=str, ensure_ascii=True)
