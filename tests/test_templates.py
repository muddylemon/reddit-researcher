from pathlib import Path

import pytest

from reddit_researcher.config import find_project_config, load_project
from reddit_researcher.templates import scaffold_project


def test_scaffold_subreddit_project_writes_expected_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "my-supplements"
    written = scaffold_project(
        project_dir=project_dir,
        mode="subreddit",
        subreddit="Supplements",
        model="qwen3:8b",
        description="demo",
    )

    relative = sorted(p.name for p in written)
    assert relative == ["project.toml", "prompt.md"]

    project = load_project(find_project_config(project_dir))
    assert project.scrape.mode == "subreddit"
    assert project.scrape.subreddits == ["Supplements"]
    assert project.analyze.model == "qwen3:8b"
    assert project.analyze.prompt_file == (project_dir / "prompt.md").resolve()


def test_scaffold_search_project_writes_terms_and_subreddits(tmp_path: Path) -> None:
    project_dir = tmp_path / "search-demo"
    written = scaffold_project(
        project_dir=project_dir,
        mode="search",
        terms=["alice", "bob"],
        allowlist_subreddits=["fitness", "nutrition"],
    )

    names = sorted(p.name for p in written)
    assert names == ["project.toml", "prompt.md", "subreddits.txt", "terms.txt"]

    terms_text = (project_dir / "terms.txt").read_text(encoding="utf-8")
    assert "alice" in terms_text
    assert "bob" in terms_text

    project = load_project(find_project_config(project_dir))
    assert project.scrape.mode == "search"
    assert project.scrape.terms_file == (project_dir / "terms.txt").resolve()


def test_scaffold_subreddit_requires_subreddit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="subreddit"):
        scaffold_project(project_dir=tmp_path / "x", mode="subreddit")


def test_scaffold_does_not_overwrite_without_force(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    scaffold_project(project_dir=project_dir, mode="subreddit", subreddit="Foo")
    (project_dir / "prompt.md").write_text("custom content", encoding="utf-8")

    written = scaffold_project(project_dir=project_dir, mode="subreddit", subreddit="Foo")
    assert written == []
    assert (project_dir / "prompt.md").read_text(encoding="utf-8") == "custom content"


def test_scaffold_uses_explicit_template(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    scaffold_project(
        project_dir=project_dir,
        mode="search",
        terms=["x"],
        prompt_template="expert-mention",
    )
    body = (project_dir / "prompt.md").read_text(encoding="utf-8")
    assert "named person" in body or "named people" in body.lower()


def test_scaffold_default_template_matches_mode(tmp_path: Path) -> None:
    subreddit_dir = tmp_path / "sub"
    scaffold_project(project_dir=subreddit_dir, mode="subreddit", subreddit="Foo")
    sub_body = (subreddit_dir / "prompt.md").read_text(encoding="utf-8")
    assert "FAQ" in sub_body or "questions" in sub_body.lower()

    search_dir = tmp_path / "search"
    scaffold_project(project_dir=search_dir, mode="search")
    search_body = (search_dir / "prompt.md").read_text(encoding="utf-8")
    assert "search term" in search_body.lower()


def test_scaffold_force_overwrites(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    scaffold_project(project_dir=project_dir, mode="subreddit", subreddit="Foo")
    (project_dir / "prompt.md").write_text("custom content", encoding="utf-8")

    written = scaffold_project(
        project_dir=project_dir,
        mode="subreddit",
        subreddit="Foo",
        force=True,
    )
    assert (project_dir / "prompt.md") in written
    assert "custom content" not in (project_dir / "prompt.md").read_text(encoding="utf-8")


def test_scaffold_project_writes_multi_sub_toml(tmp_path):
    from reddit_researcher.templates import scaffold_project

    target = tmp_path / "missouri-cannabis"
    scaffold_project(
        project_dir=target,
        mode="subreddit",
        subreddits=["cannabis", "marijuana", "drugs"],
        model="qwen3:8b",
        description="Cannabis discussion across three subs.",
    )
    body = (target / "project.toml").read_text(encoding="utf-8")
    assert 'subreddits = ["cannabis", "marijuana", "drugs"]' in body
    assert 'subreddit = "' not in body  # multi-sub form replaces the singular


def test_scaffold_project_single_sub_still_uses_singular(tmp_path):
    from reddit_researcher.templates import scaffold_project

    target = tmp_path / "single-faq"
    scaffold_project(
        project_dir=target,
        mode="subreddit",
        subreddit="personalfinance",
        model="qwen3:8b",
    )
    body = (target / "project.toml").read_text(encoding="utf-8")
    assert 'subreddit = "personalfinance"' in body
    assert "subreddits =" not in body
