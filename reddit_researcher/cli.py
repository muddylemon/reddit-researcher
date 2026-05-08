from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import (
    AnalyzeConfig,
    ProjectConfig,
    ProjectConfigError,
    ScrapeConfig,
    find_project_config,
    load_project,
)
from .env import load_dotenvs_for
from .pipeline import (
    extract_from_run,
    run_project,
    scrape_search_terms,
    scrape_subreddit,
)
from .prompt_templates import BUILTIN_TEMPLATES, list_templates
from .relevance import RelevanceConfig
from .templates import scaffold_project
from .views import (
    list_projects,
    list_runs,
    summarize_run,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "runs"
DEFAULT_PROJECTS_ROOT = REPO_ROOT / "projects"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reddit-researcher",
        description=(
            "Scrape Reddit and analyze it with a local Ollama model. "
            "Run a saved project end-to-end, or use the lower-level subcommands."
        ),
    )
    parser.add_argument("--version", action="version", version=f"reddit-researcher {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Load a project.toml and run scrape+extract end-to-end.",
    )
    run_parser.add_argument("project", help="Path to project.toml or a directory containing one.")
    run_parser.add_argument("--output-root", default=None, help="Override the project's runs/ directory.")
    run_parser.add_argument(
        "--run-dir", default=None, help="Existing run directory to resume into (search mode)."
    )
    run_parser.add_argument("--skip-extract", action="store_true", help="Scrape only; do not call Ollama.")
    run_parser.add_argument("--start-term-index", type=int, default=1)
    run_parser.add_argument("--term-limit", type=int, default=None)
    _add_analyze_overrides(run_parser)

    scrape_parser = subparsers.add_parser(
        "scrape",
        help="Scrape a single subreddit's listing into a run folder.",
    )
    scrape_parser.add_argument(
        "subreddit",
        nargs="+",
        help="One or more subreddit names without the r/ prefix.",
    )
    _add_scrape_arguments(scrape_parser)

    search_parser = subparsers.add_parser(
        "search",
        help="Search Reddit for terms from a file and save matching posts/comments.",
    )
    search_parser.add_argument("--terms-file", required=True)
    search_parser.add_argument("--subreddits-file")
    search_parser.add_argument("--run-dir")
    search_parser.add_argument("--no-exact-phrase", action="store_true")
    search_parser.add_argument("--start-term-index", type=int, default=1)
    search_parser.add_argument("--term-limit", type=int, default=None)
    _add_scrape_arguments(search_parser)

    extract_parser = subparsers.add_parser(
        "extract",
        help="Run Ollama analysis over an existing run folder.",
    )
    extract_parser.add_argument("run_dir", help="Path to an existing run directory.")
    _add_analyze_overrides(extract_parser, require_prompt=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a new project folder under projects/.",
    )
    init_parser.add_argument(
        "name",
        nargs="?",
        help="Project folder name (a slug under projects/). Omitted with --list-templates.",
    )
    init_parser.add_argument(
        "--mode",
        choices=["subreddit", "search"],
        default="subreddit",
        help="Project mode. 'subreddit' targets one community; 'search' targets terms.",
    )
    init_parser.add_argument(
        "--subreddit",
        action="append",
        default=[],
        help="Subreddit name (required for --mode subreddit). Repeatable for multi-sub scaffolds.",
    )
    init_parser.add_argument(
        "--term",
        action="append",
        default=[],
        help="Add a starter search term (repeatable). Search mode only.",
    )
    init_parser.add_argument(
        "--allowlist-subreddit",
        action="append",
        default=[],
        help="Add a starter subreddit to the search allowlist (repeatable).",
    )
    init_parser.add_argument("--model", default=None, help="Default Ollama model tag.")
    init_parser.add_argument("--description", default="", help="One-line project description.")
    init_parser.add_argument(
        "--template",
        choices=sorted(BUILTIN_TEMPLATES.keys()),
        default=None,
        help="Built-in prompt template to seed prompt.md with. Defaults to one matching --mode.",
    )
    init_parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available built-in prompt templates and exit.",
    )
    init_parser.add_argument(
        "--projects-dir",
        default=str(DEFAULT_PROJECTS_ROOT),
        help="Where the new project folder is created (default: projects/).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the target folder.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List available projects and recent runs.",
    )
    list_parser.add_argument(
        "--projects-dir",
        default=str(DEFAULT_PROJECTS_ROOT),
        help="Override the projects/ directory.",
    )
    list_parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Override the runs/ directory.",
    )
    list_parser.add_argument(
        "--runs-limit",
        type=int,
        default=20,
        help="Max number of recent runs to show.",
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Print a one-screen summary of an existing run folder.",
    )
    review_parser.add_argument("run_dir", help="Path to a run directory.")

    db_parser = subparsers.add_parser(
        "db",
        help="Query and sync the project's research DB.",
    )
    db_subs = db_parser.add_subparsers(dest="db_command", required=True)

    db_sync_parser = db_subs.add_parser("sync", help="Sync run dirs into the DB.")
    db_sync_parser.add_argument("run_dirs", nargs="*", help="One or more run directories.")
    db_sync_parser.add_argument("--project", default=None, help="Path to project.toml or its directory.")
    db_sync_parser.add_argument("--all", action="store_true", help="Sync every run under output_root.")
    db_sync_parser.add_argument(
        "--output-root", default=None,
        help="Override output_root when using --all. Defaults to project's output_root or ./runs.",
    )
    db_sync_parser.add_argument(
        "--rebuild", action="store_true",
        help="Drop and recreate all tables before syncing (recovers from schema mismatch).",
    )

    db_status_parser = db_subs.add_parser("status", help="Show DB engine, path, schema, row counts.")
    db_status_parser.add_argument("--project", default=None)

    db_query_parser = db_subs.add_parser("query", help="Run a read-only SQL query against the DB.")
    db_query_parser.add_argument("sql", help="SQL statement (read-only connection).")
    db_query_parser.add_argument("--project", default=None)
    db_query_parser.add_argument("--format", default="table", choices=["table", "json", "csv"])

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

    return parser


def _add_scrape_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sort", default="top", choices=["hot", "new", "top", "rising"])
    parser.add_argument(
        "--time-filter",
        default="month",
        choices=["hour", "day", "week", "month", "year", "all"],
    )
    parser.add_argument("--post-limit", type=int, default=25)
    parser.add_argument("--comment-limit", type=int, default=10)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument(
        "--user-agent",
        default="desktop:reddit-researcher:0.0.1 (by /u/local-user)",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))


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


def _scrape_config_from_args(args: argparse.Namespace) -> ScrapeConfig:
    return ScrapeConfig(
        sort=args.sort,
        time_filter=args.time_filter,
        post_limit=args.post_limit,
        comment_limit=args.comment_limit,
        pause_seconds=args.pause_seconds,
        max_retries=args.max_retries,
        user_agent=args.user_agent,
        exact_phrase=not getattr(args, "no_exact_phrase", False),
    )


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


def _resolve_output_root(project: ProjectConfig, override: str | None) -> Path:
    if override:
        return Path(override)
    if project.output_root is not None:
        return project.output_root
    return DEFAULT_OUTPUT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    # Load .env files into os.environ as early as possible so config defaults
    # (which read OLLAMA_URL etc.) see them. The project's own .env, if any,
    # is loaded again with override=True once we know the project dir.
    load_dotenvs_for(project_dir=None, repo_root=REPO_ROOT)

    try:
        return _dispatch(args, parser)
    except ProjectConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        # parser.error() raises SystemExit; surface its code as the return.
        return int(exc.code) if exc.code is not None else 0


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "run":
        config_path = find_project_config(Path(args.project))
        load_dotenvs_for(project_dir=config_path.parent, repo_root=REPO_ROOT)
        project = load_project(config_path)
        project.analyze = _apply_analyze_overrides(project.analyze, args)
        output_root = _resolve_output_root(project, args.output_root)
        run_dir = run_project(
            project=project,
            output_root=output_root,
            run_dir=Path(args.run_dir) if args.run_dir else None,
            skip_extract=args.skip_extract,
            start_term_index=args.start_term_index,
            term_limit=args.term_limit,
        )
        print(run_dir)
        return 0

    if args.command == "scrape":
        scrape_cfg = _scrape_config_from_args(args)
        run_dir = scrape_subreddit(
            subreddits=list(args.subreddit),
            output_root=Path(args.output_root),
            scrape=scrape_cfg,
        )
        print(run_dir)
        return 0

    if args.command == "search":
        scrape_cfg = _scrape_config_from_args(args)
        run_dir = scrape_search_terms(
            terms_file=Path(args.terms_file),
            subreddits_file=Path(args.subreddits_file) if args.subreddits_file else None,
            output_root=Path(args.output_root),
            run_dir=Path(args.run_dir) if args.run_dir else None,
            scrape=scrape_cfg,
            relevance=RelevanceConfig(),
            start_term_index=args.start_term_index,
            term_limit=args.term_limit,
        )
        print(run_dir)
        return 0

    if args.command == "extract":
        analyze_cfg = _apply_analyze_overrides(AnalyzeConfig(), args)
        final_path = extract_from_run(run_dir=Path(args.run_dir), analyze=analyze_cfg)
        print(final_path)
        return 0

    if args.command == "init":
        if args.list_templates:
            print("Available prompt templates:")
            for name, mode, description in list_templates():
                print(f"  {name:<22} [{mode}]  {description}")
            return 0
        if not args.name:
            parser.error("init: a project name is required (or pass --list-templates).")
        projects_dir = Path(args.projects_dir)
        target = projects_dir / args.name
        from .config import _default_ollama_model

        subreddit_args = list(args.subreddit) if args.subreddit else []
        written = scaffold_project(
            project_dir=target,
            mode=args.mode,
            subreddit=subreddit_args[0] if len(subreddit_args) == 1 else None,
            subreddits=subreddit_args if len(subreddit_args) > 1 else None,
            terms=args.term,
            allowlist_subreddits=args.allowlist_subreddit,
            model=args.model or _default_ollama_model(),
            description=args.description,
            prompt_template=args.template,
            force=args.force,
        )
        if written:
            print(f"Created project at {target}:")
            for path in written:
                print(f"  + {path.relative_to(target)}")
            print(f"\nNext: edit {target / 'prompt.md'}, then run:")
            print(f"  reddit-researcher run {target}")
        else:
            print(f"Project at {target} already populated; nothing changed. Pass --force to overwrite.")
        return 0

    if args.command == "list":
        print(list_projects(Path(args.projects_dir)))
        print(list_runs(Path(args.runs_dir), limit=args.runs_limit))
        return 0

    if args.command == "review":
        print(summarize_run(Path(args.run_dir)), end="")
        return 0

    if args.command == "db":
        return _dispatch_db(args, parser)

    if args.command == "diff":
        return _dispatch_diff(args, parser)

    if args.command == "series":
        return _dispatch_series(args, parser)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _dispatch_db(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .db import make_sink, sync_run

    project_arg = getattr(args, "project", None)
    if project_arg is None:
        candidate = Path.cwd() / "project.toml"
        if not candidate.exists():
            parser.error(
                "db: pass --project <path> or run from a directory containing project.toml."
            )
        project_path = candidate
    else:
        project_path = find_project_config(Path(project_arg))
    load_dotenvs_for(project_dir=project_path.parent, repo_root=REPO_ROOT)
    project = load_project(project_path)

    if args.db_command == "sync":
        return _db_sync(args, project, make_sink, sync_run, parser)
    if args.db_command == "status":
        return _db_status(project, make_sink)
    if args.db_command == "query":
        return _db_query(args, project, make_sink)
    parser.error(f"Unsupported db command: {args.db_command}")
    return 2


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
                    print(f"error: diff sync failed: {exc}", file=sys.stderr)
                    return 1
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
    except OSError:
        return False
    except _json.JSONDecodeError:
        print(
            f"warning: corrupt manifest at {run_dir}; using cached sink rows",
            file=sys.stderr,
        )
        return False
    updated = manifest.get("updated_at_utc")
    if updated is None:
        return False
    return str(updated) > str(row[0])


def _db_sync(args, project, make_sink, sync_run, parser) -> int:
    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        if args.rebuild:
            sink.rebuild()
        run_dirs = [Path(p) for p in (args.run_dirs or [])]
        if args.all:
            output_root = (
                Path(args.output_root) if args.output_root
                else (project.output_root or DEFAULT_OUTPUT_ROOT)
            )
            run_dirs.extend(_walk_run_dirs(output_root))
        # Dedup while preserving first-seen order. Idempotent sync_run still
        # works without this, but it keeps the printed count accurate.
        run_dirs = list(dict.fromkeys(p.resolve() for p in run_dirs))
        if not run_dirs:
            parser.error(
                "db sync: pass one or more run directories, or --all with an output_root."
            )
        synced = 0
        for run_dir in run_dirs:
            try:
                sync_run(sink, run_dir)
            except (FileNotFoundError, OSError) as exc:
                parser.error(f"db sync: {exc}")
            synced += 1
        print(f"synced {synced} run dir(s) into {project.storage.db_path}")
        return 0
    finally:
        sink.close()


def _walk_run_dirs(output_root: Path) -> list[Path]:
    """Return every run dir under output_root that contains a manifest.json."""
    if not output_root.exists():
        return []
    found: list[Path] = []
    for manifest_path in output_root.rglob("manifest.json"):
        found.append(manifest_path.parent)
    return found


def _db_status(project, make_sink) -> int:
    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        ro = sink.read_only_connect()
        try:
            schema_row = ro.execute(
                "SELECT schema_version, created_at_utc, reddit_researcher_version FROM _schema_meta"
            ).fetchone()
            counts = {
                table: ro.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("runs", "posts", "comments", "relevance_decisions")
            }
            recent = ro.execute(
                "SELECT run_dir, mode, scope, status, post_count, comment_count "
                "FROM runs ORDER BY synced_at_utc DESC LIMIT 10"
            ).fetchall()
        finally:
            ro.close()
    finally:
        sink.close()

    print(f"engine:           {project.storage.engine}")
    print(f"db_path:          {project.storage.db_path}")
    if schema_row:
        print(f"schema_version:   {schema_row[0]} (created {schema_row[1]}, rr {schema_row[2]})")
    print("row counts:")
    for table, n in counts.items():
        print(f"  {table:<22} {n}")
    if recent:
        print("recent runs:")
        for run_dir, mode, scope, status, posts, comments in recent:
            print(f"  [{mode}] {scope:<24} {status:<18} {posts}p {comments}c  {run_dir}")
    return 0


def _db_query(args, project, make_sink) -> int:
    import csv

    sink = make_sink(project.storage, project_dir=project.project_dir)
    try:
        ro = sink.read_only_connect()
        try:
            try:
                cursor = ro.execute(args.sql)
            except Exception as exc:
                # Read-only mode rejects writes; bad SQL also surfaces here.
                print(f"error: {exc}", file=sys.stderr)
                return 1
            cols = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
        finally:
            ro.close()
    finally:
        sink.close()

    if args.format == "json":
        import json as _json

        payload = [dict(zip(cols, row, strict=False)) for row in rows]
        print(_json.dumps(payload, ensure_ascii=True))
        return 0
    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        if cols:
            writer.writerow(cols)
        writer.writerows(rows)
        return 0
    # table
    print(_format_table(cols, rows))
    return 0


def _format_table(cols: list[str], rows: list[tuple]) -> str:
    if not cols:
        return "(no rows)"
    string_rows = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [len(c) for c in cols]
    for row in string_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    sep = "  ".join("-" * w for w in widths)
    header = "  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=False))
    body = "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=False)) for row in string_rows)
    return f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}"


if __name__ == "__main__":
    raise SystemExit(main())
