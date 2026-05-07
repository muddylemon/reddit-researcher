"""Tests for auto_sync integration in pipeline.run_project."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from reddit_researcher.config import (
    AnalyzeConfig,
    ProjectConfig,
    ScrapeConfig,
    StorageConfig,
)
from reddit_researcher.models import CommentRecord, PostRecord
from reddit_researcher.pipeline import run_project


class _StubClient:
    """Minimal stand-in for the Reddit client. Returns one canned post."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        pass

    def fetch_posts(self, subreddit: str, sort: str, limit: int, time_filter: str | None):
        post = PostRecord(
            id="p1",
            subreddit=subreddit,
            title="t",
            author="a",
            selftext="body",
            url="https://reddit.com/p1",
            permalink="/r/x/comments/p1/",
            score=5,
            upvote_ratio=0.9,
            num_comments=1,
            created_utc=1700000000.0,
            over_18=False,
            is_self=True,
            link_flair_text=None,
            sort=sort,
            time_filter=time_filter,
        )
        return [post], {"backend": "stub"}

    def fetch_comments(self, permalink: str, post_id: str, limit: int):  # noqa: ARG002
        comment = CommentRecord(
            id="c1",
            post_id=post_id,
            parent_id=f"t3_{post_id}",
            author="b",
            body="hello",
            score=1,
            created_utc=1700000100.0,
            permalink=f"{permalink}c1",
            depth=0,
        )
        return [comment], []


@pytest.fixture
def patched_make_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reddit_researcher.pipeline.make_reddit_client",
        lambda scrape: _StubClient(),
    )


def _build_project(tmp_path: Path, *, auto_sync: bool) -> ProjectConfig:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    return ProjectConfig(
        name="demo",
        description="",
        project_dir=project_dir,
        scrape=ScrapeConfig(mode="subreddit", subreddits=["AskReddit"], post_limit=1, comment_limit=1),
        analyze=AnalyzeConfig(),
        storage=StorageConfig(db_path=project_dir / "r.db", auto_sync=auto_sync),
    )


def test_auto_sync_populates_db(tmp_path: Path, patched_make_client: None) -> None:  # noqa: ARG001
    project = _build_project(tmp_path, auto_sync=True)
    run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    db_path = project.project_dir / "r.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1
    finally:
        conn.close()


def test_auto_sync_disabled_does_not_create_db(tmp_path: Path, patched_make_client: None) -> None:  # noqa: ARG001
    project = _build_project(tmp_path, auto_sync=False)
    run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    assert not (project.project_dir / "r.db").exists()


def test_auto_sync_records_project_name(tmp_path: Path, patched_make_client: None) -> None:  # noqa: ARG001
    project = _build_project(tmp_path, auto_sync=True)
    run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    db_path = project.project_dir / "r.db"
    conn = sqlite3.connect(db_path)
    try:
        names = conn.execute("SELECT project_name FROM runs").fetchall()
    finally:
        conn.close()
    assert names == [("demo",)]


def test_auto_sync_failure_does_not_fail_run(
    tmp_path: Path, patched_make_client: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG001
) -> None:
    project = _build_project(tmp_path, auto_sync=True)

    def boom(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        raise RuntimeError("disk full")

    monkeypatch.setattr("reddit_researcher.pipeline.sync_run", boom)
    # Should not raise.
    run_dir = run_project(project=project, output_root=tmp_path / "runs", skip_extract=True)
    assert (run_dir / "normalized" / "posts.jsonl").exists()
