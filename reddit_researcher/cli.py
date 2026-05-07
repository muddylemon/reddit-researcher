from __future__ import annotations

import argparse
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
    )


def _resolve_output_root(project: ProjectConfig, override: str | None) -> Path:
    if override:
        return Path(override)
    if project.output_root is not None:
        return project.output_root
    return DEFAULT_OUTPUT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
        parser.error("db query: not implemented yet (Task 12)")
    parser.error(f"Unsupported db command: {args.db_command}")
    return 2


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


if __name__ == "__main__":
    raise SystemExit(main())
