---
name: tutorial
description: Use when the user wants a short getting-started walkthrough of reddit-researcher - runs `projects/example-subreddit-faq` end-to-end on a single chunk, then opens final.md and points at next steps. Invoke for "run the tutorial", "show me how this works", "walk me through reddit-researcher", or after `/setup` finishes.
---

# Reddit Researcher tutorial

A 3-minute getting-started walk-through that scrapes one shipped example, runs a
single LLM chunk against it, and opens the resulting report. Use this when the user
wants to see the tool work end-to-end before committing to anything.

## Pre-flight

Re-run the equivalent of `/setup` checks 3, 5, and 6 inline:

1. `.venv\Scripts\reddit-researcher.exe` exists. Use the PowerShell tool:
   `Test-Path ".venv\Scripts\reddit-researcher.exe"`. `True` = ✓; `False` = ✗.
   (Do NOT use the Read tool — .exe files are binary.)
2. `curl -sf http://127.0.0.1:11434/api/tags` returns 0 (use the Bash tool).
3. The response includes at least one model in `models[]`.

If any fail, tell the user:

> One of the prerequisites isn't ready — run `/setup` first, then come back to
> `/tutorial`.

**Do not** auto-invoke `/setup`. Stop after printing the message.

## Walkthrough

Five stages. After each command, wait for it to finish before continuing — no
parallelism, no piped chains.

### Stage 1 — Show the plan

Print this paragraph (paraphrase if needed, but keep it short):

> We're going to scrape ~30 posts from r/personalfinance with their top comments,
> then run the project's prompt over a single chunk of that corpus to produce a
> small FAQ. Total time ~3 minutes on `qwen3:8b`. The full run uses multiple
> chunks; we cap to one to keep this short.

No command yet — this is context-setting only.

### Stage 2 — Scrape

(filled in by Task 8)

### Stage 3 — Extract one chunk

(filled in by Task 8)

### Stage 4 — Read the output

(filled in by Task 9)

### Stage 5 — Next steps

(filled in by Task 9)

## Idempotency

(filled in by Task 9)

## Anti-patterns

(filled in by Task 9)
