#!/usr/bin/env python3
"""Validate that a downloaded full package is a safe Squirrel delta base."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
from xml.etree import ElementTree
import zipfile

_VERSION = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<label>[0-9A-Za-z-]+))?$"
)
_PACKAGE = re.compile(
    r"^Amulet-(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+)?)-full\.nupkg$"
)
_NUMBERED_LABEL = re.compile(r"^(?P<prefix>[A-Za-z-]+)(?P<number>\d+)$")


@dataclass(frozen=True)
class Version:
    core: tuple[int, int, int]
    label: str | None


def parse_version(value: str) -> Version:
    match = _VERSION.fullmatch(value.strip())
    if not match:
        raise ValueError(f"unsupported Squirrel version: {value}")
    return Version(
        (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
        ),
        match.group("label"),
    )


def is_strictly_older(previous: Version, current: Version) -> bool:
    if previous.core != current.core:
        return previous.core < current.core
    if previous.label is None:
        return False
    if current.label is None:
        return True
    previous_label = _NUMBERED_LABEL.fullmatch(previous.label)
    current_label = _NUMBERED_LABEL.fullmatch(current.label)
    return bool(
        previous_label
        and current_label
        and previous_label.group("prefix").casefold()
        == current_label.group("prefix").casefold()
        and int(previous_label.group("number")) < int(current_label.group("number"))
    )


def _metadata_text(root: ElementTree.Element, name: str) -> str:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name:
            return (element.text or "").strip()
    return ""


def validate_delta_base(package: Path, current_version: str) -> str:
    match = _PACKAGE.fullmatch(package.name)
    if not match:
        raise ValueError("delta base must be named Amulet-<version>-full.nupkg")
    filename_version = match.group("version")
    previous = parse_version(filename_version)
    current = parse_version(current_version)
    if not is_strictly_older(previous, current):
        raise ValueError(
            f"delta base {filename_version} is not strictly older than {current_version}"
        )

    try:
        with zipfile.ZipFile(package) as archive:
            corrupt = archive.testzip()
            if corrupt:
                raise ValueError(f"delta base contains a corrupt member: {corrupt}")
            nuspecs = [
                name for name in archive.namelist() if name.lower().endswith(".nuspec")
            ]
            if len(nuspecs) != 1:
                raise ValueError(
                    "delta base must contain exactly one NuGet specification"
                )
            root = ElementTree.fromstring(archive.read(nuspecs[0]))
    except (zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValueError(f"delta base is not a valid NuGet package: {error}") from error

    package_id = _metadata_text(root, "id")
    package_version = _metadata_text(root, "version")
    if package_id != "Amulet":
        raise ValueError(
            f"delta base package id must be Amulet, got {package_id or '<empty>'}"
        )
    if package_version != filename_version:
        raise ValueError(
            "delta base filename and NuGet metadata versions differ: "
            f"{filename_version} != {package_version or '<empty>'}"
        )
    return filename_version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, help="normalized current version")
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(validate_delta_base(args.package, args.current))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
