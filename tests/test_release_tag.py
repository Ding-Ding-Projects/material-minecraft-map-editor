import unittest

from scripts.normalize_release_tag import normalize_release_tag


class ReleaseTagTests(unittest.TestCase):
    def test_empty_input_uses_fallback(self):
        self.assertEqual(normalize_release_tag("", "0.10.0-dev.42"), "0.10.0-dev.42")

    def test_preserves_canonical_stable_and_automated_tags(self):
        self.assertEqual(normalize_release_tag("0.10.77", "0.10.0-dev.1"), "0.10.77")
        self.assertEqual(
            normalize_release_tag("0.10.0-dev.426", "0.10.0-dev.1"),
            "0.10.0-dev.426",
        )

    def test_rejects_aliases_that_updater_would_reject(self):
        for alias in (
            "v0.10.77",
            "refs/tags/0.10.77",
            "0.10.0-dev426",
            "0.10.0-dev-426",
            "0.10.0-Dev.426",
        ):
            with self.subTest(alias=alias):
                with self.assertRaises(ValueError):
                    normalize_release_tag(alias, "0.10.0-dev.1")

    def test_rejects_release_package_version_collision(self):
        with self.assertRaisesRegex(ValueError, "different package identity"):
            normalize_release_tag(
                "0.10.0-dev.427",
                "0.10.0-dev.1",
                expected_version="0.10.100426",
            )
        with self.assertRaisesRegex(ValueError, "built canonical source tag"):
            normalize_release_tag(
                "0.10.0-dev.427",
                "0.10.0-dev.1",
                expected_source="0.10.0-dev.426",
            )

    def test_matching_release_and_package_identity_is_accepted(self):
        self.assertEqual(
            normalize_release_tag(
                "0.10.0-dev.426",
                "0.10.0-dev.1",
                expected_source="0.10.0-dev.426",
                expected_version="0.10.100426",
            ),
            "0.10.0-dev.426",
        )

    def test_rejects_shell_metacharacters(self):
        with self.assertRaises(ValueError):
            normalize_release_tag("0.10.77; echo compromised", "fallback")


if __name__ == "__main__":
    unittest.main()
