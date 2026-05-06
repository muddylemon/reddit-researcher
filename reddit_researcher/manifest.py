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

MANIFEST_SCHEMA_VERSION = 1


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
