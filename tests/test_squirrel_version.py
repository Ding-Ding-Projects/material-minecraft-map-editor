import unittest

from scripts.normalize_squirrel_version import normalize_squirrel_version


class SquirrelVersionTests(unittest.TestCase):
    def test_dev_build_dot_suffix_becomes_single_legacy_prerelease_token(self):
        self.assertEqual(
            normalize_squirrel_version("0.10.0-dev.154", "0.10.0-dev.999"),
            "0.10.0-dev154",
        )

    def test_dev_build_hyphen_suffix_is_normalized(self):
        self.assertEqual(
            normalize_squirrel_version("v0.10.0-dev-154", "0.10.0-dev.999"),
            "0.10.0-dev154",
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
            "0.10.0-dev154",
        )


if __name__ == "__main__":
    unittest.main()
