"""Static contract checks for the platform/version selector."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_version_selector_uses_language_resources_and_m3_traversal():
    source = (ROOT / "amulet_map_editor/api/wx/ui/version_select.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "version_select.en.platform",
        "version_select.zh.format",
        "_copy(\"version\", self._language_mode)",
    ):
        assert marker in source + resources
