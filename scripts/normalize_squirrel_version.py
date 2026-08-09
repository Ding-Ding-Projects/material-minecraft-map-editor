"""Normalize an Amulet version for Squirrel.Windows' legacy NuGet parser.

NuGet 6 can pack versions such as ``0.10.0-dev.154``, but Squirrel.Windows
2.0.1 reads the package with its older ``NuGet.SemanticVersion`` parser.  That
parser accepts a single prerelease token and rejects the dotted ``dev.154``
form.  Keep published stable versions unchanged and collapse only the bounded
CI dev-build shape into the equivalent single token.
"""

from __future__ import annotations

import argparse
import re


_STABLE = re.compile(r"^(?P<core>\d+\.\d+\.\d+)$")
_DEV_BUILD = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)-dev[.-]?(?P<run>\d+)$",
    re.IGNORECASE,
)
_SINGLE_PRERELEASE = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)-(?P<label>[0-9A-Za-z-]+)$"
)


def normalize_squirrel_version(raw: str | None, fallback: str) -> str:
    """Return a version accepted by Squirrel.Windows 2.0.1.

    The fallback is normalized through the same rules.  Invalid or unsupported
    source tags intentionally use the deterministic fallback rather than
    guessing at a release version.
    """

    candidate = (raw or "").strip().lstrip("vV")
    fallback_candidate = fallback.strip().lstrip("vV")

    stable = _STABLE.fullmatch(candidate)
    if stable:
        return stable.group("core")

    dev = _DEV_BUILD.fullmatch(candidate)
    if dev:
        return f"{dev.group('core')}-dev{dev.group('run')}"

    prerelease = _SINGLE_PRERELEASE.fullmatch(candidate)
    if prerelease:
        return f"{prerelease.group('core')}-{prerelease.group('label')}"

    fallback_stable = _STABLE.fullmatch(fallback_candidate)
    if fallback_stable:
        return fallback_stable.group("core")
    fallback_dev = _DEV_BUILD.fullmatch(fallback_candidate)
    if fallback_dev:
        return f"{fallback_dev.group('core')}-dev{fallback_dev.group('run')}"
    fallback_prerelease = _SINGLE_PRERELEASE.fullmatch(fallback_candidate)
    if fallback_prerelease:
        return f"{fallback_prerelease.group('core')}-{fallback_prerelease.group('label')}"

    raise ValueError("fallback must be a Squirrel-compatible major.minor.patch version")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="", help="release tag or source version")
    parser.add_argument("--fallback", required=True, help="deterministic CI fallback")
    args = parser.parse_args()
    print(normalize_squirrel_version(args.raw, args.fallback))


if __name__ == "__main__":
    main()
