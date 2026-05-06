from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .config import (
    AnalyzeConfig,
    ProjectConfig,
    ScrapeConfig,
    find_project_config,
    load_project,
)
from .pipeline import (
    extract_from_run,
    run_project,
    scrape_search_terms,
    scrape_subreddit,
)
from .relevance import RelevanceConfig


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "runs"


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
    run_parser.add_argument("--run-dir", default=None, help="Existing run directory to resume into (search mode).")
    run_parser.add_argument("--skip-extract", action="store_true", help="Scrape only; do not call Ollama.")
    run_parser.add_argument("--start-term-index", type=int, default=1)
    run_parser.add_argument("--term-limit", type=int, default=None)
    _add_analyze_overrides(run_parser)

    scrape_parser = subparsers.add_parser(
        "scrape",
        help="Scrape a single subreddit's listing into a run folder.",
    )
    scrape_parser.add_argument("subreddit", help="Subreddit name without the r/ prefix.")
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

    if args.command == "run":
        config_path = find_project_config(Path(args.project))
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
            subreddit=args.subreddit,
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

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
