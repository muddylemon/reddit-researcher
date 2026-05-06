from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .relevance import RelevanceConfig


VALID_MODES = {"subreddit", "search"}
VALID_SORTS = {"hot", "new", "top", "rising"}
VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}


@dataclass
class ScrapeConfig:
    mode: str = "subreddit"
    subreddit: str | None = None
    terms_file: Path | None = None
    subreddits_file: Path | None = None
    exact_phrase: bool = True
    sort: str = "top"
    time_filter: str = "month"
    post_limit: int = 25
    comment_limit: int = 10
    pause_seconds: float = 1.0
    max_retries: int = 5
    user_agent: str = "desktop:reddit-researcher:0.0.1 (by /u/local-user)"


@dataclass
class AnalyzeConfig:
    model: str = "qwen3:8b"
    prompt_file: Path | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: int = 600
    chunk_char_limit: int = 12000
    chunk_limit: int | None = None
    force_reextract: bool = False


@dataclass
class ProjectConfig:
    name: str
    description: str
    project_dir: Path
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    analyze: AnalyzeConfig = field(default_factory=AnalyzeConfig)
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    output_root: Path | None = None


def _resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def load_project(config_path: Path) -> ProjectConfig:
    """Load a project.toml file from disk and validate it."""
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found: {config_path}")

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    base_dir = config_path.parent.resolve()
    name = raw.get("name") or base_dir.name
    description = raw.get("description") or ""

    scrape_raw = raw.get("scrape", {})
    mode = scrape_raw.get("mode", "subreddit")
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid scrape.mode: {mode!r}. Must be one of {sorted(VALID_MODES)}.")
    sort = scrape_raw.get("sort", "top")
    if sort not in VALID_SORTS:
        raise ValueError(f"Invalid scrape.sort: {sort!r}. Must be one of {sorted(VALID_SORTS)}.")
    time_filter = scrape_raw.get("time_filter", "month")
    if time_filter not in VALID_TIME_FILTERS:
        raise ValueError(
            f"Invalid scrape.time_filter: {time_filter!r}. Must be one of {sorted(VALID_TIME_FILTERS)}."
        )

    scrape = ScrapeConfig(
        mode=mode,
        subreddit=scrape_raw.get("subreddit"),
        terms_file=_resolve_path(scrape_raw.get("terms_file"), base_dir),
        subreddits_file=_resolve_path(scrape_raw.get("subreddits_file"), base_dir),
        exact_phrase=bool(scrape_raw.get("exact_phrase", True)),
        sort=sort,
        time_filter=time_filter,
        post_limit=int(scrape_raw.get("post_limit", 25)),
        comment_limit=int(scrape_raw.get("comment_limit", 10)),
        pause_seconds=float(scrape_raw.get("pause_seconds", 1.0)),
        max_retries=int(scrape_raw.get("max_retries", 5)),
        user_agent=scrape_raw.get(
            "user_agent",
            "desktop:reddit-researcher:0.0.1 (by /u/local-user)",
        ),
    )

    if mode == "subreddit" and not scrape.subreddit:
        raise ValueError("scrape.mode='subreddit' requires scrape.subreddit to be set.")
    if mode == "search" and not scrape.terms_file:
        raise ValueError("scrape.mode='search' requires scrape.terms_file to be set.")

    analyze_raw = raw.get("analyze", {})
    analyze = AnalyzeConfig(
        model=analyze_raw.get("model", "qwen3:8b"),
        prompt_file=_resolve_path(analyze_raw.get("prompt_file"), base_dir),
        ollama_url=analyze_raw.get("ollama_url", "http://127.0.0.1:11434"),
        ollama_timeout_seconds=int(analyze_raw.get("ollama_timeout_seconds", 600)),
        chunk_char_limit=int(analyze_raw.get("chunk_char_limit", 12000)),
        chunk_limit=analyze_raw.get("chunk_limit"),
        force_reextract=bool(analyze_raw.get("force_reextract", False)),
    )

    relevance_raw = raw.get("relevance", {})
    keywords = relevance_raw.get("keywords") or []
    allowed_subs_value = relevance_raw.get("allowed_subreddits")
    allowed_subreddits: set[str] | None
    if allowed_subs_value is None:
        allowed_subreddits = None
    elif isinstance(allowed_subs_value, list):
        allowed_subreddits = {str(item).casefold() for item in allowed_subs_value}
    else:
        raise ValueError("relevance.allowed_subreddits must be a list of subreddit names")
    relevance = RelevanceConfig(
        keywords=[str(item) for item in keywords],
        allowed_subreddits=allowed_subreddits,
        require_exact_term_match=bool(relevance_raw.get("require_exact_term_match", True)),
    )

    output_root = _resolve_path(raw.get("output_root"), base_dir)

    return ProjectConfig(
        name=str(name),
        description=str(description),
        project_dir=base_dir,
        scrape=scrape,
        analyze=analyze,
        relevance=relevance,
        output_root=output_root,
    )


def find_project_config(path_or_dir: Path) -> Path:
    """Resolve a path to a project.toml file.

    Accepts either a path to the file itself or a directory that contains one.
    """
    candidate = Path(path_or_dir)
    if candidate.is_file():
        return candidate
    if candidate.is_dir():
        nested = candidate / "project.toml"
        if nested.is_file():
            return nested
    raise FileNotFoundError(
        f"Could not find project.toml at {path_or_dir!s}. "
        f"Pass a path to the file or a directory that contains one."
    )


# Convenience for tests / older Python checks.
if sys.version_info < (3, 11):  # pragma: no cover
    raise RuntimeError("reddit-researcher requires Python 3.11+ for tomllib.")
