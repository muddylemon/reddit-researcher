from pathlib import Path

from reddit_researcher.storage import (
    append_jsonl,
    create_run_dir,
    read_jsonl,
    slugify,
    write_json,
    write_jsonl,
    write_text,
)


def test_slugify_handles_special_characters() -> None:
    assert slugify("Dr. Jockers") == "Dr.-Jockers"
    assert slugify("  weird   name?!  ") == "weird-name"
    assert slugify("") == "run"


def test_create_run_dir_creates_subdirs(tmp_path: Path) -> None:
    run_dir = create_run_dir(output_root=tmp_path, scope="my-scope")
    assert (run_dir / "raw" / "comments").is_dir()
    assert (run_dir / "normalized").is_dir()
    assert (run_dir / "analysis" / "chunks").is_dir()
    assert (run_dir / "logs").is_dir()
    assert (run_dir / "review").is_dir()


def test_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    rows = [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
    write_jsonl(path, rows)
    assert read_jsonl(path) == rows

    append_jsonl(path, {"id": "c", "n": 3})
    assert read_jsonl(path)[-1] == {"id": "c", "n": 3}


def test_write_json_pretty_prints(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    write_json(path, {"hello": "world"})
    content = path.read_text(encoding="utf-8")
    assert "\n" in content
    assert '"hello"' in content


def test_write_text_creates_parents(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "file.md"
    write_text(path, "# hello\n")
    assert path.read_text(encoding="utf-8") == "# hello\n"
