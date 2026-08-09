import os
import tempfile
import unittest


class NotificationHistoryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._config_dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = cls._config_dir.name
        from amulet_map_editor.api import notifications

        cls.notifications = notifications

    @classmethod
    def tearDownClass(cls):
        cls._config_dir.cleanup()

    def test_add_search_bulk_dismiss_and_exports(self):
        first = self.notifications.add(
            "warning",
            "World copy",
            "Backup exists | ready",
            details="Error:\nworld copy stopped\n\nTraceback:\nline one\nline two",
        )
        second = self.notifications.add("info", "Exported", "The file is ready")
        self.assertEqual(len(self.notifications.search("world")), 1)
        self.assertEqual(len(self.notifications.search("Backup", regex=True)), 1)
        self.assertEqual(self.notifications.bulk_dismiss([first.notification_id]), 1)
        self.assertEqual(
            len(self.notifications.list_notifications(include_dismissed=False)), 1
        )
        self.assertIn("\\|", self.notifications.export_markdown())
        self.assertIn(
            "Traceback:\nline one\nline two", self.notifications.export_markdown()
        )
        self.assertIn(second.notification_id, self.notifications.export_json())
        self.assertEqual(
            self.notifications.list_notifications()[0].details,
            "Error:\nworld copy stopped\n\nTraceback:\nline one\nline two",
        )

    def test_invalid_values_are_bounded(self):
        with self.assertRaises(ValueError):
            self.notifications.add("debug", "Title", "Body")
        with self.assertRaises(ValueError):
            self.notifications.add("error", "", "Body")
        with self.assertRaises(ValueError):
            self.notifications.search("[", regex=True)
        with self.assertRaises(ValueError):
            self.notifications.add("error", "Title", "Body", details="bad\x00detail")
        with self.assertRaises(ValueError):
            self.notifications.add(
                "error",
                "Title",
                "Body",
                details="x" * (self.notifications.MAX_DETAILS_LENGTH + 1),
            )

    def test_exception_bridge_preserves_traceback_and_escapes_controls(self):
        from amulet_map_editor.api.wx.nonblocking import notify_exception

        item = notify_exception(
            object(),
            "Operation failed",
            "bad value\x00",
            "Traceback line one\nTraceback line two\x1b",
        )
        self.assertEqual(item.severity, "error")
        self.assertIn("bad value\\x00", item.details)
        self.assertIn("Traceback line one\nTraceback line two\\x1b", item.details)

    def test_notification_copy_honors_language_and_each_funny_level(self):
        from amulet_map_editor.api import (
            notification_copy,
            preferences,
            school_mode,
        )

        english = []
        cantonese = []
        for level in range(1, 6):
            preferences.update(language_mode="english", funny_level_english=level)
            english.append(notification_copy.notification_text("details.available"))
            preferences.update(language_mode="cantonese", funny_level_cantonese=level)
            cantonese.append(notification_copy.notification_text("details.available"))
        self.assertEqual(len(set(english)), 5)
        self.assertEqual(len(set(cantonese)), 5)
        self.assertIn("Notification history", english[0])
        self.assertIn("通知紀錄", cantonese[0])

        preferences.update(
            language_mode="bilingual",
            funny_level_english=1,
            funny_level_cantonese=1,
        )
        bilingual = notification_copy.notification_text("details.technical")
        self.assertIn("Full technical details", bilingual)
        self.assertIn("完整技術詳情", bilingual)

        preferences.update(
            language_mode="bilingual",
            funny_level_english=5,
            funny_level_cantonese=5,
        )
        school_mode.set_unlock_credential("1234")
        school_mode.enable()
        projected = notification_copy.notification_text("details.available")
        self.assertEqual(
            projected,
            "Full details are available in Notification history. "
            "The editor remains available.",
        )
        self.assertTrue(school_mode.unlock("1234"))

    def test_oversized_exception_details_are_truncated_without_throwing(self):
        from amulet_map_editor.api.wx.nonblocking import notify_exception

        item = notify_exception(
            object(),
            "Large failure",
            "The operation failed",
            "trace line\n" * self.notifications.MAX_DETAILS_LENGTH,
        )
        self.assertLessEqual(len(item.details), self.notifications.MAX_DETAILS_LENGTH)
        self.assertIn("were truncated", item.details)


if __name__ == "__main__":
    unittest.main()
