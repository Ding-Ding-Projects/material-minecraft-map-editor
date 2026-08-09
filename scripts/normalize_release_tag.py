"""Normalize a release-event tag without evaluating event data as shell code."""

from __future__ import annotations

import os
import re


_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def normalize_release_tag(raw: str | None, fallback: str) -> str:
    """Return a bounded GitHub release tag, or the deterministic fallback.

    The workflow supplies both values through environment variables.  A
    ``refs/tags/`` prefix is accepted because event integrations sometimes
    provide the fully-qualified ref, but the release API receives only the
    tag name.  Unsupported values fail closed instead of becoming shell
    syntax or an accidental release target.
    """

    candidate = (raw or "").strip()
    if candidate.startswith("refs/tags/"):
        candidate = candidate[len("refs/tags/") :]
    if not candidate:
        candidate = fallback.strip()
    if not _TAG.fullmatch(candidate):
        raise ValueError("release tag contains unsupported characters or is too long")
    return candidate


def main() -> None:
    print(
        normalize_release_tag(
            os.environ.get("RELEASE_TAG_INPUT"),
            os.environ.get("RELEASE_TAG_FALLBACK", ""),
        )
    )


if __name__ == "__main__":
    main()
