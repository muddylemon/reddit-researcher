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

        result = SeriesResult(project_name=project_name)
        previous_ids: set[str] = set()
        title_for: dict[str, str] = {}
        for run_dir_str, scraped_at_utc, mode, scope, post_count, comment_count in rows:
            run_dir = Path(run_dir_str)
            current_ids = per_run_post_ids.get(run_dir_str, set())
            if not result.runs:
                new_ids = sorted(current_ids)
                carried_ids: list[str] = []
            else:
                new_ids = sorted(current_ids - previous_ids)
                carried_ids = sorted(current_ids & previous_ids)
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
    finally:
        conn.close()
