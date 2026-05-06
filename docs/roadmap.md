# Roadmap

This is a living document. Beta `0.0.1` is the foundation; everything below is a target, not a
promise. If something here matters to you, open an issue.

## 0.0.x — beta polish

The current line. Goal: keep the core stable while smoothing rough edges.

- [x] `reddit-researcher init <name>` to scaffold a new project folder from a template. *(0.0.2)*
- [x] `reddit-researcher list` to show available projects and recent runs. *(0.0.2)*
- [x] `reddit-researcher review <run-dir>` for a quick CLI summary of a run's manifest + counts. *(0.0.2)*
- [x] Better error messages when `project.toml` is malformed (line-number-aware). *(0.0.2)*
- [x] CI: lint + test workflow runnable on a fork without secrets. *(0.0.2)*

## 0.1.0 — first stable line

Goal: a version that's safe to pin and recommend without caveats.

- [x] Versioned manifest schema (`schema_version` field) with a forward-compatibility note. *(0.1.0)*
- [x] Optional PRAW backend behind `[scrape].backend = "praw"` for authenticated, higher-quota use. *(0.1.1)*
- [x] First-class subreddit-mode resume (parity with search mode). *(0.1.0)*
- [x] Built-in prompt templates: question-mining, sentiment, expert-mention, FAQ extraction. *(0.1.0)*
- [x] Project-level `.env` support for things like `OLLAMA_URL` and PRAW credentials. *(0.1.0)*
- [x] Test coverage report in CI; gate at 70% currently, ratcheting toward 80%. *(0.1.0)*

## 0.2.0 — analytics

Goal: make multi-run analysis tractable.

- [ ] Optional SQLite/DuckDB sink writing each run's normalized rows into a queryable database.
- [ ] `reddit-researcher diff <run-a> <run-b>` to compare two runs of the same project.
- [ ] Time-series mode: re-run a project on a schedule and aggregate results across timestamps.
- [ ] Configurable corpus formatters (compact, conversational, structured-JSON-for-tools).

## 0.3.0 — judging and routing

Goal: better signal-to-noise on noisy topics.

- [ ] LLM-as-judge pre-filter: before the main extraction, use a smaller model to score posts.
- [ ] Pairwise judging mode for ambiguous posts (catches position bias).
- [ ] Per-chunk model routing: cheap model for filter, larger model for synthesis.
- [ ] Cost-tracking output (prompt tokens, response tokens, wall time per stage).

## Beyond

Things that are interesting but unscoped:

- Browser-friendly viewer for a run folder (a small static HTML report from `final.md` + manifest).
- A pluggable "source" layer (Hacker News, Mastodon, RSS) so the same prompts work on more inputs.
- Plugin-style extension points for custom relevance functions and corpus builders.
- A small set of canonical projects maintained in-repo so the tool ships with working examples for
  common research shapes (FAQ-mining, expert-tracking, product-feedback).

## Non-goals

To keep the project sharp, these are explicitly **out of scope**:

- A managed/cloud version of the tool.
- A required Reddit OAuth flow as the default code path.
- Integration with paid LLM APIs as the default. (A user can still wire one up by replacing
  `OllamaClient`; the tool just won't ship that as a first-class mode.)
- A web UI that becomes a maintenance burden. A static report viewer is fine; a server is not.
