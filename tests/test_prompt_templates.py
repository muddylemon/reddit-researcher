import pytest

from reddit_researcher.prompt_templates import (
    BUILTIN_TEMPLATES,
    default_template_for,
    list_templates,
    template_description,
    template_path,
    template_text,
)


def test_every_builtin_template_has_a_readable_file() -> None:
    for name in BUILTIN_TEMPLATES:
        path = template_path(name)
        assert path.is_file(), f"missing template file for {name}: {path}"
        body = template_text(name)
        assert body.strip(), f"template {name} is empty"


def test_template_description_strips_leading_hash() -> None:
    desc = template_description("question-mining")
    assert desc
    assert not desc.startswith("#")


def test_unknown_template_raises() -> None:
    with pytest.raises(KeyError):
        template_path("not-a-real-template")


def test_default_template_for_modes() -> None:
    assert default_template_for("subreddit") == "question-mining"
    assert default_template_for("search") == "sentiment-comparison"


def test_list_templates_returns_triples() -> None:
    triples = list_templates()
    assert triples
    for name, mode, description in triples:
        assert name in BUILTIN_TEMPLATES
        assert mode in {"subreddit", "search"}
        assert description
