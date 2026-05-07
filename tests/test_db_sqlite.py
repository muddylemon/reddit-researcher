"""Tests for the SQLite RunSink and the engine-agnostic sync_run()."""

# Imports below are scaffolding for tests added by Tasks 3-8 in the SQLite/DuckDB
# sink plan. Symbols unused by current test bodies are suppressed with noqa: F401.
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


def test_sqlite_init_schema_mismatch_closes_connection(tmp_path: Path) -> None:
    """Regression: SchemaVersionMismatch in __init__ must not leak the connection."""
    db_path = tmp_path / "r.db"
    storage = StorageConfig(engine="sqlite", db_path=db_path)

    # Bootstrap the DB at the current schema_version.
    sink = make_sink(storage, project_dir=tmp_path)
    sink.close()

    # Tamper with the recorded version so the next open raises.
    raw = sqlite3.connect(db_path)
    raw.execute("UPDATE _schema_meta SET schema_version = 99")
    raw.commit()
    raw.close()

    with pytest.raises(SchemaVersionMismatch):
        make_sink(storage, project_dir=tmp_path)

    # If the failed init leaked its connection, the file is still locked on
    # Windows and unlink raises PermissionError.
    db_path.unlink()
    assert not db_path.exists()
