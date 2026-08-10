from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")


def test_font_search_has_adjacent_builder_and_bounds():
    assert "Installed font regex builder" in SOURCE
    assert 'sample="Installed font family"' in SOURCE
    assert "query[:4096]" in SOURCE


def test_appearance_preset_search_has_adjacent_builder_and_bounds():
    assert "Appearance preset regex builder" in SOURCE
    assert 'sample="Appearance preset name"' in SOURCE
    assert "_preset_search_flags" in SOURCE
