"""Read-only views over projects and runs.

These functions back the `list` and `review` CLI subcommands. They are pure:
input is a path, output is a string. No mutation, no Ollama calls, no Reddit
calls — they exist so users can answer "what's here?" and "how did that run go?"
without spinning up the pipeline.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .config import find_project_config, load_project
from .manifest import MANIFEST_SCHEMA_VERSION, normalize_manifest, read_schema_version


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def _format_table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return "  (none)\n"
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render(values: list[str]) -> str:
        return "  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    lines = [render(headers), render(["-" * width for width in widths])]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines) + "\n"


def list_projects(projects_dir: Path) -> str:
    """Render a table of project folders found under `projects_dir`."""
    if not projects_dir.is_dir():
        return f"Projects ({projects_dir}):\n  (directory does not exist)\n"

    rows: list[list[str]] = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        config_path = entry / "project.toml"
        if not config_path.is_file():
            continue
        try:
            project = load_project(config_path)
        except Exception as exc:  # noqa: BLE001 - surface bad configs to the user
            rows.append([entry.name, "ERROR", str(exc)[:60], ""])
            continue
        if project.scrape.mode == "subreddit":
            subs = project.scrape.subreddits
            scope = f"r/{subs[0]}" if len(subs) == 1 else f"{len(subs)} subs: " + ", ".join(f"r/{s}" for s in subs)
        else:
            scope = "search"
            if project.scrape.terms_file:
                scope += f" ({project.scrape.terms_file.name})"
        rows.append([entry.name, project.scrape.mode, _truncate(scope, 32), project.analyze.model])

    table = _format_table(rows, ["project", "mode", "scope", "model"])
    return f"Projects ({projects_dir}):\n{table}"


def list_runs(runs_dir: Path, *, limit: int = 20) -> str:
    """Render a table of recent run folders under `runs_dir`."""
    if not runs_dir.is_dir():
        return f"Recent runs ({runs_dir}):\n  (directory does not exist)\n"

    candidates: list[tuple[float, Path, dict]] = []
    for scope_dir in runs_dir.iterdir():
        if not scope_dir.is_dir():
            continue
        for run_dir in scope_dir.iterdir():
            if not run_dir.is_dir():
                continue
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                manifest = {"status": "broken-manifest"}
            mtime = manifest_path.stat().st_mtime
            candidates.append((mtime, run_dir, manifest))

    candidates.sort(key=lambda item: item[0], reverse=True)
    candidates = candidates[:limit]

    rows: list[list[str]] = []
    for _, run_dir, manifest in candidates:
        rel = run_dir.relative_to(runs_dir).as_posix()
        mode = manifest.get("mode") or "?"
        status = manifest.get("status") or "complete"
        posts = str(manifest.get("post_count", "?"))
        comments = str(manifest.get("comment_count", "?"))
        rows.append([rel, mode, status, posts, comments])

    table = _format_table(rows, ["run", "mode", "status", "posts", "comments"])
    return f"Recent runs ({runs_dir}, newest first):\n{table}"


def summarize_run(run_dir: Path) -> str:
    """Produce a one-screen summary of a completed (or in-progress) run."""
    if not run_dir.is_dir():
        return f"Run not found: {run_dir}\n"
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return f"Run has no manifest.json: {run_dir}\n"

    try:
        manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return f"Manifest is unreadable ({manifest_path}): {exc}\n"

    lines: list[str] = []
    schema_version = read_schema_version(manifest)
    schema_note = (
        f" (schema v{schema_version}; tool writes v{MANIFEST_SCHEMA_VERSION})"
        if schema_version != MANIFEST_SCHEMA_VERSION
        else ""
    )
    lines.append(f"Run: {run_dir}{schema_note}")
    mode = manifest.get("mode", "unknown")
    status = manifest.get("status", "complete")
    if mode == "search":
        terms = manifest.get("search_terms") or []
        subs = manifest.get("subreddits") or []
        scope = f"search ({len(terms)} terms"
        if subs:
            scope += f", {len(subs)} subs"
        scope += ")"
    else:
        subs = manifest.get("subreddits") or ([manifest["subreddit"]] if manifest.get("subreddit") else [])
        if not subs:
            scope = "r/?"
        elif len(subs) == 1:
            scope = f"r/{subs[0]}"
        else:
            scope = f"{len(subs)} subs (" + ", ".join(f"r/{s}" for s in subs) + ")"
    lines.append(f"Mode:    {mode}    scope: {scope}    status: {status}")

    sort = manifest.get("sort", "?")
    time_filter = manifest.get("time_filter", "?")
    post_limit = manifest.get("post_limit_per_term", manifest.get("post_limit", "?"))
    comment_limit = manifest.get("comment_limit", "?")
    lines.append(
        f"Scrape:  sort={sort} time_filter={time_filter} "
        f"post_limit={post_limit} comment_limit={comment_limit}"
    )

    posts = manifest.get("post_count", 0)
    comments = manifest.get("comment_count", 0)
    lines.append(f"Counts:  {posts} posts, {comments} comments")

    review_path = run_dir / "review" / "relevance_review.jsonl"
    if review_path.is_file() and review_path.stat().st_size > 0:
        decisions: Counter[str] = Counter()
        with review_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                decisions[str(row.get("decision", "?"))] += 1
        breakdown = ", ".join(f"{count} {label}" for label, count in decisions.most_common())
        if breakdown:
            lines.append(f"Review:  {breakdown}")

    search_errors = manifest.get("search_fetch_error_count", 0)
    comment_errors = manifest.get("comment_fetch_error_count", 0)
    if search_errors or comment_errors:
        lines.append(f"Errors:  {search_errors} search, {comment_errors} comment")

    analysis = manifest.get("analysis")
    if isinstance(analysis, dict):
        chunk_count = analysis.get("chunk_count", 0)
        total_chunks = analysis.get("total_chunk_count", chunk_count)
        model = analysis.get("model", "?")
        when = analysis.get("analyzed_at_utc", "?")
        lines.append(f"Analyze: model={model} chunks={chunk_count}/{total_chunks} at {when}")

    final_path = run_dir / "analysis" / "final.md"
    if final_path.is_file():
        size = final_path.stat().st_size
        lines.append(f"Report:  {final_path} ({size} bytes)")
    else:
        lines.append("Report:  (not yet generated)")

    return "\n".join(lines) + "\n"


def find_default_projects_dir(start: Path) -> Path:
    """Return the conventional `projects/` directory next to the repo root."""
    return start / "projects"


def find_default_runs_dir(start: Path) -> Path:
    """Return the conventional `runs/` directory next to the repo root."""
    return start / "runs"


# Reused by tests and the CLI for repository-relative defaults.
__all__ = [
    "find_default_projects_dir",
    "find_default_runs_dir",
    "find_project_config",
    "list_projects",
    "list_runs",
    "summarize_run",
]
