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
