#!/usr/bin/env python3
"""Validate that a downloaded full package is a safe Squirrel delta base."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
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
_RELEASE_ENTRY = re.compile(
    r"^(?P<sha1>[0-9a-fA-F]{40})\s+"
    r"(?P<filename>\S+)\s+"
    r"(?P<size>\d+)"
    r"(?:\s+#\s+(?P<staging>\d{1,3})%)?$"
)
_MAX_RELEASES_BYTES = 256 * 1024


@dataclass(frozen=True)
class Version:
    core: tuple[int, int, int]
    label: str | None


@dataclass(frozen=True)
class ReleaseEntry:
    sha1: str
    filename: str
    size: int


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


def parse_release_index(releases: Path) -> tuple[ReleaseEntry, ...]:
    """Parse the bounded Squirrel v2 RELEASES format without resolving URLs."""

    if releases.name != "RELEASES":
        raise ValueError("delta base index must be named RELEASES")
    size = releases.stat().st_size
    if size <= 0:
        raise ValueError("delta base RELEASES index is empty")
    if size > _MAX_RELEASES_BYTES:
        raise ValueError(
            f"delta base RELEASES index exceeds {_MAX_RELEASES_BYTES} bytes"
        )
    try:
        text = releases.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("delta base RELEASES index is not valid UTF-8") from error

    entries: list[ReleaseEntry] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _RELEASE_ENTRY.fullmatch(line)
        if not match:
            raise ValueError(f"invalid RELEASES entry on line {line_number}")
        filename = match.group("filename")
        # Squirrel supports absolute HTTP URLs, but a downloaded release pair
        # must use the immutable asset's literal basename. Accepting a URL here
        # would let the index name one payload while the workflow validates
        # another local file.
        if "/" in filename or "\\" in filename or ":" in filename:
            raise ValueError(
                f"delta base RELEASES entry must use a filename: {filename}"
            )
        entry_size = int(match.group("size"))
        if entry_size <= 0:
            raise ValueError(
                f"delta base RELEASES entry has invalid size on line {line_number}"
            )
        staging = match.group("staging")
        if staging is not None and int(staging) > 100:
            raise ValueError(
                f"delta base RELEASES entry has invalid staging percentage on line {line_number}"
            )
        entries.append(
            ReleaseEntry(
                sha1=match.group("sha1").lower(),
                filename=filename,
                size=entry_size,
            )
        )
    if not entries:
        raise ValueError("delta base RELEASES index has no entries")
    return tuple(entries)


def _sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_release_pair(releases: Path, package: Path) -> ReleaseEntry:
    """Require one RELEASES entry that exactly describes the local package."""

    entries = parse_release_index(releases)
    matches = [entry for entry in entries if entry.filename == package.name]
    if len(matches) != 1:
        raise ValueError(
            "delta base RELEASES index must contain exactly one entry for "
            f"{package.name}; found {len(matches)}"
        )
    entry = matches[0]
    actual_size = package.stat().st_size
    if entry.size != actual_size:
        raise ValueError(
            f"delta base RELEASES size mismatch: {entry.size} != {actual_size}"
        )
    actual_sha1 = _sha1(package)
    if entry.sha1 != actual_sha1:
        raise ValueError(
            f"delta base RELEASES SHA-1 mismatch: {entry.sha1} != {actual_sha1}"
        )
    return entry


def write_single_release_index(entry: ReleaseEntry, destination: Path) -> None:
    """Write only the validated delta base so Squirrel cannot select stale rows."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        f"{entry.sha1} {entry.filename} {entry.size}\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


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
    parser.add_argument("--releases", required=True, type=Path)
    parser.add_argument(
        "--output-releases",
        type=Path,
        help="write a one-entry validated RELEASES index for Squirrel releasify",
    )
    args = parser.parse_args()
    try:
        version = validate_delta_base(args.package, args.current)
        entry = validate_release_pair(args.releases, args.package)
        if args.output_releases:
            write_single_release_index(entry, args.output_releases)
        print(version)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
