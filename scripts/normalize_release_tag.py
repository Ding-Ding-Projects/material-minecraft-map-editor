"""Validate a canonical release tag against the built Squirrel identity."""

from __future__ import annotations

import os

try:
    from scripts.normalize_squirrel_version import resolve_squirrel_version
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from normalize_squirrel_version import resolve_squirrel_version


def normalize_release_tag(
    raw: str | None,
    fallback: str,
    *,
    expected_source: str | None = None,
    expected_version: str | None = None,
) -> str:
    """Return the exact canonical source tag that produced the built package.

    The fallback is used only when no event/manual tag was supplied. Aliases,
    unsupported channels, and any source/package identity mismatch fail closed
    before a release API call can publish assets the updater will reject.
    """

    resolution = resolve_squirrel_version(raw, fallback)
    if expected_source is not None and resolution.source != expected_source:
        raise ValueError("release tag did not match the built canonical source tag")
    if expected_version is not None and resolution.version != expected_version:
        raise ValueError("release tag would collide with a different package identity")
    return resolution.source


def main() -> None:
    print(
        normalize_release_tag(
            os.environ.get("RELEASE_TAG_INPUT"),
            os.environ.get("RELEASE_TAG_FALLBACK", ""),
            expected_source=os.environ.get("RELEASE_TAG_EXPECTED_SOURCE") or None,
            expected_version=os.environ.get("RELEASE_TAG_EXPECTED_VERSION") or None,
        )
    )


if __name__ == "__main__":
    main()
