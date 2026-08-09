from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/ui/regex_dialog.py").read_text(encoding="utf-8")


def test_regex_dialog_has_guided_full_builder_and_live_capture_feedback():
    for part in (
        '"literal"',
        '"class"',
        '"start"',
        '"end"',
        '"group"',
        '"alternation"',
        '"zero-or-more"',
        '"one-or-more"',
        '"optional"',
        '"repeat"',
    ):
        assert part in SOURCE
    assert "Regex live matches and capture groups" in SOURCE
    assert "result.groups" in SOURCE
    assert "Copy pattern" in SOURCE
    assert "Python re" in SOURCE


def test_regex_dialog_accepts_call_site_sample_and_is_narrow_responsive():
    assert 'sample: str = ""' in SOURCE
    assert "wx.ScrolledWindow(self, style=wx.VSCROLL)" in SOURCE
    assert SOURCE.count("wx.BoxSizer(wx.VERTICAL)") >= 4
    assert "wx.WrapSizer(wx.HORIZONTAL)" not in SOURCE
    assert "self.SetMinSize(wx.Size(320, 380))" in SOURCE
    assert "from wx.lib.wordwrap import wordwrap" in SOURCE
    assert "(self.heading, self._heading_text)" in SOURCE
    assert "(self.description, self._description_text)" in SOURCE
    assert "wordwrap(text, width, dc, breakLongWords=True)" in SOURCE
    assert "control.SetMinSize(wx.Size(1, best.height + 12))" in SOURCE
    assert "control.InvalidateBestSize()" in SOURCE
    assert "wx.CallAfter(self._apply_material_and_reflow)" in SOURCE
    assert "apply_material3(self)\n        self._reflow()" in SOURCE
    assert SOURCE.index("self._content.Layout()") < SOURCE.index(
        "self._content.FitInside()", SOURCE.index("def _reflow")
    )
