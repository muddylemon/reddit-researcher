"""Tests for `pipeline.extract_from_run`.

These exercise the LLM-side of the pipeline by stubbing OllamaClient. Goal: lock
down the chunk-reuse logic, the empty-posts short-circuit, and the manifest
metadata writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reddit_researcher import pipeline
from reddit_researcher.config import AnalyzeConfig
from reddit_researcher.manifest import MANIFEST_SCHEMA_VERSION
from reddit_researcher.storage import write_json, write_jsonl, write_text


class _StubOllama:
    """Returns canned responses without touching the network."""

    def __init__(self, *_, **__) -> None:  # accept the constructor signature pipeline uses
        self.calls: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.calls.append(prompt)
        if len(self.calls) == 1 and "Combine the partial analyses" not in prompt:
            return f"chunk-output-{len(self.calls)}"
        if "Combine the partial analyses" in prompt:
            return "## Final synthesis\nMerged answer."
        return f"chunk-output-{len(self.calls)}"


def _stub_ollama_factory(captured: list[_StubOllama]) -> type:
    """Return a class that records each instance into `captured` for inspection."""

    class _Recorded(_StubOllama):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            captured.append(self)

    return _Recorded


def _seed_run(
    run_dir: Path,
    *,
    posts: list[dict],
    comments: list[dict],
    manifest: dict,
    relevant_posts: list[dict] | None = None,
) -> None:
    (run_dir / "normalized").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis" / "chunks").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    write_jsonl(run_dir / "normalized" / "posts.jsonl", posts)
    write_jsonl(run_dir / "normalized" / "comments.jsonl", comments)
    if relevant_posts is not None:
        write_jsonl(run_dir / "normalized" / "relevant_posts.jsonl", relevant_posts)
    write_json(run_dir / "manifest.json", manifest)


def _prompt_file(tmp_path: Path) -> Path:
    path = tmp_path / "prompt.md"
    path.write_text("Find recurring themes.\n", encoding="utf-8")
    return path


def test_extract_short_circuits_when_no_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    _seed_run(
        run_dir,
        posts=[],
        comments=[],
        manifest={"mode": "subreddit", "subreddit": "x", "post_count": 0},
    )

    final = pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path)),
    )
    assert final == run_dir / "analysis" / "final.md"
    assert "No relevant posts" in final.read_text(encoding="utf-8")
    assert captured == []  # Ollama never instantiated

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["analysis"]["chunk_count"] == 0


def test_extract_subreddit_mode_runs_chunks_and_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    _seed_run(
        run_dir,
        posts=[{"id": "p1", "title": "First", "selftext": "body", "num_comments": 1, "score": 5}],
        comments=[{"id": "c1", "post_id": "p1", "depth": 0, "score": 1, "body": "comment"}],
        manifest={"mode": "subreddit", "subreddit": "Programming", "post_count": 1},
    )

    final = pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path), chunk_char_limit=12000),
    )

    assert final.exists()
    assert "Final synthesis" in final.read_text(encoding="utf-8")
    chunk_path = run_dir / "analysis" / "chunks" / "chunk-001.md"
    assert chunk_path.read_text(encoding="utf-8") == "chunk-output-1"

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["analysis"]["chunk_count"] == 1
    # One chunk + one synthesis = 2 generate() calls.
    assert len(captured) == 1
    assert len(captured[0].calls) == 2


def test_extract_search_mode_uses_search_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    posts = [
        {
            "id": "p1",
            "title": "T1",
            "search_term": "alice",
            "subreddit": "fitness",
            "score": 10,
            "num_comments": 0,
            "comments": [],
        }
    ]
    _seed_run(
        run_dir,
        posts=posts,
        comments=[],
        manifest={
            "mode": "search",
            "subreddit": "all-reddit-search",
            "search_terms": ["alice"],
        },
        relevant_posts=posts,
    )

    pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path)),
    )

    chunk_prompt = captured[0].calls[0]
    assert "Search term: alice" in chunk_prompt  # came from build_search_corpus
    assert "global Reddit search" in chunk_prompt or "Reddit search across" in chunk_prompt


def test_extract_reuses_existing_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    _seed_run(
        run_dir,
        posts=[{"id": "p1", "title": "T", "score": 1, "num_comments": 0}],
        comments=[],
        manifest={"mode": "subreddit", "subreddit": "x"},
    )
    chunk_path = run_dir / "analysis" / "chunks" / "chunk-001.md"
    write_text(chunk_path, "previous-output")

    pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path)),
    )

    # Synthesis still runs (1 call), but the chunk is reused.
    assert len(captured[0].calls) == 1
    assert chunk_path.read_text(encoding="utf-8") == "previous-output"


def test_extract_force_reextract_overwrites_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    _seed_run(
        run_dir,
        posts=[{"id": "p1", "title": "T", "score": 1, "num_comments": 0}],
        comments=[],
        manifest={"mode": "subreddit", "subreddit": "x"},
    )
    chunk_path = run_dir / "analysis" / "chunks" / "chunk-001.md"
    write_text(chunk_path, "stale-output")

    pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path), force_reextract=True),
    )

    assert chunk_path.read_text(encoding="utf-8") == "chunk-output-1"
    assert len(captured[0].calls) == 2  # chunk + synthesis


def test_extract_chunk_limit_caps_processing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    # Build a corpus large enough to split into multiple chunks.
    posts = [
        {
            "id": f"p{i}",
            "title": f"Title {i}",
            "selftext": "x" * 4000,
            "score": i,
            "num_comments": 0,
        }
        for i in range(6)
    ]
    _seed_run(run_dir, posts=posts, comments=[], manifest={"mode": "subreddit", "subreddit": "x"})

    pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path), chunk_char_limit=4500, chunk_limit=2),
    )

    chunks_dir = run_dir / "analysis" / "chunks"
    written = sorted(chunks_dir.glob("chunk-*.md"))
    assert len(written) == 2

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["analysis"]["chunk_count"] == 2
    assert manifest["analysis"]["total_chunk_count"] >= 2
    assert manifest["analysis"]["chunk_limit"] == 2


def test_extract_multi_sub_uses_combined_scope_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[_StubOllama] = []
    monkeypatch.setattr(pipeline, "OllamaClient", _stub_ollama_factory(captured))

    run_dir = tmp_path / "run"
    _seed_run(
        run_dir,
        posts=[
            {"id": "p1", "title": "Post A", "selftext": "body a", "subreddit": "a", "score": 3, "num_comments": 1},
            {"id": "p2", "title": "Post B", "selftext": "body b", "subreddit": "b", "score": 5, "num_comments": 0},
        ],
        comments=[{"id": "c1", "post_id": "p1", "depth": 0, "score": 2, "body": "a comment"}],
        manifest={
            "mode": "subreddit",
            "subreddits": ["a", "b"],
            "per_subreddit": {
                "a": {"post_count": 1, "comment_count": 1},
                "b": {"post_count": 1, "comment_count": 0},
            },
            "post_count": 2,
            "comment_count": 1,
            "status": "complete",
            "schema_version": 2,
        },
    )

    pipeline.extract_from_run(
        run_dir=run_dir,
        analyze=AnalyzeConfig(prompt_file=_prompt_file(tmp_path), chunk_char_limit=12000),
    )

    # The first generate() call is the chunk prompt; it must contain the
    # combined scope label produced by the multi-sub branch of scope_label_for.
    chunk_prompt = captured[0].calls[0]
    assert "r/a and r/b" in chunk_prompt


def test_extract_requires_prompt_file() -> None:
    with pytest.raises(ValueError, match="prompt_file"):
        pipeline.extract_from_run(run_dir=Path("/tmp/x"), analyze=AnalyzeConfig())


def test_extract_from_run_uses_conversational_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """extract_from_run honors AnalyzeConfig.corpus_format."""
    import json as _json

    from reddit_researcher.config import AnalyzeConfig
    from reddit_researcher.pipeline import extract_from_run
    from reddit_researcher.storage import append_jsonl

    run_dir = tmp_path / "runs" / "AskReddit" / "20260507-120000"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "review").mkdir(parents=True)
    (run_dir / "analysis" / "chunks").mkdir(parents=True)
    manifest = {
        "schema_version": 2, "mode": "subreddit", "status": "complete",
        "subreddits": ["AskReddit"], "scraped_at_utc": "2026-05-07T12:00:00+00:00",
        "post_count": 1, "comment_count": 0,
    }
    (run_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")
    append_jsonl(
        run_dir / "normalized" / "posts.jsonl",
        {"id": "p1", "subreddit": "AskReddit", "title": "Hello", "author": "alice",
         "selftext": "world", "url": "u", "permalink": "/p1", "score": 1,
         "upvote_ratio": 0.9, "num_comments": 0, "created_utc": 1.0,
         "over_18": False, "is_self": True, "link_flair_text": None,
         "sort": "top", "time_filter": "month"},
    )
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Summarize.", encoding="utf-8")

    captured: dict[str, str] = {}

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def generate(self, *, model: str, prompt: str) -> str:
            if "last_prompt" not in captured:
                captured["last_prompt"] = prompt
            return "stub response"

    monkeypatch.setattr("reddit_researcher.pipeline.OllamaClient", _StubClient)

    analyze = AnalyzeConfig(
        prompt_file=prompt_file, corpus_format="conversational", chunk_char_limit=10000,
    )
    extract_from_run(run_dir=run_dir, analyze=analyze)

    assert "## Post: Hello" in captured["last_prompt"]
    assert "[POST p1]" not in captured["last_prompt"]
