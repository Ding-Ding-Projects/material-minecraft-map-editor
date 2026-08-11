from pathlib import Path


def test_preferences_search_has_adjacent_regex_builder():
    """The Settings search field carries its own anchored regex builder.

    This used to assert the literal ``wx.Button(page, label="Regex…")`` call,
    which was true before the whole dialog was redrawn in Material (see
    ``33febaf4``, which converted every button on this surface -- and every
    sibling contract test alongside it -- from a native ``wx.Button`` to
    ``studio.StudioButton``). Reverting this one button to native would
    violate the project's own zero-legacy-elements Material Design 3 rule and
    would be the only button on the page still drawn by the platform. The
    real contract -- a button labelled "Regex…", anchored beside the search
    field, bound to a handler that opens the shared builder -- is what every
    other "*_regex_builder_contract" test in this suite checks (see
    ``test_base_select_regex_builder_contract.py`` and
    ``test_search_surface_regex_builder_contract.py``, both of which look for
    ``label="Regex…"`` rather than a ``wx.Button`` literal), so this test is
    brought in line with that established pattern rather than the code being
    reverted to satisfy a stale literal.
    """
    source = Path("amulet_map_editor/api/wx/ui/preferences.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def _build_search_tab")
    end = source.index("    def _validate_regex", start)
    block = source[start:end]
    assert "self.regex_button = studio.StudioButton(" in block
    assert 'label="Regex…"' in block
    assert "search_row.add_extra(self.regex_button)" in block
    assert (
        "self.regex_button.Bind(wx.EVT_BUTTON, self._open_search_regex_builder)"
        in block
    )
    assert "def _open_search_regex_builder" in block
