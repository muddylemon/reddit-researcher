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
                    per_subreddit=per_run_sub_counts.get(run_dir_str, {}),
                    per_search_term=per_run_term_counts.get(run_dir_str, {}),
                )
            )
            previous_ids = current_ids
        result.title_for = title_for

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
            churn.sort(key=lambda pair: (-pair[1], pair[0]))
            result.churn_top = churn[:10]

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

        return result
    finally:
        conn.close()


def format_json(result: SeriesResult) -> str:
    """Serialize the SeriesResult as a single JSON object.

    `default=str` covers Path values; tuples in `churn_top` become lists,
    which is the standard JSON round-trip behavior.
    """
    return json.dumps(asdict(result), default=str, ensure_ascii=True)


_PERSISTENCE_CAP = 50
_CHURN_CAP = 10
_BREAKDOWN_ROW_CAP = 20
_TITLE_TRUNC = 80


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 3] + "..."


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

    return "\n".join(parts) + "\n"
