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
        first = self.notifications.add("warning", "World copy", "Backup exists | ready")
        second = self.notifications.add("info", "Exported", "The file is ready")
        self.assertEqual(len(self.notifications.search("world")), 1)
        self.assertEqual(len(self.notifications.search("Backup", regex=True)), 1)
        self.assertEqual(self.notifications.bulk_dismiss([first.notification_id]), 1)
        self.assertEqual(len(self.notifications.list_notifications(include_dismissed=False)), 1)
        self.assertIn("\\|", self.notifications.export_markdown())
        self.assertIn(second.notification_id, self.notifications.export_json())

    def test_invalid_values_are_bounded(self):
        with self.assertRaises(ValueError):
            self.notifications.add("debug", "Title", "Body")
        with self.assertRaises(ValueError):
            self.notifications.add("error", "", "Body")
        with self.assertRaises(ValueError):
            self.notifications.search("[", regex=True)


if __name__ == "__main__":
    unittest.main()
