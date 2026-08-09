from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")


def test_font_search_has_adjacent_builder_and_bounds():
    assert 'label=_chrome_copy("appearance.regex.button", mode, compact=True)' in SOURCE
    assert '_chrome_copy("appearance.font.regex.help", mode)' in SOURCE
    assert 'sample=_chrome_copy("sample.font", self._prefs.language_mode)' in SOURCE
    assert "query[:4096]" in SOURCE


def test_appearance_preset_search_has_adjacent_builder_and_bounds():
    assert '_chrome_copy("appearance.presets.regex.help", mode)' in SOURCE
    assert 'sample=_chrome_copy("sample.preset", self._prefs.language_mode)' in SOURCE
    assert "_preset_search_flags" in SOURCE
