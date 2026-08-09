"""Static contract checks for the native offline changelog surface."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")
FRAME = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
    encoding="utf-8"
)


class ChangelogUiContractTestCase(unittest.TestCase):
    def test_native_dialog_has_required_filters_and_export(self):
        for marker in (
            "class ChangelogDialog",
            "self.start_date",
            "self.end_date",
            "wx.adv.DatePickerCtrl",
            "self.start_picker",
            "self.end_picker",
            "_picker_changed",
            "self.regex",
            "export_markdown",
        ):
            self.assertIn(marker, UI)

    def test_changelog_is_reachable_from_menu_and_palette(self):
        self.assertIn('"Changelog…": self._open_changelog', FRAME)
        self.assertIn('("Changelog…", self._open_changelog)', FRAME)

    def test_invalid_filters_are_reported_without_network(self):
        self.assertIn('self.feedback.SetLabel(f"Invalid filter:', UI)
        self.assertNotIn("requests.", UI)
        self.assertNotIn("urllib.", UI)


if __name__ == "__main__":
    unittest.main()
