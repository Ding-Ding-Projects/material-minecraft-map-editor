#!/usr/bin/env python3
"""Select bounded, semantically nearest Squirrel delta-base release tags."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

_COMPONENT = r"(?:0|[1-9]\d*)"
_AUTOMATED = re.compile(
    rf"^(?P<major>{_COMPONENT})\.(?P<minor>{_COMPONENT})\."
    rf"(?P<patch>{_COMPONENT})-dev\.(?P<run>{_COMPONENT})$"
)
_STABLE = re.compile(
    rf"^(?P<major>{_COMPONENT})\.(?P<minor>{_COMPONENT})\." rf"(?P<patch>{_COMPONENT})$"
)
_AUTOMATED_ALIAS = re.compile(r"^v?\d+\.\d+\.\d+-dev[.-]?\d+$", re.IGNORECASE)
_STABLE_ALIAS = re.compile(r"^v?\d+\.\d+\.\d+$", re.IGNORECASE)
_MAX_INVENTORY_BYTES = 1024 * 1024
_MAX_RELEASES = 500
_AUTOMATED_PATCH_BASE = 100_000
_AUTOMATED_RUN_LIMIT = 899_999
_AUTOMATED_PATCH_LIMIT = _AUTOMATED_PATCH_BASE + _AUTOMATED_RUN_LIMIT


@dataclass(frozen=True, order=True)
class ChannelVersion:
    major: int
    minor: int
    patch: int
    sequence: int


def parse_channel_version(tag: str, channel: str) -> ChannelVersion | None:
    pattern = (
        _AUTOMATED
        if channel == "automated"
        else _STABLE if channel == "stable" else None
    )
    if pattern is None:
        raise ValueError(f"unsupported Squirrel release channel: {channel}")
    match = pattern.fullmatch(tag)
    if not match:
        alias_pattern = _AUTOMATED_ALIAS if channel == "automated" else _STABLE_ALIAS
        if alias_pattern.fullmatch(tag):
            raise ValueError(f"noncanonical {channel} release tag: {tag}")
        return None
    patch = int(match.group("patch"))
    if channel == "automated":
        run = int(match.group("run"))
        if patch != 0:
            raise ValueError("automated source tags must use patch zero")
        if run > _AUTOMATED_RUN_LIMIT:
            raise ValueError(
                f"automated run exceeds the supported maximum {_AUTOMATED_RUN_LIMIT}"
            )
    else:
        run = 0
        if _AUTOMATED_PATCH_BASE <= patch <= _AUTOMATED_PATCH_LIMIT:
            raise ValueError(
                "stable patch enters the reserved automated range "
                f"{_AUTOMATED_PATCH_BASE}..{_AUTOMATED_PATCH_LIMIT}"
            )
    return ChannelVersion(
        int(match.group("major")),
        int(match.group("minor")),
        patch,
        run,
    )


def select_candidates(
    inventory: object,
    *,
    current_source: str,
    channel: str,
    limit: int,
) -> tuple[str, ...]:
    """Return nearest older tags in one explicit channel and version series."""

    current = parse_channel_version(current_source, channel)
    if current is None:
        raise ValueError(
            f"current source {current_source!r} does not belong to channel {channel}"
        )
    if isinstance(inventory, dict):
        inventory = inventory.get("releases")
    if not isinstance(inventory, list):
        raise ValueError("release inventory must be a list")
    if len(inventory) > _MAX_RELEASES:
        raise ValueError(f"release inventory exceeds {_MAX_RELEASES} entries")

    candidates: list[tuple[ChannelVersion, str]] = []
    seen: set[str] = set()
    seen_versions: dict[ChannelVersion, str] = {}
    for item in inventory:
        if not isinstance(item, dict):
            raise ValueError("release inventory entries must be objects")
        if (
            "tagName" in item
            and "tag_name" in item
            and item["tagName"] != item["tag_name"]
        ):
            raise ValueError("release inventory has conflicting tag fields")
        tag = item.get("tagName", item.get("tag_name"))
        draft = item.get("isDraft", item.get("draft", False))
        if not isinstance(tag, str) or not isinstance(draft, bool):
            raise ValueError("release inventory has invalid tag or draft metadata")
        if draft:
            continue
        if tag in seen:
            raise ValueError(f"release inventory contains duplicate tag: {tag}")
        seen.add(tag)
        version = parse_channel_version(tag, channel)
        if version is None:
            continue
        prior_tag = seen_versions.get(version)
        if prior_tag is not None and prior_tag != tag:
            raise ValueError(
                f"release tags {prior_tag} and {tag} identify the same version"
            )
        seen_versions[version] = tag
        if (version.major, version.minor) != (current.major, current.minor):
            continue
        if version >= current:
            continue
        candidates.append((version, tag))
    candidates.sort(reverse=True)
    return tuple(tag for _version, tag in candidates[:limit])


def _read_inventory() -> Any:
    data = sys.stdin.buffer.read(_MAX_INVENTORY_BYTES + 1)
    if len(data) > _MAX_INVENTORY_BYTES:
        raise ValueError(f"release inventory exceeds {_MAX_INVENTORY_BYTES} bytes")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"release inventory is not valid UTF-8 JSON: {error}"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-source", required=True)
    parser.add_argument("--channel", choices=("automated", "stable"), required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 9), default=8)
    args = parser.parse_args()
    try:
        inventory = _read_inventory()
        for tag in select_candidates(
            inventory,
            current_source=args.current_source,
            channel=args.channel,
            limit=args.limit,
        ):
            print(tag)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
