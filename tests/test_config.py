from pathlib import Path

import pytest

from reddit_researcher.config import find_project_config, load_project


def _write_project(dir_path: Path, body: str) -> Path:
    config_path = dir_path / "project.toml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


def test_load_subreddit_project(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        name = "demo"
        description = "demo project"

        [scrape]
        mode = "subreddit"
        subreddit = "Supplements"
        sort = "top"
        time_filter = "month"
        post_limit = 5
        comment_limit = 2

        [analyze]
        model = "qwen3:8b"
        prompt_file = "prompt.md"
        """,
    )
    (tmp_path / "prompt.md").write_text("Find questions.\n", encoding="utf-8")

    project = load_project(config_path)

    assert project.name == "demo"
    assert project.scrape.mode == "subreddit"
    assert project.scrape.subreddit == "Supplements"
    assert project.scrape.post_limit == 5
    assert project.analyze.model == "qwen3:8b"
    assert project.analyze.prompt_file == (tmp_path / "prompt.md").resolve()


def test_load_search_project_with_relevance(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        name = "search"

        [scrape]
        mode = "search"
        terms_file = "terms.txt"
        subreddits_file = "subs.txt"
        post_limit = 3

        [analyze]
        model = "qwen3:8b"
        prompt_file = "prompt.md"

        [relevance]
        keywords = ["interview", "podcast"]
        allowed_subreddits = ["Fitness", "Nutrition"]
        require_exact_term_match = false
        """,
    )
    (tmp_path / "terms.txt").write_text("alice\n", encoding="utf-8")
    (tmp_path / "subs.txt").write_text("Fitness\n", encoding="utf-8")
    (tmp_path / "prompt.md").write_text("Summarize.\n", encoding="utf-8")

    project = load_project(config_path)

    assert project.scrape.mode == "search"
    assert project.scrape.terms_file == (tmp_path / "terms.txt").resolve()
    assert project.relevance.keywords == ["interview", "podcast"]
    assert project.relevance.allowed_subreddits == {"fitness", "nutrition"}
    assert project.relevance.require_exact_term_match is False


def test_invalid_mode_rejected(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "nonsense"
        subreddit = "Supplements"
        """,
    )
    with pytest.raises(ValueError, match="Invalid scrape.mode"):
        load_project(config_path)


def test_subreddit_mode_requires_subreddit(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "subreddit"
        """,
    )
    with pytest.raises(ValueError, match="requires scrape.subreddit"):
        load_project(config_path)


def test_search_mode_requires_terms_file(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        [scrape]
        mode = "search"
        """,
    )
    with pytest.raises(ValueError, match="requires scrape.terms_file"):
        load_project(config_path)


def test_find_project_config_accepts_dir(tmp_path: Path) -> None:
    config_path = _write_project(
        tmp_path,
        """
        name = "demo"

        [scrape]
        mode = "subreddit"
        subreddit = "Supplements"
        """,
    )
    assert find_project_config(tmp_path) == config_path
    assert find_project_config(config_path) == config_path


def test_find_project_config_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_project_config(tmp_path / "missing")
