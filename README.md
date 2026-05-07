# Reddit Researcher

> Local Reddit research jobs, piped through a local Ollama model. Built to fork.

**Status:** beta `0.2.0`

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

Run the example subreddit-FAQ project:

```bash
reddit-researcher run projects/example-subreddit-faq
```

That command will:

1. Fetch the top posts from `r/personalfinance` for the last month.
2. Pull the top comments per post.
3. Build a corpus, chunk it, and feed it to `qwen3:8b` with the project's prompt.
4. Write everything into a fresh `runs/personalfinance/<timestamp>/` folder.

Open `runs/.../analysis/final.md` to read the synthesized FAQ.

Want to compare reception of a few video games instead? Try:

```bash
reddit-researcher run projects/example-game-reception
```

See [`docs/ideas.md`](docs/ideas.md) for a full catalog of project shapes you can adapt.

## What is a "project"?

A project is a folder. The folder layout is up to you, but Reddit Researcher only cares about a
single file: `project.toml`.

```toml
# projects/example-subreddit-faq/project.toml
name = "subreddit-faq"
description = "Recurring questions and misconceptions in a single subreddit."

[scrape]
mode = "subreddit"
subreddit = "personalfinance"
sort = "top"
time_filter = "month"
post_limit = 30
comment_limit = 10

[analyze]
model = "qwen3:8b"
prompt_file = "prompt.md"
chunk_char_limit = 12000
ollama_timeout_seconds = 600
```

For research questions that span multiple communities, list them all:

```toml
# projects/missouri-cannabis/project.toml
name = "missouri-cannabis"
description = "Reception of Missouri's adult-use program across cannabis communities."

[scrape]
mode = "subreddit"
subreddits = ["MissouriMarijuana", "MOCannabis", "trees"]
sort = "top"
time_filter = "month"
post_limit = 25      # per subreddit (75 total here)
comment_limit = 10

[analyze]
model = "qwen3:8b"
prompt_file = "prompt.md"
chunk_char_limit = 12000
ollama_timeout_seconds = 600
```

`post_limit` is per-subreddit, matching search-mode's per-term semantics. The
combined run folder lives at `runs/missourimarijuana-mocannabis-trees/<ts>/`,
and each post in `normalized/posts.jsonl` carries its source community.

A search-mode project looks like this:

```toml
# projects/example-game-reception/project.toml
name = "game-reception"
description = "Compare how Reddit talks about a slate of video games."

[scrape]
mode = "search"
terms_file = "terms.txt"
subreddits_file = "subreddits.txt"
exact_phrase = true
sort = "top"
time_filter = "year"
post_limit = 15
comment_limit = 5

[analyze]
model = "qwen3:8b"
prompt_file = "prompt.md"
ollama_timeout_seconds = 600

[relevance]
keywords = ["review", "gameplay", "story", "performance", "bug", "patch", "worth"]
```

The repo ships four worked examples covering the most common shapes:

- [`projects/example-subreddit-faq/`](projects/example-subreddit-faq/) — what does this
  community keep asking? *(subreddit mode)*
- [`projects/example-game-reception/`](projects/example-game-reception/) — compare reception
  of multiple video games. *(search mode, comparative)*
- [`projects/example-tool-sentiment/`](projects/example-tool-sentiment/) — how do developers
  actually feel about a stack of frameworks? *(search mode, dev subs)*
- [`projects/example-product-research/`](projects/example-product-research/) — mine durability
  and "what to buy instead" patterns from review-heavy subs. *(search mode, focused)*

For more project shapes (public-figure sentiment, hobby starter packs, civic threads, trend
tracking, and more), see [`docs/ideas.md`](docs/ideas.md).

## CLI reference

```text
reddit-researcher init <name>             Scaffold a new projects/<name>/ folder.
reddit-researcher list                    Show projects and recent runs as a table.
reddit-researcher run <project>           Load project.toml and run scrape + extract.
reddit-researcher scrape <name> [<name>…]  One-off scrape of one or more subreddits (no project needed).
reddit-researcher search --terms-file=... One-off Reddit search across one or more terms.
reddit-researcher extract <run-dir>       Re-run analysis over an already-scraped run folder.
reddit-researcher review <run-dir>        Print a one-screen summary of a run's manifest.
```

Scaffold a new project in seconds:

```bash
reddit-researcher init my-research --mode subreddit --subreddit Programming
reddit-researcher init game-buzz --mode search --term "Hollow Knight Silksong" --term "GTA VI"
reddit-researcher init expert-mentions --mode search --template expert-mention
reddit-researcher init --list-templates
```

### Authenticated scraping (PRAW backend)

By default, Reddit Researcher reads Reddit's public JSON endpoints — no auth, no setup.
For higher rate limits, deeper comment trees, or listings beyond 1000 posts, you can
opt into the [PRAW](https://praw.readthedocs.io/) backend:

```bash
pip install -e ".[praw]"   # or: pip install reddit-researcher[praw]
```

Register a "script" app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps),
then put the credentials in a `.env` (or your shell environment):

```bash
# .env
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
```

Switch a project over by adding one line to its `project.toml`:

```toml
[scrape]
backend = "praw"   # default is "json"
```

Both backends expose the same scrape interface — the run folder layout and manifest
shape are identical.

### Environment variables and `.env`

Reddit Researcher reads these env vars (and a per-project `.env` file, if present):

| Variable | Purpose |
|---|---|
| `OLLAMA_URL` | Override the Ollama endpoint. Defaults to `http://127.0.0.1:11434`. |
| `OLLAMA_MODEL` | Default model when a project doesn't pin one. |
| `REDDIT_RESEARCHER_USER_AGENT` | Override the User-Agent sent to Reddit. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | PRAW credentials. Required when `[scrape].backend = "praw"`. |

Precedence (lowest to highest): code defaults → repo-root `.env` → project `.env` → shell environment → `project.toml` → CLI flags. Shell env vars are never overwritten by `.env` files.

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
