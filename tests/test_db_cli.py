"""Tests for the `db` subcommand group."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reddit_researcher.cli import main as cli_main
from reddit_researcher.storage import append_jsonl


def _write_project_with_run(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "AskReddit"\n'
        '[storage]\ndb_path = "r.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": ["AskReddit"],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 1,
        "comment_count": 0,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    append_jsonl(
        run_dir / "normalized" / "posts.jsonl",
        {
            "id": "p1", "subreddit": "AskReddit", "title": "t", "author": "a",
            "selftext": "b", "url": "u", "permalink": "p", "score": 1,
            "upvote_ratio": 0.9, "num_comments": 0, "created_utc": 1.0,
            "over_18": False, "is_self": True, "link_flair_text": None,
            "sort": "top", "time_filter": "month", "comments": [],
        },
    )
    return project_dir, run_dir


def test_db_sync_one_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    rc = cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    assert rc == 0
    db_path = project_dir / "r.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    finally:
        conn.close()
    out = capsys.readouterr().out
    assert "synced" in out.lower()


def test_db_sync_all(tmp_path: Path) -> None:
    project_dir, _ = _write_project_with_run(tmp_path)
    runs_root = tmp_path / "runs"
    assert runs_root.exists()
    rc = cli_main(
        ["db", "sync", "--all", "--project", str(project_dir), "--output-root", str(runs_root)]
    )
    assert rc == 0
    conn = sqlite3.connect(project_dir / "r.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_sync_rebuild(tmp_path: Path) -> None:
    project_dir, run_dir = _write_project_with_run(tmp_path)
    cli_main(["db", "sync", str(run_dir), "--project", str(project_dir)])
    cli_main(["db", "sync", "--rebuild", str(run_dir), "--project", str(project_dir)])
    conn = sqlite3.connect(project_dir / "r.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
    finally:
        conn.close()


def test_db_sync_no_args_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir, _ = _write_project_with_run(tmp_path)
    rc = cli_main(["db", "sync", "--project", str(project_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "run-dir" in err.lower() or "--all" in err.lower()
