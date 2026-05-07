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
