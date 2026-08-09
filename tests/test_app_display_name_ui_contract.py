import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFERENCES_UI = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"
AMULET_UI = ROOT / "amulet_map_editor/api/framework/amulet_ui.py"


class AppDisplayNameUIContractTestCase(unittest.TestCase):
    """wx-free checks for the native identity-control wiring."""

    def test_preferences_dialog_exposes_native_name_and_reset_controls(self):
        source = PREFERENCES_UI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        dialog = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        dialog_source = ast.get_source_segment(source, dialog) or ""
        self.assertIn("self.display_name = wx.TextCtrl", dialog_source)
        self.assertIn("self.display_name_reset = wx.Button", dialog_source)
        self.assertIn("preferences.MAX_DISPLAY_NAME_LENGTH", dialog_source)
        self.assertIn("preferences.validate_display_name", dialog_source)
        self.assertIn("refresh_display_identity", dialog_source)

    def test_main_frame_uses_display_name_but_stable_ids_remain_literal(self):
        source = AMULET_UI.read_text(encoding="utf-8")
        self.assertIn("preferences.format_window_title", source)
        self.assertIn("def refresh_display_identity", source)
        self.assertIn("self.SetTitle(self._format_display_title(display_name))", source)

        package_identity = (ROOT / "amulet_map_editor/__init__.py").read_text(
            encoding="utf-8"
        )
        for stable_identifier in ('"AmuletMapEditor"', '"AmuletTeam"'):
            self.assertIn(stable_identifier, package_identity)


if __name__ == "__main__":
    unittest.main()
