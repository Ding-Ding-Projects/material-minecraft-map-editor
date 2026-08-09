"""Normalize an Amulet version for Squirrel.Windows' legacy NuGet parser.

NuGet 6 can pack versions such as ``0.10.0-dev.154``, but Squirrel.Windows
2.0.1 reads the package with its older ``NuGet.SemanticVersion`` parser.  That
parser accepts a single prerelease token and rejects the dotted ``dev.154``
form.  Keep published stable versions unchanged and collapse only the bounded
CI dev-build shape into the equivalent single token.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import re

_STABLE = re.compile(r"^(?P<core>\d+\.\d+\.\d+)$")
_DEV_BUILD = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)-dev[.-]?(?P<run>\d+)$",
    re.IGNORECASE,
)
_SINGLE_PRERELEASE = re.compile(r"^(?P<core>\d+\.\d+\.\d+)-(?P<label>[0-9A-Za-z-]+)$")


@dataclass(frozen=True)
class SquirrelVersionResolution:
    version: str
    channel: str
    source: str


def _resolve_candidate(value: str) -> SquirrelVersionResolution | None:
    stable = _STABLE.fullmatch(value)
    if stable:
        core = stable.group("core")
        return SquirrelVersionResolution(core, "stable", core)

    dev = _DEV_BUILD.fullmatch(value)
    if dev:
        core = dev.group("core")
        run = dev.group("run")
        return SquirrelVersionResolution(
            f"{core}-dev{run}",
            "automated",
            f"{core}-dev.{run}",
        )

    prerelease = _SINGLE_PRERELEASE.fullmatch(value)
    if prerelease:
        core = prerelease.group("core")
        label = prerelease.group("label")
        family = re.match(r"[A-Za-z-]+", label)
        channel = "preview-" + (family.group(0).lower() if family else "other")
        return SquirrelVersionResolution(
            f"{core}-{label}",
            channel,
            f"{core}-{label}",
        )
    return None


def resolve_squirrel_version(
    raw: str | None, fallback: str
) -> SquirrelVersionResolution:
    """Resolve package version, explicit channel, and canonical source tag."""

    candidate = (raw or "").strip().lstrip("vV")
    fallback_candidate = fallback.strip().lstrip("vV")
    resolution = _resolve_candidate(candidate) if candidate else None
    if resolution is not None:
        return resolution
    fallback_resolution = _resolve_candidate(fallback_candidate)
    if fallback_resolution is not None:
        return fallback_resolution
    raise ValueError("fallback must be a Squirrel-compatible major.minor.patch version")


def normalize_squirrel_version(raw: str | None, fallback: str) -> str:
    """Return a version accepted by Squirrel.Windows 2.0.1.

    The fallback is normalized through the same rules.  Invalid or unsupported
    source tags intentionally use the deterministic fallback rather than
    guessing at a release version.
    """

    return resolve_squirrel_version(raw, fallback).version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="", help="release tag or source version")
    parser.add_argument("--fallback", required=True, help="deterministic CI fallback")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit version, explicit channel, and canonical source as JSON",
    )
    args = parser.parse_args()
    resolution = resolve_squirrel_version(args.raw, args.fallback)
    print(json.dumps(asdict(resolution)) if args.json else resolution.version)


if __name__ == "__main__":
    main()
