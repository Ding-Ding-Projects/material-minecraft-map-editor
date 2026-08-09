import os
import tempfile
import unittest


class PreferencesAndRegexTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._config_dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._config_dir.name
        from amulet_map_editor.api import preferences, regex_builder

        cls.preferences = preferences
        cls.regex_builder = regex_builder

    @classmethod
    def tearDownClass(cls):
        cls._config_dir.cleanup()

    def test_preferences_are_bounded_and_persisted(self):
        prefs = self.preferences.update(
            display_name="  My Map Studio  ",
            language_mode="bilingual",
            funny_level_english=99,
            funny_level_cantonese=0,
            ui_scale=9,
        )
        self.assertEqual(prefs.language_mode, "bilingual")
        self.assertEqual(prefs.display_name, "My Map Studio")
        self.assertEqual(prefs.funny_level_english, 5)
        self.assertEqual(prefs.funny_level_cantonese, 1)
        self.assertEqual(prefs.ui_scale, 2.0)
        self.assertEqual(self.preferences.load().language_mode, "bilingual")
        self.assertEqual(self.preferences.load().display_name, "My Map Studio")

    def test_display_name_is_bounded_and_reset_independently(self):
        self.assertEqual(
            self.preferences.format_window_title(
                "0.10.0", display_name="Map Workshop", source=True
            ),
            "Map Workshop 0.10.0 (source)",
        )
        for invalid in ("", "   ", "line\nbreak", "x" * 65, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.preferences.validate_display_name(invalid)

        self.preferences.update(display_name="Cartographer", theme="dark")
        reset = self.preferences.reset_display_name()
        self.assertEqual(reset.display_name, self.preferences.DEFAULT_DISPLAY_NAME)
        self.assertEqual(reset.theme, "dark")

    def test_unknown_preference_is_rejected(self):
        with self.assertRaises(KeyError):
            self.preferences.update(not_a_setting=True)

    def test_plain_text_and_regex_modes(self):
        plain = self.regex_builder.RegexBuilder("a+b", regex_enabled=False)
        self.assertEqual(plain.search(["a+b", "aaab"]), ["a+b"])
        regex = self.regex_builder.RegexBuilder(r"a+b", regex_enabled=True)
        self.assertEqual(regex.search(["a+b", "aaab"]), ["aaab"])

    def test_invalid_pattern_and_capture_groups(self):
        invalid = self.regex_builder.RegexBuilder("[", regex_enabled=True).validate()
        self.assertFalse(invalid.valid)
        result = self.regex_builder.RegexBuilder(
            r"(x)(y)", regex_enabled=True
        ).evaluate("xy")
        self.assertTrue(result.valid)
        self.assertEqual(result.matches, ("xy",))
        self.assertEqual(result.groups, (("x", "y"),))


if __name__ == "__main__":
    unittest.main()
