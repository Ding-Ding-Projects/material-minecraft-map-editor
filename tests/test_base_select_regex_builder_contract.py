from pathlib import Path

BASE = Path("amulet_map_editor/api/wx/ui/base_select.py").read_text(encoding="utf-8")
DIALOG = Path("amulet_map_editor/api/wx/ui/regex_dialog.py").read_text(encoding="utf-8")


def test_base_select_has_adjacent_regex_builder_and_bounded_search():
    assert "RegexBuilderDialog" in BASE
    assert 'label="Regex…"' in BASE
    assert "RegexBuilder(" in BASE
    assert "search_str[:4096]" in BASE


def test_regex_builder_dialog_is_m3_styled_and_validates_samples():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in DIALOG
    assert "apply_material3(self)" in DIALOG
    assert ".evaluate(" in DIALOG
    assert ".validate()" in DIALOG
