"""Static contract checks for the native error-reporting surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_traceback_dialog_uses_m3_and_persisted_language_resources():
    source = (
        ROOT / "amulet_map_editor/api/wx/ui/traceback_dialog.py"
    ).read_text(encoding="utf-8")
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "traceback.en.copy_error",
        "traceback.zh.copy_error",
        "_copy(\"close\", self._language_mode)",
    ):
        assert marker in source + resources
