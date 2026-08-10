from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")


def test_command_palette_search_has_adjacent_builder_and_bounded_flags():
    assert "Command palette regex builder" in SOURCE
    assert 'label="Regex…"' in SOURCE
    assert 'sample="Command, feature, or setting name"' in SOURCE
    assert "flags=self._search_flags" in SOURCE
    assert "self.query.GetValue()[:4096]" in SOURCE


def test_changelog_search_has_adjacent_builder_and_bounded_flags():
    assert "Changelog search regex builder" in SOURCE
    assert 'sample="Version, release note, or commit SHA"' in SOURCE
    assert "text=self.query.GetValue()[:4096]" in SOURCE
