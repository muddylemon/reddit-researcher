from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


def slugify(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    clean = clean.strip("-")
    return clean or "run"


def timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def create_run_dir(output_root: Path, scope: str) -> Path:
    run_dir = output_root / slugify(scope) / timestamp_slug()
    (run_dir / "raw" / "comments").mkdir(parents=True, exist_ok=True)
    (run_dir / "normalized").mkdir(parents=True, exist_ok=True)
    (run_dir / "analysis" / "chunks").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "review").mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=True))
        handle.write("\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def multi_subreddit_scope(subreddits: list[str], *, max_chars: int = 60) -> str:
    """Build the run-dir scope segment for one or many subreddits.

    For a single sub, returns the name unchanged (preserves today's run-dir
    naming). For multiple subs, lowercases and joins with '-', truncating
    to `max_chars` by dropping trailing entries and appending `+K`.
    """
    if not subreddits:
        raise ValueError("multi_subreddit_scope requires at least one subreddit")

    if len(subreddits) == 1:
        return subreddits[0]

    lowered = [sub.lower() for sub in subreddits]
    joined = "-".join(lowered)
    if len(joined) <= max_chars:
        return joined

    # Drop trailing entries until the remainder + "+K" suffix fits.
    kept = list(lowered)
    dropped = 0
    while kept:
        suffix = f"+{dropped}" if dropped else ""
        candidate = "-".join(kept) + suffix
        if len(candidate) <= max_chars:
            return candidate
        kept.pop()
        dropped += 1

    # Pathological: even the first sub plus suffix exceeds max_chars.
    # Fall back to a hard truncation of the first sub.
    return lowered[0][:max_chars]
