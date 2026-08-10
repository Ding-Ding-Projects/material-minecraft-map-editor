"""Static contract checks for the block-property selector surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_property_selectors_use_language_resources_and_m3_hooks():
    source = (
        ROOT / "amulet_map_editor/api/wx/ui/block_select/properties.py"
    ).read_text(encoding="utf-8")
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        "preferences.load().language_mode",
        "apply_material3(self)",
        "properties.en.name",
        "properties.zh.invalid",
        '_copy("not_valid", self._language_mode)',
    ):
        assert marker in source + resources
