import unittest

from scripts.normalize_squirrel_version import (
    AUTOMATED_PATCH_LIMIT,
    AUTOMATED_PATCH_BASE,
    normalize_squirrel_version,
    resolve_squirrel_version,
)


class SquirrelVersionTests(unittest.TestCase):
    def test_dev_build_dot_suffix_becomes_monotonic_numeric_patch(self):
        self.assertEqual(
            normalize_squirrel_version("0.10.0-dev.154", "0.10.0-dev.999"),
            "0.10.100154",
        )

    def test_dev_build_hyphen_suffix_is_normalized(self):
        self.assertEqual(
            normalize_squirrel_version("v0.10.0-dev-154", "0.10.0-dev.999"),
            "0.10.100154",
        )

    def test_stable_release_is_preserved(self):
        self.assertEqual(
            normalize_squirrel_version("v0.10.74", "0.10.0-dev.154"),
            "0.10.74",
        )

    def test_single_token_release_prerelease_is_preserved(self):
        self.assertEqual(
            normalize_squirrel_version("v0.10.75-rc1", "0.10.0-dev.154"),
            "0.10.75-rc1",
        )

    def test_invalid_source_uses_deterministic_fallback(self):
        self.assertEqual(
            normalize_squirrel_version("not-a-version", "0.10.0-dev.154"),
            "0.10.100154",
        )

    def test_automated_build_ranks_above_legacy_stable_and_keeps_source_tag(self):
        resolution = resolve_squirrel_version("0.10.0-dev.426", "0.10.0-dev.999")
        self.assertEqual("0.10.100426", resolution.version)
        self.assertEqual("0.10.0-dev.426", resolution.source)
        self.assertEqual("automated", resolution.channel)
        self.assertGreater(int(resolution.version.rsplit(".", 1)[1]), 76)
        self.assertEqual(100_000, AUTOMATED_PATCH_BASE)

    def test_automated_range_boundaries_and_rejected_run_fallback(self):
        self.assertEqual(
            "0.10.999999",
            normalize_squirrel_version("0.10.0-dev.899999", "0.10.0-dev.1"),
        )
        self.assertEqual(999_999, AUTOMATED_PATCH_LIMIT)
        self.assertEqual(
            "0.10.100001",
            normalize_squirrel_version("0.10.0-dev.900000", "0.10.0-dev.1"),
        )
        with self.assertRaisesRegex(ValueError, "fallback must be"):
            normalize_squirrel_version("0.10.0-dev.900000", "0.10.0-dev.900000")

    def test_stable_patch_cannot_collide_with_reserved_automated_range(self):
        self.assertEqual(
            "0.10.99999",
            normalize_squirrel_version("0.10.99999", "0.10.0-dev.1"),
        )
        with self.assertRaisesRegex(ValueError, "reserved automated range"):
            normalize_squirrel_version("0.10.100427", "0.10.0-dev.1")

    def test_automated_source_patch_must_be_zero(self):
        with self.assertRaisesRegex(ValueError, "patch zero"):
            normalize_squirrel_version("0.10.1-dev.427", "0.10.0-dev.1")


if __name__ == "__main__":
    unittest.main()
