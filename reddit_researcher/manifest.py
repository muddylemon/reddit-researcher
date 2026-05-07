"""Manifest schema constants and helpers.

Every run folder has a `manifest.json` describing the run. To let future versions
of the tool migrate or reject older runs without guessing, every manifest carries
a `schema_version` integer.

Versioning policy:

- The current schema version is `MANIFEST_SCHEMA_VERSION`.
- Manifests written before this constant existed (pre-0.1.0) implicitly have
  `schema_version = 0`. Code that reads manifests should treat a missing field
  as 0 and continue.
- Bump `MANIFEST_SCHEMA_VERSION` whenever a *required* field is added, removed,
  or changes meaning. Adding optional fields does not require a bump.
- Keep the bump small: a +1 step per breaking change, with a CHANGELOG entry
  describing the diff and any migration guidance.
"""

from __future__ import annotations

from typing import Any

MANIFEST_SCHEMA_VERSION = 2


def stamp(manifest: dict[str, Any]) -> dict[str, Any]:
    """Stamp a manifest dict with the current schema version.

    Mutates and returns the input for ergonomic chaining at write sites.
    """
    manifest["schema_version"] = MANIFEST_SCHEMA_VERSION
    return manifest


def read_schema_version(manifest: dict[str, Any]) -> int:
    """Return the manifest's `schema_version`, defaulting to 0 if absent.

    Older runs (pre-0.1.0) wrote manifests without this field; treat them as v0.
    """
    value = manifest.get("schema_version", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the manifest with subreddit-mode fields normalized.

    Older subreddit-mode manifests carried only `subreddit` (string). The
    multi-subreddit feature added `subreddits` (list) and `per_subreddit`
    (per-sub counters). To let the rest of the codebase assume one shape,
    this synthesizes both fields from the legacy form.

    Search-mode manifests (where `subreddits` is the search allowlist) are
    returned unchanged.
    """
    result = dict(manifest)
    if result.get("mode") != "subreddit":
        return result

    if "subreddits" not in result and "subreddit" in result:
        result["subreddits"] = [result["subreddit"]]

    if "per_subreddit" not in result:
        subs = result.get("subreddits") or ([result["subreddit"]] if "subreddit" in result else [])
        if subs:
            # For legacy single-sub runs, attribute all counters to the one sub.
            single = subs[0] if len(subs) == 1 else None
            result["per_subreddit"] = {
                sub: {
                    "post_count": result.get("post_count", 0) if sub == single else 0,
                    "comment_count": result.get("comment_count", 0) if sub == single else 0,
                    "status": result.get("status", "unknown") if sub == single else "unknown",
                }
                for sub in subs
            }
    return result
