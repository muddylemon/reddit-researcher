# Design: time-series mode (0.2.0)

A new `reddit-researcher series <project>` subcommand reads from the existing
SQLite/DuckDB sink and writes a per-project trend rollup (Markdown + JSON)
into `runs/_series/<project_name>/<timestamp>/`. No scheduling primitive —
the user wires cron, launchd, Task Scheduler, or `at` to invoke `run` and
`series` on whatever cadence they want.

This is the smallest thing that delivers on "aggregate results across
timestamps" without violating the no-daemon non-goals in
[docs/roadmap.md](../../roadmap.md). It closes the last unchecked item in
the 0.2.0 milestone.

## Goals

- Make multi-run-over-time analysis a one-liner: `series <project>` emits
  a Markdown report and a machine-readable JSON twin.
- Reuse the sink that already exists. No new tables — just queries.
- Keep the artifact-on-disk pattern: timestamped, immutable, alongside
  `runs/`.
- Stats only. No LLM call. Deterministic, fast, free.

## Non-goals

- Scheduling, daemons, or cron-helper output. The user owns that. Aligns
  with the "no managed/cloud version" and "no server" entries in the
  roadmap's non-goals.
- Cross-project rollups. One project per report. (A user with multiple
  related projects can run `series` against each.)
- LLM-synthesized narrative summaries. Cost-control: the rest of the tool
  treats LLM calls as opt-in.
- Auto-emission on every `run`. Explicit invocation only.

## CLI surface

One new top-level subcommand, dispatched from
[reddit_researcher/cli.py](../../../reddit_researcher/cli.py):

```text
reddit-researcher series <project> [--output-root <path>]
                                   [--limit N]
                                   [--format md|json|both]
```

- `<project>` — path to a `project.toml` or a directory containing one.
  Resolved via the existing `find_project_config` helper. The project's
  `name` becomes the `project_name` key used for sink lookups.
- `--limit N` — only include the most recent N runs (ordered by
  `scraped_at_utc`). Default: all runs of this project that exist in
  the sink.
- `--format` — `md` (default), `json`, or `both`. `both` writes both
  `series.md` and `series.json` into the output directory.
- `--output-root` — override where `_series/` lives. Default: project's
  `output_root` (from `project.toml`) or `./runs` (the CLI default).

The handler auto-syncs anything missing from the sink first (same pattern
[`diff`](../../../reddit_researcher/diff.py) uses today), then computes
and writes.

Exit codes:

- `0` on success (any non-zero number of synced runs for the project).
- `2` if the project has zero synced runs, with a clear message:
  `no runs found for project '<name>'; run it at least once before generating a series report`.

## Output layout

```text
runs/
  _series/
    <project_name>/
      <timestamp>/
        series.md       # human-readable report
        series.json     # raw structured data (when --format=json|both)
```

`<timestamp>` follows the same `YYYYMMDD-HHMMSS` UTC format as run dirs.

`_series/` is collision-free with both subreddit-mode scope dirs and
search-mode combined scope dirs because Reddit subreddit names cannot
start with `_` (Reddit's naming rules), and the search-mode combined
scope is a slug derived from term+sub names.

## Report contents

`series.md` has these sections, in order:

### Header

```text
# Series: <project_name>
<run_count> runs from <first_scraped_utc> to <last_scraped_utc>
<warnings, if any>
```

### Run table

One row per run, chronological. Columns:

- `run` — `<timestamp>` (the leaf of the run dir)
- `mode` — `subreddit` or `search`
- `scope` — e.g. `AskReddit` or `mo-cannabis-combined`
- `posts` — `runs.post_count`
- `comments` — `runs.comment_count`
- `relevant` — count of `relevance_decisions` with `decision = 'include'`
- `new` — posts in this run not in the previous run (`-` for the first row)
- `carried` — posts in this run that were also in the previous run

### Persistence

Posts present in **every** synced run (the "always-trending" set):

```text
posts present in all <N> runs (<count>):
  <post_id>  <title (truncated to 80 chars)>
  ...
```

Capped at 50 entries with a `... (+M more)` line if needed.

If `<N>` is 1, this section reads `(only one run; persistence not applicable)`.

### Churn

Top 10 most-frequent post IDs that are *not* in every run (i.e., appeared
in N of M runs, where 1 ≤ N < M):

```text
posts appearing in some-but-not-all runs (top 10 by frequency):
  <post_id>  <run_count>/<total>  <title>
  ...
```

If there are no such posts, this section reads `(none — every post is either always-present or single-run)`.

### Subreddit / term breakdown

A small text matrix of post counts per subreddit (subreddit-mode) or
per search term (search-mode), one column per run:

```text
subreddit         20260505  20260506  20260507
MissouriMarijuana       12        14        18
trees                    8         9        11
MOCannabis               3         2         2
```

Capped at the top 20 rows by total across runs.

### Warnings

A bulleted list of warnings, when applicable:

- mode change between runs (`run X mode=subreddit, run Y mode=search`)
- scope change between runs (different `scope` value)

If no warnings, the section is omitted.

### `series.json`

Mirrors the same data as a single object — `compute_series`'s
`SeriesResult` serialized via `dataclasses.asdict` (matching the diff
module's pattern). Lets users post-process or feed the data into other
tools.

## Architecture

A new module `reddit_researcher/series.py` mirrors the shape of
[reddit_researcher/diff.py](../../../reddit_researcher/diff.py): pure read
against `RunSink.read_only_connect()`, dataclass result, separate text and
JSON formatters.

```python
# series.py
@dataclass
class RunRow:
    run_dir: Path
    timestamp: str               # leaf dir name, e.g. "20260507-120000"
    scraped_at_utc: str
    mode: str
    scope: str
    post_count: int
    comment_count: int
    relevant_count: int
    new_post_ids: list[str]      # vs. previous run (empty for first)
    carried_post_ids: list[str]  # intersection with previous run
    per_subreddit: dict[str, int]
    per_search_term: dict[str, int]

@dataclass
class SeriesResult:
    project_name: str
    runs: list[RunRow]                            # chronological
    always_present_post_ids: list[str]
    title_for: dict[str, str]                     # post_id -> latest title seen
    churn_top: list[tuple[str, int]]              # (post_id, run_count)
    warnings: list[str]                           # mode/scope changes mid-series

def compute_series(
    sink: RunSink, project_name: str, limit: int | None = None,
) -> SeriesResult: ...

def format_markdown(result: SeriesResult) -> str: ...
def format_json(result: SeriesResult) -> str: ...
```

### Key SQL queries (read-only)

- Runs in chronological order:

  ```sql
  SELECT run_dir, scraped_at_utc, mode, scope, post_count, comment_count
  FROM runs
  WHERE project_name = ?
  ORDER BY scraped_at_utc ASC
  ```

- Relevant counts per run:

  ```sql
  SELECT run_dir, COUNT(*)
  FROM relevance_decisions
  WHERE decision = 'include' AND run_dir IN (?, ?, ...)
  GROUP BY run_dir
  ```

- Per-run posts (one query per run for clarity — typical
  `post_count` is 25–75, so the chattiness is fine):

  ```sql
  SELECT post_id, title, subreddit, search_term
  FROM posts
  WHERE run_dir = ?
  ```

Set arithmetic for `new` / `carried` / `always_present` is pure Python over
those id sets — clearer than SQL gymnastics for these small cardinalities.

### CLI handler

A new `_handle_series(args, parser)` function in
[reddit_researcher/cli.py](../../../reddit_researcher/cli.py) that:

1. Resolves the project via `find_project_config` and `load_project`.
2. Loads the project's `[storage]` config and constructs a sink with
   `make_sink(project.storage, project.project_dir)`.
3. Auto-syncs: walks `output_root` for run dirs whose manifest's
   `project_name` (when present) matches `project.name` and aren't yet
   in the sink, or whose `runs.synced_at_utc` is older than the manifest's
   `updated_at_utc`. Calls `sync_run` for each.
4. Calls `compute_series(sink, project.name, args.limit)`.
5. Creates `runs/_series/<project_name>/<timestamp>/` (timestamp = current
   UTC at invocation, `YYYYMMDD-HHMMSS`).
6. Writes `series.md` and/or `series.json` per `--format`.
7. Prints the destination dir + a one-line summary to stdout
   (`series report: <N> runs, <K> always-present, written to <path>`).

The auto-sync step is factored as
`_sync_stale_for_project(sink, project_name, output_root) -> int` (returns
synced run count) and lives in `cli.py` for now. A later refactor can
move it into `db.py` if `diff` wants to share it.

### `runs.project_name` is the join key

The sink already records `project_name` on every run row, populated from
the run's manifest at sync time. `series` keys on it. There is no need to
add a new column or table.

If a run pre-dates the sink's `project_name` field (none today, but
defensive): `_sync_stale_for_project` re-syncs it, which writes the
current `project_name` derived from the manifest's `project.name` field.

### Timestamp format

`runs/_series/<project>/<timestamp>/` uses `YYYYMMDD-HHMMSS` UTC, matching
`runs/<scope>/<timestamp>/`. Implementation detail: either reuse the
existing pipeline timestamp helper or add a small `series._timestamp()` —
whichever is cleaner at the call site. The format is fixed.

## Edge cases

- **Zero runs for project**: exit 2, with the message in the CLI section.
- **Single run**: produce a report. Header + 1-row table. Persistence
  section reads `(only one run; persistence not applicable)`. Churn empty.
  Exit 0.
- **Mode changed mid-series** (`subreddit` → `search`): emit warning;
  per-run table still renders correctly because columns are mode-agnostic.
- **Scope changed mid-series**: warning; persistence/churn still works on
  raw `post_id` regardless of source community.
- **Heterogeneous-scope persistence**: a post that legitimately crosses
  subreddits (rare) is still "the same post" by `post_id` from Reddit's
  perspective. This is correct; documented in the `series.md` Persistence
  section comment.
- **`project_name` rename mid-series**: documented limitation. The user
  must either re-tag old runs (manually edit manifests + `db sync --rebuild`)
  or accept that the rename creates a new series. Not worth a flag in 0.2.x.
- **Concurrent `series` invocations**: extremely unlikely on a local CLI;
  the per-invocation timestamp dir is unique to the second.

## Testing

New `tests/test_series.py` covering, at minimum:

1. `compute_series` against a 3-run fixture: row counts, `new`/`carried`
   sets, always-present set, churn ranking, per-subreddit breakdown.
2. Single-run case: report builds, persistence/churn empty, no error.
3. Zero-run case: `compute_series` raises a clear error; CLI handler
   maps that to exit code 2.
4. Mode-change warning: 2 runs, one `subreddit` and one `search`,
   warning surfaced in `SeriesResult.warnings`.
5. Scope-change warning: subreddit-mode runs with different `subreddits`
   lists across runs.
6. `format_markdown` produces non-empty output with all expected section
   headings.
7. `format_json` round-trips through `json.loads` and matches `SeriesResult`
   field names.
8. CLI integration: `reddit-researcher series <project>` writes the
   expected files into `runs/_series/<project_name>/<timestamp>/` and
   prints the summary line.
9. `--limit N` truncates to the N most-recent runs.
10. `--format json` writes only `series.json`; `--format both` writes both.
11. Auto-sync: an existing-on-disk run dir not yet in the sink is picked
    up and included in the report.

DuckDB tests skip-if-not-installed, matching the pattern used in
`test_db.py` and `test_diff.py`. The existing 85% coverage gate must
continue to pass.

## Documentation

- New "Series rollups" subsection in [README.md](../../../README.md),
  immediately after "Comparing runs", showing one invocation and the
  output layout.
- New section in [docs/architecture.md](../../architecture.md) describing
  the series module: which sink queries it makes, the
  `project_name`-as-key assumption, and the `_series/` layout.
- CHANGELOG entry under a new `0.2.1-beta` (since `0.2.0-beta` is already
  cut and called out time-series as deferred). Bump
  [`reddit_researcher/__init__.py`](../../../reddit_researcher/__init__.py)
  `__version__` accordingly.
- Tick the time-series checkbox in [docs/roadmap.md](../../roadmap.md)
  with the `0.2.1` callout.

## Risks

- **`project_name` drift**: if the user renames a project mid-series,
  pre-rename runs won't show up. Mitigation: warning-only; documented in
  the Edge cases section. Not worth a `--also-named OLD,NEW` flag in 0.2.x.
- **Auto-sync surface area**: walking `output_root` and re-syncing stale
  runs is the same logic `db sync --all` already implements. The series
  command intentionally subsets that walk to one project. If `db sync`'s
  walker grows new options later, `series` should adopt them — left as a
  follow-up note rather than a refactor in this PR.
- **Single SQL connection**: `series` opens one read-only connection for
  the duration of the report. SQLite's `PRAGMA foreign_keys = ON` does
  not need to be re-asserted on read-only connections, so this is fine —
  documented next to the connection open call.
