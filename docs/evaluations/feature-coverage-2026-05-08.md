# Feature-coverage evaluation — 2026-05-08

End-to-end test of Reddit Researcher 0.2.1-beta against a single project,
`local-llm-pulse-2026`. Goal: exercise every shipped feature in the 0.0.x
through 0.2.x lines and record what worked, what surprised me, and what's
worth changing.

- **Branch:** `test/feature-coverage-2026-05-08`
- **CLI version:** 0.2.1-beta
- **Model:** `qwen3:8b` via local Ollama (`http://127.0.0.1:11434`)
- **Project:** `projects/local-llm-pulse-2026/` — multi-subreddit subreddit-mode
  across `r/LocalLLaMA`, `r/Ollama`, `r/LocalLLM`, asking "What's the pulse of
  the local-LLM community right now?"

The project was deliberately picked to be *meta* (using a tool that depends on
local LLMs to research the local-LLM community) and to exercise the 0.2.0
multi-subreddit feature with three communities of different sizes and tones.

## What was tested

| Area | Feature | Status | Notes |
|---|---|---|---|
| 0.0.x | `init`-equivalent project scaffold | ✅ | Authored by hand; `list` picks it up. |
| 0.0.x | `list` | ✅ | Renders projects + recent runs as a table. |
| 0.0.x | `review <run-dir>` | ✅ | One-screen summary, accurate counts. |
| 0.1.0 | `schema_version` manifest | ✅ | New runs write v2; per-sub block present. |
| 0.1.0 | Default JSON backend | ✅ | 24 posts + 191 comments, no auth. |
| 0.2.0 | Multi-subreddit subreddit mode | ✅ | Single combined run dir, per-sub counts. |
| 0.2.0 | SQLite sink + `db status` / `db query` | ✅ | Auto-synced run #1, queries return rows. |
| 0.2.0 | `corpus_format = compact` | ✅ | Run #1 baseline. |
| 0.2.0 | `corpus_format = conversational` | ✅ | Run #2 via `--corpus-format` override. |
| 0.2.0 | `diff <run-a> <run-b>` | ✅ | Empty diff (same posts), JSON output clean. |
| 0.2.1 | `series <project>` | ✅ | 2-run rollup, all 24 posts always-present. |
| Misc  | `extract` standalone | ✅ | Used to drive run #1 inference after a smoke scrape. |

## Run #1 — full pipeline, compact corpus

```text
Run:    runs/localllama-ollama-localllm/20260508-185937
Mode:   subreddit, 3 subs (LocalLLaMA, Ollama, LocalLLM)
Counts: 24 posts (8/sub), 191 comments
Chunks: 7 × qwen3:8b
Wall:   scrape 1m10s + extract 2m36s ≈ 3m46s end-to-end
```

`per_subreddit` block in the manifest is exactly what you want for a
multi-community run — independent counts and a per-sub status. The combined
run-dir slug `localllama-ollama-localllm` is readable and deterministic.

### Output quality (run #1)

The synthesized `analysis/final.md` follows the prompt's four-section
structure, cites post and comment IDs in brackets, and produces concrete
cross-community contrasts (e.g. *"LocalLLaMA users praise Qwen's agentic
coding ... while Ollama users criticize its inability to scale for enterprise
workflows"*). qwen3:8b held the structural discipline across all 7 chunks and
the final synthesis pass — no drift, no hallucinated post IDs that I could
spot-check.

A representative section:

> **Models in Rotation**
> - **Qwen3.6-35B-A3B** dominates as a clear winner, praised for its sparse MoE
>   architecture (35B total params, 3B active) and efficiency on consumer
>   hardware ... [POST 1sn3izh][COMMENT oginw31].

That's well-formed: claim → evidence → citation. The cost-control rule
(`Not relevant: ...` for chunks with no signal) was never triggered, which
makes sense given the topic and the source subs.

## Run #2 — conversational corpus, same project

Same project, same `--corpus-format conversational` override on the CLI. Five
minutes after run #1, so the "top of month" listing was effectively
identical: `diff` later confirmed all 24 posts are in both runs.

```text
Run:    runs/localllama-ollama-localllm/20260508-190418
Counts: 24 posts, 191 comments
Chunks: 6 × qwen3:8b   (one fewer than run #1, see note below)
Wall:   scrape 56s + extract 2m11s ≈ 3m07s
```

Note the chunk count dropped from 7 → 6 with the conversational format.
That's counterintuitive (conversational text is "wordier") but the format's
prose framing replaces some of compact's repeated `[POST id] r/sub title:`
markers with single headings, so the byte-per-post is comparable and packing
into 12000-char chunks shifted by one. Worth confirming with a deliberate
side-by-side sometime; for this run it didn't change anything material.

### A real quality regression: citations degraded

Run #1 (compact) produced citations like `[POST 1sn3izh][COMMENT oginw31]` —
the actual Reddit IDs the prompt requested. Run #2 (conversational) produced
citations like `[POST ResearchCrafty1804][COMMENT ttkciar]` — **author
handles in place of IDs**, across most claims in `final.md`.

Both runs received the same prompt, with the same instruction to cite
`[POST <id>]`. The only variable was the corpus format. The conversational
formatter places author names prominently in the prose framing for each
post, and qwen3:8b at this size mistook the most-prominent identifier-shaped
token for the post ID.

This is not a bug in the formatter itself — the format is doing what it
says. It's a *quality* finding: **conversational corpus + small models can
silently corrupt citation accuracy.** Two reasonable mitigations:

1. Have `corpus_format = "conversational"` keep an explicit `id: <id>` line
   alongside the heading, so an ID is the most-citation-shaped token in
   each post.
2. Add a one-liner to the relevant docstring / docs: "with smaller (≤8B)
   models, prefer `compact` for any prompt that asks for cited claims."

The full run #2 `final.md` is otherwise structurally fine — same four
sections, same cross-community contrasts — but the citations would not
survive a fact-check pass against the manifest.

## `db query` smoke

```text
$ reddit-researcher db query \
    "SELECT subreddit, COUNT(*) AS posts, AVG(score) AS avg_score
     FROM posts GROUP BY subreddit ORDER BY posts DESC" \
    --project projects/local-llm-pulse-2026

subreddit   posts  avg_score
----------  -----  ---------
LocalLLM    8      822.0
LocalLLaMA  8      2165.5
Ollama      8      613.125
```

The sink picked up run #1 automatically on first `db status`. `--format json`
also works and produces clean records (verified with a top-5-by-score query).
Confirms the "JSONL is canonical, sink is a derived view" model: deleting
`research.db` and re-running `db status` rebuilds it from disk.

## `diff` between runs #1 and #2

```text
posts: A=24, B=24, only-in-A=0, only-in-B=0, in-both=24
comments: A=191, B=191, only-in-A=0, only-in-B=0, in-both=191
relevance changes (in-both posts whose decision flipped): 0
```

The two runs were minutes apart, so the "top of month" listing hadn't moved
— a perfect input for verifying `diff`'s set-membership math without noise.
JSON output (`--format json`) is a single object with `posts_only_in_a`,
`posts_only_in_b`, `posts_in_both`, comment counts, and a `warnings` array
that was empty here. Easy to pipe into anything.

The behavior I expected (an empty diff for back-to-back runs) is exactly what
shipped. The more interesting test would be diffing across a longer interval,
where new posts should appear and stale ones drop — but the math is the same.

## `series` rollup

```text
$ reddit-researcher series projects/local-llm-pulse-2026
series report: 2 runs, 24 always-present, synced 0 new run(s);
written to runs/_series/local-llm-pulse-2026/20260508-190747
```

The generated `series.md` includes a per-run table (posts / comments /
relevant / new / carried), an "always-present" set of post IDs (all 24
here, since the listing didn't move), an empty churn block, and a
per-subreddit count matrix. No LLM call — pure stats from the sink. The
sink had already auto-synced both runs, so the rollup was effectively
instant.

For a project that's actually re-run on a schedule (the use case the
0.2.1 milestone was built for), the always-present + churn split is what
you want: a perpetually-present post is something the community keeps
boosting; churn posts are the time-sensitive ones.

## `db query` — cross-table join

The sink mirrors JSONL into `posts`, `comments`, `relevance_decisions`,
and `runs` tables. Composite primary keys are `(run_dir, post_id)` for
posts and `(run_dir, comment_id)` for comments, so cross-run analysis
just works:

```text
$ reddit-researcher db query \
    "SELECT p.subreddit, COUNT(c.comment_id) AS comments,
            AVG(LENGTH(c.body)) AS avg_body_len
     FROM posts p JOIN comments c
       ON p.post_id = c.post_id AND p.run_dir = c.run_dir
     WHERE p.run_dir LIKE '%20260508-190418%'
     GROUP BY p.subreddit" \
    --project projects/local-llm-pulse-2026

subreddit   comments  avg_body_len
----------  --------  ----------------
LocalLLM    64        238.48
LocalLLaMA  64        136.33
Ollama      63        241.62
```

A small surprise: `r/LocalLLaMA` comments are *shorter* on average than
the other two subs' comments. That tracks with what the LLM noticed in
the synthesis ("LocalLLaMA leans toward enthusiast-driven model
exploration and humor") — terse meme-style replies on big enthusiast
threads. Nice that the sink can corroborate a qualitative claim with a
quantitative one in a single SQL line.

## Findings worth fixing

### 0. Conversational corpus regresses citation accuracy with small models

Documented above under run #2. Single most consequential finding from this
session — silent quality degradation, no error message, no log line. Worth
either tweaking the formatter or adding a docs caveat.

### 1. `list` truncates the multi-sub label with a broken character

```text
local-llm-pulse-2026  subreddit  3 subs: r/LocalLLaMA, r/Ollama,�  qwen3:8b
```

The `…` ellipsis used to truncate long scope labels is being printed as a
replacement character (`�`) on Windows PowerShell. The output is
`cp1252`-encoded by default; the formatter should either use `...` (ASCII) for
truncation or pin the stream encoding to UTF-8 on Windows. Low severity —
purely cosmetic — but it's the first thing a Windows user sees from `list`.

### 2. `extract <run-dir>` requires `--prompt-file` even when the run came from a project

The run dir's manifest doesn't yet record `prompt_file`, so `extract` can't
discover it. Forcing the user to supply it again is fine for ad-hoc reruns,
but a *resumed* extract on a project-originated run-dir should be able to
pick the prompt back up. Two options:

- Persist `analysis.prompt_file` (and `chunk_char_limit`, `corpus_format`,
  `model`) on the manifest at scrape time. `extract` then defaults from the
  manifest if no flags are given.
- Or thread the project root through and have `extract` look for a sibling
  `project.toml` when invoked without a prompt.

Either is small. The first is more idiomatic given the run-dir-as-source-of-
truth design.

### 3. `projects/local-*/` gitignore namespace is easy to trip on

I named this project `local-llm-pulse-2026` — accidentally matching the
`projects/local-*/` rule in `.gitignore` that's intended to keep private
research folders out of version control. Surprise: the project folder I
wanted to commit alongside the eval was silently ignored, and `git status`
gave no hint until I asked `git check-ignore`.

Two cheap fixes:

- Document the `local-` namespace in `docs/ideas.md` (and possibly the
  `init` command's help text), so users learn it before they trip on it.
- Have `init` warn if the user passes a name starting with `local-`, since
  most people don't intend to opt out of git when they scaffold a project.

I worked around it with `git add -f` for this commit; renaming the project
would have orphaned the existing run directories' `project_name` metadata.

### 4. `db`, `diff`, and `series` all need `--project` from repo root

Same wording in all three:

```text
$ reddit-researcher diff <a> <b>
reddit-researcher: error: diff: pass --project <path> or run from a
                   directory containing project.toml.
```

This is correct behavior — these subcommands need a sink, and the sink
lives next to a `project.toml`. But the *first-time* surface for someone
running from the repo root is three commands in a row that error
identically until they figure out the flag. Two cheap improvements:

- The error could suggest a concrete path: detect that the supplied
  run-dirs sit under `runs/<scope>/...` and offer the most plausible
  project root inferred from `manifest.project_name`.
- Or: when `diff` / `series` get a run-dir argument whose manifest has
  `project_name`, use that to find the project root automatically.

Either way, today's "no, do it again with `--project`" is the most
friction in an otherwise smooth surface.

## What I didn't test

These features exist but were out-of-scope for a single-project run:

- **PRAW backend.** Default JSON backend already gave us full coverage on
  three midsize subs in under a minute. Nothing in this project needed
  authenticated quotas.
- **Search mode + `terms.txt` + `subreddits.txt` allowlist.** Subreddit-mode
  ran the full pipeline; search mode shares the same downstream stages
  (relevance, normalize, extract, sink) so coverage is high.
- **DuckDB engine.** SQLite path is the default and exercised here. DuckDB
  swap is a single config change and would only be worth re-running for a
  large-scale (millions-of-rows) workload.
- **`--start-term-index` / `--term-limit` / `--run-dir` resume.** Resume
  paths are search-mode-specific.
- **`structured-json` corpus format.** Picked the two human-readable formats
  for visual comparison; the JSON format is most useful when piping into
  downstream tools, which isn't this project's shape.

## Bottom line

For a beta release, the surface is remarkably stable. The features added in
the 0.2.x line (multi-sub mode, sink, diff, corpus formats, series) compose
cleanly: every feature I touched played well with every other one I touched,
and the run-dir layout stayed legible end-to-end. The three findings above
are all paper cuts, not architectural problems.
