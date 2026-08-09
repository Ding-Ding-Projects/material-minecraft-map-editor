import os
import tempfile
import time
import unittest


class _Backend:
    def __init__(self):
        self.calls = []

    def speak(self, text, language):
        self.calls.append((text, language))


class NarratorTestCase(unittest.TestCase):
    def setUp(self):
        self._config_dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = self._config_dir.name
        from amulet_map_editor.api import tts_narrator

        self.narrator_module = tts_narrator

    def tearDown(self):
        self._config_dir.cleanup()

    def test_settings_are_off_by_default_and_bounded(self):
        settings = self.narrator_module.load_settings()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.language, "english")
        self.assertEqual(
            self.narrator_module.update_settings(
                enabled=True,
                language="both",
                category_cooldown_seconds=99999,
                debounce_seconds=-5,
            ).category_cooldown_seconds,
            3600.0,
        )
        self.assertEqual(self.narrator_module.load_settings().debounce_seconds, 0.0)

    def test_debounced_events_replace_same_category_and_both_is_serial(self):
        backend = _Backend()
        settings = self.narrator_module.NarratorSettings(
            enabled=True,
            language="both",
            category_cooldown_seconds=0,
            debounce_seconds=0.05,
        )
        narrator = self.narrator_module.Narrator(backend, settings)
        try:
            narrator.announce("update", "old", "舊", funny_level_english=1)
            narrator.announce("update", "new", "新", funny_level_english=3)
            self.assertTrue(narrator.flush(timeout=2))
            self.assertEqual(
                [language for _text, language in backend.calls],
                ["english", "cantonese"],
            )
            self.assertTrue(backend.calls[0][0].startswith("new"))
            self.assertNotIn("old", " ".join(text for text, _language in backend.calls))
        finally:
            narrator.close()

    def test_category_cooldown_keeps_latest_event(self):
        backend = _Backend()
        settings = self.narrator_module.NarratorSettings(
            enabled=True, category_cooldown_seconds=0.2, debounce_seconds=0
        )
        narrator = self.narrator_module.Narrator(backend, settings)
        try:
            narrator.announce("save", "first", "第一")
            self.assertTrue(narrator.flush(timeout=2))
            narrator.announce("save", "second", "第二")
            time.sleep(0.05)
            self.assertEqual(len(backend.calls), 1)
            self.assertTrue(narrator.flush(timeout=2))
            self.assertEqual(len(backend.calls), 2)
            self.assertEqual(backend.calls[-1][0], "second")
        finally:
            narrator.close()

    def test_style_text_never_changes_level_one_facts(self):
        style_text = self.narrator_module.style_text
        self.assertEqual(style_text("Saved 3 files", "english", 1), "Saved 3 files")
        self.assertIn("Saved 3 files", style_text("Saved 3 files", "english", 5))
        self.assertIn("檔案", style_text("已儲存 3 個檔案", "cantonese", 5))

    def test_null_backend_is_safe(self):
        backend = self.narrator_module.default_backend()
        backend.speak("offline", "cantonese")
        self.assertFalse(backend.available)


if __name__ == "__main__":
    unittest.main()
