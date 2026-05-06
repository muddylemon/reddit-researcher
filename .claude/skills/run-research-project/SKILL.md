---
name: run-research-project
description: Use when the user asks to run, execute, or kick off a Reddit research project in this repo. Handles staged execution (small scrape first, then full extract), checking Ollama is available, and surfacing the manifest and final report at the end. Invoke for "run the X project", "scrape r/Y and analyze it", or any request to execute reddit-researcher against a project folder.
---

# Running a Reddit research project

Use this skill to execute a project in this repo end-to-end. The goal is to fail fast on cheap
problems (missing model, broken project.toml) before spending minutes on a full scrape.

## Pre-flight checks

Before invoking `reddit-researcher`, confirm:

1. **The project folder exists** and contains `project.toml`. Glob `projects/*/project.toml` if
   the user gave a vague name.
2. **Ollama is reachable** at the URL in the project (default `http://127.0.0.1:11434`). A quick
   `curl http://127.0.0.1:11434/api/tags` works.
3. **The model in `[analyze].model` is pulled.** If `ollama list` doesn't show it, run
   `ollama pull <model>` first.
4. **The user-agent in `[scrape].user_agent` looks reasonable** (not the literal default in a public
   fork — Reddit may rate-limit aggressively).

If any check fails, tell the user before running.

## Recommended execution order

Don't run everything at once on a fresh project. Use this ladder:

### Step 1 — Tiny scrape, no extract

```bash
reddit-researcher run projects/<name> --skip-extract --term-limit 1
```

(Drop `--term-limit` for subreddit-mode projects.)

This shakes out:
- Bad search terms.
- Subreddit names that don't exist.
- An overly aggressive relevance filter that excludes everything.

Read `runs/<scope>/<ts>/manifest.json` and `review/relevance_review.jsonl` before continuing.

### Step 2 — Single-chunk extract

```bash
reddit-researcher extract runs/<scope>/<ts> \
  --prompt-file projects/<name>/prompt.md \
  --chunk-limit 1 --force-reextract
```

Checks the prompt actually does something useful on real data. `--force-reextract` overwrites any
previous chunk output.

### Step 3 — Full run

```bash
reddit-researcher run projects/<name>
```

Or, if you already have a partial scrape, resume into it:

```bash
reddit-researcher run projects/<name> --run-dir runs/<scope>/<ts>
```

## After it finishes

Always surface these to the user:

- The final report path: `runs/<scope>/<ts>/analysis/final.md`.
- The manifest summary: post count, comment count, error counts.
- A short summary of what `final.md` says (read it and report 3–5 bullet points).

If the manifest reports any `search_fetch_errors` or `comment_fetch_errors`, mention them
explicitly — partial runs are easy to miss.

## Common failure modes

- **`Ollama returned 404 for model 'X'`** — the user hasn't pulled it. Suggest `ollama pull X`.
- **Empty `final.md` saying "No relevant posts selected for analysis."** — the relevance filter
  rejected everything. Loosen `[relevance].keywords`, broaden subreddits, or set
  `require_exact_term_match = false`.
- **HTTP 429 errors in the log** — Reddit is rate-limiting. Increase `pause_seconds` in the
  project.toml (try 2–3) and resume into the same run dir.
- **Hours-long runs that produce nothing useful** — the prompt is the problem 90% of the time.
  Use the `design-research-project` skill to revise it.
