---
name: design-research-project
description: Use when the user wants to start a new Reddit research job in this repo - creates a projects/<name>/ folder with a project.toml, prompt.md, and any term/subreddit lists they need. Invoke for "new research project", "design a reddit study", "set up a project for X", or when the user describes a research question that maps to scraping Reddit.
---

# Designing a Reddit research project

Use this skill when the user wants to start a new piece of Reddit research that will run through
this repo's pipeline. The output is a self-contained `projects/<name>/` folder.

## What you're producing

A folder under `projects/` containing:

- `project.toml` — required. Scrape mode, model, prompt path.
- `prompt.md` — required. The instruction the LLM will follow.
- `terms.txt` — required for `mode = "search"`. One search term per line.
- `subreddits.txt` — optional allowlist for search mode.

Refer to the shipped examples for canonical layouts:

- `projects/example-subreddit-faq/` — subreddit mode (community FAQ mining).
- `projects/example-game-reception/` — search mode, comparative sentiment.
- `projects/example-tool-sentiment/` — search mode, dev-tool comparisons.
- `projects/example-product-research/` — search mode, review-heavy subs.

If the user's question doesn't fit any of those shapes, check `docs/ideas.md` for more
templates before designing from scratch.

## Workflow

### 1. Pin down the research question

Before writing any files, get clear on:

- **The question.** "What recurring questions about X come up?" "How do redditors talk about Y?"
  "Who mentions person Z and in what context?"
- **The scope.** One subreddit? A list of search terms? A list of terms restricted to certain subs?
- **The shape of the output.** Bullet list? Per-term sections? A ranked theme list? This becomes the
  `prompt.md`.

If any of these are vague, ask the user before generating files. A focused prompt is worth more
than another scrape pass.

### 2. Pick a scrape mode

| Mode         | When to use                                                      |
|--------------|------------------------------------------------------------------|
| `subreddit`  | One community, broad survey of recent activity.                  |
| `search`     | Specific terms, names, or phrases — possibly across many subs.   |

For search mode, decide:

- Use `exact_phrase = true` for names and multi-word phrases. Disable only for genuinely broad searches.
- Provide a `subreddits.txt` allowlist when the topic is niche; this dramatically improves signal.
- Keep `post_limit` low (5–15) for first runs; you can resume into the same `--run-dir` later.

### 3. Write `prompt.md` deliberately

A good prompt does three things:

1. States the task in one paragraph.
2. Tells the model how to structure the output (headings, ordering, citations).
3. Includes a cost-control rule if you expect many irrelevant chunks (e.g., "If the chunk has no
   meaningful evidence for the topic, write one sentence beginning `Not relevant:` and stop.").

Always tell the model to cite post/comment ids in brackets when claiming something. The corpus
includes them as `[POST <id>]` and `[COMMENT <id>]`.

### 4. Configure relevance (optional but useful)

For search-mode projects, add a `[relevance]` table with 3–10 keywords that any meaningfully-relevant
post is likely to contain. This runs *before* the LLM and saves tokens. Keep the list tight — one
overly-broad keyword neutralizes the filter.

```toml
[relevance]
keywords = ["interview", "podcast", "study"]
```

You can also pin an `allowed_subreddits` list here if you want stricter filtering than the
search-time `subreddits.txt`.

### 5. Test on a tiny slice before committing

After writing the project, suggest the user verify with:

```bash
# Subreddit mode: cap the post count via the project.toml or override.
reddit-researcher run projects/<name> --skip-extract

# Search mode: process a single term first.
reddit-researcher run projects/<name> --term-limit 1 --skip-extract
```

Then have them check `runs/.../normalized/posts.jsonl` (or `relevant_posts.jsonl` if the relevance
filter is on) before turning extraction on.

## Anti-patterns

- **Don't use `mode = "subreddit"` for a topic spread across communities.** That's what search mode
  is for.
- **Don't write a 30-line prompt.** Long prompts dilute the model's attention. Keep it under ~200 words.
- **Don't add "be thorough" or "cite everything" without specifying *what* counts as evidence.** Models
  comply by padding output. Be concrete.
- **Don't skip the relevance keywords on a wide search run.** You will spend hours of inference on
  spam, ads, and unrelated communities.
