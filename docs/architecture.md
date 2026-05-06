# Architecture

Reddit Researcher is a small pipeline. It does five things in order and writes everything to disk.

```text
+----------------+     +------------------+     +----------------+     +-------------+     +-----------+
| 1. Load        | --> | 2. Reddit JSON   | --> | 3. Normalize   | --> | 4. Relevance| --> | 5. Ollama |
|    project.toml|     |    fetch         |     |    + persist   |     |    review   |     |   extract |
+----------------+     +------------------+     +----------------+     +-------------+     +-----------+
                              |                          |                    |                  |
                              v                          v                    v                  v
                          raw/*.json              normalized/*.jsonl     review/*.jsonl     analysis/*.md
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `cli.py`           | Argparse front door. Translates flags into config dataclasses and dispatches to the pipeline. |
| `config.py`        | Loads and validates `project.toml`. Resolves relative paths against the project folder. |
| `reddit_client.py` | Reads Reddit's public JSON endpoints with retry + 429 handling. No auth. |
| `ollama_client.py` | Thin wrapper over Ollama's HTTP API. Surfaces missing models with the available list. |
| `pipeline.py`      | Orchestrates scrape → normalize → relevance → extract. Handles checkpointing. |
| `prompting.py`     | Loads prompt files, builds corpora, chunks long text, and assembles model prompts. |
| `relevance.py`     | Deterministic, configurable pre-LLM filter. Decides `include`, `review`, or `exclude`. |
| `storage.py`       | JSON, JSONL, and run-folder helpers. The output contract lives here. |
| `progress.py`      | Per-run logger that writes to `logs/scrape.log` and `logs/extract.log`. |
| `models.py`        | `PostRecord` and `CommentRecord` dataclasses. |

## Data contract

Every run writes the same shape:

```text
runs/<scope>/<timestamp>/
  manifest.json              run metadata
  raw/                       unmodified Reddit responses
  normalized/                clean rows for analysis
  review/                    relevance decisions
  analysis/                  LLM output
  logs/                      per-stage logs
```

This layout is intentionally flat and human-greppable. Forks should treat it as the public
interface — adding files is fine, renaming or restructuring is a breaking change.

## Invariants worth knowing

- **Scrapes are append-only.** A failed scrape does not delete prior progress; resuming into the
  same `--run-dir` re-uses everything in `normalized/`.
- **Extractions reuse chunks.** `analysis/chunks/chunk-NNN.md` is reused if non-empty unless
  `--force-reextract` is passed.
- **Relevance is cheap and deterministic.** It runs in-process with no network calls. The LLM only
  ever sees posts whose decision is `include` or `review`.
- **Search-mode corpora are grouped by `search_term`.** This lets a per-term prompt produce a
  per-term section in the synthesis.

## Why TOML for projects

- Built into the standard library on Python 3.11+ (`tomllib`). No new dependency.
- Easy to read, easy to diff. Comments are first-class.
- Strict typing avoids the YAML "Norway problem" and ambiguous numbers.

## Why Reddit's public JSON endpoint, not PRAW

- Zero-config: no `client_id`, `client_secret`, refresh tokens, or registered apps. A fork-it-and-go
  contract.
- The endpoint is sufficient for low-volume research. For higher volume or authenticated reads,
  see the roadmap — a PRAW backend is planned.

## Why Ollama, not a hosted LLM

- Local-first: data never leaves the machine, no API key handling, no per-token spend during
  iteration.
- Practical for prompt tuning: rerunning extraction over the same scrape is free.
- The `OllamaClient` API is intentionally narrow (`generate`, `list_models`). Swapping it for a
  different local backend is a one-file change.
