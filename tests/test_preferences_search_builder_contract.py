from pathlib import Path


def test_preferences_search_has_adjacent_regex_builder():
    source = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def _build_search_tab")
    end = source.index("    def _validate_regex", start)
    block = source[start:end]
    assert "self.regex_button = wx.Button(" in block
    assert '"builder", mode, bilingual_separator="\\n"' in block
    assert "self.regex_button.SetName(settings_search.localized_copy" in block
    assert (
        "self.regex_button.Bind(wx.EVT_BUTTON, self._open_search_regex_builder)"
        in block
    )
    assert "def _open_search_regex_builder" in block
