"""Static contract checks for the native NBT editor migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nbt_editor_uses_language_mode_and_material3_hook():
    source = (ROOT / "amulet_map_editor/api/wx/ui/nbt_editor.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "nbt.en.edit_title",
        "nbt.zh.edit_title",
        "_copy(\"commit\", self._language_mode)",
    ):
        assert marker in source + resources
