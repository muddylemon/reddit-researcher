# Changelog

All notable changes to Reddit Researcher are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
