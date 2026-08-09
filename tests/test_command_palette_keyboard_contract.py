from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_native_command_palette_has_roving_keyboard_result_controls():
    source = (ROOT / "amulet_map_editor/api/wx/ui/preferences.py").read_text(encoding="utf-8")
    assert "self.results.Bind(wx.EVT_KEY_DOWN, self._on_result_key)" in source
    assert "wx.WXK_DOWN" in source
    assert "wx.WXK_UP" in source
    assert "wx.WXK_HOME" in source
    assert "wx.WXK_END" in source
    assert "wx.WXK_RETURN" in source
