import unittest

from scripts.normalize_release_tag import normalize_release_tag


class ReleaseTagTests(unittest.TestCase):
    def test_empty_input_uses_fallback(self):
        self.assertEqual(normalize_release_tag("", "0.10.0-dev.42"), "0.10.0-dev.42")

    def test_strips_fully_qualified_tag_ref(self):
        self.assertEqual(normalize_release_tag("refs/tags/v0.10.77", "fallback"), "v0.10.77")

    def test_preserves_valid_release_tag_verbatim(self):
        self.assertEqual(normalize_release_tag("v0.10.77-rc1", "fallback"), "v0.10.77-rc1")

    def test_rejects_shell_metacharacters(self):
        with self.assertRaises(ValueError):
            normalize_release_tag("0.10.77; echo compromised", "fallback")


if __name__ == "__main__":
    unittest.main()
