import json
from pathlib import Path

from reddit_researcher.templates import scaffold_project
from reddit_researcher.views import list_projects, list_runs, summarize_run


def _write_run(runs_dir: Path, scope: str, manifest: dict) -> Path:
    run_dir = runs_dir / scope / "20260506-120000"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def test_list_projects_handles_missing_dir(tmp_path: Path) -> None:
    output = list_projects(tmp_path / "does-not-exist")
    assert "directory does not exist" in output


def test_list_projects_renders_table(tmp_path: Path) -> None:
    scaffold_project(
        project_dir=tmp_path / "alpha",
        mode="subreddit",
        subreddit="Programming",
    )
    scaffold_project(project_dir=tmp_path / "beta", mode="search")

    output = list_projects(tmp_path)
    assert "alpha" in output
    assert "beta" in output
    assert "subreddit" in output
    assert "search" in output
    assert "r/Programming" in output


def test_list_runs_orders_by_recency_and_caps(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(
        runs_dir,
        "Programming",
        {
            "mode": "subreddit",
            "subreddit": "Programming",
            "status": "complete",
            "post_count": 25,
            "comment_count": 100,
        },
    )
    _write_run(
        runs_dir,
        "all-reddit-search",
        {
            "mode": "search",
            "search_terms": ["alice"],
            "status": "complete",
            "post_count": 5,
            "comment_count": 12,
        },
    )

    output = list_runs(runs_dir, limit=10)
    assert "Programming/20260506-120000" in output
    assert "all-reddit-search/20260506-120000" in output
    assert "complete" in output


def test_summarize_run_includes_relevance_breakdown(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        "Programming",
        {
            "mode": "subreddit",
            "subreddit": "Programming",
            "status": "complete",
            "post_count": 3,
            "comment_count": 6,
            "sort": "top",
            "time_filter": "month",
            "post_limit": 3,
            "comment_limit": 2,
        },
    )
    review_path = run_dir / "review" / "relevance_review.jsonl"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        '{"decision": "include"}\n{"decision": "include"}\n{"decision": "exclude"}\n',
        encoding="utf-8",
    )

    output = summarize_run(run_dir)
    assert "Run:" in output
    assert "r/Programming" in output
    assert "3 posts, 6 comments" in output
    assert "2 include" in output
    assert "1 exclude" in output


def test_summarize_missing_run(tmp_path: Path) -> None:
    output = summarize_run(tmp_path / "missing")
    assert "Run not found" in output


def test_summarize_run_without_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    output = summarize_run(run_dir)
    assert "no manifest.json" in output
