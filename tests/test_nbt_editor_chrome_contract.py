from pathlib import Path


SOURCE = Path("amulet_map_editor/api/wx/ui/nbt_editor.py").read_text(
    encoding="utf-8"
)


def test_nbt_editor_starts_borderless_for_shared_material_frame_chrome():
    assert "style=wx.NO_BORDER | wx.RESIZE_BORDER" in SOURCE
    assert "apply_material3(self)" in SOURCE


def test_nbt_editor_keeps_real_edit_and_close_actions():
    assert "self.save_button.Bind(wx.EVT_BUTTON, self.save)" in SOURCE
    assert "self.cancel_button.Bind(wx.EVT_BUTTON, lambda evt: self.Close())" in SOURCE
