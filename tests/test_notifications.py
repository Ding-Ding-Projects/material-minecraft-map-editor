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


if __name__ == "__main__":
    unittest.main()
