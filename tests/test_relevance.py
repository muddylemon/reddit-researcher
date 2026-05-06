from reddit_researcher.relevance import RelevanceConfig, review_post_relevance


def test_review_post_relevance_includes_exact_match_with_keyword_context() -> None:
    review = review_post_relevance(
        {
            "id": "post1",
            "search_term": "Dr Jockers",
            "subreddit": "keto",
            "title": "Dr Jockers and fasting glucose",
            "selftext": "",
            "comments": [],
        },
        RelevanceConfig(keywords=["glucose", "fasting"], allowed_subreddits={"keto"}),
    )

    assert review["decision"] == "include"
    assert "exact term in title/body" in review["reason"]


def test_review_post_relevance_excludes_allowed_subreddit_without_exact_match() -> None:
    review = review_post_relevance(
        {
            "id": "post1",
            "search_term": "Dr Casey Peavler",
            "subreddit": "keto",
            "title": "Casey at the clinic",
            "selftext": "general glucose discussion",
            "comments": [],
        },
        RelevanceConfig(keywords=["glucose"], allowed_subreddits={"keto"}),
    )

    assert review["decision"] == "exclude"


def test_review_post_relevance_excludes_disallowed_subreddit() -> None:
    review = review_post_relevance(
        {
            "id": "post1",
            "search_term": "Dr Jockers",
            "subreddit": "BollyBlindsNGossip",
            "title": "Dr Jockers and fasting glucose",
            "selftext": "",
            "comments": [],
        },
        RelevanceConfig(allowed_subreddits={"keto"}),
    )

    assert review["decision"] == "exclude"
    assert review["reason"] == "subreddit outside allowlist"


def test_review_post_relevance_no_filter_includes_everything() -> None:
    review = review_post_relevance(
        {
            "id": "post1",
            "search_term": "",
            "subreddit": "anything",
            "title": "any title",
            "selftext": "any body",
            "comments": [],
        },
        RelevanceConfig(),
    )

    assert review["decision"] == "include"
    assert review["reason"] == "no relevance filter configured"


def test_review_post_relevance_keyword_only_returns_review() -> None:
    review = review_post_relevance(
        {
            "id": "post1",
            "search_term": "",
            "subreddit": "anything",
            "title": "general glucose talk",
            "selftext": "",
            "comments": [],
        },
        RelevanceConfig(keywords=["glucose"]),
    )

    assert review["decision"] == "review"
    assert "project keyword present" in review["reason"]
