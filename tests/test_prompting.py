from pathlib import Path

from reddit_researcher.prompting import (
    build_chunk_prompt,
    build_corpus,
    build_search_corpus,
    build_synthesis_prompt,
    chunk_text,
    load_terms,
    quote_search_term,
    scope_label_for,
)


def test_chunk_text_splits_large_input() -> None:
    text = "A" * 50 + "\n\n" + "B" * 50 + "\n\n" + "C" * 50
    chunks = chunk_text(text, max_chars=60)
    assert len(chunks) == 3
    assert chunks[0] == "A" * 50


def test_build_corpus_includes_posts_and_comments() -> None:
    corpus = build_corpus(
        posts=[
            {
                "id": "post1",
                "title": "Question about magnesium",
                "author": "alice",
                "score": 12,
                "num_comments": 3,
                "link_flair_text": "Question",
                "selftext": "Does this help sleep?",
            }
        ],
        comments=[
            {
                "id": "comment1",
                "post_id": "post1",
                "depth": 0,
                "score": 5,
                "body": "I had the same question.",
            }
        ],
    )
    assert "[POST post1]" in corpus
    assert "[COMMENT comment1]" in corpus


def test_prompt_builders_embed_key_context() -> None:
    chunk_prompt = build_chunk_prompt(
        scope_label="r/Supplements",
        prompt_text="Find recurring questions.",
        chunk_text_value="[POST post1] title: Hello",
        chunk_index=1,
        chunk_count=2,
    )
    synthesis_prompt = build_synthesis_prompt(
        scope_label="r/Supplements",
        prompt_text="Find recurring questions.",
        chunk_outputs=["Theme 1", "Theme 2"],
    )
    assert "r/Supplements" in chunk_prompt
    assert "chunk 1 of 2" in chunk_prompt
    assert "Theme 1" in synthesis_prompt


def test_load_terms_ignores_blank_lines_and_comments(tmp_path: Path) -> None:
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text(
        "\nDr Jockers\t\n# comment\n\nDavid Perlmutter\n",
        encoding="utf-8",
    )

    assert load_terms(terms_file) == ["Dr Jockers", "David Perlmutter"]


def test_quote_search_term_wraps_names_for_exact_search() -> None:
    assert quote_search_term("Dr Jockers") == '"Dr Jockers"'


def test_build_search_corpus_groups_posts_by_search_term() -> None:
    corpus = build_search_corpus(
        posts=[
            {
                "id": "post1",
                "search_term": "Dr Jockers",
                "subreddit": "keto",
                "title": "Thoughts on Dr Jockers?",
                "author": "alice",
                "score": 42,
                "num_comments": 7,
                "permalink": "/r/keto/comments/post1/thoughts/",
                "url": "https://www.reddit.com/r/keto/comments/post1/thoughts/",
                "selftext": "Is this a meaningful source?",
                "comments": [
                    {
                        "id": "comment1",
                        "post_id": "post1",
                        "depth": 0,
                        "score": 5,
                        "body": "People are discussing the expert directly.",
                    }
                ],
            }
        ]
    )

    assert "## Search term: Dr Jockers" in corpus
    assert "[POST post1] r/keto title: Thoughts on Dr Jockers?" in corpus
    assert "url: https://www.reddit.com/r/keto/comments/post1/thoughts/" in corpus
    assert "[COMMENT comment1] post=post1 depth=0 score=5" in corpus


def test_scope_label_distinguishes_modes() -> None:
    assert scope_label_for(subreddit="Supplements", search_terms=None) == "r/Supplements"
    assert scope_label_for(subreddit=None, search_terms=["alice"]) == "a global Reddit search"
    assert scope_label_for(subreddit="keto", search_terms=["alice"]) == "a Reddit search across r/keto"


def test_scope_label_for_single_sub_via_list() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["Supplements"]) == "r/Supplements"


def test_scope_label_for_two_subs_uses_and() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["a", "b"]) == "r/a and r/b"


def test_scope_label_for_three_subs_oxford_comma() -> None:
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=["a", "b", "c"]) == "r/a, r/b, r/c"


def test_scope_label_for_many_subs_truncates() -> None:
    subs = ["a", "b", "c", "d", "e", "f", "g"]
    assert scope_label_for(subreddit=None, search_terms=None, subreddits=subs) == "r/a, r/b, r/c, and 4 others"


def test_scope_label_for_legacy_subreddit_arg_still_works() -> None:
    # Existing call sites pass `subreddit` only; behavior must be unchanged.
    assert scope_label_for(subreddit="Supplements", search_terms=None) == "r/Supplements"
