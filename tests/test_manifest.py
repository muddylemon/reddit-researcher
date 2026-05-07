from reddit_researcher.manifest import MANIFEST_SCHEMA_VERSION, read_schema_version, stamp


def test_stamp_adds_schema_version_to_empty_manifest() -> None:
    manifest: dict = {}
    stamped = stamp(manifest)
    assert stamped is manifest
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION


def test_stamp_overwrites_existing_schema_version() -> None:
    manifest: dict = {"schema_version": 0, "mode": "subreddit"}
    stamp(manifest)
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["mode"] == "subreddit"


def test_read_schema_version_defaults_to_zero_when_missing() -> None:
    assert read_schema_version({}) == 0
    assert read_schema_version({"mode": "search"}) == 0


def test_read_schema_version_handles_garbage() -> None:
    assert read_schema_version({"schema_version": "abc"}) == 0
    assert read_schema_version({"schema_version": None}) == 0
    assert read_schema_version({"schema_version": 3}) == 3


from reddit_researcher.manifest import normalize_manifest


def test_normalize_v1_subreddit_run_synthesizes_subreddits_list() -> None:
    raw = {
        "schema_version": 1,
        "mode": "subreddit",
        "subreddit": "cannabis",
        "post_count": 25,
        "comment_count": 140,
        "status": "complete",
    }
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["cannabis"]
    assert normalized["per_subreddit"] == {
        "cannabis": {"post_count": 25, "comment_count": 140, "status": "complete"},
    }
    # Original fields preserved.
    assert normalized["subreddit"] == "cannabis"
    assert normalized["mode"] == "subreddit"


def test_normalize_v0_subreddit_run_with_missing_schema_version() -> None:
    raw = {"mode": "subreddit", "subreddit": "x", "post_count": 1, "comment_count": 0}
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["x"]
    assert "x" in normalized["per_subreddit"]


def test_normalize_v2_multi_sub_passthrough() -> None:
    raw = {
        "schema_version": 2,
        "mode": "subreddit",
        "subreddits": ["a", "b"],
        "per_subreddit": {
            "a": {"post_count": 5, "comment_count": 10, "status": "complete"},
            "b": {"post_count": 7, "comment_count": 12, "status": "complete"},
        },
        "post_count": 12,
        "comment_count": 22,
    }
    normalized = normalize_manifest(raw)
    assert normalized["subreddits"] == ["a", "b"]
    assert normalized["per_subreddit"]["b"]["post_count"] == 7


def test_normalize_search_mode_untouched() -> None:
    raw = {"schema_version": 1, "mode": "search", "subreddits": ["fitness"]}
    normalized = normalize_manifest(raw)
    # subreddits in search mode is the allowlist, not a multi-sub list — leave alone.
    assert normalized["subreddits"] == ["fitness"]
    assert "per_subreddit" not in normalized
