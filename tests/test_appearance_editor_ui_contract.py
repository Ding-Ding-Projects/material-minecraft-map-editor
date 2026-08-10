import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).parents[1] / "amulet_map_editor/api/wx/ui/preferences.py"


class AppearanceEditorUiContractTestCase(unittest.TestCase):
    def test_native_surface_has_font_search_preview_and_colour_translation(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        dialog = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        build = next(
            node
            for node in dialog.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_build_appearance_tab"
        )
        body = ast.get_source_segment(source, build)
        for required in (
            "font_search",
            "font_regex",
            "font_choice",
            "font_preview",
            "_filter_appearance_fonts",
            "accent_colour_picker",
            "accent_rgb",
            "accent_hsl",
            "accent_contrast",
            "_update_accent_controls",
        ):
            self.assertIn(required, body)
        self.assertIn("appearance_editor.parse_hex", source)
        self.assertIn("appearance_editor.contrast_summary", source)
        self.assertIn("query[:4096]", source)
        self.assertIn('flags=getattr(self, "_font_search_flags", 0)', source)

    def test_appearance_form_still_round_trips_through_existing_preset_values(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("appearance_presets.AppearanceValues(", source)
        self.assertIn("accent=self.accent.GetValue().strip()", source)
        self.assertIn("self._update_accent_controls(values.accent)", source)
        self.assertIn("self._reset_appearance_property", source)
        self.assertIn("self._reset_appearance_form", source)


if __name__ == "__main__":
    unittest.main()
