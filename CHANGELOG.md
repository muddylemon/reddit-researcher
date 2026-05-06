# Changelog

All notable changes to Reddit Researcher are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
