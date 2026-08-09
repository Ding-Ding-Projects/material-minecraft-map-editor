from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from scripts.validate_squirrel_delta_base import (
    is_strictly_older,
    parse_version,
    validate_delta_base,
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


if __name__ == "__main__":
    unittest.main()
