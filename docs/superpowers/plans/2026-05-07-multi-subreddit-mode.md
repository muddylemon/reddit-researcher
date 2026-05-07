# Multi-subreddit subreddit-mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a single subreddit-mode run scrape multiple subreddits into one combined run folder, with per-sub observability in the manifest, while keeping single-sub semantics byte-equivalent to today.

**Architecture:** Refactor `scrape_subreddit` to take `subreddits: list[str]` (single-sub becomes a list of one). The current per-post inner loop is unchanged; an outer loop iterates over subs. `posts.jsonl` stays a single combined file with each row tagged by its API-returned `subreddit`. Manifest gains `subreddits: [...]` and a `per_subreddit` map. Schema version 1 → 2; old runs read forward via a small normalization helper.

**Tech stack:** Python 3.11+, stdlib `tomllib`, `argparse`, `pathlib`, `json`. Tests with `pytest` and `monkeypatch`. No new runtime dependencies.

**Spec:** [docs/superpowers/specs/2026-05-07-multi-subreddit-mode-design.md](../specs/2026-05-07-multi-subreddit-mode-design.md)

---

## Task 1: Add `multi_subreddit_scope` helper to storage

**Files:**
- Modify: [reddit_researcher/storage.py](../../../reddit_researcher/storage.py)
- Test: [tests/test_storage.py](../../../tests/test_storage.py)

This is an additive helper. No existing code calls it yet — Task 4 wires it in.

- [ ] **Step 1: Write failing tests for `multi_subreddit_scope`**

Append to `tests/test_storage.py`:

```python
from reddit_researcher.storage import multi_subreddit_scope


def test_multi_subreddit_scope_single_sub_passthrough() -> None:
    assert multi_subreddit_scope(["personalfinance"]) == "personalfinance"


def test_multi_subreddit_scope_lowercases_and_joins() -> None:
    assert multi_subreddit_scope(["Cannabis", "Marijuana", "Drugs"]) == "cannabis-marijuana-drugs"


def test_multi_subreddit_scope_truncates_with_plus_suffix() -> None:
    subs = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    result = multi_subreddit_scope(subs, max_chars=30)
    assert len(result) <= 30
    assert result.endswith(("+1", "+2", "+3", "+4", "+5", "+6", "+7", "+8", "+9", "+10", "+11"))
    assert result.startswith("alpha")


def test_multi_subreddit_scope_no_truncation_when_under_limit() -> None:
    assert multi_subreddit_scope(["a", "b", "c"], max_chars=60) == "a-b-c"


def test_multi_subreddit_scope_empty_list_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="at least one"):
        multi_subreddit_scope([])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v -k multi_subreddit_scope`
Expected: FAIL with `ImportError: cannot import name 'multi_subreddit_scope'`.

- [ ] **Step 3: Implement `multi_subreddit_scope` in `reddit_researcher/storage.py`**

Append to the bottom of `reddit_researcher/storage.py`:

```python
def multi_subreddit_scope(subreddits: list[str], *, max_chars: int = 60) -> str:
    """Build the run-dir scope segment for one or many subreddits.

    For a single sub, returns the name unchanged (preserves today's run-dir
    naming). For multiple subs, lowercases and joins with '-', truncating
    to `max_chars` by dropping trailing entries and appending `+K`.
    """
    if not subreddits:
        raise ValueError("multi_subreddit_scope requires at least one subreddit")

    if len(subreddits) == 1:
        return subreddits[0]

    lowered = [sub.lower() for sub in subreddits]
    joined = "-".join(lowered)
    if len(joined) <= max_chars:
        return joined

    # Drop trailing entries until the remainder + "+K" suffix fits.
    kept = list(lowered)
    dropped = 0
    while kept:
        suffix = f"+{dropped}" if dropped else ""
        candidate = "-".join(kept) + suffix
        if len(candidate) <= max_chars:
            return candidate
        kept.pop()
        dropped += 1

    # Pathological: even the first sub plus suffix exceeds max_chars.
    # Fall back to a hard truncation of the first sub.
    return lowered[0][:max_chars]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests, including the four new ones).

- [ ] **Step 5: Commit**

```bash
git add reddit_researcher/storage.py tests/test_storage.py
git commit -m "feat: add multi_subreddit_scope helper for run-dir naming"
```

---

## Task 2: Manifest reader normalization + schema bump 1 → 2

**Files:**
- Modify: [reddit_researcher/manifest.py](../../../reddit_researcher/manifest.py)
- Test: [tests/test_manifest.py](../../../tests/test_manifest.py)

Adds `normalize_manifest(manifest)` that synthesizes `subreddits` and `per_subreddit` from older manifests, and bumps `MANIFEST_SCHEMA_VERSION` to 2. Existing read sites (`extract_from_run`, `views.summarize_run`, `views.list_runs`) are migrated in this task to call the normalizer.

- [ ] **Step 1: Write failing tests for `normalize_manifest`**

Append to `tests/test_manifest.py`:

```python
from reddit_researcher.manifest import normalize_manifest


def test_normalize_v1_subreddit_run_synthesizes_subreddits_list() -> None:
    raw = {
        "schema_version": 1,
        "mode": "subreddit",
        "subreddit": "cannabis",
        "post_count": 25,
        "comment_count": 140,
        "status": "complete",
    }
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["cannabis"]
    assert normalized["per_subreddit"] == {
        "cannabis": {"post_count": 25, "comment_count": 140, "status": "complete"},
    }
    # Original fields preserved.
    assert normalized["subreddit"] == "cannabis"
    assert normalized["mode"] == "subreddit"


def test_normalize_v0_subreddit_run_with_missing_schema_version() -> None:
    raw = {"mode": "subreddit", "subreddit": "x", "post_count": 1, "comment_count": 0}
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["x"]
    assert "x" in normalized["per_subreddit"]


def test_normalize_v2_multi_sub_passthrough() -> None:
    raw = {
        "schema_version": 2,
        "mode": "subreddit",
        "subreddits": ["a", "b"],
        "per_subreddit": {
            "a": {"post_count": 5, "comment_count": 10, "status": "complete"},
            "b": {"post_count": 7, "comment_count": 12, "status": "complete"},
        },
        "post_count": 12,
        "comment_count": 22,
    }
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["a", "b"]
    assert normalized["per_subreddit"]["b"]["post_count"] == 7


def test_normalize_search_mode_untouched() -> None:
    raw = {"schema_version": 1, "mode": "search", "subreddits": ["fitness"]}
    normalized = normalize_manifest(raw)
    # subreddits in search mode is the allowlist, not a multi-sub list — leave alone.
    assert normalized["subreddits"] == ["fitness"]
    assert "per_subreddit" not in normalized
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manifest.py -v -k normalize`
Expected: FAIL with `ImportError: cannot import name 'normalize_manifest'`.

- [ ] **Step 3: Bump schema version and add `normalize_manifest`**

Edit [reddit_researcher/manifest.py](../../../reddit_researcher/manifest.py):

Change `MANIFEST_SCHEMA_VERSION = 1` to `MANIFEST_SCHEMA_VERSION = 2`.

Append below `read_schema_version`:

```python
def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the manifest with subreddit-mode fields normalized.

    Older subreddit-mode manifests carried only `subreddit` (string). The
    multi-subreddit feature added `subreddits` (list) and `per_subreddit`
    (per-sub counters). To let the rest of the codebase assume one shape,
    this synthesizes both fields from the legacy form.

    Search-mode manifests (where `subreddits` is the search allowlist) are
    returned unchanged.
    """
    result = dict(manifest)
    if result.get("mode") != "subreddit":
        return result

    if "subreddits" not in result and "subreddit" in result:
        result["subreddits"] = [result["subreddit"]]

    if "per_subreddit" not in result:
        subs = result.get("subreddits") or ([result["subreddit"]] if "subreddit" in result else [])
        if subs:
            # For legacy single-sub runs, attribute all counters to the one sub.
            single = subs[0] if len(subs) == 1 else None
            result["per_subreddit"] = {
                sub: {
                    "post_count": result.get("post_count", 0) if sub == single else 0,
                    "comment_count": result.get("comment_count", 0) if sub == single else 0,
                    "status": result.get("status", "unknown") if sub == single else "unknown",
                }
                for sub in subs
            }
    return result
```

- [ ] **Step 4: Run manifest tests**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Migrate existing manifest read sites to use the normalizer**

Edit [reddit_researcher/pipeline.py](../../../reddit_researcher/pipeline.py) line ~384 (inside `extract_from_run`):

```python
from .manifest import normalize_manifest, stamp as stamp_manifest
```

Replace:

```python
    manifest_path = run_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
```

with:

```python
    manifest_path = run_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
```

Edit [reddit_researcher/views.py](../../../reddit_researcher/views.py):

Add to imports:

```python
from .manifest import MANIFEST_SCHEMA_VERSION, normalize_manifest, read_schema_version
```

In `list_runs`, replace:

```python
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {"status": "broken-manifest"}
```

with:

```python
            try:
                manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                manifest = {"status": "broken-manifest"}
```

In `summarize_run`, replace:

```python
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"Manifest is unreadable ({manifest_path}): {exc}\n"
```

with:

```python
    try:
        manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return f"Manifest is unreadable ({manifest_path}): {exc}\n"
```

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: PASS for all existing tests. The bump from `MANIFEST_SCHEMA_VERSION = 1` to `2` will be picked up automatically by `test_subreddit_resume.py`'s assertion (it compares against the constant, not the literal `1`).

- [ ] **Step 7: Commit**

```bash
git add reddit_researcher/manifest.py reddit_researcher/pipeline.py reddit_researcher/views.py tests/test_manifest.py
git commit -m "feat: normalize_manifest + schema_version bump 1 -> 2"
```

---

## Task 3: ScrapeConfig — replace `subreddit` with `subreddits`

**Files:**
- Modify: [reddit_researcher/config.py](../../../reddit_researcher/config.py)
- Modify: [reddit_researcher/views.py](../../../reddit_researcher/views.py) (one read site)
- Modify: [tests/test_config.py](../../../tests/test_config.py)
- Modify: [tests/test_subreddit_resume.py](../../../tests/test_subreddit_resume.py) (constructor calls)

This task changes `ScrapeConfig.subreddit: str | None` → `ScrapeConfig.subreddits: list[str]`. The TOML accepts either `subreddit = "x"` or `subreddits = [...]` and normalizes. Pipeline signature is **not yet** changed — this task adds a temporary shim in `pipeline.run_project` that passes `subreddits[0]` until Task 4 refactors `scrape_subreddit`.

- [ ] **Step 1: Update `tests/test_config.py` — add new validation tests, adjust existing assertion**

Replace the existing `test_load_subreddit_project` body (lines ~14–43) so it asserts the new field:

```python
def test_load_subreddit_project(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        name = "demo"
        description = "demo project"

        [scrape]
        mode = "subreddit"
        subreddit = "Supplements"
        sort = "top"
        time_filter = "month"
        post_limit = 5
        comment_limit = 2

        [analyze]
        model = "qwen3:8b"
        prompt_file = "prompt.md"
        """,
    )
    (tmp_path / "prompt.md").write_text("Find questions.\n", encoding="utf-8")

    project = load_project(config_path)

    assert project.name == "demo"
    assert project.scrape.mode == "subreddit"
    assert project.scrape.subreddits == ["Supplements"]
    assert project.scrape.post_limit == 5
```

Replace the body of `test_subreddit_mode_requires_subreddit` (lines ~94–103) so the error message check accepts either field name:

```python
def test_subreddit_mode_requires_subreddit(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        """,
    )
    with pytest.raises(ValueError, match="requires scrape.subreddit"):
        load_project(config_path)
```

(The error message will mention both `subreddit` and `subreddits` — the regex `"requires scrape.subreddit"` matches both.)

Append new tests at the bottom of `tests/test_config.py`:

```python
def test_subreddits_plural_only(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        subreddits = ["cannabis", "marijuana", "drugs"]
        """,
    )
    project = load_project(config_path)
    assert project.scrape.subreddits == ["cannabis", "marijuana", "drugs"]


def test_subreddit_and_subreddits_both_set_rejected(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        subreddit = "x"
        subreddits = ["y", "z"]
        """,
    )
    with pytest.raises(ValueError, match="not both"):
        load_project(config_path)


def test_subreddits_empty_list_rejected(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        subreddits = []
        """,
    )
    with pytest.raises(ValueError, match="requires scrape.subreddit"):
        load_project(config_path)


def test_subreddits_dedup_case_insensitive(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        subreddits = ["Cannabis", "cannabis", "Drugs", "DRUGS", "Marijuana"]
        """,
    )
    project = load_project(config_path)
    assert project.scrape.subreddits == ["Cannabis", "Drugs", "Marijuana"]


def test_subreddits_invalid_entry_rejected(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        subreddits = ["valid", "has whitespace"]
        """,
    )
    with pytest.raises(ValueError, match="invalid subreddit name"):
        load_project(config_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'ScrapeConfig' object has no attribute 'subreddits'` and similar.

- [ ] **Step 3: Update `ScrapeConfig` and `load_project` in `reddit_researcher/config.py`**

In `ScrapeConfig` (lines ~43–58), remove `subreddit: str | None = None` and replace with `subreddits: list[str] = field(default_factory=list)`. The dataclass should look like:

```python
@dataclass
class ScrapeConfig:
    mode: str = "subreddit"
    backend: str = "json"
    subreddits: list[str] = field(default_factory=list)
    terms_file: Path | None = None
    subreddits_file: Path | None = None
    exact_phrase: bool = True
    sort: str = "top"
    time_filter: str = "month"
    post_limit: int = 25
    comment_limit: int = 10
    pause_seconds: float = 1.0
    max_retries: int = 5
    user_agent: str = field(default_factory=_default_user_agent)
```

In `load_project`, replace the block that reads `subreddit` (lines ~149–169) with normalization logic. After the existing `backend` validation, add:

```python
    raw_singular = scrape_raw.get("subreddit")
    raw_plural = scrape_raw.get("subreddits")
    if raw_singular is not None and raw_plural is not None:
        raise ProjectConfigError(
            "scrape.subreddit and scrape.subreddits cannot both be set; choose one (not both).",
            path=config_path,
        )

    subreddits_list: list[str] = []
    if raw_plural is not None:
        if not isinstance(raw_plural, list):
            raise ProjectConfigError(
                "scrape.subreddits must be a list of subreddit names.",
                path=config_path,
            )
        seen_lower: set[str] = set()
        for item in raw_plural:
            if not isinstance(item, str) or not item.strip() or "/" in item or any(ch.isspace() for ch in item):
                raise ProjectConfigError(
                    f"invalid subreddit name in scrape.subreddits: {item!r}",
                    path=config_path,
                )
            lowered = item.casefold()
            if lowered in seen_lower:
                continue
            seen_lower.add(lowered)
            subreddits_list.append(item)
    elif raw_singular is not None:
        if not isinstance(raw_singular, str) or not raw_singular.strip() or "/" in raw_singular or any(ch.isspace() for ch in raw_singular):
            raise ProjectConfigError(
                f"invalid subreddit name in scrape.subreddit: {raw_singular!r}",
                path=config_path,
            )
        subreddits_list = [raw_singular]
```

Then update the `ScrapeConfig(...)` instantiation to remove `subreddit=...` and add `subreddits=subreddits_list`:

```python
    scrape = ScrapeConfig(
        mode=mode,
        backend=backend,
        subreddits=subreddits_list,
        terms_file=_resolve_path(scrape_raw.get("terms_file"), base_dir),
        subreddits_file=_resolve_path(scrape_raw.get("subreddits_file"), base_dir),
        exact_phrase=bool(scrape_raw.get("exact_phrase", True)),
        sort=sort,
        time_filter=time_filter,
        post_limit=int(scrape_raw.get("post_limit", 25)),
        comment_limit=int(scrape_raw.get("comment_limit", 10)),
        pause_seconds=float(scrape_raw.get("pause_seconds", 1.0)),
        max_retries=int(scrape_raw.get("max_retries", 5)),
        user_agent=scrape_raw.get("user_agent", _default_user_agent()),
    )
```

Replace the `if mode == "subreddit" and not scrape.subreddit:` check with:

```python
    if mode == "subreddit" and not scrape.subreddits:
        raise ProjectConfigError(
            "scrape.mode='subreddit' requires scrape.subreddit (or scrape.subreddits) to be set.",
            path=config_path,
        )
```

- [ ] **Step 4: Update `views.py` to use new field**

Edit [reddit_researcher/views.py](../../../reddit_researcher/views.py) line ~58–64. Replace:

```python
        if project.scrape.mode == "subreddit":
            scope = f"r/{project.scrape.subreddit}"
        else:
```

with:

```python
        if project.scrape.mode == "subreddit":
            subs = project.scrape.subreddits
            scope = f"r/{subs[0]}" if len(subs) == 1 else f"{len(subs)} subs: " + ", ".join(f"r/{s}" for s in subs)
        else:
```

Also at line ~139:

```python
        scope = f"r/{manifest.get('subreddit', '?')}"
```

becomes:

```python
        subs = manifest.get("subreddits") or ([manifest["subreddit"]] if manifest.get("subreddit") else [])
        if not subs:
            scope = "r/?"
        elif len(subs) == 1:
            scope = f"r/{subs[0]}"
        else:
            scope = f"{len(subs)} subs (" + ", ".join(f"r/{s}" for s in subs) + ")"
```

- [ ] **Step 5: Add a temporary shim in `pipeline.run_project`**

Edit [reddit_researcher/pipeline.py](../../../reddit_researcher/pipeline.py) line ~480. Replace:

```python
    if project.scrape.mode == "subreddit":
        scrape_dir = scrape_subreddit(
            subreddit=project.scrape.subreddit or "",
            output_root=output_root,
            scrape=project.scrape,
            relevance=project.relevance,
            run_dir=run_dir,
        )
```

with (temporary — Task 4 will replace `subreddit=` with `subreddits=`):

```python
    if project.scrape.mode == "subreddit":
        scrape_dir = scrape_subreddit(
            subreddit=project.scrape.subreddits[0],
            output_root=output_root,
            scrape=project.scrape,
            relevance=project.relevance,
            run_dir=run_dir,
        )
```

- [ ] **Step 6: Update test_subreddit_resume.py to use `subreddits=`**

Edit [tests/test_subreddit_resume.py](../../../tests/test_subreddit_resume.py). Replace every occurrence of `ScrapeConfig(mode="subreddit", subreddit="testsub", ...)` with `ScrapeConfig(mode="subreddit", subreddits=["testsub"], ...)`. The `pipeline.scrape_subreddit(subreddit="testsub", ...)` call sites stay unchanged (Task 4 changes those).

Three occurrences of `ScrapeConfig(...)` to update — at lines 83, 101, 111.

- [ ] **Step 7: Run full test suite**

Run: `pytest -v`
Expected: PASS (all tests).

- [ ] **Step 8: Commit**

```bash
git add reddit_researcher/config.py reddit_researcher/views.py reddit_researcher/pipeline.py tests/test_config.py tests/test_subreddit_resume.py
git commit -m "refactor: replace ScrapeConfig.subreddit with subreddits list"
```

---

## Task 4: Refactor `scrape_subreddit` to take a list, write per-sub manifest

**Files:**
- Modify: [reddit_researcher/pipeline.py](../../../reddit_researcher/pipeline.py) (function signature + outer loop + manifest)
- Modify: [reddit_researcher/cli.py](../../../reddit_researcher/cli.py) (call site update; see Step 6)
- Modify: [tests/test_subreddit_resume.py](../../../tests/test_subreddit_resume.py)
- Create: [tests/test_multi_subreddit.py](../../../tests/test_multi_subreddit.py)

This task changes the function signature from `subreddit: str` to `subreddits: list[str]`, adds the outer loop, writes the new manifest fields, and uses `multi_subreddit_scope` for run-dir naming.

- [ ] **Step 1: Write a failing single-sub regression test**

Append to [tests/test_subreddit_resume.py](../../../tests/test_subreddit_resume.py) (it already has the stub client and helpers we need):

```python
def test_subreddit_scrape_writes_per_subreddit_manifest_section(monkeypatch, tmp_path: Path) -> None:
    posts = [_make_post("p1"), _make_post("p2")]
    comments = {"p1": [_make_comment("c1", "p1")], "p2": [_make_comment("c2", "p2")]}
    _patch_client(monkeypatch, posts, comments)

    run_dir = pipeline.scrape_subreddit(
        subreddits=["testsub"],
        output_root=tmp_path,
        scrape=ScrapeConfig(mode="subreddit", subreddits=["testsub"], post_limit=2, comment_limit=2),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["subreddits"] == ["testsub"]
    assert manifest["subreddit"] == "testsub"  # populated only for len-1
    assert manifest["per_subreddit"]["testsub"]["post_count"] == 2
    assert manifest["per_subreddit"]["testsub"]["comment_count"] == 2
    assert manifest["per_subreddit"]["testsub"]["status"] == "complete"
```

- [ ] **Step 2: Write a failing multi-sub scrape test**

Create [tests/test_multi_subreddit.py](../../../tests/test_multi_subreddit.py):

```python
"""Tests for multi-subreddit subreddit-mode scraping."""

from __future__ import annotations

import json
from pathlib import Path

from reddit_researcher import pipeline
from reddit_researcher.config import ScrapeConfig
from reddit_researcher.models import CommentRecord, PostRecord


def _make_post(post_id: str, subreddit: str) -> PostRecord:
    return PostRecord(
        id=post_id,
        subreddit=subreddit,
        title=f"title for {post_id}",
        author="someone",
        selftext="body",
        url=f"https://reddit.com/r/{subreddit}/comments/{post_id}/",
        permalink=f"/r/{subreddit}/comments/{post_id}/",
        score=10,
        upvote_ratio=0.9,
        num_comments=1,
        created_utc=0.0,
        over_18=False,
        is_self=True,
        link_flair_text=None,
        sort="top",
        time_filter="month",
    )


def _make_comment(comment_id: str, post_id: str) -> CommentRecord:
    return CommentRecord(
        id=comment_id,
        post_id=post_id,
        parent_id=None,
        author="someone",
        body="comment body",
        score=1,
        created_utc=0.0,
        permalink=f"/c/{comment_id}/",
        depth=0,
    )


class _MultiSubStubClient:
    """Stub that returns per-sub posts and supports controlled fetch failures."""

    def __init__(
        self,
        posts_by_sub: dict[str, list[PostRecord]],
        comments_by_post: dict[str, list[CommentRecord]],
        fetch_errors: dict[str, str] | None = None,
    ) -> None:
        self._posts = posts_by_sub
        self._comments = comments_by_post
        self._errors = fetch_errors or {}

    def fetch_posts(self, subreddit, sort, limit, time_filter):  # noqa: ARG002
        if subreddit in self._errors:
            raise RuntimeError(self._errors[subreddit])
        return list(self._posts.get(subreddit, [])), {"subreddit": subreddit, "sort": sort, "pages": []}

    def fetch_comments(self, permalink, post_id, limit):  # noqa: ARG002
        return list(self._comments.get(post_id, [])), {"post_id": post_id, "fake": True}


def _patch_client(monkeypatch, client) -> None:
    monkeypatch.setattr(pipeline, "make_reddit_client", lambda _scrape: client)


def test_multi_sub_scrape_combines_posts_into_one_run_dir(monkeypatch, tmp_path: Path) -> None:
    posts_by_sub = {
        "cannabis": [_make_post("a1", "cannabis"), _make_post("a2", "cannabis")],
        "marijuana": [_make_post("b1", "marijuana")],
    }
    comments = {pid: [_make_comment(f"c-{pid}", pid)] for pid in ("a1", "a2", "b1")}
    _patch_client(monkeypatch, _MultiSubStubClient(posts_by_sub, comments))

    run_dir = pipeline.scrape_subreddit(
        subreddits=["cannabis", "marijuana"],
        output_root=tmp_path,
        scrape=ScrapeConfig(
            mode="subreddit",
            subreddits=["cannabis", "marijuana"],
            post_limit=5,
            comment_limit=1,
        ),
    )

    # Run dir uses the joined slug.
    assert run_dir.parent.name == "cannabis-marijuana"

    posts_path = run_dir / "normalized" / "posts.jsonl"
    rows = [json.loads(line) for line in posts_path.read_text(encoding="utf-8").splitlines() if line]
    assert sorted(row["id"] for row in rows) == ["a1", "a2", "b1"]
    assert {row["subreddit"] for row in rows} == {"cannabis", "marijuana"}

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["subreddits"] == ["cannabis", "marijuana"]
    assert "subreddit" not in manifest  # omitted for multi-sub
    assert manifest["per_subreddit"]["cannabis"]["post_count"] == 2
    assert manifest["per_subreddit"]["marijuana"]["post_count"] == 1
    assert manifest["per_subreddit"]["cannabis"]["status"] == "complete"
    assert manifest["per_subreddit"]["marijuana"]["status"] == "complete"
    assert manifest["status"] == "complete"
    assert manifest["post_count"] == 3


def test_multi_sub_scrape_isolates_fetch_failure(monkeypatch, tmp_path: Path) -> None:
    posts_by_sub = {
        "cannabis": [_make_post("a1", "cannabis")],
        "marijuana": [],  # never reached because fetch fails
        "drugs": [_make_post("c1", "drugs")],
    }
    comments = {pid: [_make_comment(f"c-{pid}", pid)] for pid in ("a1", "c1")}
    errors = {"marijuana": "HTTP 503 from listing endpoint"}
    _patch_client(monkeypatch, _MultiSubStubClient(posts_by_sub, comments, errors))

    run_dir = pipeline.scrape_subreddit(
        subreddits=["cannabis", "marijuana", "drugs"],
        output_root=tmp_path,
        scrape=ScrapeConfig(
            mode="subreddit",
            subreddits=["cannabis", "marijuana", "drugs"],
            post_limit=5,
            comment_limit=1,
        ),
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["per_subreddit"]["cannabis"]["status"] == "complete"
    assert manifest["per_subreddit"]["marijuana"]["status"] == "fetch_error"
    assert "503" in manifest["per_subreddit"]["marijuana"]["error"]
    assert manifest["per_subreddit"]["drugs"]["status"] == "complete"
    # Other subs still produced posts.
    assert manifest["post_count"] == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_multi_subreddit.py tests/test_subreddit_resume.py -v`
Expected: FAIL — `TypeError: scrape_subreddit() got an unexpected keyword argument 'subreddits'` (multi tests) and `KeyError: 'per_subreddit'` (regression test).

- [ ] **Step 4: Refactor `scrape_subreddit` in `reddit_researcher/pipeline.py`**

Replace the entire `scrape_subreddit` function body with:

```python
def scrape_subreddit(
    *,
    subreddits: list[str],
    output_root: Path,
    scrape: ScrapeConfig,
    relevance: RelevanceConfig | None = None,
    run_dir: Path | None = None,
) -> Path:
    """Scrape one or more subreddits' listings into a single run dir.

    Single-sub semantics are unchanged from earlier versions. With multiple
    subs, the outer loop iterates each sub in order; per-sub status is tracked
    in `manifest["per_subreddit"]`. Posts already carry the API-returned
    `subreddit` field, so the combined `posts.jsonl` is naturally tagged.

    If `run_dir` is supplied and already exists, the scrape resumes into that
    folder: posts already written to `normalized/posts.jsonl` are skipped, and
    new posts are appended.
    """
    from .storage import multi_subreddit_scope

    if not subreddits:
        raise ValueError("scrape_subreddit requires at least one subreddit")

    if run_dir is None:
        run_dir = create_run_dir(output_root=output_root, scope=multi_subreddit_scope(subreddits))
    else:
        (run_dir / "raw" / "comments").mkdir(parents=True, exist_ok=True)
        (run_dir / "normalized").mkdir(parents=True, exist_ok=True)
        (run_dir / "analysis" / "chunks").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "review").mkdir(parents=True, exist_ok=True)

    logger = RunLogger(run_dir)
    client = make_reddit_client(scrape)

    posts_path = run_dir / "normalized" / "posts.jsonl"
    comments_path = run_dir / "normalized" / "comments.jsonl"
    relevant_posts_path = run_dir / "normalized" / "relevant_posts.jsonl"
    review_path = run_dir / "review" / "relevance_review.jsonl"
    for path in (posts_path, comments_path, relevant_posts_path, review_path):
        if not path.exists():
            write_text(path, "")

    processed_post_ids = {row.get("id") for row in read_jsonl(posts_path) if row.get("id")}
    all_post_count = len(processed_post_ids)
    all_comment_count = sum(1 for _ in read_jsonl(comments_path)) if comments_path.stat().st_size > 0 else 0

    # Recompute per-sub counts from the on-disk JSONL on resume.
    per_sub: dict[str, dict] = {sub: {"post_count": 0, "comment_count": 0, "status": "pending"} for sub in subreddits}
    for row in read_jsonl(posts_path):
        sub = row.get("subreddit")
        if sub in per_sub:
            per_sub[sub]["post_count"] += 1
    for row in read_jsonl(comments_path):
        # Comments don't carry subreddit directly — attribute via post_id lookup is overkill;
        # we recompute per-sub comment counts after each successful sub instead.
        pass

    raw_payloads_by_sub: dict[str, object] = {}

    manifest: dict = {
        "mode": "subreddit",
        "status": "starting",
        "subreddits": list(subreddits),
        "sort": scrape.sort,
        "time_filter": scrape.time_filter,
        "post_limit": scrape.post_limit,
        "comment_limit": scrape.comment_limit,
        "pause_seconds": scrape.pause_seconds,
        "max_retries": scrape.max_retries,
        "scraped_at_utc": datetime.now(UTC).isoformat(),
        "post_count": all_post_count,
        "comment_count": all_comment_count,
        "per_subreddit": per_sub,
    }
    if len(subreddits) == 1:
        manifest["subreddit"] = subreddits[0]

    def checkpoint(status: str) -> None:
        manifest["status"] = status
        manifest["updated_at_utc"] = datetime.now(UTC).isoformat()
        manifest["post_count"] = all_post_count
        manifest["comment_count"] = all_comment_count
        manifest["per_subreddit"] = per_sub
        write_json(run_dir / "manifest.json", stamp_manifest(manifest))

    checkpoint("starting")
    logger.info(f"Starting subreddit scrape {subreddits} into {run_dir}")

    for sub in subreddits:
        per_sub[sub]["status"] = "fetching"
        checkpoint("fetching_comments")

        try:
            posts, raw_posts = client.fetch_posts(
                subreddit=sub,
                sort=scrape.sort,
                limit=scrape.post_limit,
                time_filter=scrape.time_filter,
            )
            raw_payloads_by_sub[sub] = raw_posts
        except RuntimeError as exc:
            per_sub[sub]["status"] = "fetch_error"
            per_sub[sub]["error"] = str(exc)
            logger.info(f"r/{sub} listing fetch failed: {exc}")
            write_json(run_dir / "raw" / "posts.json", raw_payloads_by_sub)
            checkpoint("fetching_comments")
            continue

        new_posts = [post for post in posts if post.id not in processed_post_ids]
        if len(new_posts) < len(posts):
            logger.info(
                f"r/{sub}: resuming, {len(posts) - len(new_posts)} of {len(posts)} posts already in posts.jsonl"
            )

        for index, post in enumerate(new_posts, start=1):
            logger.info(f"r/{sub} comment fetch {index}/{len(new_posts)}: {post.id}")
            comments, raw_comments = client.fetch_comments(
                permalink=post.permalink,
                post_id=post.id,
                limit=scrape.comment_limit,
            )
            post.comments = comments
            write_json(run_dir / "raw" / "comments" / f"{post.id}.json", raw_comments)
            post_payload = post.to_dict()
            append_jsonl(posts_path, post_payload)
            for comment in comments:
                append_jsonl(comments_path, comment.to_dict())
            if relevance is not None:
                review = review_post_relevance(post_payload, relevance)
                append_jsonl(review_path, review)
                if review["decision"] in {"include", "review"}:
                    append_jsonl(relevant_posts_path, post_payload)
            all_post_count += 1
            all_comment_count += len(comments)
            per_sub[sub]["post_count"] += 1
            per_sub[sub]["comment_count"] += len(comments)
            processed_post_ids.add(post.id)
            checkpoint("fetching_comments")

        per_sub[sub]["status"] = "complete"
        write_json(run_dir / "raw" / "posts.json", raw_payloads_by_sub)
        checkpoint("fetching_comments")

    checkpoint("complete")
    logger.info(f"Completed subreddit scrape: {all_post_count} posts, {all_comment_count} comments")
    return run_dir
```

- [ ] **Step 5: Update `pipeline.run_project` to pass the list**

Replace the temporary shim from Task 3 (line ~480) with:

```python
    if project.scrape.mode == "subreddit":
        scrape_dir = scrape_subreddit(
            subreddits=project.scrape.subreddits,
            output_root=output_root,
            scrape=project.scrape,
            relevance=project.relevance,
            run_dir=run_dir,
        )
```

- [ ] **Step 6: Update `cli.py` `scrape` subcommand call site**

Edit [reddit_researcher/cli.py](../../../reddit_researcher/cli.py) line ~268. Replace:

```python
    if args.command == "scrape":
        scrape_cfg = _scrape_config_from_args(args)
        run_dir = scrape_subreddit(
            subreddit=args.subreddit,
            output_root=Path(args.output_root),
            scrape=scrape_cfg,
        )
        print(run_dir)
        return 0
```

with:

```python
    if args.command == "scrape":
        scrape_cfg = _scrape_config_from_args(args)
        # args.subreddit is still a string here — Task 8 widens the CLI to nargs="+".
        run_dir = scrape_subreddit(
            subreddits=[args.subreddit],
            output_root=Path(args.output_root),
            scrape=scrape_cfg,
        )
        print(run_dir)
        return 0
```

- [ ] **Step 7: Update existing `test_subreddit_resume.py` to use new signature**

Replace the three `pipeline.scrape_subreddit(subreddit="testsub", ...)` calls with `pipeline.scrape_subreddit(subreddits=["testsub"], ...)`. Three occurrences at lines ~80, 98, 108.

- [ ] **Step 8: Run full test suite**

Run: `pytest -v`
Expected: PASS for all tests, including the new multi-sub tests, regression test, and resume test.

- [ ] **Step 9: Commit**

```bash
git add reddit_researcher/pipeline.py reddit_researcher/cli.py tests/test_subreddit_resume.py tests/test_multi_subreddit.py
git commit -m "feat: scrape_subreddit accepts a list, writes per_subreddit manifest"
```

---

## Task 5: `scope_label_for` accepts `subreddits` list

**Files:**
- Modify: [reddit_researcher/prompting.py](../../../reddit_researcher/prompting.py)
- Modify: [tests/test_prompting.py](../../../tests/test_prompting.py)

Done before Task 6 so the `extract_from_run` change in Task 6 can call the new signature without leaving the suite red between commits.

- [ ] **Step 1: Write failing tests for the new branches**

Append to [tests/test_prompting.py](../../../tests/test_prompting.py):

```python
def test_scope_label_for_single_sub_via_list() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["Supplements"]) == "r/Supplements"


def test_scope_label_for_two_subs_uses_and() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["a", "b"]) == "r/a and r/b"


def test_scope_label_for_three_subs_oxford_comma() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["a", "b", "c"]) == "r/a, r/b, r/c"


def test_scope_label_for_many_subs_truncates() -> None:
    subs = ["a", "b", "c", "d", "e", "f", "g"]
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=subs) == "r/a, r/b, r/c, and 4 others"


def test_scope_label_for_legacy_subreddit_arg_still_works() -> None:
    # Existing call sites pass `subreddit` only; behavior must be unchanged.
    assert scope_label_for(subreddit="Supplements", search_terms=None) == "r/Supplements"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompting.py -v -k scope_label`
Expected: FAIL — `TypeError: scope_label_for() got an unexpected keyword argument 'subreddits'`.

- [ ] **Step 3: Update `scope_label_for` signature and logic**

Edit [reddit_researcher/prompting.py](../../../reddit_researcher/prompting.py) lines ~164–172. Replace:

```python
def scope_label_for(subreddit: str | None, search_terms: list[str] | None) -> str:
    """Produce a human-readable label for the run's data scope."""
    if search_terms:
        if subreddit:
            return f"a Reddit search across r/{subreddit}"
        return "a global Reddit search"
    if subreddit:
        return f"r/{subreddit}"
    return "Reddit"
```

with:

```python
def scope_label_for(
    subreddit: str | None,
    search_terms: list[str] | None,
    subreddits: list[str] | None = None,
) -> str:
    """Produce a human-readable label for the run's data scope.

    Accepts either a single `subreddit` (legacy callers) or a `subreddits`
    list (multi-sub mode). Search-mode takes precedence when `search_terms`
    is truthy.
    """
    if search_terms:
        if subreddit:
            return f"a Reddit search across r/{subreddit}"
        return "a global Reddit search"

    if subreddits:
        if len(subreddits) == 1:
            return f"r/{subreddits[0]}"
        if len(subreddits) == 2:
            return f"r/{subreddits[0]} and r/{subreddits[1]}"
        if len(subreddits) <= 5:
            return ", ".join(f"r/{s}" for s in subreddits)
        head = ", ".join(f"r/{s}" for s in subreddits[:3])
        return f"{head}, and {len(subreddits) - 3} others"

    if subreddit:
        return f"r/{subreddit}"
    return "Reddit"
```

- [ ] **Step 4: Run prompting tests**

Run: `pytest tests/test_prompting.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite (Task 5's `extract_from_run` change should now work)**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/prompting.py tests/test_prompting.py
git commit -m "feat: scope_label_for accepts subreddits list"
```

---

## Task 7: `build_corpus` prefixes posts with `r/<subreddit>`

**Files:**
- Modify: [reddit_researcher/prompting.py](../../../reddit_researcher/prompting.py) (`build_corpus`)
- Modify: [tests/test_prompting.py](../../../tests/test_prompting.py)

This is a small additive change — the post header line gets `r/<sub>` between `[POST <id>]` and `title:`, matching what `build_search_corpus` already does. Single-sub runs see the same prefix; it's just informative.

- [ ] **Step 1: Update existing test for new prefix and add a multi-sub test**

Edit `test_build_corpus_includes_posts_and_comments` in [tests/test_prompting.py](../../../tests/test_prompting.py) lines ~22–46:

```python
def test_build_corpus_includes_posts_and_comments() -> None:
    corpus = build_corpus(
        posts=[
            {
                "id": "post1",
                "subreddit": "Supplements",
                "title": "Question about magnesium",
                "author": "alice",
                "score": 12,
                "num_comments": 3,
                "link_flair_text": "Question",
                "selftext": "Does this help sleep?",
            }
        ],
        comments=[
            {
                "id": "comment1",
                "post_id": "post1",
                "depth": 0,
                "score": 5,
                "body": "I had the same question.",
            }
        ],
    )
    assert "[POST post1] r/Supplements" in corpus
    assert "[COMMENT comment1]" in corpus


def test_build_corpus_handles_posts_without_subreddit() -> None:
    corpus = build_corpus(
        posts=[{"id": "p", "title": "t", "author": "a", "score": 0, "num_comments": 0}],
        comments=[],
    )
    # Missing subreddit falls back to "unknown" (mirrors build_search_corpus behavior).
    assert "[POST p] r/unknown" in corpus
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_prompting.py::test_build_corpus_includes_posts_and_comments tests/test_prompting.py::test_build_corpus_handles_posts_without_subreddit -v`
Expected: FAIL — assertion `[POST post1] r/Supplements in corpus` does not match (current corpus says only `[POST post1] title: ...`).

- [ ] **Step 3: Update `build_corpus` to prefix `r/<sub>` on the post header**

Edit `build_corpus` in [reddit_researcher/prompting.py](../../../reddit_researcher/prompting.py) lines ~28–52. Replace:

```python
def build_corpus(posts: list[dict], comments: list[dict]) -> str:
    """Build a text corpus for subreddit-mode runs (posts + flat comments)."""
    lines: list[str] = []

    for post in posts:
        lines.extend(
            [
                f"[POST {post['id']}] title: {post['title']}",
                f"author: {post.get('author') or 'unknown'} | score: {post.get('score', 0)} | comments: {post.get('num_comments', 0)}",
                f"flair: {post.get('link_flair_text') or 'none'}",
            ]
        )
```

with:

```python
def build_corpus(posts: list[dict], comments: list[dict]) -> str:
    """Build a text corpus for subreddit-mode runs (posts + flat comments).

    Prefixes each post header with `r/<subreddit>` so the LLM has the source
    community on every line — matters when the run combines multiple subs.
    """
    lines: list[str] = []

    for post in posts:
        subreddit = post.get("subreddit") or "unknown"
        lines.extend(
            [
                f"[POST {post['id']}] r/{subreddit} title: {post['title']}",
                f"author: {post.get('author') or 'unknown'} | score: {post.get('score', 0)} | comments: {post.get('num_comments', 0)}",
                f"flair: {post.get('link_flair_text') or 'none'}",
            ]
        )
```

- [ ] **Step 4: Run prompting tests**

Run: `pytest tests/test_prompting.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/prompting.py tests/test_prompting.py
git commit -m "feat: build_corpus prefixes post header with r/<subreddit>"
```

---

## Task 8: CLI `scrape` subcommand accepts multiple subreddits

**Files:**
- Modify: [reddit_researcher/cli.py](../../../reddit_researcher/cli.py)
- Modify: [tests/test_cli.py](../../../tests/test_cli.py)

- [ ] **Step 1: Add a failing CLI test**

Look at [tests/test_cli.py](../../../tests/test_cli.py) to find the existing pattern — it likely uses `build_parser()` and asserts on parsed args. If the existing test_cli.py doesn't have a `scrape`-positional test, add one.

Append to [tests/test_cli.py](../../../tests/test_cli.py):

```python
def test_scrape_subcommand_accepts_multiple_subreddits() -> None:
    from reddit_researcher.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["scrape", "cannabis", "marijuana", "drugs"])
    assert args.command == "scrape"
    assert args.subreddit == ["cannabis", "marijuana", "drugs"]


def test_scrape_subcommand_accepts_single_subreddit() -> None:
    from reddit_researcher.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["scrape", "personalfinance"])
    assert args.subreddit == ["personalfinance"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_cli.py -v -k scrape_subcommand`
Expected: FAIL — `args.subreddit` is a string `"cannabis"`, not a list.

- [ ] **Step 3: Widen the `scrape` positional to `nargs="+"`**

Edit [reddit_researcher/cli.py](../../../reddit_researcher/cli.py) line ~67:

```python
    scrape_parser.add_argument("subreddit", help="Subreddit name without the r/ prefix.")
```

becomes:

```python
    scrape_parser.add_argument(
        "subreddit",
        nargs="+",
        help="One or more subreddit names without the r/ prefix.",
    )
```

- [ ] **Step 4: Update the `scrape` dispatch to pass the list directly**

Edit [reddit_researcher/cli.py](../../../reddit_researcher/cli.py) line ~268. Replace the Task 4 call:

```python
    if args.command == "scrape":
        scrape_cfg = _scrape_config_from_args(args)
        run_dir = scrape_subreddit(
            subreddits=[args.subreddit],
            output_root=Path(args.output_root),
            scrape=scrape_cfg,
        )
        print(run_dir)
        return 0
```

with:

```python
    if args.command == "scrape":
        scrape_cfg = _scrape_config_from_args(args)
        run_dir = scrape_subreddit(
            subreddits=list(args.subreddit),
            output_root=Path(args.output_root),
            scrape=scrape_cfg,
        )
        print(run_dir)
        return 0
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add reddit_researcher/cli.py tests/test_cli.py
git commit -m "feat: 'scrape' CLI accepts multiple subreddits as positional args"
```

---

## Task 9: CLI `init` + `scaffold_project` rename

**Files:**
- Modify: [reddit_researcher/templates.py](../../../reddit_researcher/templates.py)
- Modify: [reddit_researcher/cli.py](../../../reddit_researcher/cli.py)
- Modify: [tests/test_templates.py](../../../tests/test_templates.py)

This task does two things at once:
1. Renames the existing `subreddits` parameter on `scaffold_project` to `allowlist_subreddits` (avoids name collision).
2. Adds a new `subreddits` parameter for subreddit-mode multi-sub scaffolding, plus a multi-sub TOML emitter.

- [ ] **Step 1: Read existing test_templates.py to learn its patterns**

Run: open [tests/test_templates.py](../../../tests/test_templates.py) and identify call sites using the kwarg `subreddits=`. They will need updating to `allowlist_subreddits=` for the search-mode allowlist tests.

- [ ] **Step 2: Add failing test for multi-sub scaffold**

Append to [tests/test_templates.py](../../../tests/test_templates.py):

```python
def test_scaffold_project_writes_multi_sub_toml(tmp_path):
    from reddit_researcher.templates import scaffold_project

    target = tmp_path / "missouri-cannabis"
    scaffold_project(
        project_dir=target,
        mode="subreddit",
        subreddits=["cannabis", "marijuana", "drugs"],
        model="qwen3:8b",
        description="Cannabis discussion across three subs.",
    )
    body = (target / "project.toml").read_text(encoding="utf-8")
    assert 'subreddits = ["cannabis", "marijuana", "drugs"]' in body
    assert 'subreddit = "' not in body  # multi-sub form replaces the singular


def test_scaffold_project_single_sub_still_uses_singular(tmp_path):
    from reddit_researcher.templates import scaffold_project

    target = tmp_path / "single-faq"
    scaffold_project(
        project_dir=target,
        mode="subreddit",
        subreddit="personalfinance",
        model="qwen3:8b",
    )
    body = (target / "project.toml").read_text(encoding="utf-8")
    assert 'subreddit = "personalfinance"' in body
    assert "subreddits =" not in body
```

Also: any existing test that calls `scaffold_project(... subreddits=["fitness", ...] ...)` (search-mode allowlist) needs its kwarg renamed to `allowlist_subreddits=`. Update those occurrences in `tests/test_templates.py` accordingly.

- [ ] **Step 3: Run tests to confirm new ones fail and existing ones break**

Run: `pytest tests/test_templates.py -v`
Expected: New tests FAIL with `TypeError: unexpected keyword argument 'subreddits'` (or assertion failure). Existing search-mode allowlist tests pass *only after* their kwarg is renamed to `allowlist_subreddits=`.

- [ ] **Step 4: Add multi-sub TOML emitter and update `scaffold_project`**

Edit [reddit_researcher/templates.py](../../../reddit_researcher/templates.py).

Add a new helper near `_subreddit_project_toml`:

```python
def _multi_subreddit_project_toml(*, name: str, description: str, subreddits: list[str], model: str) -> str:
    formatted_subs = ", ".join(f'"{sub}"' for sub in subreddits)
    return f"""\
# Generated by `reddit-researcher init`.
# See docs/architecture.md for the full config reference.

name = "{name}"
description = "{description}"

[scrape]
mode = "subreddit"
subreddits = [{formatted_subs}]
sort = "top"
time_filter = "month"
post_limit = 25
comment_limit = 10
pause_seconds = 1.0
max_retries = 5

[analyze]
model = "{model}"
prompt_file = "prompt.md"
chunk_char_limit = 12000
ollama_timeout_seconds = 600
"""
```

Update `scaffold_project` signature and body:

```python
def scaffold_project(
    *,
    project_dir: Path,
    mode: str,
    subreddit: str | None = None,
    subreddits: list[str] | None = None,
    terms: list[str] | None = None,
    allowlist_subreddits: list[str] | None = None,
    model: str = "qwen3:8b",
    description: str = "",
    prompt_template: str | None = None,
    force: bool = False,
) -> list[Path]:
    """Create a new project folder.

    Returns the list of files written. Skips files that already exist unless
    `force=True`. `prompt_template` selects a built-in prompt by name; when None,
    a sensible default is chosen for the mode.

    For subreddit-mode, pass either `subreddit` (single) or `subreddits` (list)
    — not both. For search-mode, `allowlist_subreddits` populates `subreddits.txt`
    (the search allowlist), distinct from the multi-sub feature.
    """
    if mode not in {"subreddit", "search"}:
        raise ValueError(f"Invalid mode: {mode!r}. Must be 'subreddit' or 'search'.")
    if mode == "subreddit":
        if subreddit and subreddits:
            raise ValueError("Pass subreddit or subreddits to scaffold_project, not both.")
        if not subreddit and not subreddits:
            raise ValueError("mode='subreddit' requires --subreddit (or --subreddits).")

    project_dir.mkdir(parents=True, exist_ok=True)
    name = project_dir.name
    written: list[Path] = []

    template_name = prompt_template or default_template_for(mode)
    prompt = template_text(template_name)

    if mode == "subreddit":
        if subreddits:
            sub_label = ", ".join(f"r/{s}" for s in subreddits)
            body = _multi_subreddit_project_toml(
                name=slugify(name),
                description=description or f"Research project across {sub_label}.",
                subreddits=subreddits,
                model=model,
            )
        else:
            body = _subreddit_project_toml(
                name=slugify(name),
                description=description or f"Research project for r/{subreddit}.",
                subreddit=subreddit or "",
                model=model,
            )
        files: list[tuple[Path, str]] = [
            (project_dir / "project.toml", body),
            (project_dir / "prompt.md", prompt),
        ]
    else:
        body = _search_project_toml(
            name=slugify(name),
            description=description or "Reddit search across one or more terms.",
            model=model,
        )
        terms_body = TERMS_TEMPLATE
        if terms:
            terms_body += "\n".join(terms) + "\n"
        subs_body = SUBREDDITS_TEMPLATE
        if allowlist_subreddits:
            subs_body += "\n".join(allowlist_subreddits) + "\n"
        files = [
            (project_dir / "project.toml", body),
            (project_dir / "prompt.md", prompt),
            (project_dir / "terms.txt", terms_body),
            (project_dir / "subreddits.txt", subs_body),
        ]

    for path, content in files:
        if path.exists() and not force:
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return written
```

- [ ] **Step 5: Update CLI `init` to accept repeatable `--subreddit` and pass through correctly**

Edit [reddit_researcher/cli.py](../../../reddit_researcher/cli.py) line ~104:

```python
    init_parser.add_argument("--subreddit", help="Subreddit name (required for --mode subreddit).")
```

becomes:

```python
    init_parser.add_argument(
        "--subreddit",
        action="append",
        default=[],
        help="Subreddit name (required for --mode subreddit). Repeatable for multi-sub scaffolds.",
    )
```

Update the dispatch block (around line ~308) to map the args correctly. Replace:

```python
        written = scaffold_project(
            project_dir=target,
            mode=args.mode,
            subreddit=args.subreddit,
            terms=args.term,
            subreddits=args.allowlist_subreddit,
            model=args.model or _default_ollama_model(),
            description=args.description,
            prompt_template=args.template,
            force=args.force,
        )
```

with:

```python
        subreddit_args = list(args.subreddit) if args.subreddit else []
        written = scaffold_project(
            project_dir=target,
            mode=args.mode,
            subreddit=subreddit_args[0] if len(subreddit_args) == 1 else None,
            subreddits=subreddit_args if len(subreddit_args) > 1 else None,
            terms=args.term,
            allowlist_subreddits=args.allowlist_subreddit,
            model=args.model or _default_ollama_model(),
            description=args.description,
            prompt_template=args.template,
            force=args.force,
        )
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_templates.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Run full suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add reddit_researcher/templates.py reddit_researcher/cli.py tests/test_templates.py
git commit -m "feat: 'init' CLI scaffolds multi-sub projects; rename allowlist_subreddits"
```

---

## Task 10: Documentation, CHANGELOG, roadmap update

**Files:**
- Modify: [README.md](../../../README.md)
- Modify: [docs/architecture.md](../../architecture.md) (if it exists)
- Modify: [docs/roadmap.md](../../roadmap.md)
- Modify: [CHANGELOG.md](../../../CHANGELOG.md)

- [ ] **Step 1: Add a multi-sub example to README.md**

Edit the subreddit-mode example block in [README.md](../../../README.md) (around the `[scrape] mode = "subreddit"` section). Below the existing single-sub example, add:

````markdown
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
```

`post_limit` is per-subreddit, matching search-mode's per-term semantics. The
combined run folder lives at `runs/missourimarijuana-mocannabis-trees/<ts>/`,
and each post in `normalized/posts.jsonl` carries its source community.
````

- [ ] **Step 2: Update `docs/roadmap.md`**

Edit [docs/roadmap.md](../../roadmap.md) line ~35. Change:

```markdown
- [ ] **Multi-subreddit subreddit-mode** — `[scrape].subreddits = ["a", "b", "c"]` scrapes
      each into one combined run dir. Surfaced as a real friction point during the
      Missouri-cannabis case study; right now users have to hand-write a Python harness.
```

to:

```markdown
- [x] **Multi-subreddit subreddit-mode** — `[scrape].subreddits = ["a", "b", "c"]` scrapes
      each into one combined run dir. *(0.2.0)*
```

- [ ] **Step 3: Update `docs/architecture.md` if it exists**

If [docs/architecture.md](../../architecture.md) exists and documents the manifest schema, add a brief note that subreddit-mode now supports a list of subreddits and that posts in `posts.jsonl` are partitioned by their `subreddit` field. If it doesn't exist, skip this step.

- [ ] **Step 4: Add CHANGELOG entry**

Edit [CHANGELOG.md](../../../CHANGELOG.md). Add an entry at the top:

```markdown
## 0.2.0-beta

### Added
- Multi-subreddit subreddit-mode: `[scrape].subreddits = ["a", "b", "c"]` scrapes
  multiple communities into a single combined run folder, with per-sub status
  tracked in `manifest["per_subreddit"]`. Single-sub projects continue to work
  unchanged. `post_limit` applies per-subreddit (matching search-mode semantics).
- Manifest `schema_version` bumped 1 → 2 (additive). New fields: `subreddits`
  (list, always present in subreddit-mode), `per_subreddit` (per-sub counters
  and status). Old (v1) manifests read forward via a normalization helper —
  no rewriting needed.
- `multi_subreddit_scope` helper for run-dir naming with multiple subs.

### Changed
- `ScrapeConfig.subreddit` (str) replaced by `ScrapeConfig.subreddits` (list).
  TOML projects continue to accept either `subreddit = "x"` or
  `subreddits = ["a", "b"]` (but not both).
- `scaffold_project` parameter `subreddits` (search-mode allowlist) renamed to
  `allowlist_subreddits` to free up the name for the new multi-sub scaffolder.
- `reddit-researcher scrape <name>` now accepts multiple positional names:
  `reddit-researcher scrape cannabis marijuana drugs`.
- `reddit-researcher init --subreddit` is now repeatable; supplying multiple
  scaffolds a `subreddits = [...]` project.
```

- [ ] **Step 5: Bump `__version__`**

Edit `reddit_researcher/__init__.py`:

```python
__version__ = "0.2.0-beta"
```

- [ ] **Step 6: Run full test suite one more time**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/roadmap.md docs/architecture.md CHANGELOG.md reddit_researcher/__init__.py
git commit -m "docs: multi-subreddit mode (0.2.0-beta)"
```

---

## Acceptance verification

After all 10 tasks land, manually verify acceptance criteria from the spec:

- [ ] `pytest -v` is green.
- [ ] A `project.toml` with `subreddits = ["a", "b", "c"]` runs end-to-end against a stubbed Reddit client (covered by `tests/test_multi_subreddit.py`).
- [ ] `runs/<slug>/<ts>/` for a multi-sub run uses the joined slug name (covered by `test_multi_sub_scrape_combines_posts_into_one_run_dir`).
- [ ] `manifest["per_subreddit"]` populates for both single-sub and multi-sub runs (covered by `test_subreddit_scrape_writes_per_subreddit_manifest_section` and `test_multi_sub_scrape_combines_posts_into_one_run_dir`).
- [ ] An old (v1) manifest reads without modification through `normalize_manifest` (covered by `test_normalize_v1_subreddit_run_synthesizes_subreddits_list`).
- [ ] Coverage gate (currently 70%) holds.
