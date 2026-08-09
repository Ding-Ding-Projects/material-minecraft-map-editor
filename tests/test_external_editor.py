import os
from pathlib import Path
import tempfile
import unittest

from amulet_map_editor.api import external_editor


class ExternalEditorTestCase(unittest.TestCase):
    def test_discovery_is_deterministic_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            path_editor = root_path / "code.cmd"
            path_editor.write_text("", encoding="utf-8")
            env = {
                "USERPROFILE": root,
                "LOCALAPPDATA": root,
                "ProgramFiles": root,
                "ProgramFiles(x86)": root,
            }

            def which(name):
                return str(path_editor) if name in {"code", "code.cmd"} else None

            found = external_editor.discover_editors(
                environ=env, platform="win32", which=which
            )
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].path, path_editor.resolve())
            self.assertEqual(found[0].source, "PATH")

    def test_select_and_open_folder_uses_workspace_root(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            editor = root_path / "Code.exe"
            folder = root_path / "export"
            folder.mkdir()
            editor.write_text("", encoding="utf-8")
            previous = os.environ.get("CONFIG_DIR")
            os.environ["CONFIG_DIR"] = str(root_path / "profile")
            calls = []
            try:
                selected = external_editor.select_editor(editor)
                self.assertTrue(selected.ok)
                self.assertEqual(external_editor.load_selected(), str(editor.resolve()))

                result = external_editor.open_path(
                    folder,
                    runner=lambda command, **kwargs: calls.append((command, kwargs)),
                )
            finally:
                if previous is None:
                    os.environ.pop("CONFIG_DIR", None)
                else:
                    os.environ["CONFIG_DIR"] = previous
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "opened")
            self.assertEqual(calls[0][0][0], str(editor.resolve()))
            self.assertEqual(
                calls[0][0][1:],
                ("--reuse-window", "--folder-uri", folder.resolve().as_uri()),
            )

    def test_missing_editor_and_target_are_safe_results(self):
        missing = external_editor.validate_editor_path("C:/does-not-exist/Code.exe")
        self.assertFalse(missing.ok)
        self.assertEqual(missing.status, "unavailable")
        target = external_editor.open_path("C:/does-not-exist/export")
        self.assertFalse(target.ok)
        self.assertEqual(target.status, "invalid_target")


if __name__ == "__main__":
    unittest.main()
