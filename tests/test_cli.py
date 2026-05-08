"""Surface-level CLI tests.

These exercise main() with various argv sets, mocking out the pipeline calls so
no Reddit/Ollama traffic happens. The goal is to cover dispatch logic, argument
parsing, and the small handlers (init, list, review) end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reddit_researcher import cli


def test_version_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "reddit-researcher" in out


def test_init_list_templates(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["init", "--list-templates"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "question-mining" in out
    assert "sentiment-comparison" in out


def test_init_creates_subreddit_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(
        [
            "init",
            "demo",
            "--mode",
            "subreddit",
            "--subreddit",
            "Programming",
            "--projects-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created project" in out
    assert (tmp_path / "demo" / "project.toml").is_file()
    assert (tmp_path / "demo" / "prompt.md").is_file()


def test_init_idempotent_without_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = [
        "init",
        "demo",
        "--mode",
        "subreddit",
        "--subreddit",
        "Foo",
        "--projects-dir",
        str(tmp_path),
    ]
    cli.main(args)
    capsys.readouterr()  # discard first run output
    rc = cli.main(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "already populated" in out


def test_init_with_explicit_template(tmp_path: Path) -> None:
    rc = cli.main(
        [
            "init",
            "demo",
            "--mode",
            "search",
            "--term",
            "alice",
            "--template",
            "expert-mention",
            "--projects-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    body = (tmp_path / "demo" / "prompt.md").read_text(encoding="utf-8")
    assert "named person" in body or "named people" in body.lower()


def test_init_requires_name_when_not_listing(tmp_path: Path) -> None:
    rc = cli.main(["init", "--projects-dir", str(tmp_path)])
    assert rc == 2


def test_list_command_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(
        [
            "init",
            "demo",
            "--mode",
            "subreddit",
            "--subreddit",
            "Programming",
            "--projects-dir",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    rc = cli.main(
        [
            "list",
            "--projects-dir",
            str(tmp_path),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "demo" in out
    assert "subreddit" in out


def test_review_command_summarizes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "Programming" / "20260506-120000"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "mode": "subreddit",
                "subreddit": "Programming",
                "status": "complete",
                "post_count": 10,
                "comment_count": 50,
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    rc = cli.main(["review", str(run_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Programming" in out
    assert "10 posts" in out


def test_run_command_surfaces_config_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "project.toml"
    bad.write_text('[scrape\nmode = "subreddit"\n', encoding="utf-8")

    rc = cli.main(["run", str(bad)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "invalid TOML" in err


def test_run_command_dispatches_subreddit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock the pipeline call to confirm CLI args land on the right path."""
    cli.main(
        [
            "init",
            "demo",
            "--mode",
            "subreddit",
            "--subreddit",
            "Programming",
            "--projects-dir",
            str(tmp_path),
        ]
    )

    captured: dict[str, object] = {}

    def fake_run_project(**kwargs):
        captured.update(kwargs)
        return tmp_path / "fake-run"

    monkeypatch.setattr(cli, "run_project", fake_run_project)

    rc = cli.main(
        [
            "run",
            str(tmp_path / "demo"),
            "--skip-extract",
            "--output-root",
            str(tmp_path / "runs"),
        ]
    )
    assert rc == 0
    assert captured["skip_extract"] is True
    assert captured["output_root"] == tmp_path / "runs"


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


def test_corpus_format_cli_override_threads_to_analyze_config() -> None:
    """--corpus-format overrides AnalyzeConfig.corpus_format via _apply_analyze_overrides."""
    import argparse

    from reddit_researcher.cli import _apply_analyze_overrides
    from reddit_researcher.config import AnalyzeConfig

    base = AnalyzeConfig()
    args = argparse.Namespace(
        prompt_file=None, model=None, ollama_url=None, ollama_timeout_seconds=None,
        chunk_char_limit=None, chunk_limit=None, force_reextract=False,
        corpus_format="conversational",
    )
    result = _apply_analyze_overrides(base, args)
    assert result.corpus_format == "conversational"


def test_corpus_format_cli_override_none_falls_back_to_base() -> None:
    import argparse

    from reddit_researcher.cli import _apply_analyze_overrides
    from reddit_researcher.config import AnalyzeConfig

    base = AnalyzeConfig(corpus_format="structured-json")
    args = argparse.Namespace(
        prompt_file=None, model=None, ollama_url=None, ollama_timeout_seconds=None,
        chunk_char_limit=None, chunk_limit=None, force_reextract=False,
        corpus_format=None,
    )
    result = _apply_analyze_overrides(base, args)
    assert result.corpus_format == "structured-json"


# ---------------------------------------------------------------------------
# Project auto-discovery from run-dir manifest
# ---------------------------------------------------------------------------


def _write_manifest(run_dir: Path, *, project_name: str | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": 2, "mode": "subreddit", "status": "complete",
        "subreddits": ["AskReddit"], "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 0, "comment_count": 0,
    }
    if project_name is not None:
        manifest["project_name"] = project_name
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_project_toml(project_dir: Path, *, name: str = "demo") -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.toml").write_text(
        f'name = "{name}"\n'
        '[scrape]\nmode = "subreddit"\nsubreddit = "AskReddit"\n'
        '[analyze]\nprompt_file = "prompt.md"\nmodel = "stub"\n'
        '[storage]\ndb_path = "r.db"\nauto_sync = false\n',
        encoding="utf-8",
    )
    (project_dir / "prompt.md").write_text("Summarize.", encoding="utf-8")


def test_resolve_project_from_run_finds_match(tmp_path: Path) -> None:
    from reddit_researcher.cli import _resolve_project_from_run

    projects_dir = tmp_path / "projects"
    _write_project_toml(projects_dir / "demo")
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name="demo")

    resolved = _resolve_project_from_run(run_dir, projects_dir)
    assert resolved == projects_dir / "demo" / "project.toml"


def test_resolve_project_from_run_returns_none_without_project_name(tmp_path: Path) -> None:
    from reddit_researcher.cli import _resolve_project_from_run

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name=None)

    assert _resolve_project_from_run(run_dir, projects_dir) is None


def test_resolve_project_from_run_returns_none_when_project_missing(tmp_path: Path) -> None:
    from reddit_researcher.cli import _resolve_project_from_run

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name="missing")

    assert _resolve_project_from_run(run_dir, projects_dir) is None


def test_resolve_project_from_run_handles_corrupt_manifest(tmp_path: Path) -> None:
    from reddit_researcher.cli import _resolve_project_from_run

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{not json", encoding="utf-8")

    assert _resolve_project_from_run(run_dir, projects_dir) is None


def test_extract_autodiscovers_prompt_from_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extract <run-dir>` without --prompt-file resolves the project via manifest.project_name."""
    projects_dir = tmp_path / "projects"
    _write_project_toml(projects_dir / "demo")
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name="demo")

    monkeypatch.setattr(cli, "DEFAULT_PROJECTS_ROOT", projects_dir)

    captured: dict[str, object] = {}

    def fake_extract(*, run_dir: Path, analyze) -> Path:
        captured["run_dir"] = run_dir
        captured["prompt_file"] = analyze.prompt_file
        captured["model"] = analyze.model
        return run_dir / "analysis" / "final.md"

    monkeypatch.setattr(cli, "extract_from_run", fake_extract)

    rc = cli.main(["extract", str(run_dir)])
    assert rc == 0
    # prompt_file resolves to the project's prompt.md (relative path resolved by load_project).
    assert captured["prompt_file"] == projects_dir / "demo" / "prompt.md"
    assert captured["model"] == "stub"


def test_extract_errors_when_no_prompt_and_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """No --prompt-file and no project_name in manifest → helpful error, no extract call."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name=None)

    monkeypatch.setattr(cli, "DEFAULT_PROJECTS_ROOT", projects_dir)

    called = {"hit": False}

    def fake_extract(*, run_dir: Path, analyze) -> Path:  # pragma: no cover - shouldn't run
        called["hit"] = True
        return run_dir

    monkeypatch.setattr(cli, "extract_from_run", fake_extract)

    rc = cli.main(["extract", str(run_dir)])
    assert rc == 2
    assert called["hit"] is False
    err = capsys.readouterr().err
    assert "--prompt-file is required" in err


def test_extract_explicit_prompt_file_skips_autodiscovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--prompt-file wins; even a stale/missing project_name is harmless."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    _write_manifest(run_dir, project_name="missing")

    explicit_prompt = tmp_path / "explicit.md"
    explicit_prompt.write_text("Different prompt.", encoding="utf-8")

    monkeypatch.setattr(cli, "DEFAULT_PROJECTS_ROOT", projects_dir)

    captured: dict[str, object] = {}

    def fake_extract(*, run_dir: Path, analyze) -> Path:
        captured["prompt_file"] = analyze.prompt_file
        return run_dir

    monkeypatch.setattr(cli, "extract_from_run", fake_extract)

    rc = cli.main(["extract", str(run_dir), "--prompt-file", str(explicit_prompt)])
    assert rc == 0
    assert captured["prompt_file"] == explicit_prompt
