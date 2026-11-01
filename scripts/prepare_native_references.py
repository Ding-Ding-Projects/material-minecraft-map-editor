"""Prepare a pinned native reference profile without downloads or execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


PROFILE = "vanilla-java-1.20.1"
ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ("reports/blocks.json", 4915308,
     "f10d5da83ec8cd995d4f484b788c5b1467a490728e687c629a681450e3253017"),
    ("reports/registries.json", 381349,
     "3702ca0119f46233c387dda959b42c549daa42b759fc049d834e1012028323f4"),
    ("registry-source-receipt.json", 864,
     "8f81ca9b461bad9c371d9fb1bdec7165ada5c0ebb9802982015ed0dddbcb4cde"),
    ("java-geometry-reference-evidence.json", 2881,
     "88b22690a55926aa1e6b3cc4a29ca52107a1699983d7a36a504c4d8ef1320a21"),
)


class PreparationError(ValueError):
    """A bounded error code, without private paths or file contents."""


def regular(info):
    return (stat.S_ISREG(info.st_mode)
            and not (getattr(info, "st_file_attributes", 0) & 0x400))


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def read_pinned(path: Path, size: int, digest: str) -> bytes:
    before = path.lstat()
    if not regular(before) or before.st_size != size:
        raise PreparationError("reference_type_or_size_mismatch")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not regular(opened) or identity(opened) != identity(before):
            raise PreparationError("reference_changed")
        data = stream.read(size + 1)
        after = os.fstat(stream.fileno())
    if (identity(after) != identity(before)
            or identity(path.lstat()) != identity(before)):
        raise PreparationError("reference_changed")
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise PreparationError("reference_hash_mismatch")
    return data


def validate_directory(path: Path):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise PreparationError("directory_not_regular")


def prepare(reports: Path, destination: Path) -> dict:
    """Use explicitly selected stable directories; not a hostile-path sandbox."""
    validate_directory(reports)
    validate_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise PreparationError("destination_exists")
    sources = (
        reports / "blocks.json",
        reports / "registries.json",
        ROOT / "docs/compatibility/java-1201-registry-producer-receipt.json",
        ROOT / "docs/compatibility/java-geometry-reference-evidence.json",
    )
    # Validate every source before creating anything. Do not normalize bytes.
    payloads = [read_pinned(source, size, digest)
                for source, (_, size, digest) in zip(sources, FILES)]
    created = False
    try:
        destination.mkdir(exist_ok=False)
        created = True
        (destination / "reports").mkdir(exist_ok=False)
        for (relative, size, digest), data in zip(FILES, payloads):
            target = destination / relative
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            read_pinned(target, size, digest)
    except (OSError, PreparationError):
        # Keep owned partial output for inspection; never delete caller paths.
        if created:
            raise PreparationError("incomplete_destination_retained") from None
        raise PreparationError("destination_creation_failed") from None
    return {"status": "prepared", "profile": PROFILE,
            "filesVerified": len(FILES), "bytesVerified": sum(x[1] for x in FILES),
            "downloaded": False, "generatorExecuted": False,
            "worldCompatibilityVerified": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", required=True, type=Path,
                        help="Explicit directory containing the two official reports")
    parser.add_argument("--destination", required=True, type=Path,
                        help="New directory under an existing stable parent")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.reports, args.destination)
    except PreparationError as error:
        result = {"status": "unavailable", "reason": str(error)}
    except OSError:
        result = {"status": "unavailable", "reason": "reference_io_unavailable"}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "prepared" else 1


if __name__ == "__main__":
    sys.exit(main())
