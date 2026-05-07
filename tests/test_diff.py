"""Tests for reddit_researcher.diff."""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: F401

from reddit_researcher.cli import main as cli_main
from reddit_researcher.config import StorageConfig
from reddit_researcher.db import make_sink, sync_run
from reddit_researcher.diff import (
    DiffResult,
    RunSummary,
    compute_diff,
    format_json,  # noqa: F401
    format_text,  # noqa: F401
)
from reddit_researcher.storage import append_jsonl


def _post_row(post_id: str, subreddit: str = "AskReddit") -> dict:
    return {
        "id": post_id,
        "subreddit": subreddit,
        "title": f"Title {post_id}",
        "author": "alice",
        "selftext": "body",
        "url": f"https://reddit.com/{post_id}",
        "permalink": f"/r/{subreddit}/comments/{post_id}/",
        "score": 1,
        "upvote_ratio": 0.9,
        "num_comments": 0,
        "created_utc": 1.0,
        "over_18": False,
        "is_self": True,
        "link_flair_text": None,
        "sort": "top",
        "time_filter": "month",
        "comments": [],
    }


def _comment_row(comment_id: str, post_id: str) -> dict:
    return {
        "id": comment_id,
        "post_id": post_id,
        "parent_id": f"t3_{post_id}",
        "author": "bob",
        "body": "comment body",
        "score": 1,
        "created_utc": 2.0,
        "permalink": f"/r/x/comments/{post_id}/_/{comment_id}/",
        "depth": 0,
    }


def _make_synced_run(
    sink, tmp_path: Path, *, scope: str, ts: str, mode: str = "subreddit",
    posts: list[dict] | None = None, comments: list[dict] | None = None,
    decisions: list[dict] | None = None, project_name: str | None = "demo",
) -> Path:
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": mode,
        "status": "complete",
        "subreddits": [scope] if mode == "subreddit" else [],
        "scraped_at_utc": f"2026-05-07T{ts[-6:-4]}:00:00+00:00",
        "post_count": len(posts or []),
        "comment_count": len(comments or []),
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts or []:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    for c in comments or []:
        append_jsonl(run_dir / "normalized" / "comments.jsonl", c)
    for d in decisions or []:
        append_jsonl(run_dir / "review" / "relevance_review.jsonl", d)
    sync_run(sink, run_dir)
    return run_dir


def test_compute_diff_returns_diffresult(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert isinstance(result, DiffResult)
        assert isinstance(result.a, RunSummary)
        assert isinstance(result.b, RunSummary)
    finally:
        sink.close()


def test_compute_diff_posts_only_in_a(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3"), _post_row("p4")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert sorted(result.posts_only_in_a) == ["p1"]
        assert sorted(result.posts_only_in_b) == ["p4"]
        assert sorted(result.posts_in_both) == ["p2", "p3"]
    finally:
        sink.close()


def test_compute_diff_identical_post_sets(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1"), _post_row("p2")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert result.posts_only_in_a == []
        assert result.posts_only_in_b == []
        assert sorted(result.posts_in_both) == ["p1", "p2"]
    finally:
        sink.close()


def test_compute_diff_comments_set_counts(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            comments=[_comment_row("c1", "p1"), _comment_row("c2", "p1"), _comment_row("c3", "p1")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1")],
            comments=[_comment_row("c2", "p1"), _comment_row("c3", "p1"), _comment_row("c4", "p1")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert result.comments_only_in_a == 1   # c1
        assert result.comments_only_in_b == 1   # c4
        assert result.comments_in_both == 2     # c2, c3
    finally:
        sink.close()


def test_compute_diff_relevance_changes(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
                {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "off-topic"},
                {"post_id": "p3", "subreddit": "AskReddit", "decision": "review", "reason": "ambiguous"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1"), _post_row("p2"), _post_row("p3")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule changed"},
                {"post_id": "p2", "subreddit": "AskReddit", "decision": "exclude", "reason": "off-topic"},
                {"post_id": "p3", "subreddit": "AskReddit", "decision": "include", "reason": "now matches"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        # Two flips: p1 (include→exclude), p3 (review→include). p2 unchanged.
        changes_by_id = {c["post_id"]: c for c in result.relevance_changes}
        assert set(changes_by_id) == {"p1", "p3"}
        assert changes_by_id["p1"]["a_decision"] == "include"
        assert changes_by_id["p1"]["b_decision"] == "exclude"
        assert changes_by_id["p3"]["a_decision"] == "review"
        assert changes_by_id["p3"]["b_decision"] == "include"
    finally:
        sink.close()


def test_compute_diff_warns_on_mode_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000", mode="subreddit",
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="all-reddit-search", ts="20260508-120000", mode="search",
        )
        result = compute_diff(sink, run_a, run_b)
        assert any("mode mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_warns_on_scope_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="worldnews", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert any("scope mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_warns_on_project_mismatch(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000", project_name="alpha",
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000", project_name="beta",
        )
        result = compute_diff(sink, run_a, run_b)
        assert any("project mismatch" in w for w in result.warnings)
    finally:
        sink.close()


def test_compute_diff_no_warnings_when_runs_match(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260507-120000")
        run_b = _make_synced_run(sink, tmp_path, scope="AskReddit", ts="20260508-120000")
        result = compute_diff(sink, run_a, run_b)
        assert result.warnings == []
    finally:
        sink.close()


def test_format_text_includes_summary_and_counts(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            comments=[_comment_row("c1", "p1")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3")],
            comments=[_comment_row("c1", "p2"), _comment_row("c2", "p2")],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "Diff: A vs B" in text
        assert "AskReddit" in text
        assert "posts:" in text
        assert "only-in-A=1" in text
        assert "only-in-B=1" in text
        assert "in-both=1" in text
        assert "p1" in text       # listed in only-in-A
        assert "p3" in text       # listed in only-in-B
    finally:
        sink.close()


def test_format_text_caps_long_lists(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        # 25 posts only in A — text format should cap at 20 and append "(+N more)".
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row(f"p{i:02d}") for i in range(25)],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "(+5 more)" in text
    finally:
        sink.close()


def test_format_text_includes_relevance_changes(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        text = format_text(result)
        assert "relevance changes" in text.lower()
        assert "include -> exclude" in text or "include → exclude" in text
    finally:
        sink.close()


def test_format_json_round_trip(tmp_path: Path) -> None:
    storage = StorageConfig(db_path=tmp_path / "r.db")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            comments=[_comment_row("c1", "p1")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "include", "reason": "ok"},
            ],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3")],
            comments=[_comment_row("c2", "p2")],
            decisions=[
                {"post_id": "p1", "subreddit": "AskReddit", "decision": "exclude", "reason": "rule"},
            ],
        )
        result = compute_diff(sink, run_a, run_b)
        payload = json.loads(format_json(result))
        # All DiffResult fields present.
        for key in (
            "a", "b", "posts_only_in_a", "posts_only_in_b", "posts_in_both",
            "comments_only_in_a", "comments_only_in_b", "comments_in_both",
            "relevance_changes", "warnings",
        ):
            assert key in payload, f"missing key: {key}"
        # Lists round-trip without truncation (unlike text).
        assert payload["posts_only_in_a"] == ["p1"]
        assert payload["posts_only_in_b"] == ["p3"]
        assert payload["posts_in_both"] == ["p2"]
        # Path serialized via default=str.
        assert isinstance(payload["a"]["run_dir"], str)
    finally:
        sink.close()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "project.toml").write_text(
        '[scrape]\nmode = "subreddit"\nsubreddit = "AskReddit"\n'
        '[storage]\ndb_path = "r.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    return project_dir


def _write_run_jsonl_only(
    tmp_path: Path, *, scope: str, ts: str, posts: list[dict], project_name: str | None = "demo",
) -> Path:
    """Write a run dir to disk WITHOUT syncing (CLI is supposed to auto-sync)."""
    run_dir = tmp_path / "runs" / scope / ts
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "mode": "subreddit",
        "status": "complete",
        "subreddits": [scope],
        "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": len(posts),
        "comment_count": 0,
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for p in posts:
        append_jsonl(run_dir / "normalized" / "posts.jsonl", p)
    return run_dir


def test_cli_diff_text_format_auto_syncs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1"), _post_row("p2")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260508-120000",
        posts=[_post_row("p2"), _post_row("p3")],
    )
    rc = cli_main(["diff", str(run_a), str(run_b), "--project", str(project_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Diff: A vs B" in out
    assert "p1" in out
    assert "p3" in out


def test_cli_diff_json_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260508-120000",
        posts=[_post_row("p1")],
    )
    rc = cli_main([
        "diff", str(run_a), str(run_b),
        "--project", str(project_dir), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["posts_in_both"] == ["p1"]


def test_cli_diff_missing_run_dir_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000",
        posts=[_post_row("p1")],
    )
    bogus = tmp_path / "nope"
    rc = cli_main(["diff", str(run_a), str(bogus), "--project", str(project_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "manifest" in err.lower() or "not found" in err.lower() or "no such" in err.lower()


def test_compute_diff_works_on_duckdb_engine(tmp_path: Path) -> None:
    """Regression: ensure compute_diff doesn't depend on sqlite-only cursor semantics."""
    pytest.importorskip("duckdb")
    storage = StorageConfig(engine="duckdb", db_path=tmp_path / "r.duckdb")
    sink = make_sink(storage, project_dir=tmp_path)
    try:
        run_a = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260507-120000",
            posts=[_post_row("p1"), _post_row("p2")],
            comments=[_comment_row("c1", "p1")],
        )
        run_b = _make_synced_run(
            sink, tmp_path, scope="AskReddit", ts="20260508-120000",
            posts=[_post_row("p2"), _post_row("p3")],
            comments=[_comment_row("c1", "p2"), _comment_row("c2", "p2")],
        )
        result = compute_diff(sink, run_a, run_b)
        assert sorted(result.posts_only_in_a) == ["p1"]
        assert sorted(result.posts_only_in_b) == ["p3"]
        assert sorted(result.posts_in_both) == ["p2"]
        assert result.comments_only_in_a == 0  # c1 in both runs (different post_id but same id)
        # Note: in our test data, c1 appears in both runs (under different posts), so it's
        # in_both for the comment_id set diff. c2 is only in B.
        assert result.comments_only_in_b == 1
        assert result.comments_in_both == 1
    finally:
        sink.close()


def test_cli_diff_warnings_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = _write_project(tmp_path)
    run_a = _write_run_jsonl_only(
        tmp_path, scope="AskReddit", ts="20260507-120000", posts=[_post_row("p1")],
    )
    run_b = _write_run_jsonl_only(
        tmp_path, scope="worldnews", ts="20260508-120000", posts=[_post_row("p2", subreddit="worldnews")],
    )
    rc = cli_main(["diff", str(run_a), str(run_b), "--project", str(project_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "warning:" in captured.err.lower()
    assert "scope mismatch" in captured.err.lower()
