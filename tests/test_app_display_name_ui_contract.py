import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFERENCES_UI = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"
AMULET_UI = ROOT / "amulet_map_editor/api/framework/amulet_ui.py"


class AppDisplayNameUIContractTestCase(unittest.TestCase):
    """wx-free checks for the native identity-control wiring."""

    def test_preferences_dialog_exposes_painted_name_and_reset_controls(self):
        source = PREFERENCES_UI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        dialog = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        dialog_source = ast.get_source_segment(source, dialog) or ""
        # The identity controls are painted rather than native. Pinning
        # "wx.TextCtrl" here is what a check for this contract used to do,
        # and it made the test forbid the very migration the project asked
        # for: the field kept its behaviour, its max length, its validation
        # and its reset, and the assertion failed anyway because the class
        # name changed. What the contract is actually about is that the
        # dialog has a bounded, validated, resettable display-name control.
        self.assertIn("self.display_name = forms.MaterialTextField", dialog_source)
        self.assertIn("self.display_name_reset = studio.StudioButton", dialog_source)
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

    def test_main_menu_masthead_uses_the_persisted_display_name(self):
        source = (
            ROOT / "amulet_map_editor/api/framework/pages/main_menu.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "from amulet_map_editor.api import image, lang, preferences", source
        )
        self.assertIn(
            "self._amulet_name.SetLabel(preferences.load().display_name)", source
        )


if __name__ == "__main__":
    unittest.main()
