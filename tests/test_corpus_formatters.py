"""Tests for reddit_researcher.corpus_formatters."""

from __future__ import annotations

import pytest

from reddit_researcher.corpus_formatters import VALID_CORPUS_FORMATS, format_corpus


def test_valid_corpus_formats_set() -> None:
    assert VALID_CORPUS_FORMATS == {"compact", "conversational", "structured-json"}


def test_format_corpus_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unknown corpus format"):
        format_corpus(mode="subreddit", fmt="yaml", posts=[], comments=[])


def test_format_corpus_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown corpus mode"):
        format_corpus(mode="firehose", fmt="compact", posts=[], comments=[])
