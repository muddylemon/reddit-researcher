# Agent instructions

Reddit Researcher is a local-first Reddit research CLI. A "project" is a folder with
a `project.toml` and a `prompt.md`; a "run" is a timestamped folder under `runs/`
that holds the scrape, normalized data, and the LLM's analysis. Everything is on disk
as JSON / JSONL / Markdown; an optional SQLite/DuckDB sink mirrors it for cross-run
queries.

## Skills

This repo ships five Claude Code skills under `.claude/skills/`. They are also
useful as instructions for any agentic tool that can follow a Markdown
playbook.

- **`/setup`** — pre-flight check on a fresh clone. Verifies Python 3.11+, the venv,
  the editable install, Ollama reachability, and a pulled model. Offers a fix
  command per gap (one Y/N per fix; never batched). Ends with an offer to run
  `/tutorial`.
- **`/tutorial`** — 3-minute end-to-end run of `projects/example-subreddit-faq` capped
  at one extract chunk. Use after `/setup` succeeds.
- **`/design-research-project`** — turns a research question into a new
  `projects/<name>/` folder (project.toml + prompt.md + optional terms /
  subreddits files).
- **`/run-research-project`** — staged execution of an existing project: tiny
  scrape → single-chunk extract → full run, surfacing the manifest and
  `final.md`.
- **`/review-research-results`** — opens a completed run, summarises `final.md`,
  and flags data-quality issues (low relevance hit-rate, fetch errors,
  hallucinated post IDs).

**Onboarding flow for a fresh clone:** `/setup` → `/tutorial` → `/design-research-project`.

## CLI conventions

- Use the venv's binary explicitly. On Windows: `.venv\Scripts\reddit-researcher.exe`.
  On POSIX: `.venv/bin/reddit-researcher`.
- `db`, `diff`, and `series` need `--project <path>` to resolve the SQLite/DuckDB
  sink. (`extract` and `diff` auto-discover the project from `manifest.project_name`
  when both run-dirs reference a project that lives at
  `projects/<project_name>/project.toml` — this is the contract; see "Project
  layout" below.)
- Scrape-only iteration: `--skip-extract`. Extract-only on an existing run dir:
  `reddit-researcher extract <run-dir>`.
- For search-mode projects, work a slice first: `--term-limit 1` for a one-term
  smoke test; `--chunk-limit 1` to test the prompt cheaply.

## Project layout

- `projects/<name>/` — committable project. The `name` field inside
  `project.toml` MUST match the folder name; auto-discovery for `extract` /
  `diff` looks up `projects/<manifest.project_name>/`.
- `projects/local-*/` — gitignored. Use this prefix for private experiments;
  `git status` won't show them.
- `runs/` — entirely gitignored. Each run lives at
  `runs/<scope>/<timestamp>/` (see `docs/architecture.md` for the full layout).
- `research.db` (or whatever `[storage].db_path` points at) sits next to
  `project.toml` per project. It's a mirror of the JSONL — safe to delete and
  re-sync.

## Conventions worth knowing before you write code or prompts

- **Corpus format defaults to `compact`.** `conversational` reads better but
  degrades citations on small (≤8B) local models — the model latches onto
  author handles in the prose framing and substitutes them for bracketed post
  IDs. If a prompt asks for cited claims and you're on an 8B-class model, stay
  on `compact`.
- **Local-first by design.** No outbound calls except Reddit's public JSON
  endpoint (or PRAW with user-supplied creds) and the user's local Ollama. Do
  not introduce remote / cloud dependencies.
- **PRAW is opt-in.** Default backend is the unauthenticated JSON endpoint.
  `[scrape].backend = "praw"` switches to PRAW; that path needs
  `pip install -e ".[praw]"` and `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`
  in the environment.
- **Multi-subreddit subreddit mode** uses `subreddits = ["a", "b", "c"]` (not
  `subreddit = "a"`); `post_limit` is per-subreddit. Combined run lands at
  `runs/<a>-<b>-<c>/<ts>/`.
- **Resumability is real.** Scrapes checkpoint after every post; extractions
  reuse previously-completed chunks. Use `--run-dir <path>` to resume into an
  existing run.

## Where to look

| Topic | File |
|---|---|
| System architecture, run-folder layout | `docs/architecture.md` |
| Picking a model for your hardware | `docs/model-recommendations.md` |
| Project shapes and recipes | `docs/ideas.md` |
| Roadmap | `docs/roadmap.md` |
| Changelog | `CHANGELOG.md` |

## Anti-patterns

- Adding a `mode = "subreddit"` project for a topic that spans communities. Use
  search mode with a `subreddits.txt` allowlist instead.
- 30-line prompts. Long prompts dilute model attention. Keep prompts under
  ~200 words.
- Naming a committable project `local-foo`. The repo's `.gitignore` matches
  `projects/local-*/`, so the folder will silently disappear from `git status`.
- Committing `runs/`. Always gitignored.
