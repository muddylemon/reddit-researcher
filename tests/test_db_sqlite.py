"""Tests for the SQLite RunSink and the engine-agnostic sync_run()."""

from __future__ import annotations

import sqlite3  # noqa: F401
from pathlib import Path

import pytest

from reddit_researcher.config import StorageConfig
from reddit_researcher.db import (
    DuckdbNotInstalled,  # noqa: F401
    RunSink,  # noqa: F401
    SchemaVersionMismatch,  # noqa: F401
    SyncResult,  # noqa: F401
    make_sink,
    sync_run,  # noqa: F401
)
from reddit_researcher.db_sqlite import SCHEMA_VERSION, SqliteRunSink  # noqa: F401


def test_factory_returns_sqlite_sink_by_default(tmp_path: Path) -> None:
    storage = StorageConfig(engine="sqlite", db_path=tmp_path / "research.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        assert isinstance(sink, SqliteRunSink)
        assert (tmp_path / "research.db").exists()
    finally:
        sink.close()


def test_factory_raises_for_unknown_engine(tmp_path: Path) -> None:
    storage = StorageConfig(engine="postgres", db_path=tmp_path / "x.db")
    with pytest.raises(ValueError, match="unknown storage engine"):
        make_sink(storage, project_dir=tmp_path)
