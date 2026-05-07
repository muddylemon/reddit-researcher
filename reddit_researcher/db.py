"""Database sink — engine-agnostic surface.

`RunSink` is a Protocol implemented by `SqliteRunSink` (default, stdlib) and
`DuckdbRunSink` (optional `[duckdb]` extra). `make_sink()` dispatches on
`StorageConfig.engine`. `sync_run()` is the engine-agnostic logic that reads
a run dir's JSONL + manifest and writes them through the sink in one
transaction.

JSONL on disk is the source of truth. The DB is a derived view; deleting it
is always safe — re-sync from JSONL.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import StorageConfig
from .manifest import normalize_manifest
from .storage import read_jsonl


class DuckdbNotInstalled(RuntimeError):
    """Raised when the `duckdb` extra has not been installed."""


class SchemaVersionMismatch(RuntimeError):
    """Raised when the on-disk DB schema version differs from the current code's."""


@dataclass
class SyncResult:
    run_dir: Path
    posts: int
    comments: int
    relevance: int


class RunSink(Protocol):
    """Engine-agnostic write surface for one run's data."""

    def transaction(self) -> AbstractContextManager[Any]: ...

    def upsert_run(self, run_dir: Path, manifest: dict[str, Any]) -> None: ...

    def insert_posts(self, run_dir: Path, posts: list[dict[str, Any]]) -> None: ...

    def insert_comments(self, run_dir: Path, comments: list[dict[str, Any]]) -> None: ...

    def insert_relevance(self, run_dir: Path, decisions: list[dict[str, Any]]) -> None: ...

    def delete_run(self, run_dir: Path) -> None: ...

    def read_only_connect(self) -> Any: ...

    def rebuild(self) -> None: ...

    def close(self) -> None: ...


def make_sink(storage: StorageConfig, project_dir: Path) -> RunSink:
    """Build a RunSink for the given storage config.

    The duckdb branch lazy-imports its module so users without the extra never
    hit the import.
    """
    db_path = storage.db_path
    if not db_path.is_absolute():
        db_path = (project_dir / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if storage.engine == "sqlite":
        from .db_sqlite import SqliteRunSink

        return SqliteRunSink(db_path)
    if storage.engine == "duckdb":
        try:
            from .db_duckdb import DuckdbRunSink
        except DuckdbNotInstalled:
            raise
        return DuckdbRunSink(db_path)
    raise ValueError(f"unknown storage engine: {storage.engine!r}")


def sync_run(sink: RunSink, run_dir: Path) -> SyncResult:
    """Read JSONL + manifest from a run dir and upsert into the sink.

    Idempotent — re-syncing the same run dir is safe. The whole sync runs in
    one transaction, so a crash mid-sync leaves prior state untouched.
    """
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json under {run_dir}")
    manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))

    posts_path = run_dir / "normalized" / "posts.jsonl"
    comments_path = run_dir / "normalized" / "comments.jsonl"
    review_path = run_dir / "review" / "relevance_review.jsonl"

    posts = read_jsonl(posts_path) if posts_path.exists() else []
    comments = read_jsonl(comments_path) if comments_path.exists() else []
    reviews = read_jsonl(review_path) if review_path.exists() else []

    with sink.transaction():
        sink.delete_run(run_dir)
        sink.upsert_run(run_dir, manifest)
        sink.insert_posts(run_dir, posts)
        sink.insert_comments(run_dir, comments)
        sink.insert_relevance(run_dir, reviews)

    return SyncResult(
        run_dir=run_dir,
        posts=len(posts),
        comments=len(comments),
        relevance=len(reviews),
    )
