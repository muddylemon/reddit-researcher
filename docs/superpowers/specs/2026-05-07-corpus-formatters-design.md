# Design: configurable corpus formatters (0.2.0)

Three named formats — `compact`, `conversational`, `structured-json` — selected
by `[analyze].corpus_format` in `project.toml` and overridable per-run with
`--corpus-format`. `compact` remains the default and is byte-equivalent to
today's output, so existing projects produce identical corpora without any
config change.

## Goals

- Give users a knob to swap between human-friendly and machine-friendly corpus
  shapes without writing custom formatter code.
- Keep `compact` (today's default) byte-equivalent so existing prompts and
  snapshots aren't disturbed.
- Make adding a fourth format later a small change (one function per mode in
  `corpus_formatters.py` plus a literal added to `VALID_CORPUS_FORMATS`).

## Non-goals

- Pluggable user-supplied formatters. The set is closed; the three formats
  cover compact, prose, and structured needs.
- Per-format chunking strategies. The existing paragraph-boundary
  `chunk_text` works for all three formats because they all separate posts
  with blank lines.
- Changing `chunk_text` itself.

## Format shapes

### `compact` (default, current behavior)

Subreddit-mode:

```text
[POST abc123] r/AskReddit title: What's the best book you've read?
author: alice | score: 42 | comments: 18
flair: none
body: ...

[COMMENT def456] post=abc123 depth=0 score=5
body: ...
```

Search-mode adds `## Search term: <term>` headings grouping posts; comments
appear after each post (not flat).

Byte-equivalent to today's `build_corpus` and `build_search_corpus` output.

### `conversational`

Markdown headings + prose-style metadata. Subreddit-mode:

```text
## Post: What's the best book you've read?
*r/AskReddit — by alice — 42 points, 18 comments*

What's the best book you've read?

### Comment by bob (5 points)
I just finished...
```

Search-mode adds a top-level `# Search term: <term>` heading. Comments still
appear after their post.

### `structured-json`

One JSON object per post, separated by blank lines. NOT a wrapping array,
NOT strict JSONL. Blank-line separation lets the existing paragraph-based
`chunk_text` keep whole JSON objects together inside a chunk.

```text
{"id": "abc123", "subreddit": "AskReddit", "title": "...", "author": "alice",
 "score": 42, "body": "...",
 "comments": [{"id": "def", "author": "bob", "score": 5, "body": "..."}]}

{"id": "abc456", "subreddit": "news", "title": "...", ...}
```

Each post object includes:
- `id`, `subreddit`, `title`, `author`, `score`, `body`
- `search_term` (search-mode only — absent in subreddit-mode)
- `comments`: array of `{id, author, score, body}` objects (may be empty)

Consumers that want strict JSONL or a wrapping `{"posts": [...]}` array can
re-wrap. The corpus-as-emitted is intentionally chunker-friendly.

## Module + dispatch

```text
reddit_researcher/
  corpus_formatters.py    # NEW: 3 formatters per mode (6 functions) + dispatch + VALID_CORPUS_FORMATS
  prompting.py            # MODIFY: build_corpus + build_search_corpus thin wrappers around dispatch
  config.py               # MODIFY: AnalyzeConfig.corpus_format; import VALID_CORPUS_FORMATS for validation
  cli.py                  # MODIFY: --corpus-format flag on _add_analyze_overrides
  pipeline.py             # MODIFY: extract_from_run uses format_corpus(...) instead of direct calls
```

`corpus_formatters.py` exposes:

```python
VALID_CORPUS_FORMATS = {"compact", "conversational", "structured-json"}

def format_corpus(
    *,
    mode: str,                              # "subreddit" | "search"
    fmt: str,                               # one of VALID_CORPUS_FORMATS
    posts: list[dict],
    comments: list[dict] | None = None,    # subreddit-mode only
) -> str:
    """Dispatch to the appropriate (mode, fmt) formatter."""
```

Internally, six small functions:
- `_subreddit_compact(posts, comments)`
- `_subreddit_conversational(posts, comments)`
- `_subreddit_structured_json(posts, comments)`
- `_search_compact(posts)`
- `_search_conversational(posts)`
- `_search_structured_json(posts)`

`build_corpus(posts, comments)` and `build_search_corpus(posts)` in
`prompting.py` become thin wrappers calling
`format_corpus(mode=..., fmt="compact", ...)` to preserve the existing
public surface — anything (including tests) that imports them keeps working.

`extract_from_run` in `pipeline.py` reads `analyze.corpus_format` and calls
`format_corpus(mode=..., fmt=analyze.corpus_format, ...)` directly, bypassing
the back-compat wrappers.

## Config

`AnalyzeConfig` in `reddit_researcher/config.py` gains:

```python
@dataclass
class AnalyzeConfig:
    ...existing fields...
    corpus_format: str = "compact"
```

`load_project` imports `VALID_CORPUS_FORMATS` from `corpus_formatters.py` and
validates `analyze.corpus_format`:

```python
analyze_corpus_format = analyze_raw.get("corpus_format", "compact")
if analyze_corpus_format not in VALID_CORPUS_FORMATS:
    raise ProjectConfigError(
        f"invalid analyze.corpus_format: {analyze_corpus_format!r}. "
        f"Must be one of {sorted(VALID_CORPUS_FORMATS)}.",
        path=config_path,
    )
```

## CLI

`_add_analyze_overrides(parser)` gains:

```python
parser.add_argument(
    "--corpus-format",
    choices=sorted(VALID_CORPUS_FORMATS),
    default=None,
    help="Override [analyze].corpus_format for this run.",
)
```

`_apply_analyze_overrides(base, args)` threads `args.corpus_format` (when
non-None) onto the returned `AnalyzeConfig`.

## Pipeline

In `extract_from_run`, replace the existing two-branch dispatch:

```python
corpus = build_search_corpus(posts=posts) if is_search else build_corpus(posts=posts, comments=comments)
```

with:

```python
corpus = format_corpus(
    mode="search" if is_search else "subreddit",
    fmt=analyze.corpus_format,
    posts=posts,
    comments=None if is_search else comments,
)
```

## Testing

New `tests/test_corpus_formatters.py` covers, at minimum:

1. `_subreddit_compact` byte-equivalent to today's `build_corpus` (snapshot
   against fixed inputs).
2. `_search_compact` byte-equivalent to today's `build_search_corpus`.
3. `_subreddit_conversational` contains `## Post:`, `### Comment by`, and the
   score/comment-count line; no `[POST id]` markers.
4. `_search_conversational` adds `# Search term:` heading.
5. `_subreddit_structured_json` produces parseable JSON when split on `\n\n`;
   each object has documented keys; comments nested under posts; no
   `search_term` field.
6. `_search_structured_json` includes `search_term` field on each post.
7. `format_corpus` raises `ValueError` for unknown `fmt`.
8. Existing tests in `tests/test_prompting.py` for `build_corpus` and
   `build_search_corpus` continue to pass without modification (proves the
   compact wrappers preserve the byte-equivalence contract).

New `tests/test_config.py` additions:

9. `[analyze].corpus_format` parsed correctly when present.
10. `[analyze].corpus_format` defaults to `"compact"` when absent.
11. Invalid value rejected with `ProjectConfigError`.

New `tests/test_cli.py` (or `tests/test_run_project.py`) addition:

12. `--corpus-format conversational` thread through `_apply_analyze_overrides`
    onto the resulting `AnalyzeConfig`.

New pipeline integration check (extends `tests/test_extract.py` or similar):

13. `extract_from_run` with `analyze.corpus_format = "conversational"`
    produces a chunk prompt containing `## Post:` markers (mock the Ollama
    client; capture the prompt argument).

## Documentation

- `README.md` — new "Corpus formats" subsection (or short paragraph in the
  Usage section) showing the three options and a one-line example of each.
- `CHANGELOG.md` — entry under `0.2.0-beta`.
- `docs/roadmap.md` — check the corpus-formatters bullet.
- `docs/architecture.md` — short bullet in the prompting / extract section
  describing the formatter dispatch.

## Risks

- **Snapshot drift on `compact`.** The byte-equivalence guarantee depends on
  `_subreddit_compact` and `_search_compact` reproducing today's output
  exactly. Snapshot tests (items 1, 2 above) plus the unchanged existing
  `test_prompting.py` tests both protect this.
- **JSON chunking.** Each post is emitted as one JSON object via
  `json.dumps(...)`, which escapes newlines in body text as `\n` (literal
  backslash-n in the output). The serialized object therefore contains no
  actual `\n` characters, only the post-separator blank lines we emit
  between objects. `chunk_text` splits on `\n\n`, so chunk boundaries always
  fall cleanly between whole post objects.
- **Adding a fourth format later.** Requires a new function per mode plus
  appending to `VALID_CORPUS_FORMATS`. The dispatch in `format_corpus`
  uses an explicit if/elif on `fmt` so the path is obvious.
