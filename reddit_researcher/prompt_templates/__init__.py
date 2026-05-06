"""Built-in prompt templates exposed via `reddit-researcher init --template`.

Each template is a Markdown file in this package. The first line of each file
is treated as a one-line description (after stripping a leading `#`) and shown
in `reddit-researcher init --list-templates`.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

# (template_id, recommended_mode). Mode is advisory — templates can run in either
# mode if the user accepts the tradeoffs.
BUILTIN_TEMPLATES: dict[str, str] = {
    "question-mining": "subreddit",
    "theme-extraction": "subreddit",
    "sentiment-comparison": "search",
    "tool-evaluation": "search",
    "product-research": "search",
    "expert-mention": "search",
}


def template_path(name: str) -> Path:
    """Return the on-disk path to a built-in template file."""
    if name not in BUILTIN_TEMPLATES:
        raise KeyError(f"Unknown template: {name!r}. Try `reddit-researcher init --list-templates`.")
    files = resources.files(__name__)
    return Path(str(files.joinpath(f"{name}.md")))


def template_text(name: str) -> str:
    """Return the prompt text for a built-in template."""
    return template_path(name).read_text(encoding="utf-8")


def template_description(name: str) -> str:
    """Return the one-line description (first non-blank line, stripped of `#`)."""
    for line in template_text(name).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.lstrip("#").strip()
    return ""


def default_template_for(mode: str) -> str:
    """Return the default template id for a given scrape mode."""
    return "question-mining" if mode == "subreddit" else "sentiment-comparison"


def list_templates() -> list[tuple[str, str, str]]:
    """Return `(name, mode, description)` triples for every built-in template."""
    return [(name, mode, template_description(name)) for name, mode in sorted(BUILTIN_TEMPLATES.items())]
