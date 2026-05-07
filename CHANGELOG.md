# Changelog

All notable changes to Reddit Researcher are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0-beta] — 2026-05-07

The analytics-and-multi-run line. Closes four of the five 0.2.0 roadmap items;
time-series mode (scheduled re-runs + cross-timestamp aggregation) is deferred
to a follow-up.

Highlights:

- **Multi-subreddit subreddit-mode** — scrape several communities into one combined
  run folder.
- **SQLite/DuckDB sink** — every run is mirrored into a small queryable DB
  (default SQLite, opt-in DuckDB) so cross-run analysis is `SELECT ...` instead of
  one-off scripts.
- **`reddit-researcher diff`** — compare two runs (counts, post-id sets,
  relevance flips).
- **Configurable corpus formatters** — pick `compact` (default), `conversational`,
  or `structured-json`.

JSONL on disk remains canonical; the sink is a derived view.

### Added
- Multi-subreddit subreddit-mode: `[scrape].subreddits = ["a", "b", "c"]` scrapes
  multiple communities into a single combined run folder, with per-sub status
  tracked in `manifest["per_subreddit"]`. Single-sub projects continue to work
  unchanged. `post_limit` applies per-subreddit (matching search-mode semantics).
- Manifest `schema_version` bumped 1 → 2 (additive). New fields: `subreddits`
  (list, always present in subreddit-mode), `per_subreddit` (per-sub counters
  and status). Old (v1) manifests read forward via `normalize_manifest` —
  no rewriting needed.
- `multi_subreddit_scope` helper for run-dir naming with multiple subs.
- **Run database sink.** Each run's normalized rows are mirrored into a
  small relational DB for cross-run analysis. SQLite (stdlib) is the default;
  DuckDB is opt-in via `pip install reddit-researcher[duckdb]` plus
  `[storage].engine = "duckdb"`. New `[storage]` config block (`engine`,
  `db_path`, `auto_sync`). Tables: `runs`, `posts`, `comments`,
  `relevance_decisions`, plus `_schema_meta`. JSONL on disk remains canonical.
- **`db` CLI subcommand group.**
  - `db sync [<run-dir>...] [--all] [--rebuild]` — sync one or many run dirs.
  - `db status` — print engine, DB path, schema version, row counts, recent runs.
  - `db query "<SQL>"` — run a read-only query; output as table, JSON, or CSV.
- **`reddit-researcher diff <run-a> <run-b>`.** Compare two runs of (typically)
  the same project: counts diff, post_id set membership (only-in-A,
  only-in-B, in-both), comment counts, and relevance-decision flips. Reads
  from the SQLite/DuckDB sink and auto-syncs each run if missing. Text
  table by default; `--format json` for piping. Warns on mode/scope/project
  mismatch but always produces a result.
- **Configurable corpus formatters.** New `[analyze].corpus_format` field
  selects between `compact` (default, byte-equivalent to today's output),
  `conversational` (markdown headings + prose metadata), and `structured-json`
  (one JSON object per post, blank-line separated). Override per-run with
  `--corpus-format`. The legacy `build_corpus` / `build_search_corpus` are
  now thin wrappers around `format_corpus`.

### Changed

- `ScrapeConfig.subreddit` (str) replaced by `ScrapeConfig.subreddits` (list).
  TOML projects continue to accept either `subreddit = "x"` or
  `subreddits = ["a", "b"]` (but not both).
- `scaffold_project` parameter `subreddits` (search-mode allowlist) renamed to
  `allowlist_subreddits` to free up the name for the new multi-sub scaffolder.
- `reddit-researcher scrape <name>` now accepts multiple positional names:
  `reddit-researcher scrape cannabis marijuana drugs`.
- `reddit-researcher init --subreddit` is now repeatable; supplying multiple
  scaffolds a `subreddits = [...]` project.
- CI coverage gate raised from 70% to 85% (currently passing at 89%).

### Internal

- New tests covering pipeline gaps revealed by the v0.1.1-beta coverage report:
  `tests/test_extract.py` (6 tests), `tests/test_search_scrape.py` (7 tests),
  `tests/test_run_project.py` (5 tests). Plus full test coverage for the new
  0.2.0 features (sink, diff, corpus formatters): 203 tests passing total
  (was 35 in 0.0.1-beta).
- New "Caveats and known limitations" section in
  [docs/architecture.md](docs/architecture.md) documenting Reddit's anonymous
  in-sub search behavior, multi-subreddit handling, the ~1000-post pagination
  cap, comment-tree limits, and relevance-filter tuning.
- New "Local industry directory" pattern in [docs/ideas.md](docs/ideas.md) —
  the multi-subreddit case study shape with the cannabis-businesses example.
- `CONTRIBUTING.md` notes the optional `[praw]` and `[duckdb]` extras.

### Deferred to a follow-up

- Time-series mode (scheduled re-runs + cross-timestamp aggregation across
  `runs.synced_at_utc`) — the fifth 0.2.0 roadmap item. Best built on top of
  the sink that landed in this release.

## [0.1.1-beta] — 2026-05-06

Closes the last open item in the `0.1.0` milestone.

### Added
- **Optional PRAW backend.** New `[scrape].backend = "praw"` config field selects an
  authenticated [PRAW](https://praw.readthedocs.io/)-backed client. Higher rate-limit
  ceiling than the unauth JSON endpoint, full comment-tree expansion, and listings beyond
  1000 posts.
  - Install with `pip install reddit-researcher[praw]`.
  - Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in your environment or a project
    `.env` file. Register a "script" app at https://www.reddit.com/prefs/apps to get them.
  - Helpful errors when `praw` is not installed (`PrawNotInstalled`) or credentials are
    missing (`PrawCredentialsMissing`). Both surface install + setup instructions.
- New `make_reddit_client(scrape)` factory in `reddit_client.py` dispatches between the
  two backends. `praw_client.PrawRedditClient` mirrors `RedditClient`'s interface, so
  the pipeline doesn't care which backend it gets.

### Changed
- `pipeline.py` constructs its Reddit client through the factory instead of instantiating
  `RedditClient` directly. No behavior change for projects on the default `"json"` backend.

### Internal
- 78 tests passing (was 67), 76% line coverage. PRAW tests use stubbed `praw.Reddit`
  objects so the suite still runs without the optional dep installed.

## [0.1.0-beta] — 2026-05-06

First-stable-line foundations. Knocks out everything in the `0.1.0` roadmap
milestone except the optional PRAW backend, which gets its own pass.

### Added
- **Versioned manifest schema.** Every `manifest.json` written by 0.1.0 carries
  `schema_version: 1`. New `reddit_researcher.manifest` module owns the constant
  and the read/write helpers. Manifests written before this release implicitly
  have `schema_version = 0` and are handled gracefully by `reddit-researcher review`.
- **Subreddit-mode resume.** `scrape_subreddit` now accepts `run_dir=` and appends
  to existing `normalized/posts.jsonl` instead of overwriting. `reddit-researcher run
  <project> --run-dir <path>` works for both modes now.
- **Built-in prompt templates.** Six vetted prompts ship in
  `reddit_researcher/prompt_templates/`: `question-mining`, `theme-extraction`,
  `sentiment-comparison`, `tool-evaluation`, `product-research`, `expert-mention`.
  - `reddit-researcher init <name> --template <id>` seeds `prompt.md` from a template.
  - `reddit-researcher init --list-templates` shows the catalog.
  - The default-no-flag behavior of `init` now picks the right template based on
    `--mode` (subreddit → `question-mining`, search → `sentiment-comparison`).
- **`.env` support.** Tiny in-tree dotenv parser (no new dependency). `.env`
  files are loaded from the repo root and from the project folder, with project
  values overriding repo values, and shell environment values winning over both.
  Useful keys: `OLLAMA_URL`, `OLLAMA_MODEL`, `REDDIT_RESEARCHER_USER_AGENT`.
- **Coverage in CI.** `pytest-cov` is a dev dependency; the Linux 3.12 CI job
  enforces a 70% line-coverage gate. Local: `pytest --cov`.

### Changed
- `AnalyzeConfig.model` and `AnalyzeConfig.ollama_url` defaults now read from
  `OLLAMA_MODEL` and `OLLAMA_URL` env vars when set. `ScrapeConfig.user_agent`
  honors `REDDIT_RESEARCHER_USER_AGENT`. CLI flags and `project.toml` values
  still win over env-derived defaults.
- `scrape_subreddit` writes a checkpointing manifest with `status: starting/
  fetching_comments/complete`, matching search-mode behavior. The status field
  is now part of the schema for both modes.

### Internal
- New `reddit_researcher.env` and `reddit_researcher.manifest` modules.
- `reddit_researcher.prompt_templates` is a package-data directory of `.md` files,
  exposed through a small loader.
- 67 tests passing (was 35), 74.5% line coverage.

## [0.0.2-beta] — 2026-05-06

Beta polish pass — knocks out the first roadmap milestone.

### Added
- `reddit-researcher init <name>` scaffolds a new project folder. Modes:
  `--mode subreddit --subreddit Foo` and `--mode search [--term ...] [--allowlist-subreddit ...]`.
  Idempotent by default; pass `--force` to overwrite.
- `reddit-researcher list` shows projects (under `projects/`) and the most recent runs
  (under `runs/`) as compact tables. `--projects-dir`, `--runs-dir`, and `--runs-limit` overrides.
- `reddit-researcher review <run-dir>` prints a one-screen summary of a run's manifest:
  mode, scope, status, scrape settings, post/comment counts, relevance breakdown, errors,
  analysis info, and the path to `final.md`.
- GitHub Actions CI: pytest matrix across Python 3.11/3.12/3.13 plus Windows and macOS smoke runs,
  and a `ruff check` + `ruff format --check` lint job. Runnable on a fork, no secrets needed.
- Ruff configuration in `pyproject.toml`.

### Changed
- Project-config validation now raises `ProjectConfigError`, which prefixes the offending file
  path (and a line number, when tomllib provides one) before the message. The CLI catches
  these and exits with status 2 plus a `error: <path:line>: <detail>` line on stderr.

### Internal
- New `reddit_researcher.templates` module owns project scaffolding.
- New `reddit_researcher.views` module owns read-only project/run inspection.

### Examples
- Replaced the original health-adjacent examples with four broadly-applicable templates
  covering the four most common project shapes:
  - `example-subreddit-faq` (community FAQ mining, replaces `example-supplements`)
  - `example-game-reception` (comparative sentiment, replaces `example-search`)
  - `example-tool-sentiment` (developer-focused tool comparison)
  - `example-product-research` (durability + buyer research)
- New [`docs/ideas.md`](docs/ideas.md) catalogs additional project shapes for inspiration:
  public-figure sentiment, hobby starter packs, civic threads, trend tracking, and more.

## [0.0.1-beta] — 2026-05-06

Initial public-facing beta. Generalized fork of an internal research tool.

### Added
- `project.toml` config format and `reddit-researcher run <project>` end-to-end command.
- Lower-level `scrape`, `search`, and `extract` subcommands.
- Configurable, generic relevance review (keyword + allowlist driven).
- Two example projects: `example-supplements` (subreddit mode) and `example-search` (search mode).
- Built-in Claude Code skills under `.claude/skills/` for designing, running, and reviewing
  research projects.
- Architecture and roadmap docs.
- Test suite covering prompting, relevance, storage, and config loading.
- MIT license, packaging via `pyproject.toml`, and a `reddit-researcher` console entry point.
