# Contributing to Reddit Researcher

Thanks for your interest. This is a small, local-first tool. PRs that keep it small are easiest to merge.

## Ground rules

- **Stay local-first.** No required cloud APIs, hosted LLMs, paid services, or telemetry.
- **Keep dependencies thin.** `requests` for HTTP, `pytest` for tests, `tomllib` from the stdlib.
  New runtime deps need a clear justification.
- **Prefer composable primitives.** A new feature should usually be a function in the existing
  modules, not a new abstraction layer.
- **Don't break run folders.** The `runs/<scope>/<timestamp>/` layout is part of the public
  contract — additions are fine, renames need a deprecation note.
- **Write a test.** Even a tiny one. The test suite is fast on purpose.

## Dev setup

```bash
python -m venv .venv
source .venv/bin/activate     # or .venv\Scripts\Activate.ps1 on Windows
pip install -e ".[dev]"
pytest
```

If you're working on or testing the PRAW backend, also install the optional extra:

```bash
pip install -e ".[dev,praw]"
```

The PRAW tests use stubbed `praw.Reddit` objects and run cleanly without the real
`praw` package, so most contributors don't need the extra installed.

## Running the tool against your changes

```bash
reddit-researcher --version
reddit-researcher run projects/example-subreddit-faq --skip-extract
```

Use `--skip-extract` while iterating on scraping logic so you don't burn LLM time.

## Style

- Type-hinted Python, `from __future__ import annotations` at the top of new modules.
- Avoid module-level globals beyond constants.
- Match the existing brevity in docstrings: one sentence, then the why.
- Don't add comments that explain obvious code.

## Filing issues

Helpful issues include:

- The exact command you ran.
- The contents of `manifest.json` from the affected run folder (sanitize as needed).
- The Python and Ollama versions.
- The model tag in use.

## Adding a new project example

If you have a high-quality, broadly-applicable project, drop it under `projects/example-<name>/`
with a clean `project.toml` and `prompt.md`. Keep prompts subject-agnostic where possible — these
are meant to be templates, not finished research artifacts.
