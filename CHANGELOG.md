# Changelog

All notable changes to Reddit Researcher are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
