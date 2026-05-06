from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .relevance import RelevanceConfig

VALID_MODES = {"subreddit", "search"}
VALID_SORTS = {"hot", "new", "top", "rising"}
VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}

# Environment variable names that override built-in defaults. CLI flags and
# project.toml values still win over these. Documented in docs/architecture.md.
ENV_OLLAMA_URL = "OLLAMA_URL"
ENV_OLLAMA_MODEL = "OLLAMA_MODEL"
ENV_USER_AGENT = "REDDIT_RESEARCHER_USER_AGENT"


def _default_ollama_url() -> str:
    return os.environ.get(ENV_OLLAMA_URL, "http://127.0.0.1:11434")


def _default_ollama_model() -> str:
    return os.environ.get(ENV_OLLAMA_MODEL, "qwen3:8b")


def _default_user_agent() -> str:
    return os.environ.get(
        ENV_USER_AGENT,
        "desktop:reddit-researcher:0.1.0 (by /u/local-user)",
    )


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
    user_agent: str = field(default_factory=_default_user_agent)


@dataclass
class AnalyzeConfig:
    model: str = field(default_factory=_default_ollama_model)
    prompt_file: Path | None = None
    ollama_url: str = field(default_factory=_default_ollama_url)
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


class ProjectConfigError(ValueError):
    """Raised when a project.toml is malformed or fails validation.

    `path` is the offending file, `lineno` is the 1-based line number when the
    underlying error reports one (e.g. tomllib parse errors), otherwise `None`.
    """

    def __init__(self, message: str, *, path: Path, lineno: int | None = None) -> None:
        location = f"{path}:{lineno}" if lineno else str(path)
        super().__init__(f"{location}: {message}")
        self.path = path
        self.lineno = lineno
        self.detail = message


def load_project(config_path: Path) -> ProjectConfig:
    """Load a project.toml file from disk and validate it."""
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found: {config_path}")

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        # tomllib's message often embeds "(at line N, column M)" — surface it.
        lineno = getattr(exc, "lineno", None)
        raise ProjectConfigError(f"invalid TOML: {exc}", path=config_path, lineno=lineno) from exc

    base_dir = config_path.parent.resolve()
    name = raw.get("name") or base_dir.name
    description = raw.get("description") or ""

    scrape_raw = raw.get("scrape", {})
    mode = scrape_raw.get("mode", "subreddit")
    if mode not in VALID_MODES:
        raise ProjectConfigError(
            f"invalid scrape.mode: {mode!r}. Must be one of {sorted(VALID_MODES)}.",
            path=config_path,
        )
    sort = scrape_raw.get("sort", "top")
    if sort not in VALID_SORTS:
        raise ProjectConfigError(
            f"invalid scrape.sort: {sort!r}. Must be one of {sorted(VALID_SORTS)}.",
            path=config_path,
        )
    time_filter = scrape_raw.get("time_filter", "month")
    if time_filter not in VALID_TIME_FILTERS:
        raise ProjectConfigError(
            f"invalid scrape.time_filter: {time_filter!r}. Must be one of {sorted(VALID_TIME_FILTERS)}.",
            path=config_path,
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
        user_agent=scrape_raw.get("user_agent", _default_user_agent()),
    )

    if mode == "subreddit" and not scrape.subreddit:
        raise ProjectConfigError(
            "scrape.mode='subreddit' requires scrape.subreddit to be set.",
            path=config_path,
        )
    if mode == "search" and not scrape.terms_file:
        raise ProjectConfigError(
            "scrape.mode='search' requires scrape.terms_file to be set.",
            path=config_path,
        )

    analyze_raw = raw.get("analyze", {})
    analyze = AnalyzeConfig(
        model=analyze_raw.get("model", _default_ollama_model()),
        prompt_file=_resolve_path(analyze_raw.get("prompt_file"), base_dir),
        ollama_url=analyze_raw.get("ollama_url", _default_ollama_url()),
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
        raise ProjectConfigError(
            "relevance.allowed_subreddits must be a list of subreddit names",
            path=config_path,
        )
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
