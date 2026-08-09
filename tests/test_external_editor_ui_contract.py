import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
SOURCE_PATH = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"


class ExternalEditorUiContractTestCase(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(self.source)
        dialog = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        self.methods = {
            node.name: ast.get_source_segment(self.source, node)
            for node in dialog.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_preferences_exposes_browse_validate_and_persisted_editor(self):
        build = self.methods["_build_appearance_tab"]
        for required in (
            "external_editor.load_selected",
            "External editor executable",
            "external_editor_browse",
            "external_editor_test",
            "_browse_external_editor",
            "_test_external_editor",
        ):
            self.assertIn(required, build)
        browse = self.methods["_browse_external_editor"]
        self.assertIn("choose_path", browse)
        self.assertIn("Code executables", browse)
        self.assertIn("external_editor.validate_editor_path", browse)
        save = self.methods["_save"]
        self.assertIn("external_editor_path=self.external_editor_path.GetValue()", save)


if __name__ == "__main__":
    unittest.main()
