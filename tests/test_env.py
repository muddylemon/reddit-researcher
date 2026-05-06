import os
from pathlib import Path

import pytest

from reddit_researcher.env import load_dotenv, load_dotenvs_for, parse_env_file


def test_parse_env_file_basic() -> None:
    text = """\
# a comment
KEY1=value1
KEY2 = value2
EMPTY=
"""
    assert parse_env_file(text) == {
        "KEY1": "value1",
        "KEY2": "value2",
        "EMPTY": "",
    }


def test_parse_env_file_quoted_values() -> None:
    text = """\
DOUBLE="value with spaces"
SINGLE='value with #hash'
HASH_BARE=foo # trailing comment
"""
    parsed = parse_env_file(text)
    assert parsed["DOUBLE"] == "value with spaces"
    assert parsed["SINGLE"] == "value with #hash"
    assert parsed["HASH_BARE"] == "foo"


def test_parse_env_file_export_prefix() -> None:
    assert parse_env_file("export FOO=bar\n") == {"FOO": "bar"}


def test_parse_env_file_skips_invalid_lines() -> None:
    parsed = parse_env_file("not_a_definition\n=missing_key\nVALID=ok\n")
    assert parsed == {"VALID": "ok"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RR_TEST_KEY", "RR_TEST_OVERRIDE", "RR_TEST_PROJECT"):
        monkeypatch.delenv(key, raising=False)


def test_load_dotenv_sets_env(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("RR_TEST_KEY=hello\n", encoding="utf-8")

    applied = load_dotenv(path)
    assert applied == {"RR_TEST_KEY": "hello"}
    assert os.environ["RR_TEST_KEY"] == "hello"


def test_load_dotenv_does_not_override_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RR_TEST_OVERRIDE", "shell-wins")
    path = tmp_path / ".env"
    path.write_text("RR_TEST_OVERRIDE=dotenv-loses\n", encoding="utf-8")

    applied = load_dotenv(path)
    assert applied == {}
    assert os.environ["RR_TEST_OVERRIDE"] == "shell-wins"


def test_load_dotenv_override_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RR_TEST_OVERRIDE", "shell-value")
    path = tmp_path / ".env"
    path.write_text("RR_TEST_OVERRIDE=dotenv-value\n", encoding="utf-8")

    applied = load_dotenv(path, override=True)
    assert applied == {"RR_TEST_OVERRIDE": "dotenv-value"}
    assert os.environ["RR_TEST_OVERRIDE"] == "dotenv-value"


def test_load_dotenv_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "missing") == {}


def test_load_dotenvs_for_project_overrides_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = tmp_path / "repo" / "projects" / "demo"
    project.mkdir(parents=True)
    (repo / ".env").write_text("RR_TEST_KEY=from-repo\nRR_TEST_PROJECT=from-repo\n", encoding="utf-8")
    (project / ".env").write_text("RR_TEST_PROJECT=from-project\n", encoding="utf-8")

    applied = load_dotenvs_for(project_dir=project, repo_root=repo)
    assert os.environ["RR_TEST_KEY"] == "from-repo"
    assert os.environ["RR_TEST_PROJECT"] == "from-project"
    assert applied["RR_TEST_PROJECT"] == "from-project"
