# Design: `reddit-researcher diff` (0.2.0)

A new top-level CLI subcommand that compares two run directories and surfaces
what changed between them. Reads from the SQLite/DuckDB sink shipped earlier
in 0.2.0; if either run isn't yet in the DB, it's synced on the fly. Output is
a compact text table by default, JSON with `--format json`.

## Goals

- Make "what changed between these two runs?" a one-liner instead of an
  ad-hoc grep / `wc -l` exercise.
- Pay back the SQLite/DuckDB sink: the diff becomes a few SQL queries against
  pre-indexed data.
- Stay friendly when the runs don't perfectly match: warn but still produce a
  useful diff.

## Non-goals

- Diffing analysis text (`analysis/final.md`). LLM output is non-deterministic;
  a unified diff between two runs would be mostly re-phrasing noise. If a user
  wants this, `diff -u` against the two files is one shell command.
- Per-post field-level diffs (score delta, num_comments delta, etc.). Useful
  for time-series, but inflates output and overlaps with the upcoming
  time-series milestone item. v1 stays at counts + set membership.
- Comment-by-comment diffs. We compare comment counts; listing every
  comment_id only-in-A would explode output for typical run sizes.

## CLI surface

```text
reddit-researcher diff <run-a> <run-b> [--project <path>] [--format text|json]
```

- `<run-a>`, `<run-b>` — two positional run-dir paths. Resolved to absolute,
  must exist and contain `manifest.json`.
- `--project` — same resolution as `db sync` / `db status` / `db query`.
  Defaults to `cwd/project.toml` if present. Drives which sink (which DB
  file) the diff reads from.
- `--format text|json` — default `text`. JSON emits the full `DiffResult`
  as a dict.

Exit codes:
- `0` — diff computed (even if mismatches were warned).
- `2` — bad input (missing run dir, missing manifest, project not resolvable).
- `1` — runtime error (sink open failure, sync failure, DB error).

## Module + data shape

```text
reddit_researcher/
  diff.py      # compute_diff(), DiffResult, RunSummary, format_text(), format_json()
```

`diff.py` exposes:

```python
@dataclass
class RunSummary:
    run_dir: Path
    mode: str
    scope: str
    project_name: str | None
    scraped_at_utc: str
    post_count: int
    comment_count: int

@dataclass
class DiffResult:
    a: RunSummary
    b: RunSummary
    posts_only_in_a: list[str]      # post_ids
    posts_only_in_b: list[str]
    posts_in_both: list[str]
    comments_only_in_a: int          # set diff on comment_id; counts only — listing ids would explode output
    comments_only_in_b: int
    comments_in_both: int             # comments whose comment_id appears in both runs
    relevance_changes: list[dict]    # {post_id, a_decision, b_decision} for posts in both with different decisions
    warnings: list[str]


def compute_diff(sink: RunSink, run_a: Path, run_b: Path) -> DiffResult:
    """Pure function: opens read-only conn, runs ~5 queries, returns the result."""
    ...

def format_text(result: DiffResult) -> str: ...
def format_json(result: DiffResult) -> str: ...
```

Splitting compute from format keeps the structured result independently
testable from the formatter, and lets future callers (a hypothetical
HTTP/JSON surface, programmatic Python use) reach into the same logic.

## Sync-on-the-fly logic (CLI handler)

1. Resolve both run dirs to absolute paths. `parser.error` if either is missing
   or lacks `manifest.json`.
2. Resolve project (default cwd, errored if absent — same pattern as
   `_dispatch_db`).
3. Open sink via `make_sink(project.storage, project_dir=project.project_dir)`.
4. For each run dir, check if it's already current in the sink:
   `SELECT synced_at_utc FROM runs WHERE run_dir = ?`. Sync via
   `sync_run(sink, run_dir)` if:
   - the row is absent, OR
   - the manifest has an `updated_at_utc` field that is lexicographically
     greater than the row's `synced_at_utc` (both are ISO 8601 with timezone,
     so string comparison is chronological).
   When the manifest has no `updated_at_utc` (legacy v0 manifests), trust
   the existing row.
5. Call `compute_diff(sink, run_a, run_b)`.
6. Print warnings to stderr (one per line, `warning: <text>`).
7. Print the formatted result to stdout.
8. Close sink.

## Mismatch warnings

`compute_diff` populates `result.warnings` when:

- `mode mismatch: A=<a-mode>, B=<b-mode>` — different scrape modes.
- `scope mismatch: A=<a-scope>, B=<b-scope>` — different subreddits/scopes;
  post_id overlap is likely zero.
- `project mismatch: A=<a-name>, B=<b-name>` — different `project_name`
  values (now meaningful since the I1 fix populates this column).

Warnings never block computation. The CLI prints them to stderr.

## Text format

Sized to fit one screen on typical 80-col terminals.

```text
=== Diff: A vs B ===

A: runs/AskReddit/20260507-120000  (subreddit, AskReddit, 2026-05-07T12:00Z)
   project=demo  posts=42  comments=180
B: runs/AskReddit/20260508-090000  (subreddit, AskReddit, 2026-05-08T09:00Z)
   project=demo  posts=51  comments=224

posts: A=42, B=51, only-in-A=8, only-in-B=17, in-both=34
comments: A=180, B=224, only-in-A=22, only-in-B=66, in-both=158
relevance changes (in-both posts whose decision flipped): 3

posts only in A (8):
  abc123, def456, ghi789, jkl012, mno345, pqr678, stu901, vwx234

posts only in B (17):
  yzA567, BCD890, EFG123, HIJ456, KLM789, NOP012, QRS345, TUV678
  WXY901, ZAB234, CDE567, FGH890, IJK123, LMN456, OPQ789, RST012
  ... (+1 more)

relevance changes:
  abc123  include -> exclude
  def456  review  -> include
  ghi789  exclude -> include
```

Caps:
- "posts only in A/B" lists capped at 20 items in text mode; remainder shown
  as `... (+N more)`.
- "relevance changes" lists all (typically small).
- JSON format always emits the full list.

## JSON format

`json.dumps(asdict(result), default=str, ensure_ascii=True)`. `Path`
serializes via `default=str`. All `DiffResult` fields present; lists are
unbounded.

## Error handling

- Missing run dir or missing `manifest.json` → `parser.error(...)` with rc=2.
- Sync failure → caught in CLI, `print(f"error: {exc}", file=sys.stderr)`,
  return 1.
- DB / connection failure → same as sync failure.
- Mismatched runs → warnings, never errors.

## Testing

New `tests/test_diff.py`:

1. `compute_diff` happy path — two synced runs, asserts post-id sets and
   comment counts.
2. `compute_diff` identical runs — `posts_only_in_a == posts_only_in_b == []`,
   no warnings.
3. `compute_diff` mode mismatch warning.
4. `compute_diff` scope mismatch warning.
5. `compute_diff` project mismatch warning.
6. `compute_diff` relevance flip — post `p1` is `include` in A, `exclude` in
   B; appears in `relevance_changes`.
7. `format_text` snapshot — includes counts header, "only in A" / "only in B"
   / "in both" sections, relevance changes.
8. `format_text` cap at 20 items with `... (+N more)` line.
9. `format_json` round-trips through `json.loads` to a dict with all fields.
10. CLI E2E via `cli_main(["diff", ...])` — both runs auto-sync, returns 0,
    stdout contains expected counts.
11. CLI errors cleanly (rc=2) on missing run dir.

## Documentation

- `docs/architecture.md` — short paragraph in the existing "Storage" section
  pointing at `diff` as a sink consumer.
- `README.md` — new "Comparing runs" subsection right after "Querying across
  runs".
- `CHANGELOG.md` — entry under `0.2.0-beta` describing the new subcommand.
- `docs/roadmap.md` — check the diff bullet under 0.2.0.

## Risks

- **Auto-sync delay.** If a large run isn't yet synced, `diff` will sync it
  before computing — could take seconds. Acceptable; the user invoked diff
  explicitly.
- **`posts_in_both` is unused in text output.** It's in `DiffResult` for JSON
  consumers and future formatters. Text format only shows the "only in"
  lists plus the count. Slight asymmetry; documented in code.
- **Read-only sink connection.** `compute_diff` uses `sink.read_only_connect()`,
  but the on-the-fly `sync_run` writes through the writer connection. Two
  connections to the same SQLite file, in sequence — no contention since
  there's one writer process.
