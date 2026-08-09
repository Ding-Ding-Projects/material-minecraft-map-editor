"""Resolve an Amulet source tag to a monotonic Squirrel.Windows version.

Legacy automatic packages used prerelease text such as ``0.10.0-dev154``.
Squirrel's updater can compare that suffix lexically and rank a new build below
the older stable ``0.10.76``. Keep the public source tag unchanged, but map a
bounded automatic run to a numeric patch above the legacy stable line.
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
AUTOMATED_PATCH_BASE = 100_000
AUTOMATED_RUN_LIMIT = 899_999
AUTOMATED_PATCH_LIMIT = AUTOMATED_PATCH_BASE + AUTOMATED_RUN_LIMIT


@dataclass(frozen=True)
class SquirrelVersionResolution:
    version: str
    channel: str
    source: str


def _resolve_candidate(value: str) -> SquirrelVersionResolution | None:
    stable = _STABLE.fullmatch(value)
    if stable:
        core = stable.group("core")
        patch = int(core.rsplit(".", 1)[1])
        if AUTOMATED_PATCH_BASE <= patch <= AUTOMATED_PATCH_LIMIT:
            raise ValueError(
                "stable patch enters the reserved automated range "
                f"{AUTOMATED_PATCH_BASE}..{AUTOMATED_PATCH_LIMIT}"
            )
        return SquirrelVersionResolution(core, "stable", core)

    dev = _DEV_BUILD.fullmatch(value)
    if dev:
        core = dev.group("core")
        major, minor, source_patch = core.split(".")
        if int(source_patch) != 0:
            raise ValueError("automated source tags must use patch zero")
        run = int(dev.group("run"))
        if run > AUTOMATED_RUN_LIMIT:
            return None
        return SquirrelVersionResolution(
            f"{major}.{minor}.{AUTOMATED_PATCH_BASE + run}",
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
    """Return a monotonic version accepted by Squirrel.Windows 2.0.1.

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
