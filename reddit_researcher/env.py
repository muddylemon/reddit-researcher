"""Tiny `.env` loader.

A deliberately small dotenv parser. It handles the cases real users hit (KEY=value,
optional quotes, blank lines, `#` comments, `export KEY=value`) and skips fancy
features (variable expansion, multi-line values, `.env.local` cascading).

Lookup precedence, lowest to highest:

  1. Defaults baked into the code.
  2. Variables already in `os.environ` from the shell.
  3. Repo-root `.env` (if present).
  4. Project-folder `.env` (if a project is being run).
  5. CLI flags.

Step 3-4 are what this module owns. Existing values in `os.environ` are not
overwritten by default — the shell wins over `.env`. That's the convention
most tools follow and it keeps surprises low when the user runs
`OLLAMA_URL=... reddit-researcher run ...`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<rest>.*)$")


def _parse_value(rest: str) -> str:
    """Extract the value from the right-hand side of `KEY=<rest>`."""
    rest = rest.lstrip()
    if not rest:
        return ""
    quote = rest[0] if rest[0] in {'"', "'"} else None
    if quote is not None:
        end = rest.find(quote, 1)
        if end == -1:
            # Unterminated quote — fall through to bare-value handling so we
            # don't silently lose data on a malformed line.
            return rest[1:].rstrip()
        return rest[1:end]
    # Unquoted: a `#` preceded by whitespace starts a comment; otherwise it's
    # part of the value.
    match = re.search(r"\s+#", rest)
    if match:
        rest = rest[: match.start()]
    return rest.rstrip()


def parse_env_file(text: str) -> dict[str, str]:
    """Parse the contents of a `.env` file into a dict.

    Quoting rules:
      - Single or double quotes wrap a value verbatim (no escape processing).
        Anything after the closing quote on the same line is discarded.
      - Unquoted values stop at the first whitespace-prefixed `#` (comment).
      - A leading `#` on a line marks the entire line as a comment.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        match = _KEY_RE.match(raw_line)
        if not match:
            continue
        result[match.group("key")] = _parse_value(match.group("rest"))
    return result


def load_dotenv(path: Path, *, override: bool = False) -> dict[str, str]:
    """Load a `.env` file into `os.environ` and return what was loaded.

    If `path` does not exist, returns an empty dict.
    Existing values in `os.environ` are preserved unless `override=True`.
    """
    if not path.is_file():
        return {}
    parsed = parse_env_file(path.read_text(encoding="utf-8"))
    applied: dict[str, str] = {}
    for key, value in parsed.items():
        if key in os.environ and not override:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def load_dotenvs_for(project_dir: Path | None, repo_root: Path) -> dict[str, str]:
    """Load repo-root `.env`, then project `.env`, into `os.environ`.

    Project values override repo-root values. Existing shell environment values
    win over both. Returns the union of what was set.
    """
    applied: dict[str, str] = {}
    applied.update(load_dotenv(repo_root / ".env"))
    if project_dir is not None:
        applied.update(load_dotenv(project_dir / ".env", override=True))
    return applied
