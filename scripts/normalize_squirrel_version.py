"""Validate an Amulet source tag and map it to a Squirrel.Windows version.

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

_COMPONENT = r"(?:0|[1-9]\d*)"
_STABLE = re.compile(
    rf"^(?P<major>{_COMPONENT})\.(?P<minor>{_COMPONENT})\." rf"(?P<patch>{_COMPONENT})$"
)
_DEV_BUILD = re.compile(
    rf"^(?P<major>{_COMPONENT})\.(?P<minor>{_COMPONENT})\."
    rf"(?P<patch>{_COMPONENT})-dev\.(?P<run>{_COMPONENT})$"
)
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
        patch = int(stable.group("patch"))
        if AUTOMATED_PATCH_BASE <= patch <= AUTOMATED_PATCH_LIMIT:
            raise ValueError(
                "stable patch enters the reserved automated range "
                f"{AUTOMATED_PATCH_BASE}..{AUTOMATED_PATCH_LIMIT}"
            )
        return SquirrelVersionResolution(value, "stable", value)

    dev = _DEV_BUILD.fullmatch(value)
    if dev:
        major = dev.group("major")
        minor = dev.group("minor")
        if int(dev.group("patch")) != 0:
            raise ValueError("automated source tags must use patch zero")
        run = int(dev.group("run"))
        if run > AUTOMATED_RUN_LIMIT:
            raise ValueError(
                f"automated run exceeds the supported maximum {AUTOMATED_RUN_LIMIT}"
            )
        return SquirrelVersionResolution(
            f"{major}.{minor}.{AUTOMATED_PATCH_BASE + run}",
            "automated",
            value,
        )
    return None


def resolve_squirrel_version(
    raw: str | None, fallback: str
) -> SquirrelVersionResolution:
    """Resolve package version, explicit channel, and canonical source tag."""

    candidate = raw if raw not in (None, "") else fallback
    resolution = _resolve_candidate(candidate)
    if resolution is None:
        raise ValueError(
            "source tag must be canonical major.minor.patch or " "major.minor.0-dev.run"
        )
    return resolution


def normalize_squirrel_version(raw: str | None, fallback: str) -> str:
    """Return a monotonic version accepted by Squirrel.Windows 2.0.1.

    The fallback is used only when the source tag is absent. Every supplied
    source tag is validated exactly; aliases never silently become a different
    published package identity.
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
