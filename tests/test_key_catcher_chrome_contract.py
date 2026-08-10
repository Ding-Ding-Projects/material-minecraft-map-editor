from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/util/key_config.py").read_text(encoding="utf-8")


def test_key_catcher_starts_borderless_and_uses_m3_helper():
    assert "wx.DEFAULT_DIALOG_STYLE" not in SOURCE
    assert "style=wx.NO_BORDER | wx.WANTS_CHARS" in SOURCE
    assert "apply_material3(self)" in SOURCE


def test_key_catcher_retains_input_bindings_and_modal_result():
    assert "panel.Bind(wx.EVT_KEY_DOWN, self._on_key)" in SOURCE
    assert "panel.Bind(wx.EVT_LEFT_DOWN, self._on_key)" in SOURCE
    assert "self.EndModal(1)" in SOURCE
