"""Tests for `pipeline.run_project` — the top-level orchestrator.

We monkeypatch the underlying scrape and extract calls so the test verifies
dispatch only, not the inner workings (those have their own tests).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reddit_researcher import pipeline
from reddit_researcher.config import AnalyzeConfig, ProjectConfig, ScrapeConfig
from reddit_researcher.relevance import RelevanceConfig


def _make_project(*, mode: str, prompt_file: Path | None, tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        name="demo",
        description="",
        project_dir=tmp_path,
        scrape=ScrapeConfig(
            mode=mode,
            subreddits=["Programming"] if mode == "subreddit" else [],
            terms_file=tmp_path / "terms.txt" if mode == "search" else None,
        ),
        analyze=AnalyzeConfig(prompt_file=prompt_file),
        relevance=RelevanceConfig(),
    )


def test_run_project_subreddit_mode_dispatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_scrape_subreddit(**kwargs):
        captured.update(kwargs)
        return tmp_path / "runs" / "Programming" / "stamp"

    def fail_search(**_):
        pytest.fail("subreddit mode should not call scrape_search_terms")

    def fake_extract(**kwargs):
        captured["extract_called"] = True
        captured["extract_run_dir"] = kwargs["run_dir"]
        return kwargs["run_dir"] / "analysis" / "final.md"

    monkeypatch.setattr(pipeline, "scrape_subreddit", fake_scrape_subreddit)
    monkeypatch.setattr(pipeline, "scrape_search_terms", fail_search)
    monkeypatch.setattr(pipeline, "extract_from_run", fake_extract)

    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    project = _make_project(mode="subreddit", prompt_file=prompt, tmp_path=tmp_path)

    result = pipeline.run_project(
        project=project,
        output_root=tmp_path / "runs",
    )
    assert result == tmp_path / "runs" / "Programming" / "stamp"
    assert captured["subreddits"] == ["Programming"]
    assert captured["extract_called"] is True


def test_run_project_search_mode_dispatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return tmp_path / "runs" / "all-reddit-search" / "stamp"

    def fail_subreddit(**_):
        pytest.fail("search mode should not call scrape_subreddit")

    monkeypatch.setattr(pipeline, "scrape_subreddit", fail_subreddit)
    monkeypatch.setattr(pipeline, "scrape_search_terms", fake_search)
    monkeypatch.setattr(pipeline, "extract_from_run", lambda **_: tmp_path / "fake-final.md")

    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    terms = tmp_path / "terms.txt"
    terms.write_text("alice\n", encoding="utf-8")
    project = _make_project(mode="search", prompt_file=prompt, tmp_path=tmp_path)

    pipeline.run_project(
        project=project,
        output_root=tmp_path / "runs",
        start_term_index=2,
        term_limit=3,
    )
    assert captured["start_term_index"] == 2
    assert captured["term_limit"] == 3


def test_run_project_skip_extract_returns_scrape_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pipeline, "scrape_subreddit", lambda **_: tmp_path / "scraped")

    def fail_extract(**_):
        pytest.fail("extract_from_run must not be called when skip_extract=True")

    monkeypatch.setattr(pipeline, "extract_from_run", fail_extract)

    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    project = _make_project(mode="subreddit", prompt_file=prompt, tmp_path=tmp_path)

    result = pipeline.run_project(
        project=project,
        output_root=tmp_path / "runs",
        skip_extract=True,
    )
    assert result == tmp_path / "scraped"


def test_run_project_threads_run_dir_to_subreddit_scrape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_scrape_subreddit(**kwargs):
        captured.update(kwargs)
        return tmp_path / "scraped"

    monkeypatch.setattr(pipeline, "scrape_subreddit", fake_scrape_subreddit)
    monkeypatch.setattr(pipeline, "extract_from_run", lambda **_: tmp_path / "final.md")

    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    project = _make_project(mode="subreddit", prompt_file=prompt, tmp_path=tmp_path)

    explicit_run_dir = tmp_path / "explicit-run"
    pipeline.run_project(
        project=project,
        output_root=tmp_path / "runs",
        run_dir=explicit_run_dir,
    )
    assert captured["run_dir"] == explicit_run_dir


def test_run_project_no_prompt_skips_extract_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the project has no prompt_file, run_project returns the scrape dir without erroring."""
    monkeypatch.setattr(pipeline, "scrape_subreddit", lambda **_: tmp_path / "scraped")

    def fail_extract(**_):
        pytest.fail("extract_from_run should not be called when prompt_file is None")

    monkeypatch.setattr(pipeline, "extract_from_run", fail_extract)

    project = _make_project(mode="subreddit", prompt_file=None, tmp_path=tmp_path)
    result = pipeline.run_project(project=project, output_root=tmp_path / "runs")
    assert result == tmp_path / "scraped"
