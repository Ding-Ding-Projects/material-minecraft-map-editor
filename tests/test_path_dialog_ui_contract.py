"""Static contract checks for the shared Material 3 path picker."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_path_picker_uses_persisted_language_resources_and_m3_hook():
    source = (ROOT / "amulet_map_editor/api/wx/ui/path_dialog.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "path.en.choose_folder",
        "path.zh.choose_folder",
        "_copy(\"browse\", self._language_mode)",
    ):
        assert marker in source + resources
