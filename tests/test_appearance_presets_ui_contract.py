import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
PREFERENCES_UI = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"


class AppearancePresetsUiContractTestCase(unittest.TestCase):
    def setUp(self):
        self.source = PREFERENCES_UI.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.dialog = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        self.methods = {
            node.name: node
            for node in self.dialog.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def method_source(self, name: str) -> str:
        return ast.get_source_segment(self.source, self.methods[name])

    def test_appearance_tab_has_native_preset_and_reset_controls(self):
        build = self.method_source("_build_appearance_tab")
        for required in (
            "wx.ScrolledWindow",
            "appearance_preset_list",
            "appearance_preset_name",
            "appearance_preset_load",
            "appearance_preset_save",
            "appearance_preset_update",
            "appearance_preset_export",
            "appearance_preset_import",
            "appearance_reset_property",
            "appearance_reset_selected",
            "appearance_reset_all",
            "appearance_status",
            "SetName",
            "SetScrollRate",
            "wx.WrapSizer",
        ):
            self.assertIn(required, build)
        for method in (
            "_load_appearance_preset",
            "_save_appearance_preset",
            "_update_appearance_preset",
            "_export_appearance_preset",
            "_import_appearance_preset",
            "_reset_appearance_property",
            "_reset_appearance_form",
        ):
            self.assertIn(method, self.methods)
            self.assertIn(method, build)

    def test_domain_load_save_apply_and_invalid_storage_guard_are_wired(self):
        init = self.method_source("__init__")
        self.assertIn("appearance_presets.load_presets()", init)
        self.assertIn("AppearancePresetValidationError", init)

        save_preset = self.method_source("_save_appearance_preset")
        self.assertIn("self._appearance_values_from_form()", save_preset)
        self.assertIn("appearance_presets.save_preset", save_preset)
        self.assertIn("replace=False", save_preset)

        update_preset = self.method_source("_update_appearance_preset")
        self.assertIn("appearance_presets.save_preset", update_preset)
        self.assertIn("replace=True", update_preset)

        load_preset = self.method_source("_load_appearance_preset")
        self.assertIn("self._set_appearance_form(preset.values)", load_preset)

        build = self.method_source("_build_appearance_tab")
        self.assertIn("control.Enable(False)", build)
        self.assertIn("were left unchanged", build)
        guarded_refreshes = [
            node
            for node in self.methods["_build_appearance_tab"].body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "self._appearance_load_error is None"
        ]
        self.assertEqual(len(guarded_refreshes), 1)
        self.assertIn(
            "self._refresh_appearance_presets()",
            ast.get_source_segment(self.source, guarded_refreshes[0]),
        )

    def test_import_export_are_bounded_native_file_flows(self):
        exported = self.method_source("_export_appearance_preset")
        self.assertIn("wx.FileDialog", exported)
        self.assertIn("wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT", exported)
        self.assertIn("appearance_presets.export_preset", exported)
        self.assertIn('encoding="utf-8"', exported)

        imported = self.method_source("_import_appearance_preset")
        self.assertIn("wx.FileDialog", imported)
        self.assertIn("wx.FD_OPEN | wx.FD_FILE_MUST_EXIST", imported)
        self.assertIn("appearance_presets.MAX_IMPORT_BYTES", imported)
        self.assertIn(".read(appearance_presets.MAX_IMPORT_BYTES + 1)", imported)
        self.assertIn("appearance_presets.import_preset", imported)

    def test_resets_stage_values_until_ok_and_save_reuses_validation(self):
        property_reset = self.method_source("_reset_appearance_property")
        all_reset = self.method_source("_reset_appearance_form")
        save = self.method_source("_save")
        self.assertIn("appearance_presets.SHIPPED_APPEARANCE", property_reset)
        self.assertIn("appearance_presets.SHIPPED_APPEARANCE", all_reset)
        self.assertNotIn("preferences.reset", property_reset + all_reset)
        self.assertIn("self._appearance_values_from_form()", save)
        self.assertIn("self._appearance_tab_index", save)
        self.assertIn("AppearancePresetValidationError", save)


if __name__ == "__main__":
    unittest.main()
