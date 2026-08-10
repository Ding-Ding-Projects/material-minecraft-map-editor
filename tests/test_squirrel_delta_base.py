from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from scripts import validate_squirrel_delta_base as delta_validation
from scripts.validate_squirrel_delta_base import (
    is_strictly_older,
    parse_release_index,
    parse_version,
    validate_delta_base,
    validate_release_pair,
    validate_sha256,
    validate_source_match,
    write_single_release_index,
)

NUSPEC = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2010/07/nuspec.xsd">
  <metadata><id>{package_id}</id><version>{version}</version></metadata>
</package>
"""


class SquirrelDeltaBaseTests(unittest.TestCase):
    def _package(
        self,
        root: Path,
        version: str,
        *,
        package_id: str = "Amulet",
        metadata_version: str | None = None,
    ) -> Path:
        path = root / f"Amulet-{version}-full.nupkg"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "Amulet.nuspec",
                NUSPEC.format(
                    package_id=package_id,
                    version=metadata_version or version,
                ),
            )
            archive.writestr("lib/net45/Amulet.exe", b"fixture")
        return path

    def _releases(
        self,
        root: Path,
        package: Path,
        *,
        filename: str | None = None,
        sha1: str | None = None,
        size: int | None = None,
        extra: str = "",
    ) -> Path:
        path = root / "RELEASES"
        digest = hashlib.sha1(package.read_bytes(), usedforsecurity=False).hexdigest()
        line = (
            f"{sha1 or digest} {filename or package.name} "
            f"{package.stat().st_size if size is None else size}"
        )
        path.write_text(f"{extra}{line}\n", encoding="utf-8")
        return path

    def test_strict_order_supports_monotonic_dev_and_stable_release(self):
        self.assertTrue(
            is_strictly_older(
                parse_version("0.10.0-dev414"), parse_version("0.10.0-dev415")
            )
        )
        self.assertTrue(
            is_strictly_older(parse_version("0.10.0-dev414"), parse_version("0.10.75"))
        )
        self.assertFalse(
            is_strictly_older(parse_version("0.10.75"), parse_version("0.10.0-dev415"))
        )

    def test_valid_package_is_accepted(self):
        with TemporaryDirectory() as directory:
            package = self._package(Path(directory), "0.10.0-dev414")
            self.assertEqual(
                "0.10.0-dev414",
                validate_delta_base(package, "0.10.0-dev415"),
            )

    def test_valid_release_pair_is_accepted_and_staged_without_stale_rows(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._package(root, "0.10.0-dev414")
            releases = self._releases(
                root,
                package,
                extra=("0" * 40 + " Amulet-0.10.0-dev413-delta.nupkg 99\n"),
            )
            entry = validate_release_pair(releases, package)
            staged = root / "staged" / "RELEASES"
            write_single_release_index(entry, staged)

            self.assertEqual(package.name, entry.filename)
            self.assertEqual((entry,), parse_release_index(staged))
            self.assertNotIn("dev413", staged.read_text(encoding="utf-8"))

    def test_release_pair_rejects_hash_size_and_filename_mismatches(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._package(root, "0.10.0-dev414")
            cases = (
                ({"sha1": "0" * 40}, "SHA-1 mismatch"),
                ({"size": package.stat().st_size + 1}, "size mismatch"),
                (
                    {"filename": "Amulet-0.10.0-dev413-full.nupkg"},
                    "exactly one entry",
                ),
            )
            for options, expected in cases:
                with self.subTest(expected=expected):
                    releases = self._releases(root, package, **options)
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_release_pair(releases, package)

    def test_release_pair_rejects_duplicate_or_malformed_index_entries(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._package(root, "0.10.0-dev414")
            releases = self._releases(root, package)
            line = releases.read_text(encoding="utf-8")
            releases.write_text(line + line, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one entry"):
                validate_release_pair(releases, package)

            releases.write_text("this is not a Squirrel feed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid RELEASES entry"):
                validate_release_pair(releases, package)

    def test_equal_or_newer_package_is_rejected(self):
        with TemporaryDirectory() as directory:
            package = self._package(Path(directory), "0.10.0-dev415")
            with self.assertRaisesRegex(ValueError, "not strictly older"):
                validate_delta_base(package, "0.10.0-dev415")

    def test_wrong_package_identity_is_rejected(self):
        with TemporaryDirectory() as directory:
            package = self._package(
                Path(directory), "0.10.0-dev414", package_id="Other"
            )
            with self.assertRaisesRegex(ValueError, "package id"):
                validate_delta_base(package, "0.10.0-dev415")

    def test_filename_and_metadata_must_agree(self):
        with TemporaryDirectory() as directory:
            package = self._package(
                Path(directory), "0.10.0-dev414", metadata_version="0.10.0-dev413"
            )
            with self.assertRaisesRegex(ValueError, "versions differ"):
                validate_delta_base(package, "0.10.0-dev415")

    def test_corrupt_archive_is_rejected(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "Amulet-0.10.0-dev414-full.nupkg"
            package.write_bytes(b"not a zip archive")
            with self.assertRaisesRegex(ValueError, "not a valid NuGet package"):
                validate_delta_base(package, "0.10.0-dev415")

    def test_github_asset_sha256_is_optional_but_exact_when_present(self):
        with TemporaryDirectory() as directory:
            package = self._package(Path(directory), "0.10.0-dev414")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()

            validate_sha256(package, None, "delta base package")
            validate_sha256(package, f"sha256:{digest}", "delta base package")
            with self.assertRaisesRegex(ValueError, "metadata is malformed"):
                validate_sha256(package, "sha256:not-a-digest", "delta base package")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                validate_sha256(
                    package,
                    "sha256:" + ("0" * 64),
                    "delta base package",
                )

    def test_release_source_must_match_legacy_or_monotonic_package_version(self):
        validate_source_match("0.10.0-dev426", "0.10.0-dev.426", "automated")
        validate_source_match("0.10.100426", "0.10.0-dev.426", "automated")
        validate_source_match("0.10.76", "0.10.76", "stable")
        with self.assertRaisesRegex(ValueError, "does not match release source"):
            validate_source_match("0.10.0-dev424", "0.10.0-dev.426", "automated")

    def test_release_source_rejects_reserved_stable_and_unbounded_automation(self):
        with self.assertRaisesRegex(ValueError, "reserved automated range"):
            validate_source_match("0.10.100427", "0.10.100427", "stable")
        with self.assertRaisesRegex(ValueError, "supported maximum"):
            validate_source_match("0.10.1000000", "0.10.0-dev.900000", "automated")
        with self.assertRaisesRegex(ValueError, "patch zero"):
            validate_source_match("0.10.100427", "0.10.1-dev.427", "automated")

    def test_package_download_size_is_bounded(self):
        with TemporaryDirectory() as directory:
            package = self._package(Path(directory), "0.10.0-dev414")
            with patch.object(
                delta_validation,
                "_MAX_PACKAGE_BYTES",
                package.stat().st_size - 1,
            ):
                with self.assertRaisesRegex(ValueError, "package exceeds"):
                    validate_delta_base(package, "0.10.0-dev415")

    def test_archive_extracted_size_is_bounded(self):
        with TemporaryDirectory() as directory:
            package = self._package(Path(directory), "0.10.0-dev414")
            with patch.object(delta_validation, "_MAX_EXTRACTED_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "extracted bytes"):
                    validate_delta_base(package, "0.10.0-dev415")

    def test_archive_member_paths_cannot_escape_staging(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "Amulet-0.10.0-dev414-full.nupkg"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    "Amulet.nuspec",
                    NUSPEC.format(package_id="Amulet", version="0.10.0-dev414"),
                )
                archive.writestr("../outside.txt", "fixture")
            with self.assertRaisesRegex(ValueError, "unsafe member path"):
                validate_delta_base(package, "0.10.0-dev415")


if __name__ == "__main__":
    unittest.main()
