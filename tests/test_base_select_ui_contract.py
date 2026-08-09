"""Static contract checks for the block/entity selector surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_base_selector_uses_persisted_language_resources_and_m3_hook():
    source = (ROOT / "amulet_map_editor/api/wx/ui/base_select.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "base_select.en.namespace",
        "base_select.zh.namespace",
        "_copy(\"search\", self._language_mode)",
    ):
        assert marker in source + resources
