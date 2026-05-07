from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .relevance import RelevanceConfig

VALID_MODES = {"subreddit", "search"}
VALID_SORTS = {"hot", "new", "top", "rising"}
VALID_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
VALID_BACKENDS = {"json", "praw"}
VALID_DB_ENGINES = {"sqlite", "duckdb"}

# Environment variable names that override built-in defaults. CLI flags and
# project.toml values still win over these. Documented in docs/architecture.md.
ENV_OLLAMA_URL = "OLLAMA_URL"
ENV_OLLAMA_MODEL = "OLLAMA_MODEL"
ENV_USER_AGENT = "REDDIT_RESEARCHER_USER_AGENT"

# PRAW credentials for the authenticated backend. Read-only mode does not need
# a username or password — registering a "script" app at https://www.reddit.com/prefs/apps
# yields the client_id and client_secret.
ENV_PRAW_CLIENT_ID = "REDDIT_CLIENT_ID"
ENV_PRAW_CLIENT_SECRET = "REDDIT_CLIENT_SECRET"


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
    backend: str = "json"
    subreddits: list[str] = field(default_factory=list)
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
class StorageConfig:
    engine: str = "sqlite"
    db_path: Path = field(default_factory=lambda: Path("research.db"))
    auto_sync: bool = True


@dataclass
class ProjectConfig:
    name: str
    description: str
    project_dir: Path
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    analyze: AnalyzeConfig = field(default_factory=AnalyzeConfig)
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
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


def _is_valid_subreddit_name(value: object) -> bool:
    """Return True if value looks like a usable subreddit name.

    Reddit allows alphanumerics + underscore; we additionally reject empty
    strings, whitespace, and slashes (which would break URL paths and run-dir
    naming).
    """
    if not isinstance(value, str):
        return False
    if not value.strip():
        return False
    if "/" in value:
        return False
    if any(ch.isspace() for ch in value):
        return False
    return True


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
    backend = scrape_raw.get("backend", "json")
    if backend not in VALID_BACKENDS:
        raise ProjectConfigError(
            f"invalid scrape.backend: {backend!r}. Must be one of {sorted(VALID_BACKENDS)}.",
            path=config_path,
        )

    raw_singular = scrape_raw.get("subreddit")
    raw_plural = scrape_raw.get("subreddits")
    if raw_singular is not None and raw_plural is not None:
        raise ProjectConfigError(
            "scrape.subreddit and scrape.subreddits cannot both be set; choose one (not both).",
            path=config_path,
        )

    subreddits_list: list[str] = []
    if raw_plural is not None:
        if not isinstance(raw_plural, list):
            raise ProjectConfigError(
                "scrape.subreddits must be a list of subreddit names.",
                path=config_path,
            )
        seen_lower: set[str] = set()
        for item in raw_plural:
            if not _is_valid_subreddit_name(item):
                raise ProjectConfigError(
                    f"invalid subreddit name in scrape.subreddits: {item!r}",
                    path=config_path,
                )
            lowered = item.casefold()
            if lowered in seen_lower:
                continue
            seen_lower.add(lowered)
            subreddits_list.append(item)
    elif raw_singular is not None:
        if not _is_valid_subreddit_name(raw_singular):
            raise ProjectConfigError(
                f"invalid subreddit name in scrape.subreddit: {raw_singular!r}",
                path=config_path,
            )
        subreddits_list = [raw_singular]

    scrape = ScrapeConfig(
        mode=mode,
        backend=backend,
        subreddits=subreddits_list,
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

    if mode == "subreddit" and not scrape.subreddits:
        raise ProjectConfigError(
            "scrape.mode='subreddit' requires scrape.subreddit (or scrape.subreddits) to be set.",
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

    storage_raw = raw.get("storage", {})
    storage_engine = storage_raw.get("engine", "sqlite")
    if storage_engine not in VALID_DB_ENGINES:
        raise ProjectConfigError(
            f"invalid storage.engine: {storage_engine!r}. Must be one of {sorted(VALID_DB_ENGINES)}.",
            path=config_path,
        )
    storage_db_path_raw = storage_raw.get("db_path", "research.db")
    storage_db_path = _resolve_path(storage_db_path_raw, base_dir)
    if storage_db_path is None:
        storage_db_path = (base_dir / "research.db").resolve()
    storage = StorageConfig(
        engine=storage_engine,
        db_path=storage_db_path,
        auto_sync=bool(storage_raw.get("auto_sync", True)),
    )

    output_root = _resolve_path(raw.get("output_root"), base_dir)

    return ProjectConfig(
        name=str(name),
        description=str(description),
        project_dir=base_dir,
        scrape=scrape,
        analyze=analyze,
        relevance=relevance,
        storage=storage,
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
