# Reddit Researcher

> Local Reddit research jobs, piped through a local Ollama model. Built to fork.

**Status:** beta `0.0.1`

Reddit Researcher is a small, opinionated Python CLI for running structured research on Reddit.
You define a **project** (a folder with a TOML config and a prompt), point the tool at it, and
it scrapes Reddit's public JSON endpoints, applies a deterministic relevance filter, and runs
your prompt over the results with a local [Ollama](https://ollama.com/) model. No third-party APIs,
no hosted LLMs, no Reddit OAuth required.

It's designed to be **forked**: each project lives in its own folder, all artifacts go into
timestamped `runs/` directories, and there are first-class extension points (project configs,
relevance keywords, custom prompts, Claude Code skills).

## Why this exists

- **Local-first.** Your data never leaves your machine. The only outbound traffic is Reddit's public
  JSON and your local Ollama instance.
- **Cheap iteration.** A deterministic relevance pass runs before any LLM call, so you only spend
  inference cycles on posts that are likely worth reading.
- **Resumable.** Scrapes checkpoint after every post; extractions reuse previously-completed chunks.
- **Reproducible.** Every run is a folder of JSON, JSONL, and Markdown — no databases, no opaque
  state.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com/) running locally with at least one model pulled
- A polite User-Agent (the default is fine for personal use)

A practical default model: `qwen3:8b`. See [`docs/model-recommendations.md`](docs/model-recommendations.md)
for hardware-specific guidance.

## Install

```bash
git clone https://github.com/muddylemon/reddit-researcher.git
cd reddit-researcher
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `reddit-researcher` console command.

## 60-second quickstart

Pull a model and start Ollama:

```bash
ollama pull qwen3:8b
ollama serve   # leave running in another terminal
```

Run the example subreddit project:

```bash
reddit-researcher run projects/example-supplements
```

That command will:

1. Fetch the top posts from `r/Supplements` for the last month.
2. Pull a small number of comments per post.
3. Build a corpus, chunk it, and feed it to `qwen3:8b` with the project's prompt.
4. Write everything into a fresh `runs/Supplements/<timestamp>/` folder.

Open `runs/.../analysis/final.md` to read the synthesized result.

## What is a "project"?

A project is a folder. The folder layout is up to you, but Reddit Researcher only cares about a
single file: `project.toml`.

```toml
# projects/example-supplements/project.toml
name = "supplements-questions"
description = "Recurring questions in r/Supplements over the last month."

[scrape]
mode = "subreddit"
subreddit = "Supplements"
sort = "top"
time_filter = "month"
post_limit = 25
comment_limit = 10

[analyze]
model = "qwen3:8b"
prompt_file = "prompt.md"
chunk_char_limit = 12000
ollama_timeout_seconds = 600
```

A search-mode project looks like this:

```toml
# projects/example-search/project.toml
name = "experts-mentioned-on-reddit"
description = "Find Reddit discussion of named experts."

[scrape]
mode = "search"
terms_file = "terms.txt"
subreddits_file = "subreddits.txt"
exact_phrase = true
sort = "top"
time_filter = "all"
post_limit = 10
comment_limit = 3

[analyze]
model = "qwen3:8b"
prompt_file = "prompt.md"
ollama_timeout_seconds = 600

[relevance]
keywords = ["interview", "podcast", "research"]
```

See [`projects/example-supplements/`](projects/example-supplements/) and
[`projects/example-search/`](projects/example-search/) for full examples.

## CLI reference

```text
reddit-researcher run <project>           Load project.toml and run scrape + extract.
reddit-researcher scrape <subreddit>      One-off subreddit scrape (no project needed).
reddit-researcher search --terms-file=... One-off Reddit search across one or more terms.
reddit-researcher extract <run-dir>       Re-run analysis over an already-scraped run folder.
```

Common flags (see `reddit-researcher <cmd> --help` for the full list):

- `--skip-extract` — scrape only; don't call Ollama.
- `--run-dir <path>` — resume into an existing run folder (search mode).
- `--start-term-index N` / `--term-limit N` — process a slice of `terms.txt`.
- `--force-reextract` — regenerate chunk outputs even if they already exist.
- `--model`, `--prompt-file`, `--chunk-limit` — override what's in `project.toml`.

## Run folder layout

```text
runs/<scope>/<timestamp>/
  manifest.json                    settings, status, counts, errors
  logs/
    scrape.log
    extract.log
  raw/
    posts.json                     raw Reddit response payloads
    comments/<post-id>.json
  review/
    relevance_review.jsonl         one decision per candidate post
  normalized/
    candidate_posts.jsonl          all search hits before comments
    posts.jsonl                    fetched posts (with comments embedded)
    relevant_posts.jsonl           subset selected for LLM analysis
    comments.jsonl                 flattened comments
  analysis/
    chunks/chunk-001.md            one model response per chunk
    final.md                       synthesized final report
```

## Built-in Claude Code skills

If you use [Claude Code](https://claude.com/claude-code), this repo ships with skills under
`.claude/skills/`:

- **design-research-project** — walks you through creating a new `projects/<name>/` folder
  with a `project.toml`, `prompt.md`, and any term/subreddit files you need.
- **run-research-project** — runs an existing project and surfaces the manifest + final report.
- **review-research-results** — opens a completed run and summarizes what was found, what
  failed, and what to tweak.

These are plain Markdown files; you can read or fork them without Claude Code.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the planned trajectory toward `0.1.0` and beyond.
Highlights for the next few releases:

- Pluggable storage backends (SQLite, DuckDB) for cross-run analytics.
- Optional PRAW backend for authenticated, higher-quota scraping.
- A small judge-pipeline mode (LLM-as-judge for filtering noisy posts).
- Project templates and a `reddit-researcher init` command.

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the basics. The short version: keep
the core dependency-light, prefer composable primitives over big abstractions, and don't add
remote/cloud dependencies — this tool is local-first by design.

## Caveats

- Reddit's public JSON endpoint is rate-limited and occasionally serves stale or partial data.
  Be patient, keep `--pause-seconds` reasonable, and respect the platform.
- The relevance filter is deliberately simple (substring + keyword). It's a cost-control pass,
  not a final classifier — the LLM is allowed to disagree.
- Local LLM output quality depends heavily on your model and your prompt. Iterate on small
  scrapes (`--term-limit 1`, `--chunk-limit 1`) before committing to long runs.

## License

MIT — see [`LICENSE`](LICENSE).
