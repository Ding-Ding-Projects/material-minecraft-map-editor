"""Static contract checks for the language-selection dialog chrome."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_language_selector_has_named_actions_and_m3_traversal():
    source = (ROOT / "amulet_map_editor/api/framework/pages/main_menu.py").read_text(
        encoding="utf-8"
    )
    resources = (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8")
    for marker in (
        'lang.get("language_select.ok")',
        'lang.get("language_select.cancel")',
        "apply_material3(self)",
        "language_select.ok=Apply",
        "language_select.cancel=Cancel",
    ):
        assert marker in source + resources
