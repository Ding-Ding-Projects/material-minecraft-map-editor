from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")


def test_command_palette_search_has_adjacent_builder_and_bounded_flags():
    assert "Command palette regex builder" in SOURCE
    assert '_chrome_copy("appearance.regex.button", self._language_mode)' in SOURCE
    assert 'sample=_chrome_copy("sample.command", self._language_mode)' in SOURCE
    assert "flags=self._search_flags" in SOURCE
    assert "self.query.GetValue()[:4096]" in SOURCE


def test_changelog_search_has_adjacent_builder_and_bounded_flags():
    assert "Changelog search regex builder" in SOURCE
    assert 'sample=_chrome_copy("sample.changelog", self._language_mode)' in SOURCE
    assert "text=self.query.GetValue()[:4096]" in SOURCE
